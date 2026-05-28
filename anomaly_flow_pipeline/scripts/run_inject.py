#!/usr/bin/env python3
"""
run_inject.py — 异常注入 CLI 入口（Phase 1）

支持：
- 单异常场景注入
- 多异常场景注入（--scenarios）
- 预处理前置（--preprocess）
- 上下文感知改写（自动引入前后步骤）

用法:
    # 单异常注入（基础模式）
    python -m anomaly_flow_pipeline.scripts.run_inject \\
        --utg path/to/utg.json \\
        --scenario "搜索列表加载失败，显示网络错误提示" \\
        --output /tmp/modified_utg.json

    # 多异常注入 + 预处理
    python -m anomaly_flow_pipeline.scripts.run_inject \\
        --utg path/to/utg.json \\
        --scenarios '["搜索列表加载失败", "商品详情价格显示异常"]' \\
        --template example_data/shopping-flow-search-and-buy_new.json \\
        --preprocess \\
        --output /tmp/modified_utg.json
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
from anomaly_flow_pipeline.core.utg_preprocessor import UTGPreprocessor


def main():
    parser = argparse.ArgumentParser(description="异常注入 — 决策注入步 + 改写 ui_summary")
    parser.add_argument("--utg", required=True, help="utg_info.json 文件路径")
    parser.add_argument("--scenario", default=None, help="异常场景文本描述（单场景）")
    parser.add_argument("--scenarios", default=None, help="多个异常场景 JSON 数组字符串")
    parser.add_argument("--template", default=None,
                        help="Flow 模板路径（用于预处理页面补齐参考）")
    parser.add_argument("--preprocess", action="store_true", default=False,
                        help="注入前先执行 Phase 0 预处理")
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

    # 解析异常场景列表
    scenarios = []
    if args.scenario:
        scenarios.append(args.scenario)
    if args.scenarios:
        try:
            extra = json.loads(args.scenarios)
            if isinstance(extra, list):
                scenarios.extend(extra)
        except json.JSONDecodeError:
            print(f"❌ --scenarios 格式错误，应为 JSON 数组: {args.scenarios}")
            sys.exit(1)

    if not scenarios:
        print("❌ 请提供 --scenario 或 --scenarios")
        sys.exit(1)

    # 决定注入路径
    actual_utg = str(utg_path)

    # Phase 0: 预处理（可选）
    if args.preprocess:
        print("=" * 60)
        print("Phase 0: UTG 预处理")
        print("=" * 60)
        preprocessor = UTGPreprocessor(model=args.model)
        pre_result = preprocessor.run(
            utg_path=str(utg_path),
            template_path=args.template,
            output_path=None,  # 先不在磁盘保存中间结果
        )
        if not pre_result["success"]:
            print(f"❌ 预处理失败: {pre_result.get('error', '')}")
            sys.exit(1)

        # 将预处理后的 utg 保存到临时文件
        tmp_pre_path = utg_path.parent / f".{utg_path.name}.preprocessed"
        preprocessor.save(pre_result["modified_utg"], str(tmp_pre_path))
        actual_utg = str(tmp_pre_path)

        print(f"  步骤: {pre_result['steps_before']} → {pre_result['steps_after']}")
        phases = pre_result.get("phases", {})
        if "dedup" in phases and not phases["dedup"].get("skipped"):
            print(f"  去重: {phases['dedup'].get('total_before', 0)} → {phases['dedup'].get('total_after', 0)}")
        if "rewrite" in phases and not phases["rewrite"].get("skipped"):
            print(f"  重写: {phases['rewrite'].get('success', 0)} 步成功")
        if "align" in phases and not phases["align"].get("skipped"):
            print(f"  数据对齐: {phases['align'].get('issues_found', 0)} 个问题")
        if "complete" in phases and not phases["complete"].get("skipped"):
            print(f"  页面补齐: {len(phases['complete'].get('inserted', []))} 页")
        print()

    # Phase 1: 异常注入
    print("=" * 60)
    print(f"Phase 1: 异常注入 ({len(scenarios)} 个场景)")
    print("=" * 60)

    injector = UTGAnomalyInjector(model=args.model)

    if len(scenarios) == 1:
        # 单场景注入
        result = injector.inject(
            utg_path=actual_utg,
            anomaly_scenario=scenarios[0],
            output_path=args.output,
        )
    else:
        # 多场景注入
        result = injector.inject_multiple(
            utg_path=actual_utg,
            anomaly_scenarios=scenarios,
            output_path=args.output,
        )

    if not result["success"]:
        print(f"❌ 注入失败: {result.get('error', '未知错误')}")
        sys.exit(1)

    print(f"✅ 注入成功")
    if result.get("injection_details"):
        for detail in result["injection_details"]:
            print(f"  Step {detail['injection_step']} (stepId={detail['step_id']}): {detail['anomaly_scenario'][:60]}")
            print(f"    理由: {detail.get('decision_reason', '')[:120]}")
    else:
        print(f"  注入步: Step {result['injection_step']} (stepId={result['step_id']})")
        print(f"  决策理由: {result['decision_reason'][:200]}")
        print(f"\n  ── 原始 ui_summary ──")
        print(f"  {result['original_ui_summary'][:150]}")
        print(f"\n  ── 改写后 ui_summary ──")
        print(f"  {result['rewritten_ui_summary'][:150]}")

    if args.output:
        print(f"\n  ✓ 已保存: {args.output}")

    # 清理临时文件
    if args.preprocess:
        tmp_pre_path = utg_path.parent / f".{utg_path.name}.preprocessed"
        if tmp_pre_path.exists():
            tmp_pre_path.unlink()


if __name__ == "__main__":
    main()
