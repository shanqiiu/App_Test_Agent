#!/usr/bin/env python3
"""
run_extract_topic_data.py — 从 UTG 抽取 topics.fields 与 mockInstances 并更新模板

用法:
    python -m anomaly_flow_pipeline.scripts.run_extract_topic_data \
        --utg example_data/utg_info.json \
        --template example_data/shopping-flow-search-and-buy_new.json \
        --output example_data/shopping-flow-search-and-buy_new.json

    # 只预览抽取结果，不写文件
    python -m anomaly_flow_pipeline.scripts.run_extract_topic_data \
        --utg example_data/utg_info.json \
        --template example_data/shopping-flow-search-and-buy_new.json \
        --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

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

from anomaly_flow_pipeline.core.topic_data_extractor import UTGTopicDataExtractor


def main():
    parser = argparse.ArgumentParser(description="从 UTG 抽取 topics.fields 和 mockInstances")
    parser.add_argument("--utg", required=True, help="utg_info.json 路径")
    parser.add_argument("--template", required=True, help="待更新的模板 JSON 路径")
    parser.add_argument("--output", "-o", default=None, help="输出模板路径；不填则覆盖 --template")
    parser.add_argument("--dry-run", action="store_true", help="只打印抽取结果，不写入文件")
    parser.add_argument("--use-llm", action="store_true", help="启用 LLM 增强抽取")
    parser.add_argument("--validate", action="store_true", help="启用 LLM 验证判定")
    parser.add_argument("--model", default=None, help="VLM 模型名")
    args = parser.parse_args()

    for name, path in [("UTG", args.utg), ("模板", args.template)]:
        if not Path(path).exists():
            print(f"❌ {name} 文件不存在: {path}")
            sys.exit(1)

    extractor = UTGTopicDataExtractor(
        use_llm=args.use_llm,
        validate_with_llm=args.validate,
        model=args.model,
    )

    if args.dry_run:
        result = extractor.extract(args.utg, args.template)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    output = args.output or args.template
    result = extractor.update_template(args.utg, args.template, output)
    print("✅ 模板已更新")
    print(f"  输出: {result['output_path']}")
    print(f"  新增字段: {result['added_fields'] or '无'}")
    print(f"  更新实例: {result['updated_instance_id']}")
    print(f"  业务ID字段: {result['business_id_fields'] or '无'}")
    print(f"  验证: {'通过' if result['validation'].get('passed') else '未通过'} ({result['validation'].get('score')})")
    if result.get("warnings"):
        print(f"  警告: {result['warnings']}")
    if result["validation"].get("issues"):
        print(f"  问题: {result['validation']['issues']}")


if __name__ == "__main__":
    main()
