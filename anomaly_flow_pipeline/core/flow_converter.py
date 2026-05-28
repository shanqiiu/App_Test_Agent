"""
flow_converter.py — 将修改后的 utg_info.json 智能合并到 Flow 模板（Phase 2）

相比原始版本的盲替换，新增：
1. 步骤 → screenKey (targetPage) 语义映射
2. 利用模板 mockInstances 做数据绑定（单一真相源）
3. 支持补充缺失的关键页面（从模板补齐）
4. LLM 智能分配 targetPage（当 Rule-based 无法匹配时）

输出格式符合 Schema：
{
  "order": 1,
  "action": "用户在搜索框输入'iPhone 16 Pro'，系统展示搜索结果",
  "targetPage": "searchResult",
  "anomalyTag": null
}
"""

import json
import logging
import re
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from .llm_client import LLMClient

logger = logging.getLogger(__name__)

# ── 内置 screenKey → 中文关键词映射 ─────────────────────

SCREEN_KEY_KEYWORDS: Dict[str, List[str]] = {
    "home": ["首页", "推荐", "主页", "启动"],
    "search": ["搜索框", "输入关键词", "搜索页", "联想词", "搜索"],
    "searchResult": ["搜索结果", "商品列表", "筛选", "排序", "热卖榜", "商品信息"],
    "productDetail": ["商品详情", "轮播图", "图片轮播", "规格", "SKU", "选择规格",
                      "加入购物车", "加购"],
    "cart": ["购物车", "结算", "去结算"],
    "checkout": ["结算确认", "确认订单", "订单确认", "收货地址", "提交订单",
                 "优惠券", "支付方式"],
    "payment": ["支付", "收银台", "付款", "确认付款"],
    "orders": ["订单", "我的订单"],
    "orderDetail": ["订单详情", "支付成功", "订单号", "待发货"],
}

SCREEN_KEY_ORDER = [
    "home", "search", "searchResult", "productDetail",
    "cart", "checkout", "payment", "orders", "orderDetail",
]


def _match_screen_key(ui_summary: str, prev_key: Optional[str] = None) -> str:
    """
    基于关键词匹配 + 流程拓扑序生成 screenKey 参考建议。

    注意：此函数不再作为最终的 targetPage 决策路径，仅用于生成
    LLM prompt 中的 rule_hint 参考信息。最终决策由 LLM 做出。

    Args:
        ui_summary: 步骤的 UI 描述文本
        prev_key: 上一步的 targetPage（用于拓扑约束）

    Returns:
        建议的 screenKey（供 LLM 参考）
    """
    if not ui_summary:
        return "home"

    # 精确匹配：从后往前匹配（更具体的关键词优先）
    best_key = "home"
    best_score = 0

    for key, keywords in SCREEN_KEY_KEYWORDS.items():
        score = 0
        for kw in keywords:
            # 大小写不敏感，检查是否在文本中
            if kw.lower() in ui_summary.lower():
                score += 1
        if score > best_score:
            best_score = score
            best_key = key

    # 如果 prev_key 存在且匹配得分相同，优先保持连续
    if prev_key and best_key == "home" and prev_key != "home":
        # 检查是否可能是上一步的延续
        for key in SCREEN_KEY_KEYWORDS:
            if key == prev_key:
                for kw in SCREEN_KEY_KEYWORDS[key]:
                    if kw.lower() in ui_summary.lower():
                        return prev_key

    # 拓扑约束：不允许往回跳（除非是返回操作）
    if prev_key and best_key != prev_key:
        prev_idx = SCREEN_KEY_ORDER.index(prev_key) if prev_key in SCREEN_KEY_ORDER else -1
        best_idx = SCREEN_KEY_ORDER.index(best_key) if best_key in SCREEN_KEY_ORDER else -1
        # 如果是返回操作（back），允许往回跳
        is_back = any(w in ui_summary.lower() for w in ["返回", "back"])
        if not is_back and best_idx < prev_idx and best_idx >= 0:
            # 可能是误匹配，保留上一步
            if best_score <= 1:
                return prev_key

    return best_key


# ── 智能 screenKey 分配（LLM 主导 + 关键词约束） ────────────

SCREEN_KEY_LLM_PROMPT = """你是一个 App 页面类型分类专家。根据 UI 描述判断该步骤所属的页面类型。

## 可选页面类型（screenKey）及对应关键词参考
{screen_keys_str}

## 当前步骤
- UI 描述: {ui_summary}
- 用户操作意图: {thought}
- 上一步页面类型: {prev_key}

## 规则匹配参考（仅参考，需结合语义综合判断）
{rule_hint}

## 要求
1. **必须**从上述可选页面类型中选择最匹配的一项
2. 遵循购物流程拓扑顺序：首页 → 搜索 → 搜索结果 → 商品详情 → 购物车 → 结算 → 支付 → 订单。不应无理由往回跳转（除非是明确的返回操作）
3. 规则匹配参考仅作提示，优先根据 UI 描述的语义判断
4. 仅返回 screenKey 字符串，不要其他内容"""


# ── 智能实例匹配（LLM 主导） ────────────────────────────

INSTANCE_MATCH_PROMPT = """你是一个电商商品匹配专家。根据用户搜索意图，从可用商品列表中选择最匹配的一个。

## 用户搜索
{query}

## 规则分析参考（仅参考）
- 品牌提示: {brand_hint}
- 品类提示: {category_hint}
- 价格提示: {price_hint}

## 可用商品列表
{instances_str}

## 要求
1. 分析用户搜索意图中的品牌、品类和价格区间
2. 从可用商品列表中选择最匹配的一个
3. 匹配优先级：品牌一致性 > 品类一致性 > 价格区间接近度
4. 仅返回 instanceId，不要其他内容"""


# ── 从 UTG stepData 提取 mock 实例（LLM 主导） ──────────

EXTRACT_MOCK_PROMPT = """你是一个电商数据抽取专家。从以下用户操作步骤中提取用户最终购买的主要商品信息，生成一个 mock 商品实例。

输出的 JSON 结构必须严格遵循以下格式，所有字段不可缺失、不可捏造。步骤中未提及的字段一律设为 null。

## 用户意图（参考）
{query}

## 操作步骤描述
{steps_text}

## 输出结构（严格遵循，不可增减字段）
{{
  "instanceId": "instance_from_query",
  "imageUrl": null,
  "values": {{
    "brand": "<品牌>",
    "model": "<型号>",
    "price": <价格数字>,
    "storage": "<存储容量>",
    "color": "<颜色>",
    "processor": "<处理器>",
    "rating": <评分数字>,
    "salesVolume": <销量数字>,
    "productId": null,
    "skuId": null,
    "orderId": null,
    "addressId": null,
    "couponId": null,
    "subsidyPrice": null,
    "subsidyAmount": null,
    "maxPrice": null,
    "promotionTag": null,
    "quantity": null,
    "deliveryMethod": null,
    "deliveryTime": null,
    "address": null
  }}
}}

## 填充规则（严格遵循）
1. brand/model/price/storage/color/processor 必须从**操作步骤描述**中提取，禁止凭空捏造
2. 如果步骤中明确提到了具体型号（如"畅享70X"、"Mate 50"），必须使用步骤中的型号，不得从 query 的模糊描述（如"华为手机"）中自行实例化
3. 如果步骤中出现多个价格，以最终结算/支付步骤的金额为准
4. rating/salesVolume 用合理默认值
5. 其余字段一律设为 null
6. price 必须是数字，不可为字符串
7. 不得添加输出结构中不存在的字段"""


# ── 后备：从 UTG query 生成 mock 实例（仅当步骤提取失败时使用） ──

GENERATE_MOCK_PROMPT = """你是一个电商数据抽取专家。从用户搜索查询中提取商品信息，生成一个 mock 商品实例。

输出的 JSON 结构必须严格遵循以下格式，所有字段不可缺失、不可捏造。

## 用户搜索
{query}

## 输出结构（严格遵循，不可增减字段）
{{
  "instanceId": "instance_from_query",
  "imageUrl": null,
  "values": {{
    "brand": "<品牌>",
    "model": "<型号>",
    "price": <价格数字>,
    "storage": "<存储容量>",
    "color": "<颜色>",
    "processor": "<处理器>",
    "rating": <评分数字>,
    "salesVolume": <销量数字>,
    "productId": null,
    "skuId": null,
    "orderId": null,
    "addressId": null,
    "couponId": null,
    "subsidyPrice": null,
    "subsidyAmount": null,
    "maxPrice": null,
    "promotionTag": null,
    "quantity": null,
    "deliveryMethod": null,
    "deliveryTime": null,
    "address": null
  }}
}}

## 填充规则
1. brand/model/price/storage/color/processor 从查询中推断
2. rating/salesVolume 用合理默认值
3. 其余所有字段（productId/skuId/orderId/addressId/couponId/subsidyPrice/subsidyAmount/maxPrice/promotionTag/quantity/deliveryMethod/deliveryTime/address）一律设为 null
4. price 必须是数字，不可为字符串
5. 不得添加输出结构中不存在的字段"""


class FlowConverter:
    """
    Flow 模板智能转换器

    整合：
    - targetPage 语义映射（Rule-based + LLM 兜底）
    - mockInstances 数据绑定
    - 缺失步骤补齐（从模板获取）
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
            temperature=0.0,
            max_tokens=64,
        )

    # ── screenKey 分配 ────────────────────────────────────

    def assign_screen_keys(
        self,
        steps: List[Dict],
    ) -> List[Dict]:
        """
        为每步分配 targetPage (screenKey)。

        LLM 主导分配，SCREEN_KEY_KEYWORDS 预定义关键词映射作为 prompt 中的分类约束。
        规则匹配结果作为参考提示，LLM 结合语义做出最终判断。

        Args:
            steps: [{"order": int, "action": str}, ...]

        Returns:
            [{"order": int, "action": str, "targetPage": str}, ...]
        """
        screen_keys_str = "\n".join(
            f"- {k}: {'/'.join(v)}"
            for k, v in SCREEN_KEY_KEYWORDS.items()
        )

        prev_key = None
        result = []

        for step in steps:
            action = step.get("action", "")
            thought = step.get("thought", "")
            order = step.get("order", 0)

            # 规则匹配（仅作为 LLM prompt 中的参考提示）
            rule_result = _match_screen_key(action, prev_key)
            matched_kws = []
            for kw in SCREEN_KEY_KEYWORDS.get(rule_result, []):
                if kw.lower() in action.lower():
                    matched_kws.append(kw)
            if matched_kws:
                rule_hint = (
                    f"→ 规则分析: {rule_result} "
                    f"（匹配关键词: {', '.join(matched_kws[:3])}）"
                )
            else:
                rule_hint = f"→ 规则分析: {rule_result}（未直接匹配关键词）"

            # LLM 主导判断
            target_page = "home"
            try:
                prompt = SCREEN_KEY_LLM_PROMPT.format(
                    screen_keys_str=screen_keys_str,
                    ui_summary=action[:500],
                    thought=thought[:200] if thought else "(无)",
                    prev_key=prev_key or "home",
                    rule_hint=rule_hint,
                )
                llm_result = self.llm.chat(prompt).strip().lower()
                if llm_result in SCREEN_KEY_KEYWORDS:
                    target_page = llm_result
            except Exception as e:
                logger.warning(
                    f"  LLM screenKey 分配失败 (Step {order}): {e}，使用规则结果"
                )
                target_page = rule_result

            result.append({
                "order": order,
                "action": action,
                "targetPage": target_page,
            })
            prev_key = target_page

        return result

    # ── mockInstances 数据绑定 ────────────────────────────

    def bind_mock_data(
        self,
        steps: List[Dict],
        mock_instances: List[Dict],
        query: str,
    ) -> List[Dict]:
        """
        将 steps 中的商品数据与 mockInstances 绑定，实现数据一致性。

        匹配策略：
        1. 从 query 提取商品意图（LLM 驱动，规则提取作为 prompt 参考）
        2. LLM 匹配最佳 mockInstance
        3. 将匹配的实例数据注入到 action 描述中

        Args:
            steps: [{"order": int, "action": str, "targetPage": str}, ...]
            mock_instances: 模板中的 mockInstances 列表
            query: utg_info.json 中的 query 字段

        Returns:
            数据绑定后的步骤列表
        """
        if not mock_instances:
            return steps

        # Step 1: 规则提取意图（作为 LLM prompt 中的参考提示）
        intent = self._extract_product_intent(query)

        # Step 2: LLM 匹配最佳 mockInstance
        matched = self._llm_match_instance(query, intent, mock_instances)

        if not matched:
            logger.info("  数据绑定: 无匹配的 mockInstance")
            return steps

        instance_id = matched.get("instanceId", "")
        values = matched.get("values", {})
        logger.info(
            f"  数据绑定: 匹配 {instance_id} "
            f"({values.get('brand', '')} {values.get('model', '')})"
        )

        # Step 3: 将数据注入 action 描述
        bound_steps = []
        for step in steps:
            action = step.get("action", "")
            target_page = step.get("targetPage", "")

            # 仅对商品相关页面做数据注入
            if target_page in ("searchResult", "productDetail", "cart", "checkout", "payment", "orderDetail"):
                action = self._inject_data_into_action(action, values)

            bound_steps.append({
                "order": step["order"],
                "action": action,
                "targetPage": target_page,
                "boundMockId": instance_id,
            })

        return bound_steps

    def _extract_product_intent(self, query: str) -> Dict[str, str]:
        """从 query 提取商品意图"""
        intent = {"brand": "", "category": "", "keyword": query[:100]}

        # 简单的品牌提取
        brand_patterns = [
            (r'华为|HUAWEI', "华为"),
            (r'iPhone|Apple|苹果', "Apple"),
            (r'小米|Xiaomi', "小米"),
            (r'三星|Samsung', "三星"),
        ]
        for pattern, brand in brand_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                intent["brand"] = brand
                break

        # 品类提取
        category_patterns = [
            r'手机', r'电脑|笔记本', r'平板', r'耳机',
            r'电视', r'冰箱', r'洗衣机', r'空调',
        ]
        for pattern in category_patterns:
            if re.search(pattern, query):
                intent["category"] = pattern
                break

        # 价格区间提取
        price_match = re.search(r'(\d+)\s*[以之内下\-\~]\s*(\d*)', query)
        if price_match:
            intent["max_price"] = price_match.group(1)

        return intent

    def _llm_match_instance(
        self, query: str, intent: Dict[str, str], mock_instances: List[Dict]
    ) -> Optional[Dict]:
        """
        LLM 驱动的实例匹配。

        预定义的品牌/品类/价格提取规则作为 prompt 中的参考提示，
        LLM 结合语义做出最终匹配决策。

        Args:
            query: 用户搜索查询
            intent: 规则提取的商品意图（作为 LLM 参考）
            mock_instances: 可用商品实例列表

        Returns:
            匹配的实例，或 None
        """
        if not mock_instances:
            return None

        brand_hint = intent.get("brand") or "未识别"
        category_hint = intent.get("category") or "未识别"
        price_hint = (
            f"最高 {intent['max_price']} 元"
            if intent.get("max_price") else "未指定"
        )

        instances_str = "\n".join(
            f"- {inst['instanceId']}: "
            f"{inst.get('values', {}).get('brand', '')} "
            f"{inst.get('values', {}).get('model', '')}, "
            f"¥{inst.get('values', {}).get('price', '')}, "
            f"{inst.get('values', {}).get('storage', '')}, "
            f"{inst.get('values', {}).get('color', '')}"
            for inst in mock_instances
        )

        prompt = INSTANCE_MATCH_PROMPT.format(
            query=query[:200],
            brand_hint=brand_hint,
            category_hint=category_hint,
            price_hint=price_hint,
            instances_str=instances_str,
        )

        try:
            result = self.llm.chat(prompt).strip()
            matched = next(
                (inst for inst in mock_instances if inst.get("instanceId") == result),
                None,
            )
            if matched:
                logger.info(
                    f"  LLM 匹配实例: {matched.get('instanceId')} "
                    f"({matched.get('values', {}).get('brand', '')} "
                    f"{matched.get('values', {}).get('model', '')})"
                )
                return matched
            logger.warning(f"  LLM 返回的 instanceId 无效: {result}")
        except Exception as e:
            logger.warning(f"  LLM 实例匹配失败: {e}")

        # Fallback: 返回第一个实例（仅发生在 LLM 调用失败时，不是独立决策路径）
        logger.info("  LLM 匹配失败，使用第一个可用实例作为 fallback")
        return mock_instances[0]

    def _inject_data_into_action(self, action: str, values: Dict) -> str:
        """将商品数据注入 action 描述"""
        brand = values.get("brand", "")
        model = values.get("model", "")
        storage = values.get("storage", "")
        color = values.get("color", "")
        price = str(values.get("price", ""))

        # 构建商品全称
        product_name = f"{brand} {model}"
        if storage:
            product_name += f" {storage}"
        if color:
            product_name += f" {color}"

        # 尝试替换现有商品引用
        # 匹配常见的中文商品名模式
        patterns = [
            (r'华为\S*', product_name),
            (r'iPhone\s*\S*', product_name),
            (r'小米\S*', product_name),
            (r'三星\S*', product_name),
            (r'畅享\S*', product_name),
            (r'nova\S*', product_name),
        ]
        replaced = False
        for pattern, replacement in patterns:
            if re.search(pattern, action):
                action = re.sub(pattern, replacement, action)
                replaced = True
                break

        # 替换价格
        price_patterns = [
            r'¥?\s*\d+[\.\d]*\s*元',
            r'价格\s*\d+[\.\d]*',
            r'\d+\.?\d*\s*元',
        ]
        for p in price_patterns:
            if re.search(p, action):
                action = re.sub(p, f"¥{price}元", action)
                break

        if not replaced:
            # 在结果页、详情页等场景，注入商品名
            if any(kw in action for kw in ["搜索", "结果", "列表", "展示"]):
                action = action.rstrip("。，") + f"，展示{product_name}相关信息"

        return action

    # ── 主转换流程 ────────────────────────────────────────

    def convert(
        self,
        utg_path: str,
        template_path: str,
        output_path: str,
        mode: str = "replace",
        enable_screen_key: bool = True,
        enable_data_binding: bool = True,
    ) -> Dict[str, Any]:
        """
        智能转换：UTG + Flow 模板 → 高质量 Flow JSON。

        Args:
            utg_path: 预处理后的 utg_info.json 路径
            template_path: Flow 模板 JSON 路径（优先 _new.json）
            output_path: 输出路径
            mode: "replace" - 完全替换, "fill" - 按顺序填充, "smart" - 智能合并
            enable_screen_key: 是否分配 targetPage
            enable_data_binding: 是否绑定 mockInstances 数据

        Returns:
            {
                "success": bool,
                "output_path": str,
                "step_count": int,
                "screen_keys_assigned": int|None,
                "bound_mock_id": str|None,
                "error": str|None,
            }
        """
        result = {
            "success": False,
            "output_path": output_path,
            "step_count": 0,
            "screen_keys_assigned": None,
            "bound_mock_id": None,
            "error": None,
        }

        try:
            utg_data = self._load_json(utg_path)
            template = self._load_json(template_path)

            # 提取有效步骤
            utg_steps = self._get_valid_steps_from_utg(utg_data)
            if not utg_steps:
                result["error"] = "utg_info.json 中没有有效的 ui_summary 步骤"
                return result

            logger.info(f"UTG 有效步骤: {len(utg_steps)}")

            merged = deepcopy(template)

            # 确保 mainFlow 存在
            if "mainFlow" not in merged:
                merged["mainFlow"] = {
                    "id": "flow-from-utg",
                    "steps": [],
                }

            # mainFlow 的实例化字段由 UTG 数据决定，模板原有数据仅作 spec 参考，不作数
            merged["mainFlow"]["id"] = "flow-from-utg"
            merged["mainFlow"]["name"] = utg_data.get("query", "操作流程")
            merged["mainFlow"]["description"] = utg_data.get("query", "")
            merged["mainFlow"]["precondition"] = (
                f"用户已登录，{utg_data.get('appName', 'APP')}首页正常加载"
            )

            # 构建基础步骤
            new_steps = [
                {"order": s["order"], "action": s["ui_summary"]}
                for s in utg_steps
            ]

            # Step 1: 分配 targetPage（screenKey 映射）
            if enable_screen_key:
                new_steps = self.assign_screen_keys(new_steps)
                screen_key_count = sum(
                    1 for s in new_steps if s.get("targetPage") and s["targetPage"] != "home"
                )
                result["screen_keys_assigned"] = screen_key_count
                logger.info(f"  targetPage 分配: {screen_key_count}/{len(new_steps)} 步")

            # Step 2: 数据绑定（从 UTG stepData 提取 mock 实例，与 mainFlow.steps 保持一致）
            if enable_data_binding:
                query = utg_data.get("query", "")
                # 主路径：从步骤描述提取（确保与 step 内容一致）
                mock_instance = self._extract_mock_from_steps(utg_steps, query)
                # 后备：query 生成（仅步骤提取失败时）
                if not mock_instance and query:
                    mock_instance = self._generate_mock_from_query(query)
                if mock_instance:
                    mock_instances = [mock_instance]
                    new_steps = self.bind_mock_data(new_steps, mock_instances, query)
                    # 同步更新 topics 中的 mockInstances（替换模板预设数据）
                    self._update_merged_mock_instances(merged, mock_instances)
                    # 记录绑定的 mock ID
                    bound_ids = set(
                        s.get("boundMockId") for s in new_steps if s.get("boundMockId")
                    )
                    if bound_ids:
                        result["bound_mock_id"] = list(bound_ids)[0]
                        logger.info(f"  数据绑定: {list(bound_ids)}")
                else:
                    logger.info("  数据绑定: 无 query 或生成失败，跳过")

            # Step 3: 合并到模板
            if mode == "smart":
                # 智能合并：模板为框架，UTG 填充
                merged_steps = self._smart_merge(new_steps, merged["mainFlow"].get("steps", []))
                merged["mainFlow"]["steps"] = merged_steps
            elif mode == "replace":
                merged["mainFlow"]["steps"] = new_steps
            elif mode == "fill":
                template_steps = merged["mainFlow"].get("steps", [])
                for i, ns in enumerate(new_steps):
                    if i < len(template_steps):
                        merged_step = template_steps[i]
                        merged_step["action"] = ns.get("action", merged_step.get("action", ""))
                        if enable_screen_key and "targetPage" in ns:
                            merged_step["targetPage"] = ns["targetPage"]
                    else:
                        template_steps.append(ns)
                merged["mainFlow"]["steps"] = template_steps
            else:
                result["error"] = f"未知的合并模式: {mode}"
                return result

            # 按模板 mainFlow.steps 的字段输出，避免生成模板外字段。
            step_fields = self._get_template_step_fields(template)
            if step_fields:
                merged["mainFlow"]["steps"] = self._filter_step_fields(
                    merged["mainFlow"].get("steps", []),
                    step_fields,
                )
                if "targetPage" not in step_fields:
                    result["screen_keys_assigned"] = None
                if "boundMockId" not in step_fields:
                    result["bound_mock_id"] = None

            self._save_json(merged, output_path)
            step_count = len(merged["mainFlow"]["steps"])
            logger.info(f"输出步骤数: {step_count}")
            logger.info(f"已保存: {output_path}")

            result["success"] = True
            result["step_count"] = step_count
            return result

        except Exception as e:
            logger.exception("转换失败")
            result["error"] = str(e)
            return result

    # ── 辅助方法 ──────────────────────────────────────────

    def _get_valid_steps_from_utg(self, utg_data: Dict) -> List[Dict]:
        """从 utg_info.json 中提取有效步骤"""
        step_data = utg_data.get("stepData", [])
        valid = []
        invalid_ids = {"home", "end", "start"}
        for item in step_data:
            sid = str(item.get("stepId", ""))
            if sid.lower() in invalid_ids:
                continue
            ui_summary = (item.get("ui_summary") or "").strip()
            if not ui_summary:
                continue
            valid.append({
                "order": len(valid) + 1,
                "stepId": sid,
                "ui_summary": ui_summary,
                "thought": item.get("thought", ""),
            })
        return valid

    def _extract_mock_from_steps(self, utg_steps: List[Dict], query: str) -> Optional[Dict]:
        """
        从 UTG stepData 提取 mock 商品实例（主路径）。

        优先从步骤描述中抽取实际商品信息，query 仅作为辅助上下文。
        确保 mock 实例与 mainFlow.steps 中描述的商品一致，避免无中生有。

        Args:
            utg_steps: 有效步骤列表，每项含 ui_summary/thought
            query: 用户搜索查询（辅助上下文）

        Returns:
            包含 instanceId/imageUrl/values 的 mock 实例字典，或 None
        """
        _ALL_VALUES_FIELDS = [
            "brand", "model", "price", "storage", "color", "processor",
            "rating", "salesVolume", "productId", "skuId", "orderId",
            "addressId", "couponId", "subsidyPrice", "subsidyAmount",
            "maxPrice", "promotionTag", "quantity", "deliveryMethod",
            "deliveryTime", "address",
        ]

        # 构建步骤文本摘要（截取避免超 tokens）
        texts = []
        for s in utg_steps:
            summary = (s.get("ui_summary") or "").strip()
            if summary:
                texts.append(f"Step {s['order']}: {summary[:200]}")
        if not texts:
            return None
        steps_text = "\n".join(texts)[:2500]

        try:
            gen_llm = LLMClient(temperature=0.1, max_tokens=1024)
            prompt = EXTRACT_MOCK_PROMPT.format(
                query=(query or "")[:200],
                steps_text=steps_text,
            )
            raw = gen_llm.chat(prompt)
            parsed = gen_llm.extract_json(raw)

            instance = parsed if "instanceId" in parsed else {
                "instanceId": "instance_from_query",
                "imageUrl": None,
                "values": parsed,
            }
            instance.setdefault("imageUrl", None)

            values = instance.get("values", {})
            if not values:
                logger.warning(f"  LLM 返回的 mock 实例缺少 values: {parsed}")
                return None

            cleaned = {}
            for field in _ALL_VALUES_FIELDS:
                cleaned[field] = values.get(field) if field in values else None
            instance["values"] = cleaned

            logger.info(
                f"  从步骤提取 mock 实例: "
                f"{cleaned.get('brand', '')} {cleaned.get('model', '')} "
                f"¥{cleaned.get('price', '')}"
            )
            return instance

        except Exception as e:
            logger.warning(f"  从步骤提取 mock 实例失败: {e}")

        return None

    def _generate_mock_from_query(self, query: str) -> Optional[Dict]:
        """
        从 UTG query 用 LLM 生成 mock 商品实例（后备路径）。

        仅当 _extract_mock_from_steps 失败时使用此后备方法。
        模板中的 mockInstances 仅作 spec 参考，实际数据由 LLM 从查询中提取生成。
        输出的字段结构严格与模板 spec 一致，UTG 未涉及的字段一律置 null。

        Args:
            query: 用户搜索查询（如 "去京东下单一台华为手机"）

        Returns:
            包含 instanceId/imageUrl/values 的 mock 实例字典，或 None
        """
        if not query or not query.strip():
            return None

        # 模板 spec 定义的 21 个 values 字段
        _ALL_VALUES_FIELDS = [
            "brand", "model", "price", "storage", "color", "processor",
            "rating", "salesVolume", "productId", "skuId", "orderId",
            "addressId", "couponId", "subsidyPrice", "subsidyAmount",
            "maxPrice", "promotionTag", "quantity", "deliveryMethod",
            "deliveryTime", "address",
        ]

        try:
            # 使用独立的 LLM 调用（需要更高 max_tokens 生成完整 JSON）
            gen_llm = LLMClient(
                temperature=0.1,
                max_tokens=1024,
            )
            prompt = GENERATE_MOCK_PROMPT.format(query=query[:300])
            raw = gen_llm.chat(prompt)
            parsed = gen_llm.extract_json(raw)

            # 标准化 instanceId 和 imageUrl
            instance = parsed if "instanceId" in parsed else {
                "instanceId": "instance_from_query",
                "imageUrl": None,
                "values": parsed,
            }
            instance.setdefault("imageUrl", None)

            values = instance.get("values", {})
            if not values:
                logger.warning(f"  LLM 返回的 mock 实例缺少 values: {parsed}")
                return None

            # 补全缺失字段为 null，去除多余字段
            cleaned = {}
            for field in _ALL_VALUES_FIELDS:
                cleaned[field] = values.get(field) if field in values else None
            instance["values"] = cleaned

            logger.info(
                f"  LLM 生成 mock 实例(后备): "
                f"{cleaned.get('brand', '')} {cleaned.get('model', '')} "
                f"¥{cleaned.get('price', '')}"
            )
            return instance

        except Exception as e:
            logger.warning(f"  LLM 生成 mock 实例失败: {e}")

        return None

    @staticmethod
    def _update_merged_mock_instances(merged: Dict, new_instances: List[Dict]):
        """
        用 LLM 生成的新 mock 实例替换 merged 中所有模板预设的 mockInstances。

        Args:
            merged: 合并后的输出字典（deepcopy of template）
            new_instances: 新生成的 mock 实例列表
        """
        if not new_instances:
            return

        replaced = 0
        for topic in merged.get("topics", []):
            # topics 层级的 mockInstances
            if "mockInstances" in topic:
                topic["mockInstances"] = new_instances
                replaced += 1
            # fields 层级嵌套的 mockInstances
            for field in topic.get("fields", []):
                if "mockInstances" in field:
                    field["mockInstances"] = new_instances
                    replaced += 1

        if replaced > 0:
            logger.info(f"  topics mockInstances 已替换（{len(new_instances)} 实例, {replaced} 处）")

    def _get_template_step_fields(self, template: Dict) -> List[str]:
        """获取模板步骤字段顺序，用于约束输出字段。"""
        steps = template.get("mainFlow", {}).get("steps", [])
        if not steps:
            return ["order", "action"]

        fields = list(steps[0].keys())
        for required in ("order", "action"):
            if required not in fields:
                fields.append(required)
        return fields

    def _filter_step_fields(self, steps: List[Dict], fields: List[str]) -> List[Dict]:
        """仅保留模板声明的步骤字段。"""
        filtered = []
        for step in steps:
            filtered.append({
                field: step[field]
                for field in fields
                if field in step
            })
        return filtered

    def _smart_merge(self, utg_steps: List[Dict], template_steps: List[Dict]) -> List[Dict]:
        """
        智能合并：
        - 以 UTG 步骤为主体（已由 LLM 分配 targetPage）
        - 对模板中有、但 UTG 缺失的关键步骤，从模板补充
        - 确保 screenKey 拓扑序正确

        注意：模板步骤分析使用 _match_screen_key 作为页面类型推断的
        辅助工具，这仅是参考分析，不构成独立决策路径。
        """
        if not template_steps:
            return utg_steps

        # 分析模板步骤的页面类型（模板无 targetPage 字段，使用关键词辅助判断）
        template_keys = [
            _match_screen_key(s.get("action", "")) for s in template_steps
        ]

        # 提取 UTG 中的 screenKey（已由 LLM 分配）
        utg_keys = [s.get("targetPage", "") for s in utg_steps]

        # 检查缺失的关键页面
        missing = []
        for i, key in enumerate(template_keys):
            if key in ("productDetail", "orderDetail") and key not in utg_keys:
                # 找到插入位置
                insert_after = -1
                for j, uk in enumerate(utg_keys):
                    if uk == self._get_prev_key(key, template_keys, i):
                        insert_after = j
                if insert_after >= 0 and insert_after < len(utg_steps) - 1:
                    missing.append({
                        "key": key,
                        "action": template_steps[i].get("action", ""),
                        "insert_after": insert_after,
                    })

        if missing:
            # 从后往前插入
            missing.sort(key=lambda x: x["insert_after"], reverse=True)
            for m in missing:
                logger.info(f"  补齐: 在 Step {m['insert_after']} 后插入 '{m['key']}'")
                utg_steps.insert(m["insert_after"] + 1, {
                    "order": m["insert_after"] + 2,
                    "action": m["action"],
                    "targetPage": m["key"],
                })
            # 重新编号
            for i, s in enumerate(utg_steps):
                s["order"] = i + 1

        return utg_steps

    @staticmethod
    def _get_prev_key(key: str, keys: List[str], idx: int) -> str:
        """获取 key 在拓扑序中的前一个 key"""
        if idx > 0:
            return keys[idx - 1]
        return "home"

    @staticmethod
    def _load_json(path: str) -> Dict:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def _save_json(data: Dict, path: str):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
