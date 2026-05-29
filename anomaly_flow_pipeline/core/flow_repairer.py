"""
flow_repairer.py — Phase 4: 基于质量验证报告自动修复 Flow

读取 Phase 2 输出的 flow JSON 和 Phase 3 的验证报告，
调用 LLM 自动修复所有可修复的问题，输出修复后的 flow。
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

from .llm_client import LLMClient

logger = logging.getLogger(__name__)

REPAIR_PROMPT = """你是一个 APP 操作流程修复专家。根据质量验证报告中的问题，修复 mainFlow 的步骤。

## ⚠️ 最重要：这是一个异常注入测试 Flow
流程中**故意注入**了异常场景："{anomaly_scenario}"。
该异常场景是核心测试内容，**必须保留**，绝对不能删除或修复掉。
异常导致的衔接问题（如加载失败后页面空白）是**正常现象**，不需要修复。

## 当前 mainFlow 步骤
{steps_text}

## 质量验证报告发现的问题
{issues_text}

## 修复规则
1. **异常保留**：包含"{anomaly_scenario}"相关描述的步骤**绝对不能删除**
2. **重复合并**：连续相同非异常操作合并为 1 步（如两次点购物车→保留 1 次）
3. **数据修正**：数量爆炸（54→1）修正为合理值；与异常无关的数据矛盾才修正
4. **无关步骤删除**：与主线完全无关且不含异常的页面才删除
5. **缺失页面补充**：补充商品详情、支付、订单确认等关键页面
6. **保持格式**：每条 action 按"页面初始状态：...\\n操作：...\\n最终状态：..."格式
7. **步骤精简**：修复后步骤总数尽量 ≤10
8. **保持 Schema**：仅保留 order 和 action 字段

## 输出格式
直接输出修复后的 JSON 数组（order 重新编号从 1 开始）：
[
  {{"order": 1, "action": "页面初始状态：...\\n操作：...\\n最终状态：..."}},
  ...
]

只输出 JSON 数组，不要 markdown 包裹，不要额外说明。"""


class FlowRepairer:
    """基于验证报告自动修复 Flow"""

    def __init__(self, api_key=None, api_url=None, model=None):
        self.llm = LLMClient(
            api_key=api_key,
            api_url=api_url,
            model=model,
            temperature=0.1,
        )

    def repair(
        self,
        flow_path: str,
        validation_report: Dict,
        anomaly_scenario: str = "",
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        执行修复。

        Args:
            flow_path: phase2_flow.json 路径
            validation_report: 验证报告 dict
            anomaly_scenario: 注入的异常场景描述（用于保护异常不被误删）
            output_path: 修复后输出路径（可选）
        """
        result = {"success": False, "output_path": output_path, "step_count": 0, "error": None}

        try:
            # 加载 flow
            with open(flow_path, 'r', encoding='utf-8') as f:
                flow_data = json.load(f)

            steps = flow_data.get("mainFlow", {}).get("steps", [])
            if not steps:
                result["error"] = "无步骤数据"
                return result

            # 提取问题列表
            issues = self._extract_issues(validation_report)
            if not issues:
                logger.info("  无需修复：验证报告未发现问题")
                result["success"] = True
                result["step_count"] = len(steps)
                return result

            logger.info(f"  待修复问题: {len(issues)} 项")

            # 构建步骤文本
            step_lines = []
            for s in steps:
                step_lines.append(
                    f"Step {s['order']}: {s.get('action', '')}"
                )
            steps_text = "\n\n".join(step_lines)

            # 构建问题文本
            issues_text = "\n".join(f"- {i}" for i in issues)

            prompt = REPAIR_PROMPT.format(
                anomaly_scenario=anomaly_scenario or "(无异常注入)",
                steps_text=steps_text,
                issues_text=issues_text,
            )

            # LLM 修复
            raw = self.llm.chat(prompt)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.replace("```json", "").replace("```", "").strip()

            parsed = self.llm.extract_json(raw)

            if not isinstance(parsed, list) or not parsed:
                result["error"] = f"LLM 修复返回格式异常: {type(parsed).__name__}"
                return result

            # 重新编号
            for i, step in enumerate(parsed):
                step["order"] = i + 1
                # 过滤非法字段
                allowed = {"order", "action"}
                for key in list(step.keys()):
                    if key not in allowed:
                        del step[key]

            # 更新 flow
            flow_data["mainFlow"]["steps"] = parsed
            result["step_count"] = len(parsed)
            logger.info(
                f"  修复完成: {len(steps)} → {len(parsed)} 步"
            )

            if output_path:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(flow_data, f, ensure_ascii=False, indent=2)
                result["output_path"] = output_path
                logger.info(f"  ✓ 已保存: {output_path}")

            result["success"] = True
            return result

        except Exception as e:
            logger.exception("修复失败")
            result["error"] = str(e)
            return result

    @staticmethod
    def _extract_issues(report: Dict) -> List[str]:
        """从验证报告中提取可操作的问题列表"""
        issues = []

        # Phase 3 validate() 输出的 dimensions
        dims = report.get("dimensions", {})
        for dim_name, dim_data in dims.items():
            for issue in dim_data.get("issues", []):
                if isinstance(issue, str):
                    issues.append(f"[{dim_name}] {issue}")

        # pipeline_report.json 格式
        phases = report.get("phases", {})
        validation = phases.get("validation", {})
        for dim_name, dim_data in validation.get("dimensions", {}).items():
            for issue in dim_data.get("issues", []):
                if isinstance(issue, str) and issue not in issues:
                    issues.append(f"[{dim_name}] {issue}")

        # 整体校验的 detail
        holistic = dims.get("holistic", {})
        detail = holistic.get("detail", {})
        for dim_key, dim_info in detail.items():
            for issue in dim_info.get("issues", []):
                issues.append(f"[{dim_key}] {issue}")

        return issues

