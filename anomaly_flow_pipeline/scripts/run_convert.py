#!/usr/bin/env python3
"""
run_convert.py — Phase 2 CLI 入口：LLM 驱动的内容填充

将注入异常后的 UTG 转换为符合 Schema 的 Flow JSON。

用法:
    python -m anomaly_flow_pipeline.scripts.run_convert \
        --utg /tmp/modified_utg.json \
        --template example_data/shopping-flow-search-and-buy_new.json \
        --output /tmp/flow.json

    python -m anomaly_flow_pipeline.scripts.run_convert \
        --utg /tmp/modified_utg.json \
        --template example_data/shopping-flow-search-and-buy_new.json \
        --output /tmp/flow.json \
        --schema schema/model-schema.json

链式:
    python -m anomaly_flow_pipeline.scripts.run_inject \
        --utg tmp/utg.json --scenario "..." --output /tmp/modified.json

    python -m anomaly_flow_pipeline.scripts.run_convert \
        --utg /tmp/modified.json \
        --template example_data/shopping-flow-search-and-buy_new.json \
        --output /tmp/flow.json
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
    parser = argparse.ArgumentParser(description="Phase 2: LLM 驱动内容填充")
    parser.add_argument("--utg", required=True, help="注入异常后的 utg_info.json 路径")
    parser.add_argument("--template", required=True, help="Flow 模板 JSON 路径")
    parser.add_argument("--output", "-o", required=True, help="输出路径")
    parser.add_argument("--schema", default=None,
                        help="model-schema.json 路径（默认 schema/model-schema.json）")
    parser.add_argument("--no-data-binding", action="store_true",
                        help="禁用实体提取（不生成 mockInstances）")
    parser.add_argument("--compress-steps", action="store_true",
                        help="合并相邻同页面步骤（LLM 驱动）")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s", stream=sys.stdout)

    for name, path in [("UTG", args.utg), ("模板", args.template)]:
        if not Path(path).exists():
            print(f"❌ {name} 文件不存在: {path}")
            sys.exit(1)

    print("=" * 60)
    print("Phase 2: LLM 驱动内容填充")
    print("=" * 60)
    print(f"  UTG:      {args.utg}")
    print(f"  模板:     {args.template}")
    print(f"  输出:     {args.output}")
    print(f"  Schema:   {args.schema or '默认'}")
    print(f"  实体提取: {'✗' if args.no_data_binding else '✓'}")
    print(f"  合并同页: {'✓' if args.compress_steps else '✗'}")
    print()

    converter = FlowConverter()
    result = converter.convert(
        utg_path=args.utg,
        template_path=args.template,
        output_path=args.output,
        schema_path=args.schema,
        enable_data_binding=not args.no_data_binding,
        compress_steps=args.compress_steps,
    )

    if result["success"]:
        print(f"✅ 转换完成: {result['step_count']} 步")
        print(f"   输出: {result['output_path']}")
        if result.get("bound_mock_id"):
            print(f"   实体: {result['bound_mock_id']}")
        # 输出样例预览
        with open(result['output_path'], 'r', encoding='utf-8') as f:
            flow_data = json.load(f)
        steps = flow_data.get("mainFlow", {}).get("steps", [])
        if steps:
            print(f"\n  ── 步骤预览 (前3步) ──")
            for s in steps[:3]:
                action = s.get("action", "")[:100]
                print(f"  Step {s['order']}: {action}...")
    else:
        print(f"❌ 转换失败: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
