#!/usr/bin/env python3
"""
apply_edit_plan.py - 直接执行 Edit Plan，跳过 OmniParser/VLM 阶段

用于已有手工或程序生成的 edit_plan JSON，无需重跑 Stage 1/2。

用法:
  python apply_edit_plan.py \
    --screenshot ../data/原图/12306无票/xxx.jpg \
    --edit-plan ./output/12306无座/edit_plan_manual_override.json \
    --output ./output/12306无座

输出:
  final_<timestamp>.png   - 修改后图像
  diff_<timestamp>.png    - 差异可视化
"""

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime

# 自动加载 .env
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parents[3] / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

VLM_API_KEY = os.environ.get('VLM_API_KEY', '')
VLM_API_URL = os.environ.get('VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions')
VLM_MODEL   = os.environ.get('VLM_MODEL', 'gpt-4o')


def load_edit_plan(plan_path: str):
    """从 JSON 文件加载 EditOp 列表"""
    from renderers.text_overlay import EditOp

    path = Path(plan_path).expanduser().resolve()
    if not path.exists():
        print(f"[ERROR] edit_plan 文件不存在: {path}")
        sys.exit(1)

    raw = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(raw, list):
        print(f"[ERROR] edit_plan JSON 须为数组")
        sys.exit(1)

    ops = []
    for i, item in enumerate(raw, 1):
        try:
            ops.append(EditOp(**item))
        except TypeError as e:
            print(f"  [WARN] 第 {i} 项字段不完整，跳过: {e}")

    if not ops:
        print("[ERROR] 未解析到有效操作")
        sys.exit(1)

    print(f"  ✓ 已加载 {len(ops)} 个操作")
    return ops


def main():
    parser = argparse.ArgumentParser(
        description='直接执行 Edit Plan，跳过 OmniParser/VLM 阶段',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python apply_edit_plan.py \\
    --screenshot ../data/原图/12306无票/微信图片_20260320112201_63_1364.jpg \\
    --edit-plan ./output/12306无座/edit_plan_manual_override.json \\
    --output ./output/12306无座
"""
    )
    parser.add_argument('--screenshot', '-s', required=True, help='原始截图路径')
    parser.add_argument('--edit-plan',  '-p', required=True, help='Edit Plan JSON 路径')
    parser.add_argument('--output',     '-o', default='./output', help='输出目录')
    parser.add_argument('--fonts-dir',  help='字体目录（可选）')
    parser.add_argument('--suffix',     default='', help='输出文件名后缀（便于区分多次运行）')
    parser.add_argument('--ui-json',    help='Stage 2 UI-JSON 路径（可选，用于 AI 图像编辑模式）')
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("apply_edit_plan — 直接执行文字编辑计划")
    print("=" * 60)
    print(f"  截图:      {args.screenshot}")
    print(f"  Edit Plan: {args.edit_plan}")
    print(f"  输出目录:  {output_dir}")

    # 加载渲染器
    from renderers.text_overlay import TextOverlayRenderer, EditOp
    from PIL import Image

    renderer = TextOverlayRenderer(
        api_key=VLM_API_KEY,
        vlm_api_url=VLM_API_URL,
        vlm_model=VLM_MODEL,
        fonts_dir=args.fonts_dir,
    )

    # 加载 edit plan
    edit_ops = load_edit_plan(args.edit_plan)
    for i, op in enumerate(edit_ops):
        r = op.region
        print(f"  [{i}] {op.action}: \"{op.content}\" @ ({r['x']},{r['y']}) {r['width']}x{r['height']}")

    # 加载 UI-JSON（如提供，用于 AI 图像编辑模式）
    ui_json = {'components': []}
    if args.ui_json:
        ui_json_path = Path(args.ui_json).expanduser().resolve()
        if ui_json_path.exists():
            ui_json = json.loads(ui_json_path.read_text(encoding='utf-8'))
            print(f"  ✓ 已加载 UI-JSON: {len(ui_json.get('components', []))} 个组件")
        else:
            print(f"  ⚠ UI-JSON 文件不存在: {ui_json_path}，使用空组件列表")

    # 执行渲染
    print("\n[执行编辑操作]")
    result_img, executed_ops = renderer.render_all(
        screenshot_path=args.screenshot,
        ui_json=ui_json,
        instruction='apply_edit_plan',
        edit_plan=edit_ops,
    )

    # 保存结果
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    suffix = f"_{args.suffix}" if args.suffix else ""
    final_path = output_dir / f"final{suffix}_{timestamp}.png"
    result_img.convert('RGB').save(str(final_path))
    print(f"\n  ✓ 修改后图像: {final_path}")

    # 保存 diff 可视化
    diff_path = output_dir / f"diff{suffix}_{timestamp}.png"
    original = Image.open(args.screenshot).convert('RGBA')
    renderer.save_diff_visualization(original, result_img, str(diff_path))
    print(f"  ✓ 差异可视化: {diff_path}")

    print("\n完成！")


if __name__ == '__main__':
    main()
