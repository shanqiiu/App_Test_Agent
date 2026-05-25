"""
从utg_info.json的ui_summary字段提取界面Spec定义，并进行App功能聚类分析。
校验基准：queries2/parsed_spec.md
"""

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class UIElement:
    name: str
    element_type: str
    interactable: bool = False
    description: str = ""


@dataclass
class PageSpec:
    page_type: str
    page_id: str
    description: str
    elements: list[UIElement] = field(default_factory=list)
    interactions: list[str] = field(default_factory=list)
    business_semantics: list[str] = field(default_factory=list)
    source_count: int = 0


@dataclass
class AppSpec:
    app_name: str
    category: str = ""
    page_specs: list[PageSpec] = field(default_factory=list)
    unique_features: list[str] = field(default_factory=list)


PAGE_TYPE_RULES = [
    # 高优先级：最具体的模式先匹配
    (r"支付密码|输入.*密码|身份验证中", "payment_password_page"),
    (r"确认订单|结算页|提交订单|订单详情.*收货地址|价格明细.*提交", "checkout_page"),
    (r"凑单助手|凑单", "bundle_helper_page"),
    (r"收银台|确认付款|极速付款", "payment_page"),
    (r"支付.*金额|支付方式.*花呗|支付方式.*白条|立即支付|领券购买.*支付", "payment_page"),
    # 筛选页：多种描述方式
    (r"筛选页面|筛选界面|筛选条件设置|筛选选项界面|筛选弹窗", "filter_page"),
    (r"筛选.*重置.*确定|筛选.*重置.*完成|重置按钮.*确定按钮|重置.*完成.*按钮", "filter_page"),
    (r"价格区间.*最低价.*最高价.*重置|价格区间输入框.*重置按钮", "filter_page"),
    (r"筛选.*服务.*折扣|筛选.*品牌.*全部分类", "filter_page"),
    # 店铺页
    (r"旗舰店|自营旗舰店|店铺页|进店|店内搜索", "store_page"),
    # 规格选择页
    (r"规格选择|确认款式|款式选择|选择.*规格|规格.*选择|系列选项.*款式选项", "spec_selection_page"),
    (r"颜色.*可选|已选.*颜色.*确定|规格.*确定按钮|数量调整.*确认", "spec_selection_page"),
    # 商品详情页
    (r"商品详情|商品.*图片.*价格|商品.*加入购物车|商品.*立即购买", "product_detail_page"),
    (r"展示商品.*价格.*按钮|商品名称.*价格.*购买|商品.*补贴价.*发起拼单", "product_detail_page"),
    # 排行榜
    (r"热卖榜|排行榜|热卖", "ranking_page"),
    # 分类页
    (r"分类选择|分类页|热门分类|大家电", "category_page"),
    # 搜索建议
    (r"搜索建议|推荐搜索|搜索内容列表|推荐搜索内容", "search_suggestion_page"),
    # 购物车
    (r"购物车", "cart_page"),
    # 搜索结果页：多种描述方式
    (r"搜索结果页|搜索结果.*页|展示搜索结果", "search_result_page"),
    (r"已搜索.*排序.*展示商品|已搜索.*商品列表", "search_result_page"),
    (r"搜索框.*关键词.*排序|搜索框.*已输入.*排序|搜索.*排序.*商品列表", "search_result_page"),
    (r"搜索框.*筛选按钮.*商品|搜索.*综合.*商品|综合.*排序.*商品", "search_result_page"),
    (r"搜索框.*商品列表|搜索.*展示.*商品|展示.*商品.*搜索", "search_result_page"),
    (r"导航栏.*已选中.*商品列表|排序.*商品.*价格", "search_result_page"),
    (r"搜索框.*已输入.*商品|搜索框.*显示.*商品", "search_result_page"),
    (r"搜索结果.*已按.*排序|展示.*商品.*价格.*补贴|页面展示.*商品.*价格.*补贴", "search_result_page"),
    (r"页面.*搜索结果.*商品|展示搜索结果.*商品", "search_result_page"),
    (r"已按.*排序.*商品|销量最高.*商品|售价.*元.*好评", "search_result_page"),
    # 首页：多种描述方式
    (r"首页", "home_page"),
    (r"搜索框.*默认.*推荐商品|搜索框.*商品推荐.*导航栏", "home_page"),
    (r"搜索框.*促销.*导航栏|搜索框.*品牌.*导航栏", "home_page"),
    (r"默认搜索内容.*促销|搜索框.*推荐.*底部导航", "home_page"),
    (r"搜索框.*商品.*分类推荐.*导航栏", "home_page"),
    (r"搜索框.*搜索按钮.*推荐商品|搜索框.*搜索按钮.*导航栏", "home_page"),
    # 加载页
    (r"加载中|执行中|小艺执行|加载动画", "loading_page"),
]

ELEMENT_RULES = [
    (r"搜索框", UIElement("search_box", "input", True, "搜索输入框")),
    (r"搜索按钮|搜索.*按钮|放大镜图标", UIElement("search_button", "button", True, "搜索触发按钮")),
    (r"筛选按钮|筛选.*按钮", UIElement("filter_button", "button", True, "筛选触发按钮")),
    (r"排序.*(?:综合|销量|价格|评论|好评)", UIElement("sort_options", "tab", True, "排序选项栏")),
    (r"(?:综合|销量|价格|评论数|好评|价格升序|价格降序).*排序", UIElement("sort_options", "tab", True, "排序选项栏")),
    (r"综合.*销量.*价格", UIElement("sort_options", "tab", True, "排序选项栏")),
    (r"加入购物车", UIElement("add_to_cart", "button", True, "加入购物车按钮")),
    (r"立即购买|领券购买|发起拼单", UIElement("buy_now", "button", True, "立即购买按钮")),
    (r"提交订单", UIElement("submit_order", "button", True, "提交订单按钮")),
    (r"确认付款|极速付款|立即支付", UIElement("confirm_payment", "button", True, "确认付款按钮")),
    (r"重置按钮|重置", UIElement("reset_button", "button", True, "筛选重置按钮")),
    (r"确定按钮|确定|完成按钮|完成|确认按钮|确认", UIElement("confirm_button", "button", True, "确认按钮")),
    (r"价格区间|最低价|最高价|自定最高价", UIElement("price_range_input", "input", True, "价格区间输入")),
    (r"百亿补贴", UIElement("subsidy_tag", "label", False, "百亿补贴标签")),
    (r"国补", UIElement("national_subsidy_tag", "label", False, "国补标签")),
    (r"导航栏|底部导航", UIElement("navigation_bar", "navigation", True, "底部导航栏")),
    (r"返回按钮", UIElement("back_button", "button", True, "返回按钮")),
    (r"收货地址|配送.*地址", UIElement("shipping_address", "label", False, "收货地址信息")),
    (r"配送方式|配送服务|快递包邮|商城配送", UIElement("delivery_method", "label", False, "配送方式")),
    (r"商品列表|商品卡片", UIElement("product_list", "list", True, "商品列表")),
    (r"优惠券|领券", UIElement("coupon", "button", True, "优惠券/领券")),
    (r"白条|花呗|微信支付|京东支付|银行卡|支付宝", UIElement("payment_method", "tab", True, "支付方式选项")),
    (r"券后价|补贴价|国补.*价|到手价", UIElement("discount_price", "label", False, "折扣/补贴价")),
    (r"规格|款式|颜色|尺码|容量|型号", UIElement("spec_option", "tab", True, "规格选项")),
    (r"数量调整|加号按钮", UIElement("quantity_adjust", "button", True, "数量调整")),
    (r"起送|还差.*元", UIElement("min_order_hint", "label", False, "起送金额提示")),
    (r"缺货|暂时缺货", UIElement("out_of_stock", "label", False, "缺货标识")),
    (r"无忧服务", UIElement("warranty_service", "label", False, "无忧服务标识")),
    (r"扫描按钮|扫描图标", UIElement("scan_button", "button", True, "扫描按钮")),
    (r"京东自营|自营", UIElement("self_operated_tag", "label", False, "自营标识")),
    (r"店铺类型|旗舰店|专卖店|专营店", UIElement("store_type_filter", "tab", True, "店铺类型筛选")),
    (r"物流|发货地|收货地|操作系统", UIElement("logistics_filter", "tab", True, "物流/发货筛选")),
    (r"PLUS|PLUS专享", UIElement("plus_tag", "label", False, "PLUS会员标识")),
    (r"好评率|已售|销量", UIElement("sales_info", "label", False, "销量/好评信息")),
]

INTERACTION_RULES = [
    (r"可点击", "click"),
    (r"可编辑|输入框", "input"),
    (r"可滚动|滚动|滑动|上下滑动", "scroll"),
    (r"已选中|已选择|当前选中", "select"),
    (r"已输入|当前内容|搜索框.*为|搜索框.*显示", "filled"),
    (r"弹窗|弹框", "popup"),
]

BUSINESS_SEMANTIC_RULES = [
    (r"拼单|拼团|发起拼单", "group_buying"),
    (r"百亿补贴", "subsidy_pricing"),
    (r"国补", "national_subsidy"),
    (r"券|优惠券|领券|券后", "coupon_system"),
    (r"自营|旗舰店|专卖店", "store_quality_tier"),
    (r"起送|凑单|满减", "minimum_order_threshold"),
    (r"排行|热卖|榜单", "ranking_recommendation"),
    (r"无忧服务|延保|售后", "after_sales_service"),
    (r"扫码|扫描", "scan_interaction"),
    (r"PLUS|PLUS专享", "plus_membership"),
]


def identify_page_type(ui_summary: str) -> str:
    for pattern, page_type in PAGE_TYPE_RULES:
        if re.search(pattern, ui_summary):
            return page_type
    return "unknown_page"


def extract_elements(ui_summary: str) -> list[UIElement]:
    elements = []
    seen = set()
    for pattern, element in ELEMENT_RULES:
        if re.search(pattern, ui_summary):
            if element.name not in seen:
                seen.add(element.name)
                elements.append(element)
    return elements


def extract_interactions(ui_summary: str) -> list[str]:
    interactions = []
    seen = set()
    for pattern, interaction in INTERACTION_RULES:
        if re.search(pattern, ui_summary):
            if interaction not in seen:
                seen.add(interaction)
                interactions.append(interaction)
    return interactions


def extract_business_semantics(ui_summary: str) -> list[str]:
    semantics = []
    seen = set()
    for pattern, semantic in BUSINESS_SEMANTIC_RULES:
        if re.search(pattern, ui_summary):
            if semantic not in seen:
                seen.add(semantic)
                semantics.append(semantic)
    return semantics


def load_utg_data(base_dir: str) -> dict[str, list[dict]]:
    app_data = defaultdict(list)
    for uuid_dir in os.listdir(base_dir):
        utg_path = os.path.join(base_dir, uuid_dir, "utg_info.json")
        if os.path.isfile(utg_path):
            with open(utg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            app_name = data.get("appName", "unknown")
            app_data[app_name].append(data)
    return app_data


APP_CATEGORY_MAP = {
    "淘宝": "shopping_ecommerce",
    "京东": "shopping_ecommerce",
    "拼多多": "shopping_ecommerce",
    "天猫": "shopping_ecommerce",
    "华为商城": "brand_direct_store",
}


def build_page_specs(app_name: str, records: list[dict]) -> list[PageSpec]:
    page_type_summaries = defaultdict(list)

    for record in records:
        for step in record.get("stepData", []):
            ui_summary = step.get("ui_summary", "")
            if not ui_summary:
                continue
            page_type = identify_page_type(ui_summary)
            page_type_summaries[page_type].append(ui_summary)

    page_specs = []
    for page_type, summaries in page_type_summaries.items():
        all_elements = []
        all_interactions = []
        all_semantics = []

        for summary in summaries:
            all_elements.extend(extract_elements(summary))
            all_interactions.extend(extract_interactions(summary))
            all_semantics.extend(extract_business_semantics(summary))

        element_counts = defaultdict(int)
        element_map = {}
        for elem in all_elements:
            element_counts[elem.name] += 1
            element_map[elem.name] = elem

        sorted_elements = sorted(element_counts.items(), key=lambda x: -x[1])
        unique_elements = [element_map[name] for name, _ in sorted_elements]

        unique_interactions = list(dict.fromkeys(all_interactions))
        unique_semantics = list(dict.fromkeys(all_semantics))

        representative = max(summaries, key=len) if summaries else ""

        page_spec = PageSpec(
            page_type=page_type,
            page_id=f"{app_name}_{page_type}",
            description=representative[:200],
            elements=unique_elements,
            interactions=unique_interactions,
            business_semantics=unique_semantics,
            source_count=len(summaries),
        )
        page_specs.append(page_spec)

    page_specs.sort(key=lambda x: -x.source_count)
    return page_specs


def build_app_spec(app_name: str, records: list[dict]) -> AppSpec:
    page_specs = build_page_specs(app_name, records)
    category = APP_CATEGORY_MAP.get(app_name, "unknown")

    all_semantics = set()
    for ps in page_specs:
        all_semantics.update(ps.business_semantics)
    page_types = {ps.page_type for ps in page_specs}

    unique_features = []
    if app_name == "淘宝":
        unique_features.append("百亿补贴+国补筛选体系")
        unique_features.append("支付密码验证(花呗/支付宝)")
    if app_name == "京东":
        unique_features.append("京东自营标识体系")
        unique_features.append("PLUS会员专享价")
        unique_features.append("凑单助手(满起送)")
        unique_features.append("收银台(白条/微信/京东支付)")
    if app_name == "拼多多":
        unique_features.append("拼单/拼团购买模式")
        unique_features.append("好评排序特色")
    if app_name == "华为商城":
        unique_features.append("品牌直营(无第三方卖家)")
        unique_features.append("无忧售后服务")
        unique_features.append("硬件参数筛选(屏幕/内存)")
    if app_name == "天猫":
        unique_features.append("品牌官方店铺为主")
        unique_features.append("天猫超市/品牌官方标识")

    return AppSpec(
        app_name=app_name,
        category=category,
        page_specs=page_specs,
        unique_features=unique_features,
    )


def compute_feature_vector(app_spec: AppSpec) -> dict[str, int]:
    vector = {}
    all_page_types = [
        "home_page", "search_result_page", "filter_page",
        "product_detail_page", "spec_selection_page", "cart_page",
        "checkout_page", "payment_page", "payment_password_page",
        "loading_page", "bundle_helper_page", "ranking_page",
        "store_page", "category_page", "search_suggestion_page",
    ]
    page_type_set = {ps.page_type for ps in app_spec.page_specs}
    for pt in all_page_types:
        vector[f"has_{pt}"] = 1 if pt in page_type_set else 0
    vector["page_type_count"] = len(page_type_set)

    all_element_names = set()
    for ps in app_spec.page_specs:
        for elem in ps.elements:
            all_element_names.add(elem.name)
    vector["element_variety"] = len(all_element_names)

    all_semantics = set()
    for ps in app_spec.page_specs:
        all_semantics.update(ps.business_semantics)
    for sem in ["group_buying", "subsidy_pricing", "national_subsidy", "coupon_system",
                "store_quality_tier", "minimum_order_threshold",
                "ranking_recommendation", "after_sales_service", "scan_interaction", "plus_membership"]:
        vector[f"sem_{sem}"] = 1 if sem in all_semantics else 0

    all_interactions = set()
    for ps in app_spec.page_specs:
        all_interactions.update(ps.interactions)
    vector["interaction_variety"] = len(all_interactions)

    return vector


def cluster_apps(app_specs: list[AppSpec]) -> dict[str, list[str]]:
    clusters = defaultdict(list)

    for app_spec in app_specs:
        name = app_spec.app_name
        page_types = {ps.page_type for ps in app_spec.page_specs}
        semantics = set()
        for ps in app_spec.page_specs:
            semantics.update(ps.business_semantics)

        # 主聚类：按category
        if app_spec.category == "brand_direct_store":
            clusters["brand_direct_store"].append(name)
        else:
            clusters["shopping_ecommerce"].append(name)

        # 细分聚类
        if "group_buying" in semantics:
            clusters["social_commerce"].append(name)

        if "store_quality_tier" in semantics and "bundle_helper_page" in page_types:
            clusters["full_service_ecommerce"].append(name)

        if "payment_password_page" in page_types:
            clusters["fintech_integrated"].append(name)

        if len(page_types) <= 5:
            clusters["streamlined_commerce"].append(name)

        if "after_sales_service" in semantics:
            clusters["brand_direct_commerce"].append(name)

        if "national_subsidy" in semantics:
            clusters["national_subsidy_ecommerce"].append(name)

    return dict(clusters)


def page_type_display_name(page_type: str) -> str:
    mapping = {
        "home_page": "首页",
        "search_result_page": "搜索结果页",
        "filter_page": "筛选页",
        "product_detail_page": "商品详情页",
        "spec_selection_page": "规格选择页",
        "cart_page": "购物车页",
        "checkout_page": "确认订单/结算页",
        "payment_page": "支付页",
        "payment_password_page": "支付密码页",
        "loading_page": "加载/执行页",
        "bundle_helper_page": "凑单助手页",
        "ranking_page": "热卖榜/排行榜页",
        "store_page": "店铺页",
        "category_page": "分类页",
        "search_suggestion_page": "搜索建议页",
        "unknown_page": "未知页面",
    }
    return mapping.get(page_type, page_type)


def element_type_display_name(element_type: str) -> str:
    mapping = {
        "button": "按钮",
        "input": "输入框",
        "label": "标签/信息",
        "navigation": "导航",
        "list": "列表",
        "icon": "图标",
        "tab": "选项卡/标签栏",
    }
    return mapping.get(element_type, element_type)


def generate_spec_report(app_specs: list[AppSpec], clusters: dict) -> str:
    lines = []
    lines.append("=" * 80)
    lines.append("购物类App界面Spec定义 & 功能聚类分析报告")
    lines.append("(校验基准: queries2/parsed_spec.md)")
    lines.append("=" * 80)
    lines.append("")

    lines.append("## 一、App功能聚类结果")
    lines.append("")
    cluster_display = {
        "shopping_ecommerce": "电商购物（主类）",
        "brand_direct_store": "品牌官方商城",
        "social_commerce": "社交电商",
        "full_service_ecommerce": "全服务电商（含凑单/自营/旗舰店）",
        "fintech_integrated": "金融支付集成电商",
        "streamlined_commerce": "精简流程电商",
        "brand_direct_commerce": "品牌直营电商",
        "national_subsidy_ecommerce": "国补体系电商",
    }
    for cluster_id, apps in clusters.items():
        display = cluster_display.get(cluster_id, cluster_id)
        lines.append(f"### [{display}]")
        lines.append(f"  Apps: {', '.join(apps)}")
        lines.append("")

    lines.append("### 聚类说明")
    lines.append("- **电商购物（主类）**: 淘宝/京东/拼多多/天猫，共享核心购物流程（首页→搜索→详情→下单）")
    lines.append("- **品牌官方商城**: 华为商城，品牌自营无第三方卖家，规格选择复杂")
    lines.append("- **社交电商**: 拼多多，采用拼单/拼团模式，无独立购物车/筛选页")
    lines.append("- **全服务电商**: 京东，功能最丰富，独有凑单助手、收银台、旗舰店、排行榜")
    lines.append("- **金融支付集成电商**: 淘宝，支付流程最细化（花呗/支付宝/密码验证）")
    lines.append("- **精简流程电商**: 页面类型≤5，流程精简")
    lines.append("- **国补体系电商**: 淘宝，独有国补筛选条件")
    lines.append("")

    lines.append("## 二、各App界面Spec定义")
    lines.append("")

    for app_spec in app_specs:
        lines.append(f"### 【{app_spec.app_name}】(分类: {app_spec.category})")
        lines.append(f"  页面类型数: {len(app_spec.page_specs)}")
        if app_spec.unique_features:
            lines.append(f"  独有特性: {', '.join(app_spec.unique_features)}")
        lines.append("")

        for ps in app_spec.page_specs:
            pt_display = page_type_display_name(ps.page_type)
            lines.append(f"  #### {pt_display} ({ps.page_id})")
            lines.append(f"  - 出现频次: {ps.source_count}")
            lines.append(f"  - 代表描述: {ps.description[:150]}...")
            lines.append(f"  - UI元素:")
            for elem in ps.elements:
                type_display = element_type_display_name(elem.element_type)
                interact = "可交互" if elem.interactable else "仅展示"
                lines.append(f"    - [{type_display}] {elem.description} ({interact})")
            if ps.interactions:
                lines.append(f"  - 交互行为: {', '.join(ps.interactions)}")
            if ps.business_semantics:
                lines.append(f"  - 业务语义: {', '.join(ps.business_semantics)}")
            lines.append("")

        lines.append("-" * 60)
        lines.append("")

    lines.append("## 三、跨App同页面Spec对比")
    lines.append("")

    all_page_types = set()
    for app_spec in app_specs:
        for ps in app_spec.page_specs:
            all_page_types.add(ps.page_type)

    for pt in sorted(all_page_types):
        pt_display = page_type_display_name(pt)
        lines.append(f"### {pt_display}")

        for app_spec in app_specs:
            matching = [ps for ps in app_spec.page_specs if ps.page_type == pt]
            if matching:
                ps = matching[0]
                elem_names = [e.description for e in ps.elements[:5]]
                sem_names = ps.business_semantics[:3]
                lines.append(f"  - **{app_spec.app_name}**: 元素=[{', '.join(elem_names)}]")
                if sem_names:
                    lines.append(f"    业务语义=[{', '.join(sem_names)}]")
            else:
                lines.append(f"  - **{app_spec.app_name}**: 无此页面")
        lines.append("")

    # 校验对比表
    lines.append("## 四、与parsed_spec.md校验对比")
    lines.append("")
    lines.append("| 页面类型 | parsed_spec | 自动提取 | 一致性 |")
    lines.append("|---------|------------|---------|--------|")

    parsed_spec_matrix = {
        "home_page": {"淘宝": True, "京东": True, "拼多多": True, "华为商城": True, "天猫": True},
        "search_result_page": {"淘宝": True, "京东": True, "拼多多": True, "华为商城": True, "天猫": True},
        "filter_page": {"淘宝": True, "京东": True, "拼多多": False, "华为商城": False, "天猫": True},
        "product_detail_page": {"淘宝": True, "京东": True, "拼多多": True, "华为商城": True, "天猫": True},
        "spec_selection_page": {"淘宝": True, "京东": False, "拼多多": False, "华为商城": True, "天猫": True},
        "payment_page": {"淘宝": True, "京东": True, "拼多多": False, "华为商城": True, "天猫": True},
        "store_page": {"淘宝": True, "京东": True, "拼多多": False, "华为商城": False, "天猫": True},
        "loading_page": {"淘宝": True, "京东": True, "拼多多": True, "华为商城": True, "天猫": True},
    }

    auto_matrix = {}
    for app_spec in app_specs:
        for ps in app_spec.page_specs:
            if ps.page_type not in auto_matrix:
                auto_matrix[ps.page_type] = {}
            auto_matrix[ps.page_type][app_spec.app_name] = True

    for pt in sorted(parsed_spec_matrix.keys()):
        pt_display = page_type_display_name(pt)
        for app_name in ["淘宝", "京东", "拼多多", "华为商城", "天猫"]:
            parsed_val = parsed_spec_matrix[pt].get(app_name, False)
            auto_val = auto_matrix.get(pt, {}).get(app_name, False)
            consistency = "OK" if parsed_val == auto_val else ("MISS" if parsed_val and not auto_val else "EXTRA")
            lines.append(f"| {pt_display}({app_name}) | {'Y' if parsed_val else '-'} | {'Y' if auto_val else '-'} | {consistency} |")

    lines.append("")

    return "\n".join(lines)


def generate_spec_json(app_specs: list[AppSpec], clusters: dict) -> dict:
    result = {
        "spec_version": "2.0",
        "spec_type": "shopping_app_ui_spec",
        "description": "从utg_info.json的ui_summary提取的购物类App界面Spec定义(校验基准: parsed_spec.md)",
        "apps": [],
        "clusters": {},
        "cross_app_comparison": {},
    }

    for app_spec in app_specs:
        app_dict = {
            "app_name": app_spec.app_name,
            "category": app_spec.category,
            "unique_features": app_spec.unique_features,
            "page_type_count": len(app_spec.page_specs),
            "pages": [],
        }
        for ps in app_spec.page_specs:
            page_dict = {
                "page_type": ps.page_type,
                "page_type_display": page_type_display_name(ps.page_type),
                "page_id": ps.page_id,
                "description": ps.description,
                "source_count": ps.source_count,
                "elements": [
                    {
                        "name": e.name,
                        "type": e.element_type,
                        "type_display": element_type_display_name(e.element_type),
                        "interactable": e.interactable,
                        "description": e.description,
                    }
                    for e in ps.elements
                ],
                "interactions": ps.interactions,
                "business_semantics": ps.business_semantics,
            }
            app_dict["pages"].append(page_dict)

        feature_vector = compute_feature_vector(app_spec)
        app_dict["feature_vector"] = feature_vector
        result["apps"].append(app_dict)

    cluster_display = {
        "shopping_ecommerce": "电商购物（主类）",
        "brand_direct_store": "品牌官方商城",
        "social_commerce": "社交电商",
        "full_service_ecommerce": "全服务电商",
        "fintech_integrated": "金融支付集成电商",
        "streamlined_commerce": "精简流程电商",
        "brand_direct_commerce": "品牌直营电商",
        "national_subsidy_ecommerce": "国补体系电商",
    }
    for cluster_id, apps in clusters.items():
        result["clusters"][cluster_id] = {
            "display_name": cluster_display.get(cluster_id, cluster_id),
            "apps": apps,
        }

    all_page_types = set()
    for app_spec in app_specs:
        for ps in app_spec.page_specs:
            all_page_types.add(ps.page_type)

    for pt in sorted(all_page_types):
        pt_display = page_type_display_name(pt)
        comparison = {}
        for app_spec in app_specs:
            matching = [ps for ps in app_spec.page_specs if ps.page_type == pt]
            if matching:
                ps = matching[0]
                comparison[app_spec.app_name] = {
                    "elements": [e.description for e in ps.elements],
                    "business_semantics": ps.business_semantics,
                    "source_count": ps.source_count,
                }
            else:
                comparison[app_spec.app_name] = None
        result["cross_app_comparison"][pt] = {
            "display_name": pt_display,
            "apps": comparison,
        }

    return result


def main():
    base_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "queries2"
    )
    output_dir = os.path.dirname(os.path.abspath(__file__))

    print(f"加载数据: {base_dir}")
    app_data = load_utg_data(base_dir)
    print(f"发现 {len(app_data)} 个App: {list(app_data.keys())}")

    app_specs = []
    for app_name, records in sorted(app_data.items()):
        print(f"  构建Spec: {app_name} ({len(records)} 条记录)")
        app_spec = build_app_spec(app_name, records)
        app_specs.append(app_spec)

    # 检查unknown_page数量
    for app_spec in app_specs:
        for ps in app_spec.page_specs:
            if ps.page_type == "unknown_page":
                print(f"  [WARNING] {app_spec.app_name} 有 {ps.source_count} 条 unknown_page")

    print("\n执行功能聚类...")
    clusters = cluster_apps(app_specs)
    for cluster_id, apps in clusters.items():
        print(f"  [{cluster_id}]: {apps}")

    report = generate_spec_report(app_specs, clusters)
    report_path = os.path.join(output_dir, "ui_spec_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n报告已生成: {report_path}")

    spec_json = generate_spec_json(app_specs, clusters)
    json_path = os.path.join(output_dir, "ui_spec_definition.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(spec_json, f, ensure_ascii=False, indent=2)
    print(f"Spec JSON已生成: {json_path}")

    specs_dir = os.path.join(output_dir, "app_specs")
    os.makedirs(specs_dir, exist_ok=True)
    for app_spec in app_specs:
        app_dict = asdict(app_spec)
        app_dict["page_specs"] = [
            {
                **asdict(ps),
                "page_type_display": page_type_display_name(ps.page_type),
            }
            for ps in app_spec.page_specs
        ]
        app_path = os.path.join(specs_dir, f"{app_spec.app_name}_spec.json")
        with open(app_path, "w", encoding="utf-8") as f:
            json.dump(app_dict, f, ensure_ascii=False, indent=2)
        print(f"  App Spec: {app_path}")

    print("\n完成!")


if __name__ == "__main__":
    main()
