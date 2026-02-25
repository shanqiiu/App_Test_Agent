#!/usr/bin/env python3
"""
generate_meta.py - GT模板 meta.json 自动生成

扫描 GT 模板目录下的异常截图，使用 VLM 分析每张图片的视觉特征，
自动生成符合 MetaLoader 规范的 meta.json 文件。

用法:
  # 单目录生成（默认 dry-run 预览）
  python generate_meta.py --dir "../data/Agent执行遇到的典型异常UI类型/analysis/gt_templates/弹窗覆盖原UI"

  # 实际写入
  python generate_meta.py --dir "../data/.../弹窗覆盖原UI" --run

  # 覆盖已有 meta.json
  python generate_meta.py --dir "../data/.../弹窗覆盖原UI" --run --force

  # 批量扫描所有子目录
  python generate_meta.py --scan-all "../data/Agent执行遇到的典型异常UI类型/analysis/gt_templates" --run

  # 手动指定类别（目录名无法自动推断时）
  python generate_meta.py --dir "./my_custom_dir" --category dialog_blocking --run
"""

import argparse
import json
import os
import re
import sys
import time
import requests
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

# 自动加载项目根目录的 .env 文件
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parents[3] / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

# 从环境变量读取配置
VLM_API_KEY = os.environ.get('VLM_API_KEY')
VLM_API_URL = os.environ.get('VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions')
VLM_MODEL = os.environ.get('VLM_MODEL', 'gpt-4o')

# 复用项目内的公共工具
from utils.common import encode_image, get_mime_type, extract_json

# ============================================================
# 目录名 → 类别映射
# ============================================================
DIR_TO_CATEGORY = {
    '弹窗覆盖原UI': ('dialog_blocking', '弹窗覆盖UI - 用于生成各类遮挡弹窗异常'),
    '内容歧义、重复': ('content_duplicate', '内容歧义/重复 - UI元素重复显示导致操作歧义'),
    'loading_timeout': ('loading_timeout', '加载超时/白屏 - 页面无内容或加载失败'),
}

CATEGORY_TO_MODE = {
    'dialog_blocking': 'dialog',
    'content_duplicate': 'content_duplicate',
    'loading_timeout': 'area_loading',
}

# 校验时的默认值
VISUAL_DEFAULTS = {
    'overlay_enabled': False,
    'overlay_opacity': 0,
    'close_button_position': 'none',
    'close_button_style': 'none',
    'main_button_text': '',
    'main_button_style': 'none',
    'title_text': '',
    'subtitle_text': '',
    'special_elements': [],
}

# ============================================================
# VLM Prompt 模板
# ============================================================

PROMPT_DIALOG_BLOCKING = """你是一个UI异常分析专家。请仔细分析这张移动APP异常UI截图，提取详细的结构化元数据。

## 分析要求

### 1. anomaly_type（英文snake_case）
根据异常UI元素的功能给出描述性ID，例如：
reward_badge_dialog, promotional_coupon_dialog, permission_dialog, context_menu_dropdown, tutorial_guide, tooltip_bubble, floating_tip_banner, ad_popup, update_dialog 等

### 2. anomaly_description（中文）
一句话描述，包含：哪个APP/页面 + 弹出了什么 + 显示什么内容。
例如："华为花粉俱乐部首页中央弹出HarmonyOS勋章奖励弹窗，显示'恭喜您获得勋章'"

### 3. visual_features
提取全部以下字段：
- app_style: APP名称（如"淘宝"、"美团"、"抖音"）
- primary_color: 弹窗主色调HEX，如"#FF6600"
- background: 背景描述+HEX，如"白色 #FFFFFF"或"红色渐变 #FF1744 → #FF6B35"
- dialog_position: 必须是以下之一：
  "center", "bottom-left-inline", "bottom-center-floating", "bottom-fixed", "bottom-floating", "top", "multi-layer"
- dialog_size_ratio: 弹窗占屏幕比例 {"width": 0.xx, "height": 0.xx}
- overlay_enabled: 是否有半透明遮罩(true/false)
- overlay_opacity: 遮罩不透明度(0.0-1.0)，无遮罩则为0
- close_button_position: "top-right"/"top-left"/"bottom-center"/"left-side"/"none"
- close_button_style: 如"gray_circle_x"/"white_text_button"/"circle_x"/"none"
- main_button_text: 主按钮文字，没有则""
- main_button_style: 如"red_filled"/"outlined_with_arrow"/"blue_filled"/"none"
- title_text: 标题文字，没有则""
- subtitle_text: 副标题，没有则""
- special_elements: 特殊视觉元素列表

如果有以下场景特定字段也请添加：
- 下拉菜单: list_style, selected_indicator, menu_items, selected_item
- 气泡提示: bubble_shape, text_content
- 引导教程: navigation_text, navigation_style, skip_button_text
- 优惠券: coupon_amount, coupon_condition
- 横幅: mascot_position, mascot_style, close_button_text, main_text

### 4. generation_template
- instruction: 一句话中文指令，描述如何生成此异常
- patch_operations: 数组，每个元素：
  {"type":"add", "component":"PascalCase组件名", "position":"与dialog_position对应", "overlay":bool, "close_button":bool}
- key_points: 5条左右中文短句，描述必须包含的视觉要素

## 输出（仅返回JSON，不要其他文字）

```json
{
  "anomaly_type": "",
  "anomaly_description": "",
  "visual_features": {
    "app_style": "",
    "primary_color": "#XXXXXX",
    "background": "",
    "dialog_position": "",
    "dialog_size_ratio": {"width": 0.0, "height": 0.0},
    "overlay_enabled": false,
    "overlay_opacity": 0,
    "close_button_position": "none",
    "close_button_style": "none",
    "main_button_text": "",
    "main_button_style": "none",
    "title_text": "",
    "subtitle_text": "",
    "special_elements": []
  },
  "generation_template": {
    "instruction": "",
    "patch_operations": [{"type":"add","component":"","position":"","overlay":false,"close_button":false}],
    "key_points": ["","","","",""]
  }
}
```"""

PROMPT_CONTENT_DUPLICATE = """你是一个UI异常分析专家。请仔细分析这张移动APP异常UI截图，这是一个"内容重复/歧义"类型的异常。

## 分析要求

### 1. anomaly_type（英文snake_case）
如：ui_duplicate_display, content_overlap, info_repeat

### 2. anomaly_description（中文）
描述哪些UI元素出现了重复/歧义，位置在哪里。

### 3. duplicate_mode（重复模式）
- "expanded_view": 原有组件在底部浮层中以扩展形式重复显示
- "simple_crop": 原有组件被简单复制到另一位置

### 4. visual_features
- app_style: APP名称
- primary_color: 主色调HEX
- background: 背景色HEX
- duplicate_element: 被重复的UI元素名称（如"选集"、"评论列表"）
- original_position: 原始位置（"page-inline"/"header"等）
- duplicate_position: 重复位置（"bottom-sheet"/"floating-panel"等）
- duplicate_expansion: {"original_layout":"horizontal/vertical/grid", "expanded_layout":"...", "original_count":数量, "expanded_count":数量, "grid_columns":列数}
- overlay_enabled: boolean
- overlay_opacity: 0.0-1.0
- close_button_position: 关闭按钮位置
- close_button_style: 关闭按钮样式

### 5. generation_template
- instruction: 中文指令
- patch_operations: type为"add"，component为"BottomSheet"或"FloatingPanel"，包含content:"duplicate_of_existing_list"
- key_points: 设计要点列表

## 输出（仅返回JSON）

```json
{
  "anomaly_type": "",
  "anomaly_description": "",
  "duplicate_mode": "expanded_view",
  "visual_features": {
    "app_style": "",
    "primary_color": "#XXXXXX",
    "background": "#XXXXXX",
    "duplicate_element": "",
    "original_position": "",
    "duplicate_position": "",
    "duplicate_expansion": {"original_layout":"","expanded_layout":"","original_count":0,"expanded_count":0,"grid_columns":0},
    "overlay_enabled": false,
    "overlay_opacity": 0,
    "close_button_position": "none",
    "close_button_style": "none"
  },
  "generation_template": {
    "instruction": "",
    "patch_operations": [{"type":"add","component":"BottomSheet","position":"bottom","content":"duplicate_of_existing_list","overlay":false,"close_button":false}],
    "key_points": ["","","",""]
  }
}
```"""

PROMPT_LOADING_TIMEOUT = """你是一个UI异常分析专家。请仔细分析这张移动APP异常UI截图，这是一个"加载超时/白屏"类型的异常。

## 分析要求

### 1. anomaly_type（英文snake_case）
如：white_screen, loading_spinner, network_error, empty_content, partial_load

### 2. anomaly_description（中文）
描述页面加载失败的具体表现。

### 3. visual_features
- app_style: APP名称或"通用"
- primary_color: 主色调HEX
- background: 背景描述+HEX
- screen_state: "blank"/"loading"/"error"/"partial"
- has_loading_indicator: 是否有加载动画(boolean)
- has_error_message: 是否有错误提示文字(boolean)
- has_retry_button: 是否有重试按钮(boolean)

### 4. generation_template
- instruction: 中文指令
- patch_operations: type为"replace"，component为"FullScreen"或"ContentArea"
- key_points: 设计要点列表

## 输出（仅返回JSON）

```json
{
  "anomaly_type": "",
  "anomaly_description": "",
  "visual_features": {
    "app_style": "",
    "primary_color": "#XXXXXX",
    "background": "",
    "screen_state": "blank",
    "has_loading_indicator": false,
    "has_error_message": false,
    "has_retry_button": false
  },
  "generation_template": {
    "instruction": "",
    "patch_operations": [{"type":"replace","component":"FullScreen","content":"blank_white","preserve_status_bar":true,"preserve_nav_bar":false}],
    "key_points": ["","","",""]
  }
}
```"""

CATEGORY_TO_PROMPT = {
    'dialog_blocking': PROMPT_DIALOG_BLOCKING,
    'content_duplicate': PROMPT_CONTENT_DUPLICATE,
    'loading_timeout': PROMPT_LOADING_TIMEOUT,
}


# ============================================================
# 核心函数
# ============================================================

def detect_category(dir_name: str) -> Tuple[Optional[str], Optional[str]]:
    """从目录名推断 category_id 和 description"""
    if dir_name in DIR_TO_CATEGORY:
        return DIR_TO_CATEGORY[dir_name]
    # 模糊匹配
    for key, value in DIR_TO_CATEGORY.items():
        if key in dir_name or dir_name in key:
            return value
    return (None, None)


def scan_images(directory: Path) -> List[Path]:
    """扫描目录内的图片文件"""
    images = []
    for ext in ['*.jpg', '*.jpeg', '*.png']:
        images.extend(directory.glob(ext))
    images.sort(key=lambda p: p.name)
    return images


def call_vlm_analyze(
    image_path: str,
    prompt: str,
    api_key: str,
    api_url: str,
    vlm_model: str,
    max_retries: int = 2,
    verbose: bool = False,
) -> Optional[dict]:
    """
    调用 VLM 分析单张异常图片

    Returns:
        解析后的 JSON dict，失败返回 None
    """
    image_base64 = encode_image(image_path)
    mime_type = get_mime_type(image_path)

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }

    payload = {
        'model': vlm_model,
        'messages': [{
            'role': 'user',
            'content': [
                {
                    'type': 'image_url',
                    'image_url': {'url': f'data:{mime_type};base64,{image_base64}'}
                },
                {'type': 'text', 'text': prompt}
            ]
        }],
        'temperature': 0.3,
        'max_tokens': 2000
    }

    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                wait = min(2 ** attempt, 10)
                print(f"    ⏳ 等待 {wait}s 后重试 ({attempt}/{max_retries})...")
                time.sleep(wait)

            response = requests.post(api_url, headers=headers, json=payload, timeout=120)

            # 429 限流
            if response.status_code == 429:
                print(f"    ⚠ API 限流 (429)")
                time.sleep(10)
                continue
            # 5xx 服务器错误
            if response.status_code >= 500:
                print(f"    ⚠ 服务器错误 ({response.status_code})")
                continue

            response.raise_for_status()
            content = response.json()['choices'][0]['message']['content']

            if verbose:
                print(f"    [VLM 原始返回] {content[:200]}...")

            result = extract_json(content)
            return result

        except requests.exceptions.Timeout:
            print(f"    ⚠ 请求超时")
        except json.JSONDecodeError as e:
            print(f"    ⚠ JSON 解析失败: {e}")
        except Exception as e:
            print(f"    ⚠ 调用失败: {e}")

    print(f"    ✗ {max_retries + 1} 次尝试均失败")
    return None


def validate_and_fill(sample: dict, category_id: str) -> Tuple[dict, List[str]]:
    """
    校验 VLM 返回结果，缺失字段填默认值

    Returns:
        (processed_sample, warnings)
    """
    warnings = []

    # 必填顶级字段
    for field in ['anomaly_type', 'anomaly_description', 'visual_features', 'generation_template']:
        if field not in sample:
            warnings.append(f"缺失字段: {field}")

    if 'anomaly_type' not in sample:
        sample['anomaly_type'] = 'unknown'
    if 'anomaly_description' not in sample:
        sample['anomaly_description'] = ''

    # visual_features 默认值
    vf = sample.get('visual_features', {})
    if not isinstance(vf, dict):
        vf = {}
        warnings.append("visual_features 不是 dict，已重置")

    if category_id == 'dialog_blocking':
        for key, default in VISUAL_DEFAULTS.items():
            if key not in vf:
                vf[key] = default
        # dialog_size_ratio 特殊处理
        if 'dialog_size_ratio' not in vf:
            vf['dialog_size_ratio'] = {'width': 0.8, 'height': 0.5}
        elif isinstance(vf['dialog_size_ratio'], dict):
            vf['dialog_size_ratio'].setdefault('width', 0.8)
            vf['dialog_size_ratio'].setdefault('height', 0.5)

    sample['visual_features'] = vf

    # generation_template 默认值
    gt = sample.get('generation_template', {})
    if not isinstance(gt, dict):
        gt = {}
        warnings.append("generation_template 不是 dict，已重置")
    gt.setdefault('instruction', '')
    gt.setdefault('patch_operations', [])
    gt.setdefault('key_points', [])
    sample['generation_template'] = gt

    return sample, warnings


def generate_usage_string(category_id: str, dir_name: str) -> str:
    """生成 usage 字段"""
    mode = CATEGORY_TO_MODE.get(category_id, 'dialog')
    if category_id == 'content_duplicate':
        return f'--anomaly-mode {mode} --gt-category "{dir_name}" --gt-sample "<sample>.jpg"'
    else:
        return f'--gt-dir ./gt_templates/{dir_name} --reference ./gt_templates/{dir_name}/<sample>.jpg'


def merge_meta(existing: dict, new_samples: dict) -> Tuple[dict, int]:
    """
    合并新样本到已有 meta.json，保留已有条目不修改

    Returns:
        (merged_meta, added_count)
    """
    merged = existing.copy()
    existing_samples = merged.get('samples', {})

    added = 0
    for filename, sample_data in new_samples.items():
        if filename not in existing_samples:
            existing_samples[filename] = sample_data
            added += 1
            print(f"    + 新增样本: {filename}")
        else:
            print(f"    = 跳过已有: {filename}")

    merged['samples'] = existing_samples
    merged['count'] = len(existing_samples)
    return merged, added


# ============================================================
# 主流程
# ============================================================

def generate_meta_for_directory(
    target_dir: str,
    category_id: str = None,
    description: str = None,
    api_key: str = None,
    api_url: str = None,
    vlm_model: str = None,
    max_retries: int = 2,
    force: bool = False,
    dry_run: bool = True,
    output_path: str = None,
    verbose: bool = False,
) -> Optional[dict]:
    """
    对单个 GT 模板目录生成 meta.json

    Returns:
        生成的 meta.json dict，失败返回 None
    """
    target_path = Path(target_dir)
    dir_name = target_path.name

    if not target_path.exists():
        print(f"[ERROR] 目录不存在: {target_dir}")
        return None

    # 1. 确定类别
    if not category_id:
        category_id, auto_desc = detect_category(dir_name)
        if not category_id:
            print(f"[ERROR] 无法从目录名 '{dir_name}' 推断类别")
            print(f"  请使用 --category 手动指定")
            print(f"  可用类别: {', '.join(DIR_TO_CATEGORY.values().__iter__().__next__() for _ in [1])}")
            print(f"  可用类别: dialog_blocking, content_duplicate, loading_timeout")
            return None
        if not description:
            description = auto_desc

    if not description:
        description = f"{dir_name} - 异常场景"

    # 2. 选择 prompt
    prompt = CATEGORY_TO_PROMPT.get(category_id, PROMPT_DIALOG_BLOCKING)

    # 3. 扫描图片
    images = scan_images(target_path)
    if not images:
        print(f"[ERROR] 目录中无图片文件: {target_dir}")
        return None

    # 4. 检查已有 meta.json
    meta_file = target_path / 'meta.json'
    existing_meta = None
    existing_samples = {}

    if meta_file.exists() and not force:
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                existing_meta = json.load(f)
            existing_samples = existing_meta.get('samples', {})
        except Exception as e:
            print(f"  ⚠ 读取已有 meta.json 失败: {e}")

    # 5. 打印信息
    mode_label = "覆盖" if force else "合并(仅新增)"
    print(f"\n{'='*60}")
    print(f"generate_meta.py - GT模板元数据自动生成")
    print(f"{'='*60}")
    print(f"  目录:       {target_dir}")
    print(f"  类别ID:     {category_id}")
    print(f"  描述:       {description}")
    print(f"  图片数:     {len(images)} 张")
    if existing_meta:
        print(f"  已有meta:   是 ({len(existing_samples)} 个样本)")
    else:
        print(f"  已有meta:   否")
    print(f"  写入模式:   {mode_label}")
    print(f"  dry-run:    {dry_run}")
    print(f"  VLM模型:    {vlm_model}")
    print(f"{'='*60}")

    # 6. 逐图分析
    new_samples = {}
    success_count = 0
    skip_count = 0
    fail_count = 0

    for i, img_path in enumerate(images, 1):
        filename = img_path.name
        print(f"\n[{i}/{len(images)}] 分析: {filename}")

        # merge 模式下跳过已有
        if not force and filename in existing_samples:
            print(f"    = 已有meta信息，跳过")
            skip_count += 1
            continue

        # 调用 VLM
        result = call_vlm_analyze(
            image_path=str(img_path),
            prompt=prompt,
            api_key=api_key,
            api_url=api_url,
            vlm_model=vlm_model,
            max_retries=max_retries,
            verbose=verbose,
        )

        if result is None:
            print(f"    ✗ 分析失败")
            fail_count += 1
            continue

        # 校验并填充默认值
        result, warnings = validate_and_fill(result, category_id)
        for w in warnings:
            print(f"    ⚠ {w}")

        new_samples[filename] = result
        success_count += 1
        anomaly_type = result.get('anomaly_type', '?')
        anomaly_desc = result.get('anomaly_description', '')
        print(f"    ✓ {anomaly_type}")
        print(f"      {anomaly_desc[:60]}{'...' if len(anomaly_desc) > 60 else ''}")

        # 防限流间隔
        if i < len(images):
            time.sleep(1)

    # 7. 组装 meta.json
    if force or existing_meta is None:
        # 全新生成或覆盖
        all_samples = {**new_samples}
        if not force and existing_meta:
            # 不应到这里，但安全起见
            all_samples = {**existing_samples, **new_samples}

        meta = {
            'category': category_id,
            'description': description,
            'count': len(all_samples),
            'samples': all_samples,
            'usage': generate_usage_string(category_id, dir_name),
        }
    else:
        # 合并模式
        meta, added = merge_meta(existing_meta, new_samples)

    # 8. 输出
    output = Path(output_path) if output_path else meta_file

    print(f"\n{'='*60}")
    print(f"生成结果")
    print(f"{'='*60}")
    print(f"  新增:   {success_count}")
    print(f"  跳过:   {skip_count}")
    print(f"  失败:   {fail_count}")
    print(f"  总样本: {meta['count']}")

    if dry_run:
        print(f"\n[DRY RUN] meta.json 预览:\n")
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        print(f"\n[DRY RUN] 使用 --run 写入文件")
    else:
        with open(output, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"  输出:   {output}")

    return meta


def scan_all_directories(
    gt_root: str,
    **kwargs,
):
    """批量扫描所有 GT 模板子目录，逐个生成 meta.json"""
    gt_path = Path(gt_root)
    if not gt_path.exists():
        print(f"[ERROR] 根目录不存在: {gt_root}")
        return

    subdirs = sorted([d for d in gt_path.iterdir() if d.is_dir()])
    if not subdirs:
        print(f"[ERROR] 根目录下无子目录: {gt_root}")
        return

    print(f"\n扫描到 {len(subdirs)} 个 GT 模板目录:")
    for d in subdirs:
        img_count = len(scan_images(d))
        has_meta = (d / 'meta.json').exists()
        print(f"  {'[有meta]' if has_meta else '[无meta]'} {d.name} ({img_count} 张)")

    print()

    results = {'success': 0, 'skip': 0, 'fail': 0}
    for i, subdir in enumerate(subdirs, 1):
        print(f"\n{'#'*60}")
        print(f"# [{i}/{len(subdirs)}] {subdir.name}")
        print(f"{'#'*60}")

        result = generate_meta_for_directory(
            target_dir=str(subdir),
            **kwargs,
        )

        if result is not None:
            results['success'] += 1
        else:
            results['fail'] += 1

    print(f"\n{'='*60}")
    print(f"批量生成完成!")
    print(f"  成功: {results['success']}")
    print(f"  失败: {results['fail']}")
    print(f"{'='*60}")


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='GT模板 meta.json 自动生成（VLM 驱动）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 预览（默认 dry-run）
  python generate_meta.py --dir "../data/.../gt_templates/弹窗覆盖原UI"

  # 实际写入
  python generate_meta.py --dir "../data/.../gt_templates/弹窗覆盖原UI" --run

  # 覆盖已有 meta.json
  python generate_meta.py --dir "../data/.../gt_templates/弹窗覆盖原UI" --run --force

  # 批量生成所有子目录
  python generate_meta.py --scan-all "../data/.../gt_templates" --run

  # 手动指定类别
  python generate_meta.py --dir "./custom_dir" --category dialog_blocking --run
"""
    )

    # 目标目录（二选一）
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--dir', '-d',
                       help='单个 GT 模板目录路径')
    group.add_argument('--scan-all',
                       help='GT 模板根目录，遍历所有子目录')

    # 类别配置
    parser.add_argument('--category', '-c',
                        choices=['dialog_blocking', 'content_duplicate', 'loading_timeout'],
                        help='类别ID（不指定则从目录名自动推断）')
    parser.add_argument('--description',
                        help='类别中文描述（不指定则自动推断）')

    # 执行模式
    parser.add_argument('--run', action='store_true',
                        help='实际写入文件（默认为 dry-run 预览）')
    parser.add_argument('--force', action='store_true',
                        help='覆盖已有 meta.json（默认 merge 仅添加新样本）')
    parser.add_argument('--dry-run', action='store_true',
                        help='仅预览，不写入（默认行为）')
    parser.add_argument('--output', '-o',
                        help='输出路径（默认 <dir>/meta.json）')

    # VLM 配置
    parser.add_argument('--api-key', default=VLM_API_KEY,
                        help='VLM API 密钥')
    parser.add_argument('--api-url', default=VLM_API_URL,
                        help='VLM API 端点')
    parser.add_argument('--vlm-model', default=VLM_MODEL,
                        help='VLM 模型名')
    parser.add_argument('--retry', type=int, default=2,
                        help='VLM 调用失败重试次数（默认 2）')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='显示 VLM 原始返回')

    args = parser.parse_args()

    # 检查 API Key
    if not args.api_key:
        print("[ERROR] 未设置 VLM_API_KEY，请配置 .env 文件或使用 --api-key")
        return

    # 默认 dry-run
    dry_run = not args.run

    if dry_run and not args.dry_run:
        print("[提示] 默认为预览模式，添加 --run 来实际写入\n")

    # 公共参数
    common_kwargs = dict(
        api_key=args.api_key,
        api_url=args.api_url,
        vlm_model=args.vlm_model,
        max_retries=args.retry,
        force=args.force,
        dry_run=dry_run,
        verbose=args.verbose,
    )

    if args.scan_all:
        scan_all_directories(
            gt_root=args.scan_all,
            **common_kwargs,
        )
    else:
        generate_meta_for_directory(
            target_dir=args.dir,
            category_id=args.category,
            description=args.description,
            output_path=args.output,
            **common_kwargs,
        )


if __name__ == '__main__':
    main()
