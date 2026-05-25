#!/usr/bin/env python3
"""
run_extract_spec.py — 页面类型 Spec 抽取 CLI 入口

从 utg.json 数据中抽取页面类型 Spec。

用法:
    python -m anomaly_flow_pipeline.scripts.run_extract_spec \\
        --data-dir path/to/utg_data \\
        --output-dir ./output

    # 从已有 raw_extractions.json 恢复（跳过 Phase 1）
    python -m anomaly_flow_pipeline.scripts.run_extract_spec \\
        --data-dir path/to/utg_data \\
        --output-dir ./output \\
        --resume ./output/raw_extractions.json
"""

import argparse
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

from anomaly_flow_pipeline.core.page_spec_extractor import PageSpecExtractor


def main():
    parser = argparse.ArgumentParser(description="页面类型 Spec 抽取")
    parser.add_argument("--data-dir", required=True, help="utg.json 数据目录")
    parser.add_argument("--output-dir", "-o", default=None, help="输出目录")
    parser.add_argument("--resume", default=None, help="从 raw_extractions.json 恢复")
    parser.add_argument("--skip-phase", type=int, default=0, choices=[0, 1, 2], help="跳过前 N 个阶段")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    parser.add_argument("--model", default=None, help="VLM 模型名")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s", stream=sys.stdout)

    if not Path(args.data_dir).exists():
        print(f"❌ 数据目录不存在: {args.data_dir}")
        sys.exit(1)

    if args.output_dir:
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    extractor = PageSpecExtractor(model=args.model)
    result = extractor.run(data_dir=args.data_dir, output_dir=args.output_dir, skip_phase=args.skip_phase, resume=args.resume)

    page_spec = result.get("page_spec")
    if page_spec:
        categories = page_spec.get("categories", {})
        total = sum(len(cat.get("page_types", {})) for cat in categories.values())
        print(f"\n✅ Spec 生成完成: {len(categories)} 类别, {total} 种页面类型")
    elif "raw_extractions" in result:
        print(f"\nℹ Phase 1 完成: {len(result['raw_extractions'])} 条原始提取")


if __name__ == "__main__":
    main()
