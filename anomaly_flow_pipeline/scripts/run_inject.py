#!/usr/bin/env python3
"""
run_inject.py — 异常注入 CLI 入口

将异常场景文本注入到 utg.json 的 ui_summary 中。

用法:
    python -m anomaly_flow_pipeline.scripts.run_inject \\
        --utg path/to/utg.json \\
        --scenario "搜索列表加载失败" \\
        --output path/to/output.json
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

from anomaly_flow_pipeline.core.utg_anomaly_injector import UTGAnomalyInjector


def main():
    parser = argparse.ArgumentParser(description="异常注入 — 决策注入步 + 改写 ui_summary")
    parser.add_argument("--utg", required=True, help="utg_info.json 文件路径")
    parser.add_argument("--scenario", required=True, help="异常场景文本描述")
    parser.add_argument("--output", "-o", default=None, help="输出文件路径")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    parser.add_argument("--model", default=None, help="VLM 模型名")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s", stream=sys.stdout)

    utg_path = Path(args.utg)
    if not utg_path.exists():
        print(f"❌ 文件不存在: {utg_path}")
        sys.exit(1)

    print("=" * 60)
    print("异常注入器")
    print("=" * 60)
    print(f"  UTG:      {utg_path}")
    print(f"  场景:     {args.scenario[:60]}")
    print(f"  输出:     {args.output or '(终端显示)'}")
    print()

    injector = UTGAnomalyInjector(model=args.model)
    result = injector.inject(utg_path=str(utg_path), anomaly_scenario=args.scenario, output_path=args.output)

    if not result["success"]:
        print(f"❌ 注入失败: {result.get('error', '未知错误')}")
        sys.exit(1)

    print(f"✅ 注入成功")
    print(f"  注入步:    Step {result['injection_step']} (stepId={result['step_id']})")
    print(f"  决策理由:  {result['decision_reason'][:200]}")
    print(f"\n  ── 原始 ui_summary ──")
    print(f"  {result['original_ui_summary'][:200]}")
    print(f"\n  ── 改写后 ui_summary ──")
    print(f"  {result['rewritten_ui_summary'][:200]}")

    if args.output:
        print(f"\n  ✓ 已保存: {args.output}")
    else:
        print(f"\n  ℹ 完整修改后 utg:")
        print(json.dumps(result["modified_utg"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
