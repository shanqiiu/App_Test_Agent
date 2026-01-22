"""
Text to HTML - 将UI描述文本转换为HTML/CSS
接收img2text.py生成的描述性文本，通过LLM生成可渲染的HTML
"""

import argparse
import os
import re
import json
import requests
from typing import Dict, Tuple
from pathlib import Path
from datetime import datetime


def extract_resolution(content: str) -> Tuple[int, int]:
    """从描述文本中提取分辨率"""
    patterns = [
        r'分辨率[:\s]*(\d+)\s*[x×]\s*(\d+)',
        r'Resolution[:\s]*(\d+)\s*[x×]\s*(\d+)',
        r'(\d+)\s*[x×]\s*(\d+)\s*(?:px|像素)',
        r'width[:\s]*(\d+).*?height[:\s]*(\d+)',
    ]
    for p in patterns:
        m = re.search(p, content, re.IGNORECASE)
        if m:
            return int(m.group(1)), int(m.group(2))
    return 375, 667


def get_system_prompt() -> str:
    """系统提示词"""
    return """你是UI还原专家，擅长将UI描述文本转换为高保真HTML/CSS。

## 核心规则

### 1. 文件结构
- 单文件HTML，所有CSS写在<style>标签内
- 引入 Font Awesome 6.0 CDN 用于图标
- 禁止使用外部CSS框架（如Bootstrap、Tailwind）

### 2. 布局规范
- `.container` 为根容器，使用精确像素尺寸，`position:relative`，`overflow:hidden`
- 功能区域（状态栏、导航栏、内容区、底部导航）使用 `position:absolute` + 像素定位
- 区域内元素根据描述选择合适的布局方式（flex/grid/absolute）

### 3. 样式还原
- 颜色：使用描述中的HEX色值，如 #FFFFFF、#1890FF
- 尺寸：根据描述估算像素值，确保比例协调
- 圆角：根据描述应用 border-radius
- 阴影：如描述提到阴影，使用 box-shadow
- 字体：系统字体栈，区分标题/正文/辅助文字大小

### 4. 图标处理
- 使用 Font Awesome 图标代替实际图标
- 根据描述选择语义相近的图标
- 示例：首页→fa-home，设置→fa-gear，搜索→fa-search

### 5. 图片占位
- 图片区域使用灰色背景占位 (#E5E5E5 或 #DDD)
- 保持描述中的宽高比

## 输出要求
- 仅输出完整HTML代码
- 不要用markdown代码块包裹
- 不要添加任何解释文字"""


def generate_prompt(content: str, resolution: Tuple[int, int]) -> str:
    """生成用户提示词"""
    w, h = resolution

    return f"""## 任务：根据以下UI描述生成完整HTML

### 画布尺寸（硬性约束）
宽度：{w}px
高度：{h}px

.container 必须严格使用此尺寸：
```css
.container {{
    width: {w}px;
    height: {h}px;
    position: relative;
    overflow: hidden;
}}
```

### UI描述
{content}

### 输出要求
1. 输出完整HTML文件，包含 <!DOCTYPE html>、<head>、<body>
2. 在<head>中引入 Font Awesome CDN：
   <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
3. 所有CSS写在<style>标签内
4. 根据描述精确还原布局、颜色、间距
5. 仅输出HTML代码，无markdown包裹，无解释

请直接输出完整HTML："""


class HTMLGenerator:
    def __init__(self, api_key: str, api_url: str, model: str = "qwen3-235b"):
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
        self.headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def generate(self, content: str) -> Dict:
        """调用LLM生成HTML"""
        resolution = extract_resolution(content)

        resp = requests.post(self.api_url, headers=self.headers, verify=False, timeout=600, json={
            "model": self.model,
            "messages": [
                {"role": "system", "content": get_system_prompt()},
                {"role": "user", "content": generate_prompt(content, resolution)}
            ],
            "temperature": 0.2,
            "max_tokens": 8192
        })
        resp.raise_for_status()

        html = resp.json()["choices"][0]["message"]["content"].strip()
        # 移除可能的markdown代码块包裹
        html = re.sub(r'^```html?\n?|```\n?$', '', html, flags=re.MULTILINE).strip()

        return {
            "html": html,
            "model": self.model,
            "timestamp": datetime.now().isoformat(),
            "resolution": {"width": resolution[0], "height": resolution[1]}
        }

    def save(self, result: Dict, output_dir: str, name: str) -> str:
        """保存生成的HTML"""
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_file = path / f"{name}_{ts}.html"
        html_file.write_text(result["html"], encoding="utf-8")

        # 保存元信息JSON（供html2img使用）
        json_file = path / f"{name}_{ts}.json"
        meta = {
            "model": result["model"],
            "timestamp": result["timestamp"],
            "resolution": result["resolution"]
        }
        json_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"[OK] {html_file}")
        print(f"     Resolution: {result['resolution']['width']}x{result['resolution']['height']}px")
        return str(html_file)


def main():
    parser = argparse.ArgumentParser(description="UI Description to HTML")
    parser.add_argument("--api-url", default="https://api.openai-next.com/v1/chat/completions")
    parser.add_argument("--api-key", default="sk-K9B2ccVeW4VdAcobD53b16E06b104aA1B5A82593FdFb2557")
    parser.add_argument("--model", default="qwen3-235b-a22b")
    parser.add_argument("--input-file", help="单个输入文件(.txt)")
    parser.add_argument("--input-dir", help="输入目录，处理所有.txt文件")
    parser.add_argument("--output-dir", default="./dist_html")
    args = parser.parse_args()

    generator = HTMLGenerator(args.api_key, args.api_url, args.model)
    print(f"=== text2html | Model: {args.model} ===\n")

    # 确定输入文件列表
    if args.input_file:
        if not os.path.exists(args.input_file):
            print(f"[ERROR] Not found: {args.input_file}")
            return
        files = [Path(args.input_file)]
    elif args.input_dir:
        files = sorted(Path(args.input_dir).glob("*.txt"))
    else:
        print("[ERROR] 请指定 --input-file 或 --input-dir")
        return

    if not files:
        print("[WARN] No .txt files found")
        return

    for i, f in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {f.name}")
        try:
            content = f.read_text(encoding='utf-8')
            result = generator.generate(content)
            generator.save(result, args.output_dir, f.stem)
        except Exception as e:
            print(f"[FAIL] {e}")
        print()


if __name__ == "__main__":
    main()
