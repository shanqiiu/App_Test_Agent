#!/usr/bin/env python3
"""
omni_vlm_fusion.py - OmniParser + VLM 融合提取

两阶段融合方案：
1. Stage 1: OmniParser 粗检测 - 获得精确边界框（高召回）
2. Stage 2: VLM 语义分组 - 一次调用判断哪些检测框构成同一功能组件
   → 代码计算合并坐标（确定性，精确）

核心思想：
- VLM 只负责语义分组（哪些框在一起）
- 几何计算（合并坐标、排序编号）完全由代码完成
- 一次 VLM 调用，传原图 + 坐标文本，不传标注图
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


# ===================== Prompt 定义 =====================

GROUPING_PROMPT = """你是一个 UI 结构分析专家。

## 任务

你将看到一张 App 截图和一份自动检测到的 UI 组件列表（含编号、坐标、识别文本）。
请判断**哪些检测框共同构成一个功能组件**，输出分组结果。

## 分组判断标准

问自己：这些元素是在**共同描述一件事物**，还是**各自承担不同功能**？

- **共同描述一件事物**（如一张服务卡片的标题+价格+描述+标签）→ 合并为一个 group
- **各自承担不同功能**（如导航栏的返回按钮 vs 页面标题）→ 各自独立 group
- **纯装饰/展示区域**（Banner、海报、状态栏）→ 该区域所有框合并为一个 group

## 输出格式

```json
{
  "groups": [
    {
      "name": "分组名称（简短描述）",
      "indices": [0, 1, 2],
      "class": "组件类型",
      "text": "合并后的语义描述"
    }
  ]
}
```

## 规则

1. **每个检测框 index 必须出现在且仅出现在一个 group 中**（不遗漏、不重复）
2. 单个组件也要作为独立 group（indices 长度为 1）
3. class 从以下类型中选择：StatusBar, NavigationBar, TextView, Button, ImageView, ImageButton, Card, TabBar, TabItem, SearchBar, Dialog, Avatar, ListItem, InputField
4. text 字段：对于多个框合并的 group，给出概括性描述（而非简单拼接）；单个框的 group 保留原始 text
5. **优先合并**：如果一个区域是在描述"同一件事物/服务/产品"，应合并为一个 Card
6. 只输出 JSON，不要输出其他内容
"""


def format_components_as_text(omni_components: List[Dict]) -> str:
    """将 OmniParser 组件列表格式化为文本，供 VLM 阅读"""
    lines = []
    for comp in omni_components:
        idx = comp.get('index', 0)
        b = comp.get('bounds', {})
        text = comp.get('text', '')
        text_part = f' text="{text}"' if text else ''
        lines.append(f'#{idx} [x={b.get("x", 0)}, y={b.get("y", 0)}, '
                     f'w={b.get("width", 0)}, h={b.get("height", 0)}]{text_part}')
    return '\n'.join(lines)


def _call_vlm_with_retry(
    api_key: str,
    api_url: str,
    payload: Dict,
    task_name: str = "VLM",
    max_retries: int = 3
) -> Dict:
    """
    通用 VLM 调用（带重试机制）

    Args:
        api_key: API 密钥
        api_url: API 端点
        payload: 完整的请求 payload
        task_name: 任务名称（用于日志）
        max_retries: 最大重试次数

    Returns:
        解析后的 JSON 字典
    """
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }

    base_wait = 5
    last_error = None

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                wait_time = min(base_wait * (2 ** (attempt - 1)), 60)
                print(f"  ⏳ 等待 {wait_time}s 后重试 ({attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                print(f"  调用 {task_name}...")

            response = requests.post(api_url, headers=headers, json=payload, timeout=180)

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
            if attempt == max_retries - 1:
                raise
        except requests.exceptions.RequestException as e:
            print(f"  ⚠ API 请求失败: {e}")
            last_error = f"API 请求失败: {e}"
            if attempt == max_retries - 1:
                raise

    raise Exception(f"{task_name}失败，已重试 {max_retries} 次。最后错误: {last_error}")


def call_vlm_for_grouping(
    api_key: str,
    api_url: str,
    model: str,
    image_path: str,
    omni_components: List[Dict],
    max_retries: int = 3
) -> Dict:
    """
    VLM 语义分组：看原图 + 坐标文本，输出哪些检测框构成同一功能组件

    Args:
        image_path: 原始截图路径
        omni_components: OmniParser 原始检测组件
        max_retries: 最大重试次数

    Returns:
        {"groups": [{"name": str, "indices": [int], "class": str, "text": str}, ...]}
    """
    image_base64 = encode_image(image_path)
    mime_type = get_mime_type(image_path)

    with Image.open(image_path) as img:
        img_width, img_height = img.size

    components_text = format_components_as_text(omni_components)

    user_prompt = f"""请分析这张 App 截图，结合下方的自动检测结果，判断哪些检测框共同构成一个功能组件。

## 图片分辨率：{img_width}x{img_height} 像素

## 自动检测结果（共 {len(omni_components)} 个检测框）

{components_text}

请输出分组结果 JSON。每个检测框 index 必须出现在且仅出现在一个 group 中。
"""

    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': GROUPING_PROMPT},
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
        'max_tokens': 4096
    }

    return _call_vlm_with_retry(
        api_key=api_key,
        api_url=api_url,
        payload=payload,
        task_name="VLM 语义分组",
        max_retries=max_retries
    )


def apply_grouping(
    groups: List[Dict],
    omni_components: List[Dict]
) -> tuple:
    """
    根据 VLM 返回的分组结果，计算合并坐标并生成最终组件列表

    Args:
        groups: VLM 返回的分组列表 [{"name", "indices", "class", "text"}, ...]
        omni_components: OmniParser 原始组件列表

    Returns:
        (final_components, merge_log)
    """
    omni_by_index = {comp.get('index', i): comp for i, comp in enumerate(omni_components)}
    all_indices = set(omni_by_index.keys())
    covered_indices = set()

    final_components = []
    merge_log = []

    for group in groups:
        indices = group.get('indices', [])
        if not indices:
            continue

        # 过滤无效 index
        valid_indices = [idx for idx in indices if idx in omni_by_index]
        invalid_indices = [idx for idx in indices if idx not in omni_by_index]
        if invalid_indices:
            print(f"  [WARN] 分组 '{group.get('name', '?')}' 包含无效 index: {invalid_indices}")

        # 过滤已被其他分组覆盖的 index（防止 VLM 返回重复分配）
        already_covered = [idx for idx in valid_indices if idx in covered_indices]
        if already_covered:
            print(f"  [WARN] 分组 '{group.get('name', '?')}' 包含已被其他分组使用的 index: {already_covered}")
            valid_indices = [idx for idx in valid_indices if idx not in covered_indices]

        if not valid_indices:
            continue

        source_comps = [omni_by_index[idx] for idx in valid_indices]
        covered_indices.update(valid_indices)

        if len(valid_indices) == 1:
            # 单组件：保留原始，仅更新 class（如果 VLM 给了更准确的）
            comp = source_comps[0].copy()
            comp['index'] = len(final_components)
            comp['original_index'] = valid_indices[0]
            vlm_class = group.get('class')
            if vlm_class:
                comp['class'] = vlm_class
            final_components.append(comp)
        else:
            # 多组件合并：计算最小外接矩形
            min_x = min(c['bounds']['x'] for c in source_comps)
            min_y = min(c['bounds']['y'] for c in source_comps)
            max_x = max(c['bounds']['x'] + c['bounds']['width'] for c in source_comps)
            max_y = max(c['bounds']['y'] + c['bounds']['height'] for c in source_comps)

            # text 优先用 VLM 给的语义描述
            vlm_text = group.get('text', '')
            if not vlm_text:
                # 按空间顺序拼接原始 text
                sorted_comps = sorted(source_comps, key=lambda c: (c['bounds']['y'], c['bounds']['x']))
                vlm_text = ' '.join(c.get('text', '') for c in sorted_comps if c.get('text'))

            merged_comp = {
                'index': len(final_components),
                'class': group.get('class', 'Card'),
                'bounds': {
                    'x': min_x,
                    'y': min_y,
                    'width': max_x - min_x,
                    'height': max_y - min_y
                },
                'text': vlm_text,
                'clickable': any(c.get('clickable', False) for c in source_comps),
                'source_indices': valid_indices,
                'note': f'语义分组合并: {group.get("name", "")}'
            }
            final_components.append(merged_comp)

            merge_log.append({
                'action': 'group_merge',
                'name': group.get('name', ''),
                'from': valid_indices,
                'to_class': group.get('class', 'Card'),
                'reason': f'{len(valid_indices)} 个检测框合并为 {group.get("name", "?")}'
            })

    # 补充未被覆盖的 index（自动作为独立组件）
    uncovered = all_indices - covered_indices
    if uncovered:
        print(f"  [WARN] {len(uncovered)} 个检测框未被 VLM 分组覆盖，自动保留: {sorted(uncovered)}")
        for idx in sorted(uncovered):
            comp = omni_by_index[idx].copy()
            comp['index'] = len(final_components)
            comp['original_index'] = idx
            comp['note'] = '未被 VLM 分组覆盖，自动保留'
            final_components.append(comp)

    # 按位置排序（从上到下，从左到右）并重新编号
    final_components.sort(key=lambda c: (c['bounds']['y'], c['bounds']['x']))
    for i, comp in enumerate(final_components):
        comp['index'] = i

    return final_components, merge_log


def omni_vlm_fusion(
    image_path: str,
    api_key: str,
    api_url: str = 'https://api.openai-next.com/v1/chat/completions',
    vlm_model: str = 'gpt-4o',
    omni_device: str = None,
    box_threshold: float = 0.05,
    iou_threshold: float = 0.7,
    omni_components: List[Dict] = None,
    output_dir: str = None
) -> Dict:
    """
    OmniParser + VLM 融合提取（单次 VLM 语义分组）

    Stage 1: OmniParser 粗检测（获得精确边界框）
    Stage 2: VLM 语义分组（判断哪些框构成同一功能组件）→ 代码计算合并

    Args:
        image_path: 截图路径
        api_key: VLM API 密钥
        api_url: VLM API 端点
        vlm_model: VLM 模型名称
        omni_device: OmniParser 运行设备
        box_threshold: OmniParser 检测阈值
        iou_threshold: OmniParser IOU 阈值
        omni_components: 已有的 OmniParser 检测结果（可选，传入则跳过检测）
        output_dir: 输出目录（用于保存中间结果，可选）

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

    # Stage 2: VLM 语义分组（单次调用：原图 + 坐标文本）
    print(f"\n[Stage 2] VLM 语义分组（原图 + 坐标文本）...")
    _stage2_status = "success"
    _stage2_error = None
    try:
        grouping_result = call_vlm_for_grouping(
            api_key=api_key,
            api_url=api_url,
            model=vlm_model,
            image_path=image_path,
            omni_components=omni_components,
            max_retries=3
        )

        groups = grouping_result.get('groups', [])
        print(f"  ✓ VLM 返回 {len(groups)} 个分组")

        # 保存分组中间结果
        if output_dir:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            screenshot_name = Path(image_path).stem
            grouping_path = Path(output_dir) / f"{screenshot_name}_stage2_grouping_{timestamp}.json"
            with open(grouping_path, 'w', encoding='utf-8') as f:
                json.dump(grouping_result, f, ensure_ascii=False, indent=2)
            print(f"  ✓ 分组结果保存至: {grouping_path}")

        # 代码计算合并
        final_components, merge_log = apply_grouping(
            groups=groups,
            omni_components=omni_components
        )

        print(f"  ✓ 合并后: {len(final_components)} 个组件")

    except Exception as e:
        print(f"  [ERROR] VLM 语义分组失败: {e}")
        import traceback
        traceback.print_exc()
        print(f"  回退到 OmniParser 原始结果（共 {len(omni_components)} 个组件）")
        final_components = omni_components
        merge_log = [{'action': 'stage2_failed', 'reason': str(e)}]
        _stage2_error = str(e)

    if merge_log:
        print(f"  处理日志:")
        for log in merge_log[:5]:
            print(f"    - {log.get('action')}: {log.get('reason', 'N/A')}")
        if len(merge_log) > 5:
            print(f"    ... 还有 {len(merge_log) - 5} 条")

    print(f"\n  ✓ 最终结果: {len(omni_components)} → {len(final_components)} 个组件")

    # 构建最终 UI-JSON
    ui_json = {
        "metadata": {
            "source": Path(image_path).name,
            "extractionMethod": "OmniParser+VLM_Grouping_v3",
            "models": {
                "detection": "OmniParser (YOLO + PaddleOCR + Florence2)",
                "semantic_grouping": vlm_model
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
        "componentCount": len(final_components),
        "_stage2_status": _stage2_status,
    }
    if _stage2_error:
        ui_json["_stage2_error"] = _stage2_error

    return ui_json


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(
        description='OmniParser + VLM 融合提取器（单次 VLM 语义分组）'
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
                        help='VLM 模型名称')
    parser.add_argument('--omni-device',
                        help='OmniParser 运行设备 (cuda/cpu)')
    parser.add_argument('--output', '-o',
                        help='输出 JSON 文件路径')
    parser.add_argument('--output-dir',
                        help='输出目录（保存分组等中间结果）')
    parser.add_argument('--pretty', action='store_true',
                        help='格式化输出 JSON')

    args = parser.parse_args()

    print("=" * 60)
    print("OmniParser + VLM 融合提取（单次语义分组）")
    print("=" * 60)

    ui_json = omni_vlm_fusion(
        image_path=args.image,
        api_key=args.api_key,
        api_url=args.api_url,
        vlm_model=args.vlm_model,
        omni_device=args.omni_device,
        output_dir=args.output_dir
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
    print(f"  提取方式: OmniParser + VLM 语义分组")
    print(f"  原始检测: {ui_json['metadata']['processing']['omni_raw_count']} 个")
    print(f"  整合后: {ui_json['componentCount']} 个")
    print("=" * 60)


if __name__ == '__main__':
    main()
