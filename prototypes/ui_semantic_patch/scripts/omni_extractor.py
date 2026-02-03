#!/usr/bin/env python3
"""
omni_extractor.py - 基于 OmniParser 的 UI 结构提取

替代 img2xml.py 中的 VLM 调用，使用本地模型实现更精确的 UI 结构提取。

优势：
- 本地运行，无需 API 调用
- YOLO 检测更精确
- Florence2 图标描述更准确
- 支持 GPU 加速
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Union, Optional, Dict, List
from PIL import Image

# 添加 OmniParser 路径 (third_party 目录)
OMNIPARSER_PATH = Path(__file__).parent.parent / 'third_party' / 'OmniParser'
sys.path.insert(0, str(OMNIPARSER_PATH))

# 延迟导入，避免模块加载时的开销
_omni_parser = None


def get_omni_parser(device: str = None):
    """懒加载 OmniParser 实例"""
    global _omni_parser
    if _omni_parser is None:
        from omni_inference import OmniParser
        _omni_parser = OmniParser(
            yolo_model_path=str(OMNIPARSER_PATH / 'weights/icon_detect/model.pt'),
            caption_model_path=str(OMNIPARSER_PATH / 'weights/icon_caption_florence'),
            device=device
        )
    return _omni_parser


def omni_to_ui_json(
    image_path: str,
    box_threshold: float = 0.05,
    iou_threshold: float = 0.7,
    use_paddleocr: bool = True,
    device: str = None,
    return_annotated_image: bool = False
) -> dict:
    """
    使用 OmniParser 从截图提取 UI 结构，输出 UI-JSON 格式

    Args:
        image_path: 截图路径
        box_threshold: 检测置信度阈值
        iou_threshold: IOU 重叠过滤阈值
        use_paddleocr: 是否使用 PaddleOCR
        device: 运行设备 ('cuda' / 'cpu')
        return_annotated_image: 是否返回可视化图片

    Returns:
        UI-JSON 格式的字典，若 return_annotated_image=True 则包含 'annotated_image' 键
    """
    # 获取图片信息
    with Image.open(image_path) as img:
        width, height = img.size

    # 获取 OmniParser 实例并解析
    parser = get_omni_parser(device)
    result = parser.parse(
        image_path,
        box_threshold=box_threshold,
        iou_threshold=iou_threshold,
        use_paddleocr=use_paddleocr,
        use_local_semantics=True,
        return_annotated_image=return_annotated_image
    )

    # 转换为 UI-JSON 格式
    components = []
    for elem in result.elements:
        # 将归一化坐标转换为像素坐标
        bbox = elem.bbox
        x = int(bbox[0] * width)
        y = int(bbox[1] * height)
        w = int((bbox[2] - bbox[0]) * width)
        h = int((bbox[3] - bbox[1]) * height)

        # 映射组件类型
        component_class = map_element_type(elem.type, elem.content, elem.interactivity)

        component = {
            "index": elem.id,
            "class": component_class,
            "bounds": {
                "x": x,
                "y": y,
                "width": w,
                "height": h
            },
            "text": elem.content or "",
            "clickable": elem.interactivity,
            "source": elem.source
        }

        # 添加内容描述（对于图标）
        if elem.type == 'icon' and elem.content:
            component["contentDesc"] = elem.content

        components.append(component)

    # 按位置排序：从上到下，从左到右
    components.sort(key=lambda c: (c['bounds']['y'], c['bounds']['x']))

    # 重新分配 index
    for i, comp in enumerate(components):
        comp['index'] = i

    # 构建 UI-JSON
    ui_json = {
        "metadata": {
            "source": Path(image_path).name,
            "extractionMethod": "OmniParser",
            "models": {
                "detection": "YOLO (icon_detect)",
                "ocr": "PaddleOCR" if use_paddleocr else "EasyOCR",
                "caption": "Florence2"
            },
            "timestamp": datetime.now().isoformat(),
            "resolution": {
                "width": width,
                "height": height
            }
        },
        "components": components,
        "componentCount": len(components)
    }

    # 添加可视化图片
    if return_annotated_image and result.annotated_image:
        ui_json["annotated_image"] = result.annotated_image

    return ui_json


def map_element_type(elem_type: str, content: str, interactivity: bool) -> str:
    """
    将 OmniParser 的元素类型映射为 UI-JSON 组件类型

    Args:
        elem_type: OmniParser 的类型 ('text' / 'icon')
        content: 元素内容
        interactivity: 是否可交互

    Returns:
        UI-JSON 组件类型
    """
    if elem_type == 'text':
        # 文本类型
        content_lower = (content or '').lower()

        # 根据内容推断类型
        if any(kw in content_lower for kw in ['搜索', 'search', '请输入', '输入']):
            return 'SearchBar'
        elif any(kw in content_lower for kw in ['登录', '注册', '确定', '取消', '提交', '下一步', 'login', 'submit', 'ok', 'cancel']):
            return 'Button'
        elif interactivity:
            return 'Button'
        else:
            return 'TextView'

    elif elem_type == 'icon':
        # 图标类型
        content_lower = (content or '').lower()

        # 根据描述推断类型
        if any(kw in content_lower for kw in ['back', 'arrow', 'return', '返回']):
            return 'ImageButton'
        elif any(kw in content_lower for kw in ['menu', 'more', '菜单', '更多']):
            return 'ImageButton'
        elif any(kw in content_lower for kw in ['search', '搜索']):
            return 'SearchBar'
        elif any(kw in content_lower for kw in ['avatar', 'profile', '头像']):
            return 'Avatar'
        elif any(kw in content_lower for kw in ['checkbox', 'check']):
            return 'Checkbox'
        elif any(kw in content_lower for kw in ['switch', 'toggle']):
            return 'Switch'
        elif interactivity:
            return 'ImageButton'
        else:
            return 'ImageView'

    return 'Unknown'


def img_to_ui_json(
    image_path: str,
    device: str = None,
    **kwargs
) -> dict:
    """
    从截图提取 UI 结构（使用 OmniParser）

    Args:
        image_path: 截图路径
        device: OmniParser 运行设备 ('cuda' / 'cpu')

    Returns:
        UI-JSON 格式字典
    """
    print("  使用 OmniParser 本地提取...")
    return omni_to_ui_json(image_path, device=device, **kwargs)


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(
        description='OmniParser UI 结构提取器'
    )
    parser.add_argument('--image', '-i', required=True,
                        help='截图路径')
    parser.add_argument('--output', '-o',
                        help='输出 JSON 文件路径')
    parser.add_argument('--box-threshold', type=float, default=0.05,
                        help='检测置信度阈值')
    parser.add_argument('--iou-threshold', type=float, default=0.7,
                        help='IOU 阈值')
    parser.add_argument('--device', default=None,
                        help='运行设备 (cuda/cpu)')
    parser.add_argument('--no-paddleocr', action='store_true',
                        help='使用 EasyOCR 替代 PaddleOCR')
    parser.add_argument('--pretty', action='store_true',
                        help='格式化输出 JSON')

    args = parser.parse_args()

    print("=" * 50)
    print("OmniParser UI 结构提取")
    print("=" * 50)

    # 提取 UI 结构
    ui_json = omni_to_ui_json(
        image_path=args.image,
        box_threshold=args.box_threshold,
        iou_threshold=args.iou_threshold,
        use_paddleocr=not args.no_paddleocr,
        device=args.device
    )

    # 输出
    if args.output:
        output_path = Path(args.output)
    else:
        image_path = Path(args.image)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = image_path.parent / f"{image_path.stem}_structure_{timestamp}.json"

    indent = 2 if args.pretty else None
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(ui_json, f, ensure_ascii=False, indent=indent)

    print(f"\n✓ UI 结构提取完成: {output_path}")
    print(f"  提取方式: OmniParser (本地)")
    print(f"  分辨率: {ui_json['metadata']['resolution']['width']}x{ui_json['metadata']['resolution']['height']}")
    print(f"  组件数: {ui_json['componentCount']}")

    # 打印组件摘要
    print("\n组件摘要:")
    for comp in ui_json['components'][:15]:
        text_preview = comp.get('text', '')[:20] + '...' if len(comp.get('text', '')) > 20 else comp.get('text', '')
        bounds = comp.get('bounds', {})
        clickable = '✓' if comp.get('clickable') else ' '
        print(f"  [{comp['index']:2d}] {comp['class']:<15} "
              f"({bounds.get('x', 0):4d},{bounds.get('y', 0):4d}) "
              f"{bounds.get('width', 0):4d}x{bounds.get('height', 0):<4d} "
              f"[{clickable}] {text_preview}")

    if ui_json['componentCount'] > 15:
        print(f"  ... 还有 {ui_json['componentCount'] - 15} 个组件")


if __name__ == '__main__':
    main()
