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
        total_steps: int
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

        # ===== Step 1: VLM 页面分类（v2 两级） =====
        page_info = self.classifier.classify(str(screenshot_path))
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
            config = self.rule_engine.get_anomaly_config(best_rule)
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
                "think": f"app={app_category}, page={page_type}, "
                         f"等待={user_waiting}, "
                         f"匹配规则={config['matched_rule_id']}"
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
                "think": f"app={app_category}, page={page_type}, 无匹配规则"
            }

        self._record_step(screenshot_path, step_index, result)
        return result

    def run(self, screenshots: List[Path]) -> Dict:
        """
        分析整个截图序列，找到注入点

        Args:
            screenshots: 截图路径列表（按时间顺序）

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
        print(f"开始语义分析（规则引擎版）")
        if self.task_description:
            print(f"任务: {self.task_description}")
        print(f"序列长度: {total_steps} 步")
        print(f"{'='*60}\n")

        for i, screenshot in enumerate(screenshots):
            print(f"\n--- Step {i}/{total_steps-1}: {screenshot.name} ---")

            result = self.analyze_step(screenshot, i, total_steps)

            print(f"  [{result.get('app_category', '?')}/{result.get('page_type', '?')}]")
            print(f"  决策: {result['decision']}")

            if result.get("matched_rule_id"):
                print(f"  匹配规则: {result['matched_rule_id']}")

            if result["decision"] == "INJECT":
                print(f"  异常模式: {result['anomaly_mode']}")
                print(f"  生成指令: {result['instruction']}")

                print(f"\n{'='*60}")
                print(f"✓ 找到注入点: Step {i}")
                print(f"  APP类别: {result['app_category']}")
                print(f"  页面类型: {result['page_type']}")
                print(f"  异常模式: {result['anomaly_mode']}")
                print(f"  匹配规则: {result['matched_rule_id']}")
                print(f"{'='*60}\n")

                return {
                    "success": True,
                    "injection_point": i,
                    "anomaly_mode": result["anomaly_mode"],
                    "instruction": result["instruction"],
                    "gt_category": result.get("gt_category", ""),
                    "gt_sample": result.get("gt_sample", ""),
                    "fault_mode": result.get("fault_mode", ""),
                    "app_category": result.get("app_category", ""),
                    "page_type": result.get("page_type", ""),
                    "matched_rule_id": result.get("matched_rule_id", ""),
                    "reasoning": result.get("think", ""),
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

    def _record_step(self, screenshot_path: Path, step_index: int, result: Dict):
        """记录分析步骤到历史"""
        record = StepRecord(
            step_index=step_index,
            screenshot_path=str(screenshot_path),
            think=result.get("think", ""),
            decision=result["decision"],
            anomaly_type=result.get("anomaly_mode"),
            instruction=result.get("instruction"),
            app_category=result.get("app_category", ""),
            conclusion=result.get("page_type", "")
        )
        self.history_manager.add_record(record)

    def reset(self) -> None:
        """重置分析器状态"""
        self.history_manager.reset()

    def get_history(self) -> List[Dict]:
        """获取分析历史"""
        return [r.to_dict() for r in self.history_manager.records]
