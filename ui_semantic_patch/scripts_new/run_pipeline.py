#!/usr/bin/env python3
"""
run_pipeline.py - UI 异常场景生成流水线

采用简化的异常弹窗生成模式：
- Stage 1: OmniParser 精确检测（YOLO + PaddleOCR + Florence2）
- Stage 2: VLM 语义分组（判断检测框分组，代码合并坐标）
- Stage 3: 直接生成异常弹窗并合并到原截图

所有中间结果均保存，便于调试和优化。
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, List

# 设置UTF-8编码输出（Windows兼容）
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 确保能导入 app 模块（将项目根目录加入 Python 路径）
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# ====== 禁用 HuggingFace 网络访问（必须在使用 transformers 前设置）======
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_DATASETS_OFFLINE'] = '1'
# 不设置 HF_TOKEN_PATH 避免权限错误，让 Transformers 自动处理
# os.environ['HF_TOKEN_PATH'] = ''  # 已注释，避免权限问题
print("✅ 已启用离线模式：模型将完全从本地加载")
# ====== 禁用网络访问结束 ======

# 自动加载项目根目录的 .env 文件
try:
    from dotenv import load_dotenv
    # 查找项目根目录的 .env
    env_path = Path(__file__).resolve().parents[2] / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        print(f"  ✓ 已加载环境配置：{env_path}")
except ImportError:
    pass  # python-dotenv 未安装，使用系统环境变量

# 从环境变量读取配置（必需）
VLM_API_KEY = os.environ.get('VLM_API_KEY')
VLM_API_URL = os.environ.get('VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions')
VLM_MODEL = os.environ.get('VLM_MODEL', 'qwen35-35b-vl')
STRUCTURE_MODEL = os.environ.get('STRUCTURE_MODEL', 'qwen35-35b-vl')
print(STRUCTURE_MODEL)
from app.stages.visualize import visualize_components
from app.core.schemas import (
    Stage2Output,
    Stage1Output,
    validate_stage2_output,
    validate_stage1_output,
)
from app.renderers.text_overlay import EditOp



# ==================== Schema验证辅助函数 ====================

def _validate_stage2_with_fallback(ui_json: dict) -> tuple[Stage2Output | dict, bool]:
    """
    验证Stage 2输出数据，尝试Schema验证，失败时回退到原始dict

    Returns:
        (验证后的数据, 是否使用Schema验证成功)
    """
    try:
        # 尝试使用新Schema验证
        stage2 = validate_stage2_output(ui_json)
        return stage2, True
    except Exception as e:
        # Schema验证失败，记录警告但继续使用旧数据
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Stage2 Schema验证失败，使用原始数据: {e}")
        # 回退到旧格式
        return ui_json, False


def _validate_stage1_with_fallback(omni_result: dict) -> tuple[Stage1Output | dict, bool]:
    """
    验证Stage 1输出数据

    Returns:
        (验证后的数据, 是否使用Schema验证成功)
    """
    try:
        stage1 = validate_stage1_output(omni_result)
        return stage1, True
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Stage1 Schema验证失败，使用原始数据: {e}")
        return omni_result, False


def _get_groups_from_data(data: Stage2Output | dict) -> list:
    """从数据中获取groups列表，兼容新旧格式"""
    if isinstance(data, Stage2Output):
        return data.groups
    return data.get('groups', [])


# ==================== 已迁移到 app/ 的辅助函数 ====================
# _parse_anomaly_type → area_loading.py
# _find_component_by_id → component_position_resolver.py
# _smart_select_component → area_loading.py
# _load_edit_plan → text_overlay.py
# ensure_meta_for_reference → app/generators/meta.py
# _parse_anomaly_type → area_loading.py 内部实现
# _find_component_by_id → component_position_resolver.py
# _smart_select_component → app/renderers/area_loading.py
# _load_edit_plan → app/renderers/text_overlay.py 内部实现


# ==================== 保留的简短辅助函数（无等价实现） ====================

def _parse_anomaly_type(instruction: str) -> str:
    """根据指令文本解析异常类型"""
    instruction_lower = instruction.lower()
    if '超时' in instruction_lower or 'timeout' in instruction_lower:
        return 'timeout'
    elif '网络' in instruction_lower or 'network' in instruction_lower:
        return 'network_error'
    elif '加载' in instruction_lower and '中' in instruction_lower:
        return 'loading'
    elif '图片' in instruction_lower or 'image' in instruction_lower or 'broken' in instruction_lower:
        return 'image_broken'
    elif '暂无' in instruction_lower or 'empty' in instruction_lower:
        return 'empty_data'
    return 'timeout'


def _find_component_by_id(ui_json: dict, target_id: str) -> Optional[dict]:
    """根据 ID 或 index 查找组件"""
    components = ui_json.get('components', [])
    for comp in components:
        if str(comp.get('id', '')) == target_id:
            return comp
    try:
        target_index = int(target_id)
        for comp in components:
            if comp.get('index') == target_index:
                return comp
    except ValueError:
        pass
    return None


def _smart_select_component(ui_json: dict, instruction: str) -> Optional[dict]:
    """根据指令智能推荐目标组件"""
    components = ui_json.get('components', [])
    instruction_lower = instruction.lower()
    type_keywords = {
        'list': ['列表', 'list', 'listview', 'recycler'],
        'image': ['图片', 'image', 'picture', 'photo'],
        'video': ['视频', 'video', 'player'],
        'feed': ['动态', 'feed', 'timeline']
    }
    for ptype in ['list', 'feed', 'image', 'video']:
        for keyword in type_keywords.get(ptype, []):
            if keyword in instruction_lower:
                for comp in reversed(components):
                    comp_class = comp.get('class', '').lower()
                    if any(k in comp_class for k in type_keywords.get(ptype, [])):
                        return comp
    largest_comp = max(components, key=lambda c: c.get('bounds', {}).get('width', 0) * c.get('bounds', {}).get('height', 0), default=None)
    return largest_comp


def _load_edit_plan(plan_path: Optional[str]) -> Optional[List['EditOp']]:
    """加载用户提供的文本编辑计划 JSON"""
    if not plan_path:
        return None
    path = Path(plan_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        print(f"  ⚠ edit_plan 文件不存在: {path}")
        return None
    try:
        raw_data = json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        print(f"  ⚠ 读取 edit_plan 失败: {e}")
        return None
    if not isinstance(raw_data, list):
        print(f"  ⚠ edit_plan JSON 需为数组: {path}")
        return None
    edit_ops: List[EditOp] = []
    for idx, item in enumerate(raw_data, 1):
        if not isinstance(item, dict):
            print(f"  ⚠ edit_plan 第 {idx} 项不是对象，已跳过")
            continue
        try:
            edit_ops.append(EditOp(**item))
        except TypeError as e:
            print(f"  ⚠ edit_plan 第 {idx} 项字段不完整: {e}")
    if not edit_ops:
        print(f"  ⚠ edit_plan 未解析到有效操作: {path}")
        return None
    print(f"  ✓ 已加载 edit_plan ({len(edit_ops)} 个操作): {path}")
    return edit_ops


# OmniParser 融合模块
try:
    from app.stages.omni_vlm_fusion import omni_vlm_fusion
    from app.stages.omni_extractor import omni_to_ui_json
    OMNIPARSER_AVAILABLE = True
except ImportError as e:
    print(f"[WARN] OmniParser 导入失败: {e}")
    OMNIPARSER_AVAILABLE = False


# ==================== 中文类别 → category_id 映射 ====================

GT_CATEGORY_NAME_TO_ID = {
    '弹窗覆盖原UI': 'dialog_blocking',
    '内容歧义、重复': 'content_duplicate',
    'loading_timeout': 'loading_timeout',
}


def ensure_meta_for_reference(
    reference_path: str,
    gt_category: str,
    api_key: str,
    api_url: str = None,
    vlm_model: str = None,
) -> tuple:
    """
    确保参考图有对应的 meta.json 条目，没有则自动调用 VLM 生成。

    Args:
        reference_path: 任意位置的参考异常图片路径
        gt_category: 中文类别名（如"弹窗覆盖原UI"）
        api_key: VLM API 密钥
        api_url: VLM API 端点
        vlm_model: VLM 模型名

    Returns:
        (gt_sample, gt_dir) 元组，可直接传给 Stage 3 渲染
    """
    import json

    ref_path = Path(reference_path).resolve()
    ref_dir = ref_path.parent
    ref_filename = ref_path.name

    # 映射中文类别 → category_id
    category_id = GT_CATEGORY_NAME_TO_ID.get(gt_category)
    if not category_id:
        # 尝试直接作为 category_id 使用
        if gt_category in ('dialog_blocking', 'content_duplicate', 'loading_timeout'):
            category_id = gt_category
        else:
            print(f"  ⚠ 无法识别类别 '{gt_category}'，将使用 dialog_blocking")
            category_id = 'dialog_blocking'

    # 检查 meta.json 是否已包含该文件条目
    meta_file = ref_dir / 'meta.json'
    if meta_file.exists():
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                existing_meta = json.load(f)
            if ref_filename in existing_meta.get('samples', {}):
                print(f"  ✓ meta.json 已包含 '{ref_filename}'，跳过生成")
                return (ref_filename, str(ref_dir))
        except Exception:
            pass

    # 自动生成 meta.json（仅分析该文件）
    print(f"\n{'='*60}")
    print(f"[Auto-Meta] 自动为参考图生成 meta.json")
    print(f"  参考图: {ref_path}")
    print(f"  类别: {gt_category} ({category_id})")
    print(f"{'='*60}")

    from app.generators.meta import generate_meta_for_directory

    result = generate_meta_for_directory(
        target_dir=str(ref_dir),
        category_id=category_id,
        api_key=api_key,
        api_url=api_url or VLM_API_URL,
        vlm_model=vlm_model or VLM_MODEL,
        force=False,
        dry_run=False,
        target_files=[ref_filename],
    )

    if result is None:
        raise RuntimeError(f"Auto-Meta 生成失败: {ref_filename}")

    if ref_filename not in result.get('samples', {}):
        raise RuntimeError(f"Auto-Meta 生成后仍无 '{ref_filename}' 条目")

    print(f"  ✓ Auto-Meta 完成，已写入 {meta_file}")
    return (ref_filename, str(ref_dir))


def run_pipeline(
    screenshot_path: str,
    instruction: str,
    output_dir: str,
    api_key: str,
    api_url: str = 'https://api.openai-next.com/v1/chat/completions',
    structure_model: str = 'qwen-vl-max',
    fonts_dir: str = None,
    gt_dir: str = None,
    vlm_api_url: str = 'https://api.openai-next.com/v1/chat/completions',
    vlm_model: str = 'demo',
    reference_path: str = None,
    reference_icon_path: str = None,
    omni_device: str = None,
    visualize: bool = True,
    anomaly_mode: str = 'dialog',
    target_component: str = None,
    gt_category: str = None,
    gt_sample: str = None,
    image_model: str = None,
    edit_plan_path: str = None,
    e2e_full_image: bool = False,
) -> dict:
    """
    执行异常场景生成流程

    Args:
        screenshot_path: 原始截图路径
        instruction: 异常指令
        output_dir: 输出目录（所有中间结果都保存在此）
        api_key: VLM API 密钥
        api_url: VLM API 端点
        structure_model: 结构提取/语义分组模型
        fonts_dir: 字体目录（可选，不指定则使用系统默认字体）
        gt_dir: GT样本目录
        vlm_api_url: VLM API 端点（语义弹窗）
        vlm_model: VLM 模型（语义弹窗）
        reference_path: 参考弹窗图片路径（dialog 模式）
        reference_icon_path: 参考加载图标路径（area_loading 模式）
        omni_device: OmniParser 运行设备
        visualize: 是否保存 OmniParser 检测结果可视化图片（默认 True）
        anomaly_mode: 异常模式 (dialog=全屏弹窗, area_loading=区域加载图标,
                               content_duplicate=内容重复, text_overlay=局部文字编辑,
                               modify_text=像素级文字替换, modify_text_e2e=端到端全图编辑)
        target_component: 目标组件ID（仅area_loading模式使用）
        gt_category: GT模板类别（如"弹窗覆盖原UI"），启用meta驱动生成
        gt_sample: GT模板样本名（如"弹出广告.jpg"），与gt_category配合使用
        image_model: 图像生成模型选择 ('gen'=纯文生图, 'edit'=图像编辑, None=自动选择)
        edit_plan_path: 文本覆盖模式下的自定义 edit_plan JSON（跳过 VLM 规划）
        e2e_full_image: modify_text_e2e 模式下是否强制整图编辑（默认 False=粗裁剪区域编辑）

    Returns:
        包含所有输出路径的字典

    Note:
        - dialog 模式：使用 semantic_ai 渲染模式（DashScope AI 图像生成）
        - area_loading 模式：在指定区域中心覆盖加载图标
        - AI 图像生成 API Key 从环境变量 DASHSCOPE_API_KEY 获取
        - 当指定 gt_category 和 gt_sample 时，启用 meta.json 驱动的精准语义生成
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    screenshot_name = Path(screenshot_path).stem
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 结果收集
    results = {
        'timestamp': timestamp,
        'screenshot': screenshot_path,
        'instruction': instruction,
        'outputs': {},
        'timing': {}
    }

    pipeline_start = time.time()

    print("=" * 60)
    print("UI 异常场景生成流水线（简化模式）")
    print("=" * 60)
    print(f"  截图: {screenshot_path}")
    print(f"  指令: {instruction}")
    print(f"  输出目录: {output_dir}")

    skip_detection_modes = {'modify_text_e2e'}
    skip_detection = anomaly_mode in skip_detection_modes
    stage1_path = None
    stage2_path = None

    if skip_detection:
        print("\n" + "=" * 60)
        print("[Stage 1/3] OmniParser 粗检测")
        print("=" * 60)
        print("  ℹ 当前模式为端到端全图编辑，跳过 Stage 1 检测")
        results['timing']['stage1'] = 0.0
        print("  ⏱ Stage 1 耗时: 0.00s")

        print("\n" + "=" * 60)
        print("[Stage 2/3] VLM 语义分组（原图 + 坐标文本 → 分组 → 代码合并）")
        print("=" * 60)
        print("  ℹ 当前模式为端到端全图编辑，跳过 Stage 2 分组")
        ui_json = {
            'metadata': {
                'source': Path(screenshot_path).name,
                'extractionMethod': 'Skipped_For_E2E_Image_Edit',
                'processing': {
                    'omni_raw_count': 0,
                    'final_count': 0,
                    'merge_log': [],
                },
            },
            'components': [],
            'componentCount': 0,
            '_stage2_status': 'skipped',
        }
        results['stage2_status'] = 'skipped'
        results['timing']['stage2'] = 0.0
        print("  ⏱ Stage 2 耗时: 0.00s")
    else:
        # ===== Stage 1: OmniParser 粗检测 =====
        stage1_start = time.time()
        print("\n" + "=" * 60)
        print("[Stage 1/3] OmniParser 粗检测")
        print("=" * 60)

        if not OMNIPARSER_AVAILABLE:
            print("[ERROR] OmniParser 不可用，请确保已正确安装")
            print("  安装方法: cd third_party/OmniParser && pip install -r requirements.txt")
            raise ImportError("OmniParser 不可用")

        print(f"  模型: YOLO + PaddleOCR + Florence2")
        print(f"  设备: {omni_device or 'auto'}")
        print(f"  可视化: {'开启' if visualize else '关闭'}")

        # 先用 OmniParser 单独检测，保存原始结果
        omni_raw_result = omni_to_ui_json(
            image_path=screenshot_path,
            device=omni_device,
            return_annotated_image=visualize
        )

        # 保存 Stage 1 结果
        stage1_path = output_dir / f"{screenshot_name}_stage1_omni_raw_{timestamp}.json"
        with open(stage1_path, 'w', encoding='utf-8') as f:
            # 保存时排除 annotated_image
            save_data = {k: v for k, v in omni_raw_result.items() if k != 'annotated_image'}
            json.dump(save_data, f, ensure_ascii=False, indent=2)
        results['outputs']['stage1_omni_raw'] = str(stage1_path)

        # 保存可视化图片
        if visualize and omni_raw_result.get('annotated_image'):
            stage1_vis_path = output_dir / f"{screenshot_name}_stage1_annotated_{timestamp}.png"
            omni_raw_result['annotated_image'].save(stage1_vis_path)
            results['outputs']['stage1_annotated'] = str(stage1_vis_path)
            print(f"  ✓ 可视化图片: {stage1_vis_path}")

        print(f"  ✓ 检测到 {omni_raw_result['componentCount']} 个组件")

        # ===== Schema验证层（可选，失败时回退到原始dict）=====
        omni_result_validated, schema_used = _validate_stage1_with_fallback(omni_raw_result)
        if schema_used:
            print(f"  ✓ Stage 1 Schema验证通过 (检测到 {omni_result_validated.total_count} 个组件)")
        else:
            print(f"  ⚠ Stage 1 使用旧格式数据")

        print(f"  ✓ 保存至: {stage1_path}")

        stage1_elapsed = time.time() - stage1_start
        results['timing']['stage1'] = round(stage1_elapsed, 2)
        print(f"  ⏱ Stage 1 耗时: {stage1_elapsed:.2f}s")

        # ===== Stage 2: VLM 语义分组（单次调用） =====
        stage2_start = time.time()
        print("\n" + "=" * 60)
        print("[Stage 2/3] VLM 语义分组（原图 + 坐标文本 → 分组 → 代码合并）")
        print("=" * 60)
        print(f"  模型: {structure_model}")

        # 调用融合函数（传入 Stage 1 的检测结果，避免重复检测）
        ui_json = omni_vlm_fusion(
            image_path=screenshot_path,
            api_key=api_key,
            api_url=api_url,
            vlm_model=structure_model,
            omni_device=omni_device,
            omni_components=omni_raw_result['components'],
            output_dir=str(output_dir)
        )

        # ===== Schema验证层（可选，失败时回退到原始dict）=====
        ui_json_validated, schema_used = _validate_stage2_with_fallback(ui_json)
        if schema_used:
            print(f"  ✓ Stage 2 Schema验证通过 (v{ui_json_validated.vlm_model})")
        else:
            print(f"  ⚠ Stage 2 使用旧格式数据")

        # 保存 Stage 2 结果
        stage2_path = output_dir / f"{screenshot_name}_stage2_filtered_{timestamp}.json"
        with open(stage2_path, 'w', encoding='utf-8') as f:
            json.dump(ui_json, f, ensure_ascii=False, indent=2)
        results['outputs']['stage2_filtered'] = str(stage2_path)

        processing_info = ui_json.get('metadata', {}).get('processing', {})
        print(f"  ✓ 原始检测: {processing_info.get('omni_raw_count', 'N/A')} 个组件")
        print(f"  ✓ 过滤后: {ui_json['componentCount']} 个组件")
        print(f"  ✓ 保存至: {stage2_path}")

        # 记录 Stage 2 状态（健壮性修复 Step 3.6）
        stage2_status = ui_json.get('_stage2_status', 'unknown')
        results['stage2_status'] = stage2_status
        if stage2_status == 'fallback':
            warn_msg = f"VLM 语义分组失败，使用 OmniParser 原始结果: {ui_json.get('_stage2_error', '')}"
            print(f"  [WARN] {warn_msg}")
            results.setdefault('warnings', []).append({
                'type': 'stage2_fallback',
                'error': ui_json.get('_stage2_error', ''),
                'message': warn_msg,
            })

        # 保存 Stage 2 可视化图片
        if visualize:
            stage2_vis_path = output_dir / f"{screenshot_name}_stage2_annotated_{timestamp}.png"
            visualize_components(
                screenshot_path=screenshot_path,
                ui_json=ui_json,
                output_path=str(stage2_vis_path)
            )
            results['outputs']['stage2_annotated'] = str(stage2_vis_path)
            print(f"  ✓ 可视化图片: {stage2_vis_path}")

        stage2_elapsed = time.time() - stage2_start
        results['timing']['stage2'] = round(stage2_elapsed, 2)
        print(f"  ⏱ Stage 2 耗时: {stage2_elapsed:.2f}s")

    # ===== Auto-Meta: 自动为任意参考图生成 meta.json =====
    if reference_path and gt_category and anomaly_mode == 'dialog':
        if not gt_sample:
            # 用户只提供了 --reference + --gt-category，自动生成 meta
            gt_sample, gt_dir = ensure_meta_for_reference(
                reference_path=reference_path,
                gt_category=gt_category,
                api_key=api_key,
                api_url=api_url,
                vlm_model=vlm_model or structure_model,
            )
        elif not gt_dir:
            # 有 gt_sample 但没 gt_dir，也检查参考图目录是否需要生成 meta
            ref_dir = str(Path(reference_path).resolve().parent)
            meta_file = Path(ref_dir) / 'meta.json'
            if not meta_file.exists():
                gt_sample, gt_dir = ensure_meta_for_reference(
                    reference_path=reference_path,
                    gt_category=gt_category,
                    api_key=api_key,
                    api_url=api_url,
                    vlm_model=vlm_model or structure_model,
                )

    # ===== Stage 3: 异常渲染（RENDERER_MAP 统一路由） =====
    stage3_start = time.time()
    print("\n" + "=" * 60)
    print(f"[Stage 3/3] 异常渲染 ({anomaly_mode} 模式)")
    print("=" * 60)
    print(f"  异常指令: {instruction}")

    try:
        from app.renderers.base import RenderResult
        from app.renderers.area_loading import AreaLoadingRenderer
        from app.renderers.content_duplicate import ContentDuplicateRenderer
        from app.renderers.text_overlay import TextOverlayRenderer
        from app.renderers.patch import PatchRenderer
        from PIL import Image

        RENDERER_MAP = {
            'dialog':            PatchRenderer,
            'area_loading':      AreaLoadingRenderer,
            'content_duplicate': ContentDuplicateRenderer,
            'text_overlay':      TextOverlayRenderer,
            'modify_text':       TextOverlayRenderer,
            'modify_text_ai':    TextOverlayRenderer,
            'modify_text_ocr':   TextOverlayRenderer,
            'modify_text_e2e':   TextOverlayRenderer,
        }

        if anomaly_mode not in RENDERER_MAP:
            print(f"  ✗ 不支持的 anomaly_mode: {anomaly_mode}")
            print(f"  支持的模式: {list(RENDERER_MAP.keys())}")
            return results

        renderer_cls = RENDERER_MAP[anomaly_mode]

        # 构造各渲染器通用初始化参数
        if anomaly_mode == 'area_loading':
            renderer = renderer_cls(
                api_key=api_key,
                vlm_api_url=vlm_api_url,
                vlm_model=vlm_model,
            )
        elif anomaly_mode == 'content_duplicate':
            renderer = renderer_cls(
                api_key=api_key,
                vlm_api_url=vlm_api_url,
                vlm_model=vlm_model,
                fonts_dir=fonts_dir,
            )
        elif anomaly_mode in ('text_overlay', 'modify_text', 'modify_text_ai', 'modify_text_ocr', 'modify_text_e2e'):
            renderer = renderer_cls(
                api_key=api_key,
                vlm_api_url=vlm_api_url,
                vlm_model=vlm_model,
                fonts_dir=fonts_dir,
            )
        else:  # dialog
            renderer = renderer_cls(
                api_key=api_key,
                vlm_api_url=vlm_api_url,
                vlm_model=vlm_model,
                fonts_dir=fonts_dir,
            )

        # 读取截图 PIL 对象
        screenshot_img = Image.open(screenshot_path)

        # 构造各模式专有 kwargs
        extra_kwargs = {'screenshot_path': screenshot_path}
        if anomaly_mode == 'area_loading':
            extra_kwargs['anomaly_type'] = _parse_anomaly_type(instruction)
            if target_component:
                component = _find_component_by_id(ui_json, target_component)
                if not component:
                    component = _smart_select_component(ui_json, instruction)
                extra_kwargs['component'] = component
        elif anomaly_mode == 'content_duplicate':
            meta_features_cd = {}
            if gt_category and gt_sample and gt_dir:
                from app.utils.meta_loader import MetaLoader
                meta_loader_cd = MetaLoader(gt_dir)
                meta_features_cd = meta_loader_cd.extract_visual_features_dict(gt_category, gt_sample) or {}
            extra_kwargs['meta_features'] = meta_features_cd
            extra_kwargs['mode'] = 'expanded_view'
            if reference_path:
                extra_kwargs['reference_path'] = reference_path
        elif anomaly_mode in ('text_overlay', 'modify_text', 'modify_text_ai', 'modify_text_ocr', 'modify_text_e2e'):
            if edit_plan_path:
                edit_plan_ops = _load_edit_plan(edit_plan_path)
                if edit_plan_ops:
                    extra_kwargs['edit_plan'] = edit_plan_ops
            if anomaly_mode == 'modify_text_ai':
                extra_kwargs['mode'] = 'modify_text_ai'
            elif anomaly_mode == 'modify_text_e2e':
                extra_kwargs['mode'] = 'modify_text_e2e'
                extra_kwargs['e2e_full_image'] = bool(e2e_full_image)
            elif anomaly_mode in ('modify_text_ocr', 'modify_text'):
                extra_kwargs['mode'] = 'modify_text_ocr'
        elif anomaly_mode == 'dialog':
            extra_kwargs['gt_category'] = gt_category
            extra_kwargs['gt_sample'] = gt_sample
            extra_kwargs['gt_dir'] = gt_dir
            extra_kwargs['reference_path'] = reference_path
            extra_kwargs['image_model'] = image_model

        # 统一调用
        render_result: RenderResult = renderer.render(
            screenshot=screenshot_img,
            ui_json=ui_json,
            instruction=instruction,
            output_dir=str(output_dir),
            **extra_kwargs,
        )

        # 统一读取结果
        final_output = render_result.output_path
        results['outputs']['final_image'] = final_output
        results['outputs']['meta_driven'] = (anomaly_mode == 'dialog')

        # 写入渲染元数据（告警等）
        if render_result.metadata:
            results.setdefault('render_metadata', {}).update(render_result.metadata)
            if render_result.metadata.get('warnings'):
                results.setdefault('warnings', []).extend(render_result.metadata['warnings'])

        print(f"  ✓ 渲染完成！保存至: {final_output}")

    except Exception as e:
        print(f"  ✗ Stage 3 渲染失败: {e}")
        import traceback
        traceback.print_exc()
        return results

    stage3_elapsed = time.time() - stage3_start
    results['timing']['stage3'] = round(stage3_elapsed, 2)
    print(f"  ⏱ Stage 3 耗时: {stage3_elapsed:.2f}s")

    # ===== 保存流水线元数据 =====
    meta_path = output_dir / f"{screenshot_name}_pipeline_meta_{timestamp}.json"
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    results['outputs']['pipeline_meta'] = str(meta_path)

    pipeline_elapsed = time.time() - pipeline_start
    results['timing']['total'] = round(pipeline_elapsed, 2)

    print("\n" + "=" * 60)
    print("✓ 流水线执行完成!")
    print("=" * 60)
    print("\n⏱ 耗时统计:")
    print(f"  [Stage 1]  OmniParser 粗检测:   {results['timing'].get('stage1', 0):.2f}s")
    print(f"  [Stage 2]  VLM 语义分组:        {results['timing'].get('stage2', 0):.2f}s")
    print(f"  [Stage 3]  异常渲染:            {results['timing'].get('stage3', 0):.2f}s")
    print(f"  [总计]     全流程耗时:          {pipeline_elapsed:.2f}s")
    print("\n中间结果:")
    if stage1_path:
        print(f"  [Stage 1]  OmniParser 原始检测: {stage1_path}")
        if visualize and results['outputs'].get('stage1_annotated'):
            print(f"  [Stage 1]  检测可视化:         {results['outputs']['stage1_annotated']}")
    else:
        print("  [Stage 1]  OmniParser 原始检测: (已跳过)")
    if stage2_path:
        print(f"  [Stage 2]  VLM 语义分组结果:   {stage2_path}")
        if visualize and results['outputs'].get('stage2_annotated'):
            print(f"  [Stage 2]  整合后可视化:       {results['outputs']['stage2_annotated']}")
    else:
        print("  [Stage 2]  VLM 语义分组结果:   (已跳过)")
    print(f"  [Stage 3]  最终异常截图:       {final_output}")
    print(f"  [Meta]     流水线元数据:       {meta_path}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description='UI 异常场景生成流水线（简化模式）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:

  # 弹窗模式（默认）
  python run_pipeline.py \\
    --screenshot ./page.png \\
    --instruction "模拟网络超时弹窗" \\
    --output ./output/

  # Meta驱动精准生成（推荐！基于GT模板的语义描述）
  python run_pipeline.py \\
    --screenshot ./page.png \\
    --instruction "生成优惠券广告弹窗" \\
    --gt-dir "./data/Agent执行遇到的典型异常UI类型/analysis/gt_templates" \\
    --gt-category "弹窗覆盖原UI" \\
    --gt-sample "弹出广告.jpg" \\
    --output ./output/

  # Meta驱动 + 参考图片
  python run_pipeline.py \\
    --screenshot ./page.png \\
    --instruction "生成权限请求弹窗" \\
    --gt-dir "./data/Agent执行遇到的典型异常UI类型/analysis/gt_templates" \\
    --gt-category "弹窗覆盖原UI" \\
    --gt-sample "关闭按钮干扰.jpg" \\
    --reference "./data/.../关闭按钮干扰.jpg" \\
    --output ./output/

  # 区域加载模式
  python run_pipeline.py \\
    --screenshot ./page.png \\
    --instruction "模拟列表加载超时" \\
    --anomaly-mode area_loading \\
    --output ./output/

  # 区域加载模式（指定目标组件）
  python run_pipeline.py \\
    --screenshot ./page.png \\
    --instruction "模拟图片加载失败" \\
    --anomaly-mode area_loading \\
    --target-component 5 \\
    --output ./output/

  # 文字覆盖编辑模式（局部精确修改，区域外像素不变）
  python run_pipeline.py \\
    --screenshot ./携程旅行01.jpg \\
    --instruction "在租车服务卡片中插入优惠信息：订阅该服务，机票满500减200元" \\
    --anomaly-mode text_overlay \\
    --output ./output/

  # Modify Text 模式（指定像素区域进行文字替换）
  python run_pipeline.py \\
    --screenshot ./page.png \\
    --instruction "把右上角价格更新为￥299" \\
    --anomaly-mode modify_text \\
    --output ./output/

Meta驱动生成说明:
  - 使用 --gt-category 和 --gt-sample 指定GT模板（传统方式）
  - 或使用 --reference + --gt-category 传入任意参考图（自动生成 meta.json）
  - 系统会从 meta.json 读取精确的语义描述和视觉特征
  - 结合参考图片的风格，生成更一致、更真实的异常弹窗

Auto-Meta 模式示例（推荐！无需预先生成 meta.json）:
  python run_pipeline.py \\
    --screenshot ./page.png \\
    --instruction "生成优惠券广告弹窗" \\
    --gt-category "弹窗覆盖原UI" \\
    --reference /path/to/any_popup.jpg \\
    --output ./output/

中间结果说明:
  - stage1_omni_raw_*.json   : OmniParser 原始检测结果
  - stage2_filtered_*.json   : VLM 语义分组后的 UI-JSON
  - final_*.png              : 最终异常场景截图
  - pipeline_meta_*.json     : 流水线元数据
"""
    )
    parser.add_argument('--screenshot', '-s', required=True,
                        help='原始截图路径')
    parser.add_argument('--instruction', '-i', required=True,
                        help='异常指令（如："模拟网络超时弹窗"）')
    parser.add_argument('--output', '-o', default='./output',
                        help='输出目录')
    parser.add_argument('--api-key', default=VLM_API_KEY,
                        help='VLM API 密钥 (或设置 VLM_API_KEY 环境变量)')
    parser.add_argument('--api-url', default=VLM_API_URL,
                        help='VLM API 端点')
    parser.add_argument('--structure-model', default=STRUCTURE_MODEL,
                        help='结构提取/语义分组模型')
    parser.add_argument('--fonts-dir',
                        help='字体目录（可选，不指定则使用系统默认字体）')
    parser.add_argument('--gt-dir',
                        help='GT样本目录')
    parser.add_argument('--vlm-api-url', default=VLM_API_URL,
                        help='VLM API 端点（语义弹窗）')
    parser.add_argument('--vlm-model', default=VLM_MODEL,
                        help='VLM 模型（语义弹窗）')
    parser.add_argument('--reference', '-r',
                        help='参考异常图片路径（任意位置均可，系统会自动生成 meta.json）')
    parser.add_argument('--reference-icon',
                        help='参考加载图标路径 (area_loading 模式，可显著提升生成真实性)')
    parser.add_argument('--omni-device',
                        help='OmniParser 设备 (cuda/cpu)')
    parser.add_argument('--no-visualize', action='store_true',
                        help='禁用 OmniParser 检测结果可视化')
    parser.add_argument('--anomaly-mode', choices=['dialog', 'area_loading', 'content_duplicate', 'text_overlay', 'modify_text', 'modify_text_ai', 'modify_text_ocr', 'modify_text_e2e'],
                        default='dialog',
                        help='异常模式: dialog=全屏弹窗(默认), area_loading=区域加载图标, content_duplicate=内容重复, text_overlay=局部文字编辑, modify_text=OCR精定位文字替换(同modify_text_ocr), modify_text_ai=AI图像编辑文字替换, modify_text_ocr=OCR精定位+PIL渲染文字替换, modify_text_e2e=端到端全图AI编辑(跳过检测分组)')
    parser.add_argument('--target-component',
                        help='目标组件ID (仅 area_loading 模式使用)')
    parser.add_argument('--gt-category',
                        help='GT模板类别，如"弹窗覆盖原UI"（启用meta驱动精准生成）')
    parser.add_argument('--gt-sample',
                        help='GT模板样本名，如"弹出广告.jpg"（与--gt-category配合使用）')
# --image-model 参数已废弃 - 现在全部使用本地服务
#     parser.add_argument('--image-model', choices=['auto', 'edit', 'gen'],
    parser.add_argument('--edit-plan',
                        help='文本覆盖/modify_text 模式使用的 Edit Plan JSON（跳过 VLM 规划）')
    parser.add_argument('--e2e-full-image', action='store_true',
                        help='modify_text_e2e 模式下启用整图端到端编辑（默认关闭，默认使用指令驱动粗裁剪）')

    args = parser.parse_args()

    # 如果指定了 gt-category 和 gt-sample 但没有指定 gt-dir，自动使用默认路径
    if args.gt_category and args.gt_sample and not args.gt_dir:
        # 使用 config.py 中的配置
        try:
            from app.core.config import get_config
            config = get_config()
            default_gt_dir = config.GT_TEMPLATES_DIR
        except Exception:
            # 降级：使用硬编码路径（兼容旧数据结构）
            default_gt_dir = Path(__file__).parent.parent.parent / 'data' / 'gt-category'
        
        if default_gt_dir.exists():
            args.gt_dir = str(default_gt_dir)
            print(f"  ✓ 自动使用默认 GT 目录: {args.gt_dir}")
        else:
            print(f"  ⚠ 默认 GT 目录不存在: {default_gt_dir}")
            print(f"  请通过 --gt-dir 手动指定")

    # 新流程：--reference + --gt-category（无需 --gt-sample），gt_sample 从 reference 文件名推断
    if args.reference and args.gt_category and not args.gt_sample:
        print(f"  ✓ Auto-Meta 模式: 参考图 → {args.reference}")
        # gt_sample 和 gt_dir 将在 run_pipeline 内由 ensure_meta_for_reference 自动设置

    # 检查必需的API密钥
    if not args.api_key:
        print("[ERROR] 未设置 VLM_API_KEY 环境变量，请配置 .env 文件")
        print("  参考: .env.example")
        return

    run_pipeline(
        screenshot_path=args.screenshot,
        instruction=args.instruction,
        output_dir=args.output,
        api_key=args.api_key,
        api_url=args.api_url,
        structure_model=args.structure_model,
        fonts_dir=args.fonts_dir,
        gt_dir=args.gt_dir,
        vlm_api_url=args.vlm_api_url,
        vlm_model=args.vlm_model,
        reference_path=args.reference,
        reference_icon_path=args.reference_icon,
        omni_device=args.omni_device,
        visualize=not args.no_visualize,
        anomaly_mode=args.anomaly_mode,
        target_component=args.target_component,
        gt_category=args.gt_category,
        gt_sample=args.gt_sample,
        # image_model 已废弃 - 现在全部使用本地服务
        # image_model=args.image_model if args.image_model != 'auto' else None,
        edit_plan_path=args.edit_plan,
        e2e_full_image=args.e2e_full_image,
    )


if __name__ == '__main__':
    main()
