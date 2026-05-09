"""
增量式语义分析器（规则引擎版本）

核心变更：将 VLM 从开放决策降级为封闭分类。
- 旧方案：VLM 自由决策（注入否？注入什么？在哪注入？）→ 不稳定
- 新方案：VLM 分类页面类型 + 规则引擎做确定性匹配 → 稳定

流程：
  逐帧遍历截图 →
    1. PageClassifier 分类页面类型（VLM 封闭式分类）
    2. RuleEngine 匹配规则（page_type → anomaly_mode）
    3. TimingValidator 时序验证
    4. 输出 injection_point + anomaly_config
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Optional

from app.utils.history_manager import HistoryManager, StepRecord
from .page_classifier import PageClassifier
from .rule_engine import RuleEngine


class SequenceAnalyzer:
    """
    增量式语义分析器（规则引擎版）

    职责：
    - 逐帧分析截图序列
    - 使用 PageClassifier 对每张截图做页面类型分类
    - 使用 RuleEngine 匹配异常注入规则
    - 一旦匹配成功则停止分析
    - 无匹配时输出 fallback 配置
    """

    def __init__(
        self,
        rule_engine: RuleEngine,
        page_classifier: PageClassifier,
        task_description: str = "",
        min_steps_before_inject: int = 2,
        max_history_steps: int = 10
    ):
        """
        初始化语义分析器

        Args:
            rule_engine: 规则引擎实例
            page_classifier: 页面分类器实例
            task_description: 任务描述（用于日志）
            min_steps_before_inject: 最少分析多少步后才考虑注入
            max_history_steps: 最大历史步数
        """
        self.rule_engine = rule_engine
        self.classifier = page_classifier
        self.task_description = task_description
        self.min_steps_before_inject = min_steps_before_inject
        self.history_manager = HistoryManager(max_history_steps)

    def analyze_step(
        self,
        screenshot_path: Path,
        step_index: int,
        total_steps: int,
        expected_anomaly_mode: str = None,
    ) -> Dict:
        """
        分析单步截图，决策是否注入异常

        Args:
            screenshot_path: 截图路径
            step_index: 当前步骤索引（从 0 开始）
            total_steps: 总步骤数

        Returns:
            {
                "decision": "INJECT" or "SKIP",
                "anomaly_mode": str or None,
                "instruction": str or None,
                "page_type": str,
                "matched_rule_id": str or None,
                "think": str
            }
        """
        screenshot_path = Path(screenshot_path)
        if not screenshot_path.exists():
            raise FileNotFoundError(f"截图不存在: {screenshot_path}")

        # ===== 前置约束：前 N 步不允许注入 =====
        if step_index < self.min_steps_before_inject:
            result = {
                "decision": "SKIP",
                "anomaly_mode": None,
                "instruction": None,
                "gt_category": None,
                "gt_sample": None,
                "app_category": "",
                "page_type": "",
                "matched_rule_id": None,
                "think": f"前 {self.min_steps_before_inject} 步强制跳过"
            }
            self._record_step(screenshot_path, step_index, result)
            return result

        # ===== Step 1: VLM 页面分类（v2 两级 + 序列上下文） =====
        # 获取上一帧的分类结果，作为序列上下文传递给 VLM
        prev_records = self.history_manager.get_recent_records()
        prev_info = None
        if prev_records:
            last = prev_records[-1]
            if last.conclusion:
                prev_info = {
                    "app_category": last.app_category or "",
                    "page_type": last.conclusion,
                    "reasoning": last.think,
                }
        step_ctx = f"{step_index + 1}/{total_steps}步"

        page_info = self.classifier.classify(
            str(screenshot_path),
            prev_page_info=prev_info,
            step_context=step_ctx,
        )
        app_category = page_info.get("app_category", "")
        page_type = page_info.get("page_type", "travel_loading")
        key_elements = page_info.get("key_elements", [])
        user_waiting = page_info.get("user_waiting", False)

        # ===== Step 2: 规则匹配 =====
        matched = self.rule_engine.match(
            app_category=app_category,
            page_type=page_type,
            key_elements=key_elements,
            user_waiting=user_waiting
        )

        best_rule = self.rule_engine.select_best(matched)

        if best_rule:
            # ===== Step 2.5: 内容验证（精准匹配门禁） =====
            content_ok, content_reason = self._verify_content(page_info, best_rule)

            # 无内容需求的规则（dialog/area_loading/response_delay）：
            # 仅当已遍历序列后半段或 VLM 确认等待态时才允许注入，
            # 优先让路给有内容需求的规则（modify_text 等）
            has_content_req = bool(best_rule.get("content_requirements"))
            is_late_stage = step_index >= total_steps // 2
            if not content_ok:
                pass  # 内容不满足 → 走 SKIP 分支
            elif not has_content_req and not is_late_stage and not user_waiting:
                # dialog 类规则在序列前半段且非等待态 → 暂不注入，让路给精准规则
                content_ok = False
                content_reason = f"无内容需求的规则({best_rule.get('fault_mode','')})在序列前半段暂不注入，等待精准规则匹配"

            if not content_ok:
                result = {
                    "decision": "SKIP",
                    "anomaly_mode": None,
                    "instruction": None,
                    "gt_category": None,
                    "gt_sample": None,
                    "app_category": app_category,
                    "page_type": page_type,
                    "matched_rule_id": best_rule.get("id"),
                    "matched_rule": None,
                    "match_score": 0,
                    "match_confidence": 0.0,
                    "vlm_reasoning": page_info.get("reasoning", ""),
                    "vlm_key_elements": key_elements,
                    "vlm_user_waiting": user_waiting,
                    "think": f"app={app_category}, page={page_type}, "
                             f"规则匹配但内容不满足: {content_reason}"
                }
                self._record_step(screenshot_path, step_index, result, page_info)
                return result

            config = self.rule_engine.get_anomaly_config(best_rule)
            match_score = best_rule.get("_match_score", config.get("priority", 0))
            confidence = min(1.0, match_score / 120.0)

            # ===== Step 2.6: 异常模式对齐检查 =====
            # 规则推荐的异常模式必须与映射配置期望一致，否则跳过
            if expected_anomaly_mode and config["anomaly_mode"] != expected_anomaly_mode:
                result = {
                    "decision": "SKIP",
                    "anomaly_mode": None,
                    "instruction": None,
                    "gt_category": None,
                    "gt_sample": None,
                    "app_category": app_category,
                    "page_type": page_type,
                    "matched_rule_id": best_rule.get("id"),
                    "matched_rule": None,
                    "match_score": 0,
                    "match_confidence": 0.0,
                    "vlm_reasoning": page_info.get("reasoning", ""),
                    "vlm_key_elements": key_elements,
                    "vlm_user_waiting": user_waiting,
                    "think": f"app={app_category}, page={page_type}, "
                             f"规则推荐异常模式={config['anomaly_mode']}, "
                             f"期望={expected_anomaly_mode} → 不匹配，跳过"
                }
                self._record_step(screenshot_path, step_index, result, page_info)
                return result

            result = {
                "decision": "INJECT",
                "anomaly_mode": config["anomaly_mode"],
                "instruction": config["instruction"],
                "gt_category": config["gt_category"],
                "gt_sample": config["gt_sample"],
                "fault_mode": config["fault_mode"],
                "app_category": app_category,
                "page_type": page_type,
                "matched_rule_id": config["matched_rule_id"],
                "matched_rule": {k: v for k, v in best_rule.items()
                                 if not k.startswith("_")},
                "match_score": match_score,
                "match_confidence": round(confidence, 2),
                "vlm_reasoning": page_info.get("reasoning", ""),
                "vlm_key_elements": key_elements,
                "vlm_user_waiting": user_waiting,
                "think": f"app={app_category}, page={page_type}, "
                         f"等待={user_waiting}, "
                         f"匹配规则={config['matched_rule_id']} "
                         f"(score={match_score}, conf={confidence:.2f})"
            }
        else:
            result = {
                "decision": "SKIP",
                "anomaly_mode": None,
                "instruction": None,
                "gt_category": None,
                "gt_sample": None,
                "app_category": app_category,
                "page_type": page_type,
                "matched_rule_id": None,
                "matched_rule": None,
                "match_score": 0,
                "match_confidence": 0.0,
                "vlm_reasoning": page_info.get("reasoning", ""),
                "vlm_key_elements": key_elements,
                "vlm_user_waiting": user_waiting,
                "think": f"app={app_category}, page={page_type}, 无匹配规则"
            }

        self._record_step(screenshot_path, step_index, result)
        return result

    def run(self, screenshots: List[Path],
            expected_anomaly_mode: str = None) -> Dict:
        """
        分析整个截图序列，找到注入点

        Args:
            screenshots: 截图路径列表（按时间顺序）
            expected_anomaly_mode: 映射配置期望的异常模式（如不匹配则跳过该候选）

        Returns:
            {
                "success": True/False,
                "injection_point": int or None,
                "anomaly_mode": str or None,
                "instruction": str or None,
                "gt_category": str or None,
                "gt_sample": str or None,
                "fault_mode": str or None,
                "page_type": str or None,
                "matched_rule_id": str or None,
                "reasoning": str,
                "history": List[dict]
            }
        """
        screenshots = [Path(p) for p in screenshots]
        total_steps = len(screenshots)

        print(f"\n{'='*60}")
        print(f"开始语义分析（全序列遍历 + 对比决策）")
        if self.task_description:
            print(f"任务: {self.task_description}")
        print(f"序列长度: {total_steps} 步")
        print(f"{'='*60}\n")

        candidates = []

        for i, screenshot in enumerate(screenshots):
            print(f"\n--- Step {i}/{total_steps-1}: {screenshot.name} ---")

            result = self.analyze_step(screenshot, i, total_steps,
                                        expected_anomaly_mode=expected_anomaly_mode)

            print(f"  [{result.get('app_category', '?')}/{result.get('page_type', '?')}]")
            print(f"  决策: {result['decision']}")

            if result.get("matched_rule_id"):
                print(f"  匹配规则: {result['matched_rule_id']} "
                      f"(score={result.get('match_score', 0)}, "
                      f"conf={result.get('match_confidence', 0)})")

            if result["decision"] == "INJECT":
                result["_step_index"] = i
                result["_total_steps"] = total_steps
                candidates.append(result)

        # ===== 全序列遍历完毕，对比决策 =====
        if candidates:
            best = self._select_best_candidate(candidates, total_steps)
            i = best["_step_index"]

            print(f"\n{'='*60}")
            print(f"✓ 全序列对比完成，选中注入点: Step {i}/{total_steps-1}")
            if len(candidates) > 1:
                print(f"  候选注入点: {len(candidates)} 个")
                for c in sorted(candidates, key=lambda c: c.get('_final_score', 0), reverse=True):
                    mark = "← 选中" if c is best else ""
                    print(f"    Step {c['_step_index']}: {c['matched_rule_id']} "
                          f"(score={c.get('_final_score', '?')}) {mark}")
            print(f"  APP类别: {best['app_category']}")
            print(f"  页面类型: {best['page_type']}")
            print(f"  异常模式: {best['anomaly_mode']}")
            print(f"  匹配规则: {best['matched_rule_id']}")
            print(f"  VLM 分类理由: {best.get('vlm_reasoning', '?')}")
            print(f"{'='*60}\n")

            return {
                "success": True,
                "injection_point": i,
                "anomaly_mode": best["anomaly_mode"],
                "instruction": best["instruction"],
                "gt_category": best.get("gt_category", ""),
                "gt_sample": best.get("gt_sample", ""),
                "fault_mode": best.get("fault_mode", ""),
                "app_category": best.get("app_category", ""),
                "page_type": best.get("page_type", ""),
                "matched_rule_id": best.get("matched_rule_id", ""),
                "matched_rule": best.get("matched_rule"),
                "match_score": best.get("match_score", 0),
                "match_confidence": best.get("match_confidence", 0.0),
                "vlm_reasoning": best.get("vlm_reasoning", ""),
                "vlm_key_elements": best.get("vlm_key_elements", []),
                "vlm_user_waiting": best.get("vlm_user_waiting", False),
                "reasoning": best.get("think", ""),
                "candidates_count": len(candidates),
                "history": [r.to_dict() for r in self.history_manager.records]
            }

        # 遍历完成未找到注入点 → 使用 fallback
        fallback = self.rule_engine.get_fallback_config()
        fallback_point = len(screenshots) // 2

        print(f"\n{'='*60}")
        print(f"⚠ 未找到匹配规则，使用 fallback")
        print(f"  注入点: Step {fallback_point} (中间位置)")
        print(f"  异常模式: {fallback.get('anomaly_mode', 'dialog')}")
        print(f"  指令: {fallback.get('instruction', '')}")
        print(f"{'='*60}\n")

        return {
            "success": True,
            "injection_point": fallback_point,
            "anomaly_mode": fallback.get("anomaly_mode", "dialog"),
            "instruction": fallback.get("instruction", ""),
            "gt_category": fallback.get("gt_category", ""),
            "gt_sample": fallback.get("gt_sample", ""),
            "fault_mode": fallback.get("fault_mode", "通用异常"),
            "app_category": "fallback",
            "page_type": "fallback",
            "matched_rule_id": "fallback",
            "reasoning": "遍历完整个序列，无规则匹配，使用 fallback 配置",
            "history": [r.to_dict() for r in self.history_manager.records]
        }

    def _record_step(self, screenshot_path: Path, step_index: int, result: Dict,
                      page_info: Dict = None):
        """记录分析步骤到历史"""
        context = {}
        if page_info:
            context = self._build_vlm_context(page_info)
        record = StepRecord(
            step_index=step_index,
            screenshot_path=str(screenshot_path),
            think=result.get("think", ""),
            decision=result["decision"],
            anomaly_type=result.get("anomaly_mode"),
            instruction=result.get("instruction"),
            app_category=result.get("app_category", ""),
            conclusion=result.get("page_type", ""),
            confidence=result.get("match_confidence", 0.0),
            context=context,
        )
        self.history_manager.add_record(record)

    def _build_vlm_context(self, page_info: Dict) -> Dict:
        """从 VLM 分类结果中提取调试上下文"""
        return {
            "vlm_reasoning": page_info.get("reasoning", ""),
            "vlm_key_elements": page_info.get("key_elements", []),
            "vlm_content_features": page_info.get("content_features", {}),
            "vlm_user_waiting": page_info.get("user_waiting", False),
        }

    def _select_best_candidate(self, candidates: List[Dict],
                                total_steps: int) -> Dict:
        """从多个候选注入点中选择最优。

        评分维度：
        - match_score (规则匹配得分, 0-120)
        - content_bonus: 有内容验证通过的规则 +15（精准匹配优先）
        - position_bonus: 序列中后部 +5（避免过早注入）
        - waiting_bonus: 用户等待态 +10
        - semantic_kw_bonus: 语义关键词匹配数 * 3

        返回得分最高的候选
        """
        for c in candidates:
            score = c.get("match_score", 0)

            # 内容验证通过的规则优先
            rule = c.get("matched_rule", {})
            if rule and rule.get("content_requirements"):
                score += 15

            # 序列位置：后半段 +5，后 1/3 额外 +3
            pos = c.get("_step_index", 0)
            if pos >= total_steps // 2:
                score += 5
            if pos >= total_steps * 2 // 3:
                score += 3

            # 用户等待态
            if c.get("vlm_user_waiting"):
                score += 10

            # 语义关键词匹配加分（_verify_content 中匹配到的）
            think = c.get("think", "")
            if "语义关键词不匹配" not in think and "内容验证通过" in think:
                score += 3  # 内容验证通过的文字确认

            c["_final_score"] = score

        candidates.sort(key=lambda c: c.get("_final_score", 0), reverse=True)
        return candidates[0]

    def _verify_content(self, page_info: Dict, rule: Dict) -> tuple:
        """验证页面内容是否满足规则的语义需求

        两层验证：
        1. 通用内容特征（has_price/has_button 等）— 快速过滤
        2. 语义关键词匹配（key_elements + reasoning）— 精准确认

        modify_text_ai / modify_text 规则额外要求 VLM 提取的关键元素
        中至少出现 1 个与规则语义相关的词。

        Returns:
            (is_ok, reason)
        """
        requirements = rule.get("content_requirements")
        if not requirements:
            return True, ""  # dialog/area_loading/response_delay 无需验证

        features = page_info.get("content_features", {})
        key_elements = [e.lower() for e in page_info.get("key_elements", [])]
        reasoning = page_info.get("reasoning", "").lower()
        anomaly_mode = rule.get("anomaly_mode", "")
        fault_mode = rule.get("fault_mode", "")
        instruction_tmpl = rule.get("instruction_template", "")

        # ===== 第一层：通用特征检查 =====
        if features:
            failed = []
            for key, required in requirements.items():
                if key in ("desc", "semantic_keywords", "min_keyword_match"):
                    continue
                if required and not features.get(key):
                    failed.append(key)
            if failed:
                desc = requirements.get("desc", "")
                return False, f"缺少内容特征: {failed} ({desc})"

        # ===== 第二层：语义关键词匹配（modify_text/modify_text_ai 专属） =====
        if anomaly_mode in ("modify_text", "modify_text_ai", "modify_text_ocr",
                            "text_overlay", "content_duplicate"):
            # 从规则中提取语义关键词
            semantic_kw = requirements.get("semantic_keywords", [])
            if not semantic_kw:
                semantic_kw = self._derive_keywords(anomaly_mode, fault_mode,
                                                     instruction_tmpl)
            min_match = requirements.get("min_keyword_match", 1)

            if semantic_kw:
                # 在 key_elements + reasoning 中匹配
                match_count = 0
                matched_words = []
                for kw in semantic_kw:
                    kw_lower = kw.lower()
                    if any(kw_lower in elem for elem in key_elements):
                        match_count += 1
                        matched_words.append(kw)
                    elif kw_lower in reasoning:
                        match_count += 1
                        matched_words.append(kw)

                if match_count < min_match:
                    return False, (
                        f"语义关键词不匹配: 需要≥{min_match}个 {semantic_kw}, "
                        f"实际匹配 {match_count} 个 {matched_words}, "
                        f"VLM 关键元素: {key_elements[:5]}"
                    )

        desc = requirements.get("desc", "")
        return True, f"内容验证通过 ({desc})"

    def _derive_keywords(self, anomaly_mode: str, fault_mode: str,
                         instruction_tmpl: str) -> list:
        """从规则语义中推导期望出现的内容关键词"""
        # 按异常模式分类
        mode_keywords = {
            "modify_text":    ["价格", "金额", "¥", "元", "票价", "总价", "合计", "优惠"],
            "modify_text_ai": ["按钮", "文字", "名称", "标题", "勾选", "勾选框", "置灰", "选集"],
            "modify_text_ocr":["按钮", "文字", "名称", "标题"],
            "text_overlay":   ["按钮", "入口", "下载", "购买", "提交", "确认"],
            "content_duplicate": ["列表", "卡片", "条目", "选项", "选集"],
        }
        keywords = list(mode_keywords.get(anomaly_mode, []))

        # 从 fault_mode 中提取额外关键词
        fault_kw = {
            "价格": ["价格", "金额", "¥", "元"],
            "篡改": ["名称", "标题", "文字"],
            "置灰": ["勾选", "选框", "按钮"],
            "遮挡": ["按钮", "下载", "入口"],
            "重复": ["条目", "列表", "卡片"],
            "延迟": ["加载", "等待"],
            "售罄": ["售罄", "缺货", "无票"],
            "无票": ["无票", "售罄", "余票"],
        }
        for k, v in fault_kw.items():
            if k in fault_mode or k in instruction_tmpl:
                keywords.extend(v)

        return list(set(keywords))  # 去重

    def reset(self) -> None:
        """重置分析器状态"""
        self.history_manager.reset()

    def get_history(self) -> List[Dict]:
        """获取分析历史"""
        return [r.to_dict() for r in self.history_manager.records]
