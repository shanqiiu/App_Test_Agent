"""
Text to HTML - 将img2text输出的结构化文本转换为HTML/CSS
"""

import argparse
import os
import re
import json
import requests
from typing import Dict, Tuple
from pathlib import Path
from datetime import datetime


def parse_structured_text(content: str) -> Dict:
    """解析img2text输出的结构化文本"""
    result = {"meta": {}, "global_style": {}, "regions": [], "elements": []}

    for line in content.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split('|')
        if len(parts) < 2:
            continue

        line_type = parts[0].upper()
        kv = {}
        for p in parts[1:]:
            if ':' in p:
                k, v = p.split(':', 1)
                kv[k.strip()] = v.strip()

        if line_type == 'META':
            result["meta"] = {
                "width": int(kv.get("width", 375)),
                "height": int(kv.get("height", 667)),
                "dpi": int(kv.get("dpi", 72))
            }
        elif line_type == 'GLOBAL':
            result["global_style"] = {
                "bg": kv.get("bg", "#FFFFFF"),
                "primary": kv.get("primary", "#1890FF"),
                "text": kv.get("text", "#333333"),
                "border": kv.get("border", "#E8E8E8")
            }
        elif line_type == 'REGION':
            result["regions"].append({
                "id": kv.get("id", "content"),
                "role": kv.get("role", "content"),
                "y": int(kv.get("y", 0)),
                "h": int(kv.get("h", 0)),
                "bg": kv.get("bg", "transparent")
            })
        elif line_type == 'EL':
            result["elements"].append({
                "region": kv.get("region", "content"),
                "type": kv.get("type", "text"),
                "x_pct": int(kv.get("x%", 0)),
                "y_pct": int(kv.get("y%", 0)),
                "w_pct": int(kv.get("w%", 0)),
                "h_pct": int(kv.get("h%", 0)),
                "bg": kv.get("bg", "transparent"),
                "fg": kv.get("fg", "#000000"),
                "radius": kv.get("radius", "0"),
                "border": kv.get("border", "none").replace('_', ' '),
                "content": kv.get("text", "").replace('_', ' ')
            })

    return result


def detect_format(content: str) -> str:
    """检测输入格式：structured(新格式) / json / text(旧格式)"""
    content = content.strip()

    # 检测新的结构化格式
    if content.startswith('META|') or '\nMETA|' in content:
        return "structured"

    # 检测JSON
    if content.startswith('{'):
        try:
            json.loads(content)
            return "json"
        except:
            pass

    return "text"


def extract_resolution(content: str, fmt: str) -> Tuple[int, int]:
    """提取分辨率"""
    if fmt == "structured":
        match = re.search(r'META\|width:(\d+)\|height:(\d+)', content)
        if match:
            return int(match.group(1)), int(match.group(2))

    if fmt == "json":
        try:
            data = json.loads(content)
            if "meta" in data:
                return data["meta"].get("width", 375), data["meta"].get("height", 667)
            if "canvas" in data:
                return data["canvas"].get("width", 375), data["canvas"].get("height", 667)
        except:
            pass

    # 通用正则匹配
    patterns = [
        r'width[:\s]*(\d+).*?height[:\s]*(\d+)',
        r'(\d+)\s*[x×]\s*(\d+)\s*(?:px|像素)',
    ]
    for p in patterns:
        m = re.search(p, content, re.IGNORECASE)
        if m:
            return int(m.group(1)), int(m.group(2))

    return 375, 667


SYSTEM_PROMPT = """你是UI还原专家，将结构化描述转换为高还原度HTML/CSS。

核心规则:
1. 单文件HTML，样式写在<style>标签内
2. .container 使用精确的像素尺寸，position:relative，overflow:hidden
3. 每个 REGION 使用 position:absolute，top/height 用像素值
4. 每个 EL 使用 position:absolute，所有坐标都是像素值（已预计算好）
5. 使用 Font Awesome 6.0 CDN: <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
6. 禁止使用外部CSS框架"""


def generate_prompt(content: str, fmt: str, resolution: Tuple[int, int]) -> str:
    """生成用户提示词，将百分比转换为像素值"""
    w, h = resolution

    if fmt == "structured":
        parsed = parse_structured_text(content)

        # 构建 region 字典，用于查找 region 的 y 和 h
        region_map = {r['id']: r for r in parsed['regions']}

        # 生成 CSS 代码片段
        css_lines = [
            f".container {{ width:{w}px; height:{h}px; position:relative; overflow:hidden; background:{parsed['global_style'].get('bg', '#FFF')}; }}",
        ]

        # REGION 样式
        for r in parsed['regions']:
            css_lines.append(
                f".{r['id']} {{ position:absolute; left:0; top:{r['y']}px; width:100%; height:{r['h']}px; background:{r['bg']}; }}"
            )

        # EL 样式 - 将百分比转换为像素
        el_styles = []
        for i, e in enumerate(parsed['elements']):
            region = region_map.get(e['region'], {'y': 0, 'h': h})
            region_h = region['h']
            region_w = w

            # 百分比转像素（相对于所属 REGION）
            el_x = int(e['x_pct'] * region_w / 100)
            el_y = int(e['y_pct'] * region_h / 100)
            el_w = int(e['w_pct'] * region_w / 100)
            el_h = int(e['h_pct'] * region_h / 100)

            el_id = f"el_{i}"
            style_parts = [
                f"position:absolute",
                f"left:{el_x}px",
                f"top:{el_y}px",
                f"width:{el_w}px",
                f"height:{el_h}px",
            ]
            if e['bg'] != 'transparent':
                style_parts.append(f"background:{e['bg']}")
            if e['fg'] != 'transparent':
                style_parts.append(f"color:{e['fg']}")
            if e['radius'] != '0':
                style_parts.append(f"border-radius:{e['radius']}px")
            if e['border'] != 'none':
                style_parts.append(f"border:{e['border']}")

            css_lines.append(f".{el_id} {{ {'; '.join(style_parts)}; }}")
            el_styles.append({
                'id': el_id,
                'region': e['region'],
                'type': e['type'],
                'content': e['content'],
                'x': el_x, 'y': el_y, 'w': el_w, 'h': el_h
            })

        # 生成 HTML 结构描述
        html_structure = ["<div class=\"container\">"]
        for r in parsed['regions']:
            html_structure.append(f"  <div class=\"{r['id']}\">")
            for el in el_styles:
                if el['region'] == r['id']:
                    if el['type'] == 'icon':
                        html_structure.append(f"    <i class=\"{el['id']} fa-solid fa-{el['content']}\"></i>")
                    elif el['type'] == 'image':
                        html_structure.append(f"    <div class=\"{el['id']}\" style=\"background:#DDD;\"></div>")
                    else:
                        html_structure.append(f"    <div class=\"{el['id']}\">{el['content']}</div>")
            html_structure.append(f"  </div>")
        html_structure.append("</div>")

        return f"""## 任务：根据以下规格生成完整HTML

### 画布尺寸（硬性约束）
{w}px × {h}px

### 预计算的CSS样式（直接使用，无需修改）
```css
{chr(10).join(css_lines)}
```

### HTML结构参考
```html
{chr(10).join(html_structure)}
```

### 输出要求
1. 输出完整HTML文件，包含<!DOCTYPE html>、<head>、<body>
2. 在<head>中引入Font Awesome CDN
3. 将上述CSS放入<style>标签
4. 将上述HTML结构放入<body>
5. 仅输出HTML代码，无markdown包裹，无解释

请直接输出完整HTML："""

    else:
        # JSON或旧文本格式
        return f"""## 任务：根据UI描述生成HTML

### 画布尺寸
{w}px × {h}px

### UI描述
{content}

### 要求
1. .container尺寸严格为{w}x{h}px，position:relative，overflow:hidden
2. 所有子元素使用position:absolute + 像素定位
3. 颜色使用描述中的HEX值
4. 图标用Font Awesome

仅输出完整HTML代码："""


class HTMLGenerator:
    def __init__(self, api_key: str, api_url: str, model: str = "qwen3-235b"):
        self.api_key, self.api_url, self.model = api_key, api_url, model
        self.headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def generate(self, content: str) -> Dict:
        fmt = detect_format(content)
        resolution = extract_resolution(content, fmt)

        resp = requests.post(self.api_url, headers=self.headers, verify=False, timeout=600, json={
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": generate_prompt(content, fmt, resolution)}
            ],
            "temperature": 0.2
        })
        resp.raise_for_status()

        html = resp.json()["choices"][0]["message"]["content"].strip()
        html = re.sub(r'^```html?\n?|```\n?$', '', html, flags=re.MULTILINE).strip()

        return {
            "html": html,
            "model": self.model,
            "timestamp": datetime.now().isoformat(),
            "resolution": {"width": resolution[0], "height": resolution[1]},
            "format": fmt
        }

    def save(self, result: Dict, output_dir: str, name: str) -> str:
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_file = path / f"{name}_{ts}.html"
        html_file.write_text(result["html"], encoding="utf-8")

        print(f"[OK] {html_file}")
        print(f"     Format: {result['format']}, Resolution: {result['resolution']['width']}x{result['resolution']['height']}px")
        return str(html_file)


def main():
    parser = argparse.ArgumentParser(description="UI Description to HTML")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--model", default="qwen3-235b")
    parser.add_argument("--input-file", required=True, help="输入文件(.txt/.json)")
    parser.add_argument("--output-dir", default="./dist_html")
    args = parser.parse_args()

    if not os.path.exists(args.input_file):
        print(f"[ERROR] Not found: {args.input_file}")
        return

    content = Path(args.input_file).read_text(encoding='utf-8')
    name = Path(args.input_file).stem

    print(f"--- {name} ({len(content)} chars) ---")

    try:
        generator = HTMLGenerator(args.api_key, args.api_url, args.model)
        result = generator.generate(content)
        generator.save(result, args.output_dir, name)
    except Exception as e:
        print(f"[FAIL] {e}")


if __name__ == "__main__":
    main()
