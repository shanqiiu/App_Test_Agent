"""
utg_preprocessor.py — UTG 数据预处理器（Phase 0）

在异常注入之前，把原始 utg_info.json 的质量问题修复到可接受水平。

三阶段流程：
  1. 去重合并（Rule-based）: 连续相同页面指纹的步骤合并
  2. 动作驱动重写（LLM）: 页面状态快照 → "用户动作→系统响应" 格式
  3. 数据对齐（LLM）: 商品名、价格跨步骤一致性修正
  4. 页面补齐（Rule + LLM）: 补充 ProductDetail、OrderDetail 等关键缺失页面

独立模块，仅依赖 llm_client 和 utg_loader。
"""

import json
import logging
import re
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from .llm_client import LLMClient
from .utg_loader import UTGLoader, UTGStep
from ..prompts import (
    ACTION_REWRITE_PROMPT,
    BATCH_ACTION_REWRITE_PROMPT,
    BATCH_SEMANTIC_DEDUP_PROMPT,
    DATA_ALIGN_PROMPT,
    PAGE_COMPLETE_PROMPT,
    SEMANTIC_DEDUP_PROMPT,
    CAUSAL_REPAIR_PROMPT,
    SHOPPING_PAGE_TOPOLOGY,
)

logger = logging.getLogger(__name__)

# ── 规则模式（非 Prompt，保留） ──────────────────────

ANOMALY_PATTERNS = [
    r'网络连接失败', r'网络错误', r'加载失败', r'无法加载',
    r'空白占位图', r'内容区域为空', r'白屏', r'黑屏',
    r'错误提示', r'显示异常', r'请求超时', r'服务不可用',
    r'页面崩溃', r'闪退', r'无响应',
]

RECOVERY_PATTERNS = [
    r'重试', r'刷新', r'恢复', r'重新加载', r'重新进入',
    r'返回.*重', r'点击.*刷新', r'网络.*恢复', r'数据.*加载成功',
    r'页面.*正常', r'自动.*恢复', r'重新.*登录',
]


def _compute_page_fingerprint(ui_summary: str, n_chars: int = 50) -> str:
    """计算页面指纹：取 ui_summary 前 n_chars 个字符，去除非中文字符和空白"""
    if not ui_summary:
        return ""
    # 取前 n_chars 并清理
    raw = ui_summary.strip()[:n_chars]
    # 提取关键内容（去掉标点符号和空白）
    key = re.sub(r'[\s,，。！？、；：""''【】《》（）\!\?\.\,\;\:\'\"\(\)\[\]\{\}]', '', raw)
    return key


def _get_action_type_label(action_type: str) -> str:
    """从 action_type 推断用户操作类型"""
    if not action_type:
        return "点击"
    at = action_type.lower()
    if "set_text" in at or "input" in at:
        return "输入"
    if "click" in at:
        return "点击"
    if "back" in at:
        return "返回"
    if "swipe" in at or "scroll" in at:
        return "滑动"
    if "clarify" in at:
        return "确认"
    return "点击"


class UTGPreprocessor:
    """UTG 数据预处理器（Phase 0）"""

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
        )

    # ── Phase 0-1: 去重合并（Rule-based） ────────────────

    def deduplicate(self, loader: UTGLoader) -> Tuple[List[UTGStep], Dict]:
        """
        基于页面指纹合并连续重复步骤。

        Returns:
            (去重后的有效步骤列表, 去重统计信息)
        """
        valid = loader.get_valid_steps()
        if not valid:
            return [], {"removed": 0, "total_before": 0, "total_after": 0}

        stat = {"total_before": len(valid), "removed": 0, "merged_groups": []}

        deduped = []
        last_fingerprint = None
        current_group = []

        for step in valid:
            fp = _compute_page_fingerprint(step.ui_summary)
            if fp and fp == last_fingerprint:
                current_group.append(step)
                stat["removed"] += 1
            else:
                if current_group:
                    # 保留组内第一条
                    deduped.append(current_group[0])
                    if len(current_group) > 1:
                        stat["merged_groups"].append(
                            f"Step{current_group[0].step_id}~Step{current_group[-1].step_id}"
                        )
                current_group = [step]
                last_fingerprint = fp

        # 处理最后一组
        if current_group:
            deduped.append(current_group[0])
            if len(current_group) > 1:
                stat["merged_groups"].append(
                    f"Step{current_group[0].step_id}~Step{current_group[-1].step_id}"
                )

        stat["total_after"] = len(deduped)
        logger.info(
            f"  去重: {stat['total_before']} → {stat['total_after']} "
            f"(移除 {stat['removed']} 步)"
        )
        if stat["merged_groups"]:
            logger.info(f"  合并组: {', '.join(stat['merged_groups'])}")

        return deduped, stat

    # ── Phase 0-1b: 语义兜底去重（LLM） ──────────────

    def _semantic_deduplicate(self, steps: List[UTGStep]) -> Tuple[List[UTGStep], Dict]:
        """
        L2 语义去重：批量模式一次 LLM 判断所有相邻对，回退到逐对模式兜底。
        """
        if len(steps) < 2:
            return steps, {"l2_removed": 0, "l2_merged": [], "l2_checks": 0}

        stat = {"l2_removed": 0, "l2_merged": [], "l2_checks": 0}

        # ── 构建候选对（排除操作类型明显不同的组合） ──
        candidates = []  # [(index, curr_step, next_step)]
        for i in range(len(steps) - 1):
            curr = steps[i]
            nxt = steps[i + 1]
            curr_act = _get_action_type_label(curr.action_type)
            next_act = _get_action_type_label(nxt.action_type)
            if curr_act != next_act and curr_act != "点击" and next_act != "点击":
                continue  # 操作类型完全不同 → 必定不同页面
            candidates.append((i, curr, nxt))

        if not candidates:
            return steps, stat

        # ── 批量 LLM 调用 ──
        stat["l2_checks"] = len(candidates)
        same_indices = set()

        try:
            pairs_lines = []
            for idx, (i, curr, nxt) in enumerate(candidates):
                pairs_lines.append(
                    f"[{idx}] Step{curr.step_id}: {curr.ui_summary}\n"
                    f"     Step{nxt.step_id}: {nxt.ui_summary}"
                )
            pairs_text = "\n\n".join(pairs_lines)

            prompt = BATCH_SEMANTIC_DEDUP_PROMPT.format(
                pair_count=len(candidates),
                pairs_text=pairs_text,
            )
            logger.info(f"  批量语义去重: {len(candidates)} 对 → 1 次 LLM")
            raw = self.llm.chat(prompt)
            parsed = self.llm.extract_json(raw)

            if isinstance(parsed, list) and len(parsed) == len(candidates):
                for idx, result in enumerate(parsed):
                    if isinstance(result, str) and result.strip().lower().startswith("same"):
                        same_indices.add(candidates[idx][0])
                logger.info(f"  批量去重结果: {len(same_indices)} 对合并")
            else:
                logger.warning("  批量去重返回格式异常，回退逐对模式")
                return self._semantic_deduplicate_sequential(steps, stat)
        except Exception as e:
            logger.warning(f"  批量去重失败: {e}，回退逐对模式")
            return self._semantic_deduplicate_sequential(steps, stat)

        # ── 应用合并结果 ──
        merged = []
        skip_next = False
        for i in range(len(steps)):
            if skip_next:
                skip_next = False
                continue
            if i == len(steps) - 1:
                merged.append(steps[i])
                break
            if i in same_indices:
                merged.append(steps[i])
                skip_next = True
                stat["l2_removed"] += 1
                stat["l2_merged"].append(
                    f"Step{steps[i].step_id}~Step{steps[i+1].step_id}"
                )
                logger.info(
                    f"  L2 语义合并: Step{steps[i].step_id} + Step{steps[i+1].step_id}"
                )
            else:
                merged.append(steps[i])

        logger.info(
            f"  语义去重: {len(candidates)} 对 → {stat['l2_removed']} 组合并"
        )
        return merged, stat

    def _semantic_deduplicate_sequential(
        self, steps: List[UTGStep], stat: Dict
    ) -> Tuple[List[UTGStep], Dict]:
        """逐对语义去重（批量失败时的兜底）"""
        merged = []
        skip_next = False

        for i in range(len(steps)):
            if skip_next:
                skip_next = False
                continue
            if i == len(steps) - 1:
                merged.append(steps[i])
                break

            curr = steps[i]
            next_step = steps[i + 1]

            # 快速预判
            curr_act = _get_action_type_label(curr.action_type)
            next_act = _get_action_type_label(next_step.action_type)
            if curr_act != next_act and curr_act != "点击" and next_act != "点击":
                merged.append(curr)
                continue

            stat["l2_checks"] += 1
            try:
                prompt = SEMANTIC_DEDUP_PROMPT.format(
                    summary_a=curr.ui_summary,
                    summary_b=next_step.ui_summary,
                )
                logger.info(
                    f"  L2 语义比较 Step{curr.step_id} vs Step{next_step.step_id} ..."
                )
                result = self.llm.chat(prompt).strip().lower()
                logger.info(
                    f"  L2 结果: Step{curr.step_id} vs Step{next_step.step_id} → {result}"
                )

                if result.startswith("same"):
                    merged.append(curr)
                    skip_next = True
                    stat["l2_removed"] += 1
                    stat["l2_merged"].append(
                        f"Step{curr.step_id}~Step{next_step.step_id}"
                    )
                    logger.info(f"  L2 语义合并: Step{curr.step_id} + Step{next_step.step_id}")
                else:
                    merged.append(curr)
            except Exception as e:
                logger.warning(f"  L2 语义比较异常 (Step{curr.step_id}): {e}")
                merged.append(curr)

        return merged, stat

    # ── Phase 0-2: 动作驱动重写（LLM 批量模式） ──────────

    def rewrite_to_action_driven(
        self, steps: List[UTGStep], batch_size: int = 5
    ) -> Tuple[List[str], Dict]:
        """
        批量重写：一次 LLM 调用处理全部步骤，返回 JSON 数组。
        相比逐步串行（N 次 LLM），批量模式只需 1 次调用。

        Args:
            steps: 有效步骤列表
            batch_size: 保留参数（兼容，批量模式不分组）

        Returns:
            (重写后的 ui_summary 列表, 重写统计)
        """
        stat = {"total": len(steps), "success": 0, "failed": 0, "skipped": 0,
                "mode": "batch"}

        effective_steps = [s for s in steps if s.ui_summary.strip()]
        if not effective_steps:
            for s in steps:
                stat["skipped"] += 1
            return [s.ui_summary for s in steps], stat

        # ── 构建批量步骤文本 ──
        step_lines = []
        for s in effective_steps:
            action_label = _get_action_type_label(s.action_type)
            thought = s.thought.strip() if s.thought else action_label
            step_lines.append(
                f"Step {s.step_id}: [{action_label}] {thought}\n"
                f"  页面描述: {s.ui_summary}"
            )
        steps_text = "\n\n".join(step_lines)

        prompt = BATCH_ACTION_REWRITE_PROMPT.format(
            step_count=len(effective_steps),
            steps_text=steps_text,
        )

        try:
            logger.info(f"  批量重写: {len(effective_steps)} 步 → 1 次 LLM")
            raw = self.llm.chat(prompt)
            parsed = self.llm.extract_json(raw)

            if isinstance(parsed, list) and len(parsed) == len(effective_steps):
                # 构建完整结果列表（含跳过的空步骤）
                result_list = []
                parsed_idx = 0
                for s in steps:
                    if s.ui_summary.strip():
                        result_list.append(str(parsed[parsed_idx]).strip('"\''))
                        stat["success"] += 1
                        parsed_idx += 1
                    else:
                        result_list.append(s.ui_summary)
                        stat["skipped"] += 1

                logger.info(
                    f"  批量重写完成: {stat['success']}/{len(effective_steps)} 成功"
                )
                return result_list, stat
            else:
                logger.warning(
                    f"  批量重写返回格式异常 (type={type(parsed).__name__}, "
                    f"len={len(parsed) if isinstance(parsed, list) else 'N/A'}), "
                    f"回退到逐步模式"
                )
        except Exception as e:
            logger.warning(f"  批量重写失败: {e}，回退到逐步模式")

        # ── 回退：单步串行（兼容 LLM 返回格式异常时） ──
        stat["mode"] = "sequential_fallback"
        return self._rewrite_sequential(steps, stat)

    def _rewrite_sequential(
        self, steps: List[UTGStep], stat: Dict
    ) -> Tuple[List[str], Dict]:
        """单步串行重写（批量模式失败时的兜底）"""
        rewritten = []
        for step in steps:
            ui_summary = step.ui_summary.strip()
            if not ui_summary:
                rewritten.append(ui_summary)
                stat["skipped"] += 1
                continue

            action_label = _get_action_type_label(step.action_type)
            thought = step.thought.strip() if step.thought else action_label

            prompt = ACTION_REWRITE_PROMPT.format(
                ui_summary=ui_summary,
                thought=thought,
                action_type=action_label,
            )

            try:
                result = self.llm.chat(prompt).strip().strip('"\'')
                if result:
                    rewritten.append(result)
                    stat["success"] += 1
                else:
                    rewritten.append(ui_summary)
                    stat["skipped"] += 1
            except Exception as e:
                logger.warning(f"  Step {step.step_id}: LLM 重写失败: {e}")
                rewritten.append(ui_summary)
                stat["failed"] += 1

        logger.info(
            f"  逐步重写: {stat['success']} 成功, {stat['failed']} 失败, "
            f"{stat['skipped']} 跳过"
        )
        return rewritten, stat

    # ── Phase 0-3: 数据对齐（LLM） ────────────────────────

    def align_data(
        self, loader: UTGLoader, steps: List[UTGStep], rewritten: List[str]
    ) -> Tuple[List[str], Dict]:
        """
        跨步骤数据一致性检查和修正。

        Args:
            loader: UTG 数据加载器
            steps: 当前有效步骤列表（去重后）
            rewritten: 当前重写后的 ui_summary 列表

        Returns:
            (修正后的 ui_summary 列表, 修正详情)
        """
        result = {"issues_found": 0, "fixes": []}

        query = loader._raw.get("query", "")

        # 构建步骤文本供 LLM 分析
        steps_text = ""
        for i, (step, rw) in enumerate(zip(steps, rewritten)):
            steps_text += f"Step {i} (stepId={step.step_id}): {rw}\n\n"

        prompt = DATA_ALIGN_PROMPT.format(
            query=query, steps_text=steps_text
        )

        try:
            raw = self.llm.chat(prompt)
            parsed = self.llm.extract_json(raw)
            issues = parsed.get("issues", [])
            result["issues_found"] = len(issues)
            result["consistency_summary"] = parsed.get("consistency_summary", "")

            if not issues:
                logger.info("  数据对齐: 未发现问题")
                return rewritten, result

            # 应用修正
            for issue in issues:
                step_idx = issue.get("step_index")
                original = issue.get("original", "")
                corrected = issue.get("corrected", "")

                if step_idx is None or step_idx >= len(rewritten):
                    continue
                if not original or not corrected:
                    continue

                old_text = rewritten[step_idx]
                # 只替换第一次出现的 original
                if original in old_text:
                    new_text = old_text.replace(original, corrected, 1)
                    rewritten[step_idx] = new_text
                    result["fixes"].append({
                        "step_index": step_idx,
                        "field": issue.get("field", ""),
                        "original": original,
                        "corrected": corrected,
                    })
                    logger.info(
                        f"  Step {step_idx}: {issue.get('field', '')} "
                        f"'{original}' → '{corrected}'"
                    )
                else:
                    logger.debug(
                        f"  Step {step_idx}: 未找到 '{original}'，跳过修正"
                    )

        except Exception as e:
            logger.warning(f"  数据对齐 LLM 调用失败: {e}")

        return rewritten, result

    # ── Phase 0-4: 页面补齐 ──────────────────────────────

    def complete_pages(
        self,
        loader: UTGLoader,
        steps: List[UTGStep],
        rewritten: List[str],
        template_path: Optional[str] = None,
    ) -> Tuple[List[str], Dict]:
        """
        检查并补充缺失的关键页面（如 ProductDetail、OrderDetail）。

        Args:
            loader: UTG 数据加载器
            steps: 去重后的步骤列表
            rewritten: 当前 ui_summary 列表
            template_path: 模板文件路径（用于获取预期页面拓扑）

        Returns:
            (补充后的 ui_summary 列表, 补充详情)
        """
        result = {"inserted": [], "total_before": len(rewritten)}

        # 构建预期页面拓扑
        expected_topology = self._get_expected_topology(template_path)

        # 构建当前步骤文本
        steps_text = ""
        for i, rw in enumerate(rewritten):
            steps_text += f"Step {i}: {rw}\n"

        prompt = PAGE_COMPLETE_PROMPT.format(
            steps_text=steps_text,
            expected_topology=json.dumps(expected_topology, ensure_ascii=False),
        )

        try:
            raw = self.llm.chat(prompt)
            parsed = self.llm.extract_json(raw)
            missing = parsed.get("missing_pages", [])

            if not missing:
                logger.info("  页面补齐: 无缺失页面")
                return rewritten, result

            # 从后往前插入，避免索引偏移
            missing.sort(key=lambda x: x.get("insert_after_step", 0), reverse=True)

            for page in missing:
                insert_after = page.get("insert_after_step", 0)
                action_desc = page.get("action_description", "")
                page_name = page.get("page_name", "")

                if insert_after < 0:
                    insert_after = 0
                if insert_after >= len(rewritten):
                    rewritten.append(action_desc)
                else:
                    rewritten.insert(insert_after + 1, action_desc)

                result["inserted"].append({
                    "page_name": page_name,
                    "insert_after_step": insert_after,
                    "action_description": action_desc,
                })
                logger.info(f"  + 在 Step {insert_after} 后插入 '{page_name}'")

        except Exception as e:
            logger.warning(f"  页面补齐 LLM 调用失败: {e}")

        result["total_after"] = len(rewritten)
        return rewritten, result

    def _get_expected_topology(self, template_path: Optional[str] = None) -> List[str]:
        """从模板获取预期的页面拓扑"""
        if not template_path:
            return list(SHOPPING_PAGE_TOPOLOGY)

        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                template = json.load(f)
            return template.get("baselineMapping", {}).get(
                "screenKeys", list(SHOPPING_PAGE_TOPOLOGY)
            )
        except Exception:
            return list(SHOPPING_PAGE_TOPOLOGY)

    # ── 全流程（Phase 0） ─────────────────────────────────

    def run(
        self,
        utg_path: str,
        template_path: Optional[str] = None,
        output_path: Optional[str] = None,
        skip_dedup: bool = False,
        skip_rewrite: bool = False,
        skip_align: bool = False,
        skip_complete: bool = False,
    ) -> Dict[str, Any]:
        """
        执行完整的预处理流程。

        Args:
            utg_path: utg_info.json 路径
            template_path: 模板 JSON 路径（可选，用于补齐参考）
            output_path: 输出路径（可选）
            skip_dedup: 跳过去重
            skip_rewrite: 跳过动作重写
            skip_align: 跳过数据对齐
            skip_complete: 跳过页面补齐

        Returns:
            {
                "success": bool,
                "modified_utg": dict,
                "phases": {
                    "dedup": {...},
                    "rewrite": {...},
                    "align": {...},
                    "complete": {...},
                },
                "steps_before": int,
                "steps_after": int,
                "output_path": str|None,
            }
        """
        result = {
            "success": False,
            "modified_utg": None,
            "phases": {},
            "steps_before": 0,
            "steps_after": 0,
            "error": None,
        }

        try:
            loader = UTGLoader(utg_path)
            result["steps_before"] = loader.valid_count
            logger.info(f"Phase 0 开始: {loader.valid_count} 有效步骤")

            # Phase 0-1: 去重
            if not skip_dedup:
                deduped_steps, dedup_stat = self.deduplicate(loader)
                # L2 语义兜底去重：在 L1 规则基础上再次合并同页面步骤
                deduped_steps, semantic_stat = self._semantic_deduplicate(deduped_steps)
                result["phases"]["dedup"] = dedup_stat
                result["phases"]["semantic_dedup"] = semantic_stat
            else:
                deduped_steps = loader.get_valid_steps()
                result["phases"]["dedup"] = {
                    "skipped": True,
                    "total_before": len(deduped_steps),
                    "total_after": len(deduped_steps),
                }
                result["phases"]["semantic_dedup"] = {"skipped": True}

            # 初始 rewritten 来自各步的 ui_summary
            rewritten = [s.ui_summary for s in deduped_steps]

            # Phase 0-2: 动作驱动重写
            if not skip_rewrite:
                rewritten, rewrite_stat = self.rewrite_to_action_driven(deduped_steps)
                result["phases"]["rewrite"] = rewrite_stat
            else:
                result["phases"]["rewrite"] = {"skipped": True}

            # Phase 0-3: 数据对齐
            if not skip_align:
                rewritten, align_stat = self.align_data(
                    loader, deduped_steps, rewritten
                )
                result["phases"]["align"] = align_stat
            else:
                result["phases"]["align"] = {"skipped": True}

            # Phase 0-3.5: 因果链断裂检测与修复
            causal_breaks = self._validate_causal_chain(rewritten)
            if causal_breaks:
                rewritten = self._repair_causal_chain(rewritten, causal_breaks)
                result["phases"]["causal_repair"] = {
                    "breaks_found": len(causal_breaks),
                    "breaks_indices": causal_breaks,
                }
            else:
                result["phases"]["causal_repair"] = {"breaks_found": 0}

            # Phase 0-4: 页面补齐
            if not skip_complete:
                rewritten, complete_stat = self.complete_pages(
                    loader, deduped_steps, rewritten, template_path
                )
                result["phases"]["complete"] = complete_stat
            else:
                result["phases"]["complete"] = {"skipped": True}

            # 组装修改后 utg
            modified_utg = self._build_modified_utg(
                loader, deduped_steps, rewritten
            )
            result["modified_utg"] = modified_utg
            result["steps_after"] = len(rewritten)
            result["success"] = True

            if output_path:
                self.save(modified_utg, output_path)
                result["output_path"] = output_path
                logger.info(f"  ✓ 已保存: {output_path}")

            logger.info(
                f"Phase 0 完成: {result['steps_before']} → {result['steps_after']} 步"
            )
            return result

        except Exception as e:
            logger.exception("Phase 0 预处理失败")
            result["error"] = str(e)
            return result

    # ── Phase 0-5: 因果链断裂检测 ──────────────────────────

    def _validate_causal_chain(self, rewritten: List[str]) -> List[int]:
        """
        检测相邻步骤间的因果链断裂。

        规则：若 Step i 的最终状态包含异常（网络失败/空白页等），
        而 Step i+1 的初始状态没有任何恢复/过渡描述 → 标记为断裂。

        Returns:
            断裂点的前一步索引列表 (i)
        """
        breaks = []
        for i in range(len(rewritten) - 1):
            prev = rewritten[i]
            next_step = rewritten[i + 1]

            # 只检查前一步的描述的后半段（最终状态部分）
            prev_end = prev[-(min(len(prev), 200)):]

            # 检查是否含异常
            has_anomaly = any(
                re.search(pat, prev_end) for pat in ANOMALY_PATTERNS
            )
            if not has_anomaly:
                continue

            # 检查后一步是否含恢复/过渡描述
            has_recovery = any(
                re.search(pat, next_step) for pat in RECOVERY_PATTERNS
            )
            if not has_recovery:
                breaks.append(i)
                logger.warning(
                    f"  因果链断裂: Step {i} 存在异常但 Step {i+1} 无恢复过渡"
                )

        return breaks

    # ── Phase 0-5b: 因果链修复 ──────────────────────────────

    def _repair_causal_chain(
        self, rewritten: List[str], breaks: List[int]
    ) -> List[str]:
        """
        对断裂点调用 LLM 修复后一步的描述，插入恢复/过渡语句。

        Args:
            rewritten: 当前 ui_summary 列表
            breaks: 断裂点前一步索引列表

        Returns:
            修复后的 ui_summary 列表
        """
        if not breaks:
            return rewritten

        repaired = list(rewritten)
        for i in breaks:
            prev = repaired[i]
            next_idx = i + 1
            if next_idx >= len(repaired):
                continue

            try:
                prompt = CAUSAL_REPAIR_PROMPT.format(
                    prev_summary=prev,
                    next_summary=repaired[next_idx],
                )
                result = self.llm.chat(prompt).strip()

                # 清理可能的 markdown 包裹
                if result.startswith("```"):
                    result = re.sub(r'^```(?:text|plain|json)?\s*', '', result)
                    result = re.sub(r'\s*```$', '', result)
                    result = result.strip()

                if result and len(result) > 20:
                    repaired[next_idx] = result
                    logger.info(
                        f"  ✓ 修复 Step {next_idx}: 插入恢复过渡"
                    )
                else:
                    logger.warning(f"  LLM 修复 Step {next_idx} 返回内容过短，跳过")

            except Exception as e:
                logger.warning(f"  修复 Step {next_idx} 失败: {e}")

        return repaired

    def _build_modified_utg(
        self,
        loader: UTGLoader,
        valid_steps: List[UTGStep],
        rewritten: List[str],
    ) -> Dict:
        """组装修改后的 utg_info.json"""
        modified = deepcopy(loader._raw)

        # 清空原始 stepData，重新构建
        new_step_data = []

        for i, step in enumerate(valid_steps):
            ui_summary = rewritten[i] if i < len(rewritten) else step.ui_summary
            new_step_data.append({
                "stepId": step.step_id,
                "action_type": step.action_type,
                "thought": step.thought,
                "ui_summary": ui_summary,
                "cost_time": step.cost_time,
                "type": step.step_type,
                "imageId": step.image_id,
            })

        # 添加被去重跳过的步骤不展示在最终数据中
        # 保留全量 stepData 但标记去重的步骤
        # 更好的方式：保留所有 step，但将去重的步骤 ui_summary 设为 "（已合并）"
        # 考虑到 downstream 只需要有 ui_summary 的步骤，这里直接替换有效步骤的 ui_summary
        # 非有效步骤（home/end/start）保持不变

        # 更简单的做法：只替换有效的 step 的 ui_summary
        step_data_map = {}
        for item in modified.get("stepData", []):
            sid = str(item.get("stepId", ""))
            step_data_map[sid] = item

        # 用重写后的内容更新
        for i, step in enumerate(valid_steps):
            ui_summary = rewritten[i] if i < len(rewritten) else step.ui_summary
            if step.step_id in step_data_map:
                step_data_map[step.step_id]["ui_summary"] = ui_summary

        # 对于被去重合并掉的步骤（不在 valid_steps 但在原始 stepData 中），保留但标记
        valid_ids = {s.step_id for s in valid_steps}
        for item in modified.get("stepData", []):
            sid = str(item.get("stepId", ""))
            if sid not in valid_ids and item.get("ui_summary", "").strip():
                item["ui_summary"] = "（已合并到上一步）"

        return modified

    @staticmethod
    def save(modified_utg: Dict, output_path: str) -> str:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(modified_utg, f, ensure_ascii=False, indent=2)
        return str(path)

