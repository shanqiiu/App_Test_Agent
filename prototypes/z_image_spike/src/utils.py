"""
Utility functions for logging, GPU management, and file I/O.
"""

import logging
import json
import torch
from pathlib import Path
from typing import Any, Dict


def setup_logger(name: str, log_file: str = None, level=logging.INFO) -> logging.Logger:
    """
    Setup logger with console and file handlers.

    Args:
        name: Logger name
        log_file: Optional log file path
        level: Logging level

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (if specified)
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_gpu_memory_gb() -> float:
    """
    Get available GPU memory in GB.

    Returns:
        Available GPU memory in GB, or 0 if CUDA not available
    """
    if not torch.cuda.is_available():
        return 0.0

    return torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)


def clear_gpu_cache():
    """Clear GPU cache to free memory."""
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def ensure_dir(path: str) -> Path:
    """
    Ensure directory exists, create if not.

    Args:
        path: Directory path

    Returns:
        Path object
    """
    dir_path = Path(path)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def save_json(data: Dict[str, Any], path: str):
    """
    Save dictionary to JSON file.

    Args:
        data: Data to save
        path: Output file path
    """
    ensure_dir(Path(path).parent)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_json(path: str) -> Dict[str, Any]:
    """
    Load JSON file.

    Args:
        path: JSON file path

    Returns:
        Loaded data dictionary
    """
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)
