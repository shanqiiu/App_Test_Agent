#!/usr/bin/env python3
"""
xml2json.py - UIAutomator XML 转 UI-JSON

将 Android UIAutomator dump 的 XML 布局树转换为轻量化的 UI-JSON 格式。
过滤不可见组件，仅保留关键特征用于后续 VLM 推理。
"""

import xml.etree.ElementTree as ET
import json
import argparse
import re
from pathlib import Path
from datetime import datetime
from typing import Optional
from PIL import Image


def parse_bounds(bounds_str: str) -> dict:
    """
    解析 UIAutomator bounds 字符串
    格式: "[x1,y1][x2,y2]" → {"x": x1, "y": y1, "width": w, "height": h}
    """
    pattern = r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]'
    match = re.match(pattern, bounds_str)
    if not match:
        return {"x": 0, "y": 0, "width": 0, "height": 0}

    x1, y1, x2, y2 = map(int, match.groups())
    return {
        "x": x1,
        "y": y1,
        "width": x2 - x1,
        "height": y2 - y1
    }


def is_visible(bounds: dict, screen_width: int, screen_height: int) -> bool:
    """判断组件是否可见（在屏幕范围内且有面积）"""
    if bounds["width"] <= 0 or bounds["height"] <= 0:
        return False
    if bounds["x"] >= screen_width or bounds["y"] >= screen_height:
        return False
    if bounds["x"] + bounds["width"] <= 0 or bounds["y"] + bounds["height"] <= 0:
        return False
    return True


def parse_node(node: ET.Element, screen_width: int, screen_height: int, index: int) -> Optional[dict]:
    """
    解析单个 XML 节点为组件字典
    """
    bounds_str = node.get('bounds', '[0,0][0,0]')
    bounds = parse_bounds(bounds_str)

    # 过滤不可见组件
    if not is_visible(bounds, screen_width, screen_height):
        return None

    component = {
        "index": index,
        "class": node.get('class', '').split('.')[-1],  # 只保留类名
        "bounds": bounds,
    }

    # 可选属性
    resource_id = node.get('resource-id', '')
    if resource_id:
        # 简化 resource-id：去掉包名前缀
        component["id"] = resource_id.split('/')[-1] if '/' in resource_id else resource_id

    text = node.get('text', '')
    if text:
        component["text"] = text

    content_desc = node.get('content-desc', '')
    if content_desc:
        component["contentDesc"] = content_desc

    # 状态属性
    if node.get('clickable') == 'true':
        component["clickable"] = True
    if node.get('enabled') == 'false':
        component["enabled"] = False
    if node.get('selected') == 'true':
        component["selected"] = True
    if node.get('checked') == 'true':
        component["checked"] = True

    return component


def traverse_xml(root: ET.Element, screen_width: int, screen_height: int) -> list:
    """
    递归遍历 XML 树，提取所有叶子节点组件
    """
    components = []
    index = 0

    def _traverse(node: ET.Element):
        nonlocal index
        children = list(node)

        if not children:
            # 叶子节点
            component = parse_node(node, screen_width, screen_height, index)
            if component:
                components.append(component)
                index += 1
        else:
            # 递归处理子节点
            for child in children:
                _traverse(child)

    _traverse(root)
    return components


def xml_to_json(xml_path: str, screenshot_path: Optional[str] = None,
                width: Optional[int] = None, height: Optional[int] = None) -> dict:
    """
    主函数：将 UIAutomator XML 转换为 UI-JSON

    Args:
        xml_path: UIAutomator dump 的 XML 文件路径
        screenshot_path: 可选，对应的截图路径（用于获取分辨率）
        width: 可选，手动指定屏幕宽度
        height: 可选，手动指定屏幕高度

    Returns:
        UI-JSON 字典
    """
    # 确定屏幕分辨率
    if width and height:
        screen_width, screen_height = width, height
    elif screenshot_path and Path(screenshot_path).exists():
        with Image.open(screenshot_path) as img:
            screen_width, screen_height = img.size
    else:
        # 默认分辨率
        screen_width, screen_height = 1080, 1920

    # 解析 XML
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # 提取组件
    components = traverse_xml(root, screen_width, screen_height)

    # 构建 UI-JSON
    ui_json = {
        "metadata": {
            "source": Path(xml_path).name,
            "timestamp": datetime.now().isoformat(),
            "resolution": {
                "width": screen_width,
                "height": screen_height
            }
        },
        "components": components,
        "componentCount": len(components)
    }

    return ui_json


def main():
    parser = argparse.ArgumentParser(
        description='UIAutomator XML → UI-JSON 转换器'
    )
    parser.add_argument('--xml-path', '-x', required=True,
                        help='UIAutomator dump 的 XML 文件路径')
    parser.add_argument('--screenshot', '-s',
                        help='对应的截图路径（用于获取分辨率）')
    parser.add_argument('--width', '-W', type=int,
                        help='手动指定屏幕宽度')
    parser.add_argument('--height', '-H', type=int,
                        help='手动指定屏幕高度')
    parser.add_argument('--output', '-o',
                        help='输出 JSON 文件路径')
    parser.add_argument('--pretty', action='store_true',
                        help='格式化输出 JSON')

    args = parser.parse_args()

    # 转换
    ui_json = xml_to_json(
        xml_path=args.xml_path,
        screenshot_path=args.screenshot,
        width=args.width,
        height=args.height
    )

    # 输出
    if args.output:
        output_path = Path(args.output)
    else:
        xml_path = Path(args.xml_path)
        output_path = xml_path.with_suffix('.json')

    indent = 2 if args.pretty else None
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(ui_json, f, ensure_ascii=False, indent=indent)

    print(f"✓ 转换完成: {output_path}")
    print(f"  分辨率: {ui_json['metadata']['resolution']['width']}x{ui_json['metadata']['resolution']['height']}")
    print(f"  组件数: {ui_json['componentCount']}")


if __name__ == '__main__':
    main()
