#!/usr/bin/env python3
"""
run_convert.py — 将修改后的 utg_info.json 合并到 Flow 模板 CLI 入口

用法:
    # replace 模式（完全替换 steps）
    python -m anomaly_flow_pipeline.scripts.run_convert \\
        --utg /tmp/modified_utg.json \\
        --template anomaly_flow_pipeline/example_data/shopping-flow-search-and-buy.json \\
        --output /tmp/flow.json

    # fill 模式（按顺序填充）
    python -m anomaly_flow_pipeline.scripts.run_convert \\
        --utg /tmp/modified_utg.json \\
        --template path/to/template.json \\
        --output /tmp/flow.json --mode fill

链式:
    python -m anomaly_flow_pipeline.scripts.run_inject \\
        --utg tmp/utg.json --scenario "..." --output /tmp/modified.json

    python -m anomaly_flow_pipeline.scripts.run_convert \\
        --utg /tmp/modified.json \\
        --template example_data/shopping-flow-search-and-buy.json \\
        --output /tmp/flow.json
"""

import argparse
import logging
import sys
from pathlib import Path

# 将项目根目录加入 sys.path
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from anomaly_flow_pipeline.core.flow_converter import FlowConverter


def main():
    parser = argparse.ArgumentParser(description="UTG → Flow 转换")
    parser.add_argument("--utg", required=True, help="修改后的 utg_info.json 路径")
    parser.add_argument("--template", required=True, help="Flow 模板 JSON 路径")
    parser.add_argument("--output", "-o", required=True, help="输出路径")
    parser.add_argument("--mode", choices=["replace", "fill"], default="replace", help="合并模式")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s", stream=sys.stdout)

    for name, path in [("UTG", args.utg), ("模板", args.template)]:
        if not Path(path).exists():
            print(f"❌ {name} 文件不存在: {path}")
            sys.exit(1)

    print("=" * 60)
    print("UTG → Flow 转换")
    print("=" * 60)
    print(f"  UTG:   {args.utg}")
    print(f"  模板:  {args.template}")
    print(f"  输出:  {args.output}")
    print(f"  模式:  {args.mode}")
    print()

    converter = FlowConverter()
    result = converter.convert(utg_path=args.utg, template_path=args.template, output_path=args.output, mode=args.mode)

    if result["success"]:
        print(f"✅ 转换完成: {result['step_count']} 步")
        print(f"   输出: {result['output_path']}")
    else:
        print(f"❌ 转换失败: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
