#!/usr/bin/env python3
"""
extract_page_spec.py — 从 utg.json 数据中抽取页面类型 Spec

三阶段流程：
  Phase 1: 提取原始页面类型（每个 utg 每个 step → LLM → 页面类型短语）
  Phase 2: 按 app 聚类归一化（LLM 聚类 → 标准 page_type 名称）
  Phase 3: 构建 Spec（生成 instruction 模板 → page_spec.json）

用法:
    # 全流程
    python extract_page_spec.py --data-dir path/to/utg_data --output-dir ./output

    # 仅 Phase 1（提取原始类型）
    python extract_page_spec.py --data-dir path/to/utg_data --output-dir ./output --skip-phase 0

    # 从已有 raw_extractions.json 恢复（跳过 Phase 1）
    python extract_page_spec.py --data-dir path/to/utg_data --output-dir ./output \
      --resume ./output/raw_extractions.json

    # 指定模型
    python extract_page_spec.py --data-dir path/to/utg_data --output-dir ./output --model gpt-4o

依赖:
    - 环境变量 VLM_API_KEY, VLM_API_URL, VLM_MODEL（或通过 .env 文件）
"""

import argparse
import importlib.util
import json
import logging
import os
import sys
from pathlib import Path

# ── 项目路径引导 ──────────────────────────────────────────
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# ── .env 加载 ────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    for p in [_project_root / ".env", _project_root.parent / ".env"]:
        if p.exists():
            load_dotenv(p)
except ImportError:
    pass

# ── 直接文件导入（绕过 app.injection.__init__）────────────
_extractor_path = (
    Path(__file__).resolve().parent.parent
    / "app" / "injection" / "page_spec_extractor.py"
)
_spec = importlib.util.spec_from_file_location(
    "page_spec_extractor", str(_extractor_path)
)
_mod = importlib.util.module_from_spec(_spec)
_mod.__package__ = "app.injection"
_spec.loader.exec_module(_mod)
PageSpecExtractor = _mod.PageSpecExtractor
run_extraction = _mod.run_extraction


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)


def main():
    parser = argparse.ArgumentParser(
        description="从 utg.json 数据中抽取页面类型 Spec",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 全流程
  %(prog)s --data-dir ../../data/utg_data --output-dir ../../outputs/page_spec

  # 跳过 Phase 1，从已有提取结果恢复
  %(prog)s --data-dir ../../data/utg_data --output-dir ../../outputs/page_spec \\
    --resume ../../outputs/page_spec/raw_extractions.json

  # 仅执行 Phase 2+3（跳过 Phase 1）
  %(prog)s --data-dir ../../data/utg_data --output-dir ../../outputs/page_spec \\
    --skip-phase 1
        """,
    )
    parser.add_argument(
        "--data-dir", required=True,
        help="utg.json / utg_info.json 数据所在目录",
    )
    parser.add_argument(
        "--output-dir", "-o", default=None,
        help="输出目录（中间产物和最终 spec 保存位置）",
    )
    parser.add_argument(
        "--resume", default=None,
        help="从 raw_extractions.json 恢复（跳过 Phase 1）",
    )
    parser.add_argument(
        "--skip-phase", type=int, default=0, choices=[0, 1, 2],
        help="跳过前 N 个阶段（1=跳过Phase1, 2=跳过Phase1+2）",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="详细日志",
    )
    parser.add_argument(
        "--api-key", default=None,
        help="VLM API Key（默认从环境变量读取）",
    )
    parser.add_argument(
        "--api-url", default=None,
        help="VLM API URL（默认从环境变量读取）",
    )
    parser.add_argument(
        "--model", default=None,
        help="VLM 模型名（默认从环境变量读取）",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"❌ 数据目录不存在: {data_dir}")
        sys.exit(1)

    if args.output_dir:
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("页面类型 Spec 抽取器")
    print("=" * 60)
    print(f"  数据目录: {data_dir}")
    print(f"  输出目录: {args.output_dir or '(当前目录)'}")
    print(f"  跳过阶段: Phase 1-{args.skip_phase}" if args.skip_phase > 0 else "  跳过: 无")
    if args.resume:
        print(f"  恢复文件: {args.resume}")
    print()

    extractor = PageSpecExtractor(
        api_key=args.api_key,
        api_url=args.api_url,
        model=args.model,
    )

    result = extractor.run(
        data_dir=str(data_dir),
        output_dir=args.output_dir,
        skip_phase=args.skip_phase,
        resume=args.resume,
    )

    page_spec = result.get("page_spec")
    if page_spec:
        categories = page_spec.get("categories", {})
        total_types = sum(
            len(cat.get("page_types", {}))
            for cat in categories.values()
        )
        print(f"\n✅ Spec 生成完成")
        print(f"  类别: {len(categories)}")
        print(f"  页面类型总数: {total_types}")

        for cat_name, cat_data in sorted(categories.items()):
            pts = cat_data.get("page_types", {})
            print(f"    {cat_name}: {len(pts)} 种页面类型")
    else:
        if "raw_extractions" in result:
            print(f"\nℹ Phase 1 完成: {len(result['raw_extractions'])} 条原始提取")
        if "normalized" in result:
            apps = result["normalized"].get("apps", {})
            total = sum(len(v) for v in apps.values())
            print(f"\nℹ Phase 2 完成: {len(apps)} 个 App, {total} 种标准页面类型")


if __name__ == "__main__":
    main()
