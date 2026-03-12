#!/usr/bin/env python3
"""
generate_instructions.py - 指令泛化生成脚本

基于业务场景配置 + LLM CoT 推理，生成多样化的测试指令。
支持两种指令类型：
  - anomaly: 异常注入指令（描述要注入的故障）
  - user:    用户意图指令（模拟用户对 Agent 的自然语言指令）

用法：
    # dry-run 模式（不调用 API，输出提示词预览）
    python generate_instructions.py --scenario flight_booking --dry-run

    # 生成异常注入指令（默认）
    python generate_instructions.py --scenario flight_booking --type anomaly --count 30

    # 生成用户意图指令
    python generate_instructions.py --scenario flight_booking --type user --count 30

    # 同时生成两种指令
    python generate_instructions.py --scenario flight_booking --type both --count 30
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# 自动加载项目根目录的 .env 文件
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parents[3] / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

# 确保能导入本地模块
sys.path.insert(0, str(Path(__file__).parent))

from injection.prompts import (
    build_instruction_generation_prompt,
    build_user_instruction_prompt,
)
from injection.anomaly_recommender import DEFAULT_CATEGORY_DESCRIPTIONS


# 场景数据根目录
SCENARIOS_DIR = Path(__file__).parent.parent / "data" / "scenarios"


def load_scenario(scenario_name: str) -> Dict:
    """加载场景配置"""
    scenario_file = SCENARIOS_DIR / scenario_name / "scenario.json"
    if not scenario_file.exists():
        raise FileNotFoundError(f"场景配置不存在: {scenario_file}")
    with open(scenario_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def format_business_steps(scenario: Dict) -> str:
    """格式化业务步骤为文本"""
    lines = []
    for step in scenario["business_steps"]:
        elements = "、".join(step["key_elements"])
        lines.append(
            f"步骤 {step['step']}: {step['name']}\n"
            f"  描述: {step['description']}\n"
            f"  关键元素: {elements}"
        )
    return "\n\n".join(lines)


def format_anomaly_types(scenario: Dict) -> str:
    """格式化异常类型为文本"""
    lines = []
    mapping = scenario.get("anomaly_mode_mapping", {})
    for i, (mode, info) in enumerate(mapping.items(), 1):
        scenarios_text = "、".join(info["flight_scenarios"][:3]) + " 等"
        lines.append(
            f"{i}. {mode} - {info['description']}\n"
            f"   典型场景: {scenarios_text}"
        )
    return "\n".join(lines)


def call_llm(prompt: str, system_msg: str = None) -> str:
    """调用 LLM API 生成内容"""
    import requests

    api_key = os.environ.get('VLM_API_KEY')
    api_url = os.environ.get('VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions')
    model = os.environ.get('VLM_MODEL', 'gpt-4o')

    if not api_key:
        raise ValueError("未设置 VLM_API_KEY 环境变量，请在 .env 中配置")

    if system_msg is None:
        system_msg = "你是一个移动应用测试专家。请严格按照要求输出 JSON 格式。"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.8,
        "max_tokens": 4096
    }

    print("  调用 LLM API 生成指令...")
    response = requests.post(api_url, headers=headers, json=payload, timeout=120)
    response.raise_for_status()

    result = response.json()
    content = result["choices"][0]["message"]["content"]
    return content


def parse_llm_response(response_text: str, id_prefix: str = "FB") -> List[Dict]:
    """解析 LLM 返回的 JSON 指令列表"""
    text = response_text.strip()

    # 移除 markdown 代码块标记
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.rindex("```")
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.rindex("```")
        text = text[start:end].strip()

    # 查找 JSON 数组
    if "[" in text:
        start = text.index("[")
        end = text.rindex("]") + 1
        text = text[start:end]

    instructions = json.loads(text)

    # 为每条指令添加 ID
    for i, inst in enumerate(instructions, 1):
        if "id" not in inst:
            inst["id"] = f"{id_prefix}-{i:03d}"

    return instructions


def generate_anomaly_instructions(scenario: Dict, count: int) -> List[Dict]:
    """使用 LLM 生成异常注入指令"""
    business_steps = format_business_steps(scenario)
    anomaly_types = format_anomaly_types(scenario)

    prompt = build_instruction_generation_prompt(
        scenario_name=scenario["scenario_name"],
        business_steps=business_steps,
        anomaly_types=anomaly_types,
        count=count
    )

    response = call_llm(
        prompt,
        system_msg="你是一个移动应用测试专家，擅长构造异常场景的测试指令。请严格按照要求输出 JSON 格式。"
    )
    instructions = parse_llm_response(response, id_prefix="FB")

    print(f"  LLM 生成了 {len(instructions)} 条异常指令")
    return instructions


def generate_user_instructions(scenario: Dict, count: int) -> List[Dict]:
    """使用 LLM 生成用户意图指令"""
    business_steps = format_business_steps(scenario)

    prompt = build_user_instruction_prompt(
        scenario_name=scenario["scenario_name"],
        app_name=scenario.get("app_name", "App"),
        business_steps=business_steps,
        count=count
    )

    response = call_llm(
        prompt,
        system_msg="你是一个用户行为分析专家，擅长模拟真实用户的自然语言表达。请严格按照要求输出 JSON 格式。"
    )
    instructions = parse_llm_response(response, id_prefix="UI")

    print(f"  LLM 生成了 {len(instructions)} 条用户指令")
    return instructions


def save_instructions(
    output_data: Dict,
    output_path: Path
) -> None:
    """保存指令到 JSON 文件"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    total = output_data.get("total_count", 0)
    print(f"\n已保存 {total} 条指令到: {output_path}")


def print_anomaly_stats(instructions: List[Dict]) -> None:
    """打印异常指令统计"""
    mode_counts = {}
    step_counts = {}
    for inst in instructions:
        mode = inst.get("anomaly_mode", "unknown")
        step = inst.get("target_step", "unknown")
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
        step_counts[step] = step_counts.get(step, 0) + 1

    print("  异常模式分布:")
    for mode, count in sorted(mode_counts.items(), key=lambda x: -x[1]):
        print(f"    {mode}: {count} 条")
    print("  目标步骤分布:")
    for step, count in sorted(step_counts.items(), key=lambda x: -x[1]):
        print(f"    {step}: {count} 条")


def print_user_stats(instructions: List[Dict]) -> None:
    """打印用户指令统计"""
    intent_counts = {}
    complexity_counts = {}
    for inst in instructions:
        intent = inst.get("intent", "unknown")
        complexity = inst.get("complexity", "unknown")
        intent_counts[intent] = intent_counts.get(intent, 0) + 1
        complexity_counts[complexity] = complexity_counts.get(complexity, 0) + 1

    print(f"  意图分布 ({len(intent_counts)} 种):")
    for intent, count in sorted(intent_counts.items(), key=lambda x: -x[1]):
        print(f"    {intent}: {count} 条")
    print("  复杂度分布:")
    for c, count in sorted(complexity_counts.items()):
        print(f"    {c}: {count} 条")


def main():
    parser = argparse.ArgumentParser(
        description="指令泛化生成脚本（异常指令 + 用户意图指令）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 预览提示词（不调用 API）
    python generate_instructions.py --scenario flight_booking --dry-run

    # 生成异常注入指令
    python generate_instructions.py --scenario flight_booking --type anomaly --count 30

    # 生成用户意图指令
    python generate_instructions.py --scenario flight_booking --type user --count 30

    # 同时生成两种指令
    python generate_instructions.py --scenario flight_booking --type both

    # 列出可用场景
    python generate_instructions.py --list-scenarios
        """
    )

    parser.add_argument(
        "--scenario", "-s",
        type=str,
        help="场景名称（对应 data/scenarios/ 下的目录名）"
    )

    parser.add_argument(
        "--type", "-t",
        type=str,
        choices=["anomaly", "user", "both"],
        default="both",
        help="指令类型：anomaly（异常注入）、user（用户意图）、both（两者）（默认 both）"
    )

    parser.add_argument(
        "--count", "-n",
        type=int,
        default=20,
        help="每种类型的生成数量（默认 20）"
    )

    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="输出文件路径（默认保存到场景目录下的 instructions.json）"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅输出提示词，不调用 LLM API"
    )

    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="列出所有可用场景"
    )

    args = parser.parse_args()

    # 列出场景
    if args.list_scenarios:
        print("\n可用场景:")
        if SCENARIOS_DIR.exists():
            for d in sorted(SCENARIOS_DIR.iterdir()):
                if d.is_dir() and (d / "scenario.json").exists():
                    scenario = load_scenario(d.name)
                    print(f"  - {d.name}: {scenario.get('description', '无描述')}")
        else:
            print("  （暂无场景配置）")
        return

    if not args.scenario:
        parser.error("请指定 --scenario 参数或使用 --list-scenarios 查看可用场景")

    # 加载场景
    print(f"\n加载场景: {args.scenario}")
    scenario = load_scenario(args.scenario)
    print(f"  场景名称: {scenario['scenario_name']}")
    print(f"  业务步骤: {len(scenario['business_steps'])} 步")
    print(f"  异常模式: {len(scenario.get('anomaly_mode_mapping', {}))} 种")

    gen_anomaly = args.type in ("anomaly", "both")
    gen_user = args.type in ("user", "both")
    business_steps = format_business_steps(scenario)

    # === Dry-run 模式 ===
    if args.dry_run:
        if gen_anomaly:
            anomaly_types = format_anomaly_types(scenario)
            prompt = build_instruction_generation_prompt(
                scenario_name=scenario["scenario_name"],
                business_steps=business_steps,
                anomaly_types=anomaly_types,
                count=args.count
            )
            print("\n" + "=" * 60)
            print("DRY RUN - 异常注入指令提示词")
            print("=" * 60)
            print(prompt)
            print(f"\n提示词长度: {len(prompt)} 字符")

        if gen_user:
            prompt = build_user_instruction_prompt(
                scenario_name=scenario["scenario_name"],
                app_name=scenario.get("app_name", "App"),
                business_steps=business_steps,
                count=args.count
            )
            print("\n" + "=" * 60)
            print("DRY RUN - 用户意图指令提示词")
            print("=" * 60)
            print(prompt)
            print(f"\n提示词长度: {len(prompt)} 字符")

        print("\n" + "=" * 60)
        print(f"目标生成: {args.count} 条/类型")
        print("=" * 60)
        return

    # === LLM 生成 ===
    output_data = {
        "scenario": scenario["scenario_name"],
        "app_name": scenario.get("app_name", ""),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    if gen_user:
        print("\n--- 生成用户意图指令 ---")
        user_instructions = generate_user_instructions(scenario, args.count)
        output_data["user_instructions"] = user_instructions

    if gen_anomaly:
        print("\n--- 生成异常注入指令 ---")
        anomaly_instructions = generate_anomaly_instructions(scenario, args.count)
        output_data["anomaly_mode_coverage"] = list(set(
            inst.get("anomaly_mode", "unknown") for inst in anomaly_instructions
        ))
        output_data["anomaly_instructions"] = anomaly_instructions

    total = len(output_data.get("user_instructions", [])) + len(output_data.get("anomaly_instructions", []))
    output_data["total_count"] = total

    # 保存
    output_path = Path(args.output) if args.output else (
        SCENARIOS_DIR / args.scenario / "instructions.json"
    )
    save_instructions(output_data, output_path)

    # 统计
    print("\n生成统计:")
    if gen_user and output_data.get("user_instructions"):
        print(f"\n  [用户意图指令] {len(output_data['user_instructions'])} 条")
        print_user_stats(output_data["user_instructions"])
    if gen_anomaly and output_data.get("anomaly_instructions"):
        print(f"\n  [异常注入指令] {len(output_data['anomaly_instructions'])} 条")
        print_anomaly_stats(output_data["anomaly_instructions"])


if __name__ == "__main__":
    main()
