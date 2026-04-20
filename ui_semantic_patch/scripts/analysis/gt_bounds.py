#!/usr/bin/env python3
"""
extract_gt_bounds.py - 从 GT 参考图中提取弹窗精确边界框

流程：
1. 对 GT 参考图运行 OmniParser (Stage 1) 获取所有检测框
2. 运行 VLM 语义过滤 (Stage 2) 合并弹窗子元素
3. 根据 meta.json 中的 dialog_position + dialog_size_ratio 计算预期区域
4. 用 IoU 匹配找到最佳弹窗组件
5. 对有遮罩的弹窗(overlay_enabled=true)使用亮度分割法辅助定位
6. 将精确像素边界 dialog_bounds_px 写回 meta.json

支持所有样本类型：
- overlay_enabled=false: 使用 OmniParser 检测 + IoU 匹配
- overlay_enabled=true: 优先使用亮度分割法，OmniParser 作为辅助验证
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

# 添加 scripts 目录到路径
SCRIPTS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

# 自动加载 .env
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parents[4] / '.env'
    if env_path.exists():
        print("hhhhh")
        load_dotenv(env_path)
except ImportError:
    pass

# 环境变量
VLM_API_KEY = os.environ.get('VLM_API_KEY')
VLM_API_URL = os.environ.get('VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions')
STRUCTURE_MODEL = os.environ.get('STRUCTURE_MODEL', os.environ.get('VLM_MODEL', 'qwen35-9b-vl'))

print(VLM_API_URL)
def _import_omni_to_ui_json():
    """兼容脚本直跑与包内运行的 OmniParser 导入。"""
    try:
        # 包内运行（如 python -m ...）
        from ..omni_extractor import omni_to_ui_json  # type: ignore
    except Exception:
        # 脚本直跑（如 python gt_bounds.py），依赖前面注入的 SCRIPTS_DIR
        from omni_extractor import omni_to_ui_json  # type: ignore
    return omni_to_ui_json


def _import_omni_vlm_fusion():
    """兼容脚本直跑与包内运行的 VLM 融合导入。"""
    try:
        # 包内运行（如 python -m ...）
        from ..omni_vlm_fusion import omni_vlm_fusion  # type: ignore
    except Exception:
        # 脚本直跑（如 python gt_bounds.py），依赖前面注入的 SCRIPTS_DIR
        from omni_vlm_fusion import omni_vlm_fusion  # type: ignore
    return omni_vlm_fusion


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


def detect_dialog_by_brightness(
    image_path: str,
    dialog_position: str = 'center',
    overlay_opacity: float = 0.5,
    min_area_ratio: float = 0.02,
    max_area_ratio: float = 0.6,
) -> Optional[Dict[str, int]]:
    """
    通过亮度分割法定位有遮罩(overlay)弹窗的精确边界。

    原理：半透明遮罩将背景压暗为均匀暗色区域，弹窗卡片是唯一的高亮区域。
    通过亮度阈值分割 + 连通区域分析可以精确提取弹窗轮廓。

    Args:
        image_path: GT 图片路径
        dialog_position: 弹窗位置（用于多候选区时选择）
        overlay_opacity: 遮罩不透明度（用于自适应阈值）
        min_area_ratio: 候选区域最小面积占比（过滤噪点）
        max_area_ratio: 候选区域最大面积占比（过滤背景误检）

    Returns:
        {'x': int, 'y': int, 'width': int, 'height': int} 或 None
    """
    img = Image.open(image_path).convert('RGB')
    img_w, img_h = img.size
    screen_area = img_w * img_h

    gray = np.array(img.convert('L'))

    # 自适应阈值：遮罩越深，亮暗差越大
    # overlay_opacity=0.5 时，遮罩区域亮度约为原始的 50%
    # 弹窗区域保持原始亮度，通常 > 150
    # 取中位数作为暗区域代表值，阈值设为中位数 + 偏移
    median_brightness = np.median(gray)
    threshold = int(median_brightness + (255 - median_brightness) * 0.3)
    threshold = max(threshold, 100)  # 最低阈值防止全白场景
    print(f"  亮度分割: 中位数={median_brightness:.0f}, 阈值={threshold}")

    # 二值化：亮区域 = 弹窗候选
    binary = (gray > threshold).astype(np.uint8)

    # 连通区域分析（简单的 flood-fill 实现，避免依赖 scipy）
    regions = _find_connected_regions(binary, min_area=int(screen_area * min_area_ratio))

    if not regions:
        print(f"  亮度分割: 未找到有效亮区域")
        return None

    # 过滤候选区域（放宽 min_area 以保留按钮等小部件，合并后再做整体过滤）
    small_min = max(min_area_ratio * 0.3, 0.005)  # 允许更小的子区域参与合并
    filtered = []
    for region in regions:
        x, y, w, h = region
        area = w * h
        area_ratio = area / screen_area

        if area_ratio > max_area_ratio:
            continue
        if area_ratio < small_min:
            continue

        # 宽高比检查：弹窗通常不会极端细长
        aspect = max(w, h) / max(min(w, h), 1)
        if aspect > 8:
            continue

        filtered.append((x, y, w, h, area_ratio))

    if not filtered:
        print(f"  亮度分割: 过滤后无有效候选区域")
        return None

    print(f"  亮度分割: {len(filtered)} 个原始区域")
    for i, (x, y, w, h, ratio) in enumerate(filtered):
        print(f"    [{i}] ({x},{y}) {w}x{h} ({ratio:.1%})")

    # 合并空间上接近的区域（同一弹窗的卡片、按钮、标题等）
    candidates = _merge_nearby_regions(filtered, img_w, img_h, screen_area,
                                        min_area_ratio, max_area_ratio)

    if not candidates:
        print(f"  亮度分割: 合并后无有效候选区域")
        return None

    print(f"  亮度分割: 合并后 {len(candidates)} 个候选")
    for i, (x, y, w, h, ratio) in enumerate(candidates):
        print(f"    [{i}] ({x},{y}) {w}x{h} ({ratio:.1%})")

    # 选择最佳候选
    best = _select_best_candidate(candidates, dialog_position, img_w, img_h)
    x, y, w, h, _ = best
    print(f"  亮度分割 初始: ({x},{y}) {w}x{h}")

    # 边界扩展：从初始亮区域向外扩展，直到触碰遮罩层
    expanded = _expand_to_dialog_edge(gray, x, y, w, h, median_brightness)
    ex, ey, ew, eh = expanded['x'], expanded['y'], expanded['width'], expanded['height']
    if (ex, ey, ew, eh) != (x, y, w, h):
        print(f"  亮度分割 扩展: ({ex},{ey}) {ew}x{eh}")
    print(f"  亮度分割 ✓: ({ex},{ey}) {ew}x{eh}")
    return expanded


def _expand_to_dialog_edge(
    gray: np.ndarray,
    x: int, y: int, w: int, h: int,
    overlay_brightness: float,
    step: int = 8,
    band: int = 12,
    grace: int = 2,
    max_expand_ratio: float = 0.5,
) -> Dict[str, int]:
    """
    从初始亮区域向外扩展边界，直到触碰遮罩暗区域。

    弹窗可能包含暗色部分（照片、深色按钮），亮度分割只检测到了
    最亮的核心区域。通过扫描边缘带的亮度分布，判断是否仍属于弹窗。

    判断标准：扩展方向上的带内，与弹窗水平/垂直范围交叉的区域中，
    亮像素占比 > 40%。

    Args:
        gray: 灰度图 numpy 数组
        x, y, w, h: 初始边界框
        overlay_brightness: 遮罩层的代表亮度（中位数）
        step: 每次扩展的像素步长
        band: 每次采样的带宽
        grace: 允许连续多少个暗带不中断
        max_expand_ratio: 每个方向最大扩展量 = 初始尺寸 * 此比例
    """
    img_h, img_w = gray.shape

    # 计算遮罩区域的代表亮度：取初始框之外的像素
    mask = np.ones_like(gray, dtype=bool)
    mask[y:y+h, x:x+w] = False
    outside_pixels = gray[mask]
    if len(outside_pixels) > 0:
        overlay_base = float(np.percentile(outside_pixels, 50))
    else:
        overlay_base = float(np.percentile(gray, 25))

    # 亮像素阈值：高于遮罩中位数 + 一个台阶
    bright_px_threshold = overlay_base + (255 - overlay_base) * 0.2
    bright_ratio_threshold = 0.40

    print(f"  扩展: overlay_base={overlay_base:.0f}, bright_px_threshold={bright_px_threshold:.0f}")

    # 最大扩展量
    max_expand_v = int(h * max_expand_ratio)
    max_expand_h = int(w * max_expand_ratio)

    top, bottom = y, y + h
    left, right = x, x + w

    def _band_is_dialog(band_slice: np.ndarray) -> bool:
        if band_slice.size == 0:
            return False
        return np.mean(band_slice > bright_px_threshold) > bright_ratio_threshold

    # 向上扩展
    expanded_up = 0
    dark_count = 0
    while top - step >= 0 and expanded_up < max_expand_v:
        row_band = gray[max(0, top - band):top, left:right]
        if _band_is_dialog(row_band):
            top -= step
            expanded_up += step
            dark_count = 0
        else:
            dark_count += 1
            if dark_count > grace:
                break
            top -= step
            expanded_up += step

    # 向下扩展
    expanded_down = 0
    dark_count = 0
    while bottom + step <= img_h and expanded_down < max_expand_v:
        row_band = gray[bottom:min(img_h, bottom + band), left:right]
        if _band_is_dialog(row_band):
            bottom += step
            expanded_down += step
            dark_count = 0
        else:
            dark_count += 1
            if dark_count > grace:
                break
            bottom += step
            expanded_down += step

    # 向左扩展
    expanded_left = 0
    dark_count = 0
    while left - step >= 0 and expanded_left < max_expand_h:
        col_band = gray[top:bottom, max(0, left - band):left]
        if _band_is_dialog(col_band):
            left -= step
            expanded_left += step
            dark_count = 0
        else:
            dark_count += 1
            if dark_count > grace:
                break
            left -= step
            expanded_left += step

    # 向右扩展
    expanded_right = 0
    dark_count = 0
    while right + step <= img_w and expanded_right < max_expand_h:
        col_band = gray[top:bottom, right:min(img_w, right + band)]
        if _band_is_dialog(col_band):
            right += step
            expanded_right += step
            dark_count = 0
        else:
            dark_count += 1
            if dark_count > grace:
                break
            right += step
            expanded_right += step

    return {'x': max(0, left), 'y': max(0, top),
            'width': min(img_w, right) - max(0, left),
            'height': min(img_h, bottom) - max(0, top)}


def _merge_nearby_regions(
    regions: List[Tuple[int, int, int, int, float]],
    img_w: int,
    img_h: int,
    screen_area: int,
    min_area_ratio: float,
    max_area_ratio: float,
    gap_threshold_ratio: float = 0.08,
) -> List[Tuple[int, int, int, int, float]]:
    """
    合并空间上接近的亮区域。

    弹窗通常由多个亮度不同的部分组成（卡片主体、按钮、标题），
    亮度分割后它们会成为独立区域。如果这些区域在垂直方向上接近
    且水平范围有显著重叠，则合并为同一弹窗。

    Args:
        regions: [(x, y, w, h, area_ratio), ...]
        gap_threshold_ratio: 两个区域间距 / 屏幕高度 的最大比例

    Returns:
        合并后的候选区域列表
    """
    if len(regions) <= 1:
        return [r for r in regions if r[4] >= min_area_ratio]

    gap_threshold = int(img_h * gap_threshold_ratio)

    # 按 y 坐标排序
    sorted_regions = sorted(regions, key=lambda r: r[1])

    # 贪心合并：如果两个区域垂直间距小于阈值且水平有重叠，则合并
    merged = []
    current = list(sorted_regions[0])  # [x, y, w, h, area_ratio]

    for i in range(1, len(sorted_regions)):
        rx, ry, rw, rh, r_ratio = sorted_regions[i]

        # 当前合并区域的底边
        cur_bottom = current[1] + current[3]
        # 下一区域的顶边
        next_top = ry
        vertical_gap = next_top - cur_bottom

        # 水平重叠检查
        cur_left, cur_right = current[0], current[0] + current[2]
        next_left, next_right = rx, rx + rw
        overlap_left = max(cur_left, next_left)
        overlap_right = min(cur_right, next_right)
        horizontal_overlap = overlap_right - overlap_left

        # 重叠比例（相对于较小区域的宽度）
        min_width = min(current[2], rw)
        overlap_ratio = horizontal_overlap / max(min_width, 1) if horizontal_overlap > 0 else 0

        if vertical_gap <= gap_threshold and overlap_ratio > 0.3:
            # 合并：扩展当前区域的边界框
            new_x = min(current[0], rx)
            new_y = min(current[1], ry)
            new_right = max(current[0] + current[2], rx + rw)
            new_bottom = max(current[1] + current[3], ry + rh)
            current[0] = new_x
            current[1] = new_y
            current[2] = new_right - new_x
            current[3] = new_bottom - new_y
            current[4] = (current[2] * current[3]) / screen_area
        else:
            merged.append(tuple(current))
            current = list(sorted_regions[i])

    merged.append(tuple(current))

    # 最终过滤
    result = []
    for (x, y, w, h, ratio) in merged:
        if ratio < min_area_ratio or ratio > max_area_ratio:
            continue
        result.append((x, y, w, h, ratio))

    return result


def _find_connected_regions(
    binary: np.ndarray,
    min_area: int = 100
) -> List[Tuple[int, int, int, int]]:
    """
    在二值图中找到连通亮区域的外接矩形。

    使用行扫描 + 合并的方式，避免逐像素 flood-fill 的性能问题。

    Returns:
        [(x, y, width, height), ...]
    """
    h, w = binary.shape
    visited = np.zeros_like(binary, dtype=bool)
    regions = []

    # 下采样加速（对大图）
    scale = 1
    if h * w > 2_000_000:
        scale = 2
        binary = binary[::scale, ::scale]
        visited = np.zeros_like(binary, dtype=bool)
        h, w = binary.shape
        min_area = min_area // (scale * scale)

    # 扫描线找连通区域
    for y_start in range(0, h, 4):  # 步长4加速扫描
        for x_start in range(0, w, 4):
            if binary[y_start, x_start] == 0 or visited[y_start, x_start]:
                continue

            # BFS 找连通区域
            min_x, min_y = x_start, y_start
            max_x, max_y = x_start, y_start
            pixel_count = 0
            stack = [(x_start, y_start)]
            visited[y_start, x_start] = True

            while stack:
                cx, cy = stack.pop()
                pixel_count += 1
                min_x = min(min_x, cx)
                min_y = min(min_y, cy)
                max_x = max(max_x, cx)
                max_y = max(max_y, cy)

                for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx] and binary[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((nx, ny))

            region_w = max_x - min_x + 1
            region_h = max_y - min_y + 1
            if region_w * region_h >= min_area:
                regions.append((
                    min_x * scale,
                    min_y * scale,
                    region_w * scale,
                    region_h * scale,
                ))

    return regions


def _select_best_candidate(
    candidates: List[Tuple[int, int, int, int, float]],
    dialog_position: str,
    img_w: int,
    img_h: int
) -> Tuple[int, int, int, int, float]:
    """根据 dialog_position 从候选区域中选择最佳匹配"""
    if len(candidates) == 1:
        return candidates[0]

    scored = []
    for (x, y, w, h, ratio) in candidates:
        cx = (x + w / 2) / img_w
        cy = (y + h / 2) / img_h
        score = ratio  # 面积越大越可能是弹窗

        if 'bottom' in dialog_position:
            score += max(0, cy - 0.5) * 0.5
        elif dialog_position == 'center':
            score += max(0, 1 - abs(cy - 0.5) * 3) * 0.3
            score += max(0, 1 - abs(cx - 0.5) * 3) * 0.2
        elif dialog_position == 'top':
            score += max(0, 0.5 - cy) * 0.5

        scored.append(((x, y, w, h, ratio), score))

    scored.sort(key=lambda s: s[1], reverse=True)
    return scored[0][0]


def extract_bounds_for_sample(
    image_path: str,
    sample_meta: Dict,
    api_key: str = None,
    api_url: str = None,
    vlm_model: str = None,
    omni_device: str = None,
    skip_vlm: bool = False
) -> Optional[Dict[str, int]]:
    """
    对单个 GT 样本提取弹窗精确边界框

    策略选择：
    - overlay_enabled=true: 优先亮度分割法（利用遮罩的明暗对比），
      OmniParser 作为辅助验证
    - overlay_enabled=false: OmniParser 检测 + IoU 匹配

    Args:
        image_path: GT 图片路径
        sample_meta: meta.json 中该样本的元数据
        api_key: VLM API key（可选，overlay 样本可不需要）
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
    overlay_enabled = visual_features.get('overlay_enabled', False)
    overlay_opacity = visual_features.get('overlay_opacity', 0.5)

    print(f"  overlay_enabled={overlay_enabled}, opacity={overlay_opacity}")

    # 策略分支
    if overlay_enabled:
        return _extract_with_brightness(
            image_path, dialog_position, overlay_opacity,
            dialog_size_ratio, screen_width, screen_height,
            api_key, api_url, vlm_model, omni_device, skip_vlm
        )
    else:
        return _extract_with_omniparser(
            image_path, dialog_position, dialog_size_ratio,
            screen_width, screen_height,
            api_key, api_url, vlm_model, omni_device, skip_vlm
        )


def _extract_with_brightness(
    image_path: str,
    dialog_position: str,
    overlay_opacity: float,
    dialog_size_ratio: Dict,
    screen_width: int,
    screen_height: int,
    api_key: str = None,
    api_url: str = None,
    vlm_model: str = None,
    omni_device: str = None,
    skip_vlm: bool = False,
) -> Optional[Dict[str, int]]:
    """overlay 弹窗提取：亮度分割 + OmniParser 辅助扩展"""

    print(f"  [策略] 亮度分割 + OmniParser 辅助 (overlay 弹窗)")

    # 1. 亮度分割 → 找到弹窗亮色核心区域
    brightness_bounds = detect_dialog_by_brightness(
        image_path=image_path,
        dialog_position=dialog_position,
        overlay_opacity=overlay_opacity,
    )

    if not brightness_bounds:
        # 亮度分割完全失败，回退到纯 OmniParser
        print(f"  [回退] 亮度分割失败，尝试纯 OmniParser")
        return _extract_with_omniparser(
            image_path, dialog_position, dialog_size_ratio,
            screen_width, screen_height,
            api_key, api_url, vlm_model, omni_device, skip_vlm
        )

    # 2. OmniParser 辅助扩展：用检测到的 UI 组件补全暗色区域
    expanded = _expand_with_omniparser(
        image_path=image_path,
        initial_bounds=brightness_bounds,
        screen_width=screen_width,
        screen_height=screen_height,
        omni_device=omni_device,
    )

    # 3. 验证最终结果
    expected_area = (dialog_size_ratio.get('width', 0.8) *
                     dialog_size_ratio.get('height', 0.5) *
                     screen_width * screen_height)
    actual_area = expanded['width'] * expanded['height']
    ratio = actual_area / expected_area if expected_area > 0 else 0

    if 0.2 < ratio < 4.0:
        print(f"  ✓ 最终结果通过验证 (面积比={ratio:.2f})")
        return expanded

    # 面积偏差过大，回退到纯 OmniParser IoU 匹配
    print(f"  ⚠ 面积偏差过大 (比={ratio:.2f})，回退到纯 OmniParser IoU 匹配")
    return _extract_with_omniparser(
        image_path, dialog_position, dialog_size_ratio,
        screen_width, screen_height,
        api_key, api_url, vlm_model, omni_device, skip_vlm
    )


def _expand_with_omniparser(
    image_path: str,
    initial_bounds: Dict[str, int],
    screen_width: int,
    screen_height: int,
    omni_device: str = None,
    overlap_threshold: float = 0.15,
    gap_px: int = 80,
) -> Dict[str, int]:
    """
    用 OmniParser 检测到的 UI 组件扩展亮度分割的初始边界。

    原理：亮度分割只能捕获弹窗的亮色部分，暗色区域（照片、深色标题栏）
    会被遗漏。OmniParser 能检测到这些暗色区域内的 UI 元素（文字、按钮、
    图标等）。将与初始边界重叠或紧邻的组件吸收进来，即可得到完整弹窗边界。

    迭代扩展：每轮将与当前边界重叠/紧邻的组件合并，直到无新组件被吸收。

    Args:
        image_path: 图片路径
        initial_bounds: 亮度分割得到的初始边界
        screen_width, screen_height: 屏幕尺寸
        omni_device: OmniParser 运行设备
        overlap_threshold: 组件与当前边界的最小重叠/邻近比例
        gap_px: 组件与当前边界的最大间距（像素），在此范围内视为相邻

    Returns:
        扩展后的边界框
    """
    # 加载灰度图用于亮度过滤
    gray = np.array(Image.open(image_path).convert('L'))

    # 计算遮罩区域的亮度基准（初始框之外的像素中位数）
    ib = initial_bounds
    mask = np.ones_like(gray, dtype=bool)
    mask[ib['y']:ib['y']+ib['height'], ib['x']:ib['x']+ib['width']] = False
    outside_pixels = gray[mask]
    overlay_median = float(np.median(outside_pixels)) if len(outside_pixels) > 0 else 100.0
    # 组件亮度阈值：高于遮罩亮度 + 一个台阶才算弹窗内组件
    comp_brightness_threshold = overlay_median + (255 - overlay_median) * 0.12

    # 运行 OmniParser Stage 1
    try:
        omni_to_ui_json = _import_omni_to_ui_json()
        print(f"  [OmniParser 辅助] 检测 UI 组件...")
        omni_result = omni_to_ui_json(image_path=image_path, device=omni_device)
        components = omni_result['components']
        print(f"  [OmniParser 辅助] 检测到 {len(components)} 个组件")
    except Exception as e:
        print(f"  [OmniParser 辅助] 加载失败: {e}，使用亮度分割结果")
        return initial_bounds

    if not components:
        return initial_bounds

    screen_area = screen_width * screen_height

    # 过滤组件：排除状态栏、导航栏、全屏背景 + 亮度过滤
    dialog_components = []
    rejected_dark = 0
    for comp in components:
        b = comp.get('bounds', {})
        comp_area = b.get('width', 0) * b.get('height', 0)

        # 排除占屏幕 > 50% 的背景组件
        if comp_area > screen_area * 0.5:
            continue
        # 排除极小组件（< 0.1% 屏幕面积）
        if comp_area < screen_area * 0.001:
            continue
        # 排除状态栏
        if comp.get('class', '') == 'StatusBar':
            continue

        # 亮度过滤：排除位于遮罩暗区域的组件（APP背景透过遮罩显示的内容）
        bx, by = b.get('x', 0), b.get('y', 0)
        bw, bh = b.get('width', 0), b.get('height', 0)
        # 取组件区域的平均亮度
        region = gray[by:by+bh, bx:bx+bw]
        if region.size > 0:
            comp_mean_brightness = float(np.mean(region))
            if comp_mean_brightness < comp_brightness_threshold:
                rejected_dark += 1
                continue

        dialog_components.append(b)

    if rejected_dark > 0:
        print(f"  [OmniParser 辅助] 亮度过滤: 排除 {rejected_dark} 个暗区组件 "
              f"(阈值={comp_brightness_threshold:.0f}, overlay={overlay_median:.0f})")

    # 迭代扩展
    current = dict(initial_bounds)  # copy
    max_iterations = 5

    for iteration in range(max_iterations):
        absorbed = 0
        remaining = []

        for comp_bounds in dialog_components:
            if _should_absorb(current, comp_bounds, gap_px, overlap_threshold):
                # 合并到当前边界
                new_x = min(current['x'], comp_bounds['x'])
                new_y = min(current['y'], comp_bounds['y'])
                new_right = max(current['x'] + current['width'],
                                comp_bounds['x'] + comp_bounds['width'])
                new_bottom = max(current['y'] + current['height'],
                                 comp_bounds['y'] + comp_bounds['height'])
                current = {
                    'x': new_x, 'y': new_y,
                    'width': new_right - new_x,
                    'height': new_bottom - new_y,
                }
                absorbed += 1
            else:
                remaining.append(comp_bounds)

        dialog_components = remaining

        if absorbed == 0:
            break
        print(f"    迭代 {iteration+1}: 吸收 {absorbed} 个组件 → "
              f"({current['x']},{current['y']}) {current['width']}x{current['height']}")

    # 安全检查：扩展后不应超过屏幕面积的 70%
    expanded_area = current['width'] * current['height']
    if expanded_area > screen_area * 0.7:
        print(f"  ⚠ OmniParser 扩展过度 ({expanded_area/screen_area:.1%})，回退到亮度结果")
        return initial_bounds

    if current != initial_bounds:
        print(f"  [OmniParser 辅助] 扩展: "
              f"({initial_bounds['x']},{initial_bounds['y']}) "
              f"{initial_bounds['width']}x{initial_bounds['height']} → "
              f"({current['x']},{current['y']}) "
              f"{current['width']}x{current['height']}")
    else:
        print(f"  [OmniParser 辅助] 无需扩展")

    return current


def _should_absorb(
    current: Dict[str, int],
    comp: Dict[str, int],
    gap_px: int,
    overlap_threshold: float,
) -> bool:
    """
    判断一个组件是否应被吸收到当前弹窗边界中。

    条件（满足任一即可）：
    1. 组件与当前边界有足够的重叠（IoU 或 containment）
    2. 组件紧邻当前边界（间距 < gap_px）且水平有显著对齐

    Args:
        current: 当前弹窗边界
        comp: 候选组件边界
        gap_px: 最大间距
        overlap_threshold: 最小重叠比例
    """
    cx1, cy1 = current['x'], current['y']
    cx2, cy2 = cx1 + current['width'], cy1 + current['height']
    bx1, by1 = comp['x'], comp['y']
    bx2, by2 = bx1 + comp['width'], by1 + comp['height']

    # 条件 1: 组件被当前边界包含（或显著重叠）
    containment = compute_containment(comp, current)
    if containment > overlap_threshold:
        return True

    # 条件 2: 紧邻 + 水平对齐
    # 垂直间距
    if by1 > cy2:
        v_gap = by1 - cy2
    elif cy1 > by2:
        v_gap = cy1 - by2
    else:
        v_gap = 0  # 垂直有重叠

    # 水平间距
    if bx1 > cx2:
        h_gap = bx1 - cx2
    elif cx1 > bx2:
        h_gap = cx1 - bx2
    else:
        h_gap = 0  # 水平有重叠

    # 间距过大则不吸收
    if v_gap > gap_px or h_gap > gap_px:
        return False

    # 水平对齐检查：组件的水平范围应与当前边界有显著重叠
    h_overlap_left = max(cx1, bx1)
    h_overlap_right = min(cx2, bx2)
    if h_overlap_right <= h_overlap_left:
        return False  # 完全不在水平范围内

    comp_width = max(comp['width'], 1)
    h_overlap_ratio = (h_overlap_right - h_overlap_left) / comp_width
    return h_overlap_ratio > 0.3


def _extract_with_omniparser(
    image_path: str,
    dialog_position: str,
    dialog_size_ratio: Dict,
    screen_width: int,
    screen_height: int,
    api_key: str = None,
    api_url: str = None,
    vlm_model: str = None,
    omni_device: str = None,
    skip_vlm: bool = False,
) -> Optional[Dict[str, int]]:
    """OmniParser 检测 + IoU 匹配提取弹窗边界"""

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
    try:
        omni_to_ui_json = _import_omni_to_ui_json()
        omni_result = omni_to_ui_json(
            image_path=image_path,
            device=omni_device
        )
        omni_components = omni_result['components']
        print(f"  检测到 {len(omni_components)} 个组件")
    except Exception as e:
        print(f"  ✗ OmniParser 运行失败: {e}")
        print("    提示: 请安装 OmniParser 依赖，例如")
        print("      pip install -r ../../third_party/OmniParser/requirements.txt")
        return None

    # Stage 2: VLM 语义过滤（合并弹窗子元素）
    if not skip_vlm and api_key:
        print(f"  [Stage 2] VLM 语义过滤...")
        omni_vlm_fusion = _import_omni_vlm_fusion()
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


def visualize_bounds(
    category_dir: str,
    results: Dict[str, Dict[str, int]],
    output_dir: str = None,
) -> List[str]:
    """
    将提取的弹窗边界框可视化到原图上。

    在原图上绘制：
    - 红色矩形框标记弹窗边界
    - 绿色虚线框标记裁剪后的参考图区域（含 padding）
    - 左上角标注样本名和坐标信息

    Args:
        category_dir: GT 模板目录
        results: {sample_name: {'x','y','width','height'}, ...}
        output_dir: 输出目录（默认 category_dir/bounds_vis/）

    Returns:
        输出图片路径列表
    """
    from PIL import ImageDraw, ImageFont

    category_path = Path(category_dir)
    if output_dir:
        vis_dir = Path(output_dir)
    else:
        vis_dir = category_path / 'bounds_vis'
    vis_dir.mkdir(parents=True, exist_ok=True)

    # 加载字体
    font = _load_font(16)
    small_font = _load_font(12)

    output_paths = []

    for name, bounds in results.items():
        image_path = category_path / name
        if not image_path.exists():
            continue

        img = Image.open(str(image_path)).convert('RGB')
        draw = ImageDraw.Draw(img)
        img_w, img_h = img.size

        x, y, w, h = bounds['x'], bounds['y'], bounds['width'], bounds['height']

        # 红色实线框：弹窗精确边界
        for offset in range(3):  # 3px 线宽
            draw.rectangle(
                (x - offset, y - offset, x + w + offset, y + h + offset),
                outline='red',
            )

        # 绿色虚线框：裁剪区域（含 5% padding）
        pad = int(min(w, h) * 0.05)
        crop_box = (
            max(0, x - pad),
            max(0, y - pad),
            min(img_w, x + w + pad),
            min(img_h, y + h + pad),
        )
        _draw_dashed_rect(draw, crop_box, color='lime', dash_length=10, gap_length=6)

        # 标注信息
        area_ratio = (w * h) / (img_w * img_h)
        info_lines = [
            f"{name}",
            f"bounds: ({x},{y}) {w}x{h}",
            f"area: {area_ratio:.1%} of screen",
        ]
        text_y = 10
        for line in info_lines:
            # 文字背景
            bbox = draw.textbbox((10, text_y), line, font=small_font)
            draw.rectangle(
                (bbox[0] - 2, bbox[1] - 2, bbox[2] + 2, bbox[3] + 2),
                fill=(0, 0, 0, 180),
            )
            draw.text((10, text_y), line, fill='white', font=small_font)
            text_y += bbox[3] - bbox[1] + 4

        # 裁剪预览（右下角小图）
        cropped = img.crop(crop_box)
        preview_max = 200
        c_w, c_h = cropped.size
        scale = min(preview_max / c_w, preview_max / c_h, 1.0)
        preview_size = (int(c_w * scale), int(c_h * scale))
        preview = cropped.resize(preview_size, Image.Resampling.LANCZOS)

        # 贴到右下角
        px = img_w - preview_size[0] - 10
        py = img_h - preview_size[1] - 10
        # 白色边框
        draw.rectangle(
            (px - 3, py - 3, px + preview_size[0] + 3, py + preview_size[1] + 3),
            outline='white', width=2,
        )
        img.paste(preview, (px, py))

        # 标注 "裁剪预览"
        draw.text(
            (px, py - 16), "cropped preview",
            fill='white', font=small_font,
        )

        # 保存
        out_name = f"bounds_{Path(name).stem}.jpg"
        out_path = vis_dir / out_name
        img.save(str(out_path), quality=90)
        output_paths.append(str(out_path))
        print(f"  ✓ 可视化: {out_path}")

    print(f"\n  可视化输出目录: {vis_dir}")
    return output_paths


def _load_font(size: int):
    """加载字体，降级到默认"""
    from PIL import ImageFont
    font_paths = [
        'C:/Windows/Fonts/msyh.ttc',
        'C:/Windows/Fonts/arial.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/System/Library/Fonts/Helvetica.ttc',
    ]
    for fp in font_paths:
        try:
            return ImageFont.truetype(fp, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _draw_dashed_rect(
    draw: 'ImageDraw.ImageDraw',
    box: Tuple,
    color: str = 'lime',
    dash_length: int = 10,
    gap_length: int = 6,
    width: int = 2,
):
    """绘制虚线矩形"""
    x1, y1, x2, y2 = box
    edges = [
        ((x1, y1), (x2, y1)),  # top
        ((x2, y1), (x2, y2)),  # right
        ((x2, y2), (x1, y2)),  # bottom
        ((x1, y2), (x1, y1)),  # left
    ]
    for (sx, sy), (ex, ey) in edges:
        length = max(abs(ex - sx), abs(ey - sy))
        if length == 0:
            continue
        dx = (ex - sx) / length
        dy = (ey - sy) / length
        pos = 0
        while pos < length:
            seg_end = min(pos + dash_length, length)
            draw.line(
                (sx + dx * pos, sy + dy * pos, sx + dx * seg_end, sy + dy * seg_end),
                fill=color, width=width,
            )
            pos = seg_end + gap_length


def extract_all_bounds(
    category_dir: str,
    meta: dict,
    api_key: str = None,
    api_url: str = None,
    vlm_model: str = None,
    omni_device: str = None,
    skip_vlm: bool = False,
    force: bool = False,
) -> Dict[str, Dict[str, int]]:
    """
    对一个类别目录下所有样本提取 dialog_bounds_px。

    供 generate_meta.py 等外部脚本调用。

    Args:
        category_dir: GT 模板子目录路径
        meta: 已加载的 meta.json dict
        force: 是否覆盖已有 dialog_bounds_px

    Returns:
        {sample_name: {'x': int, 'y': int, 'width': int, 'height': int}, ...}
    """
    category_path = Path(category_dir)
    samples = meta.get('samples', {})
    results = {}

    for name, sample_meta in samples.items():
        if not force and 'dialog_bounds_px' in sample_meta:
            print(f"  = 跳过已有 bounds: {name}")
            continue

        image_path = category_path / name
        if not image_path.exists():
            print(f"  ⚠ 图片不存在: {image_path}")
            continue

        bounds = extract_bounds_for_sample(
            image_path=str(image_path),
            sample_meta=sample_meta,
            api_key=api_key,
            api_url=api_url,
            vlm_model=vlm_model,
            omni_device=omni_device,
            skip_vlm=skip_vlm,
        )

        if bounds:
            results[name] = bounds

    # 自动生成可视化
    if results:
        visualize_bounds(category_dir=category_dir, results=results)

    return results


def main():
    parser = argparse.ArgumentParser(
        description='从 GT 参考图中提取弹窗精确边界框'
    )
    parser.add_argument('--gt-dir', default=None,
                        help='GT 模板目录（默认自动查找）')
    parser.add_argument('--category', default='弹窗覆盖原UI',
                        help='处理的类别名称')
    parser.add_argument('--sample', default=None,
                        help='只处理指定样本（默认处理所有样本）')
    parser.add_argument('--force', action='store_true',
                        help='强制重新提取（覆盖已有 dialog_bounds_px）')
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

    # 确定要处理的样本
    if args.sample:
        # 用户指定了具体样本
        target_samples = {args.sample: samples[args.sample]} if args.sample in samples else {}
        if not target_samples:
            print(f"[ERROR] 样本不存在: {args.sample}")
            sys.exit(1)
    else:
        # 处理所有样本（跳过已有 dialog_bounds_px 的，除非 --force）
        target_samples = {}
        for name, sample_meta in samples.items():
            if not args.force and 'dialog_bounds_px' in sample_meta:
                continue
            target_samples[name] = sample_meta

    print(f"\n  待处理样本 ({len(target_samples)} 个):")
    for name in target_samples:
        vf = target_samples[name].get('visual_features', {})
        overlay = "overlay" if vf.get('overlay_enabled', False) else "no-overlay"
        print(f"    - {name} (位置: {vf.get('dialog_position', '?')}, {overlay})")

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

    # 可视化
    if results:
        print(f"\n{'='*60}")
        print("生成可视化")
        print(f"{'='*60}")
        vis_paths = visualize_bounds(
            category_dir=str(category_dir),
            results=results,
        )

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
