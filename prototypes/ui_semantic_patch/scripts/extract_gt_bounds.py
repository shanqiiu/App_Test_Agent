#!/usr/bin/env python3
"""
extract_gt_bounds.py - 从 GT 参考图中提取弹窗精确边界框

流程：
1. 对 GT 参考图运行 OmniParser (Stage 1) 获取所有检测框
2. 运行 VLM 语义过滤 (Stage 2) 合并弹窗子元素
3. 根据 meta.json 中的 dialog_position + dialog_size_ratio 计算预期区域
4. 用 IoU 匹配找到最佳弹窗组件
5. 将精确像素边界 dialog_bounds_px 写回 meta.json

只处理 overlay_enabled=false 的样本（4个）：
- 商品下方存在遮挡.jpg
- 使用教程遮挡2.jpg
- 使用教程遮挡3.jpg
- 弹出提示.jpg
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image

# 添加 scripts 目录到路径
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

# 自动加载 .env
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parents[3] / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

# 环境变量
VLM_API_KEY = os.environ.get('VLM_API_KEY')
VLM_API_URL = os.environ.get('VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions')
STRUCTURE_MODEL = os.environ.get('STRUCTURE_MODEL', 'qwen-vl-max')


def calculate_expected_region(
    dialog_position: str,
    dialog_size_ratio: Dict,
    screen_width: int,
    screen_height: int
) -> Dict[str, int]:
    """
    根据 meta.json 的 dialog_position 和 dialog_size_ratio
    计算弹窗的预期像素区域（宽松估计，用于 IoU 匹配）

    Returns:
        {'x': int, 'y': int, 'width': int, 'height': int}
    """
    # 解析尺寸比例
    if isinstance(dialog_size_ratio, dict):
        w_ratio = dialog_size_ratio.get('width', 0.8)
        h_ratio = dialog_size_ratio.get('height', 0.5)
    else:
        w_ratio, h_ratio = 0.8, 0.5

    exp_w = int(screen_width * w_ratio)
    exp_h = int(screen_height * h_ratio)

    # 根据 dialog_position 计算预期位置
    if dialog_position == 'center':
        exp_x = (screen_width - exp_w) // 2
        exp_y = (screen_height - exp_h) // 2

    elif dialog_position == 'bottom-fixed':
        exp_x = (screen_width - exp_w) // 2
        exp_y = screen_height - exp_h - 20

    elif dialog_position == 'bottom-floating':
        exp_x = (screen_width - exp_w) // 2
        exp_y = screen_height - exp_h - 80

    elif dialog_position == 'bottom-center-floating':
        exp_x = (screen_width - exp_w) // 2
        exp_y = int(screen_height * 0.75)

    elif dialog_position == 'bottom-left-inline':
        exp_x = 30
        exp_y = int(screen_height * 0.50)

    elif dialog_position in ('bottom', 'bottom-center'):
        exp_x = (screen_width - exp_w) // 2
        exp_y = screen_height - exp_h - 100

    elif dialog_position == 'multi-layer':
        exp_x = (screen_width - exp_w) // 2
        exp_y = (screen_height - exp_h) // 2

    else:
        exp_x = (screen_width - exp_w) // 2
        exp_y = (screen_height - exp_h) // 2

    return {'x': exp_x, 'y': exp_y, 'width': exp_w, 'height': exp_h}


def compute_iou(box_a: Dict, box_b: Dict) -> float:
    """
    计算两个矩形的 IoU (Intersection over Union)

    Args:
        box_a, box_b: {'x': int, 'y': int, 'width': int, 'height': int}

    Returns:
        IoU 值 [0, 1]
    """
    ax1, ay1 = box_a['x'], box_a['y']
    ax2, ay2 = ax1 + box_a['width'], ay1 + box_a['height']

    bx1, by1 = box_b['x'], box_b['y']
    bx2, by2 = bx1 + box_b['width'], by1 + box_b['height']

    # 交集
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0

    inter_area = (ix2 - ix1) * (iy2 - iy1)
    area_a = box_a['width'] * box_a['height']
    area_b = box_b['width'] * box_b['height']
    union_area = area_a + area_b - inter_area

    if union_area <= 0:
        return 0.0

    return inter_area / union_area


def compute_containment(inner: Dict, outer: Dict) -> float:
    """
    计算 inner 被 outer 包含的比例 (intersection / inner_area)

    用于处理预期区域估计不准确但检测框精确的情况。

    Returns:
        [0, 1]，1.0 表示 inner 完全被 outer 包含
    """
    ix1 = max(inner['x'], outer['x'])
    iy1 = max(inner['y'], outer['y'])
    ix2 = min(inner['x'] + inner['width'], outer['x'] + outer['width'])
    iy2 = min(inner['y'] + inner['height'], outer['y'] + outer['height'])

    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0

    inter_area = (ix2 - ix1) * (iy2 - iy1)
    inner_area = inner['width'] * inner['height']

    if inner_area <= 0:
        return 0.0

    return inter_area / inner_area


def find_dialog_component(
    components: List[Dict],
    expected_region: Dict,
    screen_width: int,
    screen_height: int,
    dialog_position: str
) -> Optional[Tuple[Dict, float, str]]:
    """
    在检测组件列表中找到最可能是弹窗的组件

    策略：
    1. 计算每个组件与预期区域的 IoU
    2. 计算每个组件与预期区域的 containment（组件被预期区域包含的比例）
    3. 过滤掉明显的背景组件（如状态栏、全屏内容区）
    4. 综合评分选择最佳匹配

    Returns:
        (component, score, match_reason) 或 None
    """
    if not components:
        return None

    screen_area = screen_width * screen_height
    candidates = []

    for comp in components:
        bounds = comp.get('bounds', {})
        comp_area = bounds.get('width', 0) * bounds.get('height', 0)

        # 过滤：排除占屏幕面积超过 60% 的组件（这些是背景/全屏内容区）
        if comp_area > screen_area * 0.6:
            continue

        # 过滤：排除状态栏
        comp_class = comp.get('class', '')
        if comp_class == 'StatusBar':
            continue

        # 过滤：排除太小的组件（面积小于屏幕的 0.5%）
        if comp_area < screen_area * 0.005:
            continue

        # 计算 IoU
        iou = compute_iou(bounds, expected_region)

        # 计算 containment：组件被预期区域包含的程度
        containment = compute_containment(bounds, expected_region)

        # 计算反向 containment：预期区域被组件包含的程度
        reverse_containment = compute_containment(expected_region, bounds)

        # 综合评分
        # IoU 权重最高，但 containment 也很重要（预期区域估计可能不准确）
        score = iou * 0.5 + containment * 0.3 + reverse_containment * 0.2

        # 位置加分：检查组件是否在预期的屏幕区域
        position_bonus = _position_bonus(bounds, dialog_position, screen_width, screen_height)
        score += position_bonus * 0.15

        if score > 0.05:  # 最低阈值
            candidates.append((comp, score, iou, containment))

    if not candidates:
        return None

    # 按综合评分排序
    candidates.sort(key=lambda x: x[1], reverse=True)
    best_comp, best_score, best_iou, best_containment = candidates[0]

    reason = f"IoU={best_iou:.3f}, containment={best_containment:.3f}, score={best_score:.3f}"
    return (best_comp, best_score, reason)


def _position_bonus(
    bounds: Dict,
    dialog_position: str,
    screen_width: int,
    screen_height: int
) -> float:
    """
    根据 dialog_position 对位于正确屏幕区域的组件给予加分

    Returns:
        [0, 1]
    """
    center_x = bounds['x'] + bounds['width'] / 2
    center_y = bounds['y'] + bounds['height'] / 2

    # 归一化到 [0, 1]
    norm_cx = center_x / screen_width
    norm_cy = center_y / screen_height

    if 'bottom' in dialog_position:
        # 弹窗应在屏幕下半部分
        return max(0, (norm_cy - 0.5) * 2)
    elif dialog_position == 'center':
        # 弹窗应在屏幕中间区域
        return max(0, 1 - abs(norm_cy - 0.5) * 4)
    elif dialog_position == 'top':
        # 弹窗应在屏幕上半部分
        return max(0, (0.5 - norm_cy) * 2)

    return 0.5  # 未知位置，给中间分


def extract_bounds_for_sample(
    image_path: str,
    sample_meta: Dict,
    api_key: str,
    api_url: str,
    vlm_model: str,
    omni_device: str = None,
    skip_vlm: bool = False
) -> Optional[Dict[str, int]]:
    """
    对单个 GT 样本提取弹窗精确边界框

    Args:
        image_path: GT 图片路径
        sample_meta: meta.json 中该样本的元数据
        api_key: VLM API key
        api_url: VLM API URL
        vlm_model: VLM 模型名称
        omni_device: OmniParser 设备
        skip_vlm: 是否跳过 VLM Stage 2（只用 Stage 1）

    Returns:
        {'x': int, 'y': int, 'width': int, 'height': int} 或 None
    """
    print(f"\n  --- 处理: {Path(image_path).name} ---")

    # 获取图片尺寸
    with Image.open(image_path) as img:
        screen_width, screen_height = img.size
    print(f"  图片尺寸: {screen_width}x{screen_height}")

    # 从 meta 提取位置信息
    visual_features = sample_meta.get('visual_features', {})
    dialog_position = visual_features.get('dialog_position', 'center')
    dialog_size_ratio = visual_features.get('dialog_size_ratio', {'width': 0.8, 'height': 0.5})

    # 计算预期区域
    expected = calculate_expected_region(
        dialog_position, dialog_size_ratio,
        screen_width, screen_height
    )
    print(f"  预期区域: x={expected['x']}, y={expected['y']}, "
          f"w={expected['width']}, h={expected['height']} "
          f"(位置类型: {dialog_position})")

    # Stage 1: OmniParser 检测
    print(f"  [Stage 1] OmniParser 检测...")
    from omni_extractor import omni_to_ui_json
    omni_result = omni_to_ui_json(
        image_path=image_path,
        device=omni_device
    )
    omni_components = omni_result['components']
    print(f"  检测到 {len(omni_components)} 个组件")

    # Stage 2: VLM 语义过滤（合并弹窗子元素）
    if not skip_vlm and api_key:
        print(f"  [Stage 2] VLM 语义过滤...")
        from omni_vlm_fusion import omni_vlm_fusion
        fusion_result = omni_vlm_fusion(
            image_path=image_path,
            api_key=api_key,
            api_url=api_url,
            vlm_model=vlm_model,
            omni_components=omni_components
        )
        components = fusion_result['components']
        print(f"  过滤后 {len(components)} 个组件")
    else:
        components = omni_components
        if not api_key:
            print(f"  ⚠ 未提供 API key，跳过 VLM 过滤")

    # 打印所有候选组件
    print(f"  组件列表:")
    for comp in components:
        b = comp.get('bounds', {})
        area_ratio = (b.get('width', 0) * b.get('height', 0)) / (screen_width * screen_height)
        print(f"    [{comp.get('index', '?'):2d}] {comp.get('class', '?'):<15} "
              f"({b.get('x', 0):4d},{b.get('y', 0):4d}) "
              f"{b.get('width', 0):4d}x{b.get('height', 0):<4d} "
              f"({area_ratio:.1%}) "
              f"\"{comp.get('text', '')[:30]}\"")

    # IoU 匹配
    match_result = find_dialog_component(
        components=components,
        expected_region=expected,
        screen_width=screen_width,
        screen_height=screen_height,
        dialog_position=dialog_position
    )

    if not match_result:
        print(f"  ✗ 未找到匹配的弹窗组件")
        return None

    matched_comp, score, reason = match_result
    bounds = matched_comp['bounds']
    print(f"  ✓ 匹配成功: [{matched_comp.get('index', '?')}] "
          f"\"{matched_comp.get('text', '')[:30]}\"")
    print(f"    边界: x={bounds['x']}, y={bounds['y']}, "
          f"w={bounds['width']}, h={bounds['height']}")
    print(f"    {reason}")

    return {
        'x': bounds['x'],
        'y': bounds['y'],
        'width': bounds['width'],
        'height': bounds['height']
    }


def main():
    parser = argparse.ArgumentParser(
        description='从 GT 参考图中提取弹窗精确边界框'
    )
    parser.add_argument('--gt-dir', default=None,
                        help='GT 模板目录（默认自动查找）')
    parser.add_argument('--category', default='弹窗覆盖原UI',
                        help='处理的类别名称')
    parser.add_argument('--sample', default=None,
                        help='只处理指定样本（默认处理所有非 overlay 样本）')
    parser.add_argument('--api-key', default=VLM_API_KEY,
                        help='VLM API 密钥（默认从环境变量读取）')
    parser.add_argument('--api-url', default=VLM_API_URL,
                        help='VLM API 端点')
    parser.add_argument('--vlm-model', default=STRUCTURE_MODEL,
                        help='VLM 模型名称')
    parser.add_argument('--omni-device', default=None,
                        help='OmniParser 运行设备')
    parser.add_argument('--skip-vlm', action='store_true',
                        help='跳过 VLM 过滤，只用 OmniParser')
    parser.add_argument('--dry-run', action='store_true',
                        help='只分析不写入 meta.json')

    args = parser.parse_args()

    # 查找 GT 模板目录
    if args.gt_dir:
        gt_dir = Path(args.gt_dir)
    else:
        gt_dir = SCRIPTS_DIR.parent / 'data' / 'Agent执行遇到的典型异常UI类型' / 'analysis' / 'gt_templates'

    category_dir = gt_dir / args.category
    meta_path = category_dir / 'meta.json'

    if not meta_path.exists():
        print(f"[ERROR] meta.json 不存在: {meta_path}")
        sys.exit(1)

    # 加载 meta.json
    with open(meta_path, 'r', encoding='utf-8') as f:
        meta = json.load(f)

    samples = meta.get('samples', {})

    print("=" * 60)
    print("GT 弹窗边界框提取")
    print("=" * 60)
    print(f"  类别: {args.category}")
    print(f"  目录: {category_dir}")
    print(f"  样本数: {len(samples)}")

    # 确定要处理的样本（只处理 overlay_enabled=false 的）
    if args.sample:
        # 用户指定了具体样本
        target_samples = {args.sample: samples[args.sample]} if args.sample in samples else {}
        if not target_samples:
            print(f"[ERROR] 样本不存在: {args.sample}")
            sys.exit(1)
    else:
        # 自动筛选 overlay_enabled=false 的样本
        target_samples = {}
        for name, sample_meta in samples.items():
            vf = sample_meta.get('visual_features', {})
            if not vf.get('overlay_enabled', True):
                target_samples[name] = sample_meta

    print(f"\n  待处理样本 ({len(target_samples)} 个):")
    for name in target_samples:
        vf = target_samples[name].get('visual_features', {})
        print(f"    - {name} (位置: {vf.get('dialog_position', '?')})")

    if not target_samples:
        print("  没有需要处理的样本")
        return

    # 逐个处理
    results = {}
    for sample_name, sample_meta in target_samples.items():
        image_path = category_dir / sample_name

        if not image_path.exists():
            print(f"\n  ⚠ 图片不存在: {image_path}")
            continue

        bounds = extract_bounds_for_sample(
            image_path=str(image_path),
            sample_meta=sample_meta,
            api_key=args.api_key,
            api_url=args.api_url,
            vlm_model=args.vlm_model,
            omni_device=args.omni_device,
            skip_vlm=args.skip_vlm
        )

        if bounds:
            results[sample_name] = bounds

    # 汇总
    print("\n" + "=" * 60)
    print("提取结果汇总")
    print("=" * 60)

    for name, bounds in results.items():
        # 计算实际比例（用于对比）
        image_path = category_dir / name
        with Image.open(str(image_path)) as img:
            sw, sh = img.size
        actual_w_ratio = bounds['width'] / sw
        actual_h_ratio = bounds['height'] / sh

        old_ratio = target_samples[name].get('visual_features', {}).get('dialog_size_ratio', {})
        old_w = old_ratio.get('width', '?') if isinstance(old_ratio, dict) else '?'
        old_h = old_ratio.get('height', '?') if isinstance(old_ratio, dict) else '?'

        print(f"  {name}:")
        print(f"    bounds_px: x={bounds['x']}, y={bounds['y']}, "
              f"w={bounds['width']}, h={bounds['height']}")
        print(f"    实际比例: width={actual_w_ratio:.3f}, height={actual_h_ratio:.3f}")
        print(f"    原始比例: width={old_w}, height={old_h}")

    # 写入 meta.json
    if not args.dry_run and results:
        print(f"\n  写入 meta.json...")
        for name, bounds in results.items():
            meta['samples'][name]['dialog_bounds_px'] = bounds

        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"  ✓ 已更新 {len(results)} 个样本的 dialog_bounds_px")
        print(f"  ✓ 保存至: {meta_path}")
    elif args.dry_run:
        print(f"\n  [DRY-RUN] 未写入 meta.json")
    else:
        print(f"\n  ⚠ 没有成功提取的结果")


if __name__ == '__main__':
    main()
