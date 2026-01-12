"""
工具函数模块

提供日志配置、目录创建、时间戳生成等通用功能
"""

import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional


def setup_logging(log_level: str = "INFO", log_file: Optional[str] = None) -> logging.Logger:
    """
    配置日志系统

    Args:
        log_level: 日志级别 (DEBUG, INFO, WARNING, ERROR)
        log_file: 日志文件路径(可选)

    Returns:
        配置好的logger对象
    """
    logger = logging.getLogger("model_api_spike")
    logger.setLevel(getattr(logging, log_level.upper()))

    # 避免重复添加handler
    if logger.handlers:
        return logger

    # 控制台handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # 文件handler(如果指定)
    if log_file:
        ensure_dir(os.path.dirname(log_file))
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

    return logger


def ensure_dir(directory: str) -> None:
    """
    确保目录存在,不存在则创建

    Args:
        directory: 目录路径
    """
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)


def get_timestamp(format_str: str = "%Y%m%d_%H%M%S") -> str:
    """
    生成时间戳字符串

    Args:
        format_str: 时间格式字符串

    Returns:
        格式化的时间戳
    """
    return datetime.now().strftime(format_str)


def load_env_file(env_path: str = ".env") -> None:
    """
    加载.env文件中的环境变量

    Args:
        env_path: .env文件路径
    """
    try:
        from dotenv import load_dotenv
        if os.path.exists(env_path):
            load_dotenv(env_path)
            logging.getLogger("model_api_spike").info(f"Loaded environment variables from {env_path}")
    except ImportError:
        logging.getLogger("model_api_spike").warning("python-dotenv not installed, skipping .env file loading")


def format_time(seconds: float) -> str:
    """
    格式化时间(秒)为可读字符串

    Args:
        seconds: 秒数

    Returns:
        格式化的时间字符串
    """
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.2f}s"
    else:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m{secs:.1f}s"


def format_cost(cost_usd: float) -> str:
    """
    格式化成本(美元)为可读字符串

    Args:
        cost_usd: 美元金额

    Returns:
        格式化的成本字符串
    """
    return f"${cost_usd:.4f}"


def print_separator(char: str = "=", length: int = 60) -> None:
    """
    打印分隔线

    Args:
        char: 分隔符字符
        length: 长度
    """
    print(char * length)


def print_header(title: str, width: int = 60) -> None:
    """
    打印标题头部

    Args:
        title: 标题文本
        width: 总宽度
    """
    print_separator("=", width)
    print(title.center(width))
    print_separator("=", width)


def print_section(title: str, width: int = 60) -> None:
    """
    打印章节标题

    Args:
        title: 章节标题
        width: 总宽度
    """
    print_separator("-", width)
    print(title)
    print_separator("-", width)
