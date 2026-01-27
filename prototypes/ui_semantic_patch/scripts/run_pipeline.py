#!/usr/bin/env python3
"""
run_pipeline.py - 一键执行完整流程

支持两种模式：
1. XML 模式：UIAutomator XML + 截图 → 异常截图
2. 纯截图模式：截图 → (VLM提取结构) → 异常截图
"""

import argparse
import json
from pathlib import Path
from datetime import datetime

from xml2json import xml_to_json
from img2xml import img_to_ui_json
from vlm_patch import generate_patch
from patch_renderer import PatchRenderer


def run_pipeline(
    screenshot_path: str,
    instruction: str,
    output_path: str,
    api_key: str,
    xml_path: str = None,
    api_url: str = 'https://api.openai-next.com/v1/chat/completions',
    structure_model: str = 'qwen-vl-max',
    patch_model: str = 'qwen-vl-max',
    fonts_dir: str = None,
    components_dir: str = None,
    render_mode: str = 'pil',
    image_api_url: str = 'https://api.openai-next.com/v1/images/generations',
    image_model: str = 'flux-schnell',
    gt_dir: str = None,
    save_intermediate: bool = True
) -> str:
    """
    执行完整的异常场景生成流程

    Args:
        screenshot_path: 原始截图路径
        instruction: 异常指令
        output_path: 输出路径
        api_key: VLM API 密钥
        xml_path: UIAutomator XML 文件路径（可选，不提供则用 VLM 提取）
        api_url: VLM API 端点
        structure_model: 结构提取模型（VLM，用于 img2xml）
        patch_model: Patch 生成模型（VLM，用于 vlm_patch）
        fonts_dir: 字体目录
        components_dir: 组件库目录
        render_mode: 渲染模式 ('pil' 纯算法 / 'generate' 大模型生成)
        image_api_url: 图像生成 API 端点
        image_model: 图像生成模型名称
        gt_dir: GT样本目录（用于模板匹配，优先于其他渲染方式）
        save_intermediate: 是否保存中间结果

    Returns:
        输出文件路径
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = Path(output_path).parent if Path(output_path).suffix else Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("UI Semantic Patch Pipeline")
    print("=" * 60)

    # ===== 第一阶段：结构提取 =====
    if xml_path and Path(xml_path).exists():
        # 模式1: 使用 UIAutomator XML
        print("\n[1/3] 结构提取: UIAutomator XML → UI-JSON")
        ui_json = xml_to_json(
            xml_path=xml_path,
            screenshot_path=screenshot_path
        )
    else:
        # 模式2: 使用 VLM 从截图提取
        print("\n[1/3] 结构提取: 截图 → (VLM) → UI-JSON")
        ui_json = img_to_ui_json(
            image_path=screenshot_path,
            api_key=api_key,
            api_url=api_url,
            model=structure_model
        )

    ui_json_path = output_dir / f"ui_structure_{timestamp}.json"
    if save_intermediate:
        with open(ui_json_path, 'w', encoding='utf-8') as f:
            json.dump(ui_json, f, ensure_ascii=False, indent=2)
        print(f"  ✓ UI-JSON: {ui_json_path}")
    else:
        # 临时保存供后续使用
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump(ui_json, f, ensure_ascii=False)
            ui_json_path = Path(f.name)

    print(f"  ✓ 分辨率: {ui_json['metadata']['resolution']['width']}x{ui_json['metadata']['resolution']['height']}")
    print(f"  ✓ 组件数: {ui_json['componentCount']}")

    # ===== 第二阶段：VLM 推理 =====
    print("\n[2/3] VLM 推理: 生成 JSON Patch")
    print(f"  异常指令: {instruction}")

    patch = generate_patch(
        api_key=api_key,
        api_url=api_url,
        model=patch_model,
        screenshot_path=screenshot_path,
        ui_json_path=str(ui_json_path),
        instruction=instruction
    )

    patch_path = output_dir / f"patch_{timestamp}.json"
    if save_intermediate:
        with open(patch_path, 'w', encoding='utf-8') as f:
            json.dump(patch, f, ensure_ascii=False, indent=2)
        print(f"  ✓ JSON Patch: {patch_path}")

    print(f"  ✓ 操作数: {len(patch.get('actions', []))}")
    for i, action in enumerate(patch.get('actions', [])):
        print(f"    [{i+1}] {action.get('type')}: {action.get('target', action.get('component', {}).get('class', 'N/A'))}")

    # ===== 第三阶段：像素级重绘 =====
    print("\n[3/3] 像素级重绘: 应用 Patch")
    if render_mode == 'generate':
        print(f"  渲染模式: 大模型生成 (model={image_model})")
    else:
        print(f"  渲染模式: PIL 算法")

    renderer = PatchRenderer(
        screenshot_path=screenshot_path,
        ui_json_path=str(ui_json_path),
        fonts_dir=fonts_dir,
        components_dir=components_dir,
        render_mode=render_mode,
        api_key=api_key,
        api_url=image_api_url,
        image_model=image_model,
        gt_dir=gt_dir
    )

    result = renderer.apply_patch(patch)

    # 确定输出路径
    if Path(output_path).suffix:
        final_output = output_path
    else:
        screenshot_name = Path(screenshot_path).stem
        final_output = output_dir / f"{screenshot_name}_anomaly_{timestamp}.png"

    renderer.save(str(final_output))

    print("\n" + "=" * 60)
    print(f"✓ 完成! 异常截图已保存至: {final_output}")
    print("=" * 60)

    return str(final_output)


def main():
    parser = argparse.ArgumentParser(
        description='UI Semantic Patch Pipeline - 一键生成异常场景截图',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:

  # 纯截图模式（推荐）- 无需 UIAutomator XML
  python run_pipeline.py \\
    --screenshot ./page.png \\
    --instruction "模拟网络超时弹窗" \\
    --api-key YOUR_KEY

  # XML 模式 - 如果有 UIAutomator dump
  python run_pipeline.py \\
    --xml ./page.xml \\
    --screenshot ./page.png \\
    --instruction "模拟登录失败提示" \\
    --api-key YOUR_KEY
"""
    )
    parser.add_argument('--screenshot', '-s', required=True,
                        help='原始截图路径')
    parser.add_argument('--instruction', '-i', required=True,
                        help='异常指令（如："模拟网络超时弹窗"）')
    parser.add_argument('--xml', '-x',
                        help='UIAutomator XML 文件路径（可选，不提供则用 VLM 提取结构）')
    parser.add_argument('--output', '-o', default='./output',
                        help='输出路径（文件或目录）')
    parser.add_argument('--api-key', default= "sk-K9B2ccVeW4VdAcobD53b16E06b104aA1B5A82593FdFb2557",
                        help='VLM API 密钥')
    parser.add_argument('--api-url',
                        default='https://api.openai-next.com/v1/chat/completions',
                        help='VLM API 端点')
    parser.add_argument('--structure-model',
                        default='qwen-vl-max',
                        help='结构提取模型（VLM，用于从截图识别UI组件）')
    parser.add_argument('--patch-model',
                        default='qwen-vl-max',
                        help='Patch生成模型（VLM，用于生成修改指令）')
    parser.add_argument('--fonts-dir',
                        help='字体目录')
    parser.add_argument('--components-dir',
                        help='组件库目录')
    parser.add_argument('--render-mode',
                        choices=['pil', 'generate'],
                        default='pil',
                        help='渲染模式: pil(纯算法,默认,快速) / generate(大模型生成弹窗,更真实)')
    parser.add_argument('--image-api-url',
                        default='https://api.openai-next.com/v1/images/generations',
                        help='图像生成 API 端点（render-mode=generate时使用）')
    parser.add_argument('--image-model',
                        default='flux-schnell',
                        help='图像生成模型（render-mode=generate时使用）')
    parser.add_argument('--gt-dir',
                        help='GT样本目录（用于模板匹配，优先于其他渲染方式）')
    parser.add_argument('--no-intermediate', action='store_true',
                        help='不保存中间结果')

    args = parser.parse_args()

    run_pipeline(
        screenshot_path=args.screenshot,
        instruction=args.instruction,
        output_path=args.output,
        api_key=args.api_key,
        xml_path=args.xml,
        api_url=args.api_url,
        structure_model=args.structure_model,
        patch_model=args.patch_model,
        fonts_dir=args.fonts_dir,
        components_dir=args.components_dir,
        render_mode=args.render_mode,
        image_api_url=args.image_api_url,
        image_model=args.image_model,
        gt_dir=args.gt_dir,
        save_intermediate=not args.no_intermediate
    )


if __name__ == '__main__':
    main()
