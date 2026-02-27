#!/usr/bin/env python3
"""
text_overlay_renderer.py - 文字覆盖编辑渲染器

功能：在App UI截图上进行精确的局部文字编辑，实现：
- insert_text:  在已有卡片/区域内插入新文字（如优惠信息）
- replace_region: 替换整个区域内容（如Banner替换）
- modify_text:  原地替换已有文字（如修改价格）
- add_badge:    添加角标/标签（如"限时优惠"）

设计原则：
- 局部编辑：所有操作限定在 bounding box 内，区域外像素 bit-identical
- 风格一致：从原图同区域已有文字采样字号/颜色/粗细，而非猜测
- 文字清晰：使用 PIL + TrueType 字体直接绘制，不使用 AI 图像生成
- VLM 决策：VLM 规划"编辑什么"，PIL 执行"怎么画"
"""

import json
import os
import re
import requests
import base64
from typing import Dict, List, Tuple, Optional, Any
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from dataclasses import dataclass, field, asdict

from utils.common import encode_image, get_mime_type, extract_json


# ==================== 数据结构 ====================

@dataclass
class TextStyle:
    """文字视觉风格"""
    font_size: int = 28
    font_color: Tuple[int, int, int] = (51, 51, 51)
    font_weight: str = 'regular'  # regular / bold
    bg_color: Tuple[int, int, int] = (255, 255, 255)
    line_height: int = 40
    font_path: Optional[str] = None


@dataclass
class EditOp:
    """单次编辑操作"""
    action: str  # insert_text / replace_region / modify_text / add_badge / expand_card
    region: Dict[str, int]  # {"x": ..., "y": ..., "width": ..., "height": ...}
    content: str  # 文字内容
    target_component: Optional[int] = None  # UI-JSON 中的 component index
    style_hint: Dict[str, Any] = field(default_factory=dict)  # VLM 建议的风格
    reference_component: Optional[int] = None  # 用于风格采样的参考组件 index


# ==================== VLM 编辑规划 Prompt ====================

EDIT_PLAN_PROMPT = """你是一个App UI编辑专家。给定一张App截图和它的UI组件结构(UI-JSON)，根据用户指令规划精确的文字编辑操作。

## UI-JSON 组件列表
```json
{components_json}
```

## 用户编辑指令
{instruction}

## 任务
分析截图和UI结构，输出一个编辑操作列表。每个操作修改一个局部区域，不影响其他区域。

## 操作类型说明
- `expand_card`: 【推荐用于插入文字】将目标卡片/区域向下撑高，在底部新增空间中插入文字。原卡片内容完全保留，下方所有内容自动下移。这是最安全的插入方式，不会覆盖已有内容。
- `insert_text`: 在已有卡片/区域的空白处插入文字行。注意：仅当目标区域确实有足够空白时才使用，否则应使用 expand_card。
- `replace_region`: 替换一个矩形区域的全部内容（如整个Banner换新内容）。
- `modify_text`: 只替换已有文字的内容（如修改价格、标题），保留原位置和风格。
- `add_badge`: 在组件右上角或指定位置添加小标签（如"限时"、"新"、"热"）。

## 输出格式（严格JSON数组）
```json
[
  {{
    "action": "expand_card",
    "target_component": 5,
    "content": "优惠：订阅该服务，机票满500减200元",
    "reference_component": 4,
    "style_hint": {{
      "color_type": "accent",
      "font_scale": 0.85,
      "padding_top": 8,
      "padding_bottom": 12
    }}
  }}
]
```

## 字段说明
- `target_component`: UI-JSON中目标组件的index（expand_card 时选卡片内最底部的文字组件）
- `content`: 要插入/替换的文字
- `position`: 仅insert_text使用，"below"=组件下方, "inside"=组件内部, "above"=组件上方
- `reference_component`: 用于采样文字风格的参考组件index（通常选同一卡片内的已有文字）
- `style_hint.color_type`: "primary"=主文字色, "secondary"=副文字色, "accent"=强调色(如橙色/红色)
- `style_hint.font_scale`: 相对参考组件的字号缩放比例, 1.0=相同, 0.85=略小
- `style_hint.padding_top`: expand_card 新增区域的上内边距(px)，默认8
- `style_hint.padding_bottom`: expand_card 新增区域的下内边距(px)，默认12

## 注意事项
1. 当需要在已有卡片中插入新文字行时，优先使用 expand_card 而非 insert_text
2. expand_card 的 target_component 应选择卡片内最后一行文字组件（新文字会出现在它下方）
3. expand_card 会自动撑高卡片并下移后续内容，不会覆盖任何已有元素
4. 优先选择同一卡片内的文字作为 reference_component（风格最相近）
5. 只返回JSON数组，不要其他内容"""


# ==================== 渲染器主类 ====================

class TextOverlayRenderer:
    """文字覆盖编辑渲染器 - 局部精确编辑"""

    def __init__(
        self,
        api_key: str = None,
        vlm_api_url: str = 'https://api.openai-next.com/v1/chat/completions',
        vlm_model: str = 'gpt-4o',
        fonts_dir: str = None
    ):
        self.api_key = api_key
        self.vlm_api_url = vlm_api_url
        self.vlm_model = vlm_model
        self.fonts_dir = fonts_dir
        self._font_cache = {}

    # ==================== 1. VLM 编辑规划 ====================

    def plan_edits(
        self,
        screenshot_path: str,
        ui_json: dict,
        instruction: str
    ) -> List[EditOp]:
        """
        VLM 分析截图和UI结构，生成编辑操作列表

        Args:
            screenshot_path: 原始截图路径
            ui_json: Stage 2 过滤后的UI-JSON
            instruction: 用户编辑指令

        Returns:
            EditOp 列表
        """
        print(f"  [编辑规划] 正在分析页面...")

        # Step 1: 优先尝试关键词精确匹配（确定性定位，不依赖 VLM）
        kw_result = self._keyword_match_target(ui_json, instruction)
        if kw_result:
            content = self._extract_edit_content(instruction)
            target = kw_result['target_comp']
            ref = kw_result['ref_comp']
            bounds = target.get('bounds', {})

            op = EditOp(
                action='expand_card',
                region={
                    'x': bounds.get('x', 0),
                    'y': bounds.get('y', 0),
                    'width': bounds.get('width', 100),
                    'height': bounds.get('height', 40),
                },
                content=content,
                target_component=target.get('index'),
                style_hint={'color_type': 'accent', 'font_scale': 0.9},
                reference_component=ref.get('index'),
            )

            r = op.region
            print(f"  ✓ 关键词精确匹配成功: 1 个操作")
            print(f"    [0] {op.action}: \"{op.content[:30]}...\" @ ({r['x']},{r['y']}) {r['width']}x{r['height']}")
            return [op]

        # Step 2: 关键词匹配失败，使用 VLM 规划
        print(f"  [VLM规划] 关键词未匹配到目标，使用 VLM 分析...")

        components = ui_json.get('components', [])
        # 精简组件信息，减少 token
        slim_components = []
        for c in components:
            slim_components.append({
                'index': c.get('index'),
                'class': c.get('class'),
                'bounds': c.get('bounds'),
                'text': c.get('text', '')[:50],  # 截断长文本
            })
        components_json = json.dumps(slim_components, ensure_ascii=False, indent=2)

        prompt = EDIT_PLAN_PROMPT.format(
            components_json=components_json,
            instruction=instruction
        )

        # 调用 VLM
        raw_plan = self._call_vlm_with_image(screenshot_path, prompt)
        if not raw_plan:
            print(f"  ⚠ VLM 编辑规划失败，使用回退策略")
            return self._fallback_plan(ui_json, instruction)

        # 解析 VLM 输出
        try:
            plan_data = self._extract_json_array(raw_plan)
        except Exception as e:
            print(f"  ⚠ JSON 解析失败: {e}")
            return self._fallback_plan(ui_json, instruction)

        # 转换为 EditOp
        edit_ops = []
        for item in plan_data:
            op = self._parse_edit_op(item, ui_json)
            if op:
                edit_ops.append(op)

        print(f"  ✓ 编辑规划完成: {len(edit_ops)} 个操作")
        for i, op in enumerate(edit_ops):
            r = op.region
            print(f"    [{i}] {op.action}: \"{op.content[:30]}...\" @ ({r['x']},{r['y']}) {r['width']}x{r['height']}")

        return edit_ops

    def _parse_edit_op(self, item: dict, ui_json: dict) -> Optional[EditOp]:
        """将 VLM 输出的单个操作解析为 EditOp"""
        action = item.get('action', '')
        content = item.get('content', '')
        target_idx = item.get('target_component')
        ref_idx = item.get('reference_component')
        position = item.get('position', 'below')
        style_hint = item.get('style_hint', {})

        if not action or not content:
            return None

        components = ui_json.get('components', [])

        # 查找目标组件
        target_comp = None
        if target_idx is not None:
            for c in components:
                if c.get('index') == target_idx:
                    target_comp = c
                    break

        if not target_comp:
            print(f"    ⚠ 目标组件 {target_idx} 未找到，跳过")
            return None

        bounds = target_comp.get('bounds', {})

        # 根据 action 和 position 计算编辑区域
        if action == 'expand_card':
            # expand_card: region 记录的是目标组件（卡片底部文字）的 bounds
            # 实际的撑高和绘制在 _exec_expand_card 中处理
            region = {
                'x': bounds.get('x', 0),
                'y': bounds.get('y', 0),
                'width': bounds.get('width', 100),
                'height': bounds.get('height', 40),
            }
        elif action == 'insert_text':
            region = self._calc_insert_region(target_comp, position, ui_json)
        elif action == 'replace_region':
            region = {
                'x': bounds.get('x', 0),
                'y': bounds.get('y', 0),
                'width': bounds.get('width', 100),
                'height': bounds.get('height', 40),
            }
        elif action == 'modify_text':
            region = {
                'x': bounds.get('x', 0),
                'y': bounds.get('y', 0),
                'width': bounds.get('width', 100),
                'height': bounds.get('height', 40),
            }
        elif action == 'add_badge':
            badge_w, badge_h = 80, 32
            region = {
                'x': bounds.get('x', 0) + bounds.get('width', 100) - badge_w - 8,
                'y': bounds.get('y', 0) + 8,
                'width': badge_w,
                'height': badge_h,
            }
        else:
            return None

        return EditOp(
            action=action,
            region=region,
            content=content,
            target_component=target_idx,
            style_hint=style_hint,
            reference_component=ref_idx,
        )

    def _calc_insert_region(
        self,
        target_comp: dict,
        position: str,
        ui_json: dict
    ) -> Dict[str, int]:
        """计算 insert_text 的编辑区域"""
        bounds = target_comp.get('bounds', {})
        tx, ty = bounds.get('x', 0), bounds.get('y', 0)
        tw, th = bounds.get('width', 100), bounds.get('height', 40)

        # 估算插入行高度（取目标组件高度的 0.8，至少 32px，至多 60px）
        insert_h = max(32, min(60, int(th * 0.8)))

        if position == 'below':
            return {
                'x': tx,
                'y': ty + th,
                'width': tw,
                'height': insert_h,
            }
        elif position == 'above':
            return {
                'x': tx,
                'y': max(0, ty - insert_h),
                'width': tw,
                'height': insert_h,
            }
        else:  # inside - 在组件内部底部插入
            return {
                'x': tx,
                'y': ty + th - insert_h,
                'width': tw,
                'height': insert_h,
            }

    def _fallback_plan(self, ui_json: dict, instruction: str) -> List[EditOp]:
        """VLM 失败时的回退策略：根据指令关键词简单匹配"""
        components = ui_json.get('components', [])
        if not components:
            return []

        # 从指令中提取文字内容（引号或冒号后的部分）
        content = instruction
        # 尝试提取引号中的内容
        quote_match = re.search(r'[""「](.+?)[""」]', instruction)
        if quote_match:
            content = quote_match.group(1)

        # 选择中间区域最大的组件
        mid_components = [
            c for c in components
            if c.get('bounds', {}).get('y', 0) > 200  # 跳过顶部导航
        ]
        if not mid_components:
            mid_components = components

        target = max(
            mid_components,
            key=lambda c: c.get('bounds', {}).get('width', 0) * c.get('bounds', {}).get('height', 0)
        )

        bounds = target.get('bounds', {})
        return [EditOp(
            action='expand_card',
            region={
                'x': bounds.get('x', 0),
                'y': bounds.get('y', 0),
                'width': bounds.get('width', 200),
                'height': bounds.get('height', 40),
            },
            content=content,
            target_component=target.get('index'),
            style_hint={'color_type': 'accent'},
            reference_component=target.get('index'),
        )]

    # ==================== 1.5 关键词精确定位（确定性，不依赖 VLM） ====================

    def _keyword_match_target(self, ui_json: dict, instruction: str) -> Optional[dict]:
        """
        从指令中提取关键词，在 UI-JSON 中搜索匹配的卡片区域。

        Returns:
            匹配结果 dict: {
                'target_comp':  卡片最后一个文字组件（expand_card 的 target）
                'ref_comp':     卡片内单行文字组件（风格采样参考）
                'keyword':      匹配到的关键词
            }
            或 None（未匹配到）
        """
        components = ui_json.get('components', [])
        if not components:
            return None

        # 1. 从指令中提取关键词
        keywords = []
        patterns = [
            r'在(.+?)(?:卡片|部分|区域|模块|服务)中',
            r'在(.+?)(?:中|里)插入',
            r'(?:对|给)(.+?)(?:插入|添加|增加)',
            r'(.+?)(?:卡片|部分|区域|模块)',
        ]
        for p in patterns:
            m = re.search(p, instruction)
            if m:
                kw = m.group(1).strip()
                if 2 <= len(kw) <= 10:
                    keywords.append(kw)

        # 补充短关键词（取前2字）
        for kw in list(keywords):
            if len(kw) > 2:
                keywords.append(kw[:2])

        if not keywords:
            return None

        # 2. 在组件文本中搜索关键词
        matched_comps = []
        for comp in components:
            text = comp.get('text', '')
            if not text:
                continue
            for kw in keywords:
                if kw in text:
                    matched_comps.append((comp, kw))
                    break

        if not matched_comps:
            return None

        # 选最佳匹配（最长关键词）
        header_comp, matched_kw = max(matched_comps, key=lambda x: len(x[1]))
        header_bounds = header_comp.get('bounds', {})
        header_y = header_bounds.get('y', 0)
        header_bottom = header_y + header_bounds.get('height', 0)

        # 3. 查找同一卡片区域的所有组件（header 下方，间隔检测卡片边界）
        candidates = [
            c for c in components
            if c.get('bounds', {}).get('y', 0) >= header_y - 10
        ]
        candidates.sort(key=lambda c: c.get('bounds', {}).get('y', 0))

        card_comps = []
        prev_bottom = header_y
        for comp in candidates:
            cy = comp.get('bounds', {}).get('y', 0)
            ch = comp.get('bounds', {}).get('height', 0)
            gap = cy - prev_bottom
            # 间隔 > 80px 视为新卡片，停止
            if gap > 80 and cy > header_bottom:
                break
            card_comps.append(comp)
            prev_bottom = max(prev_bottom, cy + ch)

        if not card_comps:
            card_comps = [header_comp]

        # 最后一个组件作为 target（expand_card 在其下方插入）
        target_comp = card_comps[-1]

        # 4. 在卡片内找单行文字组件作为风格参考（height 15-55px）
        ref_comp = None
        for comp in card_comps:
            h = comp.get('bounds', {}).get('height', 0)
            if comp.get('text') and 15 < h < 55:
                ref_comp = comp
                break
        if ref_comp is None:
            ref_comp = header_comp

        print(f"  [关键词匹配] \"{matched_kw}\" → 标题: [{header_comp.get('index')}] \"{header_comp.get('text', '')[:20]}\"")
        print(f"    目标(最底部): [{target_comp.get('index')}] \"{target_comp.get('text', '')[:30]}\"")
        print(f"    参考(风格): [{ref_comp.get('index')}] \"{ref_comp.get('text', '')[:20]}\" h={ref_comp.get('bounds', {}).get('height', '?')}px")
        print(f"    卡片组件数: {len(card_comps)}")

        return {
            'target_comp': target_comp,
            'ref_comp': ref_comp,
            'keyword': matched_kw,
        }

    def _extract_edit_content(self, instruction: str) -> str:
        """从编辑指令中提取要显示的文字内容"""
        # Pattern 1: "插入XX信息：内容" → "XX：内容"
        m = re.search(r'插入(.+?)信息[：:](.+)', instruction)
        if m:
            label = m.group(1).strip()
            body = m.group(2).strip()
            return f"{label}：{body}"

        # Pattern 2: 最后一个冒号后的内容
        m = re.search(r'[：:]([^：:]+)$', instruction)
        if m:
            return m.group(1).strip()

        # Pattern 3: 引号内容
        m = re.search(r'[""「](.+?)[""」]', instruction)
        if m:
            return m.group(1)

        return instruction

    # ==================== 2. 风格提取（像素级） ====================

    def extract_text_style(
        self,
        image: Image.Image,
        component: dict,
        ui_json: dict = None
    ) -> TextStyle:
        """
        从原图中某个已有文字组件提取完整视觉风格

        Args:
            image: 原始截图
            component: UI-JSON 中的文字组件
            ui_json: 完整 UI-JSON（用于查找同区域其他文字）

        Returns:
            TextStyle 对象
        """
        bounds = component.get('bounds', {})
        x, y = bounds.get('x', 0), bounds.get('y', 0)
        w, h = bounds.get('width', 100), bounds.get('height', 40)

        # 确保坐标合法
        img_w, img_h = image.size
        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))
        w = min(w, img_w - x)
        h = min(h, img_h - y)

        if w <= 0 or h <= 0:
            return TextStyle()

        bbox = (x, y, x + w, y + h)
        region = image.crop(bbox)

        # 1. 采样背景色
        bg_color = self._sample_background_color(region)

        # 2. 采样文字颜色
        font_color = self._sample_text_color(region, bg_color)

        # 3. 匹配字号
        font_path = self._find_font()
        # 多行文本组件的 height 是整体高度，需折算到单行
        effective_h = h
        if h > 55:
            text = component.get('text', '')
            if text:
                # 用换行符或文字量估算行数
                est_lines = max(1, round(h / 38))
                effective_h = max(20, h // est_lines)
        font_size = self._match_font_size(int(effective_h), font_path)
        # 正文字号上限（App 正文一般 24-36px，标题最大 48px）
        font_size = min(font_size, 42)

        # 4. 检测粗细
        font_weight = self._detect_font_weight(region, bg_color)

        return TextStyle(
            font_size=font_size,
            font_color=font_color,
            font_weight=font_weight,
            bg_color=bg_color,
            line_height=h,
            font_path=font_path,
        )

    def _sample_background_color(self, region: Image.Image) -> Tuple[int, int, int]:
        """
        从区域边缘像素采样背景色

        取四条边缘各 2px 的像素，用中位数避免文字像素干扰。
        """
        region_rgb = region.convert('RGB')
        w, h = region_rgb.size

        if w < 3 or h < 3:
            # 区域太小，取中心像素
            px = region_rgb.getpixel((w // 2, h // 2))
            return px[:3]

        pixels = []
        # 上边缘 2 行
        for x_pos in range(w):
            for y_pos in range(min(2, h)):
                pixels.append(region_rgb.getpixel((x_pos, y_pos)))
        # 下边缘 2 行
        for x_pos in range(w):
            for y_pos in range(max(0, h - 2), h):
                pixels.append(region_rgb.getpixel((x_pos, y_pos)))
        # 左边缘 2 列
        for y_pos in range(h):
            for x_pos in range(min(2, w)):
                pixels.append(region_rgb.getpixel((x_pos, y_pos)))
        # 右边缘 2 列
        for y_pos in range(h):
            for x_pos in range(max(0, w - 2), w):
                pixels.append(region_rgb.getpixel((x_pos, y_pos)))

        if not pixels:
            return (255, 255, 255)

        r = sorted([p[0] for p in pixels])[len(pixels) // 2]
        g = sorted([p[1] for p in pixels])[len(pixels) // 2]
        b = sorted([p[2] for p in pixels])[len(pixels) // 2]
        return (r, g, b)

    def _sample_text_color(
        self,
        region: Image.Image,
        bg_color: Tuple[int, int, int]
    ) -> Tuple[int, int, int]:
        """
        从区域中采样文字颜色

        过滤掉背景色像素，剩余像素取中位数。
        """
        region_rgb = region.convert('RGB')
        w, h = region_rgb.size

        # 收集所有像素
        pixels = []
        for py in range(h):
            for px in range(w):
                pixels.append(region_rgb.getpixel((px, py)))

        # 只保留与背景色差异足够大的像素（即文字像素）
        threshold = 40
        text_pixels = [
            p for p in pixels
            if self._color_distance(p, bg_color) > threshold
        ]

        if not text_pixels or len(text_pixels) < 3:
            return (51, 51, 51)  # 默认深灰

        r = sorted([p[0] for p in text_pixels])[len(text_pixels) // 2]
        g = sorted([p[1] for p in text_pixels])[len(text_pixels) // 2]
        b = sorted([p[2] for p in text_pixels])[len(text_pixels) // 2]
        return (r, g, b)

    def _match_font_size(self, target_height: int, font_path: str = None) -> int:
        """
        二分搜索找到渲染后高度最接近 target_height 的字号

        Args:
            target_height: 目标文字区域的像素高度
            font_path: 字体文件路径

        Returns:
            最佳匹配字号
        """
        if not font_path:
            # 无字体文件时按经验比例估算
            return max(12, int(target_height * 0.72))

        low, high = 8, 120
        temp_img = Image.new('RGBA', (1, 1))
        draw = ImageDraw.Draw(temp_img)
        sample_text = "测试Ag"

        best_size = max(12, int(target_height * 0.72))

        try:
            while low <= high:
                mid = (low + high) // 2
                font = ImageFont.truetype(font_path, mid)
                bbox = draw.textbbox((0, 0), sample_text, font=font)
                rendered_h = bbox[3] - bbox[1]

                if rendered_h < target_height:
                    best_size = mid
                    low = mid + 1
                elif rendered_h > target_height:
                    high = mid - 1
                else:
                    return mid
        except Exception:
            pass

        return best_size

    def _detect_font_weight(
        self,
        region: Image.Image,
        bg_color: Tuple[int, int, int]
    ) -> str:
        """
        检测文字粗细：统计水平方向连续深色像素的平均宽度

        笔画宽度 ≤ 3px → regular, > 3px → bold
        """
        gray = region.convert('L')
        w, h = gray.size

        if w < 5 or h < 5:
            return 'regular'

        # 计算二值化阈值：背景亮度 - 偏移
        bg_brightness = (bg_color[0] + bg_color[1] + bg_color[2]) // 3
        threshold = max(50, bg_brightness - 60)

        stroke_widths = []
        for y_pos in range(h):
            in_stroke = False
            width_count = 0
            for x_pos in range(w):
                pixel_val = gray.getpixel((x_pos, y_pos))
                if pixel_val < threshold:
                    width_count += 1
                    in_stroke = True
                elif in_stroke:
                    if width_count >= 2:  # 忽略噪点
                        stroke_widths.append(width_count)
                    width_count = 0
                    in_stroke = False

        if not stroke_widths:
            return 'regular'

        stroke_widths.sort()
        median_stroke = stroke_widths[len(stroke_widths) // 2]
        return 'bold' if median_stroke > 3.5 else 'regular'

    @staticmethod
    def _color_distance(c1: Tuple[int, ...], c2: Tuple[int, ...]) -> float:
        """欧几里得颜色距离"""
        return sum((a - b) ** 2 for a, b in zip(c1[:3], c2[:3])) ** 0.5

    # ==================== 3. 编辑操作执行 ====================

    def apply_edit(
        self,
        image: Image.Image,
        edit_op: EditOp,
        ui_json: dict
    ) -> Image.Image:
        """
        执行单个编辑操作，仅修改 edit_op.region 内的像素

        Args:
            image: 当前图像（会被 copy，不修改原对象）
            edit_op: 编辑操作
            ui_json: UI-JSON（用于风格采样）

        Returns:
            编辑后的图像
        """
        result = image.copy()
        action = edit_op.action

        if action == 'expand_card':
            result = self._exec_expand_card(result, edit_op, ui_json)
        elif action == 'insert_text':
            result = self._exec_insert_text(result, edit_op, ui_json)
        elif action == 'replace_region':
            result = self._exec_replace_region(result, edit_op, ui_json)
        elif action == 'modify_text':
            result = self._exec_modify_text(result, edit_op, ui_json)
        elif action == 'add_badge':
            result = self._exec_add_badge(result, edit_op, ui_json)

        return result

    def _resolve_style(
        self,
        image: Image.Image,
        edit_op: EditOp,
        ui_json: dict
    ) -> TextStyle:
        """
        为编辑操作确定文字风格

        优先从 reference_component 采样，回退到 target_component，最终用默认值。
        """
        components = ui_json.get('components', [])
        ref_idx = edit_op.reference_component
        target_idx = edit_op.target_component

        # 查找参考组件
        ref_comp = None
        for c in components:
            idx = c.get('index')
            if ref_idx is not None and idx == ref_idx:
                ref_comp = c
                break
        if ref_comp is None:
            for c in components:
                if c.get('index') == target_idx:
                    ref_comp = c
                    break

        if ref_comp and ref_comp.get('text'):
            style = self.extract_text_style(image, ref_comp, ui_json)
        else:
            # 没有可参考的文字组件，使用默认
            style = TextStyle(font_path=self._find_font())

        # 应用 style_hint 调整
        hint = edit_op.style_hint
        if hint.get('font_scale'):
            style.font_size = max(12, int(style.font_size * hint['font_scale']))

        if hint.get('color_type') == 'accent':
            # 强调色：如果原色太暗，切换为橙红色
            brightness = sum(style.font_color) / 3
            if brightness < 150:
                style.font_color = (255, 107, 0)  # 携程橙
            else:
                style.font_color = (230, 70, 20)

        return style

    def _exec_insert_text(
        self,
        image: Image.Image,
        edit_op: EditOp,
        ui_json: dict
    ) -> Image.Image:
        """
        在指定区域插入文字

        原理：crop 出目标区域 → 采样背景色填充 → 绘制文字 → paste 回原位
        """
        r = edit_op.region
        x, y, w, h = r['x'], r['y'], r['width'], r['height']

        # 裁剪到图像边界内
        img_w, img_h = image.size
        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))
        w = min(w, img_w - x)
        h = min(h, img_h - y)

        if w <= 0 or h <= 0:
            return image

        # 确定风格
        style = self._resolve_style(image, edit_op, ui_json)

        # 取出原区域（保留原像素用于背景采样）
        original_region = image.crop((x, y, x + w, y + h)).convert('RGBA')

        # 采样该区域的背景色
        bg_color = self._sample_background_color(original_region)

        # 创建编辑层：纯背景色填充 + 文字
        edit_layer = Image.new('RGBA', (w, h), (*bg_color, 255))
        draw = ImageDraw.Draw(edit_layer)

        # 加载字体
        font = self._get_font(style.font_size, style.font_weight == 'bold', style.font_path)

        # 计算文字位置（垂直居中，水平 padding）
        padding_x = max(8, int(w * 0.03))
        text_content = edit_op.content

        # 自动换行
        lines = self._wrap_text(text_content, w - padding_x * 2, font, draw)

        # 计算总文字高度
        total_text_h = 0
        line_heights = []
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            lh = bbox[3] - bbox[1]
            line_heights.append(lh)
            total_text_h += lh

        line_spacing = max(4, int(style.font_size * 0.3))
        total_text_h += line_spacing * (len(lines) - 1) if len(lines) > 1 else 0

        # 垂直居中
        start_y = max(0, (h - total_text_h) // 2)

        # 逐行绘制
        current_y = start_y
        for i, line in enumerate(lines):
            draw.text(
                (padding_x, current_y),
                line,
                font=font,
                fill=(*style.font_color, 255)
            )
            current_y += line_heights[i] + line_spacing

        # 边缘羽化：让编辑区域的上下边缘与原图自然融合
        edit_layer = self._feather_edges(edit_layer, original_region, feather_px=2)

        # paste 回原图
        result = image.copy()
        result.paste(edit_layer, (x, y), edit_layer)
        return result

    def _exec_replace_region(
        self,
        image: Image.Image,
        edit_op: EditOp,
        ui_json: dict
    ) -> Image.Image:
        """
        替换指定区域的全部内容

        原理：crop 出目标区域 → 用背景色填充 → 绘制新内容 → 带羽化 mask paste 回原位
        """
        r = edit_op.region
        x, y, w, h = r['x'], r['y'], r['width'], r['height']

        img_w, img_h = image.size
        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))
        w = min(w, img_w - x)
        h = min(h, img_h - y)

        if w <= 0 or h <= 0:
            return image

        style = self._resolve_style(image, edit_op, ui_json)

        # 采样原区域背景色
        original_region = image.crop((x, y, x + w, y + h)).convert('RGBA')
        bg_color = self._sample_background_color(original_region)

        # 创建新区域
        new_region = Image.new('RGBA', (w, h), (*bg_color, 255))
        draw = ImageDraw.Draw(new_region)

        font = self._get_font(style.font_size, style.font_weight == 'bold', style.font_path)

        # 自动换行
        padding_x = max(12, int(w * 0.04))
        padding_y = max(8, int(h * 0.1))
        lines = self._wrap_text(edit_op.content, w - padding_x * 2, font, draw)

        current_y = padding_y
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            lh = bbox[3] - bbox[1]
            draw.text(
                (padding_x, current_y),
                line,
                font=font,
                fill=(*style.font_color, 255)
            )
            current_y += lh + max(4, int(style.font_size * 0.3))

        # 边缘羽化
        new_region = self._feather_edges(new_region, original_region, feather_px=3)

        result = image.copy()
        result.paste(new_region, (x, y), new_region)
        return result

    def _exec_modify_text(
        self,
        image: Image.Image,
        edit_op: EditOp,
        ui_json: dict
    ) -> Image.Image:
        """
        原地替换已有文字

        原理：采样背景色 → 背景色填充原区域（擦除旧文字） → 同位置绘制新文字
        """
        r = edit_op.region
        x, y, w, h = r['x'], r['y'], r['width'], r['height']

        img_w, img_h = image.size
        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))
        w = min(w, img_w - x)
        h = min(h, img_h - y)

        if w <= 0 or h <= 0:
            return image

        style = self._resolve_style(image, edit_op, ui_json)

        # 取出原区域
        original_region = image.crop((x, y, x + w, y + h)).convert('RGBA')

        # 采样背景色和文字色
        bg_color = self._sample_background_color(original_region)
        text_color = self._sample_text_color(original_region, bg_color)

        # 如果 style_hint 指定了 accent，覆盖文字颜色
        if edit_op.style_hint.get('color_type') == 'accent':
            text_color = style.font_color

        # Step 1: 用背景色填充（擦除原文字）
        erased = Image.new('RGBA', (w, h), (*bg_color, 255))

        # Step 2: 绘制新文字
        draw = ImageDraw.Draw(erased)
        font = self._get_font(style.font_size, style.font_weight == 'bold', style.font_path)

        # 计算文字位置（尽量与原文字位置一致：垂直居中，水平靠左 padding）
        padding_x = max(4, int(w * 0.02))
        bbox = draw.textbbox((0, 0), edit_op.content, font=font)
        text_h = bbox[3] - bbox[1]
        text_y = max(0, (h - text_h) // 2)

        draw.text(
            (padding_x, text_y),
            edit_op.content,
            font=font,
            fill=(*text_color, 255)
        )

        # 边缘羽化
        erased = self._feather_edges(erased, original_region, feather_px=2)

        result = image.copy()
        result.paste(erased, (x, y), erased)
        return result

    def _exec_add_badge(
        self,
        image: Image.Image,
        edit_op: EditOp,
        ui_json: dict
    ) -> Image.Image:
        """
        在指定位置添加角标/标签

        原理：在局部区域尺寸上绘制圆角矩形 + 文字 → crop-paste 隔离
        """
        r = edit_op.region
        x, y, w, h = r['x'], r['y'], r['width'], r['height']

        img_w, img_h = image.size
        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))
        w = min(w, img_w - x)
        h = min(h, img_h - y)

        if w <= 0 or h <= 0:
            return image

        # 取出原区域
        original_region = image.crop((x, y, x + w, y + h)).convert('RGBA')

        # 在局部区域尺寸上绘制角标
        badge = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(badge)

        # 角标配色
        hint = edit_op.style_hint
        badge_bg = self._parse_color(hint.get('bg_color', '#FF4D4F'))
        badge_text_color = self._parse_color(hint.get('text_color', '#FFFFFF'))

        # 绘制圆角矩形背景（填满整个局部区域）
        radius = min(h // 2, 12)
        draw.rounded_rectangle(
            [0, 0, w - 1, h - 1],
            radius=radius,
            fill=(*badge_bg, 230)
        )

        # 绘制文字（居中）
        font_size = max(12, h - 8)
        font = self._get_font(font_size, bold=True)
        text_bbox = draw.textbbox((0, 0), edit_op.content, font=font)
        text_w = text_bbox[2] - text_bbox[0]
        text_h = text_bbox[3] - text_bbox[1]
        text_x = (w - text_w) // 2
        text_y = (h - text_h) // 2
        text_x = (w - text_w) // 2
        text_y = (h - text_h) // 2

        draw.text(
            (text_x, text_y),
            edit_op.content,
            font=font,
            fill=(*badge_text_color, 255)
        )

        # alpha_composite 在局部区域上合并，然后 paste 回原图
        merged = Image.alpha_composite(original_region, badge)

        result = image.copy()
        result.paste(merged, (x, y), merged)
        return result

    def _exec_expand_card(
        self,
        image: Image.Image,
        edit_op: EditOp,
        ui_json: dict
    ) -> Image.Image:
        """
        卡片扩展：保留原卡片所有像素，向下撑高插入新文字行，后续内容自动下移。

        原理：
        1. 确定目标组件位置（卡片内最后一行文字）
        2. 计算插入行所需的高度（文字高度 + padding）
        3. 创建新画布（原图高度 + 插入高度）
        4. 拷贝: 上半部分（含目标组件）原样 → 新文字行 → 下半部分下移
        5. 结果：原有像素全部保留，仅多了一个插入带

        Returns:
            扩展后的图像（高度增加）
        """
        r = edit_op.region
        target_y = r['y']
        target_h = r['height']
        card_x = r['x']
        card_w = r['width']

        img_w, img_h = image.size

        # 确定风格
        style = self._resolve_style(image, edit_op, ui_json)
        font = self._get_font(style.font_size, style.font_weight == 'bold', style.font_path)

        # 计算插入行的实际需要高度
        padding_top = edit_op.style_hint.get('padding_top', 8)
        padding_bottom = edit_op.style_hint.get('padding_bottom', 12)
        padding_x = max(12, int(card_w * 0.03))

        # 计算文字渲染后的高度（支持自动换行）
        temp_img = Image.new('RGBA', (1, 1))
        temp_draw = ImageDraw.Draw(temp_img)
        lines = self._wrap_text(edit_op.content, card_w - padding_x * 2, font, temp_draw)

        line_spacing = max(4, int(style.font_size * 0.3))
        total_text_h = 0
        line_heights = []
        for line in lines:
            bbox = temp_draw.textbbox((0, 0), line, font=font)
            lh = bbox[3] - bbox[1]
            line_heights.append(lh)
            total_text_h += lh
        total_text_h += line_spacing * (len(lines) - 1) if len(lines) > 1 else 0

        insert_h = padding_top + total_text_h + padding_bottom

        # 分割点：目标组件底部（新文字插入在此处）
        split_y = target_y + target_h

        print(f"    卡片扩展: split_y={split_y}, insert_h={insert_h}px, lines={len(lines)}")
        print(f"    文字: \"{edit_op.content[:40]}\"")

        # === 构建新画布 ===
        new_h = img_h + insert_h
        new_image = Image.new('RGBA', (img_w, new_h), (0, 0, 0, 0))

        # Part 1: 上半部分 — 原图 [0, split_y) 原样拷贝
        upper = image.crop((0, 0, img_w, split_y))
        new_image.paste(upper, (0, 0))

        # Part 2: 插入带 — 采样背景色，绘制新文字
        # 从目标组件所在行采样背景色（取 split_y 上方 1px 横条）
        sample_row_y = max(0, split_y - 1)
        sample_strip = image.crop((card_x, sample_row_y, card_x + card_w, sample_row_y + 1))
        bg_color = self._sample_background_color(sample_strip)

        # 插入带占满全宽（左右用原图对应行的像素填充，保持连续性）
        insert_band = Image.new('RGBA', (img_w, insert_h), (0, 0, 0, 0))

        # 先用分割点上方一行像素纵向拉伸填充整个插入带（保持左右边缘连续）
        edge_row = image.crop((0, sample_row_y, img_w, sample_row_y + 1))
        for iy in range(insert_h):
            insert_band.paste(edge_row, (0, iy))

        # 在卡片区域内用纯背景色覆盖（文字绘制区）
        draw_band = ImageDraw.Draw(insert_band)
        draw_band.rectangle(
            [card_x, 0, card_x + card_w, insert_h],
            fill=(*bg_color, 255)
        )

        # 绘制文字
        current_y = padding_top
        for i, line in enumerate(lines):
            draw_band.text(
                (card_x + padding_x, current_y),
                line,
                font=font,
                fill=(*style.font_color, 255)
            )
            current_y += line_heights[i] + line_spacing

        new_image.paste(insert_band, (0, split_y))

        # Part 3: 下半部分 — 原图 [split_y, img_h) 下移 insert_h
        lower = image.crop((0, split_y, img_w, img_h))
        new_image.paste(lower, (0, split_y + insert_h))

        return new_image

    # ==================== 4. 边缘处理 ====================

    def _feather_edges(
        self,
        edit_layer: Image.Image,
        original_region: Image.Image,
        feather_px: int = 2
    ) -> Image.Image:
        """
        边缘羽化：让编辑区域边缘与原图自然融合

        对编辑层的边缘 feather_px 像素做 alpha 渐变，
        使编辑区域的边界与原图柔和过渡，避免硬切割。
        """
        w, h = edit_layer.size

        if feather_px <= 0 or w < feather_px * 2 + 1 or h < feather_px * 2 + 1:
            return edit_layer

        # 构建 alpha mask：中心为 255，边缘渐变到 0
        mask = Image.new('L', (w, h), 255)

        for i in range(feather_px):
            alpha = int(255 * (i + 1) / (feather_px + 1))
            draw_mask = ImageDraw.Draw(mask)
            # 上边缘
            draw_mask.line([(0, i), (w - 1, i)], fill=alpha)
            # 下边缘
            draw_mask.line([(0, h - 1 - i), (w - 1, h - 1 - i)], fill=alpha)
            # 左边缘
            draw_mask.line([(i, 0), (i, h - 1)], fill=alpha)
            # 右边缘
            draw_mask.line([(w - 1 - i, 0), (w - 1 - i, h - 1)], fill=alpha)

        # 用 mask 混合编辑层和原区域
        original_rgba = original_region.convert('RGBA')
        edit_rgba = edit_layer.convert('RGBA')
        result = Image.composite(edit_rgba, original_rgba, mask)
        return result

    # ==================== 5. 批量执行 + Diff 验证 ====================

    def render_all(
        self,
        screenshot_path: str,
        ui_json: dict,
        instruction: str,
        edit_plan: List[EditOp] = None
    ) -> Tuple[Image.Image, List[EditOp]]:
        """
        完整渲染流程：规划编辑 → 逐步执行 → 返回结果

        Args:
            screenshot_path: 原始截图路径
            ui_json: Stage 2 UI-JSON
            instruction: 用户指令
            edit_plan: 预设的编辑计划（可选，为空则调用 VLM 规划）

        Returns:
            (编辑后图像, 执行的 EditOp 列表)
        """
        original = Image.open(screenshot_path).convert('RGBA')

        # 规划编辑操作
        if edit_plan is None:
            edit_plan = self.plan_edits(screenshot_path, ui_json, instruction)

        if not edit_plan:
            print(f"  ⚠ 无编辑操作，返回原图")
            return original, []

        # 串行执行每个编辑
        # expand_card 会改变图像高度，后续操作的 y 坐标需要累加偏移
        result = original.copy()
        executed_ops = []
        y_offset = 0  # 累计 y 偏移（由 expand_card 引起）

        for i, op in enumerate(edit_plan):
            # 如果有累计偏移，调整当前操作的 y 坐标
            if y_offset > 0 and op.action != 'expand_card':
                op_split_y = 0  # 默认不调整
                # 只调整位于已扩展区域下方的操作
                if op.region['y'] > 0:
                    op.region = dict(op.region)  # 避免修改原对象
                    op.region['y'] += y_offset

            if y_offset > 0 and op.action == 'expand_card':
                op.region = dict(op.region)
                op.region['y'] += y_offset

            print(f"  [执行 {i + 1}/{len(edit_plan)}] {op.action}: \"{op.content[:25]}\"")
            try:
                prev_h = result.size[1]
                result = self.apply_edit(result, op, ui_json)
                new_h = result.size[1]

                # 如果是 expand_card，记录高度变化
                if op.action == 'expand_card' and new_h > prev_h:
                    delta = new_h - prev_h
                    y_offset += delta
                    print(f"    ↕ 图像高度 +{delta}px (累计偏移: {y_offset}px)")

                executed_ops.append(op)
                print(f"    ✓ 完成")
            except Exception as e:
                print(f"    ✗ 失败: {e}")

        return result, executed_ops

    def save_diff_visualization(
        self,
        original: Image.Image,
        edited: Image.Image,
        output_path: str,
        amplify: int = 10
    ):
        """
        生成 diff 可视化图：标红所有被修改的像素

        Args:
            original: 原始图像
            edited: 编辑后图像
            output_path: 输出路径
            amplify: 差异放大倍数
        """
        try:
            import numpy as np
            orig_rgb = original.convert('RGB')
            edit_rgb = edited.convert('RGB')

            # expand_card 会改变图像高度，需要统一尺寸
            ow, oh = orig_rgb.size
            ew, eh = edit_rgb.size
            if ow != ew or oh != eh:
                # 用黑色填充较小图像使尺寸一致
                max_w, max_h = max(ow, ew), max(oh, eh)
                if ow < max_w or oh < max_h:
                    padded = Image.new('RGB', (max_w, max_h), (0, 0, 0))
                    padded.paste(orig_rgb, (0, 0))
                    orig_rgb = padded
                if ew < max_w or eh < max_h:
                    padded = Image.new('RGB', (max_w, max_h), (0, 0, 0))
                    padded.paste(edit_rgb, (0, 0))
                    edit_rgb = padded

            orig_arr = np.array(orig_rgb, dtype=np.int16)
            edit_arr = np.array(edit_rgb, dtype=np.int16)

            diff = np.abs(orig_arr - edit_arr)
            diff_sum = diff.sum(axis=2)  # 每像素 R+G+B 差异总和

            changed_mask = diff_sum > 0
            changed_count = int(changed_mask.sum())

            # 构建 diff 图像
            h, w = orig_arr.shape[:2]
            diff_arr = np.zeros((h, w, 3), dtype=np.uint8)

            # 被修改像素：红色通道标记，亮度=差异程度
            intensity = np.clip(diff_sum * amplify, 0, 255).astype(np.uint8)
            diff_arr[changed_mask, 0] = intensity[changed_mask]

            # 未修改像素：暗灰色显示原图轮廓
            gray = orig_arr[~changed_mask].mean(axis=1).astype(np.uint8) // 3
            diff_arr[~changed_mask, 0] = gray
            diff_arr[~changed_mask, 1] = gray
            diff_arr[~changed_mask, 2] = gray

            diff_img = Image.fromarray(diff_arr)
            diff_img.save(output_path)

        except ImportError:
            # numpy 不可用时，用纯 PIL 实现（慢但可用）
            orig_rgb = original.convert('RGB')
            edit_rgb = edited.convert('RGB')
            # 统一尺寸
            ow, oh = orig_rgb.size
            ew, eh = edit_rgb.size
            max_w, max_h = max(ow, ew), max(oh, eh)
            if ow < max_w or oh < max_h:
                padded = Image.new('RGB', (max_w, max_h), (0, 0, 0))
                padded.paste(orig_rgb, (0, 0))
                orig_rgb = padded
            if ew < max_w or eh < max_h:
                padded = Image.new('RGB', (max_w, max_h), (0, 0, 0))
                padded.paste(edit_rgb, (0, 0))
                edit_rgb = padded

            w, h = orig_rgb.size
            diff_img = Image.new('RGB', (w, h), (0, 0, 0))
            draw_diff = ImageDraw.Draw(diff_img)
            changed_count = 0

            for py in range(h):
                for px in range(w):
                    r1, g1, b1 = orig_rgb.getpixel((px, py))
                    r2, g2, b2 = edit_rgb.getpixel((px, py))
                    dr, dg, db = abs(r1 - r2), abs(g1 - g2), abs(b1 - b2)
                    if dr + dg + db > 0:
                        changed_count += 1
                        val = min(255, (dr + dg + db) * amplify)
                        draw_diff.point((px, py), fill=(val, 0, 0))
                    else:
                        g = (r1 + g1 + b1) // 9
                        draw_diff.point((px, py), fill=(g, g, g))
            diff_img.save(output_path)

        total_pixels = edited.size[0] * edited.size[1]
        pct = changed_count / total_pixels * 100 if total_pixels > 0 else 0
        print(f"  ✓ Diff 可视化: {output_path}")
        print(f"    修改像素: {changed_count}/{total_pixels} ({pct:.2f}%)")

    # ==================== 辅助函数 ====================

    def _call_vlm_with_image(self, image_path: str, prompt: str) -> Optional[str]:
        """调用 VLM API（图文输入）"""
        if not self.api_key:
            return None

        try:
            image_base64 = encode_image(image_path)
            mime_type = get_mime_type(image_path)

            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }

            payload = {
                'model': self.vlm_model,
                'messages': [
                    {
                        'role': 'user',
                        'content': [
                            {
                                'type': 'image_url',
                                'image_url': {'url': f'data:{mime_type};base64,{image_base64}'}
                            },
                            {'type': 'text', 'text': prompt}
                        ]
                    }
                ],
                'temperature': 0.3,
                'max_tokens': 2000
            }

            response = requests.post(
                self.vlm_api_url,
                headers=headers,
                json=payload,
                timeout=120
            )
            response.raise_for_status()

            content = response.json()['choices'][0]['message']['content']
            return content

        except Exception as e:
            print(f"  ⚠ VLM 调用失败: {e}")
            return None

    def _extract_json_array(self, text: str) -> list:
        """从 VLM 输出中提取 JSON 数组"""
        # 尝试直接解析
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

        # 尝试提取 ```json ... ``` 代码块
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if json_match:
            try:
                result = json.loads(json_match.group(1))
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

        # 尝试提取 [ ... ] 块
        bracket_match = re.search(r'\[[\s\S]*\]', text)
        if bracket_match:
            result = json.loads(bracket_match.group(0))
            if isinstance(result, list):
                return result

        raise ValueError(f"无法提取 JSON 数组: {text[:200]}...")

    def _get_font(
        self,
        size: int,
        bold: bool = False,
        font_path: str = None
    ) -> ImageFont.FreeTypeFont:
        """获取字体，带缓存"""
        cache_key = (size, bold, font_path)
        if cache_key in self._font_cache:
            return self._font_cache[cache_key]

        path = font_path or self._find_font()
        if path:
            try:
                font = ImageFont.truetype(path, size)
                self._font_cache[cache_key] = font
                return font
            except Exception:
                pass

        font = ImageFont.load_default()
        self._font_cache[cache_key] = font
        return font

    def _find_font(self) -> Optional[str]:
        """查找可用的中文字体"""
        candidates = [
            # Windows
            'C:/Windows/Fonts/msyh.ttc',
            'C:/Windows/Fonts/msyhbd.ttc',
            'C:/Windows/Fonts/simhei.ttf',
            # macOS
            '/System/Library/Fonts/PingFang.ttc',
            '/System/Library/Fonts/STHeiti Light.ttc',
            # Linux
            '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ]

        # 自定义字体目录优先
        if self.fonts_dir:
            font_dir = Path(self.fonts_dir)
            for f in font_dir.glob('*.ttf'):
                candidates.insert(0, str(f))
            for f in font_dir.glob('*.ttc'):
                candidates.insert(0, str(f))

        for path in candidates:
            if Path(path).exists():
                return path

        return None

    def _wrap_text(
        self,
        text: str,
        max_width: int,
        font: ImageFont.FreeTypeFont,
        draw: ImageDraw.ImageDraw = None
    ) -> List[str]:
        """文本自动换行"""
        if draw is None:
            temp_img = Image.new('RGBA', (1, 1))
            draw = ImageDraw.Draw(temp_img)

        lines = []
        current_line = ""

        for char in text:
            test_line = current_line + char
            bbox = draw.textbbox((0, 0), test_line, font=font)
            line_width = bbox[2] - bbox[0]

            if line_width <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = char

        if current_line:
            lines.append(current_line)

        return lines if lines else [text]

    @staticmethod
    def _parse_color(color_str: str) -> Tuple[int, int, int]:
        """解析颜色字符串 (#RRGGBB 或 RGB tuple)"""
        if isinstance(color_str, (list, tuple)):
            return tuple(color_str[:3])

        if isinstance(color_str, str) and color_str.startswith('#'):
            hex_str = color_str.lstrip('#')
            if len(hex_str) == 6:
                return (
                    int(hex_str[0:2], 16),
                    int(hex_str[2:4], 16),
                    int(hex_str[4:6], 16)
                )

        return (255, 77, 79)  # 默认红色
