"""
Image to Text - UI截图描述工具
将UI截图转换为描述性文本，供LLM生成HTML
"""

import base64
import requests
import os
import argparse
import json
from typing import Dict, Optional, Tuple
from pathlib import Path
from datetime import datetime
try:
    from PIL import Image
except ImportError:
    Image = None


class ImageMetadata:
    """提取图片元信息"""

    def __init__(self, image_path: str):
        self.path = image_path
        self.width: int = 0
        self.height: int = 0
        self.dpi: Tuple[int, int] = (72, 72)
        self.format: str = ""
        self._extract()

    def _extract(self):
        if Image is None:
            return
        try:
            with Image.open(self.path) as img:
                self.width, self.height = img.size
                self.format = img.format or Path(self.path).suffix.upper().replace(".", "")
                if "dpi" in img.info:
                    self.dpi = img.info["dpi"]
        except Exception as e:
            print(f"[WARN] {e}")

    def to_dict(self) -> Dict:
        return {"width": self.width, "height": self.height, "format": self.format}


def get_prompt(metadata: ImageMetadata) -> str:
    """生成描述性文本的提示词"""
    w, h = metadata.width, metadata.height

    return f"""你是一位专业的UI设计分析师。请详细描述这张手机App截图的界面布局和视觉设计。

## 图片信息
- 分辨率: {w} x {h} 像素

## 请按以下结构描述

### 1. 整体概述
- 这是什么类型的页面（首页/列表页/详情页/设置页等）
- 整体配色风格（主色调、背景色、强调色）
- 页面的主要功能

### 2. 页面结构（从上到下）

#### 顶部区域
- 状态栏：背景色、高度估计
- 导航栏/标题栏：背景色、标题文字、左右按钮/图标

#### 主体内容区
- 背景色
- 包含哪些模块/卡片/列表
- 每个模块的：
  - 布局方式（横向排列/纵向排列/网格）
  - 包含的元素（图标、文字、图片、按钮等）
  - 主要颜色

#### 底部区域（如有）
- 底部导航栏/TabBar
- 包含几个选项卡，每个的图标和文字
- 当前选中项的样式

### 3. 关键视觉元素
- 使用的图标风格（线性/填充/彩色）
- 文字层级（标题/正文/辅助文字的大小和颜色差异）
- 圆角使用情况
- 阴影/分割线的使用
- 间距和留白特点

### 4. 交互元素
- 按钮样式（形状、颜色、文字）
- 输入框样式
- 可点击区域的视觉提示

请用清晰、具体的语言描述，包含颜色值（如#FFFFFF）和尺寸估计（如约50px高），以便后续还原为HTML/CSS。"""


class ImageAnalyzer:
    def __init__(self, api_key: str, api_url: str, model: str = "qwen3-vl-30b"):
        self.api_key, self.api_url, self.model = api_key, api_url, model
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def encode_image(self, path: str) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')

    def analyze(self, image_path: str) -> Dict:
        metadata = ImageMetadata(image_path)
        if not metadata.width:
            raise ValueError("Cannot read image")

        resp = requests.post(self.api_url, headers=self.headers, verify=False, json={
            "model": self.model,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{self.encode_image(image_path)}"}},
                {"type": "text", "text": get_prompt(metadata)}
            ]}],
            "max_tokens": 4096,
            "temperature": 0.3
        })
        resp.raise_for_status()

        return {
            "description": resp.json()["choices"][0]["message"]["content"],
            "metadata": metadata.to_dict(),
            "model": self.model,
            "timestamp": datetime.now().isoformat()
        }

    def save(self, result: Dict, name: str, output_dir: str) -> str:
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 保存描述文本
        txt_file = path / f"{name}_{ts}.txt"
        content = f"""# UI Description
# Resolution: {result['metadata']['width']} x {result['metadata']['height']}
# Model: {result['model']}
# Time: {result['timestamp']}

{result['description']}
"""
        txt_file.write_text(content, encoding="utf-8")
        print(f"[OK] {txt_file}")

        # 保存元信息JSON
        json_file = path / f"{name}_{ts}.json"
        json_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        return str(txt_file)


def main():
    parser = argparse.ArgumentParser(description="UI Screenshot to Description")
    parser.add_argument("--api-url", default="https://api.openai-next.com/v1/chat/completions")
    parser.add_argument("--api-key", default="sk-K9B2ccVeW4VdAcobD53b16E06b104aA1B5A82593FdFb2557")
    parser.add_argument("--model", default="qwen-vl-max")
    parser.add_argument("--image-path", help="Single image file")
    parser.add_argument("--images-dir", default="./images", help="Directory of images")
    parser.add_argument("--output-dir", default="./outputs")
    args = parser.parse_args()

    analyzer = ImageAnalyzer(args.api_key, args.api_url, args.model)
    print(f"=== img2text | Model: {args.model} ===\n")

    if args.image_path:
        images = [Path(args.image_path)]
    else:
        images = [f for f in sorted(Path(args.images_dir).iterdir())
                  if f.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}]

    if not images:
        print(f"[WARN] No images found")
        return

    for i, img in enumerate(images, 1):
        print(f"[{i}/{len(images)}] {img.name}")
        try:
            result = analyzer.analyze(str(img))
            analyzer.save(result, img.stem, args.output_dir)
        except Exception as e:
            print(f"[FAIL] {e}")
        print()


if __name__ == "__main__":
    main()
