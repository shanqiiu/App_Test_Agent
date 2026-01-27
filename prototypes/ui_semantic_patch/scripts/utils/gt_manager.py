#!/usr/bin/env python3
"""
gt_manager.py - Ground Truth 管理与利用

利用真实异常UI截图（GT）优化生成效果：
1. 组件模板提取 - 从GT中裁剪弹窗/Toast作为模板
2. 风格分析 - 提取GT的颜色、圆角等特征
3. Few-shot参考 - 将GT作为VLM的示例输入
"""

import json
import os
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from PIL import Image
import numpy as np
from collections import Counter


class GTManager:
    """
    Ground Truth 管理器

    目录结构:
    assets/gt_samples/
    ├── dialogs/              # 弹窗GT
    │   ├── error_01.png
    │   ├── error_01.json     # 元数据（bounds, style等）
    │   └── ...
    ├── toasts/               # Toast GT
    │   ├── network_error.png
    │   └── ...
    └── index.json            # GT索引
    """

    def __init__(self, gt_dir: str):
        """
        初始化GT管理器

        Args:
            gt_dir: GT样本目录路径
        """
        self.gt_dir = Path(gt_dir)
        self.gt_dir.mkdir(parents=True, exist_ok=True)

        # 子目录
        self.dialogs_dir = self.gt_dir / "dialogs"
        self.toasts_dir = self.gt_dir / "toasts"
        self.loadings_dir = self.gt_dir / "loadings"

        for d in [self.dialogs_dir, self.toasts_dir, self.loadings_dir]:
            d.mkdir(exist_ok=True)

        # 加载索引
        self.index_path = self.gt_dir / "index.json"
        self.index = self._load_index()

    def _load_index(self) -> dict:
        """加载GT索引"""
        if self.index_path.exists():
            with open(self.index_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"dialogs": [], "toasts": [], "loadings": []}

    def _save_index(self):
        """保存GT索引"""
        with open(self.index_path, 'w', encoding='utf-8') as f:
            json.dump(self.index, f, ensure_ascii=False, indent=2)

    # ==================== 模板提取 ====================

    def extract_component_from_gt(
        self,
        gt_image_path: str,
        bounds: Dict[str, int],
        component_type: str,
        style: str = "default",
        name: Optional[str] = None
    ) -> str:
        """
        从GT截图中裁剪组件作为模板

        Args:
            gt_image_path: GT截图路径
            bounds: 组件边界 {"x": 0, "y": 0, "width": 100, "height": 50}
            component_type: 组件类型 (dialog/toast/loading)
            style: 样式标签 (error/warning/info/success)
            name: 模板名称（可选）

        Returns:
            保存的模板路径
        """
        # 打开GT图片
        gt_image = Image.open(gt_image_path).convert('RGBA')

        # 裁剪组件区域
        x, y, w, h = bounds['x'], bounds['y'], bounds['width'], bounds['height']
        component = gt_image.crop((x, y, x + w, y + h))

        # 确定保存路径
        type_dir = {
            'dialog': self.dialogs_dir,
            'toast': self.toasts_dir,
            'loading': self.loadings_dir
        }.get(component_type.lower(), self.gt_dir)

        if name is None:
            existing = list(type_dir.glob(f"{style}_*.png"))
            name = f"{style}_{len(existing) + 1:02d}"

        template_path = type_dir / f"{name}.png"
        meta_path = type_dir / f"{name}.json"

        # 保存模板图片
        component.save(template_path)

        # 保存元数据
        meta = {
            "source": str(gt_image_path),
            "bounds": bounds,
            "type": component_type,
            "style": style,
            "size": {"width": w, "height": h},
            "dominant_colors": self._extract_dominant_colors(component)
        }
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        # 更新索引
        type_key = f"{component_type.lower()}s"
        if type_key not in self.index:
            self.index[type_key] = []
        self.index[type_key].append({
            "name": name,
            "style": style,
            "path": str(template_path.relative_to(self.gt_dir)),
            "size": {"width": w, "height": h}
        })
        self._save_index()

        print(f"✓ 模板已保存: {template_path}")
        return str(template_path)

    def get_template(
        self,
        component_type: str,
        style: str = None,
        target_size: Tuple[int, int] = None
    ) -> Optional[Image.Image]:
        """
        获取匹配的模板

        Args:
            component_type: 组件类型
            style: 样式（可选，None则返回任意匹配的）
            target_size: 目标尺寸 (width, height)

        Returns:
            模板图片，如果没有匹配则返回None
        """
        type_key = f"{component_type.lower()}s"
        templates = self.index.get(type_key, [])

        if not templates:
            return None

        # 筛选匹配的模板
        candidates = templates
        if style:
            candidates = [t for t in templates if t.get('style') == style]
            if not candidates:
                candidates = templates  # 回退到所有模板

        # 选择尺寸最接近的
        if target_size and len(candidates) > 1:
            target_w, target_h = target_size
            candidates.sort(key=lambda t: abs(t['size']['width'] - target_w) + abs(t['size']['height'] - target_h))

        # 加载模板
        template_info = candidates[0]
        template_path = self.gt_dir / template_info['path']

        if template_path.exists():
            img = Image.open(template_path).convert('RGBA')
            # 调整到目标尺寸
            if target_size and img.size != target_size:
                img = img.resize(target_size, Image.Resampling.LANCZOS)
            return img

        return None

    # ==================== 风格分析 ====================

    def _extract_dominant_colors(self, image: Image.Image, n_colors: int = 5) -> List[str]:
        """提取图片的主要颜色"""
        # 缩小图片加速处理
        small = image.resize((50, 50), Image.Resampling.NEAREST)
        pixels = list(small.getdata())

        # 过滤透明像素
        if image.mode == 'RGBA':
            pixels = [p[:3] for p in pixels if p[3] > 128]
        else:
            pixels = [p[:3] if len(p) >= 3 else (p[0], p[0], p[0]) for p in pixels]

        if not pixels:
            return []

        # 量化颜色（减少颜色数量）
        quantized = []
        for r, g, b in pixels:
            qr = (r // 32) * 32
            qg = (g // 32) * 32
            qb = (b // 32) * 32
            quantized.append((qr, qg, qb))

        # 统计最常见的颜色
        counter = Counter(quantized)
        top_colors = counter.most_common(n_colors)

        # 转换为十六进制
        return [f"#{r:02x}{g:02x}{b:02x}" for (r, g, b), _ in top_colors]

    def analyze_gt_style(self, gt_image_path: str, bounds: Dict[str, int] = None) -> dict:
        """
        分析GT的视觉风格

        Args:
            gt_image_path: GT图片路径
            bounds: 分析区域（可选，None则分析整图）

        Returns:
            风格特征字典
        """
        image = Image.open(gt_image_path).convert('RGBA')

        if bounds:
            x, y, w, h = bounds['x'], bounds['y'], bounds['width'], bounds['height']
            image = image.crop((x, y, x + w, y + h))

        # 提取颜色
        dominant_colors = self._extract_dominant_colors(image)

        # 分析背景色（通常是边缘像素）
        pixels = np.array(image)
        edge_pixels = np.concatenate([
            pixels[0, :, :3],      # 上边
            pixels[-1, :, :3],     # 下边
            pixels[:, 0, :3],      # 左边
            pixels[:, -1, :3]      # 右边
        ])
        bg_color = tuple(edge_pixels.mean(axis=0).astype(int))
        bg_hex = f"#{bg_color[0]:02x}{bg_color[1]:02x}{bg_color[2]:02x}"

        # 检测是否有圆角（简化：检查角落透明度）
        has_rounded_corners = False
        if image.mode == 'RGBA':
            corners = [
                image.getpixel((0, 0))[3],
                image.getpixel((image.width-1, 0))[3],
                image.getpixel((0, image.height-1))[3],
                image.getpixel((image.width-1, image.height-1))[3]
            ]
            has_rounded_corners = any(c < 128 for c in corners)

        return {
            "dominant_colors": dominant_colors,
            "background_color": bg_hex,
            "has_rounded_corners": has_rounded_corners,
            "size": {"width": image.width, "height": image.height}
        }

    # ==================== Few-shot 参考 ====================

    def get_fewshot_examples(
        self,
        component_type: str,
        max_examples: int = 2
    ) -> List[dict]:
        """
        获取Few-shot示例，用于VLM提示

        Args:
            component_type: 组件类型
            max_examples: 最大示例数

        Returns:
            示例列表，每个包含图片路径和描述
        """
        type_key = f"{component_type.lower()}s"
        templates = self.index.get(type_key, [])[:max_examples]

        examples = []
        for t in templates:
            template_path = self.gt_dir / t['path']
            meta_path = template_path.with_suffix('.json')

            example = {
                "image_path": str(template_path),
                "style": t.get('style', 'default'),
                "size": t.get('size', {})
            }

            # 加载元数据
            if meta_path.exists():
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                    example["dominant_colors"] = meta.get("dominant_colors", [])

            examples.append(example)

        return examples

    def build_fewshot_prompt(
        self,
        component_type: str,
        instruction: str
    ) -> str:
        """
        构建包含GT参考的提示词

        Args:
            component_type: 组件类型
            instruction: 原始指令

        Returns:
            增强的提示词
        """
        examples = self.get_fewshot_examples(component_type)

        if not examples:
            return instruction

        # 构建风格描述
        style_hints = []
        for ex in examples:
            colors = ex.get('dominant_colors', [])
            if colors:
                style_hints.append(f"颜色方案: {', '.join(colors[:3])}")

        style_desc = "; ".join(style_hints) if style_hints else ""

        enhanced_prompt = f"""{instruction}

参考风格要求:
- 组件类型: {component_type}
- {style_desc}
- 请生成与参考风格一致的组件"""

        return enhanced_prompt


def create_gt_from_annotation(
    screenshot_path: str,
    annotation: dict,
    gt_manager: GTManager
) -> List[str]:
    """
    从标注数据批量创建GT模板

    Args:
        screenshot_path: 原始截图路径
        annotation: 标注数据，格式:
            {
                "components": [
                    {"type": "dialog", "style": "error", "bounds": {...}},
                    {"type": "toast", "style": "warning", "bounds": {...}}
                ]
            }
        gt_manager: GT管理器

    Returns:
        创建的模板路径列表
    """
    created = []
    for comp in annotation.get('components', []):
        path = gt_manager.extract_component_from_gt(
            gt_image_path=screenshot_path,
            bounds=comp['bounds'],
            component_type=comp['type'],
            style=comp.get('style', 'default')
        )
        created.append(path)
    return created


# ==================== 命令行工具 ====================

def main():
    import argparse

    parser = argparse.ArgumentParser(description='GT管理工具')
    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # extract 子命令
    extract_parser = subparsers.add_parser('extract', help='从GT提取组件模板')
    extract_parser.add_argument('--image', '-i', required=True, help='GT截图路径')
    extract_parser.add_argument('--bounds', '-b', required=True,
                                help='边界框 "x,y,width,height"')
    extract_parser.add_argument('--type', '-t', required=True,
                                choices=['dialog', 'toast', 'loading'],
                                help='组件类型')
    extract_parser.add_argument('--style', '-s', default='default',
                                help='样式标签')
    extract_parser.add_argument('--gt-dir', default='../assets/gt_samples',
                                help='GT目录')

    # analyze 子命令
    analyze_parser = subparsers.add_parser('analyze', help='分析GT风格')
    analyze_parser.add_argument('--image', '-i', required=True, help='GT截图路径')
    analyze_parser.add_argument('--bounds', '-b', help='边界框 "x,y,width,height"')

    # list 子命令
    list_parser = subparsers.add_parser('list', help='列出已有模板')
    list_parser.add_argument('--gt-dir', default='../assets/gt_samples', help='GT目录')

    args = parser.parse_args()

    if args.command == 'extract':
        # 解析bounds
        x, y, w, h = map(int, args.bounds.split(','))
        bounds = {"x": x, "y": y, "width": w, "height": h}

        gt_manager = GTManager(args.gt_dir)
        gt_manager.extract_component_from_gt(
            gt_image_path=args.image,
            bounds=bounds,
            component_type=args.type,
            style=args.style
        )

    elif args.command == 'analyze':
        bounds = None
        if args.bounds:
            x, y, w, h = map(int, args.bounds.split(','))
            bounds = {"x": x, "y": y, "width": w, "height": h}

        gt_manager = GTManager('.')
        style = gt_manager.analyze_gt_style(args.image, bounds)
        print(json.dumps(style, indent=2, ensure_ascii=False))

    elif args.command == 'list':
        gt_manager = GTManager(args.gt_dir)
        print(json.dumps(gt_manager.index, indent=2, ensure_ascii=False))

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
