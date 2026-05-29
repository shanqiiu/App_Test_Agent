"""
utg_anomaly_injector.py — 增强版异常注入器（Phase 1）

相比原始版本的增强：
1. 上下文感知改写：改写时引入前后步骤的 ui_summary，保证逻辑连贯
2. 相邻步联动微调：注入后自动调整前后步骤描述，形成因果链
3. 多步注入：支持一次注入多个异常场景
4. 晦涩表述检测：避免生成开发/测试术语
5. 注入后验证：确保改写结果质量

独立模块，仅依赖 llm_client 和 utg_loader。
"""

import json
import logging
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from .llm_client import LLMClient
from .utg_loader import UTGLoader
from ..prompts import (
    DECISION_PROMPT,
    REWRITE_PROMPT,
    NEIGHBOR_ADJUST_PROMPT,
    VALIDATION_PROMPT,
)

logger = logging.getLogger(__name__)

# ── 晦涩表述黑名单 ──────────────────────────────────────

OBSCURE_PATTERNS = [
    r'\bexception\b', r'\berror\b', r'\bnull\b', r'\bundefined\b',
    r'\btimeout\b', r'\bfailed\b', r'\bfailure\b',
    r'HTTP\s*\d{3}', r'状态码', r'异常码',
    r'Async\w*Exception', r'Runtime\w*Error',
    r'数据库查询', r'接口返回', r'后端返回',
    r'抛出', r'捕获到异常',
    r'JSON\s*解析', r'请求失败',
    r'网络请求超时', r'API\s*调用',
]

NATURAL_ALTERNATIVES = {
    "网络错误": {
        "晦涩": "系统抛出NetworkErrorException",
        "自然": "页面顶部提示'网络连接失败，轻触屏幕重试'，内容区域显示空白占位图",
    },
    "价格异常": {
        "晦涩": "价格字段返回null导致显示异常",
        "自然": "商品价格显示为'¥0.00'，明显低于正常售价，价格文字颜色变为红色警示",
    },
    "加载失败": {
        "晦涩": "列表数据查询超时报错",
        "自然": "页面列表区域持续显示加载中动画，超过10秒仍未加载出内容，底部提示'加载失败，点击重试'",
    },
    "图片异常": {
        "晦涩": "图片资源URL返回404",
        "自然": "商品图片位置显示为灰色破损图标，图片无法加载，替代文字显示'图片加载失败'",
    },
}

# ── Prompt 模板 ──────────────────────────────────────────

def _contains_obscure(text: str) -> List[str]:
    """检测文本中是否包含晦涩表述"""
    found = []
    for pattern in OBSCURE_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        found.extend(matches)
    return found

def _clean_obscure(text: str) -> str:
    """对已知的晦涩模式做基本清理"""
    # 移除异常的堆栈/类名样式的文本
    text = re.sub(r'\w+(?:Exception|Error|Failure)\b', '异常', text)
    # 替换 HTTP 状态码
    text = re.sub(r'HTTP\s*\d{3}', '错误提示', text)
    # 替换 API/后端/数据库等开发者视角词
    text = re.sub(r'API\s*调用', '请求', text)
    text = re.sub(r'数据库查询', '数据加载', text)
    text = re.sub(r'后端返回', '页面显示', text)
    return text

def _format_context(context: str, label: str, max_chars: int = 300) -> str:
    """格式化上下文文本"""
    if not context or context == "(无)":
        return f"  {label}: (无前序步骤)"
    truncated = context.strip()[:max_chars]
    return f"  {label}: {truncated}"

class UTGAnomalyInjector:
    """
    UTG 异常注入器（增强版）

    流程：
    1. 加载 utg_info.json → UTGLoader
    2. LLM 决策注入步（支持多步注入）
    3. LLM 上下文感知改写 ui_summary
    4. 相邻步联动微调（保证连贯性）
    5. 注入后质量验证
    6. 组装修改后 utg_info.json
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
        self.llm_validate = LLMClient(
            api_key=api_key,
            api_url=api_url,
            model=model,
            temperature=0.0,
            max_tokens=512,
        )

    # ── 单异常注入（增强版） ─────────────────────────────

    def inject(
        self,
        utg_path: str,
        anomaly_scenario: str,
        output_path: Optional[str] = None,
        enable_neighbor_adjust: bool = True,
        enable_validation: bool = True,
    ) -> Dict[str, Any]:
        """
        执行增强的异常注入流程（上下文感知 + 相邻步联动 + 验证）。

        Args:
            utg_path: utg_info.json 路径
            anomaly_scenario: 异常场景描述
            output_path: 输出路径
            enable_neighbor_adjust: 是否启用相邻步微调
            enable_validation: 是否启用注入后验证

        Returns:
            包含详细注入信息的字典
        """
        result = {
            "success": False,
            "modified_utg": None,
            "injection_step": None,
            "step_id": None,
            "original_ui_summary": None,
            "rewritten_ui_summary": None,
            "neighbor_adjustments": [],
            "validation": None,
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

            # Step 1: 决策注入步
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

            # Step 2: 上下文感知改写
            logger.info("LLM 上下文感知改写 ui_summary...")

            # 获取前后步骤的 ui_summary
            prev_summary = valid_steps[injection_step - 1].ui_summary if injection_step > 0 else ""
            next_summary = valid_steps[injection_step + 1].ui_summary if injection_step < len(valid_steps) - 1 else ""

            rewritten = self._rewrite_ui_summary_context_aware(
                target_step, injection_step, anomaly_scenario,
                prev_summary, next_summary,
            )
            logger.info(f"  ✓ 改写完成 ({len(rewritten)} chars)")

            # 晦涩表述检测与清理
            obscure_terms = _contains_obscure(rewritten)
            if obscure_terms:
                logger.warning(f"  ⚠ 发现 {len(obscure_terms)} 处晦涩表述: {obscure_terms[:5]}")
                rewritten = _clean_obscure(rewritten)
                logger.info(f"  → 已清理晦涩表述")

            # Step 3: 相邻步联动微调
            neighbor_adjusts = []
            if enable_neighbor_adjust:
                neighbor_adjusts = self._adjust_neighbor_steps(
                    loader, valid_steps, injection_step, rewritten, anomaly_scenario,
                )
                if neighbor_adjusts:
                    logger.info(f"  ✓ 相邻步微调: {len(neighbor_adjusts)} 步")

            # Step 4: 注入后验证
            validation_result = None
            if enable_validation:
                validation_result = self._validate_injection(
                    target_step.ui_summary, rewritten, anomaly_scenario,
                )
                if validation_result:
                    if validation_result.get("is_valid"):
                        logger.info("  ✓ 注入验证通过")
                    else:
                        issues = validation_result.get("issues", [])
                        logger.warning(f"  ⚠ 注入验证发现问题: {issues}")
                else:
                    logger.info("  ✓ 注入验证: LLM 不可用，跳过")

            # Step 5: 组装修改后 utg
            modified_utg = self._build_modified_utg(
                loader, valid_steps, injection_step, rewritten, neighbor_adjusts,
            )

            if output_path:
                self.save(modified_utg, output_path)
                logger.info(f"  ✓ 已保存: {output_path}")

            result["success"] = True
            result["modified_utg"] = modified_utg
            result["injection_step"] = injection_step
            result["step_id"] = target_step.step_id
            result["original_ui_summary"] = target_step.ui_summary
            result["rewritten_ui_summary"] = rewritten
            result["neighbor_adjustments"] = neighbor_adjusts
            result["validation"] = validation_result
            result["decision_reason"] = decision_reason
            return result

        except Exception as e:
            logger.exception("异常注入流程失败")
            result["error"] = str(e)
            return result

    # ── 多异常注入 ────────────────────────────────────────

    def inject_multiple(
        self,
        utg_path: str,
        anomaly_scenarios: List[str],
        output_path: Optional[str] = None,
        enable_neighbor_adjust: bool = True,
        enable_validation: bool = True,
    ) -> Dict[str, Any]:
        """
        一次运行注入多个异常场景。

        策略：
        - 每次选择不同的步骤
        - 已注入的步骤不再参与后续决策
        - 所有异常类型记录在 anomalyTag 中
        """
        result = {
            "success": False,
            "modified_utg": None,
            "injection_details": [],
            "error": None,
        }

        try:
            # 第一步：仅加载用于注入
            loader = UTGLoader(utg_path)
            modified_utg = deepcopy(loader._raw)

            used_step_indices = set()
            all_details = []

            for i, scenario in enumerate(anomaly_scenarios):
                logger.info(f"\n--- 异常 {i + 1}/{len(anomaly_scenarios)}: {scenario[:60]} ---")

                # 重新加载（因为 modified_utg 可能在变化，但这里用原始 utg 进行决策
                # 以保证每次决策的输入一致）
                temp_loader = UTGLoader(utg_path)
                valid_steps = temp_loader.get_valid_steps()

                if not valid_steps:
                    logger.warning(f"  跳过: 无有效步骤")
                    continue

                # 过滤已使用的步骤
                available_steps = [
                    (idx, s) for idx, s in enumerate(valid_steps)
                    if idx not in used_step_indices
                ]
                if not available_steps:
                    logger.warning(f"  跳过: 无可用的未注入步骤")
                    continue

                # 决策（使用可用步骤的子集）
                decision = self._decide_injection_step(
                    temp_loader, scenario, exclude_indices=list(used_step_indices),
                )
                injection_step = decision.get("injection_step")

                if injection_step is None or injection_step < 0:
                    logger.warning(f"  跳过: 无法决策注入步")
                    continue

                if injection_step >= len(valid_steps):
                    continue

                used_step_indices.add(injection_step)
                target_step = valid_steps[injection_step]

                # 上下文感知改写
                prev_summary = valid_steps[injection_step - 1].ui_summary if injection_step > 0 else ""
                next_summary = valid_steps[injection_step + 1].ui_summary if injection_step < len(valid_steps) - 1 else ""

                rewritten = self._rewrite_ui_summary_context_aware(
                    target_step, injection_step, scenario,
                    prev_summary, next_summary,
                )

                # 晦涩表述清理
                obscure_terms = _contains_obscure(rewritten)
                if obscure_terms:
                    rewritten = _clean_obscure(rewritten)

                # 相邻步微调
                neighbor_adjusts = []
                if enable_neighbor_adjust:
                    neighbor_adjusts = self._adjust_neighbor_steps(
                        temp_loader, valid_steps, injection_step, rewritten, scenario,
                    )

                # 直接修改 modified_utg
                for item in modified_utg.get("stepData", []):
                    if str(item.get("stepId", "")) == target_step.step_id:
                        item["ui_summary"] = rewritten
                        break

                # 相邻步修改
                for adj in neighbor_adjusts:
                    adj_step_id = adj.get("step_id")
                    adj_text = adj.get("adjusted_text", "")
                    for item in modified_utg.get("stepData", []):
                        if str(item.get("stepId", "")) == adj_step_id:
                            item["ui_summary"] = adj_text
                            break

                detail = {
                    "anomaly_index": i,
                    "anomaly_scenario": scenario,
                    "injection_step": injection_step,
                    "step_id": target_step.step_id,
                    "original_ui_summary": target_step.ui_summary[:200],
                    "rewritten_ui_summary": rewritten[:200],
                    "decision_reason": decision.get("reason", ""),
                    "neighbor_adjustments": neighbor_adjusts,
                }
                all_details.append(detail)
                logger.info(f"  ✓ 注入完成: Step {injection_step}")

            if not all_details:
                result["error"] = "未能注入任何异常"
                return result

            if output_path:
                self.save(modified_utg, output_path)
                logger.info(f"  ✓ 已保存: {output_path}")

            result["success"] = True
            result["modified_utg"] = modified_utg
            result["injection_details"] = all_details
            return result

        except Exception as e:
            logger.exception("多异常注入失败")
            result["error"] = str(e)
            return result

    # ── 决策 ──────────────────────────────────────────────

    def _decide_injection_step(
        self,
        loader: UTGLoader,
        anomaly_scenario: str,
        exclude_indices: Optional[List[int]] = None,
    ) -> Dict:
        """LLM 决策注入步"""
        steps_text = loader.get_summary_text()

        # 如果排除了某些步骤，在 steps_text 中标记
        if exclude_indices:
            lines = steps_text.split("\n")
            marked_lines = []
            step_counter = 0
            for line in lines:
                if line.startswith("Step "):
                    if step_counter in exclude_indices:
                        marked_lines.append(line + " [已注入异常，请勿选择]")
                    else:
                        marked_lines.append(line)
                    step_counter += 1
                else:
                    marked_lines.append(line)
            steps_text = "\n".join(marked_lines)

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

        return {
            "injection_step": injection_step,
            "reason": parsed.get("reason", ""),
            "raw_response": raw,
        }

    # ── 上下文感知改写 ────────────────────────────────────

    def _rewrite_ui_summary_context_aware(
        self,
        step,
        step_index: int,
        anomaly_scenario: str,
        prev_summary: str = "",
        next_summary: str = "",
    ) -> str:
        """
        上下文感知改写：提供前后步骤的 ui_summary 作为参考，
        确保改写后的描述在序列中逻辑连贯。
        """
        prev_text = _format_context(prev_summary, "前一步骤")
        next_text = _format_context(next_summary, "后一步骤")

        prompt = REWRITE_PROMPT.format(
            anomaly_scenario=anomaly_scenario,
            step_index=step_index,
            thought=step.thought.strip() if step.thought else "(无)",
            action_type=step.action_type.strip() if step.action_type else "(无)",
            original_ui_summary=step.ui_summary,
            prev_summary=prev_text,
            next_summary=next_text,
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

    # ── 相邻步联动微调 ────────────────────────────────────

    def _adjust_neighbor_steps(
        self,
        loader: UTGLoader,
        valid_steps: List,
        injection_step: int,
        rewritten_summary: str,
        anomaly_scenario: str,
    ) -> List[Dict]:
        """
        注入后微调相邻步骤的 ui_summary，使异常在序列中自然流动。

        策略（扩展版，前后各 2 步）：
        - 前 2 步：微调使其操作结果自然引向异常
        - 前 1 步：微调作为异常的直接前导
        - 后 1 步：微调使其体现异常的直接影响
        - 后 2 步：微调体现异常的残余效应（如用户尝试恢复、数据逐步恢复）
        """
        adjustments = []

        # 需要微调的偏移量列表：(offset, position_label)
        offsets = []
        if injection_step > 1:
            offsets.append((-2, "前2"))
        if injection_step > 0:
            offsets.append((-1, "前1"))
        if injection_step < len(valid_steps) - 1:
            offsets.append((1, "后1"))
        if injection_step < len(valid_steps) - 2:
            offsets.append((2, "后2"))

        for offset, pos in offsets:
            neighbor_idx = injection_step + offset
            if neighbor_idx < 0 or neighbor_idx >= len(valid_steps):
                continue

            neighbor_step = valid_steps[neighbor_idx]
            try:
                prompt = NEIGHBOR_ADJUST_PROMPT.format(
                    pos=pos,
                    step_index=neighbor_idx,
                    anomaly_scenario=anomaly_scenario,
                    current_step_description=rewritten_summary[:300],
                    original_ui_summary=neighbor_step.ui_summary,
                    thought=neighbor_step.thought.strip() if neighbor_step.thought else "(无)",
                    action_type=neighbor_step.action_type.strip() if neighbor_step.action_type else "(无)",
                )
                adjusted = self.llm.chat(prompt).strip()
                if adjusted and len(adjusted) > 20:
                    adjustments.append({
                        "position": pos,
                        "step_index": neighbor_idx,
                        "step_id": neighbor_step.step_id,
                        "original": neighbor_step.ui_summary[:200],
                        "adjusted_text": adjusted,
                    })
                    logger.debug(f"  {pos}步微调: Step {neighbor_idx}")
            except Exception as e:
                logger.debug(f"  {pos}步微调跳过: {e}")

        return adjustments

    # ── 注入后验证 ────────────────────────────────────────

    def _validate_injection(
        self,
        original: str,
        rewritten: str,
        scenario: str,
    ) -> Optional[Dict]:
        """
        验证注入结果质量。

        检查：
        1. 非空且足够长
        2. 无晦涩表述
        3. 保留了原始页面核心结构
        4. 异常描述自然融入
        """
        # Rule-based 快速检查
        issues = []

        if not rewritten or len(rewritten) < 20:
            issues.append(f"改写结果过短 ({len(rewritten)} chars)")

        obscures = _contains_obscure(rewritten)
        if obscures:
            issues.append(f"含有晦涩表述: {obscures[:3]}")

        # LLM 验证
        if self.llm_validate:
            try:
                prompt = VALIDATION_PROMPT.format(
                    original=original[:500],
                    rewritten=rewritten[:500],
                    scenario=scenario[:200],
                )
                raw = self.llm_validate.chat(prompt)
                parsed = self.llm_validate.extract_json(raw)
                if not parsed.get("is_valid", True):
                    llm_issues = parsed.get("issues", [])
                    issues.extend(llm_issues)
                return {
                    "is_valid": len(issues) == 0,
                    "issues": issues,
                    "llm_validation": parsed,
                    "suggestion": parsed.get("suggestion", ""),
                }
            except Exception:
                pass

        return {
            "is_valid": len(issues) == 0,
            "issues": issues,
            "llm_validation": None,
            "suggestion": "",
        }

    # ── 组装修改后 utg ────────────────────────────────────

    def _build_modified_utg(
        self,
        loader: UTGLoader,
        valid_steps: List,
        injection_step: int,
        rewritten_ui_summary: str,
        neighbor_adjustments: List[Dict],
    ) -> Dict:
        """组装修改后的 utg_info.json，包含相邻步的微调"""
        modified = deepcopy(loader._raw)

        # 构建 stepId → ui_summary 的映射
        updates = {}
        updates[valid_steps[injection_step].step_id] = rewritten_ui_summary

        for adj in neighbor_adjustments:
            updates[adj["step_id"]] = adj["adjusted_text"]

        # 应用到 modified_utg
        replaced_count = 0
        for item in modified.get("stepData", []):
            sid = str(item.get("stepId", ""))
            if sid in updates:
                item["ui_summary"] = updates[sid]
                replaced_count += 1

        # Fallback: 按有效步骤索引
        if replaced_count == 0:
            valid_idx = 0
            for item in modified.get("stepData", []):
                sid = str(item.get("stepId", ""))
                if sid.lower() not in {"home", "end", "start"} and item.get("ui_summary", "").strip():
                    if valid_idx == injection_step:
                        item["ui_summary"] = rewritten_ui_summary
                    for adj in neighbor_adjustments:
                        if adj.get("position") == "prev" and valid_idx == injection_step - 1:
                            item["ui_summary"] = adj["adjusted_text"]
                        if adj.get("position") == "next" and valid_idx == injection_step + 1:
                            item["ui_summary"] = adj["adjusted_text"]
                    valid_idx += 1

        return modified

    # ── 保存 ──────────────────────────────────────────────

    @staticmethod
    def save(modified_utg: Dict, output_path: str) -> str:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(modified_utg, f, ensure_ascii=False, indent=2)
        return str(path)
