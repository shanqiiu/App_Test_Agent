"""
quality_validator.py — 输出质量验证器（Phase 3）

在最终输出前对 Flow JSON 进行多维度质量验证：

1. Schema 合规性 — 必含字段、字段类型、步骤连续性
2. 数据一致性 — 商品名、价格、数量跨步骤一致
3. 步骤连贯性 — 相邻步骤是否有因果链、无断裂
4. 可读性 — 无晦涩表述、口语化程度
5. 流程合理性 — 符合业务页面拓扑

纯 Python 实现，仅最后一项可读性检查可选 LLM。
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)

# ── 验证常量 ─────────────────────────────────────────────

MIN_ACTION_LENGTH = 20
MAX_ACTION_LENGTH = 200
MAX_CONSECUTIVE_SAME_PAGE = 1

SCREEN_KEY_ORDER = [
    "home", "search", "searchResult", "productDetail",
    "cart", "checkout", "payment", "orders", "orderDetail",
]

OBSCURE_PATTERNS = [
    r'\bexception\b', r'\berror\b', r'\bnull\b', r'\bundefined\b',
    r'HTTP\s*\d{3}', r'状态码', r'异常码',
    r'数据库查询', r'后端返回',
    r'JSON\s*解析', r'请求失败',
]

REQUIRED_FIELDS = ["order", "action"]
OPTIONAL_FIELDS = ["targetPage", "anomalyTag", "boundMockId"]


class QualityValidator:
    """Flow 输出质量验证器"""

    def validate(self, flow_data: Dict, template_path: Optional[str] = None) -> Dict[str, Any]:
        """
        执行全维度验证。

        Args:
            flow_data: Flow JSON 数据
            template_path: 模板路径（可选，用于对比 screenKeys）

        Returns:
            {
                "passed": bool,
                "score": float,  # 0.0 - 1.0
                "dimensions": {
                    "schema": {"passed": bool, "issues": [...]},
                    "consistency": {"passed": bool, "issues": [...]},
                    "coherence": {"passed": bool, "issues": [...]},
                    "readability": {"passed": bool, "issues": [...]},
                    "topology": {"passed": bool, "issues": [...]},
                },
                "summary": str,
            }
        """
        result = {
            "passed": False,
            "score": 0.0,
            "dimensions": {},
            "summary": "",
        }

        steps = flow_data.get("mainFlow", {}).get("steps", [])

        # 各维度验证
        schema_result = self._validate_schema(steps)
        consistency_result = self._validate_consistency(steps)
        coherence_result = self._validate_coherence(steps)
        readability_result = self._validate_readability(steps)

        topology_result = {"passed": True, "issues": [], "score": 1.0}
        if template_path:
            topology_result = self._validate_topology(steps, template_path)

        dimensions = {
            "schema": schema_result,
            "consistency": consistency_result,
            "coherence": coherence_result,
            "readability": readability_result,
            "topology": topology_result,
        }
        result["dimensions"] = dimensions

        # 综合评分
        total_score = sum(d.get("score", 0) for d in dimensions.values())
        result["score"] = round(total_score / len(dimensions), 2)
        result["passed"] = all(d.get("passed", False) for d in dimensions.values())

        # 汇总
        all_issues = []
        for dim_name, dim_result in dimensions.items():
            for issue in dim_result.get("issues", []):
                all_issues.append(f"[{dim_name}] {issue}")

        if all_issues:
            result["summary"] = f"发现 {len(all_issues)} 个问题: {'; '.join(all_issues[:5])}"
            if len(all_issues) > 5:
                result["summary"] += f" (还有 {len(all_issues) - 5} 个问题)"
        else:
            result["summary"] = "全部验证通过"

        logger.info(f"  质量评分: {result['score']}/1.0 {'✅' if result['passed'] else '❌'}")
        if all_issues:
            for issue in all_issues:
                logger.info(f"    ⚠ {issue}")

        return result

    # ── Schema 合规性 ────────────────────────────────────

    def _validate_schema(self, steps: List[Dict]) -> Dict:
        """Schema 合规性验证"""
        issues = []
        scores = []

        if not steps:
            return {"passed": False, "issues": ["无步骤"], "score": 0.0}

        # 检查必填字段
        for i, step in enumerate(steps):
            for field in REQUIRED_FIELDS:
                if field not in step:
                    issues.append(f"Step {step.get('order', i)}: 缺少必填字段 '{field}'")
                    scores.append(0)
                else:
                    scores.append(1)

            # order 必须是正整数且连续
            order = step.get("order", 0)
            if not isinstance(order, int) or order < 1:
                issues.append(f"Step {i}: order 必须为正整数 (当前: {order})")
                scores.append(0)
            elif i > 0 and order != steps[i - 1].get("order", 0) + 1:
                issues.append(f"Step {i}: order 不连续 ({steps[i-1].get('order')} → {order})")
                scores.append(0)

            # action 不能为空
            action = step.get("action", "")
            if not action or len(action.strip()) < 5:
                issues.append(f"Step {order}: action 为空或过短")
                scores.append(0)

        # 可选字段 coverage
        optional_coverage = {}
        for field in OPTIONAL_FIELDS:
            count = sum(1 for s in steps if field in s)
            optional_coverage[field] = f"{count}/{len(steps)}"

        if optional_coverage.get("targetPage", "0/0").startswith("0"):
            issues.append("所有步骤均缺少 targetPage 字段")

        score = sum(scores) / len(scores) if scores else 0
        passed = len([i for i in issues if "缺少必填" in i]) == 0

        return {"passed": passed, "issues": issues, "score": score, "coverage": optional_coverage}

    # ── 数据一致性 ───────────────────────────────────────

    def _validate_consistency(self, steps: List[Dict]) -> Dict:
        """跨步骤数据一致性验证"""
        issues = []

        # 提取所有步骤中的商品名和价格
        product_names = set()
        prices = set()

        for step in steps:
            action = step.get("action", "")

            # 提取商品名（如 "iPhone 16 Pro"、"华为畅享70X"）
            name_match = re.findall(r'[\u4e00-\u9fff\w]+\s*[\u4e00-\u9fff\w]+(?:Pro|Max|Ultra|\d+[\w]*)*', action)
            for n in name_match:
                if len(n) > 3:  # 排除短词
                    product_names.add(n)

            # 提取价格（如 ¥6999、1648.00元）
            price_match = re.findall(r'¥?\s*\d+[\.\d]*\s*元', action)
            for p in price_match:
                prices.add(p)

        # 检查商品名不一致（多个不同品牌的商品）
        brands_found = set()
        for name in product_names:
            for brand in ["华为", "iPhone", "Apple", "小米", "三星", "荣耀", "OPPO", "vivo"]:
                if brand in name:
                    brands_found.add(brand)
        if len(brands_found) > 1:
            issues.append(f"步骤中出现多个品牌: {', '.join(brands_found)}")

        # 检查价格不一致
        if len(prices) > 1:
            issues.append(f"步骤中出现多个价格: {', '.join(prices)}")

        passed = len(issues) == 0
        score = 1.0 if passed else max(0.3, 1.0 - len(issues) * 0.3)
        return {"passed": passed, "issues": issues, "score": score}

    # ── 步骤连贯性 ───────────────────────────────────────

    def _validate_coherence(self, steps: List[Dict]) -> Dict:
        """相邻步骤连贯性验证"""
        issues = []
        violations = 0
        total_checks = max(len(steps) - 1, 1)

        for i in range(len(steps) - 1):
            curr = steps[i]
            next_step = steps[i + 1]

            curr_action = curr.get("action", "")
            next_action = next_step.get("action", "")

            # 检查连续相同 targetPage（过度停留）
            curr_page = curr.get("targetPage", "")
            next_page = next_step.get("targetPage", "")
            if curr_page and next_page and curr_page == next_page:
                # 允许 home → search 等正常连续
                # 但同页面超过 2 步连续视为冗余
                if i >= 1:
                    prev_page = steps[i - 1].get("targetPage", "")
                    if prev_page == curr_page:
                        violations += 1
                        issues.append(
                            f"Step {curr['order']}~{next_step['order']}: "
                            f"连续 {curr_page} 超过2步，可能有冗余"
                        )

            # 检查前后步是否有关联（后一步应参考前一步的结果）
            # 简单启发：后一步包含"返回"而前一步无"进入"，可能是断裂
            if "返回" in next_action and "进入" not in curr_action and "跳转" not in curr_action:
                if curr_page and next_page:
                    violation = True
                    # 但如果是正常的页面切换，不算断裂
                    if curr_page not in ("home", "search") and next_page in ("home", "search"):
                        violation = False
                    if violation:
                        violations += 1

        passed = violations == 0
        score = max(0, 1.0 - violations * 0.2)
        return {"passed": passed, "issues": issues, "score": score}

    # ── 可读性 ───────────────────────────────────────────

    def _validate_readability(self, steps: List[Dict]) -> Dict:
        """可读性检查：晦涩表述、句长、自然语言程度"""
        issues = []
        total_checks = 0
        violations = 0

        for step in steps:
            action = step.get("action", "")
            if not action:
                continue

            total_checks += 1

            # 晦涩表述
            for pattern in OBSCURE_PATTERNS:
                if re.search(pattern, action, re.IGNORECASE):
                    violations += 1
                    issues.append(
                        f"Step {step['order']}: 含晦涩表述 (匹配: {pattern})"
                    )
                    break

            # 句长
            if len(action) > MAX_ACTION_LENGTH:
                violations += 1
                issues.append(
                    f"Step {step['order']}: 描述过长 ({len(action)} chars > {MAX_ACTION_LENGTH})"
                )

            # 缺少主语（用户/系统）
            if not re.search(r'用户|系统|页面', action):
                violations += 1
                issues.append(
                    f"Step {step['order']}: 缺少主语（用户/系统/页面）"
                )

        passed = violations == 0
        score = max(0, 1.0 - violations * 0.15)
        return {"passed": passed, "issues": issues, "score": score}

    # ── 流程拓扑 ─────────────────────────────────────────

    def _validate_topology(self, steps: List[Dict], template_path: str) -> Dict:
        """验证步骤流程是否符合业务页面拓扑"""
        issues = []
        violations = 0

        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                template = json.load(f)
        except Exception:
            return {"passed": True, "issues": [], "score": 1.0}

        screen_keys = template.get("baselineMapping", {}).get("screenKeys", SCREEN_KEY_ORDER)

        # 检查步骤中的 targetPage 是否在 screenKeys 中
        for step in steps:
            tp = step.get("targetPage", "")
            if tp and tp not in screen_keys:
                violations += 1
                issues.append(
                    f"Step {step['order']}: targetPage '{tp}' 不在 screenKeys 中: {screen_keys}"
                )

        # 检查是否覆盖了所有关键页面
        pages_covered = set()
        for step in steps:
            tp = step.get("targetPage", "")
            if tp:
                pages_covered.add(tp)

        # 更宽松的检查：如果步骤数少于 5，不强制覆盖
        if len(steps) >= 5:
            for key in ["searchResult", "cart", "checkout"]:
                if key not in pages_covered:
                    violations += 1
                    issues.append(f"流程缺少关键页面: {key}")

        passed = violations == 0
        score = max(0, 1.0 - violations * 0.2)
        return {"passed": passed, "issues": issues, "score": score, "pages_covered": list(pages_covered)}


def validate_flow(
    flow_path: str,
    template_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    便捷入口：直接验证 Flow JSON 文件。

    Args:
        flow_path: Flow JSON 文件路径
        template_path: 模板 JSON 路径（可选，用于拓扑验证）

    Returns:
        验证结果字典
    """
    with open(flow_path, 'r', encoding='utf-8') as f:
        flow_data = json.load(f)

    validator = QualityValidator()
    return validator.validate(flow_data, template_path)
