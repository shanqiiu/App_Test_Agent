"""
API客户端模块

提供统一的API客户端接口,支持多个文生图API提供商
"""

import base64
import time
import requests
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


logger = logging.getLogger("model_api_spike")


class APIError(Exception):
    """API调用错误"""
    pass


class APIClient(ABC):
    """API客户端基类"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化API客户端

        Args:
            config: provider配置字典
        """
        self.api_key = config["api_key"]
        self.api_url = config["api_url"]
        self.model = config["model"]
        self.default_params = config.get("default_params", {})
        self.cost_per_image = config.get("cost_per_image", 0.0)

    @abstractmethod
    def generate_image(self, prompt: str, **kwargs) -> bytes:
        """
        生成图像

        Args:
            prompt: 文本提示词
            **kwargs: 其他生成参数

        Returns:
            图像二进制数据

        Raises:
            APIError: API调用失败
        """
        pass

    def _make_request(
        self,
        url: str,
        headers: Dict[str, str],
        json_data: Dict[str, Any],
        timeout: int = 60,
        max_retries: int = 1
    ) -> requests.Response:
        """
        发送HTTP请求(带重试)

        Args:
            url: 请求URL
            headers: 请求头
            json_data: JSON数据
            timeout: 超时时间(秒)
            max_retries: 最大重试次数

        Returns:
            Response对象

        Raises:
            APIError: 请求失败
        """
        for attempt in range(max_retries + 1):
            try:
                logger.debug(f"Making request to {url} (attempt {attempt + 1}/{max_retries + 1})")
                response = requests.post(
                    url,
                    headers=headers,
                    json=json_data,
                    timeout=timeout,
                    verify=False  # 注意：生产环境应该启用SSL验证
                )
                response.raise_for_status()
                return response

            except requests.exceptions.Timeout:
                if attempt < max_retries:
                    logger.warning(f"Request timeout, retrying... ({attempt + 1}/{max_retries})")
                    time.sleep(2)
                else:
                    raise APIError(f"Request timed out after {timeout}s")

            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code
                error_msg = f"HTTP {status_code}: {e.response.text[:200]}"

                if status_code == 401:
                    raise APIError("Authentication failed. Check your API key.")
                elif status_code == 429:
                    raise APIError("Rate limit exceeded. Please try again later.")
                elif status_code >= 500:
                    if attempt < max_retries:
                        logger.warning(f"Server error, retrying... ({attempt + 1}/{max_retries})")
                        time.sleep(2)
                    else:
                        raise APIError(f"Server error: {error_msg}")
                else:
                    raise APIError(error_msg)

            except requests.exceptions.ConnectionError as e:
                raise APIError(f"Connection error: {str(e)}")

            except Exception as e:
                raise APIError(f"Unexpected error: {str(e)}")

        raise APIError("Max retries exceeded")


class FluxClient(APIClient):
    """Flux API客户端"""

    def generate_image(self, prompt: str, **kwargs) -> bytes:
        """
        使用Flux API生成图像

        Args:
            prompt: 文本提示词
            **kwargs: 覆盖默认参数

        Returns:
            图像二进制数据
        """
        # 合并默认参数和自定义参数
        params = {**self.default_params, **kwargs}

        # 构建请求数据
        json_data = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "negative_prompt": "",
            "width": params.get("width", 450),
            "height": params.get("height", 807),
            "num_inference_steps": params.get("num_inference_steps", 10),
            "true_cfg_scale": params.get("true_cfg_scale", 4.0),
            "seed": params.get("seed")
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        logger.debug(f"Flux API request: model={self.model}, size={json_data['width']}x{json_data['height']}")

        # 发送请求
        response = self._make_request(self.api_url, headers, json_data)

        # 解析响应
        try:
            response_data = response.json()
            base64_data = response_data["choices"][0]["message"]["content"]
            image_data = base64.b64decode(base64_data)
            logger.info(f"Flux API generated image: {len(image_data)} bytes")
            return image_data
        except (KeyError, IndexError) as e:
            raise APIError(f"Invalid response format: {e}")
        except Exception as e:
            raise APIError(f"Failed to decode image: {e}")


class QwenClient(APIClient):
    """Qwen Image API客户端"""

    def generate_image(self, prompt: str, **kwargs) -> bytes:
        """
        使用Qwen API生成图像

        Args:
            prompt: 文本提示词
            **kwargs: 覆盖默认参数

        Returns:
            图像二进制数据
        """
        # 合并默认参数和自定义参数
        params = {**self.default_params, **kwargs}

        # 构建请求数据(Qwen格式)
        json_data = {
            "model": self.model,
            "input": {
                "prompt": prompt
            },
            "parameters": {
                "size": f"{params.get('width', 512)}*{params.get('height', 768)}",
                "n": 1,
                "seed": params.get("seed"),
                "steps": params.get("steps", 20)
            }
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable"  # Qwen可能需要异步模式
        }

        logger.debug(f"Qwen API request: model={self.model}, size={json_data['parameters']['size']}")

        # 发送请求
        response = self._make_request(self.api_url, headers, json_data)

        # 解析响应(Qwen可能返回URL或base64)
        try:
            response_data = response.json()

            # 检查是否是异步任务
            if "output" in response_data and "task_id" in response_data["output"]:
                # 异步模式：需要轮询结果
                task_id = response_data["output"]["task_id"]
                logger.info(f"Qwen returned async task: {task_id}")
                # 简化处理：这里假设同步模式,实际使用可能需要轮询
                raise APIError("Async mode not yet supported")

            # 同步模式：直接获取图像
            if "output" in response_data and "results" in response_data["output"]:
                result = response_data["output"]["results"][0]
                if "url" in result:
                    # URL模式：下载图像
                    image_url = result["url"]
                    img_response = requests.get(image_url, timeout=30)
                    img_response.raise_for_status()
                    image_data = img_response.content
                elif "b64_image" in result:
                    # Base64模式：直接解码
                    image_data = base64.b64decode(result["b64_image"])
                else:
                    raise APIError("No image data in response")

                logger.info(f"Qwen API generated image: {len(image_data)} bytes")
                return image_data

            raise APIError("Invalid Qwen response format")

        except (KeyError, IndexError) as e:
            raise APIError(f"Invalid response format: {e}")
        except Exception as e:
            raise APIError(f"Failed to process Qwen response: {e}")


def create_client(provider_name: str, provider_config: Dict[str, Any]) -> APIClient:
    """
    工厂方法：创建API客户端

    Args:
        provider_name: provider名称(flux, qwen)
        provider_config: provider配置字典

    Returns:
        对应的APIClient实例

    Raises:
        ValueError: 不支持的provider
    """
    clients = {
        "flux": FluxClient,
        "qwen": QwenClient
    }

    if provider_name not in clients:
        available = ", ".join(clients.keys())
        raise ValueError(
            f"Unsupported provider: {provider_name}. "
            f"Available providers: {available}"
        )

    logger.info(f"Creating {provider_name} API client")
    return clients[provider_name](provider_config)
