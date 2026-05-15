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
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from datetime import datetime

from .base import BaseRenderer, RenderResult
from app.core.schemas import TextStyle, EditOp
from app.core.config import config
from app.utils.common import encode_image, get_mime_type, extract_json

# PaddleOCR 离线模型路径配置（使用集中配置）
_PADDLEOCR_MODEL_DIR = config.PADDLEOCR_MODEL_DIR


# ==================== 数据结构 ====================

# TextStyle and EditOp are now defined in app.core.schemas


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


MODIFY_TEXT_PLAN_PROMPT = """你是一个App UI像素级编辑专家。给定一张App截图，你需要精确定位并规划文字替换操作。

## 截图信息
- 图像尺寸: {img_width}x{img_height} 像素

## 用户编辑指令
{instruction}

## 任务
仔细观察截图，找到所有需要修改的文字区域，为每个区域输出一个 modify_text 操作。
每个操作需要精确指定文字所在的像素矩形（region），确保只覆盖目标文字，不影响周围元素。

## 操作说明
`modify_text`：擦除原文字，在同一位置用相同背景色和风格绘制新文字。
要点：
- region 必须精确包裹目标文字，宁可略小也不要过大（避免误覆盖相邻元素）
- 同一类文字（如多行的席别票量）每行分别输出一个操作
- font_color 直接从截图视觉判断（灰色/红色/绿色等）
- font_size 根据文字高度估算（像素高度的 60%~70%）

## 输出格式（严格JSON数组，只输出JSON不要其他内容）
```json
[
  {{
    "action": "modify_text",
    "region": {{
      "x": 443,
      "y": 1230,
      "width": 80,
      "height": 36
    }},
    "content": "无票",
    "target_component": null,
    "style_hint": {{
      "font_size": 24,
      "font_color": "#999999"
    }},
    "reference_component": null
  }}
]
```

## 字段说明
- `region.x/y`: 文字区域左上角坐标（像素）
- `region.width/height`: 文字区域尺寸（像素），精确包裹文字即可
- `content`: 替换后的文字内容
- `style_hint.font_size`: 字号（像素），文字高度的 60%~70%
- `style_hint.font_color`: 文字颜色（十六进制，如 "#999999" 灰、"#FF4444" 红）

## 注意事项
1. 必须逐行输出，同一行里有多个需要修改的字段也要分开（每个字段一个操作）
2. region 坐标基于原始图像像素，请仔细对照截图位置
3. 只返回JSON数组，不要说明文字"""


MODIFY_TEXT_AI_PLAN_PROMPT = """你是一个App UI编辑专家。给定一张App截图和它的UI组件结构(UI-JSON)，根据用户指令规划文字修改操作。

## UI-JSON 组件列表
```json
{components_json}
```

## 用户编辑指令
{instruction}

## 任务
分析截图和UI结构，找到需要修改文字的目标区域（通常是一个卡片或一组相关元素），输出编辑操作列表。
每个操作对应一个组件区域，包含该区域内所有需要的文字修改。

## 输出格式（严格JSON数组，只输出JSON不要其他内容）
```json
[
  {{
    "target_component": 8,
    "related_component_ids": [9, 10],
    "edit_description": "将该车次卡片中的票量信息全部改为无票状态",
    "text_changes": [
      {{"from": "售磬", "to": "无票"}},
      {{"from": "有票", "to": "无票"}},
      {{"from": "3张", "to": "无票"}},
      {{"from": "8张", "to": "无票"}}
    ],
    "button_changes": [
      {{"from": "预订", "to": "预订", "state": "disabled_gray"}},
      {{"from": "候补", "to": "候补", "state": "disabled_gray"}}
    ]
  }}
]
```

## 字段说明
- `target_component`: UI-JSON 中目标主组件 index（优先选择车次主卡片）
- `related_component_ids`: 与同一车次强相关的附属组件 index 列表（如席位列表、预订按钮区），可选
- `edit_description`: 自然语言描述该区域需要做的修改（用于生成图像编辑指令）
- `text_changes`: 具体的文字替换列表，from=原文字（与截图中实际显示的完全一致），to=替换后的文字
- `button_changes`: 需要联动修改的按钮（可选）。当用户要求“无票且按钮灰色/禁用”时必须提供；state 统一用 `disabled_gray`

## 注意事项
1. 优先选择卡片级组件（class 为 Card、Container 等大区域），将同一卡片内的多处修改合并为一个操作
2. text_changes.from 要与截图中实际显示的文字完全一致
3. 如果有多个相似的卡片都需要修改，每个卡片分别输出一个操作
4. 当指令提到“按钮灰色/按钮禁用/不可点击”时，必须输出 button_changes
5. 若目标信息跨多个组件（常见于票务页面：主卡片 + 席位列表 + 预订按钮），必须在 related_component_ids 中列出这些组件
5. 只返回JSON数组，不要说明文字"""


# ==================== 渲染器主类 ====================

class TextOverlayRenderer(BaseRenderer):
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
        self._debug_crop_root: Optional[Path] = None
        self._debug_crop_counter: int = 0

    # ==================== 1. VLM 编辑规划 ====================

    def plan_edits(
        self,
        screenshot_path: str,
        ui_json: dict,
        instruction: str,
        mode: str = 'default'
    ) -> List[EditOp]:
        """
        VLM 分析截图和UI结构，生成编辑操作列表

        Args:
            screenshot_path: 原始截图路径
            ui_json: Stage 2 过滤后的UI-JSON
            instruction: 用户编辑指令
            mode: 控制规划策略，modify_text 时走像素级规划

        Returns:
            EditOp 列表
        """
        print(f"  [编辑规划] 正在分析页面...")

        # ---- modify_text_ai: 纯 AI 图像编辑模式 ----
        if mode == 'modify_text_ai':
            instruction_lower = instruction.lower()
            need_disable_button = (
                ('按钮' in instruction and ('灰' in instruction or '禁用' in instruction or '不可点击' in instruction))
                or ('button' in instruction_lower and ('gray' in instruction_lower or 'grey' in instruction_lower or 'disable' in instruction_lower))
            )
            # 内容名篡改类指令（"误杀3→误杀6"、"长津湖→常津湖"）走 OCR+PIL，
            # AI 图像编辑裁切范围过大且语义合并后定位不准
            is_text_tamper = any(kw in instruction for kw in ('改成', '改为', '替换为', '→', '->'))
            if is_text_tamper:
                print("  ℹ modify_text_ai 检测到内容名篡改指令，切换至 OCR+PIL 路径")
                return self.plan_edits(screenshot_path, ui_json, instruction, mode='modify_text_ocr')
            ai_plan = self._plan_modify_text_ai_edits(screenshot_path, ui_json, instruction)
            if ai_plan is not None:
                # 对“无票 + 按钮灰色禁用”场景优先走 OCR 精定位 + PIL，
                # 避免 AI 区域编辑把整块内容误去色。
                if need_disable_button or any(op.style_hint.get('need_disable_button') for op in ai_plan):
                    ocr_plan = self._refine_ops_with_ocr(
                        ai_plan,
                        screenshot_path,
                        include_button_changes=True
                    )
                    if ocr_plan:
                        print("  ✓ modify_text_ai 已切换为 OCR 精定位灰化策略")
                        return ocr_plan
                    # OCR 没命中时，禁止回落到大区域 AI 编辑（会导致整体变灰）
                    if self._is_seat_specific_instruction(instruction):
                        print("  ⚠ OCR 精定位未命中，且为席位定向指令；为避免误改行，本次不执行降级编辑")
                        return []
                    print("  ⚠ OCR 精定位未命中，回退到像素级 VLM 规划（禁用大区域AI编辑）")
                    modify_plan = self._plan_modify_text_edits(screenshot_path, instruction)
                    if modify_plan is not None:
                        return modify_plan
                    print("  ⚠ 像素级规划也失败，返回空编辑以避免误改整块区域")
                    return []
                return ai_plan
            print("  ⚠ AI 规划失败，回退到像素级 VLM 规划")
            modify_plan = self._plan_modify_text_edits(screenshot_path, instruction)
            if modify_plan is not None:
                return modify_plan
            print("  ⚠ modify_text_ai 规划失败，回退至默认策略")

        # ---- modify_text_ocr: 纯 OCR 精定位 + PIL 渲染 ----
        if mode in ('modify_text_ocr', 'modify_text'):
            # 先用 VLM 获取卡片级目标（复用 AI 规划的 VLM 定位能力）
            card_plan = self._plan_modify_text_ai_edits(screenshot_path, ui_json, instruction)
            if card_plan is not None:
                # OCR 精定位：只保留 OCR 匹配到的文字级操作
                ocr_plan = self._refine_ops_with_ocr(card_plan, screenshot_path)
                if ocr_plan:
                    return ocr_plan
                print("  ⚠ OCR 精定位无匹配结果")
            else:
                print("  ⚠ VLM 组件定位失败")
            # 回退到像素级 VLM 规划
            print("  ⚠ 回退到像素级 VLM 规划")
            modify_plan = self._plan_modify_text_edits(screenshot_path, instruction)
            if modify_plan is not None:
                return modify_plan
            print("  ⚠ modify_text_ocr 规划失败，回退至默认策略")

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

    def _plan_modify_text_edits(
        self,
        screenshot_path: str,
        instruction: str
    ) -> Optional[List[EditOp]]:
        """像素级 modify_text 模式下的规划逻辑"""
        print("  [ModifyText规划] 使用像素级坐标模式")

        try:
            with Image.open(screenshot_path) as img:
                img_w, img_h = img.size
        except Exception as exc:
            print(f"  ✗ 无法读取截图: {exc}")
            return None

        prompt = MODIFY_TEXT_PLAN_PROMPT.format(
            img_width=img_w,
            img_height=img_h,
            instruction=instruction
        )

        raw_plan = self._call_vlm_with_image(screenshot_path, prompt)
        if not raw_plan:
            print("  ✗ modify_text 规划调用失败")
            return None

        try:
            plan_data = self._extract_json_array(raw_plan)
        except Exception as exc:
            print(f"  ✗ JSON 解析失败: {exc}")
            return None

        edit_ops: List[EditOp] = []
        for item in plan_data:
            op = self._parse_modify_text_op(item)
            if op:
                edit_ops.append(op)

        print(f"  ✓ modify_text 规划完成: {len(edit_ops)} 个操作")
        for i, op in enumerate(edit_ops):
            r = op.region
            print(f"    [{i}] region=({r['x']},{r['y']},{r['width']}x{r['height']}) → \"{op.content[:30]}\"")

        return edit_ops

    def _parse_modify_text_op(self, item: dict) -> Optional[EditOp]:
        """解析 modify_text 专用的 VLM 输出"""
        if not isinstance(item, dict):
            return None

        action = item.get('action') or 'modify_text'
        if action != 'modify_text':
            return None

        content = item.get('content', '').strip()
        if not content:
            return None

        region_src = item.get('region') or {}

        def _to_int(value, default=0):
            try:
                return int(round(float(value)))
            except (TypeError, ValueError):
                return default

        region = {
            'x': max(0, _to_int(region_src.get('x'), 0)),
            'y': max(0, _to_int(region_src.get('y'), 0)),
            'width': max(1, _to_int(region_src.get('width'), 1)),
            'height': max(1, _to_int(region_src.get('height'), 1)),
        }

        style_hint = item.get('style_hint') or {}

        return EditOp(
            action='modify_text',
            region=region,
            content=content,
            target_component=item.get('target_component'),
            style_hint=style_hint,
            reference_component=item.get('reference_component'),
        )

    def _plan_modify_text_ai_edits(
        self,
        screenshot_path: str,
        ui_json: dict,
        instruction: str
    ) -> Optional[List[EditOp]]:
        """
        AI 图像编辑模式的规划逻辑：利用 UI-JSON 组件信息定位目标卡片。

        与 _plan_modify_text_edits 不同，本方法不要求 VLM 估算像素坐标，
        而是让 VLM 选择 Stage 2 分组后的组件 index 并描述文字修改，
        由组件的 bounds 提供精确的裁切区域。

        Returns:
            EditOp 列表（style_hint 中含 use_ai_edit=True 和 text_changes），
            或 None 表示规划失败。
        """
        print("  [ModifyText-AI规划] 使用 UI-JSON 组件定位 + AI 图像编辑")

        components = ui_json.get('components', [])
        if not components:
            print("  ✗ UI-JSON 无组件数据，无法使用 AI 规划")
            return None

        # 精简组件信息
        slim_components = []
        for c in components:
            slim_components.append({
                'index': c.get('index'),
                'class': c.get('class'),
                'bounds': c.get('bounds'),
                'text': c.get('text', '')[:80],
            })
        components_json = json.dumps(slim_components, ensure_ascii=False, indent=2)

        prompt = MODIFY_TEXT_AI_PLAN_PROMPT.format(
            components_json=components_json,
            instruction=instruction
        )

        raw_plan = self._call_vlm_with_image(screenshot_path, prompt)
        if not raw_plan:
            print("  ✗ AI 规划 VLM 调用失败")
            return None

        try:
            plan_data = self._extract_json_array(raw_plan)
        except Exception as exc:
            print(f"  ✗ JSON 解析失败: {exc}")
            return None

        # 从原始指令中直接提取颜色要求（不依赖 VLM 保留颜色词）
        _color_kws = ['灰色', '红色', '绿色', '蓝色', '黑色', '白色', '橙色', '黄色',
                      'gray', 'grey', 'red', 'green', 'blue', 'black', 'white']
        color_requirement = next((kw for kw in _color_kws if kw in instruction), None)
        instruction_lower = instruction.lower()
        need_disable_button = (
            ('按钮' in instruction and ('灰' in instruction or '禁用' in instruction or '不可点击' in instruction))
            or ('button' in instruction_lower and ('gray' in instruction_lower or 'grey' in instruction_lower or 'disable' in instruction_lower))
        )

        # 将 VLM 规划转换为 EditOp（使用组件 bounds 作为 region）
        edit_ops: List[EditOp] = []
        comp_by_index = {c.get('index'): c for c in components}
        for item in plan_data:
            target_idx = item.get('target_component')
            related_ids_raw = item.get('related_component_ids', [])
            edit_desc = item.get('edit_description', '')
            text_changes = item.get('text_changes', [])
            button_changes = item.get('button_changes', [])

            if target_idx is None or not text_changes:
                continue

            # 查找目标组件
            target_comp = comp_by_index.get(target_idx)

            if not target_comp:
                print(f"    ⚠ 目标组件 {target_idx} 未找到，跳过")
                continue

            # 解析并集组件：target + related_component_ids
            related_ids: List[int] = []
            if isinstance(related_ids_raw, list):
                for rid in related_ids_raw:
                    try:
                        rid_int = int(rid)
                    except (TypeError, ValueError):
                        continue
                    if rid_int != target_idx and rid_int in comp_by_index:
                        related_ids.append(rid_int)

            region_components = [target_comp] + [comp_by_index[rid] for rid in related_ids]
            xs = []
            ys = []
            x2s = []
            y2s = []
            for c in region_components:
                b = c.get('bounds', {})
                x = int(b.get('x', 0))
                y = int(b.get('y', 0))
                w = int(b.get('width', 100))
                h = int(b.get('height', 100))
                xs.append(x)
                ys.append(y)
                x2s.append(x + w)
                y2s.append(y + h)

            region = {
                'x': min(xs) if xs else 0,
                'y': min(ys) if ys else 0,
                'width': (max(x2s) - min(xs)) if xs else 100,
                'height': (max(y2s) - min(ys)) if ys else 100,
            }

            # 构建编辑描述作为 content
            changes_desc = '；'.join(
                f'将"{tc.get("from", "")}"改为"{tc.get("to", "")}"'
                for tc in text_changes
            )

            op = EditOp(
                action='modify_text',
                region=region,
                content=f"{edit_desc}：{changes_desc}",
                target_component=target_idx,
                style_hint={
                    'use_ai_edit': True,
                    'text_changes': text_changes,
                    'button_changes': button_changes,
                    'edit_description': edit_desc,
                    'related_component_ids': related_ids,
                    'color_requirement': color_requirement,   # 直接从原始指令提取，不依赖VLM
                    'original_instruction': instruction,       # 保留原始指令供执行阶段使用
                    'need_disable_button': need_disable_button,
                },
                reference_component=target_idx,
            )
            edit_ops.append(op)

        if not edit_ops:
            print("  ✗ AI 规划未产生有效操作")
            return None

        print(f"  ✓ AI 规划完成: {len(edit_ops)} 个操作")
        for i, op in enumerate(edit_ops):
            r = op.region
            n_changes = len(op.style_hint.get('text_changes', []))
            n_btn_changes = len(op.style_hint.get('button_changes', []))
            related_cnt = len(op.style_hint.get('related_component_ids', []))
            print(f"    [{i}] 组件{op.target_component}+{related_cnt}关联组件 ({r['width']}x{r['height']}) {n_changes}处文字修改, {n_btn_changes}处按钮联动")

        return edit_ops

    # ==================== OCR 精定位 ====================

    def _get_paddle_ocr(self):
        """懒加载 PaddleOCR（中文模式，离线模式），不可用时返回 None"""
        if hasattr(self, '_paddle_ocr_instance'):
            return self._paddle_ocr_instance
        try:
            from paddleocr import PaddleOCR
            import torch

            # 优先使用中文模型
            det_model_dir = _PADDLEOCR_MODEL_DIR / "det" / "ch" / "ch_PP-OCRv4_det_infer"
            rec_model_dir = _PADDLEOCR_MODEL_DIR / "rec" / "ch" / "ch_PP-OCRv4_rec_infer"
            cls_model_dir = _PADDLEOCR_MODEL_DIR / "cls" / "ch_ppocr_mobile_v2.0_cls_infer"

            # 如果中文模型不存在，回退到英文模型
            if not det_model_dir.exists():
                det_model_dir = _PADDLEOCR_MODEL_DIR / "det" / "en_PP-OCRv3_det_infer"
                print("    ⓘ PaddleOCR 中文检测模型不存在，使用英文检测模型")

            if not rec_model_dir.exists():
                rec_model_dir = _PADDLEOCR_MODEL_DIR / "rec" / "en_PP-OCRv4_rec_infer"
                print("    ⓘ PaddleOCR 中文识别模型不存在，使用英文识别模型")

            if not det_model_dir.exists() or not rec_model_dir.exists():
                print(f"    ⚠ PaddleOCR 本地模型不存在: {det_model_dir}, {rec_model_dir}")
                self._paddle_ocr_instance = None
                return None

            use_gpu = torch.cuda.is_available()
            self._paddle_ocr_instance = PaddleOCR(
                det_model_dir=str(det_model_dir),
                rec_model_dir=str(rec_model_dir),
                cls_model_dir=str(cls_model_dir),
                use_angle_cls=False,
                use_gpu=use_gpu,
                show_log=False,
                lang='ch'  # 使用中文模式
            )

            # 根据实际使用的模型输出提示信息
            det_type = "中文检测" if 'ch' in str(det_model_dir) else "英文检测"
            rec_type = "中文识别" if 'ch' in str(rec_model_dir) else "英文识别"
            print(f"    ✓ PaddleOCR ({det_type}+{rec_type}, 离线模式) 初始化成功")
        except Exception as e:
            print(f"    ⚠ PaddleOCR 初始化失败: {e}")
            self._paddle_ocr_instance = None
        return self._paddle_ocr_instance

    def _text_match(self, target: str, ocr_text: str) -> bool:
        """判断 OCR 识别文字是否匹配目标文字"""
        target = target.strip()
        ocr_text = ocr_text.strip()
        if not target or not ocr_text:
            return False
        # 精确匹配
        if target == ocr_text:
            return True
        # 目标包含在 OCR 结果中（OCR 多识别了一些字符）
        if target in ocr_text and len(target) >= max(1, len(ocr_text) * 0.5):
            return True
        # OCR 结果包含在目标中（OCR 少识别了一些字符）
        if ocr_text in target and len(ocr_text) >= max(1, len(target) * 0.5):
            return True
        return False

    @staticmethod
    def _looks_like_ticket_status(text: str) -> bool:
        """是否像票量状态文本（如 有票/无票/16张/售罄）"""
        t = (text or '').strip()
        if not t:
            return False
        if t in ('有票', '无票', '售磬', '售罄'):
            return True
        if re.fullmatch(r'\d+\s*张', t):
            return True
        if re.fullmatch(r'\d+', t):
            return True
        return False

    @staticmethod
    def _extract_target_seat_keyword(instruction: str) -> Optional[str]:
        """从指令中提取目标席位关键词（优先长词）。"""
        text = instruction or ''
        seat_keywords = ['高级软卧', '商务座', '硬卧', '软卧', '硬座', '无座', '二等', '一等']
        return next((kw for kw in seat_keywords if kw in text), None)

    def _find_row_anchor_y(self, ocr_items: List[dict], instruction: str) -> Optional[float]:
        """
        根据指令中的席位关键词（如硬卧/软卧）在 OCR 结果中找行锚点 y，
        用于“状态文本”兜底匹配时对齐同一行。
        """
        target_kw = self._extract_target_seat_keyword(instruction)
        if not target_kw:
            return None

        def _kw_centers(kw: str) -> List[float]:
            ys = []
            for item in ocr_items:
                txt = (item.get('text') or '').strip()
                if kw in txt:
                    b = item.get('bbox', {})
                    ys.append(b.get('y', 0) + b.get('height', 0) / 2)
            return ys

        # 1) 精确命中
        exact = _kw_centers(target_kw)
        if exact:
            exact.sort()
            return exact[len(exact) // 2]

        # 2) 硬卧缺失时用“硬座-软卧”两行推断中间行
        if target_kw == '硬卧':
            upper = _kw_centers('硬座')
            lower = _kw_centers('软卧')
            if upper and lower:
                uy = sorted(upper)[len(upper) // 2]
                ly = sorted(lower)[len(lower) // 2]
                return (uy + ly) / 2.0

        # 其它情况不盲猜，避免改错行
        return None

    def _save_debug_component_artifacts(
        self,
        screenshot: Image.Image,
        card_box_abs: Tuple[int, int, int, int],
        crop_image: Image.Image,
        ocr_items: List[dict],
        op: EditOp,
    ) -> Optional[Path]:
        """保存中间组件裁剪图与 OCR 结果，便于定位问题。"""
        if self._debug_crop_root is None:
            return None
        try:
            self._debug_crop_counter += 1
            comp_id = op.target_component if op.target_component is not None else "na"
            op_dir = self._debug_crop_root / f"op_{self._debug_crop_counter:02d}_comp_{comp_id}"
            op_dir.mkdir(parents=True, exist_ok=True)

            # 1) 卡片裁剪图
            crop_path = op_dir / "card_crop.png"
            crop_image.save(crop_path)

            # 2) OCR 可视化（在裁剪图上画框）
            ocr_vis = crop_image.convert('RGBA').copy()
            draw = ImageDraw.Draw(ocr_vis)
            for i, item in enumerate(ocr_items):
                b = item.get('bbox', {})
                x, y = b.get('x', 0), b.get('y', 0)
                w, h = b.get('width', 1), b.get('height', 1)
                draw.rectangle([(x, y), (x + w, y + h)], outline=(255, 80, 80, 255), width=2)
                label = f"{i}:{(item.get('text') or '')[:10]}"
                draw.text((x + 1, max(0, y - 14)), label, fill=(255, 80, 80, 255))
            ocr_vis.save(op_dir / "card_crop_ocr_boxes.png")

            # 3) OCR 原始结构 + 指令上下文
            x1, y1, x2, y2 = card_box_abs
            payload = {
                "target_component": op.target_component,
                "instruction": op.style_hint.get('original_instruction', ''),
                "card_box_abs": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                "ocr_items": ocr_items,
            }
            (op_dir / "ocr_items.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
            return op_dir
        except Exception as exc:
            print(f"    ⚠ 保存调试裁剪失败: {exc}")
            return None

    # ==================== 确定性文字定位 ====================

    def _locate_text_by_instruction(
        self,
        instruction: str,
        omni_components: List[Dict],
        ui_json: dict,
        screenshot_path: str,
    ) -> List[Dict]:
        """
        确定性文字定位：从指令中提取关键词 → Stage 1 OCR 匹配 → 查语义分组 → 返回裁剪区域。

        链路：
          instruction ("将硬卧改为灰色无票")
            → 提取关键词 ["硬卧", "无票"]
            → 在 omni_components[].text 中搜索
            → 找到匹配的 index → 在 ui_json merged component 中查 source_indices
            → 返回 component bounds + matched_text

        Args:
            instruction: 用户指令
            omni_components: Stage 1 OmniParser 原始检测结果 (含 OCR text)
            ui_json: Stage 2 VLM 语义分组后的合并 UI-JSON
            screenshot_path: 截图路径（用于确定图片尺寸和裁剪）

        Returns:
            List of {
                "matched_text": str,           # 匹配到的文字
                "omni_index": int,             # Stage 1 中的 index
                "component": dict,             # Stage 2 merged component
                "crop_bbox": (x1, y1, x2, y2), # 绝对坐标，用于裁剪
                "score": float,                # 匹配得分
            }
        """
        if not omni_components:
            print("    ℹ 无 omni_components，跳过确定性定位")
            return []

        # 1. 提取指令中的关键词（中文 + 数字 + 英文词）
        keywords = self._extract_keywords(instruction)
        if not keywords:
            print("    ℹ 未能从指令提取关键词")
            return []

        print(f"    [定位] 指令关键词: {keywords}")

        # 2. 在 Stage 1 omni_components 中搜索匹配
        img = Image.open(screenshot_path)
        img_w, img_h = img.size

        matches = []
        for comp in omni_components:
            text = (comp.get('text') or '').strip()
            if not text:
                continue
            score = self._match_score(text, keywords)
            if score > 0:
                matches.append({
                    'omni_index': comp.get('index', -1),
                    'text': text,
                    'score': score,
                    'bounds': comp.get('bounds', {}),
                })

        if not matches:
            print("    ⚠ Stage 1 OCR 未匹配到任何关键词")
            return []

        # 按得分排序
        matches.sort(key=lambda m: m['score'], reverse=True)
        print(f"    [定位] Stage 1 匹配到 {len(matches)} 个候选: "
              f"{[(m['text'], m['omni_index']) for m in matches[:5]]}")

        # 3. 查找每个匹配的 index 属于哪个 Stage 2 merged component
        merged_components = ui_json.get('components', [])
        results = []
        seen_indices = set()

        for match in matches:
            omni_idx = match['omni_index']
            if omni_idx in seen_indices:
                continue

            # 查找包含此 index 的 merged component
            for comp in merged_components:
                source_indices = comp.get('source_indices', [])
                if omni_idx in source_indices:
                    b = comp.get('bounds', {})
                    cx1 = max(0, b.get('x', 0))
                    cy1 = max(0, b.get('y', 0))
                    cx2 = min(img_w, cx1 + b.get('width', 0))
                    cy2 = min(img_h, cy1 + b.get('height', 0))

                    if cx2 > cx1 and cy2 > cy1:
                        results.append({
                            'matched_text': match['text'],
                            'omni_index': omni_idx,
                            'component': comp,
                            'crop_bbox': (cx1, cy1, cx2, cy2),
                            'score': match['score'],
                        })
                        seen_indices.add(omni_idx)
                        break

        # 去重：同一 merged component 只保留最高分匹配
        unique_results = []
        seen_comps = set()
        for r in results:
            comp_id = id(r['component'])
            if comp_id not in seen_comps:
                unique_results.append(r)
                seen_comps.add(comp_id)

        print(f"    [定位] 确定 {len(unique_results)} 个目标区域")
        return unique_results

    def _extract_keywords(self, instruction: str) -> List[str]:
        """从指令中提取关键词用于 OCR 匹配"""
        # 移除常见前缀/后缀噪音
        cleaned = instruction
        for noise in ['将', '改为', '修改', '替换', '模拟', '异常场景',
                       '的', '了', '在', '把', '被', '让', '使', '到', '和']:
            cleaned = cleaned.replace(noise, ' ')

        # 提取中文词（2字以上）+ 数字 + 英文词
        words = []
        # 中文词
        chinese_words = re.findall(r'[\u4e00-\u9fff]{2,}', cleaned)
        words.extend(chinese_words)
        # 英文/数字词
        en_words = re.findall(r'[a-zA-Z0-9]+', cleaned)
        words.extend(en_words)

        # 去重并过滤太短的
        seen = set()
        result = []
        for w in words:
            if w not in seen and len(w) >= 2:
                seen.add(w)
                result.append(w)
        return result

    def _match_score(self, ocr_text: str, keywords: List[str]) -> float:
        """计算 OCR 文字与关键词的匹配得分"""
        score = 0.0
        for kw in keywords:
            if kw in ocr_text:
                score += len(kw) / len(ocr_text) * 2  # 精确匹配高分
            else:
                # 子串部分匹配
                for i in range(len(kw) - 1):
                    sub = kw[i:i+2]
                    if sub in ocr_text:
                        score += 0.3
        return score

    def _build_plan_from_locations(
        self,
        located: List[Dict],
        instruction: str,
        screenshot_path: str,
    ) -> List[EditOp]:
        """
        从确定性定位结果构建 EditOp 编辑计划。

        对每个定位区域：
        1. 从原图裁剪区域
        2. 运行 PaddleOCR 做精确定位
        3. 解析指令语义，提取替换文字（而非整个 instruction）
        4. 构造 modify_text 类型的 EditOp

        Returns:
            EditOp 列表，如果无法构建则返回空列表
        """
        ocr_engine = self._get_paddle_ocr()
        if ocr_engine is None:
            print("    ⚠ PaddleOCR 不可用，无法精确定位")
            return []

        # 解析指令语义：提取替换目标文字和替换结果
        parsed = self._parse_instruction_semantics(instruction)

        def _resolve_content(matched_text: str) -> str:
            """根据语义解析结果确定 EditOp 的 content（要渲染的文字）"""
            replacement = parsed.get('replacement', '')
            if replacement:
                return replacement  # 显式替换
            if parsed.get('style_overrides', {}).get('disabled'):
                return matched_text  # 置灰：保留原文字
            return matched_text  # 回退：保留匹配文字

        import numpy as np
        ops = []
        screenshot = Image.open(screenshot_path).convert('RGB')
        img_w, img_h = screenshot.size

        for loc in located:
            x1, y1, x2, y2 = loc['crop_bbox']
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(img_w, x2), min(img_h, y2)

            if x2 <= x1 or y2 <= y1:
                continue

            crop = screenshot.crop((x1, y1, x2, y2))
            crop_np = np.array(crop)

            try:
                ocr_result = ocr_engine.ocr(crop_np, cls=False)
            except Exception as e:
                print(f"    ⚠ PaddleOCR 裁剪区运行失败: {e}")
                continue

            if not ocr_result or not ocr_result[0]:
                matched = loc['matched_text']
                # 尝试从 parsed 中获取替换文字
                replacement = parsed.get('replacement', matched)
                text_changes = parsed.get('text_changes', [{'from': matched, 'to': replacement}])

                op = EditOp(
                    action='modify_text',
                    region={'x': x1, 'y': y1, 'width': x2 - x1, 'height': y2 - y1},
                    content=_resolve_content(matched),
                    style_hint={
                        'use_ai_edit': False,
                        'original_instruction': instruction,
                        'matched_text': matched,
                        'text_changes': text_changes,
                        'source': 'deterministic_locate',
                    }
                )
                ops.append(op)
                print(f"    [定位] OCR 无结果，bounds 构造: \"{matched}\" → \"{_resolve_content(matched)}\"")
                continue

            ocr_items = []
            for item in ocr_result[0]:
                points = item[0]
                text = item[1][0]
                conf = item[1][1]
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                ocr_items.append({
                    'text': text, 'conf': conf,
                    'bbox': {
                        'x': int(min(xs)), 'y': int(min(ys)),
                        'width': max(1, int(max(xs) - min(xs))),
                        'height': max(1, int(max(ys) - min(ys))),
                    }
                })

            print(f"    [定位] OCR 裁剪区检测到 {len(ocr_items)} 个文字区域")

            matched = loc['matched_text']
            best_item = None
            best_score = 0
            for item in ocr_items:
                if matched in item['text']:
                    score = len(matched)
                    if score > best_score:
                        best_score = score
                        best_item = item
            if best_item is None:
                for item in ocr_items:
                    score = sum(1 for c in matched if c in item['text'])
                    if score > best_score:
                        best_score = score
                        best_item = item

            if best_item:
                bx, by = best_item['bbox']['x'], best_item['bbox']['y']
                bw, bh = best_item['bbox']['width'], best_item['bbox']['height']
                abs_bx, abs_by = x1 + bx, y1 + by

                # 从 parsed 获取语义替换
                replacement = parsed.get('replacement', best_item['text'])
                text_changes = parsed.get('text_changes', [{'from': best_item['text'], 'to': replacement}])

                op = EditOp(
                    action='modify_text',
                    region={'x': abs_bx, 'y': abs_by, 'width': bw, 'height': bh},
                    content=_resolve_content(best_item['text']),
                    style_hint={
                        'use_ai_edit': False,
                        'original_instruction': instruction,
                        'matched_text': best_item['text'],
                        'ocr_confidence': best_item['conf'],
                        'text_changes': text_changes,
                        'source': 'deterministic_locate_ocr',
                    }
                )
                ops.append(op)
                print(f"    [定位] 精确定位: \"{best_item['text']}\" → \"{_resolve_content(best_item['text'])}\" "
                      f"@ ({abs_bx},{abs_by}) {bw}x{bh}, conf={best_item['conf']:.2f}")
            else:
                replacement = parsed.get('replacement', matched)
                text_changes = parsed.get('text_changes', [{'from': matched, 'to': replacement}])
                op = EditOp(
                    action='modify_text',
                    region={'x': x1, 'y': y1, 'width': x2 - x1, 'height': y2 - y1},
                    content=_resolve_content(matched),
                    style_hint={
                        'use_ai_edit': False,
                        'original_instruction': instruction,
                        'matched_text': matched,
                        'text_changes': text_changes,
                        'source': 'deterministic_locate_fallback',
                    }
                )
                ops.append(op)

        return ops

    def _parse_instruction_semantics(self, instruction: str) -> Dict:
        """
        解析指令语义，提取替换目标文字和替换结果。

        支持的指令模式：
        - "将X改为Y" / "把X改成Y" / "将X修改为Y"
        - "将X置灰" / "X按钮置灰" → 灰色 + disabled 样式
        - "将X改为灰色" / "将X改为灰色无票" → 灰色样式
        - "将X删除" / "去掉X" → 空字符串
        - "改为降序" / "改成降序" → 检测方向类替换

        Returns:
            {
                "replacement": str,       # 替换后的文字
                "text_changes": [         # 具体文字替换列表
                    {"from": "原文字", "to": "替换后文字"}
                ],
                "style_overrides": {      # 额外样式覆盖
                    "font_color": str,    # 如 "#999999" 灰
                    "disabled": bool,     # 是否禁用样式
                }
            }
        """
        text = instruction.strip()

        result = {
            'replacement': '',
            'text_changes': [],
            'style_overrides': {},
        }

        # 模式 1: "将X改为Y" / "把X改成Y" / "将X修改为Y" / "修改X为Y"
        patterns = [
            (r'将.+?改[为成]\s*(.+?)(?:[，。,\.\s]|$)', 1),
            (r'把.+?改[成为]\s*(.+?)(?:[，。,\.\s]|$)', 1),
            (r'修改.+?[为成]\s*(.+?)(?:[，。,\.\s]|$)', 1),
            (r'改[为成]\s*(.+?)(?:[，。,\.\s]|$)', 1),
            (r'替换[为成]\s*(.+?)(?:[，。,\.\s]|$)', 1),
        ]

        for pattern, group_idx in patterns:
            m = re.search(pattern, text)
            if m:
                result['replacement'] = m.group(group_idx).strip().rstrip('.。,，')
                break

        # 模式 2: "将X置灰" / "X按钮置灰" / "改为灰色" / "置灰"
        gray_patterns = [
            r'(置灰|灰色|变灰|disable|不可用|禁用)',
        ]
        is_gray = any(re.search(p, text) for p in gray_patterns)
        if is_gray:
            result['style_overrides']['font_color'] = '#999999'
            result['style_overrides']['disabled'] = True
            # 置灰操作不改变文字内容，replacement 留空由调用方用 matched_text 填充

        # 模式 3: "X按钮背景置灰" / "将X背景改为灰色"
        bg_gray = re.search(r'(背景|按钮).*?(置灰|灰色)', text)
        if bg_gray and not result['replacement']:
            result['style_overrides']['background_color'] = '#CCCCCC'
            result['style_overrides']['disabled'] = True

        # 模式 4: "改为降序" / "改成升序" / "价格选最低"
        sort_patterns = {
            '降序': '价格降序',
            '升序': '价格升序',
            '最低': '价格最低',
            '最高': '价格最高',
        }
        for keyword, replacement in sort_patterns.items():
            if keyword in text and not result.get('replacement'):
                result['replacement'] = replacement
                break

        # 回退：使用整个 instruction 作为 replacement
        if not result.get('replacement'):
            result['replacement'] = text

        return result

    @staticmethod
    def _is_seat_specific_instruction(instruction: str) -> bool:
        text = instruction or ''
        return any(kw in text for kw in ['硬卧', '软卧', '硬座', '无座', '二等', '一等', '商务座', '高级软卧'])

    @staticmethod
    def _is_status_like_change(from_text: str, to_text: str) -> bool:
        f = (from_text or '').strip()
        t = (to_text or '').strip()
        if f in ('有票', '无票', '售磬', '售罄') or t in ('有票', '无票', '售磬', '售罄'):
            return True
        if re.fullmatch(r'\d+\s*张', f) or re.fullmatch(r'\d+\s*张', t):
            return True
        if re.fullmatch(r'\d+', f) or re.fullmatch(r'\d+', t):
            return True
        return False

    def _refine_ops_with_ocr(
        self,
        card_ops: List[EditOp],
        screenshot_path: str,
        include_button_changes: bool = False
    ) -> List[EditOp]:
        """
        用 PaddleOCR 将卡片级 EditOps 拆解为文字级 EditOps。

        对每个标记 use_ai_edit=True 的 card-level op：
        1. 裁切卡片区域
        2. 运行 PaddleOCR (中文) 获取所有文字的精确 bbox
        3. 将 text_changes['from'] 与 OCR 结果逐一匹配
        4. 匹配的 → 生成文字级 EditOp (PIL 模式, use_ai_edit=False)
        5. 未匹配的 → 保留原 card-level op (AI 模式, use_ai_edit=True)

        Returns:
            精化后的 EditOp 列表（可能混合 PIL 和 AI ops）
        """
        ocr_engine = self._get_paddle_ocr()
        if ocr_engine is None:
            print("    ⚠ PaddleOCR 不可用，跳过 OCR 精定位，全部走 AI 模式")
            return card_ops

        import numpy as np

        screenshot = Image.open(screenshot_path).convert('RGB')
        refined_ops: List[EditOp] = []

        for op in card_ops:
            # 非 AI 编辑的操作直接透传
            if not op.style_hint.get('use_ai_edit'):
                refined_ops.append(op)
                continue

            text_changes = op.style_hint.get('text_changes', [])
            button_changes = op.style_hint.get('button_changes', []) if include_button_changes else []
            if not text_changes:
                refined_ops.append(op)
                continue

            # 裁切卡片区域（精确 bounds，不加 padding）
            r = op.region
            card_x, card_y = r['x'], r['y']
            card_w, card_h = r['width'], r['height']
            img_w, img_h = screenshot.size

            # 边界裁剪
            cx1 = max(0, card_x)
            cy1 = max(0, card_y)
            cx2 = min(img_w, card_x + card_w)
            cy2 = min(img_h, card_y + card_h)

            if cx2 <= cx1 or cy2 <= cy1:
                refined_ops.append(op)
                continue

            crop = screenshot.crop((cx1, cy1, cx2, cy2))
            crop_np = np.array(crop)

            # 运行 PaddleOCR
            try:
                ocr_result = ocr_engine.ocr(crop_np, cls=False)
            except Exception as e:
                print(f"    ⚠ PaddleOCR 运行失败: {e}，保留 AI 模式")
                refined_ops.append(op)
                continue

            if not ocr_result or not ocr_result[0]:
                print(f"    ⚠ OCR 未检测到文字，保留 AI 模式")
                refined_ops.append(op)
                continue

            # 解析 OCR 结果为结构化列表
            ocr_items = []
            for item in ocr_result[0]:
                points = item[0]  # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                text = item[1][0]
                conf = item[1][1]
                # 四边形 → 轴对齐矩形 (x, y, w, h)
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                bx = int(min(xs))
                by = int(min(ys))
                bw = int(max(xs) - min(xs))
                bh = int(max(ys) - min(ys))
                ocr_items.append({
                    'text': text, 'conf': conf,
                    'bbox': {'x': bx, 'y': by, 'width': max(1, bw), 'height': max(1, bh)}
                })

            print(f"    [OCR] 检测到 {len(ocr_items)} 个文字区域")
            debug_dir = self._save_debug_component_artifacts(
                screenshot=screenshot,
                card_box_abs=(cx1, cy1, cx2, cy2),
                crop_image=crop,
                ocr_items=ocr_items,
                op=op,
            )
            avg_text_h = max(1.0, sum(item['bbox']['height'] for item in ocr_items) / max(1, len(ocr_items)))
            row_tolerance = max(22.0, avg_text_h * 1.25)

            # 匹配 text_changes 与 OCR 结果
            matched_ops: List[EditOp] = []
            button_ops: List[EditOp] = []
            unmatched_changes: List[dict] = []
            used_ocr_indices: set = set()
            original_instruction = str(op.style_hint.get('original_instruction', ''))
            prefer_right = ('右侧' in original_instruction) or ('第三列' in original_instruction)
            row_anchor_y = self._find_row_anchor_y(ocr_items, original_instruction)
            seat_specific = self._is_seat_specific_instruction(original_instruction)
            status_target_y: Optional[float] = row_anchor_y

            for tc in text_changes:
                from_text = tc['from'].strip()
                found = False

                exact_candidates = []
                for idx, ocr_item in enumerate(ocr_items):
                    if idx in used_ocr_indices:
                        continue
                    if not self._text_match(from_text, ocr_item['text']):
                        continue
                    bb = ocr_item['bbox']
                    cx = bb.get('x', 0) + bb.get('width', 0) / 2
                    cy = bb.get('y', 0) + bb.get('height', 0) / 2
                    anchor_y = status_target_y if status_target_y is not None else row_anchor_y
                    row_penalty = abs(cy - anchor_y) if anchor_y is not None else 0.0
                    if anchor_y is not None and row_penalty > row_tolerance and self._looks_like_ticket_status(from_text):
                        # 指令中已有席位行锚点时，票量状态词必须落在同一行附近，避免误改软卧/硬卧另一行
                        continue
                    if anchor_y is None and seat_specific and self._looks_like_ticket_status(from_text):
                        # 席位明确但锚点缺失时，不允许全局匹配票量状态，避免误改到其它行
                        continue
                    right_bonus = (-cx * 0.02) if prefer_right else 0.0
                    exact_candidates.append((row_penalty + right_bonus, idx, ocr_item))

                if exact_candidates:
                    exact_candidates.sort(key=lambda x: x[0])
                    _, idx, ocr_item = exact_candidates[0]
                    used_ocr_indices.add(idx)
                    bbox = ocr_item['bbox']
                    # 转为绝对坐标（加上卡片偏移量）
                    abs_bbox = {
                        'x': cx1 + bbox['x'],
                        'y': cy1 + bbox['y'],
                        'width': bbox['width'],
                        'height': bbox['height'],
                    }
                    # 从 OCR bbox 高度估算字号
                    est_font_size = max(12, int(bbox['height'] * 0.75))
                    color_req = str(op.style_hint.get('color_requirement', '')).lower()
                    force_gray = bool(op.style_hint.get('need_disable_button')) or ('灰' in color_req or 'gray' in color_req or 'grey' in color_req)

                    text_op = EditOp(
                        action='modify_text',
                        region=abs_bbox,
                        content=tc['to'],
                        target_component=op.target_component,
                        style_hint={
                            'use_ai_edit': False,
                            'font_size': est_font_size,
                            'color_type': 'sampled',
                            **({'font_color': '#9A9A9A'} if force_gray else {}),
                        },
                        reference_component=op.reference_component,
                    )
                    matched_ops.append(text_op)
                    # status_target_y 统一使用“裁剪局部坐标系”，用于后续按钮同一行匹配
                    status_target_y = bbox['y'] + bbox['height'] / 2
                    found = True
                    print(f"      ✓ OCR匹配: \"{from_text}\"→\"{tc['to']}\" "
                          f"@ ({abs_bbox['x']},{abs_bbox['y']}) "
                          f"{abs_bbox['width']}x{abs_bbox['height']} "
                          f"conf={ocr_item['conf']:.2f}")
                    if debug_dir is not None:
                        try:
                            screenshot.crop((
                                abs_bbox['x'],
                                abs_bbox['y'],
                                abs_bbox['x'] + abs_bbox['width'],
                                abs_bbox['y'] + abs_bbox['height'],
                            )).save(debug_dir / f"text_match_{idx:02d}.png")
                        except Exception:
                            pass

                if not found:
                    # 兜底：目标是“无票/有票/售罄”等状态词时，允许从票量状态样式中推断目标区域
                    to_text = str(tc.get('to', '')).strip()
                    if self._is_status_like_change(from_text, to_text) and seat_specific and status_target_y is None:
                        unmatched_changes.append(tc)
                        print(f"      ⓘ 跳过状态修改（席位锚点缺失，避免误改行）: \"{from_text}\"→\"{to_text}\"")
                        continue
                    if to_text in ('无票', '有票', '售磬', '售罄'):
                        candidates = []
                        for idx, ocr_item in enumerate(ocr_items):
                            if idx in used_ocr_indices:
                                continue
                            if not self._looks_like_ticket_status(ocr_item.get('text', '')):
                                continue
                            bb = ocr_item.get('bbox', {})
                            cx = bb.get('x', 0) + bb.get('width', 0) / 2
                            cy = bb.get('y', 0) + bb.get('height', 0) / 2
                            # 打分：优先同一行；当指令明确“右侧/第三列”时偏好更右
                            anchor_y = status_target_y if status_target_y is not None else row_anchor_y
                            row_penalty = abs(cy - anchor_y) if anchor_y is not None else 0
                            if anchor_y is not None and row_penalty > row_tolerance:
                                continue
                            right_bonus = (-cx * 0.02) if prefer_right else 0
                            score = row_penalty + right_bonus
                            candidates.append((score, idx, ocr_item))

                        if candidates:
                            candidates.sort(key=lambda x: x[0])
                            _, idx, ocr_item = candidates[0]
                            used_ocr_indices.add(idx)
                            bbox = ocr_item['bbox']
                            abs_bbox = {
                                'x': cx1 + bbox['x'],
                                'y': cy1 + bbox['y'],
                                'width': bbox['width'],
                                'height': bbox['height'],
                            }
                            est_font_size = max(12, int(bbox['height'] * 0.75))
                            color_req = str(op.style_hint.get('color_requirement', '')).lower()
                            force_gray = bool(op.style_hint.get('need_disable_button')) or ('灰' in color_req or 'gray' in color_req or 'grey' in color_req)
                            text_op = EditOp(
                                action='modify_text',
                                region=abs_bbox,
                                content=to_text,
                                target_component=op.target_component,
                                style_hint={
                                    'use_ai_edit': False,
                                    'font_size': est_font_size,
                                    'color_type': 'sampled',
                                    **({'font_color': '#9A9A9A'} if force_gray else {}),
                                },
                                reference_component=op.reference_component,
                            )
                            matched_ops.append(text_op)
                            # status_target_y 统一使用“裁剪局部坐标系”，用于后续按钮同一行匹配
                            status_target_y = bbox['y'] + bbox['height'] / 2
                            found = True
                            print(f"      ✓ OCR兜底匹配: \"{from_text}\"→\"{to_text}\" "
                                  f"(from OCR \"{ocr_item.get('text', '')}\") "
                                  f"@ ({abs_bbox['x']},{abs_bbox['y']}) "
                                  f"{abs_bbox['width']}x{abs_bbox['height']}")
                            if debug_dir is not None:
                                try:
                                    screenshot.crop((
                                        abs_bbox['x'],
                                        abs_bbox['y'],
                                        abs_bbox['x'] + abs_bbox['width'],
                                        abs_bbox['y'] + abs_bbox['height'],
                                    )).save(debug_dir / f"text_fallback_{idx:02d}.png")
                                except Exception:
                                    pass

                    if not found:
                        unmatched_changes.append(tc)

            # 可选：按钮灰化联动（只在 include_button_changes=True 时启用）
            if button_changes:
                matched_btn = 0
                for bc in button_changes:
                    from_btn = str(bc.get('from', '')).strip()
                    to_btn = str(bc.get('to', from_btn)).strip() or from_btn
                    if not from_btn:
                        continue
                    found_btn = False
                    btn_candidates = []
                    for idx, ocr_item in enumerate(ocr_items):
                        if idx in used_ocr_indices:
                            continue
                        if not self._text_match(from_btn, ocr_item['text']):
                            continue
                        bb = ocr_item['bbox']
                        cx = bb.get('x', 0) + bb.get('width', 0) / 2
                        cy = bb.get('y', 0) + bb.get('height', 0) / 2
                        target_y = status_target_y if status_target_y is not None else row_anchor_y
                        if seat_specific and target_y is None:
                            continue
                        row_penalty = abs(cy - target_y) if target_y is not None else 0.0
                        if target_y is not None and row_penalty > row_tolerance:
                            continue
                        right_bonus = (-cx * 0.03) if prefer_right else 0.0
                        btn_candidates.append((row_penalty + right_bonus, idx, ocr_item))

                    for _, idx, ocr_item in sorted(btn_candidates, key=lambda x: x[0]):
                        used_ocr_indices.add(idx)
                        bbox = ocr_item['bbox']

                        # 基于按钮文字框外扩估算按钮整体范围
                        # 旧策略在中文短词（如“预订”）上容易偏窄，导致灰化未完整覆盖按钮底色。
                        raw_x = cx1 + bbox['x']
                        raw_y = cy1 + bbox['y']
                        raw_w = bbox['width']
                        raw_h = bbox['height']

                        card_w = max(1, cx2 - cx1)
                        btn_text = to_btn or from_btn
                        char_cnt = max(1, len(btn_text))

                        # 宽高估算：提升最小宽度 + 增大文字外扩倍数，确保覆盖按钮底色。
                        min_btn_w = max(72, int(char_cnt * 26))
                        max_btn_w = max(110, int(card_w * 0.36))
                        btn_w = max(min_btn_w, raw_w + 30, int(raw_w * 3.2))
                        btn_w = min(btn_w, max_btn_w)

                        btn_h = max(34, raw_h + 14, int(raw_h * 2.2))

                        # 优先水平居中覆盖文字；若文字明显在卡片右侧，改为右锚点贴齐右边距。
                        bx = raw_x - (btn_w - raw_w) // 2
                        right_area = raw_x >= cx1 + int(card_w * 0.56)
                        if right_area:
                            right_margin = max(8, int(card_w * 0.02))
                            bx = cx2 - right_margin - btn_w

                        by = raw_y - (btn_h - raw_h) // 2
                        bx = max(cx1, bx)
                        by = max(cy1, by)
                        btn_w = min(btn_w, cx2 - bx)
                        btn_h = min(btn_h, cy2 - by)
                        if btn_w <= 0 or btn_h <= 0:
                            break

                        btn_op = EditOp(
                            action='modify_text',
                            region={'x': bx, 'y': by, 'width': btn_w, 'height': btn_h},
                            content=to_btn,
                            target_component=op.target_component,
                            style_hint={
                                'use_ai_edit': False,
                                'button_disable_gray': True,
                                'font_size': max(12, int(raw_h * 0.85)),
                                'font_color': '#F2F2F2',
                            },
                            reference_component=op.reference_component,
                        )
                        button_ops.append(btn_op)
                        matched_btn += 1
                        found_btn = True
                        print(f"      ✓ 按钮灰化匹配: \"{from_btn}\" @ ({bx},{by}) {btn_w}x{btn_h}")
                        if debug_dir is not None:
                            try:
                                screenshot.crop((bx, by, bx + btn_w, by + btn_h)).save(
                                    debug_dir / f"button_match_{idx:02d}.png"
                                )
                            except Exception:
                                pass
                        break
                    if not found_btn:
                        print(f"      ⓘ 按钮未匹配，跳过: \"{from_btn}\"")
                if matched_btn:
                    print(f"    ✓ 按钮联动灰化: {matched_btn}/{len(button_changes)}")

            # 汇总本组件 OCR 精化结果：允许“仅按钮成功”或“仅文本成功”
            total_ok = len(matched_ops) + len(button_ops)
            if total_ok == 0:
                print(f"    ✗ OCR 未匹配到可执行操作，跳过组件{op.target_component}: "
                      f"text={ [tc.get('from') for tc in text_changes] }, "
                      f"button={ [bc.get('from') for bc in button_changes] }")
                continue

            if matched_ops:
                print(f"    ✓ OCR 文字精定位: {len(matched_ops)}/{len(text_changes)}")
            if unmatched_changes:
                print(f"    ⓘ {len(unmatched_changes)} 个文字未匹配: "
                      f"{[tc['from'] for tc in unmatched_changes]}")

            refined_ops.extend(matched_ops)
            refined_ops.extend(button_ops)

        return refined_ops

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
            r'在(.+?)(?:卡片|部分|区域|模块|服务|弹窗|弹层)中',
            r'在(.+?)(?:中|里)插入',
            r'(?:对|给)(.+?)(?:插入|添加|增加)',
            r'(.+?)(?:卡片|部分|区域|模块|弹窗|弹层)',
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


        return (255, 77, 79)  # 默认红色

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
            # 没有可参考的文字组件：从 region 高度推算字号（比固定28更准确）
            font_path = self._find_font()
            region_h = edit_op.region.get('height', 40)
            inferred_size = self._match_font_size(int(region_h * 0.65), font_path)
            inferred_size = min(inferred_size, 42)
            style = TextStyle(font_size=inferred_size, font_path=font_path)

        # 应用 style_hint 调整（优先级：font_size > font_scale > 采样值）
        hint = edit_op.style_hint
        if hint.get('font_size'):
            # 直接指定字号，优先级最高
            style.font_size = max(8, int(hint['font_size']))
        elif hint.get('font_scale'):
            style.font_size = max(12, int(style.font_size * hint['font_scale']))

        # color_type == 'accent' 不再强制橙色，保留采样色（由 _exec_modify_text 处理颜色）

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
        原地替换已有文字 — 统一入口

        如果 edit_op.style_hint 中标记了 use_ai_edit=True，
        优先走 AI 图像编辑模型（裁切区域 → 调用 qwen-image-edit-max → 覆盖回原位），
        失败时回退到旧的 PIL 擦除+重绘方式。
        """
        # 尝试 AI 图像编辑路径
        if edit_op.style_hint.get('use_ai_edit'):
            ai_result = self._exec_modify_text_ai(image, edit_op, ui_json)
            if ai_result is not None:
                return ai_result
            print("    ⚠ AI 图像编辑失败，回退到 PIL 擦除模式")

        # ---- 旧 PIL 擦除+重绘逻辑（作为 fallback） ----
        return self._exec_modify_text_pil(image, edit_op, ui_json)

    def _exec_modify_text_pil(
        self,
        image: Image.Image,
        edit_op: EditOp,
        ui_json: dict
    ) -> Image.Image:
        """
        PIL 模式原地替换文字（旧逻辑）

        原理：采样背景色 → 背景色填充原区域（擦除旧文字） → 同位置绘制新文字

        颜色优先级：
          1. style_hint.font_color (hex/tuple) — edit_plan 精确指定
          2. style_hint.color_type == 'sampled' 或缺省 — 从原区域采样文字色
          3. style_hint.color_type == 'accent' — 保留原采样文字色（不强制橙色）
        """
        if edit_op.style_hint.get('button_disable_gray'):
            return self._exec_disable_button_pil(image, edit_op)

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

        # 颜色决策：style_hint.font_color 精确指定时优先使用
        hint = edit_op.style_hint
        if hint.get('font_color'):
            text_color = self._parse_color(hint['font_color'])
        # color_type == 'accent' 不再强制橙色，保持采样色（与原文字风格一致）

        # Step 1: 用背景色填充（擦除原文字）
        erased = Image.new('RGBA', (w, h), (*bg_color, 255))

        # Step 2: 绘制新文字，自动缩小字号防止溢出
        draw = ImageDraw.Draw(erased)
        padding_x = max(4, int(w * 0.02))
        available_w = w - padding_x * 2
        available_h = h

        font_size = style.font_size
        is_bold = style.font_weight == 'bold'
        font_path = style.font_path

        # 自适应字号：缩小直到文字宽高均在 region 内
        for _ in range(20):  # 最多收缩 20 次
            font = self._get_font(font_size, is_bold, font_path)
            bbox = draw.textbbox((0, 0), edit_op.content, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            if text_w <= available_w and text_h <= available_h:
                break
            font_size = max(8, font_size - 2)

        # 垂直居中、水平居中（modify_text 通常是单字段，居中比靠左更自然）
        text_x = max(padding_x, (w - text_w) // 2)
        text_y = max(0, (h - text_h) // 2)

        draw.text(
            (text_x, text_y),
            edit_op.content,
            font=font,
            fill=(*text_color, 255)
        )

        result = image.copy()
        result.paste(erased, (x, y), erased)
        return result

    def _exec_disable_button_pil(self, image: Image.Image, edit_op: EditOp) -> Image.Image:
        """
        将按钮渲染为灰色禁用态。

        纯去饱和方案：对区域整体去色即可。
        白色/浅灰像素去饱和后不变（等效透明），有色按钮像素变为对应灰度，
        自然保留圆角、抗锯齿、渐变等细节，无需蒙版。
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

        result = image.copy()
        region = result.crop((x, y, x + w, y + h)).convert('RGB')
        gray_region = ImageEnhance.Color(region).enhance(0.0)
        result.paste(gray_region, (x, y))
        return result

    def _exec_modify_text_ai(
        self,
        image: Image.Image,
        edit_op: EditOp,
        ui_json: dict
    ) -> Optional[Image.Image]:
        """
        AI 图像编辑模式原地替换文字

        流程：
        1. 根据 edit_op.region（组件级 bounding box）从原图裁切目标区域
        2. 适当外扩 padding，让模型有上下文感知
        3. 将裁切图保存为临时文件，发送给 qwen-image-edit-max
        4. 模型返回编辑后的图片，resize 到原区域大小
        5. 覆盖回原图对应位置

        Returns:
            编辑后的完整图像，失败返回 None
        """
        import tempfile

        r = edit_op.region
        x, y, w, h = r['x'], r['y'], r['width'], r['height']
        img_w, img_h = image.size

        # 外扩 padding（让模型看到周围上下文，但不要过大）
        pad = max(10, min(40, int(min(w, h) * 0.05)))
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(img_w, x + w + pad)
        y2 = min(img_h, y + h + pad)

        crop_w = x2 - x1
        crop_h = y2 - y1

        if crop_w <= 0 or crop_h <= 0:
            return None

        # 裁切目标区域
        crop = image.crop((x1, y1, x2, y2)).convert('RGB')

        print(f"    [AI编辑] 裁切区域: ({x1},{y1}) {crop_w}x{crop_h}")

        # 保存临时文件
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False, dir=None) as tmp:
                temp_path = tmp.name
            crop.save(temp_path, 'PNG')

            # 构建编辑 prompt
            text_changes = edit_op.style_hint.get('text_changes', [])
            button_changes = edit_op.style_hint.get('button_changes', [])
            edit_desc = edit_op.style_hint.get('edit_description', edit_op.content)

            # 颜色要求：优先读取规划阶段直接从原始指令中提取的颜色词
            color_requirement = edit_op.style_hint.get('color_requirement')
            original_instruction = edit_op.style_hint.get('original_instruction', '')
            # 回退：在 edit_desc / original_instruction 中扫描颜色词
            if not color_requirement:
                _color_kws = ['灰色', '红色', '绿色', '蓝色', '黑色', '白色', '橙色', '黄色',
                              'gray', 'grey', 'red', 'green', 'blue', 'black', 'white']
                _check = original_instruction or edit_desc
                color_requirement = next((kw for kw in _color_kws if kw in _check), None)

            has_color_override = bool(color_requirement)
            need_disable_button = bool(edit_op.style_hint.get('need_disable_button'))

            prompt_lines = [
                "请对这张App截图区域进行精确的文字修改。",
                f"修改目标：{edit_desc}",
                "",
                "具体修改内容：",
            ]
            for tc in text_changes:
                fr = tc.get('from', '')
                to = tc.get('to', '')
                prompt_lines.append(f'- 找到文字"{fr}"，将其替换为"{to}"')
            if button_changes:
                prompt_lines.append("- 按钮联动修改：")
                for bc in button_changes:
                    b_from = bc.get('from', '')
                    b_to = bc.get('to', b_from)
                    b_state = bc.get('state', 'disabled_gray')
                    prompt_lines.append(f'  - 按钮"{b_from}"改为"{b_to}"，状态设为"{b_state}"（灰色禁用态）')

            prompt_lines.extend([
                "",
                "严格要求：",
                "- 仅修改上述指定的文字内容，其他所有元素（背景、布局、图标、边框）保持完全不变",
            ])
            if need_disable_button:
                prompt_lines.append(
                    "- 与“无票/售罄”对应的操作按钮必须同步改成灰色禁用态（灰色按钮底 + 灰色或白灰按钮字），视觉上明确不可点击"
                )
                prompt_lines.append(
                    "- 若同一行原本为蓝色“预订”或橙色“候补”按钮，需改为统一灰色禁用风格，不要保留高亮色"
                )

            if has_color_override:
                prompt_lines.append(
                    f"- 新文字必须使用【{color_requirement}】字体颜色，"
                    f"绝对不能沿用原文字的颜色（原文字可能是绿色/橙色等，必须改为{color_requirement}）"
                )
                prompt_lines.append(
                    "- 新文字的字体、字号、对齐方式与原文字保持一致（仅颜色按上述要求修改）"
                )
            else:
                prompt_lines.append(
                    "- 新文字的字体、字号、颜色、对齐方式必须与被替换的原文字风格完全一致"
                )

            prompt_lines.extend([
                "- 不要添加任何新元素或改变图片的整体外观",
                "- 输出图片尺寸、比例与输入图片完全一致",
            ])
            edit_prompt = '\n'.join(prompt_lines)

            print(f"    [AI编辑] 发送 {len(text_changes)} 处文字修改请求...")

            # 调用图像生成后端（优先本地服务 LOCAL_IMAGE_API_URL）
            from app.utils.semantic_dialog_generator import generate_image
            result_img = generate_image(
                prompt=edit_prompt,
                size=f"{crop_w}*{crop_h}",
                reference_image_path=temp_path,
                force_model='edit',
                prompt_extend=False,
            )

            if result_img is None:
                print("    ✗ AI 图像编辑返回空结果")
                return None

            # resize 回精确的裁切尺寸
            result_img = result_img.convert('RGBA')
            if result_img.size != (crop_w, crop_h):
                print(f"    ℹ 后处理尺寸: {result_img.size} → ({crop_w},{crop_h})")
                result_img = result_img.resize((crop_w, crop_h), Image.Resampling.LANCZOS)

            # 边缘融合：裁切区域的最外围 padding 像素做渐变混合，避免硬边
            original_crop = image.crop((x1, y1, x2, y2)).convert('RGBA')
            result_img = self._feather_edges(result_img, original_crop, feather_px=max(2, pad // 3))

            # 覆盖回原图
            output = image.copy()
            output.paste(result_img, (x1, y1), result_img)

            print(f"    ✓ AI 编辑完成，已覆盖回原位")
            return output

        except Exception as exc:
            print(f"    ✗ AI 图像编辑异常: {exc}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            # 清理临时文件
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def _exec_modify_text_ai_e2e(
        self,
        image: Image.Image,
        screenshot_path: str,
        instruction: str,
        full_image: bool = False,
    ) -> Optional[Image.Image]:
        """
        端到端 AI 编辑：可选整图编辑或指令驱动粗裁剪编辑，不依赖检测框与分组。
        """
        def _resolve_instruction_crop_box(img_w: int, img_h: int, text: str) -> Tuple[int, int, int, int, str]:
            t = (text or "").lower()
            x1_r, x2_r = 0.03, 0.97
            y1_r, y2_r = 0.32, 0.82
            reason = "default_main_content"

            if any(k in t for k in ["顶部", "状态栏", "导航", "标题"]):
                y1_r, y2_r = 0.00, 0.30
                reason = "top_area"
            elif any(k in t for k in ["底部", "tab", "候补", "筛选"]):
                y1_r, y2_r = 0.72, 1.00
                reason = "bottom_area"
            elif any(k in t for k in ["卡片", "车次", "席位", "无票", "有票", "硬卧", "软卧", "一等", "二等"]):
                y1_r, y2_r = 0.40, 0.84
                reason = "train_cards_area"

            if any(k in t for k in ["第三列", "右侧", "右边"]):
                x1_r, x2_r = 0.52, 0.98
                reason += "_right_col"
            elif any(k in t for k in ["第一列", "左侧", "左边"]):
                x1_r, x2_r = 0.02, 0.48
                reason += "_left_col"
            elif any(k in t for k in ["第二列", "中间"]):
                x1_r, x2_r = 0.24, 0.76
                reason += "_middle_col"

            x1 = max(0, min(img_w - 2, int(img_w * x1_r)))
            y1 = max(0, min(img_h - 2, int(img_h * y1_r)))
            x2 = max(x1 + 2, min(img_w, int(img_w * x2_r)))
            y2 = max(y1 + 2, min(img_h, int(img_h * y2_r)))
            return x1, y1, x2, y2, reason

        img_w, img_h = image.size
        # 按用户原始指令直传，避免复杂模板提示导致过度改写
        edit_prompt = instruction.strip()
        if not edit_prompt:
            print("  ✗ 端到端 AI 编辑指令为空")
            return None

        try:
            from app.utils.semantic_dialog_generator import generate_image_dashscope
            if full_image:
                print("  [E2E编辑] 启用整图端到端编辑")
                result_img = generate_image_dashscope(
                    prompt=edit_prompt,
                    size=f"{img_w}*{img_h}",
                    reference_image_path=screenshot_path,
                    force_model='edit',
                    prompt_extend=False,
                )
                if result_img is None:
                    print("  ✗ 端到端 AI 编辑返回空结果")
                    return None

                result_img = result_img.convert('RGBA')
                if result_img.size != (img_w, img_h):
                    print(f"  ℹ 后处理尺寸: {result_img.size} → ({img_w},{img_h})")
                    result_img = result_img.resize((img_w, img_h), Image.Resampling.LANCZOS)
                print("  ✓ 端到端 AI 编辑完成")
                return result_img

            # 默认：粗裁剪后编辑并贴回，降低整图重绘风险
            x1, y1, x2, y2, crop_reason = _resolve_instruction_crop_box(img_w, img_h, edit_prompt)
            crop_w, crop_h = x2 - x1, y2 - y1
            print(f"  [E2E编辑] 指令裁剪区域: ({x1},{y1}) {crop_w}x{crop_h} [{crop_reason}]")
            crop_img = image.crop((x1, y1, x2, y2)).convert('RGB')
            import tempfile
            import os
            temp_path = None
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False, dir=None) as tmp:
                temp_path = tmp.name
            crop_img.save(temp_path, 'PNG')
            result_img = generate_image_dashscope(
                prompt=edit_prompt,
                size=f"{crop_w}*{crop_h}",
                reference_image_path=temp_path,
                force_model='edit',
                prompt_extend=False,
            )
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            if result_img is None:
                print("  ✗ 端到端 AI 编辑返回空结果")
                return None

            result_img = result_img.convert('RGBA')
            if result_img.size != (crop_w, crop_h):
                print(f"  ℹ 后处理尺寸: {result_img.size} → ({crop_w},{crop_h})")
                result_img = result_img.resize((crop_w, crop_h), Image.Resampling.LANCZOS)
            original_crop = image.crop((x1, y1, x2, y2)).convert('RGBA')
            blended = self._feather_edges(result_img, original_crop, feather_px=3)
            output = image.copy()
            output.paste(blended, (x1, y1), blended)
            print("  ✓ 端到端 AI 编辑完成（区域贴回）")
            return output
        except Exception as exc:
            print(f"  ✗ 端到端 AI 编辑异常: {exc}")
            import traceback
            traceback.print_exc()
            return None

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

    def render(
        self,
        screenshot: Image.Image,
        ui_json: dict,
        instruction: str,
        output_dir: str,
        **kwargs,
    ) -> RenderResult:
        """
        BaseRenderer 统一接口。

        注意：此渲染器内部 render_all() 接受文件路径而非 PIL Image 对象，
        因此 screenshot 参数不被使用，路径必须通过 kwargs['screenshot_path'] 传递。

        kwargs:
            screenshot_path (str): 截图文件路径（必需）
            edit_plan (list):      预设编辑计划（可选）
            omni_components (list): Stage 1 原始检测结果（可选，用于确定性文字定位）
        """
        screenshot_path = kwargs.get('screenshot_path')
        if not screenshot_path:
            raise ValueError("TextOverlayRenderer.render() requires kwargs['screenshot_path']")

        edit_plan = kwargs.get('edit_plan')
        mode = kwargs.get('mode', 'default')
        e2e_full_image = kwargs.get('e2e_full_image', False)
        omni_components = kwargs.get('omni_components', None)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._debug_crop_root = Path(output_dir) / f"debug_component_crops_{ts}"
        self._debug_crop_counter = 0
        self._debug_crop_root.mkdir(parents=True, exist_ok=True)
        result_img, executed_ops = self.render_all(
            screenshot_path=screenshot_path,
            ui_json=ui_json,
            instruction=instruction,
            edit_plan=edit_plan,
            mode=mode,
            e2e_full_image=e2e_full_image,
            omni_components=omni_components,
        )

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir_path = Path(output_dir)
        output_dir_path.mkdir(parents=True, exist_ok=True)

        final_path = output_dir_path / f"final_{timestamp}.png"
        result_img.convert('RGB').save(str(final_path))

        diff_path = output_dir_path / f"diff_{timestamp}.png"
        original = Image.open(screenshot_path).convert('RGBA')
        self.save_diff_visualization(original, result_img, str(diff_path))

        plan_path = output_dir_path / f"edit_plan_{timestamp}.json"
        plan_path.write_text(
            __import__('json').dumps([op.__dict__ if hasattr(op, '__dict__') else op for op in executed_ops],
                                     ensure_ascii=False, indent=2),
            encoding='utf-8'
        )

        return RenderResult(
            image=result_img,
            output_path=str(final_path),
            metadata={
                'edit_count': len(executed_ops),
                'diff_path': str(diff_path),
                'edit_plan_path': str(plan_path),
                'debug_component_crops_dir': str(self._debug_crop_root),
            },
        )

    def render_all(
        self,
        screenshot_path: str,
        ui_json: dict,
        instruction: str,
        edit_plan: List[EditOp] = None,
        mode: str = 'default',
        e2e_full_image: bool = False,
        omni_components: List[Dict] = None,
    ) -> Tuple[Image.Image, List[EditOp]]:
        """
        完整渲染流程：规划编辑 → 逐步执行 → 返回结果

        Args:
            screenshot_path: 原始截图路径
            ui_json: Stage 2 UI-JSON
            instruction: 用户指令
            edit_plan: 预设的编辑计划（可选，为空则调用 VLM 规划）
            mode: 控制规划/执行模式（'default' or 'modify_text'）

        Returns:
            (编辑后图像, 执行的 EditOp 列表)
        """
        original = Image.open(screenshot_path).convert('RGBA')

        if mode == 'modify_text_e2e':
            edited = self._exec_modify_text_ai_e2e(
                image=original,
                screenshot_path=screenshot_path,
                instruction=instruction,
                full_image=bool(e2e_full_image),
            )
            if edited is None:
                print("  ⚠ 端到端编辑失败，返回原图")
                return original, []
            executed_ops = [{
                'action': 'modify_text_e2e',
                'instruction': instruction,
                'mode': 'modify_text_e2e',
            }]
            return edited, executed_ops

        # ===== 确定性文字定位（优先于 VLM 规划） =====
        if edit_plan is None and omni_components:
            located = self._locate_text_by_instruction(
                instruction=instruction,
                omni_components=omni_components,
                ui_json=ui_json,
                screenshot_path=screenshot_path,
            )
            if located:
                print(f"    [定位] 确定性定位成功，尝试创建编辑计划...")
                # 为每个定位区域保存 debug crop
                for loc in located:
                    try:
                        x1, y1, x2, y2 = loc['crop_bbox']
                        crop = Image.open(screenshot_path).crop((x1, y1, x2, y2))
                        self._debug_crop_counter += 1
                        crop_dir = self._debug_crop_root / f"loc_{self._debug_crop_counter:02d}_{loc['matched_text']}"
                        crop_dir.mkdir(parents=True, exist_ok=True)
                        crop.save(crop_dir / "crop.png")
                        # 保存定位信息
                        (crop_dir / "info.json").write_text(
                            json.dumps({
                                'matched_text': loc['matched_text'],
                                'omni_index': loc['omni_index'],
                                'crop_bbox': list(loc['crop_bbox']),
                                'component_class': loc['component'].get('class', ''),
                                'source_indices': loc['component'].get('source_indices', []),
                            }, ensure_ascii=False, indent=2),
                            encoding='utf-8'
                        )
                    except Exception as exc:
                        print(f"    ⚠ 保存定位 crop 失败: {exc}")

                # 尝试从定位区域构建 edit_plan
                located_plan = self._build_plan_from_locations(
                    located=located,
                    instruction=instruction,
                    screenshot_path=screenshot_path,
                )
                if located_plan:
                    edit_plan = located_plan
                    print(f"    ✓ 使用确定性定位编辑计划 ({len(edit_plan)} 个操作)")
                else:
                    print(f"    ⚠ 确定性定位未能生成有效编辑计划，回退 VLM")

        # 规划编辑操作（VLM fallback）
        if edit_plan is None:
            edit_plan = self.plan_edits(screenshot_path, ui_json, instruction, mode=mode)

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

