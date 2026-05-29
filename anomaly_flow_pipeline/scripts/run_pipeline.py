#!/usr/bin/env python3
"""
run_pipeline.py — 一键端到端 pipeline 入口

整合 Phase 0-4 为完整流程：
  Phase 0: 预处理（去重 + 动作重写 + 数据对齐 + 页面补齐）
  Phase 1: 异常注入（上下文感知改写 + 相邻步联动）
  Phase 2: 智能 Flow 转换（targetPage + 数据绑定）
  Phase 3: 质量验证
  Phase 4: 报告输出

用法:
    # 完整流程
    python -m anomaly_flow_pipeline.scripts.run_pipeline \\
        --utg path/to/utg_info.json \\
        --scenario "搜索列表加载失败" \\
        --template example_data/shopping-flow-search-and-buy_new.json \\
        --output-dir ./outputs

    # 多异常场景
    python -m anomaly_flow_pipeline.scripts.run_pipeline \\
        --utg path/to/utg_info.json \\
        --scenarios '["场景1", "场景2"]' \\
        --template example_data/shopping-flow-search-and-buy_new.json

    # 跳过预处理
    python -m anomaly_flow_pipeline.scripts.run_pipeline \\
        --utg path/to/utg_info.json \\
        --scenario "价格显示异常" \\
        --no-preprocess

    # 详细日志
    python -m anomaly_flow_pipeline.scripts.run_pipeline \\
        --utg path/to/utg_info.json \\
        --scenario "加载失败" --verbose
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional

# 将项目根目录加入 sys.path
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    from dotenv import load_dotenv
    pipeline_env = Path(__file__).resolve().parent.parent / ".env"
    if pipeline_env.exists():
        load_dotenv(pipeline_env)
except ImportError:
    pass

from anomaly_flow_pipeline.core.utg_preprocessor import UTGPreprocessor
from anomaly_flow_pipeline.core.utg_anomaly_injector import UTGAnomalyInjector
from anomaly_flow_pipeline.core.flow_converter import FlowConverter
from anomaly_flow_pipeline.core.quality_validator import QualityValidator


def report_phase(phase_name: str, elapsed: float, details: Dict[str, Any]):
    """输出阶段报告"""
    status = "✅" if details.get("success", True) else "❌"
    print(f"  {status} {phase_name} ({elapsed:.1f}s)")
    for key, value in details.items():
        if key == "success" or key == "modified_utg":
            continue
        if isinstance(value, str):
            print(f"    {key}: {value[:120]}")
        elif isinstance(value, (int, float)):
            print(f"    {key}: {value}")


def main():
    parser = argparse.ArgumentParser(
        description="anomaly_flow_pipeline — 端到端异常注入 Flow 生成管道"
    )
    parser.add_argument("--utg", required=True, help="utg_info.json 路径")
    parser.add_argument("--scenario", default=None, help="异常场景描述（单场景）")
    parser.add_argument("--scenarios", default=None, help="多个异常场景 JSON 数组字符串")
    parser.add_argument("--template", required=True,
                        help="Flow 模板路径（推荐 shopping-flow-search-and-buy_new.json）")
    parser.add_argument("--output-dir", "-o", default=None, help="输出目录")
    parser.add_argument("--no-preprocess", action="store_true",
                        help="跳过 Phase 0 预处理")
    parser.add_argument("--no-neighbor-adjust", action="store_true",
                        help="跳过 Phase 1 相邻步微调")
    parser.add_argument("--no-validation", action="store_true",
                        help="跳过 Phase 3 质量验证")
    parser.add_argument("--schema", default=None,
                        help="model-schema.json 路径（默认 schema/model-schema.json）")
    parser.add_argument("--no-compress-steps", action="store_true",
                        help="禁用 Phase 2 相邻同页面步骤合并（默认启用合并）")
    parser.add_argument("--model", default=None, help="VLM 模型名")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s", stream=sys.stdout)

    # 参数校验
    utg_path = Path(args.utg)
    template_path = Path(args.template)
    if not utg_path.exists():
        print(f"❌ UTG 文件不存在: {utg_path}")
        sys.exit(1)
    if not template_path.exists():
        print(f"❌ 模板文件不存在: {template_path}")
        sys.exit(1)

    scenarios = []
    if args.scenario:
        scenarios.append(args.scenario)
    if args.scenarios:
        try:
            extra = json.loads(args.scenarios)
            if isinstance(extra, list):
                scenarios.extend(extra)
        except json.JSONDecodeError:
            print(f"❌ --scenarios 格式错误: {args.scenarios}")
            sys.exit(1)
    if not scenarios:
        print("❌ 请提供 --scenario 或 --scenarios")
        sys.exit(1)

    # 输出目录
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) if args.output_dir else Path(f"./outputs/pipeline_{timestamp}")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 质量报告
    quality_report = {
        "pipeline": "anomaly_flow_pipeline.run_pipeline",
        "input": str(utg_path),
        "template": str(template_path),
        "scenarios": scenarios,
        "timestamp": timestamp,
        "phases": {},
    }

    current_utg = str(utg_path)

    print("=" * 60)
    print(f"  anomaly_flow_pipeline — 端到端流程")
    print(f"  UTG:        {utg_path.name}")
    print(f"  模板:       {template_path.name}")
    print(f"  Schema:     {Path(args.schema).name if args.schema else 'model-schema.json'}")
    print(f"  异常场景:   {scenarios}")
    print(f"  合并同页:   {'✓' if not args.no_compress_steps else '✗'}")
    print(f"  输出目录:   {output_dir}")
    print("=" * 60)
    print()

    # ═══════════════════════════════════════════════════════
    # Phase 0: 预处理
    # ═══════════════════════════════════════════════════════
    if not args.no_preprocess:
        print(">>> Phase 0: UTG 预处理")
        t0 = time.time()
        preprocessor = UTGPreprocessor(model=args.model)
        pre_result = preprocessor.run(
            utg_path=str(utg_path),
            template_path=str(template_path),
            output_path=str(output_dir / "phase0_preprocessed.json"),
        )
        t1 = time.time()

        phase0_report = {
            "success": pre_result["success"],
            "steps_before": pre_result.get("steps_before", 0),
            "steps_after": pre_result.get("steps_after", 0),
            "error": pre_result.get("error"),
        }
        quality_report["phases"]["preprocess"] = phase0_report
        report_phase("Phase 0 预处理", t1 - t0, phase0_report)

        if not pre_result["success"]:
            print(f"  ❌ Phase 0 失败: {pre_result.get('error', '')}")
            current_utg = str(utg_path)  # 回退到原始文件
            print(f"  回退到原始 UTG")
        else:
            current_utg = str(output_dir / "phase0_preprocessed.json")
        print()
    else:
        quality_report["phases"]["preprocess"] = {"success": True, "skipped": True}
        print(">>> Phase 0: 跳过预处理")
        print()

    # ═══════════════════════════════════════════════════════
    # Phase 1: 异常注入
    # ═══════════════════════════════════════════════════════
    print(">>> Phase 1: 异常注入")
    t0 = time.time()
    injector = UTGAnomalyInjector(model=args.model)

    if len(scenarios) == 1:
        inject_result = injector.inject(
            utg_path=current_utg,
            anomaly_scenario=scenarios[0],
            output_path=str(output_dir / "phase1_injected.json"),
            enable_neighbor_adjust=not args.no_neighbor_adjust,
            enable_validation=not args.no_validation,
        )
    else:
        inject_result = injector.inject_multiple(
            utg_path=current_utg,
            anomaly_scenarios=scenarios,
            output_path=str(output_dir / "phase1_injected.json"),
            enable_neighbor_adjust=not args.no_neighbor_adjust,
            enable_validation=not args.no_validation,
        )
    t1 = time.time()

    phase1_report = {
        "success": inject_result["success"],
        "injection_count": len(inject_result.get("injection_details", [inject_result])),
        "error": inject_result.get("error"),
        "anomaly_scenarios": scenarios,
    }
    quality_report["phases"]["injection"] = phase1_report
    report_phase("Phase 1 异常注入", t1 - t0, phase1_report)

    if not inject_result["success"]:
        print(f"  ❌ 注入失败: {inject_result.get('error', '')}")
        print(f"  注入后的文件仍用于后续步骤，但可能不含异常")
        # 仍用预处理后的文件继续
        injected_utg = current_utg
    else:
        injected_utg = str(output_dir / "phase1_injected.json")
    print()

    # ═══════════════════════════════════════════════════════
    # Phase 2: Flow 转换
    # ═══════════════════════════════════════════════════════
    print(">>> Phase 2: Flow 转换")
    t0 = time.time()
    converter = FlowConverter()
    convert_result = converter.convert(
        utg_path=injected_utg,
        template_path=str(template_path),
        output_path=str(output_dir / "phase2_flow.json"),
        schema_path=args.schema,
        enable_data_binding=True,
        compress_steps=not args.no_compress_steps,
    )
    t1 = time.time()

    phase2_report = {
        "success": convert_result["success"],
        "step_count": convert_result.get("step_count", 0),
        "bound_mock_id": convert_result.get("bound_mock_id"),
        "error": convert_result.get("error"),
    }
    quality_report["phases"]["conversion"] = phase2_report
    report_phase("Phase 2 Flow 转换", t1 - t0, phase2_report)
    print()

    # ═══════════════════════════════════════════════════════
    # Phase 3: 质量验证
    # ═══════════════════════════════════════════════════════
    if not args.no_validation and convert_result["success"]:
        print(">>> Phase 3: 质量验证")
        t0 = time.time()

        flow_path = str(output_dir / "phase2_flow.json")
        with open(flow_path, 'r', encoding='utf-8') as f:
            flow_data = json.load(f)

        validator = QualityValidator()
        validation_result = validator.validate(
            flow_data,
            template_path=str(template_path),
        )
        t1 = time.time()

        phase3_report = {
            "success": validation_result["passed"],
            "score": validation_result["score"],
            "issues_count": sum(
                len(d.get("issues", []))
                for d in validation_result.get("dimensions", {}).values()
            ),
            "dimensions": {
                k: {"passed": v["passed"], "issues": v["issues"]}
                for k, v in validation_result.get("dimensions", {}).items()
            },
        }
        quality_report["phases"]["validation"] = phase3_report
        report_phase("Phase 3 质量验证", t1 - t0, phase3_report)
        print()

        # 如果验证未通过，仍保留输出
        if not validation_result["passed"]:
            print("  ⚠ 质量验证发现问题，输出文件仍已保存")
            print(f"  建议查看验证报告改进输入数据")
            print()
    else:
        quality_report["phases"]["validation"] = {"skipped": True}

    # ═══════════════════════════════════════════════════════
    # Phase 4: 报告输出
    # ═══════════════════════════════════════════════════════
    print(">>> Phase 4: 报告输出")
    quality_report["outputs"] = {
        "preprocessed": str(output_dir / "phase0_preprocessed.json") if not args.no_preprocess else None,
        "injected": str(output_dir / "phase1_injected.json"),
        "flow": str(output_dir / "phase2_flow.json"),
    }

    report_path = output_dir / "pipeline_report.json"
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(quality_report, f, ensure_ascii=False, indent=2)
    print(f"  ✓ 报告已保存: {report_path}")
    print()

    # ═══════════════════════════════════════════════════════
    # 完成
    # ═══════════════════════════════════════════════════════
    print("=" * 60)
    print(f"  Pipeline 完成")
    print(f"  输出目录: {output_dir}")
    print(f"  Flow:     {output_dir / 'phase2_flow.json'}")
    if quality_report["phases"].get("validation", {}).get("score"):
        print(f"  质量评分: {quality_report['phases']['validation']['score']}/1.0")
    print("=" * 60)


if __name__ == "__main__":
    main()
