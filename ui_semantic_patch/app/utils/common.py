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

    额外支持：如果提取到 list，自动包装成 {"groups": list} 格式
    """
    extracted = None
    
    # 尝试直接解析
    try:
        extracted = json.loads(content)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 块
    if extracted is None:
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
        if json_match:
            try:
                extracted = json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

    # 尝试找到 { ... } 块
    if extracted is None:
        brace_match = re.search(r'\{[\s\S]*\}', content)
        if brace_match:
            try:
                extracted = json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

    if extracted is None:
        raise ValueError(f"无法从 VLM 输出中提取 JSON: {content[:200]}...")

    # 格式规范化：确保返回 dict 且有 groups 键
    if isinstance(extracted, list):
        # 如果提取到 list，包装成 {"groups": list}
        return {"groups": extracted}
    elif isinstance(extracted, dict):
        # 如果是 dict 但没有 groups 键，检查是否有 items 或其他键
        if 'groups' not in extracted:
            # 尝试从其他常见键名提取
            for key in ['items', 'components', 'elements', 'result']:
                if key in extracted and isinstance(extracted[key], list):
                    extracted = {"groups": extracted[key]}
                    break
        return extracted
    else:
        # 其他类型，包装成空 groups
        return {"groups": []}
