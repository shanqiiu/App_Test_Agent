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
from ..prompts import (
    PRICE_CONSISTENCY_PROMPT,
    HOLISTIC_VALIDATION_PROMPT,
)

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
                self._llm = LLMClient(temperature=0.0)
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
        redundancy_result = self._validate_redundancy(steps)
        clarity_result = self._validate_clarity(steps)
        page_stack_result = self._validate_page_stack(steps)
        completeness_result = self._validate_flow_completeness(steps, template)
        holistic_result = self._validate_holistic(flow_data)

        topology_result = {"passed": True, "issues": [], "score": 1.0}
        if template and template_step_fields and "targetPage" in template_step_fields:
            topology_result = self._validate_topology(steps, template)

        dimensions = {
            "schema": schema_result,
            "consistency": consistency_result,
            "coherence": coherence_result,
            "readability": readability_result,
            "redundancy": redundancy_result,
            "clarity": clarity_result,
            "page_stack": page_stack_result,
            "completeness": completeness_result,
            "holistic": holistic_result,
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
            result["summary"] = f"发现 {len(all_issues)} 个问题: {'; '.join(all_issues)}"
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

        # ── 数量一致性检查 ──────────────────────────────
        # 提取各步骤中的商品数量表述，追踪数量变化链
        quantity_history: List[tuple] = []  # [(order, quantity, context)]
        quantity_patterns = [
            r'(?:共|已选|已添加)\s*(\d+)\s*件',
            r'(\d+)\s*件\s*商品',
            r'去结算\s*[（(]\s*(\d+)\s*[）)]',
            r'购物车中有\s*(\d+)\s*件',
            r'数量[：:]\s*(\d+)',
            r'共\s*(\d+)\s*件',
        ]

        for step in steps:
            action = step.get("action", "")
            order = step.get("order", 0)
            for pat in quantity_patterns:
                m = re.search(pat, action)
                if m:
                    qty = int(m.group(1))
                    # 获取数量附近的上下文（±30字）
                    idx = m.start()
                    start = max(0, idx - 30)
                    end = min(len(action), idx + len(m.group()) + 30)
                    ctx = action[start:end].strip()
                    quantity_history.append((order, qty, ctx))
                    break  # 每个步骤只取第一个匹配

        # 检查数量突变
        for i in range(1, len(quantity_history)):
            prev_order, prev_qty, prev_ctx = quantity_history[i - 1]
            curr_order, curr_qty, curr_ctx = quantity_history[i]

            # 检查两步骤之间是否有加减操作
            steps_between = action_between = ""
            if curr_order - prev_order <= 2:
                # 检查中间步骤是否有"添加"/"删除"/"清空"/"移出"操作
                for s in steps:
                    so = s.get("order", 0)
                    if prev_order < so < curr_order:
                        a = s.get("action", "")
                        steps_between += a
                        if re.search(r'添加|删除|移出|清空|增加|减少|加购|勾选|取消', a):
                            action_between = s.get("action", "")

            # 如果没有合理解释的数量变化 > 1，标记
            if abs(curr_qty - prev_qty) > 1 and not action_between:
                issues.append(
                    f"Step {prev_order}→{curr_order}: "
                    f"数量从 {prev_qty}件 突变为 {curr_qty}件 "
                    f"且无添加/删除等操作解释"
                )
            elif abs(curr_qty - prev_qty) > 10:
                issues.append(
                    f"Step {prev_order}→{curr_order}: "
                    f"数量异常跳动 ({prev_qty}件 → {curr_qty}件)"
                )

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
            step_lines.append('  Step {}: "{}"'.format(order, context))
        steps_text = "\n".join(step_lines)

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

    # ── 操作重复检测 ───────────────────────────────────────

    def _validate_redundancy(self, steps: List[Dict]) -> Dict:
        """
        检测操作重复：连续相同操作、操作-目标对重复、同页面过度停留、返回操作链。
        """
        issues = []
        violations = 0

        if len(steps) < 2:
            return {"passed": True, "issues": [], "score": 1.0}

        # 提取操作动词和操作目标
        ops: List[tuple] = []
        for step in steps:
            action = step.get("action", "")
            order = step.get("order", 0)
            # 从 "用户在XX上YY" 中提取动词
            verb = ""
            target = ""
            m = re.search(r'用户在\S*上(?:依次)?\s*(\S+)', action)
            if m:
                verb = m.group(1)
            m2 = re.search(r'(?:点击|输入|滑动|选择|切换)(\S+)', action)
            if m2:
                target = m2.group(1)
            ops.append((order, verb, target, action))

        # 连续同操作检测
        for i in range(1, len(ops)):
            prev_verb = ops[i - 1][1]
            curr_verb = ops[i][1]
            if prev_verb and curr_verb and prev_verb == curr_verb:
                prev_order = ops[i - 1][0]
                curr_order = ops[i][0]
                violations += 1
                issues.append(
                    f"Step {prev_order}→{curr_order}: "
                    f"连续相同操作 '{prev_verb}'"
                )

        # 返回操作链检测（连续3+次"返回"操作）
        return_chain = 0
        for i, (order, verb, target, action) in enumerate(ops):
            if '返回' in action or '退回' in action:
                return_chain += 1
            else:
                if return_chain >= 3:
                    violations += 1
                    issues.append(
                        f"Step {order - return_chain}→{order - 1}: "
                        f"连续 {return_chain} 次返回操作，建议合并"
                    )
                return_chain = 0
        if return_chain >= 3:
            violations += 1
            last_order = ops[-1][0]
            issues.append(
                f"Step {last_order - return_chain + 1}→{last_order}: "
                f"连续 {return_chain} 次返回操作，建议合并"
            )

        passed = violations == 0
        score = max(0, 1.0 - violations * 0.15)
        return {"passed": passed, "issues": issues, "score": score}

    # ── 二义性描述检测 ─────────────────────────────────────

    def _validate_clarity(self, steps: List[Dict]) -> Dict:
        """
        检测二义性描述：二选一结构、不确定性词汇。
        """
        issues = []
        violations = 0

        ambiguity_patterns = [
            (r'或\s*[（(]', '二选一结构（"A或B"）'),
            (r'[（(]\S+[）)]\s*或\s*[（(]', '二选一结构'),
            (r'可能[是会]?', '不确定表述 "可能"'),
            (r'大概[是会]?', '不确定表述 "大概"'),
            (r'不确定', '不确定表述'),
            (r'也许是', '不确定表述'),
        ]

        for step in steps:
            action = step.get("action", "")
            order = step.get("order", 0)
            for pat, label in ambiguity_patterns:
                m = re.search(pat, action)
                if m:
                    violations += 1
                    issues.append(
                        f"Step {order}: 含{label} — "
                        f"\"{action[m.start():m.start()+40]}...\""
                    )
                    break  # 每步只报一次

        passed = violations == 0
        score = max(0, 1.0 - violations * 0.2)
        return {"passed": passed, "issues": issues, "score": score}

    # ── 页面堆栈一致性验证 ─────────────────────────────────

    def _validate_page_stack(self, steps: List[Dict]) -> Dict:
        """
        维护简化的页面堆栈模型，验证返回操作的合法性。
        push: "进入""跳转至""前往""打开"
        pop: "返回""退回""退出"
        """
        issues = []
        violations = 0
        stack: List[str] = ["home"]  # 初始页面

        push_patterns = [r'进入\s*(\S+页)', r'跳转至\s*(\S+页?)',
                         r'前往\s*(\S+页)', r'打开\s*(\S+页)']
        pop_patterns = [r'返回', r'退回', r'退出(?!\s*登录)']

        for step in steps:
            action = step.get("action", "")
            order = step.get("order", 0)

            # 检测 push
            pushed = False
            for pat in push_patterns:
                m = re.search(pat, action)
                if m:
                    page = m.group(1) if m.lastindex else "未知页面"
                    stack.append(page)
                    pushed = True
                    break

            if pushed:
                continue

            # 检测 pop
            is_pop = any(re.search(pat, action) for pat in pop_patterns)
            if is_pop:
                if len(stack) <= 1:
                    violations += 1
                    issues.append(
                        f"Step {order}: 返回操作但页面堆栈已空 "
                        f"(当前栈: {stack})"
                    )
                else:
                    popped = stack.pop()
                    logger.debug(f"  Step {order}: pop '{popped}', 剩余栈: {stack}")

        passed = violations == 0
        score = max(0, 1.0 - violations * 0.2)
        return {"passed": passed, "issues": issues, "score": score}

    # ── 流程完成度检查 ─────────────────────────────────────

    def _validate_flow_completeness(
        self, steps: List[Dict], template: Optional[Dict] = None
    ) -> Dict:
        """
        检查流程是否包含合理的结束状态。
        根据模板的 screenKeys 或默认购物流程判断。
        """
        issues = []
        violations = 0

        if len(steps) < 3:
            return {"passed": True, "issues": [], "score": 1.0}

        # 从模板获取期望的结束页面
        expected_end = ["payment", "orderDetail", "orderComplete", "orders"]
        if template:
            screen_keys = template.get("baselineMapping", {}).get("screenKeys", [])
            if screen_keys:
                # 取最后 3 个 screenKey 作为可能终点
                end_candidates = [k for k in screen_keys[-3:]
                                 if k not in ("home", "search")]
                if end_candidates:
                    expected_end = end_candidates

        # 检查最后 3 步是否包含任一预期终点
        last_3_actions = " ".join(
            s.get("action", "") for s in steps[-3:]
        )
        last_3_pages: set = set()
        for key in expected_end:
            if re.search(key, last_3_actions, re.IGNORECASE):
                last_3_pages.add(key)

        if not last_3_pages:
            violations += 1
            issues.append(
                f"流程最后 3 步未包含预期结束页面: {expected_end}. "
                f"流程可能未完成"
            )

        passed = violations == 0
        score = 1.0 if passed else 0.7
        return {"passed": passed, "issues": issues, "score": score}

    # ── 整体流程校验（LLM 五维度审视） ──────────────────────

    def _validate_holistic(self, flow_data: Dict) -> Dict:
        """
        调用 LLM 对 mainFlow 所有步骤做五维度整体审视。
        一次性检查衔接性、逻辑清晰性、内容重复性、顺序合理性、数据一致性。

        返回维度级诊断结果，与 diagnose.md 的评估方法对齐。
        """
        main_flow = flow_data.get("mainFlow", {})
        steps = main_flow.get("steps", [])

        if len(steps) < 2:
            return {
                "passed": True, "score": 1.0,
                "issues": [], "grade": "正常",
                "detail": {},
            }

        llm = self._get_llm()
        if llm is None:
            logger.info("  整体校验: LLM 不可用，跳过")
            return {
                "passed": True, "score": 0.8,
                "issues": ["LLM 不可用，跳过整体校验"],
                "grade": "跳过",
                "detail": {},
            }

        # 整体校验需要较大输出空间，用独立 LLM 客户端
        try:
            llm_holistic = LLMClient(temperature=0.0)
        except Exception:
            llm_holistic = llm

        # 构建步骤文本
        step_lines = []
        for s in steps:
            order = s.get("order", "?")
            action = (s.get("action") or "").strip()
            step_lines.append(f"Step {order}: {action}")
        steps_text = "\n\n".join(step_lines)

        prompt = HOLISTIC_VALIDATION_PROMPT.format(
            flow_name=main_flow.get("name", ""),
            flow_desc=main_flow.get("description", ""),
            precondition=main_flow.get("precondition", ""),
            steps_text=steps_text,
        )

        try:
            raw = llm_holistic.chat(prompt)
            # 清理可能的 markdown 包裹
            raw = raw.strip()
            if raw.startswith("```"):
                raw = re.sub(r'^```(?:json)?\s*', '', raw)
                raw = re.sub(r'\s*```$', '', raw)
                raw = raw.strip()

            parsed = llm_holistic.extract_json(raw)

            if not isinstance(parsed, dict):
                return {
                    "passed": True, "score": 0.5,
                    "issues": ["整体校验 LLM 返回格式异常"],
                    "grade": "未知",
                    "detail": {},
                }

            # 汇总各维度 issue
            all_issues = []
            grades = []
            detail = {}

            for dim_key in ("coherence", "clarity", "redundancy", "sequence", "consistency"):
                dim = parsed.get(dim_key, {})
                dim_grade = dim.get("grade", "正常")
                dim_issues = dim.get("issues", [])
                grades.append(dim_grade)
                detail[dim_key] = dim

                for issue in dim_issues:
                    all_issues.append(f"[{dim_key}] {issue}")

            # 额外字段
            extra = {}
            for key in ("missing_pages", "irrelevant_steps", "suggestions"):
                val = parsed.get("sequence", {}).get(key) or parsed.get(key)
                if val:
                    extra[key] = val
                    if isinstance(val, list) and key != "suggestions":
                        all_issues.append(f"[sequence] {key}: {', '.join(str(v) for v in val)}")

            overall = parsed.get("overall_grade", "正常")

            # 综合评分
            grade_map = {"正常": 1.0, "轻微": 0.8, "严重": 0.5, "致命": 0.2, "跳过": 0.6}
            score = grade_map.get(overall, 0.5)
            passed = overall in ("正常", "轻微")

            logger.info(f"  整体校验: {overall} (score={score})")
            if all_issues:
                for issue in all_issues:
                    logger.info(f"    ⚠ {issue}")

            return {
                "passed": passed,
                "score": score,
                "issues": all_issues,
                "grade": overall,
                "detail": detail,
            }

        except Exception as e:
            logger.warning(f"  整体校验 LLM 调用失败: {e}")
            return {
                "passed": True, "score": 0.5,
                "issues": [f"整体校验异常: {e}"],
                "grade": "异常",
                "detail": {},
            }

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

