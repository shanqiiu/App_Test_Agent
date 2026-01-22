"""
Image to Text - UI截图结构化描述工具
将UI截图转换为结构化文本，用于后续HTML/CSS生成
"""

import base64
import requests
import os
import argparse
import json
from typing import Dict, Optional, List, Tuple
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
        self.color_mode: str = "RGB"
        self.has_alpha: bool = False
        self.bit_depth: int = 8
        self.format: str = ""
        self._extract()

    def _extract(self):
        if Image is None:
            return
        try:
            with Image.open(self.path) as img:
                self.width, self.height = img.size
                self.format = img.format or Path(self.path).suffix.upper().replace(".", "")
                self.color_mode = img.mode
                self.has_alpha = img.mode in ("RGBA", "LA", "PA")
                if "dpi" in img.info:
                    self.dpi = img.info["dpi"]
                elif "jfif_density" in img.info:
                    self.dpi = img.info["jfif_density"]
                self.bit_depth = {"1": 1, "L": 8, "P": 8, "RGB": 24, "YCbCr": 24, "RGBA": 32, "CMYK": 32}.get(img.mode, 8)
        except Exception as e:
            print(f"[WARN] Failed to extract metadata: {e}")

    def to_dict(self) -> Dict:
        return {
            "width": self.width,
            "height": self.height,
            "dpi": list(self.dpi) if isinstance(self.dpi, tuple) else [self.dpi, self.dpi],
            "color_mode": self.color_mode,
            "has_alpha": self.has_alpha,
            "bit_depth": self.bit_depth,
            "format": self.format,
            "aspect_ratio": round(self.width / self.height, 4) if self.height else 0
        }


def get_prompt(metadata: ImageMetadata) -> str:
    """生成结构化文本输出的提示词"""
    w, h = metadata.width, metadata.height
    dpi = metadata.dpi[0] if isinstance(metadata.dpi, (list, tuple)) else metadata.dpi

    return f"""# Role
你是UI还原专家，将截图精确描述为结构化文本。

# 图片信息
- 尺寸: {w} x {h} px
- DPI: {dpi}

# 输出格式（每行一个对象，|分隔字段）

META|width:{w}|height:{h}|dpi:{dpi}
GLOBAL|bg:背景色|primary:主色|text:正文色|border:边框色
REGION|id:区域名|role:角色|y:起始Y像素|h:高度像素|bg:背景色
EL|region:所属区域|type:类型|x%:X百分比|y%:Y百分比|w%:宽百分比|h%:高百分比|bg:背景色|fg:前景色|radius:圆角|border:边框|text:内容

# 字段说明
- REGION的y/h: 绝对像素值（区域需精确划分）
- EL的x%/y%/w%/h%: 相对于所属REGION的百分比(0-100)，更易估算且适配不同分辨率
- radius: 圆角像素，无圆角填0
- border: 边框如"1px solid #EEE"，无边框填none

# 约束
1. 区域高度之和={h}，底部区域y+h={h}
2. 颜色用#RRGGBB，透明用transparent
3. 百分比为整数(0-100)，表示相对于所属区域的比例
4. 只输出格式化内容

# 示例
META|width:1080|height:2340|dpi:72
GLOBAL|bg:#FFFFFF|primary:#1890FF|text:#333333|border:#E8E8E8
REGION|id:status_bar|role:status_bar|y:0|h:44|bg:#FFFFFF
REGION|id:app_bar|role:app_bar|y:44|h:56|bg:#FFFFFF
REGION|id:content|role:content|y:100|h:2156|bg:#F5F5F5
REGION|id:tab_bar|role:bottom_nav|y:2256|h:84|bg:#FFFFFF
EL|region:app_bar|type:icon|x%:1|y%:28|w%:4|h%:43|bg:transparent|fg:#333|radius:0|border:none|text:back
EL|region:content|type:container|x%:1|y%:1|w%:98|h%:6|bg:#FFF|fg:transparent|radius:8|border:1px_solid_#EEE|text:card
EL|region:tab_bar|type:icon|x%:10|y%:15|w%:8|h%:50|bg:transparent|fg:#999|radius:0|border:none|text:home"""


class UITextParser:
    """解析结构化文本输出"""

    def __init__(self, canvas_w: int, canvas_h: int):
        self.canvas_w, self.canvas_h = canvas_w, canvas_h
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def parse(self, text: str) -> Dict:
        self.errors.clear()
        self.warnings.clear()
        result = {"meta": {}, "global_style": {}, "regions": [], "elements": [], "_raw_text": text}

        for line_num, line in enumerate([l.strip() for l in text.split('\n') if l.strip()], 1):
            if line.startswith('#') or line.startswith('//'):
                continue
            parts = line.split('|')
            if len(parts) < 2:
                continue
            line_type = parts[0].upper()
            try:
                if line_type == 'META':
                    result["meta"] = self._parse_kv_int(parts[1:], ["width", "height", "dpi"])
                elif line_type == 'GLOBAL':
                    kv = self._parse_kv(parts[1:])
                    result["global_style"] = {
                        "background_color": kv.get("bg", "#FFFFFF"),
                        "primary_color": kv.get("primary", "#000000"),
                        "text_color": kv.get("text", "#333333"),
                        "border_color": kv.get("border", "#E8E8E8")
                    }
                elif line_type == 'REGION':
                    kv = self._parse_kv(parts[1:])
                    if kv.get("id"):
                        result["regions"].append({
                            "id": kv["id"], "role": kv.get("role", "content"),
                            "y": int(kv.get("y", 0)), "height": int(kv.get("h", 0)),
                            "background_color": kv.get("bg", "transparent")
                        })
                elif line_type == 'EL':
                    kv = self._parse_kv(parts[1:])
                    result["elements"].append({
                        "region": kv.get("region", "content"), "type": kv.get("type", "text"),
                        "x_pct": int(kv.get("x%", 0)), "y_pct": int(kv.get("y%", 0)),
                        "w_pct": int(kv.get("w%", 0)), "h_pct": int(kv.get("h%", 0)),
                        "background_color": kv.get("bg", "transparent"),
                        "foreground_color": kv.get("fg", "#000000"),
                        "border_radius": kv.get("radius", "0"),
                        "border": kv.get("border", "none").replace('_', ' '),
                        "content": kv.get("text", "").replace('_', ' ')
                    })
            except Exception as e:
                self.errors.append(f"Line {line_num}: {e}")

        self._validate(result)
        result["_parse_errors"], result["_parse_warnings"] = self.errors, self.warnings
        return result

    def _parse_kv(self, parts: List[str]) -> Dict[str, str]:
        return {k.strip(): v.strip() for p in parts if ':' in p for k, v in [p.split(':', 1)]}

    def _parse_kv_int(self, parts: List[str], int_keys: List[str]) -> Dict:
        kv = self._parse_kv(parts)
        return {k: int(v) if k in int_keys else v for k, v in kv.items()}

    def _validate(self, result: Dict):
        meta = result.get("meta", {})
        if meta.get("width", 0) != self.canvas_w:
            self.warnings.append(f"Meta width mismatch: {meta.get('width')} vs {self.canvas_w}")
        if meta.get("height", 0) != self.canvas_h:
            self.warnings.append(f"Meta height mismatch: {meta.get('height')} vs {self.canvas_h}")
        regions = result.get("regions", [])
        if regions:
            total_h = sum(r.get("height", 0) for r in regions)
            if total_h != self.canvas_h:
                self.warnings.append(f"Regions height sum {total_h} != {self.canvas_h}")


class ImageAnalyzer:
    def __init__(self, api_key: str, api_url: str, model: str = "qwen3-vl-30b-20251224164003"):
        self.api_key, self.api_url, self.model = api_key, api_url, model
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def encode_image(self, path: str) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')

    def analyze_image(self, image_base64: str, prompt: str) -> Dict:
        resp = requests.post(self.api_url, headers=self.headers, verify=False, json={
            "model": self.model,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                {"type": "text", "text": prompt}
            ]}],
            "max_tokens": 8192, "temperature": 0.1
        })
        resp.raise_for_status()
        return {"text": resp.json()["choices"][0]["message"]["content"], "model": self.model, "timestamp": datetime.now().isoformat()}

    def save_result(self, result: Dict, name: str, output_dir: str, metadata: ImageMetadata, validate: bool = True) -> str:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        raw_text = result.get("text", "")

        txt_path = output_path / f"{name}_{ts}.txt"
        txt_path.write_text(raw_text, encoding="utf-8")
        print(f"[SAVED] {txt_path}")

        if validate:
            parser = UITextParser(metadata.width, metadata.height)
            parsed = parser.parse(raw_text)
            parsed["_image_metadata"] = metadata.to_dict()
            parsed["_model_info"] = {"model": result.get("model"), "timestamp": result.get("timestamp")}

            json_path = output_path / f"{name}_{ts}.json"
            json_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")

            if parser.errors:
                print(f"[ERROR] {len(parser.errors)} errors")
            if parser.warnings:
                print(f"[WARN] {len(parser.warnings)} warnings")
            print(f"[OK] {json_path} (regions:{len(parsed['regions'])}, elements:{len(parsed['elements'])})")
            return str(json_path)
        return str(txt_path)


def analyze_single_file(analyzer: ImageAnalyzer, image_path: str, output_dir: str, validate: bool = True) -> Optional[str]:
    if not os.path.exists(image_path):
        print(f"[ERROR] Not found: {image_path}")
        return None

    metadata = ImageMetadata(image_path)
    if not metadata.width or not metadata.height:
        print(f"[SKIP] No metadata: {image_path}")
        return None

    name = Path(image_path).stem
    print(f"--- {name} ({metadata.width}x{metadata.height}) ---")

    try:
        result = analyzer.analyze_image(analyzer.encode_image(image_path), get_prompt(metadata))
        return analyzer.save_result(result, name, output_dir, metadata, validate)
    except Exception as e:
        print(f"[FAIL] {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="UI Image to Structured Text")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--model", default="qwen3-vl-30b-20251224164003")
    parser.add_argument("--image-path", help="Single image")
    parser.add_argument("--images-dir", default="./origin_imgs")
    parser.add_argument("--output-dir", default="./output_json")
    parser.add_argument("--no-validate", action="store_true")
    args = parser.parse_args()

    print(f"=== UI Analyzer | Model: {args.model} | Validate: {not args.no_validate} ===")
    analyzer = ImageAnalyzer(args.api_key, args.api_url, args.model)

    if args.image_path:
        analyze_single_file(analyzer, args.image_path, args.output_dir, not args.no_validate)
    else:
        images = [f for f in sorted(Path(args.images_dir).iterdir()) if f.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}]
        if not images:
            print(f"[WARN] No images in {args.images_dir}")
            return
        for i, img in enumerate(images, 1):
            print(f"\n[{i}/{len(images)}]")
            analyze_single_file(analyzer, str(img), args.output_dir, not args.no_validate)


if __name__ == "__main__":
    main()
