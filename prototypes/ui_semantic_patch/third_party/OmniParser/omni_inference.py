"""
OmniParser 端到端推理脚本
输入图片路径，直接输出检测结果

Usage:
    # 命令行调用
    python omni_inference.py --image path/to/image.png --output results/

    # Python 调用
    from omni_inference import OmniParser
    parser = OmniParser()
    results = parser.parse("path/to/image.png")
"""

import argparse
import json
import os
import io
import base64
from pathlib import Path
from typing import Union, List, Dict, Optional
from dataclasses import dataclass, asdict

import torch
from PIL import Image

from util.utils import (
    check_ocr_box,
    get_yolo_model,
    get_caption_model_processor,
    get_som_labeled_img
)


@dataclass
class ParsedElement:
    """解析出的 UI 元素"""
    id: int
    type: str                    # 'text' | 'icon'
    bbox: List[float]            # [x1, y1, x2, y2] 归一化坐标
    content: str                 # 文本内容或图标描述
    interactivity: bool          # 是否可交互
    source: str                  # 来源标识


@dataclass
class ParseResult:
    """解析结果"""
    elements: List[ParsedElement]
    annotated_image: Optional[Image.Image]
    image_size: tuple            # (width, height)


class OmniParser:
    """OmniParser 端到端推理类"""

    def __init__(
        self,
        yolo_model_path: str = 'weights/icon_detect/model.pt',
        caption_model_path: str = 'weights/icon_caption_florence',
        caption_model_name: str = 'florence2',
        device: str = None
    ):
        """
        初始化 OmniParser

        Args:
            yolo_model_path: YOLO 模型路径
            caption_model_path: Caption 模型路径
            caption_model_name: Caption 模型类型 ('florence2' | 'blip2')
            device: 设备 ('cuda' | 'cpu')
        """
        if device is None:
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.device = device

        print(f"[OmniParser] Loading models on {device}...")

        # 加载 YOLO 模型
        self.yolo_model = get_yolo_model(yolo_model_path)
        self.yolo_model.to(device)

        # 加载 Caption 模型
        self.caption_model_processor = get_caption_model_processor(
            model_name=caption_model_name,
            model_name_or_path=caption_model_path,
            device=device
        )

        print("[OmniParser] Models loaded successfully.")

    def parse(
        self,
        image_source: Union[str, Image.Image],
        box_threshold: float = 0.05,
        iou_threshold: float = 0.7,
        use_paddleocr: bool = True,
        use_local_semantics: bool = True,
        return_annotated_image: bool = True
    ) -> ParseResult:
        """
        解析 UI 截图

        Args:
            image_source: 图片路径或 PIL Image 对象
            box_threshold: 检测置信度阈值 (0.01-1.0)
            iou_threshold: IOU 重叠过滤阈值 (0.01-1.0)
            use_paddleocr: 是否使用 PaddleOCR (否则用 EasyOCR)
            use_local_semantics: 是否生成图标语义描述
            return_annotated_image: 是否返回标注后的图片

        Returns:
            ParseResult: 包含解析元素列表和标注图片
        """
        # 加载图片
        if isinstance(image_source, str):
            image = Image.open(image_source).convert('RGB')
        else:
            image = image_source.convert('RGB')

        w, h = image.size

        # 计算绘图参数
        box_overlay_ratio = max(image.size) / 3200
        draw_bbox_config = {
            'text_scale': 0.8 * box_overlay_ratio,
            'text_thickness': max(int(2 * box_overlay_ratio), 1),
            'text_padding': max(int(3 * box_overlay_ratio), 1),
            'thickness': max(int(3 * box_overlay_ratio), 1),
        }

        # Step 1: OCR 文本检测
        ocr_bbox_rslt, _ = check_ocr_box(
            image,
            display_img=False,
            output_bb_format='xyxy',
            goal_filtering=None,
            easyocr_args={'paragraph': False, 'text_threshold': 0.9},
            use_paddleocr=use_paddleocr
        )
        text, ocr_bbox = ocr_bbox_rslt

        # Step 2: 图标检测 + 语义生成
        encoded_image, label_coordinates, parsed_content_list = get_som_labeled_img(
            image,
            self.yolo_model,
            BOX_TRESHOLD=box_threshold,
            output_coord_in_ratio=True,
            ocr_bbox=ocr_bbox,
            draw_bbox_config=draw_bbox_config,
            caption_model_processor=self.caption_model_processor,
            ocr_text=text,
            use_local_semantics=use_local_semantics,
            iou_threshold=iou_threshold,
            scale_img=False,
            batch_size=128
        )

        # 构建结果
        elements = []
        for i, item in enumerate(parsed_content_list):
            elements.append(ParsedElement(
                id=i,
                type=item.get('type', 'unknown'),
                bbox=item.get('bbox', []),
                content=item.get('content', ''),
                interactivity=item.get('interactivity', False),
                source=item.get('source', '')
            ))

        # 解码标注图片
        annotated_image = None
        if return_annotated_image:
            annotated_image = Image.open(io.BytesIO(base64.b64decode(encoded_image)))

        return ParseResult(
            elements=elements,
            annotated_image=annotated_image,
            image_size=(w, h)
        )

    def parse_to_dict(self, image_source: Union[str, Image.Image], **kwargs) -> dict:
        """解析并返回字典格式结果"""
        result = self.parse(image_source, **kwargs)
        return {
            'image_size': result.image_size,
            'element_count': len(result.elements),
            'elements': [asdict(e) for e in result.elements]
        }

    def parse_to_json(self, image_source: Union[str, Image.Image], **kwargs) -> str:
        """解析并返回 JSON 字符串"""
        return json.dumps(self.parse_to_dict(image_source, **kwargs), indent=2, ensure_ascii=False)


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description='OmniParser 端到端推理')
    parser.add_argument('--image', '-i', type=str, required=True, help='输入图片路径')
    parser.add_argument('--output', '-o', type=str, default='./output', help='输出目录')
    parser.add_argument('--box-threshold', type=float, default=0.05, help='检测置信度阈值')
    parser.add_argument('--iou-threshold', type=float, default=0.7, help='IOU 阈值')
    parser.add_argument('--no-paddleocr', action='store_true', help='使用 EasyOCR 替代 PaddleOCR')
    parser.add_argument('--no-semantics', action='store_true', help='禁用图标语义生成')
    parser.add_argument('--device', type=str, default=None, help='设备 (cuda/cpu)')
    parser.add_argument('--json-only', action='store_true', help='仅输出 JSON，不保存标注图片')

    args = parser.parse_args()

    # 创建输出目录
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 初始化解析器
    omni = OmniParser(device=args.device)

    # 执行解析
    result = omni.parse(
        args.image,
        box_threshold=args.box_threshold,
        iou_threshold=args.iou_threshold,
        use_paddleocr=not args.no_paddleocr,
        use_local_semantics=not args.no_semantics,
        return_annotated_image=not args.json_only
    )

    # 获取输入文件名
    input_name = Path(args.image).stem

    # 保存 JSON 结果
    json_path = output_dir / f'{input_name}_result.json'
    result_dict = {
        'image_size': result.image_size,
        'element_count': len(result.elements),
        'elements': [asdict(e) for e in result.elements]
    }
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result_dict, f, indent=2, ensure_ascii=False)
    print(f"[Output] JSON saved: {json_path}")

    # 保存标注图片
    if result.annotated_image:
        img_path = output_dir / f'{input_name}_annotated.png'
        result.annotated_image.save(img_path)
        print(f"[Output] Annotated image saved: {img_path}")

    # 打印摘要
    print(f"\n{'='*50}")
    print(f"解析完成: {args.image}")
    print(f"图片尺寸: {result.image_size[0]} x {result.image_size[1]}")
    print(f"检测元素: {len(result.elements)} 个")
    print(f"  - 文本框: {sum(1 for e in result.elements if e.type == 'text')} 个")
    print(f"  - 图标框: {sum(1 for e in result.elements if e.type == 'icon')} 个")
    print(f"{'='*50}")


if __name__ == '__main__':
    main()
