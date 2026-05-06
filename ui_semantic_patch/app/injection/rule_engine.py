"""
规则引擎

根据 VLM 页面分类结果，从规则表中匹配最合适的异常注入配置。

职责：
1. 加载 rules.json 规则表
2. 根据 page_type + key_elements + user_waiting 匹配规则
3. 按优先级排序，选择最优规则
4. 生成异常注入配置（anomaly_mode, instruction, gt_category 等）
"""

import json
from pathlib import Path
from typing import List, Dict, Optional


# 规则表默认路径
DEFAULT_RULES_PATH = Path(__file__).parent / "rules.json"


class RuleEngine:
    """
    规则引擎

    接收 VLM 分类结果 → 匹配规则 → 输出 anomaly_config
    """

    def __init__(self, rules_path: Optional[str] = None):
        """
        初始化规则引擎

        Args:
            rules_path: 规则表 JSON 文件路径，默认使用内置 rules.json
        """
        path = Path(rules_path) if rules_path else DEFAULT_RULES_PATH
        if not path.exists():
            raise FileNotFoundError(f"规则表文件不存在: {path}")

        with open(path, 'r', encoding='utf-8') as f:
            self._data = json.load(f)

        self._rules: List[Dict] = self._data.get("rules", [])
        self._page_types: Dict = self._data.get("page_types", {})
        self._fallback: Dict = self._data.get("fallback", {})

        print(f"  [规则引擎] 加载 {len(self._rules)} 条规则, "
              f"{len(self._page_types)} 种页面类型")

    def match(
        self,
        page_type: str,
        page_type_name: str = "",
        key_elements: Optional[List[str]] = None,
        user_waiting: bool = False
    ) -> List[Dict]:
        """
        匹配规则

        Args:
            page_type: VLM 分类的页面类型代号 (A-J)
            page_type_name: 页面类型中文名（用于匹配）
            key_elements: 页面上的关键元素列表
            user_waiting: 用户是否在等待状态

        Returns:
            匹配到的规则列表（按 priority 降序排列），空列表表示无匹配
        """
        if not self._rules:
            return []

        # page_type 代号 → 规则表中的 page_type 键名
        type_key_map = {
            "A": "splash", "B": "home", "C": "search",
            "D": "list_result", "E": "detail", "F": "form",
            "G": "payment", "H": "profile", "I": "loading_wait",
            "J": "other"
        }
        page_type_key = type_key_map.get(page_type, "other")

        matched = []

        for rule in self._rules:
            # 1. page_type 匹配
            rule_page_types = rule.get("page_types", [])
            if page_type_key not in rule_page_types:
                continue

            score = 0

            # 2. user_waiting 加分
            if rule.get("user_waiting") and user_waiting:
                score += 20

            # 3. key_elements 加分
            required_elements = rule.get("requires_elements", [])
            if required_elements and key_elements:
                element_match = sum(
                    1 for e in required_elements
                    if any(e in elem for elem in key_elements)
                )
                score += element_match * 10

            matched.append({
                **rule,
                "_match_score": rule.get("priority", 0) + score
            })

        # 按匹配得分降序排序
        matched.sort(key=lambda r: r["_match_score"], reverse=True)

        if matched:
            print(f"  [规则引擎] 匹配到 {len(matched)} 条规则, "
                  f"最优: {matched[0].get('id', '?')} "
                  f"(得分={matched[0]['_match_score']})")
        else:
            print(f"  [规则引擎] 无匹配规则, 页面类型: {page_type_key}")

        return matched

    def select_best(self, matched_rules: List[Dict]) -> Optional[Dict]:
        """
        从匹配结果中选择最优规则

        Args:
            matched_rules: match() 返回的匹配规则列表

        Returns:
            最优规则，无匹配时返回 None
        """
        if not matched_rules:
            return None
        return matched_rules[0]

    def get_fallback_config(self) -> Dict:
        """
        获取兜底配置（无规则匹配时使用）

        Returns:
            {
                "anomaly_mode": str,
                "instruction": str,
                "gt_category": str,
                "gt_sample": str,
                "fault_mode": str
            }
        """
        return self._build_config(self._fallback)

    def get_anomaly_config(self, rule: Dict) -> Dict:
        """
        根据规则生成异常注入配置

        Args:
            rule: match() 返回的单条规则

        Returns:
            {
                "anomaly_mode": str,
                "instruction": str,
                "gt_category": str,
                "gt_sample": str,
                "fault_mode": str,
                "matched_rule_id": str,
                "priority": int
            }
        """
        return self._build_config(rule)

    def _build_config(self, rule: Dict) -> Dict:
        """从规则构建标准配置"""
        return {
            "anomaly_mode": rule.get("anomaly_mode", "dialog"),
            "instruction": rule.get("instruction_template", ""),
            "gt_category": rule.get("gt_category", ""),
            "gt_sample": rule.get("gt_sample", ""),
            "fault_mode": rule.get("fault_mode", "通用异常"),
            "matched_rule_id": rule.get("id", "fallback"),
            "priority": rule.get("priority", 0)
        }

    def list_rules(self) -> List[Dict]:
        """列出所有规则（用于调试）"""
        return list(self._rules)

    def get_page_types(self) -> Dict:
        """获取所有页面类型定义"""
        return dict(self._page_types)

    def reload(self):
        """重新加载规则表"""
        with open(DEFAULT_RULES_PATH, 'r', encoding='utf-8') as f:
            self._data = json.load(f)
        self._rules = self._data.get("rules", [])
        self._page_types = self._data.get("page_types", {})
        self._fallback = self._data.get("fallback", {})
        print(f"  [规则引擎] 重新加载: {len(self._rules)} 条规则")
