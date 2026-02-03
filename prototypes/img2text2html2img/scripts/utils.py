"""
utils.py - 公共工具函数

包含：
- retry_with_backoff: 带指数退避的重试装饰器
- get_api_key: 获取 API 密钥（优先环境变量）
"""

import os
import time
import functools
from typing import Callable, List, Optional, Type, Tuple


# 默认重试延迟（指数退避）
DEFAULT_RETRY_DELAYS = [5, 10, 20, 30, 60]

# 可重试的 HTTP 状态码
RETRYABLE_STATUS_CODES = {500, 502, 503, 504, 524}


def retry_with_backoff(
    max_retries: int = 5,
    retry_delays: List[int] = None,
    retryable_exceptions: Tuple[Type[Exception], ...] = None,
    retryable_status_codes: set = None,
    verbose: bool = True
) -> Callable:
    """
    带指数退避的重试装饰器

    Args:
        max_retries: 最大重试次数
        retry_delays: 每次重试的延迟列表（秒）
        retryable_exceptions: 可重试的异常类型
        retryable_status_codes: 可重试的 HTTP 状态码
        verbose: 是否打印重试信息

    Usage:
        @retry_with_backoff(max_retries=3)
        def call_api():
            ...
    """
    if retry_delays is None:
        retry_delays = DEFAULT_RETRY_DELAYS
    if retryable_status_codes is None:
        retryable_status_codes = RETRYABLE_STATUS_CODES

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import requests

            last_exception = None

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except requests.exceptions.HTTPError as e:
                    last_exception = e
                    status_code = e.response.status_code if e.response is not None else 0
                    if status_code in retryable_status_codes and attempt < max_retries - 1:
                        delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                        if verbose:
                            print(f"  [RETRY {attempt+1}/{max_retries}] HTTP {status_code}，{delay}s 后重试...")
                        time.sleep(delay)
                    else:
                        raise
                except (requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout,
                        requests.exceptions.ProxyError) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                        if verbose:
                            print(f"  [RETRY {attempt+1}/{max_retries}] 网络错误，{delay}s 后重试...")
                        time.sleep(delay)
                    else:
                        raise
                except Exception as e:
                    # 其他异常不重试
                    raise

            # 如果循环结束仍未成功，抛出最后一个异常
            if last_exception:
                raise last_exception

        return wrapper
    return decorator


def get_api_key(env_var: str = "API_KEY", default: str = None) -> str:
    """
    获取 API 密钥

    优先级：
    1. 环境变量
    2. 默认值（仅用于开发测试）

    Args:
        env_var: 环境变量名
        default: 默认值

    Returns:
        API 密钥字符串
    """
    key = os.environ.get(env_var)
    if key:
        return key
    if default:
        return default
    raise ValueError(f"未设置 API 密钥。请设置环境变量 {env_var}")


def get_api_config() -> dict:
    """
    获取 API 配置

    Returns:
        包含 api_key 和 api_url 的字典
    """
    return {
        "api_key": get_api_key("API_KEY", os.environ.get("VLM_API_KEY")),
        "api_url": os.environ.get("API_URL", "https://api.openai-next.com/v1/chat/completions")
    }
