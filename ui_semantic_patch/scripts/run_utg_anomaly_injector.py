#!/usr/bin/env python3
"""
run_utg_anomaly_injector.py — UTG 异常注入独立入口

基于输入的异常场景文本描述 + utg_info.json：
1. LLM 决策在序列的哪一步注入该异常
2. LLM 改写该步的 ui_summary 描述
3. 输出修改后的 utg_info.json

用法:
    # 基本用法（输出到终端）
    python run_utg_anomaly_injector.py \\
        --utg ../../tmp/utg.json \\
        --scenario "搜索列表加载失败，显示网络错误提示"

    # 指定输出文件
    python run_utg_anomaly_injector.py \\
        --utg ../../tmp/utg.json \\
        --scenario "商品详情页价格显示异常，所有价格显示为'加载中'" \\
        --output ../../outputs/anomaly_injected/utg_info.json

    # 详细日志
    python run_utg_anomaly_injector.py --utg ... --scenario "..." --verbose

    # 指定模型
    python run_utg_anomaly_injector.py --utg ... --scenario "..." --model gpt-4o

依赖:
    - 环境变量 VLM_API_KEY, VLM_API_URL, VLM_MODEL（或通过 .env 文件）
    - app.injection.utg_anomaly_injector
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

# ── 直接文件导入（绕过 app.injection.__init__ 的级联导入）──
_injector_path = (
    Path(__file__).resolve().parent.parent
    / "app" / "injection" / "utg_anomaly_injector.py"
)
_spec = importlib.util.spec_from_file_location(
    "utg_anomaly_injector", str(_injector_path)
)
_injector_mod = importlib.util.module_from_spec(_spec)
_injector_mod.__package__ = "app.injection"  # 保持包上下文
_spec.loader.exec_module(_injector_mod)
UTGAnomalyInjector = _injector_mod.UTGAnomalyInjector
run_anomaly_inject = _injector_mod.run_anomaly_inject


def setup_logging(verbose: bool = False):
    """配置日志"""
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter('[%(levelname)s] %(message)s')
    )
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)


def main():
    parser = argparse.ArgumentParser(
        description="UTG 异常注入 — 决策注入步 + 改写 ui_summary",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  %(prog)s --utg ../../tmp/utg.json --scenario \"加载失败\"\n"
            "  %(prog)s --utg ../../tmp/utg.json --scenario \"价格异常\" --output result.json\n"
            "  %(prog)s --utg ../../tmp/utg.json --scenario \"按钮不可点击\" --verbose\n"
        ),
    )
    parser.add_argument(
        "--utg", required=True,
        help="utg_info.json 文件路径",
    )
    parser.add_argument(
        "--scenario", required=True,
        help="异常场景文本描述，例如 '搜索列表加载失败，显示空白占位'",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="输出文件路径（可选，不指定则仅终端显示）",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="详细日志输出",
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
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Dry-run 模式：只决策注入步，不改写 ui_summary（快速验证）",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    # 验证输入文件
    utg_path = Path(args.utg)
    if not utg_path.exists():
        print(f"❌ 文件不存在: {utg_path}")
        sys.exit(1)

    print("=" * 60)
    print("UTG 异常注入器")
    print("=" * 60)
    print(f"  UTG:      {utg_path}")
    print(f"  场景:     {args.scenario[:60]}{'...' if len(args.scenario) > 60 else ''}")
    print(f"  输出:     {args.output or '(终端显示)'}")
    print(f"  模式:     {'Dry-Run (仅决策)' if args.dry_run else '完整流程'}")
    print()

    # 执行注入
    injector = UTGAnomalyInjector(
        api_key=args.api_key,
        api_url=args.api_url,
        model=args.model,
    )

    result = injector.inject(
        utg_path=str(utg_path),
        anomaly_scenario=args.scenario,
        output_path=args.output,
    )

    print()
    print("-" * 60)

    if not result["success"]:
        print(f"❌ 注入失败: {result.get('error', '未知错误')}")
        sys.exit(1)

    # 输出结果
    print(f"✅ 注入成功")
    print(f"  注入步:    Step {result['injection_step']} (stepId={result['step_id']})")
    print(f"  决策理由:  {result['decision_reason'][:200]}")
    print()
    print(f"  ── 原始 ui_summary ──")
    print(f"  {result['original_ui_summary'][:200]}")
    print()
    print(f"  ── 改写后 ui_summary ──")
    print(f"  {result['rewritten_ui_summary'][:200]}")

    if args.output:
        print(f"\n  ✓ 已保存: {args.output}")
    else:
        print(f"\n  ℹ 未指定 --output，仅终端显示。完整修改后 utg 如下：")
        print(json.dumps(result["modified_utg"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
