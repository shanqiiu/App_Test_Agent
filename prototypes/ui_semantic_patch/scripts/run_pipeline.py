#!/usr/bin/env python3
"""
run_pipeline.py - UI 异常场景生成流水线

采用简化的异常弹窗生成模式：
- Stage 1: OmniParser 精确检测（YOLO + PaddleOCR + Florence2）
- Stage 2: VLM 语义过滤（合并海报/卡片内的文字，清理UI结构）
- Stage 3: 直接生成异常弹窗并合并到原截图

所有中间结果均保存，便于调试和优化。
"""

import argparse
import json
import os
from pathlib import Path
from datetime import datetime

# 默认 API Key（优先使用环境变量）
# VLM_API_KEY: 用于 VLM 语义分析
# DASHSCOPE_API_KEY: 用于 DashScope AI 图像生成（在 semantic_dialog_generator.py 中使用）
DEFAULT_VLM_API_KEY = os.environ.get('VLM_API_KEY', 'sk-K9B2ccVeW4VdAcobD53b16E06b104aA1B5A82593FdFb2557')

from img2xml import img_to_ui_json
from patch_renderer import PatchRenderer
from visualize_omni import visualize_components

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
    omni_device: str = None,
    visualize: bool = True
) -> dict:
    """
    执行异常场景生成流程（简化模式）

    Args:
        screenshot_path: 原始截图路径
        instruction: 异常指令
        output_dir: 输出目录（所有中间结果都保存在此）
        api_key: VLM API 密钥
        api_url: VLM API 端点
        structure_model: 结构提取/语义过滤模型
        fonts_dir: 字体目录（可选，不指定则使用系统默认字体）
        gt_dir: GT样本目录
        vlm_api_url: VLM API 端点（语义弹窗）
        vlm_model: VLM 模型（语义弹窗）
        reference_path: 参考弹窗图片路径
        omni_device: OmniParser 运行设备
        visualize: 是否保存 OmniParser 检测结果可视化图片（默认 True）

    Returns:
        包含所有输出路径的字典

    Note:
        - 渲染模式固定为 semantic_ai（DashScope AI 图像生成）
        - AI 图像生成 API Key 从环境变量 DASHSCOPE_API_KEY 获取
        - 跳过 VLM JSON Patch 生成，直接生成弹窗覆盖
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

    # ===== Stage 2: VLM 语义过滤 =====
    print("\n" + "=" * 60)
    print("[Stage 2/3] VLM 语义过滤")
    print("=" * 60)
    print(f"  模型: {structure_model}")
    print(f"  任务: 合并海报/卡片内的文字，过滤噪声检测")

    # 调用融合函数（传入 Stage 1 的检测结果，避免重复检测）
    ui_json = omni_vlm_fusion(
        image_path=screenshot_path,
        api_key=api_key,
        api_url=api_url,
        vlm_model=structure_model,
        omni_device=omni_device,
        omni_components=omni_raw_result['components']
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

    # ===== Stage 3: 直接生成弹窗并合并 =====
    print("\n" + "=" * 60)
    print("[Stage 3/3] 异常弹窗生成与合并")
    print("=" * 60)
    print(f"  异常指令: {instruction}")
    print(f"  生成模式: semantic_ai (DashScope)")

    renderer = PatchRenderer(
        screenshot_path=screenshot_path,
        ui_json_path=str(stage2_path),
        fonts_dir=fonts_dir,
        render_mode='semantic_ai',
        api_key=api_key,
        gt_dir=gt_dir,
        vlm_api_url=vlm_api_url,
        vlm_model=vlm_model,
        reference_path=reference_path
    )

    # 直接生成弹窗并合并（不使用 JSON Patch 中间格式）
    result = renderer.generate_dialog_and_merge(
        screenshot_path=screenshot_path,
        instruction=instruction
    )

    # 保存最终结果
    final_output = output_dir / f"{screenshot_name}_final_{timestamp}.png"
    renderer.save(str(final_output))
    results['outputs']['final_image'] = str(final_output)

    print(f"  ✓ 保存至: {final_output}")

    # ===== 保存流水线元数据 =====
    meta_path = output_dir / f"{screenshot_name}_pipeline_meta_{timestamp}.json"
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    results['outputs']['pipeline_meta'] = str(meta_path)

    print("\n" + "=" * 60)
    print("✓ 流水线执行完成!")
    print("=" * 60)
    print("\n中间结果:")
    print(f"  [Stage 1] OmniParser 原始检测: {stage1_path}")
    if visualize and results['outputs'].get('stage1_annotated'):
        print(f"  [Stage 1] 检测可视化:         {results['outputs']['stage1_annotated']}")
    print(f"  [Stage 2] VLM 语义过滤结果:   {stage2_path}")
    if visualize and results['outputs'].get('stage2_annotated'):
        print(f"  [Stage 2] 过滤后可视化:       {results['outputs']['stage2_annotated']}")
    print(f"  [Stage 3] 最终异常截图:       {final_output}")
    print(f"  [Meta]    流水线元数据:       {meta_path}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description='UI 异常场景生成流水线（简化模式）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:

  python run_pipeline.py \\
    --screenshot ./page.png \\
    --instruction "模拟网络超时弹窗" \\
    --output ./output/

中间结果说明:
  - stage1_omni_raw_*.json   : OmniParser 原始检测结果
  - stage2_filtered_*.json   : VLM 语义过滤后的 UI-JSON
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
    parser.add_argument('--api-key', default=DEFAULT_VLM_API_KEY,
                        help='VLM API 密钥 (或设置 VLM_API_KEY 环境变量)')
    parser.add_argument('--api-url',
                        default='https://api.openai-next.com/v1/chat/completions',
                        help='VLM API 端点')
    parser.add_argument('--structure-model',
                        default='qwen-vl-max',
                        help='结构提取/语义过滤模型')
    parser.add_argument('--fonts-dir',
                        help='字体目录（可选，不指定则使用系统默认字体）')
    parser.add_argument('--gt-dir',
                        help='GT样本目录')
    parser.add_argument('--vlm-api-url',
                        default='https://api.openai-next.com/v1/chat/completions',
                        help='VLM API 端点（语义弹窗）')
    parser.add_argument('--vlm-model',
                        default='gpt-4o',
                        help='VLM 模型（语义弹窗）')
    parser.add_argument('--reference', '-r',
                        help='参考弹窗图片路径')
    parser.add_argument('--omni-device',
                        help='OmniParser 设备 (cuda/cpu)')
    parser.add_argument('--no-visualize', action='store_true',
                        help='禁用 OmniParser 检测结果可视化')

    args = parser.parse_args()

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
        omni_device=args.omni_device,
        visualize=not args.no_visualize
    )


if __name__ == '__main__':
    main()
