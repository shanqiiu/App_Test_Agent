"""
VLM 质量验证器

在异常生成后，通过 VLM 评估生成图像的质量。
支持重试机制，验证不通过时自动重试生成。
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from app.utils.common import encode_image, get_mime_type
from .verification_prompts import build_verification_prompt, get_expected_scenario


# 验证通过阈值
DEFAULT_QUALITY_THRESHOLD = 6.0  # quality_score >= 6 才算通过
DEFAULT_MAX_RETRIES = 2  # 最多重试 2 次（第 1 次生成 + 1 次重试）


class QualityVerifier:
    """
    VLM 质量验证器

    职责：
    1. 调用 VLM 评估生成图像的质量
    2. 解析验证结果（JSON 格式）
    3. 支持重试机制（验证不通过时重新生成）
    """

    def __init__(
        self,
        api_key: str = None,
        api_url: str = None,
        model: str = None,
        quality_threshold: float = DEFAULT_QUALITY_THRESHOLD,
        max_retries: int = DEFAULT_MAX_RETRIES
    ):
        """
        初始化质量验证器

        Args:
            api_key: VLM API 密钥，默认从环境变量读取
            api_url: VLM API URL，默认从环境变量读取
            model: VLM 模型名称，默认从环境变量读取
            quality_threshold: 质量阈值，quality_score >= threshold 才算通过
            max_retries: 最大重试次数
        """
        self.api_key = api_key or os.getenv('VLM_API_KEY')
        self.api_url = api_url or os.getenv(
            'VLM_API_URL',
            'http://mlops.huawei.com/mlops-service/api/v2/agentService/v1/chat/completions'
        )
        self.model = model or os.getenv('VLM_MODEL', 'qwen35-9b-vl')
        self.quality_threshold = quality_threshold
        self.max_retries = max_retries

        if not self.api_key:
            raise ValueError("VLM_API_KEY 环境变量未设置")

    def verify(
        self,
        base_screenshot: Path,
        generated_images: List[Path],
        anomaly_type: str,
        instruction: str,
        return_all_attempts: bool = False
    ) -> Dict:
        """
        验证生成的异常图像质量

        Args:
            base_screenshot: 原始截图路径（无异常）
            generated_images: 生成的异常图像路径列表
            anomaly_type: 异常类型
            instruction: 生成指令
            return_all_attempts: 是否返回所有尝试的结果

        Returns:
            {
                "passed": bool,
                "quality_score": float,
                "dimensions": {...},
                "issues": [...],
                "reasoning": str,
                "attempts": int,  # 总尝试次数
                "retry_count": int,  # 重试次数
                "all_results": [...]  # 可选，所有尝试的结果
            }
        """
        if not generated_images:
            return {
                "passed": False,
                "quality_score": 0.0,
                "dimensions": {},
                "issues": ["生成的异常图像列表为空"],
                "reasoning": "无法验证空图像列表",
                "attempts": 0,
                "retry_count": 0,
                "all_results": []
            }

        all_results = []
        retry_count = 0

        # 使用第一张生成的图像进行验证（如果有多张）
        primary_image = generated_images[0]

        for attempt in range(self.max_retries + 1):
            print(f"\n  [{attempt + 1}/{self.max_retries + 1}] VLM 质量验证...")

            result = self._single_verification(
                base_screenshot=base_screenshot,
                generated_image=primary_image,
                anomaly_type=anomaly_type,
                instruction=instruction,
                retry_count=attempt,
                prev_result=all_results[-1] if all_results else None
            )

            all_results.append(result)

            # 判断是否通过
            if result["passed"]:
                print(f"    ✓ 验证通过 (score={result['quality_score']:.1f})")
                return self._build_final_result(
                    result=result,
                    attempts=attempt + 1,
                    retry_count=retry_count,
                    all_results=all_results if return_all_attempts else None
                )
            else:
                print(f"    ✗ 验证未通过 (score={result['quality_score']:.1f})")
                print(f"    issues: {result.get('issues', [])}")
                retry_count += 1

        # 所有重试都失败，返回最后一次结果
        final_result = all_results[-1]
        print(f"\n  ⚠ 质量验证未通过，最终得分: {final_result['quality_score']:.1f}")

        return self._build_final_result(
            result=final_result,
            attempts=self.max_retries + 1,
            retry_count=retry_count,
            all_results=all_results if return_all_attempts else None
        )

    def _single_verification(
        self,
        base_screenshot: Path,
        generated_image: Path,
        anomaly_type: str,
        instruction: str,
        retry_count: int = 0,
        prev_result: Dict = None
    ) -> Dict:
        """
        单次 VLM 验证调用

        Args:
            base_screenshot: 原始截图路径
            generated_image: 生成的异常图像路径
            anomaly_type: 异常类型
            instruction: 生成指令
            retry_count: 当前是第几次尝试
            prev_result: 上一次验证结果

        Returns:
            单次验证结果
        """
        # 构建 prompt
        prompt = build_verification_prompt(
            anomaly_type=anomaly_type,
            instruction=instruction,
            retry_count=retry_count,
            prev_result=prev_result
        )

        # 调用 VLM
        response = self._call_vlm(
            base_screenshot=base_screenshot,
            generated_image=generated_image,
            prompt=prompt
        )

        # 解析响应
        return self._parse_verification_response(response)

    def _call_vlm(
        self,
        base_screenshot: Path,
        generated_image: Path,
        prompt: str,
        max_retries: int = 3
    ) -> str:
        """
        调用 VLM API

        Args:
            base_screenshot: 原始截图路径
            generated_image: 生成的异常图像路径
            prompt: 验证 prompt
            max_retries: 最大重试次数

        Returns:
            VLM 响应文本
        """
        base_screenshot = Path(base_screenshot)
        generated_image = Path(generated_image)

        if not base_screenshot.exists():
            raise FileNotFoundError(f"原始截图不存在: {base_screenshot}")
        if not generated_image.exists():
            raise FileNotFoundError(f"生成的异常截图不存在: {generated_image}")

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }

        # 编码图片
        base64_image = encode_image(str(base_screenshot))
        generated_b64 = encode_image(str(generated_image))

        base_mime = get_mime_type(str(base_screenshot))
        gen_mime = get_mime_type(str(generated_image))

        # 构建消息内容（两张图片）
        content = [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{base_mime};base64,{base64_image}"
                }
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{gen_mime};base64,{generated_b64}"
                }
            },
            {
                "type": "text",
                "text": prompt
            }
        ]

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": content
                }
            ],
            "temperature": 0.0,  # 确定性输出
            "max_tokens": 2048
        }

        base_wait = 5
        last_error = None

        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    wait_time = min(base_wait * (2 ** (attempt - 1)), 60)
                    print(f"      ⏳ 等待 {wait_time}s 后重试 ({attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)

                response = requests.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=180
                )

                if response.status_code == 429:
                    print(f"      ⚠ API 限流 (429)，准备重试...")
                    last_error = "API 限流 (429)"
                    continue
                elif response.status_code >= 500:
                    print(f"      ⚠ 服务器错误 ({response.status_code})，准备重试...")
                    last_error = f"服务器错误 ({response.status_code})"
                    continue

                response.raise_for_status()
                result = response.json()
                return result['choices'][0]['message']['content']

            except requests.exceptions.RequestException as e:
                print(f"      ⚠ VLM 请求失败: {e}")
                last_error = str(e)
                if attempt == max_retries - 1:
                    raise

        raise Exception(f"VLM 调用失败，已重试 {max_retries} 次。最后错误: {last_error}")

    def _parse_verification_response(self, response: str) -> Dict:
        """
        解析 VLM 验证响应

        Args:
            response: VLM 原始响应

        Returns:
            解析后的验证结果
        """
        # 方法 1：尝试提取 <result>...</result> 标签内容
        json_str = None
        result_match = re.search(r'<result>\s*(\{[\s\S]*?\})\s*</result>', response)
        if result_match:
            candidate = result_match.group(1).strip()
            if candidate:
                json_str = candidate

        # 方法 2：尝试直接找 JSON 对象
        if not json_str:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                json_str = json_match.group(0)

        # 方法 3：尝试找 ```json ... ``` 块
        if not json_str:
            json_block_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', response)
            if json_block_match:
                json_str = json_block_match.group(1)

        if not json_str:
            print(f"    ⚠ 无法从响应中提取 JSON")
            print(f"    响应前200字符: {response[:200]}")
            return self._fallback_parse(response)

        try:
            data = json.loads(json_str)

            # 验证通过判断
            passed = (
                data.get("dimensions", {}).get("anomaly_present", False)
                and data.get("dimensions", {}).get("semantic_match", False)
                and data.get("quality_score", 0) >= self.quality_threshold
            )

            return {
                "passed": passed,
                "quality_score": float(data.get("quality_score", 0)),
                "dimensions": {
                    "anomaly_present": bool(data.get("dimensions", {}).get("anomaly_present", False)),
                    "anomaly_present_score": float(data.get("dimensions", {}).get("anomaly_present_score", 0)),
                    "semantic_match": bool(data.get("dimensions", {}).get("semantic_match", False)),
                    "semantic_match_score": float(data.get("dimensions", {}).get("semantic_match_score", 0)),
                    "visual_quality": float(data.get("dimensions", {}).get("visual_quality", 0)),
                    "naturalness": float(data.get("dimensions", {}).get("naturalness", 0))
                },
                "issues": data.get("issues", []),
                "reasoning": data.get("reasoning", "")
            }

        except json.JSONDecodeError as e:
            print(f"    ⚠ JSON 解析失败: {e}")
            print(f"    提取的 JSON: {json_str[:200] if json_str else 'N/A'}")
            # 回退：尝试从文本中提取关键信息
            return self._fallback_parse(response)

    def _fallback_parse(self, response: str) -> Dict:
        """
        回退解析：当 JSON 解析失败时

        Args:
            response: VLM 原始响应

        Returns:
            基于文本推断的验证结果
        """
        response_lower = response.lower()

        # 推断 passed
        passed_keywords = ["passed", "通过", "合格", "true", "符合要求"]
        failed_keywords = ["未通过", "不合格", "false", "不符合", "failed", "问题"]

        passed = any(kw in response_lower for kw in passed_keywords)
        failed = any(kw in response_lower for kw in failed_keywords)

        # 推断 quality_score
        score_match = re.search(r'quality[_\s]?score[:\s]*(\d+\.?\d*)', response_lower)
        score = float(score_match.group(1)) if score_match else 5.0

        # 推断 anomaly_present
        anomaly_present = (
            "anomaly_present" in response_lower
            or "异常存在" in response
            or "异常已注入" in response
        )

        return {
            "passed": passed and not failed,
            "quality_score": score,
            "dimensions": {
                "anomaly_present": anomaly_present,
                "anomaly_present_score": 5.0,
                "semantic_match": True,
                "semantic_match_score": 5.0,
                "visual_quality": 5.0,
                "naturalness": 5.0
            },
            "issues": ["JSON 解析失败，使用文本推断结果"] if not passed else [],
            "reasoning": f"回退解析结果: passed={passed}, score={score}"
        }

    def _build_final_result(
        self,
        result: Dict,
        attempts: int,
        retry_count: int,
        all_results: List[Dict] = None
    ) -> Dict:
        """构建最终结果"""
        final = {
            "passed": result["passed"],
            "quality_score": result["quality_score"],
            "dimensions": result["dimensions"],
            "issues": result["issues"],
            "reasoning": result["reasoning"],
            "attempts": attempts,
            "retry_count": retry_count
        }

        if all_results:
            final["all_results"] = all_results

        return final


class VerificationResult:
    """验证结果数据类（便捷访问）"""

    def __init__(self, result: Dict):
        self._result = result

    @property
    def passed(self) -> bool:
        return self._result.get("passed", False)

    @property
    def quality_score(self) -> float:
        return self._result.get("quality_score", 0.0)

    @property
    def anomaly_present(self) -> bool:
        return self._result.get("dimensions", {}).get("anomaly_present", False)

    @property
    def semantic_match(self) -> bool:
        return self._result.get("dimensions", {}).get("semantic_match", False)

    @property
    def visual_quality(self) -> float:
        return self._result.get("dimensions", {}).get("visual_quality", 0.0)

    @property
    def naturalness(self) -> float:
        return self._result.get("dimensions", {}).get("naturalness", 0.0)

    @property
    def issues(self) -> List[str]:
        return self._result.get("issues", [])

    @property
    def reasoning(self) -> str:
        return self._result.get("reasoning", "")

    @property
    def retry_count(self) -> int:
        return self._result.get("retry_count", 0)

    def summary(self) -> str:
        """生成简洁的总结"""
        status = "✓ 通过" if self.passed else "✗ 未通过"
        return (
            f"[{status}] score={self.quality_score:.1f}, "
            f"anomaly={self.anomaly_present}, "
            f"retry={self.retry_count}"
        )
