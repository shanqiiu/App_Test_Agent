#!/usr/bin/env python3
"""
omni_vlm_fusion.py - OmniParser + VLM 融合提取

两阶段融合方案：
1. Stage 1: OmniParser 粗检测 - 获得精确边界框（高召回）
2. Stage 2: VLM 语义过滤 - 合并/过滤不合理的检测框

解决的问题：
- OmniParser 会将海报/广告图内的文字单独检测出来
- VLM 可以理解"这是一张完整的海报"这种高级语义
"""

import sys
import json
import requests
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict
from PIL import Image

from utils.common import encode_image, get_mime_type, extract_json

# 添加 OmniParser 路径 (third_party 目录)
OMNIPARSER_PATH = Path(__file__).parent.parent / 'third_party' / 'OmniParser'
sys.path.insert(0, str(OMNIPARSER_PATH))


# VLM 语义过滤的 Prompt
SEMANTIC_FILTER_PROMPT = """你是一个 UI 结构分析专家。

## 任务流程

请按以下步骤分析截图和检测结果：

### 第一步：分析页面结构

首先，仔细观察截图，识别页面的**功能分区**。常见的分区包括：
- 状态栏（时间、信号、电池）
- 导航栏（返回按钮、标题、操作按钮）
- 广告横幅/Banner
- 功能入口区（Tab切换、快捷功能）
- 主内容区（表单、卡片、列表）
- 底部导航栏

请在 `page_analysis` 中描述你识别到的分区。

### 第二步：处理检测结果

根据你对页面结构的理解，对 OmniParser 的检测结果进行处理：

1. **合并规则**：
   - 只合并**同一个独立UI组件内部**的检测框（如一个按钮内的图标和文字）
   - 广告横幅/Banner 内的文字可以合并为一个 ImageView
   - **不要跨分区合并**！不同功能分区的组件必须保持独立

2. **保留规则**：
   - 独立的按钮、输入框、标签页等应该保留
   - 表单内的每个字段应该独立保留
   - 底部导航的每个Tab可以单独保留，或合并为一个 TabBar

3. **删除规则**：
   - 明显的重复检测（同一区域被检测多次）
   - 无意义的噪声检测

## 输出格式

**重要：只输出操作指令，不要输出坐标！**

```json
{
  "page_analysis": {
    "app_type": "App类型描述",
    "regions": [
      {"name": "状态栏", "description": "顶部状态信息"},
      {"name": "导航栏", "description": "..."},
      {"name": "Banner广告", "description": "..."},
      {"name": "主功能区", "description": "机票查询表单，包含出发地、目的地、日期选择等"},
      {"name": "快捷入口", "description": "..."},
      {"name": "底部导航", "description": "..."}
    ]
  },
  "operations": [
    {
      "action": "merge",
      "indices": [1, 2, 3],
      "target_class": "ImageView",
      "target_text": "合并后的描述",
      "reason": "这些属于同一个Banner广告内的文字"
    },
    {
      "action": "keep",
      "indices": [10, 11, 12],
      "reason": "这些是表单内独立的输入组件，应分别保留"
    },
    {
      "action": "delete",
      "indices": [5, 6],
      "reason": "重复检测"
    }
  ]
}
```

## 关键原则

1. **粒度适中**：不要过度合并！保留用户可交互的独立组件
2. **尊重功能边界**：不同功能分区的组件不能合并
3. **所有原始组件的 index 必须出现在某个操作中**
4. 组件类型: StatusBar, NavigationBar, TextView, Button, ImageView, ImageButton, Card, TabBar, TabItem, SearchBar, Dialog, Avatar, ListItem, InputField 等
"""


def validate_and_fix_text_assignments(
    final_components: List[Dict],
    omni_components: List[Dict]
) -> List[Dict]:
    """
    验证并修复 VLM 文本分配的 index 偏移问题。

    问题：VLM 有时将正确的文本分配给错误的 index，导致系统性偏移。
    检测：利用数字 token（3位以上）作为锚点，检测 VLM 文本与 OCR 文本的不匹配。
    修正：确定偏移方向后，在受影响范围内旋转文本。
    """
    import re

    n = len(final_components)
    if n < 3:
        return final_components

    omni_map = {c.get('index', i): c for i, c in enumerate(omni_components)}

    def extract_nums(text: str) -> set:
        """提取3位以上的连续数字"""
        return set(re.findall(r'\d{3,}', str(text)))

    def get_source_ocr(comp: dict) -> str:
        """获取组件对应的原始 OCR 文本"""
        indices = comp.get('source_indices', [])
        if not indices:
            idx = comp.get('original_index', -1)
            indices = [idx] if idx >= 0 else []
        return ' '.join(
            omni_map[i].get('text', '') for i in indices
            if i in omni_map and omni_map[i].get('text')
        )

    # 构建匹配数据
    vlm_texts = [c.get('text', '') for c in final_components]
    vn = [extract_nums(t) for t in vlm_texts]
    on = [extract_nums(get_source_ocr(c)) for c in final_components]

    # Step 1: 评分不同偏移量
    def score_shift(shift: int):
        matches, conflicts = 0, 0
        for i in range(n):
            j = i + shift
            if 0 <= j < n and vn[i] and on[j]:
                if vn[i] & on[j]:
                    matches += 1
                else:
                    conflicts += 1
        return matches - conflicts

    best_shift, best_score = 0, score_shift(0)
    for s in [1, -1, 2, -2]:
        score = score_shift(s)
        if score > best_score:
            best_score, best_shift = score, s

    if best_shift == 0:
        return final_components

    # Step 2: 确定受影响范围（从确认冲突位置向前扩展）
    conflicts = [i for i in range(n) if vn[i] and on[i] and not (vn[i] & on[i])]
    if not conflicts:
        return final_components

    range_start, range_end = min(conflicts), max(conflicts)

    # 向前扩展纳入偏移链前序组件（使用原始起点计算偏移，避免迭代偏差）
    origin = range_start
    for k in range(1, abs(best_shift) * 2 + 1):
        candidate = origin - k
        if candidate < 0:
            break
        if vn[candidate] and on[candidate] and (vn[candidate] & on[candidate]):
            break  # 遇到正确匹配，停止
        range_start = candidate

    # Step 3: 旋转文本
    affected = list(range(range_start, range_end + 1))
    original_vlm = [vlm_texts[i] for i in affected]
    rng_size = len(affected)

    fixes = []
    for pos, comp_idx in enumerate(affected):
        source_pos = pos - best_shift

        if 0 <= source_pos < rng_size:
            new_text = original_vlm[source_pos]
        else:
            # 边界：回退到 OmniParser 原始文本
            new_text = get_source_ocr(final_components[comp_idx])
            if not new_text.strip():
                final_components[comp_idx]['_text_unverified'] = True
                continue

        if final_components[comp_idx]['text'] != new_text:
            final_components[comp_idx]['_text_before_fix'] = final_components[comp_idx]['text']
            final_components[comp_idx]['text'] = new_text
            final_components[comp_idx]['_text_fix'] = f'shift_{best_shift}'
            fixes.append((comp_idx, final_components[comp_idx]['_text_before_fix'], new_text))

    if fixes:
        print(f"  [校验] 文本-边界框偏移修正: shift={best_shift}, 范围=[{range_start},{range_end}]")
        for idx, old, new in fixes:
            print(f"    [{idx}] \"{old[:25]}...\" → \"{new[:25]}...\"")

    return final_components


def fix_component_bounds(
    vlm_components: List[Dict],
    omni_components: List[Dict],
    img_width: int,
    img_height: int
) -> List[Dict]:
    """
    修复 VLM 返回的组件坐标，确保使用原始 OmniParser 的精确坐标
    （保留此函数用于兼容旧格式，新格式使用 apply_vlm_operations）
    """
    # 建立原始组件索引映射
    omni_by_index = {comp.get('index', i): comp for i, comp in enumerate(omni_components)}

    fixed_components = []
    for comp in vlm_components:
        fixed_comp = comp.copy()
        bounds = comp.get('bounds', {})

        # 检查坐标是否合理（是否在图片范围内）
        x = bounds.get('x', 0)
        y = bounds.get('y', 0)
        w = bounds.get('width', 0)
        h = bounds.get('height', 0)

        # 如果坐标明显错误（超出图片边界或明显缩放过），尝试修复
        coords_invalid = (
            x + w > img_width * 1.1 or  # 允许 10% 误差
            y + h > img_height * 1.1 or
            w > img_width or
            h > img_height
        )

        # 检查是否有 source_indices 可以用于重新计算边界框
        source_indices = comp.get('source_indices', [])

        if source_indices:
            # 根据原始组件重新计算最小外接矩形
            source_comps = [omni_by_index[idx] for idx in source_indices if idx in omni_by_index]
            if source_comps:
                min_x = min(c['bounds']['x'] for c in source_comps)
                min_y = min(c['bounds']['y'] for c in source_comps)
                max_x = max(c['bounds']['x'] + c['bounds']['width'] for c in source_comps)
                max_y = max(c['bounds']['y'] + c['bounds']['height'] for c in source_comps)
                fixed_comp['bounds'] = {
                    'x': min_x,
                    'y': min_y,
                    'width': max_x - min_x,
                    'height': max_y - min_y
                }
                fixed_components.append(fixed_comp)
                continue

        if coords_invalid:
            # 尝试通过文本匹配找到对应的原始组件
            comp_text = comp.get('text', '')
            matched = None

            # 优先精确匹配
            for orig in omni_components:
                if orig.get('text', '') == comp_text and comp_text:
                    matched = orig
                    break

            # 模糊匹配：文本包含关系
            if not matched and comp_text:
                for orig in omni_components:
                    orig_text = orig.get('text', '')
                    if orig_text and (orig_text in comp_text or comp_text in orig_text):
                        matched = orig
                        break

            if matched:
                fixed_comp['bounds'] = matched['bounds'].copy()
                fixed_comp['_bounds_source'] = 'matched_from_omni'
            else:
                # 无法匹配，尝试缩放坐标（假设 VLM 基于某个缩放版本）
                # 常见缩放：768 宽度
                if w > 0 and x + w <= 800:  # 可能是 768 宽度的缩放
                    scale = img_width / 768.0
                    fixed_comp['bounds'] = {
                        'x': int(x * scale),
                        'y': int(y * scale),
                        'width': int(w * scale),
                        'height': int(h * scale)
                    }
                    fixed_comp['_bounds_source'] = 'scaled_from_768'

        fixed_components.append(fixed_comp)

    return fixed_components


def apply_vlm_operations(
    operations: List[Dict],
    omni_components: List[Dict]
) -> tuple:
    """
    根据 VLM 返回的操作指令，处理原始 OmniParser 组件

    Args:
        operations: VLM 返回的操作列表 (merge/delete/keep)
        omni_components: OmniParser 原始组件列表

    Returns:
        (处理后的组件列表, 操作日志)
    """
    # 建立索引映射
    omni_by_index = {comp.get('index', i): comp for i, comp in enumerate(omni_components)}

    final_components = []
    merge_log = []

    # 记录所有被处理的索引
    processed_indices = set()

    for op in operations:
        action = op.get('action', '')
        indices = op.get('indices', [])

        if action == 'merge' and indices:
            # 合并操作：计算最小外接矩形
            source_comps = [omni_by_index[idx] for idx in indices if idx in omni_by_index]
            if not source_comps:
                continue

            min_x = min(c['bounds']['x'] for c in source_comps)
            min_y = min(c['bounds']['y'] for c in source_comps)
            max_x = max(c['bounds']['x'] + c['bounds']['width'] for c in source_comps)
            max_y = max(c['bounds']['y'] + c['bounds']['height'] for c in source_comps)

            # 合并文本
            texts = [c.get('text', '') for c in source_comps if c.get('text')]
            merged_text = op.get('target_text', ' '.join(texts))

            # 判断是否可点击（任一子组件可点击则可点击）
            clickable = any(c.get('clickable', False) for c in source_comps)

            merged_comp = {
                'index': len(final_components),
                'class': op.get('target_class', 'Card'),
                'bounds': {
                    'x': min_x,
                    'y': min_y,
                    'width': max_x - min_x,
                    'height': max_y - min_y
                },
                'text': merged_text,
                'clickable': clickable,
                'source_indices': indices,
                'note': op.get('reason', '')
            }
            final_components.append(merged_comp)

            merge_log.append({
                'action': 'merge',
                'from': indices,
                'to': merged_comp['index'],
                'reason': op.get('reason', '')
            })

            processed_indices.update(indices)

        elif action == 'delete' and indices:
            # 删除操作：记录日志，不添加到结果
            merge_log.append({
                'action': 'delete',
                'indices': indices,
                'reason': op.get('reason', '')
            })
            processed_indices.update(indices)

        elif action == 'keep' and indices:
            # 保留操作：直接复制原始组件
            for idx in indices:
                if idx in omni_by_index and idx not in processed_indices:
                    orig = omni_by_index[idx].copy()
                    orig['index'] = len(final_components)
                    orig['original_index'] = idx
                    final_components.append(orig)
                    processed_indices.add(idx)

    # 处理未被任何操作覆盖的组件（默认保留）
    for idx, comp in omni_by_index.items():
        if idx not in processed_indices:
            comp_copy = comp.copy()
            comp_copy['index'] = len(final_components)
            comp_copy['original_index'] = idx
            comp_copy['note'] = '未被 VLM 处理，默认保留'
            final_components.append(comp_copy)

    # 按位置排序（从上到下，从左到右）
    final_components.sort(key=lambda c: (c['bounds']['y'], c['bounds']['x']))

    # 重新分配 index
    for i, comp in enumerate(final_components):
        comp['index'] = i

    return final_components, merge_log


def call_vlm_for_semantic_filter(
    api_key: str,
    api_url: str,
    model: str,
    image_path: str,
    omni_components: List[Dict],
    max_retries: int = 5
) -> Dict:
    """调用 VLM 进行语义过滤（带重试机制）"""
    image_base64 = encode_image(image_path)
    mime_type = get_mime_type(image_path)

    # 获取原始图片尺寸
    with Image.open(image_path) as img:
        img_width, img_height = img.size

    # 构建用户提示，强调只输出操作指令
    user_prompt = f"""请分析这张截图，并对以下 OmniParser 检测结果进行语义过滤。

## 图片分辨率：{img_width}x{img_height} 像素

## OmniParser 检测结果（共 {len(omni_components)} 个组件）

```json
{json.dumps(omni_components, ensure_ascii=False, indent=2)}
```

## 处理要求

1. **先分析页面结构**：识别页面有哪些功能分区（导航栏、Banner、表单区、快捷入口等）
2. **再处理检测框**：
   - Banner/海报内的多个文字 → 合并为一个 ImageView
   - 同一按钮内的图标和文字 → 合并
   - 表单内的各个输入字段 → **分别保留，不要合并！**
   - 不同功能分区 → **不能跨区合并！**

3. **粒度要求**：保持用户可独立交互的组件独立，不要过度合并

**重要**：只输出 JSON，坐标由程序自动计算。
"""

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }

    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': SEMANTIC_FILTER_PROMPT},
            {
                'role': 'user',
                'content': [
                    {
                        'type': 'image_url',
                        'image_url': {'url': f'data:{mime_type};base64,{image_base64}'}
                    },
                    {'type': 'text', 'text': user_prompt}
                ]
            }
        ],
        'temperature': 0.1,
        'max_tokens': 8192
    }

    base_wait = 5  # 基础等待时间（秒）
    last_error = None

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                # 指数退避：5s, 10s, 20s, 40s, 60s（最大60秒）
                wait_time = min(base_wait * (2 ** (attempt - 1)), 60)
                print(f"  ⏳ 等待 {wait_time}s 后重试 ({attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                print("  调用 VLM 进行语义过滤...")

            response = requests.post(api_url, headers=headers, json=payload, timeout=180)

            # 处理可重试的错误：429 限流 和 5xx 服务器错误
            if response.status_code == 429:
                print(f"  ⚠ API 限流 (429)，准备重试...")
                last_error = f"API 限流 (429)"
                continue
            elif response.status_code >= 500:
                print(f"  ⚠ 服务器错误 ({response.status_code})，准备重试...")
                last_error = f"服务器错误 ({response.status_code})"
                continue

            response.raise_for_status()

            result = response.json()
            content = result['choices'][0]['message']['content']
            return extract_json(content)

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            print(f"  ⚠ 网络连接错误: {type(e).__name__}")
            last_error = f"网络错误: {type(e).__name__}"
            if attempt == max_retries - 1:
                # 最后一次额外等待后再试
                print(f"  ⚠ 已达最大重试次数，额外等待 30s 后最后尝试...")
                time.sleep(30)
                try:
                    response = requests.post(api_url, headers=headers, json=payload, timeout=180)
                    response.raise_for_status()
                    result = response.json()
                    content = result['choices'][0]['message']['content']
                    return extract_json(content)
                except Exception as final_e:
                    raise Exception(f"网络持续不稳定: {final_e}")
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  ⚠ JSON 解析失败: {e}")
            last_error = f"JSON 解析失败: {e}"
            # JSON 解析错误也重试，可能是 VLM 输出不稳定
            if attempt == max_retries - 1:
                raise
        except requests.exceptions.RequestException as e:
            print(f"  ⚠ API 请求失败: {e}")
            last_error = f"API 请求失败: {e}"
            if attempt == max_retries - 1:
                raise

    # 所有重试都失败
    raise Exception(f"VLM 语义过滤失败，已重试 {max_retries} 次。最后错误: {last_error}")


def omni_vlm_fusion(
    image_path: str,
    api_key: str,
    api_url: str = 'https://api.openai-next.com/v1/chat/completions',
    vlm_model: str = 'gpt-4o',
    omni_device: str = None,
    box_threshold: float = 0.05,
    iou_threshold: float = 0.7,
    omni_components: List[Dict] = None
) -> Dict:
    """
    OmniParser + VLM 融合提取

    Args:
        image_path: 截图路径
        api_key: VLM API 密钥
        api_url: VLM API 端点
        vlm_model: VLM 模型名称
        omni_device: OmniParser 运行设备
        box_threshold: OmniParser 检测阈值
        iou_threshold: OmniParser IOU 阈值
        omni_components: 已有的 OmniParser 检测结果（可选，传入则跳过检测）

    Returns:
        语义正确的 UI-JSON
    """
    # 获取图片信息
    with Image.open(image_path) as img:
        width, height = img.size

    print(f"  图片分辨率: {width}x{height}")

    # Stage 1: OmniParser 粗检测（或复用已有结果）
    if omni_components is None:
        print("\n[Stage 1] OmniParser 粗检测...")
        from omni_extractor import omni_to_ui_json
        omni_result = omni_to_ui_json(
            image_path=image_path,
            box_threshold=box_threshold,
            iou_threshold=iou_threshold,
            device=omni_device
        )
        omni_components = omni_result['components']
        print(f"  检测到 {len(omni_components)} 个组件")
    else:
        print(f"\n[Stage 1] 复用已有 OmniParser 检测结果 ({len(omni_components)} 个组件)")

    # Stage 2: VLM 语义过滤
    print("\n[Stage 2] VLM 语义过滤...")
    try:
        filtered_result = call_vlm_for_semantic_filter(
            api_key=api_key,
            api_url=api_url,
            model=vlm_model,
            image_path=image_path,
            omni_components=omni_components,
            max_retries=5
        )

        # 检查返回格式：新格式使用 operations，旧格式使用 components
        if 'operations' in filtered_result:
            # 新格式：VLM 只返回操作指令，由代码计算坐标
            operations = filtered_result.get('operations', [])
            final_components, merge_log = apply_vlm_operations(
                operations=operations,
                omni_components=omni_components
            )
            print(f"  ✓ 使用新格式处理（operations）")

            # 验证并修复 VLM 文本分配的偏移问题
            final_components = validate_and_fix_text_assignments(
                final_components, omni_components
            )
        else:
            # 旧格式兼容：VLM 返回完整的 components
            final_components = filtered_result.get('components', omni_components)
            merge_log = filtered_result.get('merge_log', [])

            # 修复 VLM 返回的坐标（确保使用原始精确坐标）
            final_components = fix_component_bounds(
                vlm_components=final_components,
                omni_components=omni_components,
                img_width=width,
                img_height=height
            )
            print(f"  ⚠ 使用旧格式处理（components），坐标可能需要修复")

            # 验证并修复 VLM 文本分配的偏移问题
            final_components = validate_and_fix_text_assignments(
                final_components, omni_components
            )

        print(f"  ✓ 过滤后剩余 {len(final_components)} 个组件")
        if merge_log:
            print(f"  处理日志:")
            for log in merge_log[:5]:
                print(f"    - {log.get('action')}: {log.get('reason', 'N/A')}")
            if len(merge_log) > 5:
                print(f"    ... 还有 {len(merge_log) - 5} 条")

    except Exception as e:
        print(f"  [ERROR] VLM 语义过滤最终失败: {e}")
        print(f"  回退到 OmniParser 原始结果（共 {len(omni_components)} 个组件）")
        final_components = omni_components
        merge_log = []

    # 重新分配 index
    for i, comp in enumerate(final_components):
        comp['index'] = i

    # 构建最终 UI-JSON
    ui_json = {
        "metadata": {
            "source": Path(image_path).name,
            "extractionMethod": "OmniParser+VLM_Fusion",
            "models": {
                "detection": "OmniParser (YOLO + PaddleOCR + Florence2)",
                "semantic_filter": vlm_model
            },
            "timestamp": datetime.now().isoformat(),
            "resolution": {"width": width, "height": height},
            "processing": {
                "omni_raw_count": len(omni_components),
                "final_count": len(final_components),
                "merge_log": merge_log
            }
        },
        "components": final_components,
        "componentCount": len(final_components)
    }

    return ui_json


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(
        description='OmniParser + VLM 融合提取器'
    )
    parser.add_argument('--image', '-i', required=True,
                        help='截图路径')
    parser.add_argument('--api-key', required=True,
                        help='VLM API 密钥')
    parser.add_argument('--api-url',
                        default='https://api.openai-next.com/v1/chat/completions',
                        help='VLM API 端点')
    parser.add_argument('--vlm-model',
                        default='gpt-4o',
                        help='VLM 模型名称（用于语义过滤）')
    parser.add_argument('--omni-device',
                        help='OmniParser 运行设备 (cuda/cpu)')
    parser.add_argument('--output', '-o',
                        help='输出 JSON 文件路径')
    parser.add_argument('--pretty', action='store_true',
                        help='格式化输出 JSON')

    args = parser.parse_args()

    print("=" * 60)
    print("OmniParser + VLM 融合提取")
    print("=" * 60)

    ui_json = omni_vlm_fusion(
        image_path=args.image,
        api_key=args.api_key,
        api_url=args.api_url,
        vlm_model=args.vlm_model,
        omni_device=args.omni_device
    )

    # 输出
    if args.output:
        output_path = Path(args.output)
    else:
        image_path = Path(args.image)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = image_path.parent / f"{image_path.stem}_fusion_{timestamp}.json"

    indent = 2 if args.pretty else None
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(ui_json, f, ensure_ascii=False, indent=indent)

    print(f"\n{'=' * 60}")
    print(f"✓ 融合提取完成: {output_path}")
    print(f"  提取方式: OmniParser + VLM 融合")
    print(f"  原始检测: {ui_json['metadata']['processing']['omni_raw_count']} 个")
    print(f"  过滤后: {ui_json['componentCount']} 个")
    print("=" * 60)


if __name__ == '__main__':
    main()
