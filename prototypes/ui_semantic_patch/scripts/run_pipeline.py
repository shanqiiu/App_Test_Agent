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
from pathlib import Path
from datetime import datetime
from typing import Optional

# 自动加载项目根目录的 .env 文件
try:
    from dotenv import load_dotenv
    # 查找项目根目录的 .env
    env_path = Path(__file__).resolve().parents[3] / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        print(f"  ✓ 已加载环境配置: {env_path}")
except ImportError:
    pass  # python-dotenv 未安装，使用系统环境变量

# 从环境变量读取配置（必需）
VLM_API_KEY = os.environ.get('VLM_API_KEY')
VLM_API_URL = os.environ.get('VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions')
VLM_MODEL = os.environ.get('VLM_MODEL', 'gpt-4o')
STRUCTURE_MODEL = os.environ.get('STRUCTURE_MODEL', 'qwen-vl-max')

from visualize_omni import visualize_components


# ==================== 辅助函数 ====================

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
    else:
        return 'timeout'  # 默认


def _find_component_by_id(ui_json: dict, target_id: str) -> Optional[dict]:
    """根据 ID 或 index 查找组件"""
    components = ui_json.get('components', [])

    # 先按 ID 查找
    for comp in components:
        if str(comp.get('id', '')) == target_id:
            return comp

    # 再按 index 查找
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

    # 根据指令关键词匹配组件类型
    type_keywords = {
        'list': ['列表', 'list', 'listview', 'recycler'],
        'image': ['图片', 'image', 'picture', 'photo'],
        'video': ['视频', 'video', 'player'],
        'feed': ['动态', 'feed', 'timeline']
    }

    # 优先级排序
    priority_types = ['list', 'feed', 'image', 'video']

    for ptype in priority_types:
        keywords = type_keywords.get(ptype, [])
        for keyword in keywords:
            if keyword in instruction_lower:
                # 找到匹配类型，返回最大的该类型组件
                for comp in reversed(components):
                    comp_class = comp.get('class', '').lower()
                    if any(k in comp_class for k in keywords):
                        return comp

    # 如果没找到，返回最大的组件（通常是主要内容区）
    largest_comp = max(
        components,
        key=lambda c: c.get('bounds', {}).get('width', 0) * c.get('bounds', {}).get('height', 0),
        default=None
    )
    return largest_comp

# OmniParser 融合模块
try:
    from omni_vlm_fusion import omni_vlm_fusion
    from omni_extractor import omni_to_ui_json
    OMNIPARSER_AVAILABLE = True
except ImportError as e:
    print(f"[WARN] OmniParser 导入失败: {e}")
    OMNIPARSER_AVAILABLE = False


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
    vlm_model: str = 'qwen-vl-max',
    reference_path: str = None,
    reference_icon_path: str = None,
    omni_device: str = None,
    visualize: bool = True,
    anomaly_mode: str = 'dialog',
    target_component: str = None,
    gt_category: str = None,
    gt_sample: str = None
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
        anomaly_mode: 异常模式 (dialog=全屏弹窗, area_loading=区域加载图标)
        target_component: 目标组件ID（仅area_loading模式使用）
        gt_category: GT模板类别（如"弹窗覆盖原UI"），启用meta驱动生成
        gt_sample: GT模板样本名（如"弹出广告.jpg"），与gt_category配合使用

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
        'outputs': {}
    }

    print("=" * 60)
    print("UI 异常场景生成流水线（简化模式）")
    print("=" * 60)
    print(f"  截图: {screenshot_path}")
    print(f"  指令: {instruction}")
    print(f"  输出目录: {output_dir}")

    # ===== Stage 1: OmniParser 粗检测 =====
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
    print(f"  ✓ 保存至: {stage1_path}")

    # ===== Stage 2: VLM 语义分组（单次调用） =====
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

    # ===== Stage 3: 异常渲染（RENDERER_MAP 统一路由） =====
    print("\n" + "=" * 60)
    print(f"[Stage 3/3] 异常渲染 ({anomaly_mode} 模式)")
    print("=" * 60)
    print(f"  异常指令: {instruction}")

    try:
        from base_renderer import RenderResult
        from area_loading_renderer import AreaLoadingRenderer
        from content_duplicate_renderer import ContentDuplicateRenderer
        from text_overlay_renderer import TextOverlayRenderer
        from patch_renderer import PatchRenderer
        from PIL import Image

        RENDERER_MAP = {
            'dialog':            PatchRenderer,
            'area_loading':      AreaLoadingRenderer,
            'content_duplicate': ContentDuplicateRenderer,
            'text_overlay':      TextOverlayRenderer,
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
        elif anomaly_mode == 'text_overlay':
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
                from utils.meta_loader import MetaLoader
                meta_loader_cd = MetaLoader(gt_dir)
                meta_features_cd = meta_loader_cd.extract_visual_features_dict(gt_category, gt_sample) or {}
            extra_kwargs['meta_features'] = meta_features_cd
            extra_kwargs['mode'] = 'expanded_view'
            if reference_path:
                extra_kwargs['reference_path'] = reference_path
        elif anomaly_mode == 'dialog':
            extra_kwargs['gt_category'] = gt_category
            extra_kwargs['gt_sample'] = gt_sample
            extra_kwargs['gt_dir'] = gt_dir
            extra_kwargs['reference_path'] = reference_path

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
    # ===== 保存流水线元数据 =====
    meta_path = output_dir / f"{screenshot_name}_pipeline_meta_{timestamp}.json"
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    results['outputs']['pipeline_meta'] = str(meta_path)

    print("\n" + "=" * 60)
    print("✓ 流水线执行完成!")
    print("=" * 60)
    print("\n中间结果:")
    print(f"  [Stage 1]  OmniParser 原始检测: {stage1_path}")
    if visualize and results['outputs'].get('stage1_annotated'):
        print(f"  [Stage 1]  检测可视化:         {results['outputs']['stage1_annotated']}")
    print(f"  [Stage 2]  VLM 语义分组结果:   {stage2_path}")
    if visualize and results['outputs'].get('stage2_annotated'):
        print(f"  [Stage 2]  整合后可视化:       {results['outputs']['stage2_annotated']}")
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

Meta驱动生成说明:
  - 使用 --gt-category 和 --gt-sample 指定GT模板
  - 系统会从 meta.json 读取精确的语义描述和视觉特征
  - 结合参考图片的风格，生成更一致、更真实的异常弹窗
  - 比普通模式质量更高，推荐使用！

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
                        help='参考弹窗图片路径 (dialog 模式)')
    parser.add_argument('--reference-icon',
                        help='参考加载图标路径 (area_loading 模式，可显著提升生成真实性)')
    parser.add_argument('--omni-device',
                        help='OmniParser 设备 (cuda/cpu)')
    parser.add_argument('--no-visualize', action='store_true',
                        help='禁用 OmniParser 检测结果可视化')
    parser.add_argument('--anomaly-mode', choices=['dialog', 'area_loading', 'content_duplicate', 'text_overlay'],
                        default='dialog',
                        help='异常模式: dialog=全屏弹窗(默认), area_loading=区域加载图标, content_duplicate=内容重复, text_overlay=局部文字编辑')
    parser.add_argument('--target-component',
                        help='目标组件ID (仅 area_loading 模式使用)')
    parser.add_argument('--gt-category',
                        help='GT模板类别，如"弹窗覆盖原UI"（启用meta驱动精准生成）')
    parser.add_argument('--gt-sample',
                        help='GT模板样本名，如"弹出广告.jpg"（与--gt-category配合使用）')

    args = parser.parse_args()

    # 如果指定了 gt-category 和 gt-sample 但没有指定 gt-dir，自动使用默认路径
    if args.gt_category and args.gt_sample and not args.gt_dir:
        default_gt_dir = Path(__file__).parent.parent / 'data' / 'Agent执行遇到的典型异常UI类型' / 'analysis' / 'gt_templates'
        if default_gt_dir.exists():
            args.gt_dir = str(default_gt_dir)
            print(f"  ✓ 自动使用默认 GT 目录: {args.gt_dir}")
        else:
            print(f"  ⚠ 默认 GT 目录不存在: {default_gt_dir}")
            print(f"  请通过 --gt-dir 手动指定")

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
        gt_sample=args.gt_sample
    )


if __name__ == '__main__':
    main()
