#!/usr/bin/env python3
"""
image_broken_renderer.py - 区域遮挡/图片破损渲染器

功能：在目标UI区域覆盖遮挡层，模拟图片加载失败、区域破损等异常。
     被遮挡区域的内容对 agent 不可见，达到"使agent无法识别该区域"的效果。

特点：
- 使用确定性文字定位找到目标区域
- 多种遮挡效果：纯色遮罩、模糊、马赛克、破损图样式
- 纯本地计算，零 API 调用
"""

import os
import re
from typing import Dict, List, Tuple, Optional
from PIL import Image, ImageDraw, ImageFilter
from pathlib import Path
from datetime import datetime

from .base import BaseRenderer, RenderResult
from app.core.config import config


class ImageBrokenRenderer(BaseRenderer):
    """区域遮挡渲染器"""

    OVERLAY_STYLES = ['solid_gray', 'blur', 'mosaic', 'noise']

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def render(
        self,
        screenshot: Image.Image,
        ui_json: dict,
        instruction: str,
        output_dir: str,
        **kwargs,
    ) -> RenderResult:
        """
        在目标区域覆盖遮挡层。

        kwargs:
            screenshot_path (str): 截图路径
            omni_components (list): Stage 1 原始检测结果
        """
        screenshot_path = kwargs.get('screenshot_path', '')
        omni_components = kwargs.get('omni_components', None)

        result_img = screenshot.convert('RGBA')

        # 定位目标区域
        target_regions = self._locate_target_region(instruction, omni_components, ui_json, result_img.size)

        if not target_regions:
            print("  ⚠ 未能定位到目标遮挡区域，返回原图")
        else:
            for region in target_regions:
                x, y, w, h = region['x'], region['y'], region['width'], region['height']
                overlay_style = self._pick_overlay_style(instruction)
                print(f"  ✓ 遮挡区域: ({x},{y}) {w}x{h}, 样式: {overlay_style}")
                result_img = self._apply_overlay(result_img, x, y, w, h, overlay_style)

        # 保存结果
        output_dir_path = Path(output_dir)
        output_dir_path.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = output_dir_path / f"final_{ts}.png"
        result_img.convert('RGB').save(str(output_path))

        return RenderResult(
            image=result_img,
            output_path=str(output_path),
            metadata={
                'edit_count': len(target_regions),
                'anomaly_mode': 'image_broken',
            },
        )

    # ---- 区域定位（复用确定性定位逻辑） ----

    def _locate_target_region(
        self,
        instruction: str,
        omni_components: Optional[List[Dict]],
        ui_json: dict,
        img_size: Tuple[int, int],
    ) -> List[Dict]:
        """从指令中定位需要遮挡的目标区域"""
        print(f"  [image_broken] 指令: {instruction[:60]}")

        if not omni_components:
            print("  [image_broken] ⚠ omni_components 为空 → 无法定位，使用全屏 fallback")
            return self._fallback_full_region(ui_json, img_size)

        print(f"  [image_broken] Stage 1 组件数: {len(omni_components)}")

        keywords = self._extract_keywords(instruction)
        print(f"  [image_broken] 关键词: {keywords}")

        if not keywords:
            print("  [image_broken] ⚠ 关键词为空 → 使用全屏 fallback")
            return self._fallback_full_region(ui_json, img_size)

        img_w, img_h = img_size

        # 在 Stage 1 中搜索匹配
        matches = []
        for comp in omni_components:
            text = (comp.get('text') or '').strip()
            if not text:
                continue
            score = self._match_score(text, keywords)
            if score > 0:
                matches.append({'omni_index': comp.get('index', -1), 'text': text, 'score': score})

        if not matches:
            print(f"  [image_broken] ⚠ OCR 未匹配到任何关键词 (OCR 文字数: "
                  f"{sum(1 for c in omni_components if c.get('text', '').strip())})")
            # 打印前 10 个 OCR 文字供调试
            ocr_texts = [c.get('text', '') for c in omni_components if c.get('text', '').strip()][:10]
            print(f"  [image_broken] 前10个OCR文字: {ocr_texts}")
            print(f"  [image_broken] → 使用全屏 fallback")
            return self._fallback_full_region(ui_json, img_size)

        matches.sort(key=lambda m: m['score'], reverse=True)
        print(f"  [image_broken] OCR 匹配: {[(m['text'], round(m['score'], 2)) for m in matches[:5]]}")

        # 查 Stage 2 group
        merged_components = ui_json.get('components', [])
        print(f"  [image_broken] Stage 2 合并组件数: {len(merged_components)}")
        regions = []
        seen = set()

        for match in matches:
            idx = match['omni_index']
            if idx in seen:
                continue
            found = False
            for comp in merged_components:
                if idx in comp.get('source_indices', []):
                    b = comp.get('bounds', {})
                    x = max(0, b.get('x', 0))
                    y = max(0, b.get('y', 0))
                    w = min(img_w - x, b.get('width', 0))
                    h = min(img_h - y, b.get('height', 0))
                    if w > 0 and h > 0:
                        regions.append({
                            'x': x, 'y': y, 'width': w, 'height': h,
                            'matched_text': match['text'],
                        })
                        seen.add(idx)
                        found = True
                    break
            if not found:
                print(f"  [image_broken] ⚠ index={idx} 未在任何 Stage 2 组件中")

            if len(regions) >= 3:
                break

        if not regions:
            print(f"  [image_broken] ⚠ 匹配到 OCR 文字但未找到对应语义组件 → 全屏 fallback")
            return self._fallback_full_region(ui_json, img_size)

        return regions

    def _fallback_full_region(self, ui_json: dict, img_size: Tuple[int, int]) -> List[Dict]:
        """全屏区域 fallback — 找最大的非导航组件"""
        img_w, img_h = img_size
        components = ui_json.get('components', [])
        # 排除顶部导航栏和底部 TabBar
        candidates = [c for c in components
                      if c.get('class') not in ('StatusBar', 'NavigationBar', 'TabBar', 'SearchBar')]
        if not candidates:
            candidates = components

        # 选面积最大的
        largest = max(candidates, key=lambda c: c.get('bounds', {}).get('width', 0) * c.get('bounds', {}).get('height', 0))
        b = largest.get('bounds', {})
        print(f"  [image_broken] fallback 区域: [{largest.get('class')}] ({b.get('x')},{b.get('y')}) {b.get('width')}x{b.get('height')}")
        return [{'x': b.get('x', 0), 'y': b.get('y', 0), 'width': b.get('width', img_w), 'height': b.get('height', img_h)}]

    def _extract_keywords(self, instruction: str) -> List[str]:
        cleaned = instruction
        for noise in ['将', '改为', '修改', '替换', '模拟', '注入',
                       '的', '了', '在', '把', '被', '让', '使', '到', '和',
                       '异常场景', '无法', '正常', '显示', '点击']:
            cleaned = cleaned.replace(noise, ' ')
        # 保留 "遮挡" "覆盖" "区域" 等空间定位词
        words = re.findall(r'[\u4e00-\u9fff]{2,}', cleaned)
        words.extend(re.findall(r'[a-zA-Z0-9]+', cleaned))
        return list(dict.fromkeys(w for w in words if len(w) >= 2))

    def _match_score(self, text: str, keywords: List[str]) -> float:
        """双向匹配：关键词在 OCR 中，或 OCR 文字在关键词中"""
        score = 0.0
        for kw in keywords:
            if kw in text:
                score += len(kw) / max(1, len(text)) * 2
            elif text in kw:
                # OCR "鞋码" 在关键词 "鞋码选择" 中
                score += len(text) / max(1, len(kw)) * 1.5
            else:
                # 2-gram 模糊匹配
                for i in range(len(kw) - 1):
                    if kw[i:i+2] in text:
                        score += 0.3
        return score

    # ---- 遮挡效果 ----

    def _pick_overlay_style(self, instruction: str) -> str:
        """根据指令内容选择合适的遮挡样式"""
        text = instruction.lower()
        if any(w in text for w in ['加载', 'loading', '破损', 'broken', '错误', '错误图']):
            return 'noise'
        if any(w in text for w in ['模糊', 'blur']):
            return 'blur'
        if any(w in text for w in ['马赛克', 'mosaic']):
            return 'mosaic'
        return 'solid_gray'  # 默认纯灰遮罩

    def _apply_overlay(
        self,
        img: Image.Image,
        x: int, y: int, w: int, h: int,
        style: str,
    ) -> Image.Image:
        """在指定区域应用遮挡效果"""
        crop = img.crop((x, y, x + w, y + h))

        if style == 'solid_gray':
            overlay = Image.new('RGBA', (w, h), (180, 180, 180, 230))

        elif style == 'blur':
            crop_rgba = crop.convert('RGBA')
            blurred = crop_rgba.filter(ImageFilter.GaussianBlur(radius=12))
            overlay = Image.new('RGBA', (w, h), (0, 0, 0, 60))
            overlay = Image.alpha_composite(blurred, overlay)

        elif style == 'mosaic':
            small = crop.resize((max(1, w // 15), max(1, h // 15)), Image.NEAREST)
            mosaic = small.resize((w, h), Image.NEAREST)
            overlay = mosaic.convert('RGBA')
            # 加半透明暗层
            dim = Image.new('RGBA', (w, h), (0, 0, 0, 80))
            overlay = Image.alpha_composite(overlay, dim)

        elif style == 'noise':
            import numpy as np
            arr = np.array(crop.convert('RGB'))
            noise = np.random.randint(0, 80, arr.shape, dtype=np.uint8)
            broken = np.clip(arr.astype(np.int16) - 60 + noise, 0, 255).astype(np.uint8)
            overlay = Image.fromarray(broken).convert('RGBA')
            # 破损图标占位符
            draw = ImageDraw.Draw(overlay)
            cx, cy = w // 2, h // 2
            icon_size = min(w, h) // 4
            draw.rectangle(
                [(cx - icon_size, cy - icon_size), (cx + icon_size, cy + icon_size)],
                fill=(120, 120, 120, 200),
                outline=(80, 80, 80, 255),
                width=2,
            )
            # 破损图标中的 "X"
            margin = icon_size // 3
            draw.line(
                [(cx - icon_size + margin, cy - icon_size + margin),
                 (cx + icon_size - margin, cy + icon_size - margin)],
                fill=(60, 60, 60, 255), width=3,
            )
            draw.line(
                [(cx + icon_size - margin, cy - icon_size + margin),
                 (cx - icon_size + margin, cy + icon_size - margin)],
                fill=(60, 60, 60, 255), width=3,
            )

        else:
            overlay = Image.new('RGBA', (w, h), (180, 180, 180, 230))

        img.paste(overlay, (x, y), overlay if overlay.mode == 'RGBA' else None)
        return img
