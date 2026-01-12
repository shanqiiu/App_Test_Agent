"""
图像生成器模块

集成API客户端和成本追踪,提供增强的图像生成功能
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from PIL import Image
import io

from .api_client import create_client, APIClient, APIError
from .cost_tracker import CostTracker
from .utils import ensure_dir, get_timestamp


logger = logging.getLogger("model_api_spike")


class ImageGenerator:
    """图像生成器(增强版)"""

    def __init__(
        self,
        api_client: APIClient,
        cost_tracker: CostTracker,
        output_config: Dict[str, str]
    ):
        """
        初始化图像生成器

        Args:
            api_client: API客户端实例
            cost_tracker: 成本追踪器实例
            output_config: 输出配置(目录路径等)
        """
        self.client = api_client
        self.cost_tracker = cost_tracker
        self.output_config = output_config

        # 确保输出目录存在
        ensure_dir(output_config.get("image_dir", "outputs/images"))
        ensure_dir(output_config.get("metadata_dir", "outputs/metadata"))
        ensure_dir(output_config.get("report_dir", "outputs/reports"))

    def generate_single(
        self,
        scenario: Dict[str, Any],
        save_image: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        生成单张图像

        Args:
            scenario: 场景配置字典(包含id, prompt等)
            save_image: 是否保存图像
            **kwargs: 额外的生成参数

        Returns:
            生成结果字典
        """
        scenario_id = scenario["id"]
        prompt = scenario["prompt"]

        logger.info(f"Generating image for scenario: {scenario_id}")
        logger.debug(f"Prompt: {prompt[:100]}...")

        # 记录开始时间
        start_time = time.time()

        try:
            # 调用API生成图像
            image_data = self.client.generate_image(prompt, **kwargs)

            # 计算耗时
            generation_time = time.time() - start_time

            # 记录成本
            self.cost_tracker.record(
                provider=self.client.model,
                cost=self.client.cost_per_image,
                scenario_id=scenario_id,
                generation_time=generation_time,
                metadata={
                    "prompt_length": len(prompt),
                    "image_size": len(image_data)
                }
            )

            # 构建结果
            result = {
                "scenario_id": scenario_id,
                "success": True,
                "generation_time": round(generation_time, 2),
                "cost": self.client.cost_per_image,
                "image_data": image_data,
                "image_size": len(image_data),
                "timestamp": datetime.now().isoformat()
            }

            # 保存图像和元数据
            if save_image:
                file_info = self._save_result(scenario, result, image_data)
                result.update(file_info)

            logger.info(
                f"✓ Generated {scenario_id} in {generation_time:.2f}s "
                f"(cost: ${self.client.cost_per_image:.4f})"
            )

            return result

        except APIError as e:
            logger.error(f"✗ Failed to generate {scenario_id}: {e}")
            generation_time = time.time() - start_time

            return {
                "scenario_id": scenario_id,
                "success": False,
                "error": str(e),
                "generation_time": round(generation_time, 2),
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"✗ Unexpected error for {scenario_id}: {e}")
            generation_time = time.time() - start_time

            return {
                "scenario_id": scenario_id,
                "success": False,
                "error": f"Unexpected error: {str(e)}",
                "generation_time": round(generation_time, 2),
                "timestamp": datetime.now().isoformat()
            }

    def generate_batch(
        self,
        scenarios: List[Dict[str, Any]],
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        批量生成图像

        Args:
            scenarios: 场景列表
            **kwargs: 额外的生成参数

        Returns:
            生成结果列表
        """
        results = []
        total = len(scenarios)

        logger.info(f"Starting batch generation: {total} scenarios")
        print(f"\nGenerating {total} test scenarios...")
        print("-" * 60)

        for i, scenario in enumerate(scenarios, 1):
            print(f"[{i}/{total}] Processing {scenario['id']} ({scenario.get('title', 'N/A')})")

            result = self.generate_single(scenario, save_image=True, **kwargs)
            results.append(result)

            if result["success"]:
                print(f"  ✓ Generated in {result['generation_time']:.2f}s: {result.get('image_path', 'N/A')}")
                print(f"  Cost: ${result['cost']:.4f}")
            else:
                print(f"  ✗ Failed: {result['error']}")

        print("-" * 60)

        # 统计成功率
        success_count = sum(1 for r in results if r["success"])
        logger.info(f"Batch generation completed: {success_count}/{total} succeeded")

        return results

    def _save_result(
        self,
        scenario: Dict[str, Any],
        result: Dict[str, Any],
        image_data: bytes
    ) -> Dict[str, str]:
        """
        保存生成结果(图像和元数据)

        Args:
            scenario: 场景配置
            result: 生成结果
            image_data: 图像二进制数据

        Returns:
            文件路径字典
        """
        scenario_id = scenario["id"]
        provider_name = self.client.model.split("_")[0]  # flux, qwen等

        # 构建输出路径
        image_dir = Path(self.output_config.get("image_dir", "outputs/images"))
        provider_dir = image_dir / provider_name
        ensure_dir(str(provider_dir))

        metadata_dir = Path(self.output_config.get("metadata_dir", "outputs/metadata"))
        ensure_dir(str(metadata_dir))

        # 保存图像
        image_format = self.output_config.get("image_format", "png")
        image_path = provider_dir / f"{scenario_id}.{image_format}"

        try:
            with open(image_path, "wb") as f:
                f.write(image_data)
            logger.debug(f"Image saved: {image_path}")
        except Exception as e:
            logger.error(f"Failed to save image: {e}")
            raise

        # 验证图像
        try:
            img = Image.open(io.BytesIO(image_data))
            image_size = img.size
        except Exception as e:
            logger.warning(f"Failed to verify image: {e}")
            image_size = (0, 0)

        # 保存元数据
        metadata_path = metadata_dir / f"{scenario_id}.json"
        metadata = {
            "scenario": scenario,
            "generation": {
                "provider": provider_name,
                "model": self.client.model,
                "timestamp": result["timestamp"],
                "generation_time": result["generation_time"],
                "cost": result["cost"]
            },
            "image": {
                "path": str(image_path),
                "size_bytes": len(image_data),
                "dimensions": image_size,
                "format": image_format
            }
        }

        try:
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            logger.debug(f"Metadata saved: {metadata_path}")
        except Exception as e:
            logger.error(f"Failed to save metadata: {e}")

        return {
            "image_path": str(image_path),
            "metadata_path": str(metadata_path)
        }


def create_generator(
    provider_name: str,
    provider_config: Dict[str, Any],
    cost_tracker: CostTracker,
    output_config: Dict[str, str]
) -> ImageGenerator:
    """
    工厂方法：创建图像生成器

    Args:
        provider_name: API提供商名称
        provider_config: API提供商配置
        cost_tracker: 成本追踪器
        output_config: 输出配置

    Returns:
        ImageGenerator实例
    """
    # 创建API客户端
    api_client = create_client(provider_name, provider_config)

    # 创建生成器
    generator = ImageGenerator(api_client, cost_tracker, output_config)

    logger.info(f"Image generator created with {provider_name} client")

    return generator
