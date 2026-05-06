"""
logging_utils.py - 日志系统配置工具

为 UI Semantic Patch 各脚本提供统一的日志配置：
- 同时输出到终端（stdout）和日志文件
- 标准化格式：时间戳 + 级别 + 模块名 + 消息
- UTF-8 编码（Windows 兼容）
- 可配置日志目录和文件名
"""

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logging(
    log_dir: Optional[str] = None,
    log_name: str = "pipeline",
    level: int = logging.INFO,
    console: bool = True,
) -> logging.Logger:
    """
    配置根日志系统，同时输出到终端和文件。

    Args:
        log_dir:  日志文件存放目录。为 None 时仅输出到终端，不写文件。
        log_name: 日志文件名（不含扩展名），最终文件为 {log_name}.log。
        level:    日志级别，默认 logging.INFO。
        console:  是否同时输出到终端，默认 True。

    Returns:
        配置好的根 logger
    """
    logger = logging.getLogger()
    logger.setLevel(level)

    # 清除已有 handlers（避免重复配置）
    logger.handlers.clear()

    # 格式化器
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)-8s %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    # === 文件 Handler ===
    if log_dir:
        log_path = Path(log_dir).resolve() / f"{log_name}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            file_handler = logging.FileHandler(str(log_path), encoding='utf-8')
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            print(f"[WARN] 无法创建日志文件 {log_path}: {e}")

    # === 终端 Handler ===
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger
