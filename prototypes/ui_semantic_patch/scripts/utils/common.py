#!/usr/bin/env python3
"""
common.py - 公共工具函数

包含多个模块共用的工具函数，避免代码重复。
"""

import json
import base64
import re
from pathlib import Path


def encode_image(image_path: str) -> str:
    """将图片编码为 base64"""
    with open(image_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')


def get_mime_type(image_path: str) -> str:
    """获取图片 MIME 类型"""
    suffix = Path(image_path).suffix.lower()
    mime_map = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp'
    }
    return mime_map.get(suffix, 'image/png')


def extract_json(content: str) -> dict:
    """
    从 VLM 输出中提取 JSON

    支持三种格式：
    1. 纯 JSON 字符串
    2. ```json ... ``` 代码块
    3. 文本中嵌入的 { ... } 块
    """
    # 尝试直接解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 块
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试找到 { ... } 块
    brace_match = re.search(r'\{[\s\S]*\}', content)
    if brace_match:
        return json.loads(brace_match.group(0))

    raise ValueError(f"无法从 VLM 输出中提取 JSON: {content[:200]}...")
