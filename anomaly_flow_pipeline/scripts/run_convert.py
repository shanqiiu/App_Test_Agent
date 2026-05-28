#!/usr/bin/env python3
"""
run_convert.py — 将修改后的 utg_info.json 智能合并到 Flow 模板 CLI 入口

支持：
- targetPage (screenKey) 语义映射
- mockInstances 数据绑定
- 三种合并模式: replace / fill / smart

用法:
    # replace 模式（完全替换 steps）
    python -m anomaly_flow_pipeline.scripts.run_convert \\
        --utg /tmp/modified_utg.json \\
        --template example_data/shopping-flow-search-and-buy_new.json \\
        --output /tmp/flow.json

    # smart 模式（智能合并，推荐）
    python -m anomaly_flow_pipeline.scripts.run_convert \\
        --utg /tmp/modified_utg.json \\
        --template example_data/shopping-flow-search-and-buy_new.json \\
        --output /tmp/flow.json --mode smart --screen-key

链式:
    python -m anomaly_flow_pipeline.scripts.run_inject \\
        --utg tmp/utg.json --scenario "..." --output /tmp/modified.json

    python -m anomaly_flow_pipeline.scripts.run_convert \\
        --utg /tmp/modified.json \\
        --template example_data/shopping-flow-search-and-buy_new.json \\
        --output /tmp/flow.json --mode smart --screen-key
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# 将项目根目录加入 sys.path
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    from dotenv import load_dotenv
    for p in [_project_root / ".env", _project_root.parent / ".env"]:
        if p.exists():
            load_dotenv(p)
except ImportError:
    pass

from anomaly_flow_pipeline.core.flow_converter import FlowConverter


def main():
    parser = argparse.ArgumentParser(description="UTG → Flow 智能转换")
    parser.add_argument("--utg", required=True, help="修改后的 utg_info.json 路径")
    parser.add_argument("--template", required=True, help="Flow 模板 JSON 路径（推荐 _new.json）")
    parser.add_argument("--output", "-o", required=True, help="输出路径")
    parser.add_argument("--mode", choices=["replace", "fill", "smart"], default="smart",
                        help="合并模式: replace(完全替换), fill(按序填充), smart(智能合并,默认)")
    parser.add_argument("--screen-key", action="store_true", default=True,
                        help="分配 targetPage (screenKey)")
    parser.add_argument("--no-screen-key", action="store_false", dest="screen_key",
                        help="不分配 targetPage")
    parser.add_argument("--data-binding", action="store_true", default=True,
                        help="启用 mockInstances 数据绑定")
    parser.add_argument("--no-data-binding", action="store_false", dest="data_binding",
                        help="禁用数据绑定")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s", stream=sys.stdout)

    for name, path in [("UTG", args.utg), ("模板", args.template)]:
        if not Path(path).exists():
            print(f"❌ {name} 文件不存在: {path}")
            sys.exit(1)

    print("=" * 60)
    print("UTG → Flow 智能转换 (Phase 2)")
    print("=" * 60)
    print(f"  UTG:      {args.utg}")
    print(f"  模板:     {args.template}")
    print(f"  输出:     {args.output}")
    print(f"  模式:     {args.mode}")
    print(f"  targetPage: {'✓' if args.screen_key else '✗'}")
    print(f"  数据绑定:  {'✓' if args.data_binding else '✗'}")
    print()

    converter = FlowConverter()
    result = converter.convert(
        utg_path=args.utg,
        template_path=args.template,
        output_path=args.output,
        mode=args.mode,
        enable_screen_key=args.screen_key,
        enable_data_binding=args.data_binding,
    )

    if result["success"]:
        print(f"✅ 转换完成: {result['step_count']} 步")
        print(f"   输出: {result['output_path']}")
        if result.get("screen_keys_assigned") is not None:
            print(f"   targetPage: {result['screen_keys_assigned']} 步已分配")
        if result.get("bound_mock_id"):
            print(f"   数据绑定: {result['bound_mock_id']}")
        # 输出样例预览
        with open(result['output_path'], 'r', encoding='utf-8') as f:
            flow_data = json.load(f)
        steps = flow_data.get("mainFlow", {}).get("steps", [])
        if steps:
            print(f"\n  ── 步骤预览 (前3步) ──")
            for s in steps[:3]:
                tp = s.get("targetPage", "")
                action = s.get("action", "")[:80]
                print(f"  Step {s['order']}: [{tp}] {action}...")
    else:
        print(f"❌ 转换失败: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
