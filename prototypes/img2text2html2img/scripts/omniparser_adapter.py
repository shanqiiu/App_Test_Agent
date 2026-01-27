"""
OmniParser Adapter - OmniParser 输出适配器
将 OmniParser 的原始解析结果转换为 img2text2html2img 框架格式

OmniParser 输出特点：
- bbox 使用归一化坐标 [0-1]
- 包含 interactivity 可交互性标记
- source 标注检测来源 (box_ocr_content_ocr / box_yolo_content_yolo 等)

框架期望格式：
- bbox 使用像素坐标 [x1, y1, x2, y2]
- 包含 type, confidence, text 等标准字段
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass

try:
    from PIL import Image
except ImportError:
    Image = None


@dataclass
class UIComponent:
    """UI 组件数据类"""
    id: int
    type: str
    bbox: List[int]  # 像素坐标 [x1, y1, x2, y2]
    bbox_normalized: List[float]  # 归一化坐标 [0-1]
    text: str
    interactivity: bool
    confidence: float
    source: str

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "type": self.type,
            "bbox": self.bbox,
            "bbox_normalized": self.bbox_normalized,
            "text": self.text,
            "interactivity": self.interactivity,
            "confidence": self.confidence,
            "source": self.source
        }


class OmniParserAdapter:
    """
    OmniParser 输出适配器

    将 OmniParser 的解析结果转换为框架统一格式，
    支持直接加载 JSON 文件或处理内存中的数据。
    """

    # 类型映射
    TYPE_MAPPING = {
        "text": "text",
        "icon": "icon",
        # 可扩展更多类型
    }

    # 来源置信度权重（基于检测来源估算置信度）
    SOURCE_CONFIDENCE = {
        "box_ocr_content_ocr": 0.90,      # OCR 检测 + OCR 文本
        "box_yolo_content_ocr": 0.85,     # YOLO 检测 + OCR 文本
        "box_yolo_content_yolo": 0.80,    # YOLO 检测 + YOLO 描述
    }

    def __init__(self, image_size: Optional[Tuple[int, int]] = None):
        """
        初始化适配器

        Args:
            image_size: 图像尺寸 (width, height)，用于坐标转换
        """
        self.image_size = image_size

    def load_from_file(self, json_path: str, image_path: Optional[str] = None) -> Dict:
        """
        从 JSON 文件加载并转换 OmniParser 结果

        Args:
            json_path: OmniParser 输出的 JSON 文件路径
            image_path: 原始图像路径（用于获取尺寸）

        Returns:
            框架格式的检测结果
        """
        path = Path(json_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {json_path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        return self.convert(data, image_path)

    def convert(
        self,
        omni_data: Union[List[Dict], Dict],
        image_path: Optional[str] = None
    ) -> Dict:
        """
        转换 OmniParser 输出为框架格式

        Args:
            omni_data: OmniParser 原始输出（列表或字典）
            image_path: 原始图像路径

        Returns:
            {
                "image_size": [width, height],
                "components": [...],
                "detector": "OmniParser",
                "timestamp": "...",
                "statistics": {...}
            }
        """
        # 获取图像尺寸
        width, height = self._get_image_size(image_path)

        # 处理输入格式（可能是列表或包含列表的字典）
        if isinstance(omni_data, dict):
            items = omni_data.get("items", omni_data.get("components", []))
        else:
            items = omni_data

        # 转换每个组件
        components = []
        for idx, item in enumerate(items):
            component = self._convert_item(item, idx, width, height)
            if component:
                components.append(component.to_dict())

        # 统计信息
        stats = self._compute_statistics(components)

        return {
            "image_size": [width, height],
            "components": components,
            "detector": "OmniParser",
            "adapter": "OmniParserAdapter",
            "timestamp": datetime.now().isoformat(),
            "statistics": stats
        }

    def _get_image_size(self, image_path: Optional[str]) -> Tuple[int, int]:
        """获取图像尺寸"""
        if self.image_size:
            return self.image_size

        if image_path and Image:
            try:
                with Image.open(image_path) as img:
                    return img.size
            except Exception:
                pass

        # 默认尺寸（移动端常见）
        return (1080, 1920)

    def _convert_item(
        self,
        item: Dict,
        idx: int,
        width: int,
        height: int
    ) -> Optional[UIComponent]:
        """转换单个组件"""
        # 提取归一化坐标
        bbox_norm = item.get("bbox", [0, 0, 0, 0])
        if len(bbox_norm) != 4:
            return None

        # 转换为像素坐标
        x1 = int(bbox_norm[0] * width)
        y1 = int(bbox_norm[1] * height)
        x2 = int(bbox_norm[2] * width)
        y2 = int(bbox_norm[3] * height)
        bbox_pixel = [x1, y1, x2, y2]

        # 提取其他字段
        comp_type = self.TYPE_MAPPING.get(
            item.get("type", "unknown"),
            item.get("type", "unknown")
        )

        text = (item.get("content") or "").strip()
        interactivity = item.get("interactivity", False)
        source = item.get("source", "unknown")

        # 根据来源估算置信度
        confidence = self.SOURCE_CONFIDENCE.get(source, 0.75)

        # 如果是 YOLO 描述性内容，标记为 icon
        if source == "box_yolo_content_yolo" and text:
            comp_type = "icon"
            # 描述性文本作为语义标签
            if text.startswith("A ") or text.startswith("An "):
                pass  # 保留描述

        return UIComponent(
            id=item.get("id", idx),
            type=comp_type,
            bbox=bbox_pixel,
            bbox_normalized=bbox_norm,
            text=text,
            interactivity=interactivity,
            confidence=confidence,
            source=source
        )

    def _compute_statistics(self, components: List[Dict]) -> Dict:
        """计算统计信息"""
        type_counts = {}
        interactive_count = 0
        sources = {}

        for comp in components:
            # 类型统计
            t = comp.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

            # 可交互统计
            if comp.get("interactivity"):
                interactive_count += 1

            # 来源统计
            s = comp.get("source", "unknown")
            sources[s] = sources.get(s, 0) + 1

        return {
            "total_components": len(components),
            "type_distribution": type_counts,
            "interactive_count": interactive_count,
            "source_distribution": sources
        }


def convert_omniparser_to_framework(
    json_path: str,
    image_path: Optional[str] = None,
    output_path: Optional[str] = None
) -> Dict:
    """
    便捷函数：转换 OmniParser 输出文件

    Args:
        json_path: OmniParser JSON 文件路径
        image_path: 原始图像路径（可选）
        output_path: 输出文件路径（可选，不指定则不保存）

    Returns:
        框架格式的检测结果
    """
    adapter = OmniParserAdapter()
    result = adapter.load_from_file(json_path, image_path)

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"[OK] 转换完成: {output_path}")
        print(f"     组件数: {result['statistics']['total_components']}")
        print(f"     可交互: {result['statistics']['interactive_count']}")

    return result


def format_for_prompt(detection: Dict, max_items: int = 100) -> str:
    """
    将检测结果格式化为 VL 模型提示词

    Args:
        detection: 框架格式的检测结果
        max_items: 最大显示组件数

    Returns:
        格式化的提示词文本
    """
    lines = []
    w, h = detection.get("image_size", [0, 0])

    for comp in detection.get("components", [])[:max_items]:
        bbox = comp.get("bbox", [0, 0, 0, 0])
        x1, y1, x2, y2 = bbox
        comp_w, comp_h = x2 - x1, y2 - y1

        # 计算位置描述
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        pos_x = "左侧" if cx < w * 0.33 else ("右侧" if cx > w * 0.67 else "中部")
        pos_y = "顶部" if cy < h * 0.33 else ("底部" if cy > h * 0.67 else "中部")

        line = f"- [{comp.get('type', '?')}] "
        line += f"位置:{pos_y}{pos_x} "
        line += f"bbox:[{x1},{y1},{x2},{y2}] "
        line += f"尺寸:{comp_w}x{comp_h}px"

        if comp.get("text"):
            text = comp["text"][:50]  # 截断过长文本
            line += f" 内容:「{text}」"

        if comp.get("interactivity"):
            line += " [可交互]"

        lines.append(line)

    stats = detection.get("statistics", {})
    header = f"## 检测结果 (共 {stats.get('total_components', 0)} 个组件, {stats.get('interactive_count', 0)} 个可交互)\n"

    return header + "\n".join(lines)


# ============= 命令行接口 =============

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="OmniParser 输出适配器 - 转换为框架格式",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 转换单个文件
  python omniparser_adapter.py --input parse1.json --image screenshot.png

  # 转换并保存
  python omniparser_adapter.py --input parse1.json --output detection.json

  # 生成提示词格式
  python omniparser_adapter.py --input parse1.json --format prompt
"""
    )

    parser.add_argument("--input", "-i", required=True, help="OmniParser JSON 文件")
    parser.add_argument("--image", help="原始图像路径（用于获取尺寸）")
    parser.add_argument("--output", "-o", help="输出文件路径")
    parser.add_argument(
        "--format",
        choices=["json", "prompt"],
        default="json",
        help="输出格式"
    )
    parser.add_argument("--width", type=int, help="图像宽度（手动指定）")
    parser.add_argument("--height", type=int, help="图像高度（手动指定）")

    args = parser.parse_args()

    # 初始化适配器
    image_size = None
    if args.width and args.height:
        image_size = (args.width, args.height)

    adapter = OmniParserAdapter(image_size=image_size)

    # 转换
    result = adapter.load_from_file(args.input, args.image)

    # 输出
    if args.format == "prompt":
        print(format_for_prompt(result))
    else:
        if args.output:
            Path(args.output).write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            print(f"[OK] 保存到: {args.output}")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))

    # 打印统计
    stats = result.get("statistics", {})
    print(f"\n--- 统计 ---")
    print(f"总组件数: {stats.get('total_components', 0)}")
    print(f"可交互数: {stats.get('interactive_count', 0)}")
    print(f"类型分布: {stats.get('type_distribution', {})}")


if __name__ == "__main__":
    main()
