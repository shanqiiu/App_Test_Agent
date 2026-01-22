"""
文本润色器模块

调用LLM API对输入文本进行润色优化
"""

import json
import logging
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

from .cost_tracker import CostTracker
from .utils import ensure_dir, get_timestamp


logger = logging.getLogger("model_api_spike")


class TextRefineError(Exception):
    """文本润色错误"""
    pass


class TextRefiner:
    """文本润色器"""

    DEFAULT_SYSTEM_PROMPT = """你是一位专业的文字编辑，擅长润色和优化文本。
请对用户提供的文本进行润色，要求：
1. 保持原文的核心意思不变
2. 提升文字的流畅度和可读性
3. 修正语法和标点错误
4. 优化用词，使表达更加精准
5. 保持原文的语气和风格

直接输出润色后的文本，不要添加任何解释或说明。"""

    def __init__(
        self,
        api_key: str,
        api_url: str,
        model: str,
        cost_tracker: Optional[CostTracker] = None,
        output_config: Optional[Dict[str, str]] = None,
        cost_per_request: float = 0.0
    ):
        """
        初始化文本润色器

        Args:
            api_key: API密钥
            api_url: API端点URL
            model: 模型名称
            cost_tracker: 成本追踪器实例(可选)
            output_config: 输出配置(目录路径等)
            cost_per_request: 每次请求的估算成本
        """
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
        self.cost_tracker = cost_tracker
        self.output_config = output_config or {}
        self.cost_per_request = cost_per_request

        # 确保输出目录存在
        if output_config:
            ensure_dir(output_config.get("text_dir", "outputs/texts"))
            ensure_dir(output_config.get("report_dir", "outputs/reports"))

    def refine(
        self,
        text: str,
        system_prompt: Optional[str] = None,
        task_id: str = "default",
        save_result: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        润色单个文本

        Args:
            text: 待润色的文本
            system_prompt: 自定义系统提示词(可选)
            task_id: 任务ID
            save_result: 是否保存结果
            **kwargs: 额外的API参数

        Returns:
            润色结果字典
        """
        logger.info(f"Refining text for task: {task_id}")
        logger.debug(f"Input text: {text[:100]}...")

        start_time = time.time()

        try:
            # 调用API
            refined_text = self._call_api(
                text,
                system_prompt or self.DEFAULT_SYSTEM_PROMPT,
                **kwargs
            )

            generation_time = time.time() - start_time

            # 记录成本
            if self.cost_tracker:
                self.cost_tracker.record(
                    provider=self.model,
                    cost=self.cost_per_request,
                    scenario_id=task_id,
                    generation_time=generation_time,
                    metadata={
                        "input_length": len(text),
                        "output_length": len(refined_text)
                    }
                )

            result = {
                "task_id": task_id,
                "success": True,
                "input_text": text,
                "refined_text": refined_text,
                "generation_time": round(generation_time, 2),
                "cost": self.cost_per_request,
                "timestamp": datetime.now().isoformat()
            }

            # 保存结果
            if save_result:
                file_info = self._save_result(task_id, result)
                result.update(file_info)

            logger.info(
                f"Refined {task_id} in {generation_time:.2f}s "
                f"(cost: ${self.cost_per_request:.4f})"
            )

            return result

        except TextRefineError as e:
            logger.error(f"Failed to refine {task_id}: {e}")
            generation_time = time.time() - start_time

            return {
                "task_id": task_id,
                "success": False,
                "input_text": text,
                "error": str(e),
                "generation_time": round(generation_time, 2),
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Unexpected error for {task_id}: {e}")
            generation_time = time.time() - start_time

            return {
                "task_id": task_id,
                "success": False,
                "input_text": text,
                "error": f"Unexpected error: {str(e)}",
                "generation_time": round(generation_time, 2),
                "timestamp": datetime.now().isoformat()
            }

    def refine_batch(
        self,
        texts: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        批量润色文本

        Args:
            texts: 文本列表，每项包含id和text字段
            system_prompt: 自定义系统提示词(可选)
            **kwargs: 额外的API参数

        Returns:
            润色结果列表
        """
        results = []
        total = len(texts)

        logger.info(f"Starting batch refinement: {total} texts")
        print(f"\nRefining {total} texts...")
        print("-" * 60)

        for i, item in enumerate(texts, 1):
            task_id = item.get("id", f"text_{i}")
            text = item["text"]

            print(f"[{i}/{total}] Processing {task_id}")

            result = self.refine(
                text,
                system_prompt=system_prompt,
                task_id=task_id,
                save_result=True,
                **kwargs
            )
            results.append(result)

            if result["success"]:
                print(f"  Refined in {result['generation_time']:.2f}s")
                print(f"  Cost: ${result['cost']:.4f}")
            else:
                print(f"  Failed: {result['error']}")

        print("-" * 60)

        success_count = sum(1 for r in results if r["success"])
        logger.info(f"Batch refinement completed: {success_count}/{total} succeeded")

        return results

    def _call_api(
        self,
        text: str,
        system_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: int = 60
    ) -> str:
        """
        调用LLM API

        Args:
            text: 用户输入文本
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大token数
            timeout: 超时时间(秒)

        Returns:
            生成的文本

        Raises:
            TextRefineError: API调用失败
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        json_data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        logger.debug(f"Calling API: {self.api_url}, model={self.model}")

        try:
            response = requests.post(
                self.api_url,
                headers=headers,
                json=json_data,
                timeout=timeout,
                verify=False
            )
            response.raise_for_status()

            response_data = response.json()
            refined_text = response_data["choices"][0]["message"]["content"]

            return refined_text.strip()

        except requests.exceptions.Timeout:
            raise TextRefineError(f"Request timed out after {timeout}s")

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code
            error_msg = e.response.text[:200]

            if status_code == 401:
                raise TextRefineError("Authentication failed. Check your API key.")
            elif status_code == 429:
                raise TextRefineError("Rate limit exceeded. Please try again later.")
            else:
                raise TextRefineError(f"HTTP {status_code}: {error_msg}")

        except requests.exceptions.ConnectionError as e:
            raise TextRefineError(f"Connection error: {str(e)}")

        except (KeyError, IndexError) as e:
            raise TextRefineError(f"Invalid response format: {e}")

        except Exception as e:
            raise TextRefineError(f"Unexpected error: {str(e)}")

    def _save_result(
        self,
        task_id: str,
        result: Dict[str, Any]
    ) -> Dict[str, str]:
        """
        保存润色结果

        Args:
            task_id: 任务ID
            result: 润色结果

        Returns:
            文件路径字典
        """
        text_dir = Path(self.output_config.get("text_dir", "outputs/texts"))
        ensure_dir(str(text_dir))

        # 保存结果JSON
        output_path = text_dir / f"{task_id}.json"

        save_data = {
            "task_id": task_id,
            "input_text": result["input_text"],
            "refined_text": result.get("refined_text", ""),
            "success": result["success"],
            "generation_time": result["generation_time"],
            "cost": result.get("cost", 0),
            "timestamp": result["timestamp"],
            "model": self.model
        }

        if not result["success"]:
            save_data["error"] = result.get("error", "Unknown error")

        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(save_data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Result saved: {output_path}")
        except Exception as e:
            logger.error(f"Failed to save result: {e}")

        return {"output_path": str(output_path)}


def create_refiner(
    provider_config: Dict[str, Any],
    cost_tracker: Optional[CostTracker] = None,
    output_config: Optional[Dict[str, str]] = None
) -> TextRefiner:
    """
    工厂方法：创建文本润色器

    Args:
        provider_config: API配置字典
        cost_tracker: 成本追踪器
        output_config: 输出配置

    Returns:
        TextRefiner实例
    """
    refiner = TextRefiner(
        api_key=provider_config["api_key"],
        api_url=provider_config["api_url"],
        model=provider_config["model"],
        cost_tracker=cost_tracker,
        output_config=output_config,
        cost_per_request=provider_config.get("cost_per_request", 0.0)
    )

    logger.info(f"Text refiner created with model: {provider_config['model']}")

    return refiner
