#!/usr/bin/env python3
"""
visualize_omni.py - OmniParser 检测结果可视化

将 OmniParser 检测到的 UI 组件边界框和标签叠加到原始截图上，
便于验证和调试检测结果。
"""

import json
import argparse
from pathlib import Path
from typing import Dict, List, Tuple
from PIL import Image, ImageDraw, ImageFont


# 组件类型颜色映射
CLASS_COLORS = {
    'Button': '#FF6B6B',           # 红色
    'TextView': '#4ECDC4',         # 青色
    'ImageButton': '#FFE66D',      # 黄色
    'ImageView': '#95E1D3',        # 浅绿
    'SearchBar': '#F38181',        # 粉色
    'Dialog': '#FF6B9D',           # 深粉色
    'Toast': '#C44569',            # 棕红
    'Card': '#A8D8EA',             # 浅蓝
    'Avatar': '#AA96DA',           # 紫色
    'Checkbox': '#FCBAD3',         # 浅粉
    'Switch': '#A2D5F7',           # 浅蓝
    'TabBar': '#FFD3B6',           # 橙色
    'TabItem': '#FFAAA5',          # 浅橙
    'ListItem': '#FF8B94',         # 红粉
    'NavigationBar': '#2A9D8F',    # 深绿
    'StatusBar': '#264653',        # 深蓝
}

# 默认颜色
DEFAULT_COLOR = '#8E44AD'  # 紫色


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """将十六进制颜色转换为 RGB 元组"""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def get_color_for_class(component_class: str) -> Tuple[int, int, int]:
    """获取组件类型的颜色"""
    hex_color = CLASS_COLORS.get(component_class, DEFAULT_COLOR)
    return hex_to_rgb(hex_color)


def try_load_font(size: int = 12) -> ImageFont.FreeTypeFont:
    """尝试加载字体，降级到默认字体"""
    font_paths = [
        'C:/Windows/Fonts/msyh.ttc',           # 微软雅黑
        'C:/Windows/Fonts/arial.ttf',          # Arial
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',  # Linux
        '/System/Library/Fonts/Helvetica.ttc', # macOS
    ]

    for font_path in font_paths:
        try:
            return ImageFont.truetype(font_path, size)
        except:
            pass

    # 降级到默认字体
    return ImageFont.load_default()


def visualize_components(
    screenshot_path: str,
    ui_json: Dict,
    output_path: str = None,
    show_text: bool = True,
    border_width: int = 2,
    font_size: int = 10
) -> Image.Image:
    """
    将 UI 组件可视化到截图上

    Args:
        screenshot_path: 原始截图路径
        ui_json: UI-JSON 字典
        output_path: 输出图片路径（可选）
        show_text: 是否显示文本标签
        border_width: 边界框线宽
        font_size: 字体大小

    Returns:
        带注解的 PIL Image 对象
    """
    # 加载原始图片
    image = Image.open(screenshot_path).convert('RGB')
    draw = ImageDraw.Draw(image)
    font = try_load_font(font_size)

    # 获取组件列表
    components = ui_json.get('components', [])

    print(f"正在可视化 {len(components)} 个组件...")

    for comp in components:
        bounds = comp.get('bounds', {})
        x = bounds.get('x', 0)
        y = bounds.get('y', 0)
        width = bounds.get('width', 0)
        height = bounds.get('height', 0)

        # 计算矩形坐标
        box = (x, y, x + width, y + height)

        # 获取颜色
        comp_class = comp.get('class', 'Unknown')
        color = get_color_for_class(comp_class)

        # 绘制边界框
        draw.rectangle(box, outline=color, width=border_width)

        # 绘制文本标签
        if show_text:
            index = comp.get('index', 0)
            text_content = comp.get('text', '')[:15]  # 截断长文本

            # 标签内容：[索引] 类型
            label = f"[{index}] {comp_class}"
            if text_content:
                label += f"\n{text_content}"

            # 计算标签背景位置（在框的左上方）
            label_bg_y = max(0, y - font_size - 6)

            # 获取文本宽度（估算）
            bbox = draw.textbbox((0, 0), label, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            # 绘制标签背景
            label_bg = (x, label_bg_y, x + text_width + 4, label_bg_y + text_height + 4)
            draw.rectangle(label_bg, fill=color)

            # 绘制文本
            draw.text(
                (x + 2, label_bg_y + 2),
                label,
                font=font,
                fill=(255, 255, 255)  # 白色文本
            )

        # 在框内绘制圆点表示中心点
        center_x = x + width // 2
        center_y = y + height // 2
        dot_size = 3
        draw.ellipse(
            (center_x - dot_size, center_y - dot_size,
             center_x + dot_size, center_y + dot_size),
            fill=color
        )

    # 保存输出图片
    if output_path:
        image.save(output_path)
        print(f"✓ 可视化完成: {output_path}")

    return image


def main():
    parser = argparse.ArgumentParser(
        description='OmniParser 检测结果可视化',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:

  # 可视化指定的 UI-JSON 文件
  python visualize_omni.py \\
    --screenshot ./screenshot.png \\
    --ui-json ./screenshot_structure.json \\
    --output ./annotated.png

  # 仅显示在屏幕上，不保存文件
  python visualize_omni.py \\
    --screenshot ./screenshot.png \\
    --ui-json ./screenshot_structure.json \\
    --no-save

  # 调整字体大小和边界框宽度
  python visualize_omni.py \\
    --screenshot ./screenshot.png \\
    --ui-json ./screenshot_structure.json \\
    --output ./annotated.png \\
    --font-size 12 \\
    --border-width 3
"""
    )

    parser.add_argument('--screenshot', '-s', required=True,
                        help='原始截图路径')
    parser.add_argument('--ui-json', '-j', required=True,
                        help='UI-JSON 文件路径')
    parser.add_argument('--output', '-o',
                        help='输出图片路径（可选）')
    parser.add_argument('--no-save', action='store_true',
                        help='不保存文件，仅显示')
    parser.add_argument('--font-size', type=int, default=10,
                        help='标签字体大小')
    parser.add_argument('--border-width', type=int, default=2,
                        help='边界框线宽')
    parser.add_argument('--no-text', action='store_true',
                        help='不显示文本标签')

    args = parser.parse_args()

    # 验证输入文件
    if not Path(args.screenshot).exists():
        print(f"✗ 截图文件不存在: {args.screenshot}")
        return

    if not Path(args.ui_json).exists():
        print(f"✗ UI-JSON 文件不存在: {args.ui_json}")
        return

    # 加载 UI-JSON
    print(f"正在加载 UI-JSON...")
    with open(args.ui_json, 'r', encoding='utf-8') as f:
        ui_json = json.load(f)

    print(f"  分辨率: {ui_json['metadata']['resolution']['width']}x{ui_json['metadata']['resolution']['height']}")
    print(f"  组件数: {ui_json['componentCount']}")
    print(f"  提取方式: {ui_json['metadata']['extractionMethod']}")

    # 确定输出路径
    output_path = args.output
    if not args.no_save and not output_path:
        ui_json_path = Path(args.ui_json)
        output_path = ui_json_path.parent / f"{ui_json_path.stem}_annotated.png"

    # 生成可视化
    print(f"\n正在生成可视化...")
    visualize_components(
        screenshot_path=args.screenshot,
        ui_json=ui_json,
        output_path=output_path,
        show_text=not args.no_text,
        border_width=args.border_width,
        font_size=args.font_size
    )

    print("\n=" * 60)
    print("✓ OmniParser 可视化完成！")
    print("=" * 60)

    # 打印组件统计
    components = ui_json.get('components', [])
    class_counts = {}
    for comp in components:
        comp_class = comp.get('class', 'Unknown')
        class_counts[comp_class] = class_counts.get(comp_class, 0) + 1

    print("\n组件类型统计:")
    for comp_class, count in sorted(class_counts.items(), key=lambda x: -x[1]):
        color = get_color_for_class(comp_class)
        print(f"  {comp_class:<15} : {count:3d} 个")

    if output_path:
        print(f"\n输出文件: {output_path}")


if __name__ == '__main__':
    main()
