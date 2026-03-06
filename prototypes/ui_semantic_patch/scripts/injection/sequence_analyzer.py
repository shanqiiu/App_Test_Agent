"""
增量式语义分析器

借鉴 UI-Venus 的上下文理解机制，实现操作序列的增量式分析，
决策在何处注入何种异常。
"""

import os
import sys
import re
import time
import requests
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# 添加 utils 目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.common import encode_image, get_mime_type
from utils.history_manager import HistoryManager, StepRecord
from .anomaly_recommender import AnomalyRecommender
from .prompts import build_injection_prompt


class SequenceAnalyzer:
    """
    增量式语义分析器

    借鉴 UI-Venus 的设计：
    - 逐步分析截图序列，累积上下文
    - 每步决策是否注入异常
    - 一旦决策 INJECT 则停止分析
    """

    def __init__(
        self,
        recommender: AnomalyRecommender,
        task_description: str,
        api_key: str = None,
        api_url: str = None,
        model: str = None,
        max_history_steps: int = 10,
        temperature: float = 0.0,
        min_steps_before_inject: int = 2
    ):
        """
        初始化语义分析器

        Args:
            recommender: 异常推荐器实例
            task_description: 任务描述（如"在携程预订酒店"）
            api_key: VLM API 密钥，默认从环境变量读取
            api_url: VLM API URL，默认从环境变量读取
            model: VLM 模型名称，默认从环境变量读取
            max_history_steps: 最大历史步数
            temperature: VLM 生成温度（0 表示确定性输出）
            min_steps_before_inject: 最少分析多少步后才考虑注入
        """
        self.recommender = recommender
        self.task_description = task_description
        self.history_manager = HistoryManager(max_history_steps)
        self.temperature = temperature
        self.min_steps_before_inject = min_steps_before_inject

        # VLM 配置
        self.api_key = api_key or os.getenv('VLM_API_KEY')
        self.api_url = api_url or os.getenv('VLM_API_URL', 'https://api.openai.com/v1/chat/completions')
        self.model = model or os.getenv('VLM_MODEL', 'gpt-4o')

        if not self.api_key:
            raise ValueError("VLM_API_KEY 环境变量未设置")

        # 获取异常类型描述
        self.gt_categories_description = recommender.get_categories_description()

    def analyze_step(
        self,
        screenshot_path: Path,
        step_index: int,
        total_steps: int
    ) -> Dict:
        """
        分析单步截图，决策是否注入异常

        Args:
            screenshot_path: 截图路径
            step_index: 当前步骤索引（从 0 开始）
            total_steps: 总步骤数

        Returns:
            {
                "decision": "INJECT" or "SKIP",
                "anomaly_type": str or None,
                "instruction": str or None,
                "think": str,
                "conclusion": str
            }
        """
        screenshot_path = Path(screenshot_path)
        if not screenshot_path.exists():
            raise FileNotFoundError(f"截图不存在: {screenshot_path}")

        # 构建提示词
        previous_steps = self.history_manager.build_history_text()
        prompt = build_injection_prompt(
            task_description=self.task_description,
            gt_categories_description=self.gt_categories_description,
            previous_steps=previous_steps,
            step_index=step_index,
            total_steps=total_steps
        )

        # 调用 VLM
        response = self._call_vlm(screenshot_path, prompt)

        # 解析响应
        result = self._parse_vlm_response(response)

        # 强制规则：前 N 步不允许注入
        if step_index < self.min_steps_before_inject and result["decision"] == "INJECT":
            print(f"  ⚠ Step {step_index}: 前 {self.min_steps_before_inject} 步强制 SKIP")
            result["decision"] = "SKIP"
            result["anomaly_type"] = None
            result["instruction"] = None

        # 记录到历史
        record = StepRecord(
            step_index=step_index,
            screenshot_path=str(screenshot_path),
            think=result["think"],
            decision=result["decision"],
            anomaly_type=result.get("anomaly_type"),
            instruction=result.get("instruction"),
            conclusion=result["conclusion"]
        )
        self.history_manager.add_record(record)

        return result

    def run(self, screenshots: List[Path]) -> Dict:
        """
        增量式分析整个截图序列

        Args:
            screenshots: 截图路径列表（按时间顺序）

        Returns:
            {
                "success": True/False,
                "injection_point": int or None,
                "anomaly_type": str or None,
                "instruction": str or None,
                "reasoning": str,
                "history": List[dict]
            }
        """
        screenshots = [Path(p) for p in screenshots]
        total_steps = len(screenshots)

        print(f"\n{'='*60}")
        print(f"开始增量式序列分析")
        print(f"任务: {self.task_description}")
        print(f"序列长度: {total_steps} 步")
        print(f"{'='*60}\n")

        for i, screenshot in enumerate(screenshots):
            print(f"\n--- Step {i}/{total_steps-1}: {screenshot.name} ---")

            result = self.analyze_step(screenshot, i, total_steps)

            print(f"  Think: {result['think'][:100]}..." if len(result['think']) > 100 else f"  Think: {result['think']}")
            print(f"  Decision: {result['decision']}")
            if result["decision"] == "INJECT":
                print(f"  Anomaly: {result['anomaly_type']}")
                print(f"  Instruction: {result['instruction']}")

            # 检查是否决策注入
            if result["decision"] == "INJECT":
                print(f"\n{'='*60}")
                print(f"✓ 找到注入点: Step {i}")
                print(f"  异常类型: {result['anomaly_type']}")
                print(f"  生成指令: {result['instruction']}")
                print(f"{'='*60}\n")

                return {
                    "success": True,
                    "injection_point": i,
                    "anomaly_type": result["anomaly_type"],
                    "instruction": result["instruction"],
                    "reasoning": result["think"],
                    "history": [r.to_dict() for r in self.history_manager.records]
                }

        # 遍历完成但未找到注入点
        print(f"\n{'='*60}")
        print(f"⚠ 未找到合适的注入点")
        print(f"{'='*60}\n")

        return {
            "success": False,
            "injection_point": None,
            "anomaly_type": None,
            "instruction": None,
            "reasoning": "遍历完整个序列，未找到语义合适的注入点",
            "history": [r.to_dict() for r in self.history_manager.records]
        }

    def _call_vlm(self, image_path: Path, prompt: str, max_retries: int = 3) -> str:
        """
        调用 VLM API

        Args:
            image_path: 图片路径
            prompt: 提示词
            max_retries: 最大重试次数

        Returns:
            VLM 响应文本
        """
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }

        # 编码图片
        image_base64 = encode_image(str(image_path))
        mime_type = get_mime_type(str(image_path))

        # 构建请求
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_base64}"
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ],
            "temperature": self.temperature,
            "max_tokens": 1024
        }

        base_wait = 5
        last_error = None

        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    wait_time = min(base_wait * (2 ** (attempt - 1)), 60)
                    print(f"  ⏳ 等待 {wait_time}s 后重试 ({attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)

                response = requests.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=180
                )

                if response.status_code == 429:
                    print(f"  ⚠ API 限流 (429)，准备重试...")
                    last_error = "API 限流 (429)"
                    continue
                elif response.status_code >= 500:
                    print(f"  ⚠ 服务器错误 ({response.status_code})，准备重试...")
                    last_error = f"服务器错误 ({response.status_code})"
                    continue

                response.raise_for_status()
                result = response.json()
                return result['choices'][0]['message']['content']

            except requests.exceptions.RequestException as e:
                print(f"  ⚠ API 请求失败: {e}")
                last_error = str(e)
                if attempt == max_retries - 1:
                    raise

        raise Exception(f"VLM 调用失败，已重试 {max_retries} 次。最后错误: {last_error}")

    def _parse_vlm_response(self, response: str) -> Dict:
        """
        解析 VLM 响应

        借鉴 UI-Venus 的 extract_tag_content() 方法

        Args:
            response: VLM 原始响应

        Returns:
            解析后的字典
        """
        def extract_tag(tag_name: str, text: str) -> str:
            """提取 XML 标签内容"""
            pattern = rf"<{tag_name}>(.*?)</{tag_name}>"
            match = re.search(pattern, text, re.DOTALL)
            return match.group(1).strip() if match else ""

        think = extract_tag("think", response)
        decision = extract_tag("decision", response).upper()
        anomaly_type = extract_tag("anomaly_type", response)
        instruction = extract_tag("instruction", response)
        conclusion = extract_tag("conclusion", response)

        # 规范化 decision
        if decision not in ["INJECT", "SKIP"]:
            # 尝试从文本中推断
            if "INJECT" in response.upper():
                decision = "INJECT"
            else:
                decision = "SKIP"

        return {
            "decision": decision,
            "anomaly_type": anomaly_type if decision == "INJECT" else None,
            "instruction": instruction if decision == "INJECT" else None,
            "think": think or response[:200],  # 如果解析失败，取前200字符
            "conclusion": conclusion or ""
        }

    def reset(self) -> None:
        """重置分析器状态"""
        self.history_manager.reset()

    def get_history(self) -> List[Dict]:
        """获取分析历史"""
        return [r.to_dict() for r in self.history_manager.records]
