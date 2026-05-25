#!/usr/bin/env python3
"""
convert_utg_to_flow.py — 将修改后的 utg_info.json 的 ui_summary 合并到 flow 模板

流程：
  1. 读取 modified utg_info.json（含改写后的 ui_summary）
  2. 读取 flow 模板 JSON（如 shopping-flow-search-and-buy.json）
  3. 将 utg 中所有有效 step 的 ui_summary 填充到模板的 mainFlow.steps
  4. 模板的其他字段保持不变
  5. 输出合并后的 JSON

用法:
    # 基本用法
    python convert_utg_to_flow.py \
      --utg path/to/modified_utg_info.json \
      --template path/to/shopping-flow-search-and-buy.json \
      --output path/to/output.json

    # 与 run_utg_anomaly_injector.py 链式使用
    python run_utg_anomaly_injector.py \
      --utg tmp/utg.json \
      --scenario "搜索列表加载失败" \
      --output /tmp/modified_utg.json

    python convert_utg_to_flow.py \
      --utg /tmp/modified_utg.json \
      --template tmp/shopping-flow-search-and-buy.json \
      --output /tmp/flow_with_anomaly.json
"""

import argparse
import json
import logging
import sys
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# ── 项目路径引导 ──────────────────────────────────────────
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def load_json(path: str) -> Dict:
    """加载 JSON 文件"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {p}")
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(data: Dict, path: str):
    """保存 JSON 文件"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_valid_steps_from_utg(utg_data: Dict) -> List[Dict]:
    """
    从 utg_info.json 中提取有效步骤（有 ui_summary 的），返回列表。
    每个元素包含: order, stepId, action_type, thought, ui_summary, imageId
    """
    step_data = utg_data.get("stepData", [])
    valid = []
    invalid_ids = {"home", "end", "start"}
    for item in step_data:
        sid = str(item.get("stepId", ""))
        if sid.lower() in invalid_ids:
            continue
        ui_summary = (item.get("ui_summary") or "").strip()
        if not ui_summary:
            continue
        valid.append({
            "order": len(valid) + 1,
            "stepId": sid,
            "action_type": item.get("action_type", ""),
            "thought": item.get("thought", ""),
            "ui_summary": ui_summary,
            "imageId": item.get("imageId", ""),
        })
    return valid


def convert(
    utg_path: str,
    template_path: str,
    output_path: str,
    mode: str = "replace",
) -> Dict[str, Any]:
    """
    将修改后的 utg_info.json 合并到 flow 模板。

    Args:
        utg_path: 修改后的 utg_info.json 路径
        template_path: flow 模板 JSON 路径
        output_path: 输出路径
        mode: 合并模式
            "replace" - 用 utg 步骤完全替换 template 的 mainFlow.steps
            "fill"    - 按顺序填充，超出部分追加，不足保留原模板步骤

    Returns:
        {"success": bool, "output_path": str, "step_count": int, "error": str}
    """
    result = {
        "success": False,
        "output_path": output_path,
        "step_count": 0,
        "error": None,
    }

    try:
        # 1. 加载数据
        utg_data = load_json(utg_path)
        template = load_json(template_path)

        # 2. 提取 utg 有效步骤
        utg_steps = get_valid_steps_from_utg(utg_data)
        if not utg_steps:
            result["error"] = "utg_info.json 中没有有效的 ui_summary 步骤"
            return result

        logger.info(f"UTG 有效步骤: {len(utg_steps)}")

        # 3. 深拷贝模板（不修改原始数据）
        merged = deepcopy(template)

        # 4. 确保 mainFlow 存在
        if "mainFlow" not in merged:
            merged["mainFlow"] = {
                "id": "flow-from-utg",
                "name": utg_data.get("query", "操作流程"),
                "description": utg_data.get("query", ""),
                "precondition": f"用户已登录，{utg_data.get('appName', 'APP')}首页正常加载",
                "steps": [],
            }

        # 5. 构建新步骤
        #    用 utg 的 thought/action_type 生成更具描述性的 action 文本
        new_steps = []
        for i, s in enumerate(utg_steps):
            # action 文本: 优先用 ui_summary（已是改写后的异常描述）
            action_text = s["ui_summary"]

            # 如果有 thought，拼接到 action 前面作为意图说明
            thought = s.get("thought", "").strip()
            if thought:
                # 清理 thought 中的编号前缀如 "【0】"、"【312】"
                import re
                cleaned_thought = re.sub(r'^【\d+】\s*', '', thought)
                action_text = f"{cleaned_thought}。当前页面：{action_text}"

            # 严格遵循模板 step 格式: 只保留 order + action
            step_entry = {
                "order": s["order"],
                "action": action_text,
            }
            new_steps.append(step_entry)

        # 6. 合并（严格遵循模板 mainFlow 格式，不添加额外字段）
        if mode == "replace":
            merged["mainFlow"]["steps"] = new_steps
        elif mode == "fill":
            template_steps = merged["mainFlow"].get("steps", [])
            for i, ns in enumerate(new_steps):
                if i < len(template_steps):
                    # 只更新 action，保持模板原有字段不变
                    template_steps[i] = {
                        "order": template_steps[i].get("order", i + 1),
                        "action": ns["action"],
                    }
                else:
                    template_steps.append(ns)
            merged["mainFlow"]["steps"] = template_steps
        else:
            result["error"] = f"未知的合并模式: {mode}"
            return result

        # 7. 保存
        save_json(merged, output_path)

        step_count = len(merged["mainFlow"]["steps"])
        logger.info(f"输出步骤数: {step_count}")
        logger.info(f"已保存: {output_path}")

        result["success"] = True
        result["step_count"] = step_count
        return result

    except Exception as e:
        logger.exception("转换失败")
        result["error"] = str(e)
        return result


def main():
    parser = argparse.ArgumentParser(
        description="将修改后的 utg_info.json 合并到 flow 模板",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --utg /tmp/modified_utg.json --template tmp/shopping-flow-search-and-buy.json --output /tmp/flow.json

链式使用:
  python run_utg_anomaly_injector.py --utg tmp/utg.json --scenario "..." --output /tmp/modified.json
  python %(prog)s --utg /tmp/modified.json --template tmp/shopping-flow-search-and-buy.json --output output/flow.json
        """,
    )
    parser.add_argument(
        "--utg", required=True,
        help="修改后的 utg_info.json 路径",
    )
    parser.add_argument(
        "--template", required=True,
        help="flow 模板 JSON 路径（如 tmp/shopping-flow-search-and-buy.json）",
    )
    parser.add_argument(
        "--output", "-o", required=True,
        help="输出路径",
    )
    parser.add_argument(
        "--mode", choices=["replace", "fill"], default="replace",
        help="合并模式: replace=完全替换, fill=按顺序填充（默认: replace）",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="详细日志",
    )

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s", stream=sys.stdout)

    # 验证输入文件
    for name, path in [("UTG", args.utg), ("模板", args.template)]:
        if not Path(path).exists():
            print(f"❌ {name} 文件不存在: {path}")
            sys.exit(1)

    print("=" * 60)
    print("UTG → Flow 转换")
    print("=" * 60)
    print(f"  UTG:      {args.utg}")
    print(f"  模板:     {args.template}")
    print(f"  输出:     {args.output}")
    print(f"  模式:     {args.mode}")
    print()

    result = convert(
        utg_path=args.utg,
        template_path=args.template,
        output_path=args.output,
        mode=args.mode,
    )

    if result["success"]:
        print(f"✅ 转换完成: {result['step_count']} 步")
        print(f"   输出: {result['output_path']}")
    else:
        print(f"❌ 转换失败: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
