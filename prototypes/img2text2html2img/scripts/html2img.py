"""
HTML to Image - 将HTML渲染为图片，1:1复刻原图尺寸
自动从HTML或关联文件中提取分辨率
"""

import argparse
import os
import re
import json
from pathlib import Path
from typing import Tuple, Optional
from playwright.sync_api import sync_playwright


def extract_resolution_from_html(html_content: str) -> Optional[Tuple[int, int]]:
    """从HTML内容中提取.container的宽高"""
    patterns = [
        # .container { width: 1080px; height: 2340px; }
        r'\.container\s*\{[^}]*width:\s*(\d+)px[^}]*height:\s*(\d+)px',
        r'\.container\s*\{[^}]*height:\s*(\d+)px[^}]*width:\s*(\d+)px',
        # width:1080px;height:2340px
        r'width:\s*(\d+)px;\s*height:\s*(\d+)px',
    ]
    for p in patterns:
        m = re.search(p, html_content, re.IGNORECASE | re.DOTALL)
        if m:
            groups = m.groups()
            if 'height' in p[:30]:  # 如果height在前
                return int(groups[1]), int(groups[0])
            return int(groups[0]), int(groups[1])
    return None


def extract_resolution_from_meta(meta_path: Path) -> Optional[Tuple[int, int]]:
    """从JSON或TXT元数据文件提取分辨率"""
    if not meta_path.exists():
        return None

    content = meta_path.read_text(encoding='utf-8')

    # JSON格式
    if meta_path.suffix == '.json':
        try:
            data = json.loads(content)
            if "_image_metadata" in data:
                meta = data["_image_metadata"]
                return meta.get("width"), meta.get("height")
            if "meta" in data:
                return data["meta"].get("width"), data["meta"].get("height")
        except:
            pass

    # 结构化文本格式
    m = re.search(r'META\|width:(\d+)\|height:(\d+)', content)
    if m:
        return int(m.group(1)), int(m.group(2))

    return None


def get_resolution(html_path: Path, html_content: str) -> Tuple[int, int]:
    """获取渲染分辨率，优先级：关联元数据 > HTML内容 > 默认值"""

    # 1. 尝试从同名.json文件读取
    json_path = html_path.with_suffix('.json')
    res = extract_resolution_from_meta(json_path)
    if res and res[0] and res[1]:
        return res

    # 2. 尝试从同名.txt文件读取
    txt_path = html_path.with_suffix('.txt')
    res = extract_resolution_from_meta(txt_path)
    if res and res[0] and res[1]:
        return res

    # 3. 尝试查找同目录下的元数据文件（文件名包含html文件名）
    stem = html_path.stem.split('_')[0]  # 去掉时间戳后缀
    for f in html_path.parent.glob(f"{stem}*.json"):
        res = extract_resolution_from_meta(f)
        if res and res[0] and res[1]:
            return res

    # 4. 从HTML内容提取
    res = extract_resolution_from_html(html_content)
    if res:
        return res

    # 5. 默认值
    return 375, 667


def html_to_image(html_path: str, output_path: str, width: int = None, height: int = None, timeout: int = 500) -> bool:
    """将HTML渲染为图片"""
    html_path = Path(html_path)
    if not html_path.exists():
        print(f"[ERROR] Not found: {html_path}")
        return False

    html_content = html_path.read_text(encoding='utf-8')

    # 获取分辨率
    if width and height:
        w, h = width, height
    else:
        w, h = get_resolution(html_path, html_content)

    print(f"    Resolution: {w}x{h}px")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # 设置精确的viewport尺寸
            page.set_viewport_size({"width": w, "height": h})

            # 加载HTML
            abs_path = html_path.absolute()
            page.goto(f"file:///{str(abs_path).replace(os.sep, '/')}")
            page.wait_for_timeout(timeout)

            # 使用clip精确截取指定区域，确保1:1
            screenshot = page.screenshot(clip={"x": 0, "y": 0, "width": w, "height": h})

            # 保存
            output = Path(output_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(screenshot)

            browser.close()
            print(f"[OK] {output}")
            return True

    except Exception as e:
        print(f"[FAIL] {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="HTML to Image (1:1 复刻)")
    parser.add_argument("-i", "--input", required=True, help="HTML文件或目录")
    parser.add_argument("-o", "--output", help="输出文件(单文件)或目录")
    parser.add_argument("--width", type=int, help="强制指定宽度(覆盖自动检测)")
    parser.add_argument("--height", type=int, help="强制指定高度(覆盖自动检测)")
    parser.add_argument("--timeout", type=int, default=500, help="渲染等待时间(ms)")
    args = parser.parse_args()

    input_path = Path(args.input)

    if input_path.is_file():
        # 单文件
        output = args.output or f"output_images/{input_path.stem}.png"
        print(f"--- {input_path.name} ---")
        html_to_image(str(input_path), output, args.width, args.height, args.timeout)

    elif input_path.is_dir():
        # 目录批量处理
        output_dir = Path(args.output or "output_images")
        html_files = list(input_path.glob("*.html"))

        if not html_files:
            print(f"[WARN] No HTML files in {input_path}")
            return

        print(f"=== Processing {len(html_files)} files ===\n")
        success, fail = 0, 0

        for i, f in enumerate(sorted(html_files), 1):
            print(f"[{i}/{len(html_files)}] {f.name}")
            output = output_dir / f"{f.stem}.png"
            if html_to_image(str(f), str(output), args.width, args.height, args.timeout):
                success += 1
            else:
                fail += 1
            print()

        print(f"=== Done: {success} ok, {fail} failed ===")
    else:
        print(f"[ERROR] Not found: {input_path}")


if __name__ == "__main__":
    main()
