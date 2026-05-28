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

from .llm_client import LLMClient

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


# ── 价格一致性 Few-Shot Prompt ──────────────────────────

PRICE_CONSISTENCY_PROMPT = """你是一个电商流程数据质量检查专家。判断以下操作步骤中的多个价格是否属于数据不一致。

## 判断规则
- 多款不同商品各有不同价格 → ✅ 正常
- 同一商品**同一价格类型**在不同步骤变化 → ❌ 是不一致
- 同一商品同时出现**不同价格类型**（如：原价 vs 补贴价 vs 国补后价 vs 券后价 vs 总价）→ ✅ 正常，这是不同价格语义
- 补贴金额/优惠金额/减免金额 → ✅ 正常，和售价是不同概念
- 用户输入的筛选价格上限/下限 → 忽略，不应计入
- **核心原则**：判断是否不一致的核心是看"同一价格类型"是否变化。原价¥1648和补贴后价¥1400.8是同一个商品的两个不同价格类型，**不是不一致**。

## 示例

示例1 - 正常（多商品不同价格）:
步骤:
  Step 7: "展示畅享70X（1648元）和畅享70X活力版（1299元）等多款手机"
  Step 8: "用户点击华为畅享70X（1648元）"
提取到的价格: 1648, 1299
判断: 正常。两个不同商品有不同的价格，搜索结果页的正常展示。

示例2 - 正常（原价与补贴价共存，同一页面）:
步骤:
  Step 20: "订单确认页展示华为畅享70X手机，数量1件，总价¥1648元，补贴后价¥1400.8元，已优惠¥247.2元"
提取到的价格: 1648, 1400.8, 247.2
判断: 正常。同一订单确认页同时展示原价¥1648、补贴后价¥1400.8、优惠金额¥247.2，属于不同价格类型（原价/补贴价/优惠额），不是不一致。

示例3 - 正常（原价与补贴价跨步骤）:
步骤:
  Step 9: "商品详情页展示价格1648元"
  Step 11: "购物车显示补贴后价1400.8元"
提取到的价格: 1648, 1400.8
判断: 正常。Step 9展示原价，Step 11展示补贴后价，价格类型不同。

示例4 - 不一致（同一价格类型变化）:
步骤:
  Step 8: "购物车总价显示¥2999"
  Step 10: "提交订单总价显示¥3499"
提取到的价格: 2999, 3499
判断: 不一致。购物车和结算的总价（同一价格类型）不同且无合理解释。

## 待判断的流程
步骤:
{steps_text}

提取到的价格: {price_list}

请仅输出以下格式之一（不要其他内容）：
正常: <简要理由>
不一致: <简要理由>"""


class QualityValidator:
    """Flow 输出质量验证器"""

    def __init__(self, llm: Optional[LLMClient] = None):
        """
        Args:
            llm: 可选 LLM 客户端。不传时按需从环境变量创建。
        """
        self._llm = llm

    def _get_llm(self) -> Optional[LLMClient]:
        """获取 LLM 客户端（延迟初始化）"""
        if self._llm is None:
            try:
                self._llm = LLMClient(temperature=0.0, max_tokens=128)
            except Exception:
                return None
        return self._llm

    def validate(self, flow_data: Dict, template_path: Optional[str] = None) -> Dict[str, Any]:
        """
        执行全维度验证。

        Args:
            flow_data: Flow JSON 数据
            template_path: 模板路径（可选，用于推导字段约束 + 拓扑 screenKeys）

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

        # 从模板读取步骤字段约束（仅验证模板中存在的字段）
        template_step_fields = None
        template = None
        if template_path:
            template = self._load_template(template_path)
            if template:
                template_steps = template.get("mainFlow", {}).get("steps", [])
                if template_steps:
                    template_step_fields = list(template_steps[0].keys())
                    # 确保必填字段始终在列表中
                    for required in REQUIRED_FIELDS:
                        if required not in template_step_fields:
                            template_step_fields.append(required)

        # 各维度验证
        schema_result = self._validate_schema(steps, template_step_fields)
        consistency_result = self._validate_consistency(steps)
        coherence_result = self._validate_coherence(steps)
        readability_result = self._validate_readability(steps)

        topology_result = {"passed": True, "issues": [], "score": 1.0}
        if template and template_step_fields and "targetPage" in template_step_fields:
            topology_result = self._validate_topology(steps, template)

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

    def _validate_schema(self, steps: List[Dict],
                         template_step_fields: Optional[List[str]] = None) -> Dict:
        """
        Schema 合规性验证。

        Args:
            steps: 步骤列表
            template_step_fields: 模板定义的步骤字段列表。
                                  仅验证这些字段的覆盖度，避免对模板不存在的字段误报。
                                  为 None 时使用硬编码后备（兼容未传模板的场景）。
        """
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

        # 可选字段 coverage — 仅验证模板中存在的字段
        optional_fields = self._get_optional_fields(template_step_fields)
        optional_coverage = {}
        for field in optional_fields:
            count = sum(1 for s in steps if field in s)
            optional_coverage[field] = f"{count}/{len(steps)}"
            if count == 0:
                issues.append(f"所有步骤均缺少 {field} 字段")

        score = sum(scores) / len(scores) if scores else 0
        passed = len([i for i in issues if "缺少必填" in i]) == 0

        return {"passed": passed, "issues": issues, "score": score, "coverage": optional_coverage}

    @staticmethod
    def _get_optional_fields(template_step_fields: Optional[List[str]]) -> List[str]:
        """
        从模板步骤字段中推导可选字段列表。

        模板字段中剔除必填字段后即为可选字段。
        若 template_step_fields 为 None（未传入模板），返回空列表（不检查可选字段覆盖度）。
        """
        if template_step_fields is None:
            return []
        return [f for f in template_step_fields if f not in REQUIRED_FIELDS]

    # ── 数据一致性 ───────────────────────────────────────

    def _validate_consistency(self, steps: List[Dict]) -> Dict:
        """
        跨步骤数据一致性验证。

        品牌检查：纯规则提取。
        价格检查：正则提取 + 归一化去重；
                 若仍有多个价格 → Few-Shot LLM 判别是否为真实不一致；
                 若 LLM 不可用 → 跳过价格检查（保守策略）。
        """
        issues = []

        # ── 品牌检查（纯规则） ──────────────────────────
        product_names = set()
        for step in steps:
            action = step.get("action", "")
            for m in re.finditer(
                    r'[\u4e00-\u9fff\w]+\s*[\u4e00-\u9fff\w]+(?:Pro|Max|Ultra|\d+[\w]*)*',
                    action):
                if len(m.group()) > 3:
                    product_names.add(m.group())

        brands_found = set()
        for name in product_names:
            for brand in ["华为", "iPhone", "Apple", "小米", "三星", "荣耀", "OPPO", "vivo"]:
                if brand in name:
                    brands_found.add(brand)
        if len(brands_found) > 1:
            issues.append(f"步骤中出现多个品牌: {', '.join(brands_found)}")

        # ── 价格提取（正则 + 归一化） ──────────────────
        # 收集 (order, raw_text, numeric_value) 用于 LLM 上下文
        all_prices: List[tuple] = []
        price_numerics: set = set()

        for step in steps:
            action = step.get("action", "")
            order = step.get("order", 0)

            for m in re.finditer(r'¥?\s*(\d+[\.\d]*)\s*元', action):
                raw = m.group(0)
                try:
                    numeric = float(m.group(1))
                except ValueError:
                    continue
                all_prices.append((order, raw, numeric))
                price_numerics.add(numeric)

        # 如果只有一个价格（或没有），直接通过
        if len(price_numerics) <= 1:
            passed = len(issues) == 0
            score = 1.0 if passed else max(0.3, 1.0 - len(issues) * 0.3)
            return {"passed": passed, "issues": issues, "score": score}

        # ── 多个价格 → Few-Shot LLM 判别 ───────────────
        llm = self._get_llm()
        if llm is None:
            # LLM 不可用时保守策略：不报错（跳过价格检查）
            logger.info("  价格检查: LLM 不可用，跳过")
            passed = len(issues) == 0
            score = 1.0 if passed else max(0.3, 1.0 - len(issues) * 0.3)
            return {"passed": passed, "issues": issues, "score": score}

        # 构建步骤上下文（只包含有价格的步骤，截断避免超 token）
        step_lines = []
        for order, raw, numeric in all_prices:
            step_action = ""
            for s in steps:
                if s.get("order") == order:
                    step_action = s.get("action", "")
                    break
            # 提取价格附近的文本（前后各 60 字，适应多行 action 格式）
            idx = step_action.find(raw)
            start = max(0, idx - 60)
            end = min(len(step_action), idx + len(raw) + 60)
            context = step_action[start:end].strip()
            step_lines.append('  Step {}: "{}"'.format(order, context[:120]))
        steps_text = "\n".join(step_lines)[:2000]

        price_list = ", ".join(
            sorted(f'¥{int(p)}元' if p == int(p) else f'¥{p}元' for p in price_numerics)
        )

        prompt = PRICE_CONSISTENCY_PROMPT.format(
            steps_text=steps_text,
            price_list=price_list,
        )

        try:
            llm_result = llm.chat(prompt).strip()
            logger.info(f"  价格一致性 LLM 判断: {llm_result}")

            if llm_result.startswith("不一致"):
                issues.append(f"步骤中出现多个商品售价: {price_list}（LLM: {llm_result}）")
            else:
                logger.info(f"  价格差异已由 LLM 判定为正常: {llm_result}")
        except Exception as e:
            logger.warning(f"  价格一致性 LLM 判断失败: {e}")

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

    def _validate_topology(self, steps: List[Dict], template: Dict) -> Dict:
        """验证步骤流程是否符合业务页面拓扑"""
        issues = []
        violations = 0

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

    @staticmethod
    def _load_template(template_path: str) -> Optional[Dict]:
        """安全加载模板 JSON"""
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            logger.warning(f"无法加载模板: {template_path}")
            return None


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
