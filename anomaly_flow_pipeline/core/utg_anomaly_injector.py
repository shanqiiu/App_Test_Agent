"""
utg_anomaly_injector.py — 独立异常注入决策与 ui_summary 改写模块

基于输入的异常场景文本描述 + utg_info.json，实现：
1. LLM 决策：在序列的哪一步注入该异常最合理
2. LLM 改写：将该步的 ui_summary 改写为异常状态描述
3. 输出：完整的修改后 utg_info.json

独立模块，仅依赖 llm_client 和 utg_loader。
"""

import json
import logging
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Dict, Optional, Any

from .llm_client import LLMClient
from .utg_loader import UTGLoader

logger = logging.getLogger(__name__)

# ── Prompt 模板 ──────────────────────────────────────────

DECISION_PROMPT = """你是一个 App 异常测试场景生成专家。给定一个 App 操作序列中每步的 UI 状态描述，以及一个待注入的异常场景描述，你需要选择在序列的哪一步注入该异常最合理。

## 异常场景描述
{anomaly_scenario}

## 操作序列 UI 状态描述（按时间顺序）
{steps_text}

## 决策原则
1. 选择与异常场景描述**最自然契合**的步骤
2. 优先选择用户刚完成关键操作后、进入关键页面的时机
3. 避免选在首页、加载中状态、纯输入步骤
4. 避免选在序列的末尾步骤

## 输出格式（仅返回 JSON）
{{
  "injection_step": <int>,
  "reason": "<string>"
}}
"""

REWRITE_PROMPT = """你是一个 App 异常测试场景生成专家。你需要改写 App 操作序列中某一步骤的 UI 描述（ui_summary），使其反映指定的异常场景状态。

## 异常场景描述
{anomaly_scenario}

## 当前步骤的原始信息
- 步骤索引: Step {step_index}
- 操作意图: {thought}
- 操作类型: {action_type}
- 原始 UI 描述: {original_ui_summary}

## 改写要求
1. **保持原有核心页面结构**
2. **自然融入异常状态**
3. **风格一致**
4. **不改变操作意图**
5. **具体而非抽象**

## 输出格式
只输出改写后的 ui_summary 文本，不要包含其他内容。
"""


class UTGAnomalyInjector:
    """
    UTG 异常注入器

    流程：
    1. 加载 utg_info.json → UTGLoader
    2. LLM 决策注入步
    3. LLM 改写 ui_summary
    4. 组装修改后 utg_info.json
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.llm = LLMClient(
            api_key=api_key,
            api_url=api_url,
            model=model,
            temperature=0.1,
            max_tokens=1024,
        )

    def inject(
        self,
        utg_path: str,
        anomaly_scenario: str,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """执行完整的异常注入流程"""
        result = {
            "success": False,
            "modified_utg": None,
            "injection_step": None,
            "step_id": None,
            "original_ui_summary": None,
            "rewritten_ui_summary": None,
            "decision_reason": "",
            "anomaly_scenario": anomaly_scenario,
            "error": None,
        }

        try:
            print(f"  [LLM] {self.llm.model}")
            logger.info(f"加载 UTG: {utg_path}")

            loader = UTGLoader(utg_path)
            valid_steps = loader.get_valid_steps()
            if not valid_steps:
                result["error"] = "utg.json 中没有有效的 ui_summary 步骤"
                return result

            logger.info(f"  有效步骤: {len(valid_steps)} / {loader.total_steps} 总步骤")

            # Step 2: 决策注入步
            logger.info("LLM 决策注入步...")
            decision = self._decide_injection_step(loader, anomaly_scenario)
            injection_step = decision.get("injection_step")
            decision_reason = decision.get("reason", "")

            if injection_step is None or injection_step < 0:
                result["error"] = f"LLM 未返回有效的注入步: {decision}"
                result["decision"] = decision
                return result

            if injection_step >= len(valid_steps):
                result["error"] = (
                    f"LLM 返回的注入步 {injection_step} 超出有效范围 "
                    f"(0-{len(valid_steps) - 1})"
                )
                return result

            target_step = valid_steps[injection_step]
            logger.info(f"  ✓ 注入步: Step {injection_step} (stepId={target_step.step_id})")
            logger.info(f"  理由: {decision_reason[:120]}")

            # Step 3: 改写 ui_summary
            logger.info("LLM 改写 ui_summary...")
            rewritten = self._rewrite_ui_summary(target_step, injection_step, anomaly_scenario)
            logger.info(f"  ✓ 改写完成 ({len(rewritten)} chars)")

            # Step 4: 组装修改后 utg
            modified_utg = self._build_modified_utg(loader, injection_step, rewritten)

            if output_path:
                self.save(modified_utg, output_path)
                logger.info(f"  ✓ 已保存: {output_path}")

            result["success"] = True
            result["modified_utg"] = modified_utg
            result["injection_step"] = injection_step
            result["step_id"] = target_step.step_id
            result["original_ui_summary"] = target_step.ui_summary
            result["rewritten_ui_summary"] = rewritten
            result["decision_reason"] = decision_reason
            return result

        except Exception as e:
            logger.exception("异常注入流程失败")
            result["error"] = str(e)
            return result

    def _decide_injection_step(self, loader: UTGLoader, anomaly_scenario: str) -> Dict:
        steps_text = loader.get_summary_text()
        prompt = DECISION_PROMPT.format(
            anomaly_scenario=anomaly_scenario, steps_text=steps_text,
        )
        raw = self.llm.chat(prompt)
        parsed = self.llm.extract_json(raw)

        injection_step = parsed.get("injection_step")
        if isinstance(injection_step, str):
            valid_steps = loader.get_valid_steps()
            for i, s in enumerate(valid_steps):
                if s.step_id == injection_step or str(i) == injection_step:
                    injection_step = i
                    break
            else:
                injection_step = int(injection_step) if injection_step.isdigit() else -1

        return {"injection_step": injection_step, "reason": parsed.get("reason", ""), "raw_response": raw}

    def _rewrite_ui_summary(self, step, step_index: int, anomaly_scenario: str) -> str:
        prompt = REWRITE_PROMPT.format(
            anomaly_scenario=anomaly_scenario,
            step_index=step_index,
            thought=step.thought.strip() if step.thought else "(无)",
            action_type=step.action_type.strip() if step.action_type else "(无)",
            original_ui_summary=step.ui_summary,
        )
        rewritten = self.llm.chat(prompt).strip()

        # 清理 markdown 包裹
        if rewritten.startswith("```") and rewritten.endswith("```"):
            rewritten = re.sub(r'^```(?:text|plain|json)?\s*', '', rewritten)
            rewritten = re.sub(r'\s*```$', '', rewritten)
            rewritten = rewritten.strip()

        if not rewritten:
            logger.warning("LLM 返回空改写结果，使用原始 ui_summary")
            return step.ui_summary
        return rewritten

    def _build_modified_utg(self, loader: UTGLoader, injection_step: int, rewritten_ui_summary: str) -> Dict:
        valid_steps = loader.get_valid_steps()
        target = valid_steps[injection_step]
        target_step_id = target.step_id
        modified = deepcopy(loader._raw)

        replaced = False
        for item in modified.get("stepData", []):
            if str(item.get("stepId", "")) == target_step_id:
                item["ui_summary"] = rewritten_ui_summary
                replaced = True
                break

        if not replaced:
            valid_idx = 0
            for item in modified.get("stepData", []):
                sid = str(item.get("stepId", ""))
                if sid.lower() not in {"home", "end", "start"} and item.get("ui_summary", "").strip():
                    if valid_idx == injection_step:
                        item["ui_summary"] = rewritten_ui_summary
                        break
                    valid_idx += 1

        return modified

    @staticmethod
    def save(modified_utg: Dict, output_path: str) -> str:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(modified_utg, f, ensure_ascii=False, indent=2)
        return str(path)
