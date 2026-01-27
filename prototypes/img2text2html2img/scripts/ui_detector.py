"""
UI Detector - UI组件检测模块
使用 OmniParser 检测 UI 组件，获取精确边界框和 OCR 文本
"""

import argparse
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from abc import ABC, abstractmethod

try:
    from PIL import Image
except ImportError:
    Image = None


class UIDetector(ABC):
    """UI组件检测基类"""

    @abstractmethod
    def detect(self, image_path: str) -> Dict:
        """
        检测UI组件，返回结构化结果

        Returns:
            {
                "image_size": [width, height],
                "components": [
                    {
                        "id": 0,
                        "type": "button|text|image|icon|input|...",
                        "bbox": [x1, y1, x2, y2],
                        "confidence": 0.95,
                        "text": "按钮文字",
                    }
                ],
                "detector": "detector_name",
                "timestamp": "ISO timestamp"
            }
        """
        pass

    def save(self, result: Dict, output_path: str) -> str:
        """保存检测结果"""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)


class OmniParserDetector(UIDetector):
    """
    基于 OmniParser 的 UI 检测器

    OmniParser 是 Microsoft 开源的 UI 解析工具，专为屏幕截图设计，
    支持组件检测、OCR 文本识别、图标分类等功能。

    GitHub: https://github.com/microsoft/OmniParser
    """

    def __init__(self, device: str = "cuda", model_path: Optional[str] = None):
        """
        初始化 OmniParser 检测器

        Args:
            device: 推理设备 ("cuda" / "cpu")
            model_path: 模型路径（可选，默认自动下载）
        """
        self.device = device
        self.model_path = model_path
        self._parser = None

    def _load_model(self):
        """延迟加载模型"""
        if self._parser is not None:
            return

        try:
            from omniparser import OmniParser
            self._parser = OmniParser(
                device=self.device,
                model_path=self.model_path
            )
            print(f"[OmniParser] 模型加载成功 (device={self.device})")
        except ImportError:
            raise ImportError(
                "OmniParser 未安装。请运行:\n"
                "  pip install omniparser-v2\n"
                "或从源码安装:\n"
                "  git clone https://github.com/microsoft/OmniParser.git\n"
                "  cd OmniParser && pip install -e ."
            )

    def detect(self, image_path: str) -> Dict:
        """检测 UI 组件"""
        self._load_model()

        # 获取图像尺寸
        if Image:
            with Image.open(image_path) as img:
                width, height = img.size
        else:
            width, height = 0, 0

        # 调用 OmniParser
        result = self._parser.parse(image_path)

        # 转换为统一格式
        components = []
        for idx, item in enumerate(result.get("ui_elements", [])):
            component = {
                "id": idx,
                "type": self._map_type(item.get("type", "unknown")),
                "bbox": item.get("bbox", [0, 0, 0, 0]),
                "confidence": item.get("score", 0.0),
                "text": item.get("ocr_text", "") or item.get("text", ""),
            }
            components.append(component)

        return {
            "image_size": [width, height],
            "components": components,
            "detector": "OmniParser",
            "timestamp": datetime.now().isoformat()
        }

    def _map_type(self, omni_type: str) -> str:
        """映射 OmniParser 类型到统一类型"""
        type_mapping = {
            "Button": "button",
            "Text": "text",
            "Icon": "icon",
            "Image": "image",
            "Input": "input",
            "CheckBox": "checkbox",
            "Switch": "switch",
            "ListItem": "list_item",
            "Container": "container",
        }
        return type_mapping.get(omni_type, omni_type.lower())


class OmniParserRawDetector(UIDetector):
    """
    OmniParser 原始输出检测器

    直接加载 OmniParser 的原始解析 JSON 文件（归一化坐标格式），
    无需安装 omniparser pip 包，适用于已有解析结果的场景。

    输入格式示例 (parse1.json):
    [
      {"id": 0, "type": "text", "bbox": [0.1, 0.2, 0.3, 0.4], "content": "文本"},
      {"id": 1, "type": "icon", "bbox": [0.5, 0.6, 0.7, 0.8], "interactivity": true}
    ]
    """

    def __init__(self, json_path: Optional[str] = None):
        """
        初始化检测器

        Args:
            json_path: 预解析的 JSON 文件路径（可选，也可在 detect 时指定）
        """
        self.json_path = json_path
        self._adapter = None

    def _get_adapter(self):
        """延迟导入适配器"""
        if self._adapter is None:
            try:
                from omniparser_adapter import OmniParserAdapter
                self._adapter = OmniParserAdapter()
            except ImportError:
                raise ImportError(
                    "请确保 omniparser_adapter.py 在同一目录下"
                )
        return self._adapter

    def detect(self, image_path: str, json_path: Optional[str] = None) -> Dict:
        """
        从预解析的 JSON 文件加载检测结果

        Args:
            image_path: 原始图像路径（用于获取尺寸）
            json_path: 解析结果 JSON 路径（覆盖初始化时的路径）

        Returns:
            框架格式的检测结果
        """
        json_file = json_path or self.json_path
        if not json_file:
            # 尝试自动查找同名 JSON 文件
            img_path = Path(image_path)
            candidates = [
                img_path.with_suffix(".json"),
                img_path.parent / f"{img_path.stem}_detection.json",
                img_path.parent / "parse_json" / f"{img_path.stem}.json",
            ]
            for candidate in candidates:
                if candidate.exists():
                    json_file = str(candidate)
                    break

        if not json_file or not Path(json_file).exists():
            raise FileNotFoundError(
                f"未找到解析结果文件。请指定 --json-path 参数，"
                f"或确保存在 {image_path.replace(Path(image_path).suffix, '.json')}"
            )

        adapter = self._get_adapter()
        return adapter.load_from_file(json_file, image_path)


class MockDetector(UIDetector):
    """
    模拟检测器（用于测试，无需安装 OmniParser）

    基于图像分割生成模拟的 UI 组件边界框
    """

    def __init__(self, grid_rows: int = 4, grid_cols: int = 3):
        self.grid_rows = grid_rows
        self.grid_cols = grid_cols

    def detect(self, image_path: str) -> Dict:
        """生成模拟检测结果"""
        # 获取图像尺寸
        if Image:
            with Image.open(image_path) as img:
                width, height = img.size
        else:
            width, height = 1080, 1920

        # 生成网格组件
        components = []
        cell_w = width // self.grid_cols
        cell_h = height // self.grid_rows

        component_types = ["button", "text", "icon", "image", "input"]

        idx = 0
        for row in range(self.grid_rows):
            for col in range(self.grid_cols):
                x1 = col * cell_w + 10
                y1 = row * cell_h + 10
                x2 = (col + 1) * cell_w - 10
                y2 = (row + 1) * cell_h - 10

                components.append({
                    "id": idx,
                    "type": component_types[idx % len(component_types)],
                    "bbox": [x1, y1, x2, y2],
                    "confidence": 0.85 + (idx % 10) * 0.01,
                    "text": f"组件{idx}" if idx % 2 == 0 else "",
                })
                idx += 1

        return {
            "image_size": [width, height],
            "components": components,
            "detector": "MockDetector",
            "timestamp": datetime.now().isoformat()
        }


class SAM2Detector(UIDetector):
    """
    基于 SAM2 (Segment Anything Model 2) 的 UI 检测器

    SAM2 提供强大的零样本分割能力，但不提供组件类型分类。
    适合与其他模型组合使用。

    [TODO] 待实现
    """

    def __init__(self, model_path: str = "sam2_hiera_large"):
        self.model_path = model_path
        raise NotImplementedError("SAM2Detector 尚未实现，请使用 OmniParserDetector")

    def detect(self, image_path: str) -> Dict:
        pass


def get_detector(detector_type: str = "omniparser", **kwargs) -> UIDetector:
    """
    获取检测器实例

    Args:
        detector_type: 检测器类型
            - "omniparser": OmniParser pip 包（需安装）
            - "omniparser_raw": 加载预解析的 JSON 文件（推荐）
            - "mock": 模拟检测器（测试用）
            - "sam2": SAM2 检测器（未实现）
        **kwargs: 传递给检测器的参数

    Returns:
        UIDetector 实例
    """
    detectors = {
        "omniparser": OmniParserDetector,
        "omniparser_raw": OmniParserRawDetector,
        "mock": MockDetector,
        "sam2": SAM2Detector,
    }

    if detector_type not in detectors:
        raise ValueError(f"未知的检测器类型: {detector_type}，可选: {list(detectors.keys())}")

    return detectors[detector_type](**kwargs)


def format_detection_result(detection: Dict, indent: str = "  ") -> str:
    """
    将检测结果格式化为可读文本

    Args:
        detection: 检测结果字典
        indent: 缩进字符串

    Returns:
        格式化的文本
    """
    lines = []
    w, h = detection.get("image_size", [0, 0])
    lines.append(f"画布尺寸: {w} x {h} px")
    lines.append(f"检测器: {detection.get('detector', 'unknown')}")
    lines.append(f"组件数量: {len(detection.get('components', []))}")
    lines.append("")

    for comp in detection.get("components", []):
        bbox = comp.get("bbox", [0, 0, 0, 0])
        x1, y1, x2, y2 = bbox
        comp_w, comp_h = x2 - x1, y2 - y1

        line = f"[{comp.get('type', 'unknown')}] "
        line += f"bbox:[{x1},{y1},{x2},{y2}] "
        line += f"尺寸:{comp_w}x{comp_h}px "
        line += f"置信度:{comp.get('confidence', 0):.2f}"

        if comp.get("text"):
            line += f" 文本:「{comp['text']}」"

        lines.append(line)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="UI 组件检测 - 使用 OmniParser 获取精确边界框",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 单张图片检测
  python ui_detector.py --image-path ./test.jpg

  # 指定输出目录
  python ui_detector.py --image-path ./test.jpg --output-dir ./outputs

  # 批量检测
  python ui_detector.py --images-dir ./screenshots --output-dir ./outputs

  # 使用 CPU 推理
  python ui_detector.py --image-path ./test.jpg --device cpu

  # 使用模拟检测器（测试用）
  python ui_detector.py --image-path ./test.jpg --detector mock
"""
    )

    # 输入参数
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--image-path", help="单个图片文件")
    input_group.add_argument("--images-dir", help="图片目录（批量处理）")

    # 输出参数
    parser.add_argument("--output-dir", default="./outputs", help="输出目录")

    # 检测器参数
    parser.add_argument(
        "--detector",
        default="omniparser",
        choices=["omniparser", "mock"],
        help="检测器类型"
    )
    parser.add_argument(
        "--device",
        default=os.environ.get("OMNIPARSER_DEVICE", "cuda"),
        help="推理设备 (cuda/cpu)"
    )
    parser.add_argument(
        "--model-path",
        default=os.environ.get("OMNIPARSER_MODEL_PATH"),
        help="模型路径（可选）"
    )

    # 输出选项
    parser.add_argument("--print", action="store_true", help="打印检测结果")

    args = parser.parse_args()

    # 初始化检测器
    print(f"=== UI Detector | {args.detector} ===\n")

    try:
        if args.detector == "omniparser":
            detector = get_detector(
                "omniparser",
                device=args.device,
                model_path=args.model_path
            )
        else:
            detector = get_detector("mock")
    except ImportError as e:
        print(f"[ERROR] {e}")
        print("\n使用 --detector mock 可跳过 OmniParser 进行测试")
        return

    # 确定输入文件列表
    if args.image_path:
        images = [Path(args.image_path)]
    else:
        images_dir = Path(args.images_dir)
        images = [
            f for f in sorted(images_dir.iterdir())
            if f.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}
        ]

    if not images:
        print("[WARN] 未找到图片文件")
        return

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    success, fail = 0, 0

    for i, img_path in enumerate(images, 1):
        print(f"[{i}/{len(images)}] {img_path.name}")

        try:
            # 检测
            result = detector.detect(str(img_path))

            # 保存
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = output_dir / f"{img_path.stem}_{ts}_detection.json"
            detector.save(result, str(output_file))

            print(f"  组件数: {len(result['components'])}")
            print(f"  输出: {output_file}")

            # 打印详情
            if args.print:
                print("\n" + format_detection_result(result) + "\n")

            success += 1

        except Exception as e:
            print(f"  [FAIL] {e}")
            fail += 1

        print()

    print(f"=== 完成: 成功 {success}, 失败 {fail} ===")


if __name__ == "__main__":
    main()
