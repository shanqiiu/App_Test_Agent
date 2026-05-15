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
from typing import Dict, List, Tuple, Optional
from PIL import Image, ImageDraw, ImageFilter
from pathlib import Path
from datetime import datetime

from .base import BaseRenderer, RenderResult
from .text_overlay import TextOverlayRenderer
from app.core.config import config


class ImageBrokenRenderer(BaseRenderer):
    """区域遮挡渲染器 — 复用 TextOverlayRenderer 的确定性文字定位"""

    OVERLAY_STYLES = ['solid_gray', 'blur', 'mosaic', 'noise']

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 仅用于文字定位，不调 VLM → 空配置即可
        self._locator = TextOverlayRenderer(api_key='', vlm_api_url='', vlm_model='')

    def render(
        self,
        screenshot: Image.Image,
        ui_json: dict,
        instruction: str,
        output_dir: str,
        **kwargs,
    ) -> RenderResult:
        screenshot_path = kwargs.get('screenshot_path', '')
        omni_components = kwargs.get('omni_components', None)

        result_img = screenshot.convert('RGBA')

        # 使用 TextOverlayRenderer 的确定性文字定位
        print(f"  [image_broken] 指令: {instruction[:60]}")
        if not omni_components:
            print("  [image_broken] ⚠ omni_components 为空 → 全屏 fallback")
            target_regions = self._fallback_full_region(ui_json, result_img.size)
        else:
            print(f"  [image_broken] Stage 1 组件数: {len(omni_components)}")
            located = self._locator._locate_text_by_instruction(
                instruction=instruction,
                omni_components=omni_components,
                ui_json=ui_json,
                screenshot_path=screenshot_path,
            )
            if located:
                target_regions = [{
                    'x': loc['crop_bbox'][0], 'y': loc['crop_bbox'][1],
                    'width': loc['crop_bbox'][2] - loc['crop_bbox'][0],
                    'height': loc['crop_bbox'][3] - loc['crop_bbox'][1],
                    'matched_text': loc.get('matched_text', ''),
                } for loc in located]
            else:
                print("  [image_broken] ⚠ 未定位到目标 → 全屏 fallback")
                target_regions = self._fallback_full_region(ui_json, result_img.size)

        if not target_regions:
            print("  ⚠ 未能定位到目标遮挡区域，返回原图")
        else:
            for region in target_regions:
                x, y, w, h = region['x'], region['y'], region['width'], region['height']
                overlay_style = self._pick_overlay_style(instruction)
                print(f"  ✓ 遮挡区域: ({x},{y}) {w}x{h}, 样式: {overlay_style}")
                result_img = self._apply_overlay(result_img, x, y, w, h, overlay_style)

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

    # ---- fallback & overlay ----

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
