"""
topic_data_extractor.py — 从 UTG 抽取 topics.fields 和 mockInstances

默认使用模板中的 events[].relatedData 与 UTG 文本内容做保守抽取；
可选启用 LLM，用于补充字段、实例值和质量验证。
"""

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

from .llm_client import LLMClient


LLM_EXTRACT_PROMPT = """你是 App 业务建模数据抽取专家。请从 UTG 操作轨迹中抽取 topics.fields 和一个 mockInstance。

## 模板已有字段
{existing_fields}

## 模板事件相关数据 relatedData
{related_data}

## UTG 文本
{utg_text}

## 要求
1. fields 只抽业务建模字段，不要抽 stepId、imageId、控件坐标、action_type 等轨迹或控件元数据。
2. values 必须只包含能从 UTG 明确观察或能由业务 ID 规则稳定生成的值。
3. 对商品、SKU、订单、地址、优惠券等业务对象，保留 productId、skuId、orderId、addressId、couponId。
4. 如果发现价格、补贴价、价格上限、促销标签、数量、配送方式、配送时间、地址等业务字段，也要抽取。
5. 字段 id 使用英文 camelCase；字段 type 只能是 string、number、boolean、array、enum、date、price。

只输出 JSON：
{{
  "fields": [
    {{"id": "字段ID", "name": "中文名", "type": "string|number|boolean|array|enum|date|price", "reason": "为什么需要该字段"}}
  ],
  "values": {{
    "字段ID": "字段值"
  }},
  "businessIdFields": ["productId", "skuId"],
  "warnings": ["不确定或冲突的信息"]
}}"""


LLM_VALIDATE_PROMPT = """你是 App 业务建模质量验证专家。请验证从 UTG 抽取出的 fields 和 mockInstance 是否合理。

## UTG 文本
{utg_text}

## 模板事件 relatedData
{related_data}

## 抽取结果
{extracted}

## 验证要求
1. fields 是否覆盖 mockInstance.values 中的业务字段。
2. mockInstance.values 是否与 UTG 中商品、价格、补贴、订单、配送等信息一致。
3. 业务 ID 字段是否来自事件 relatedData 或合理业务对象，不应来自 stepId、imageId、控件坐标。
4. 是否存在明显缺失字段、错误字段、错误值。

只输出 JSON：
{{
  "passed": true,
  "score": 0.0,
  "issues": ["问题"],
  "suggestions": ["建议"]
}}"""


FIELD_CATALOG: Dict[str, Dict[str, Any]] = {
    "brand": {"id": "brand", "name": "品牌", "type": "string", "filterable": True, "displayInCard": True},
    "price": {"id": "price", "name": "价格", "type": "price", "filterable": True, "sortable": True, "displayInCard": True, "unit": "元"},
    "model": {"id": "model", "name": "型号", "type": "string", "displayInDetail": True},
    "storage": {"id": "storage", "name": "存储容量", "type": "enum", "filterable": True, "displayInDetail": True},
    "color": {"id": "color", "name": "颜色", "type": "enum", "filterable": True, "displayInCard": True},
    "processor": {"id": "processor", "name": "处理器", "type": "string", "displayInDetail": True},
    "rating": {"id": "rating", "name": "评分", "type": "number", "sortable": True, "displayInCard": True},
    "salesVolume": {"id": "salesVolume", "name": "销量", "type": "number", "sortable": True, "displayInCard": True},
    "productId": {"id": "productId", "name": "商品ID", "type": "string", "required": True},
    "skuId": {"id": "skuId", "name": "SKU ID", "type": "string", "required": True},
    "orderId": {"id": "orderId", "name": "订单ID", "type": "string"},
    "addressId": {"id": "addressId", "name": "收货地址ID", "type": "string"},
    "couponId": {"id": "couponId", "name": "优惠券ID", "type": "string"},
    "subsidyPrice": {"id": "subsidyPrice", "name": "补贴后价格", "type": "price", "displayInDetail": True, "unit": "元"},
    "subsidyAmount": {"id": "subsidyAmount", "name": "补贴金额", "type": "price", "displayInDetail": True, "unit": "元"},
    "maxPrice": {"id": "maxPrice", "name": "价格上限", "type": "price", "filterable": True, "unit": "元"},
    "promotionTag": {"id": "promotionTag", "name": "促销标签", "type": "string", "filterable": True, "displayInCard": True},
    "quantity": {"id": "quantity", "name": "购买数量", "type": "number", "displayInDetail": True},
    "deliveryMethod": {"id": "deliveryMethod", "name": "配送方式", "type": "string", "displayInDetail": True},
    "deliveryTime": {"id": "deliveryTime", "name": "配送时间", "type": "string", "displayInDetail": True},
    "address": {"id": "address", "name": "收货地址", "type": "string", "displayInDetail": True},
}


class UTGTopicDataExtractor:
    """从 UTG 和模板中抽取业务字段与 mock 实例。"""

    def __init__(
        self,
        use_llm: bool = False,
        validate_with_llm: bool = False,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.use_llm = use_llm
        self.validate_with_llm = validate_with_llm
        self.llm = None
        if use_llm or validate_with_llm:
            self.llm = LLMClient(
                api_key=api_key,
                api_url=api_url,
                model=model,
                temperature=0.0,
                max_tokens=2048,
            )

    def extract(self, utg_path: str, template_path: str) -> Dict[str, Any]:
        utg = self._load_json(utg_path)
        template = self._load_json(template_path)
        text = self._collect_utg_text(utg)

        values = self._extract_values(text, utg)
        id_fields = self._extract_business_id_fields(template)
        for field_id in id_fields:
            values.setdefault(field_id, self._make_id_value(field_id, values, utg))

        llm_warnings: List[str] = []
        if self.use_llm and self.llm:
            llm_result = self._extract_with_llm(text, template)
            values = self._merge_llm_values(values, llm_result.get("values", {}), utg)
            for field_id in llm_result.get("businessIdFields", []):
                if field_id.endswith("Id") and field_id not in id_fields:
                    id_fields.append(field_id)
                    values.setdefault(field_id, self._make_id_value(field_id, values, utg))
            llm_warnings = llm_result.get("warnings", [])

        field_ids = self._field_ids_for_values(values)
        fields = [self._field_definition(fid, values.get(fid)) for fid in field_ids]
        if self.use_llm and self.llm:
            fields = self._merge_llm_fields(fields, llm_result.get("fields", []), values)
        instance = self._build_mock_instance(values)

        validation = self._validate_extraction(fields, instance, id_fields, text, template)

        return {
            "fields": fields,
            "mockInstances": [instance],
            "businessIdFields": id_fields,
            "values": values,
            "validation": validation,
            "warnings": llm_warnings,
        }

    def update_template(self, utg_path: str, template_path: str, output_path: str) -> Dict[str, Any]:
        template = self._load_json(template_path)
        extracted = self.extract(utg_path, template_path)

        topics = template.setdefault("topics", [])
        if not topics:
            topics.append({"id": "default", "name": "默认主题", "fields": [], "mockInstances": []})

        topic = topics[0]
        existing_fields = {f.get("id"): f for f in topic.setdefault("fields", [])}
        added_fields = []
        for field in extracted["fields"]:
            fid = field["id"]
            if fid not in existing_fields:
                topic["fields"].append(field)
                existing_fields[fid] = field
                added_fields.append(fid)

        instances = topic.setdefault("mockInstances", [])
        instance = extracted["mockInstances"][0]
        matched = self._find_matching_instance(instances, instance["values"])
        if matched:
            matched.setdefault("values", {}).update(instance["values"])
            updated_instance_id = matched.get("instanceId")
        else:
            instances.append(instance)
            updated_instance_id = instance["instanceId"]

        self._ensure_instance_values(topic)

        self._save_json(template, output_path)
        return {
            "output_path": output_path,
            "added_fields": added_fields,
            "updated_instance_id": updated_instance_id,
            "business_id_fields": extracted["businessIdFields"],
            "values": extracted["values"],
            "validation": extracted["validation"],
            "warnings": extracted["warnings"],
        }

    def _extract_with_llm(self, text: str, template: Dict[str, Any]) -> Dict[str, Any]:
        existing_fields = []
        for topic in template.get("topics", []):
            existing_fields.extend([f.get("id") for f in topic.get("fields", []) if f.get("id")])
        related_data = self._related_data(template)
        prompt = LLM_EXTRACT_PROMPT.format(
            existing_fields=json.dumps(existing_fields, ensure_ascii=False),
            related_data=json.dumps(related_data, ensure_ascii=False),
            utg_text=text[:8000],
        )
        try:
            return self.llm.extract_json(self.llm.chat(prompt))
        except Exception as e:
            return {"fields": [], "values": {}, "businessIdFields": [], "warnings": [f"LLM 抽取失败: {e}"]}

    def _extract_values(self, text: str, utg: Dict[str, Any]) -> Dict[str, Any]:
        values: Dict[str, Any] = {}

        if "华为" in text:
            values["brand"] = "华为"
        elif re.search(r"iPhone|Apple|苹果", text, re.IGNORECASE):
            values["brand"] = "Apple"
        elif "小米" in text:
            values["brand"] = "小米"
        elif "三星" in text:
            values["brand"] = "三星"

        model = self._first_match(text, [
            r"华为\s*(畅享\d+X?)",
            r"(畅享\d+X?)",
            r"(iPhone\s*\d+\s*(?:Pro|Pro Max)?)",
            r"(Pura\s*\d+\s*Pro)",
        ])
        if model:
            values["model"] = model.replace(" ", "")

        storage = self._first_match(text, [r"(\d+\s*GB)", r"(\d+\s*TB)"])
        if storage:
            values["storage"] = storage.replace(" ", "")

        color = self._first_match(text, [r"(雪域白)", r"(沙漠钛金属)", r"(白色钛金属)", r"(黑色钛金属)", r"(钛灰)", r"(岩石青)"])
        if color:
            values["color"] = color

        max_price = self._first_number(text, [r"价格上限\s*(\d+(?:\.\d+)?)\s*元", r"(\d+(?:\.\d+)?)\s*以内"])
        if max_price is not None:
            values["maxPrice"] = max_price

        subsidy_price = self._first_number(text, [r"国补后价\s*(\d+(?:\.\d+)?)\s*元"])
        if subsidy_price is not None:
            values["subsidyPrice"] = subsidy_price

        subsidy_amount = self._first_number(text, [r"已补贴\s*(\d+(?:\.\d+)?)\s*元"])
        if subsidy_amount is not None:
            values["subsidyAmount"] = subsidy_amount

        submit_price = self._first_number(text, [r"提交订单\s*(\d+(?:\.\d+)?)\s*元"])
        list_price = self._first_number(text, [r"售价\s*(\d+(?:\.\d+)?)\s*元", r"补贴价\s*(\d+(?:\.\d+)?)\s*元"])
        if submit_price is not None:
            values["price"] = submit_price
        elif list_price is not None:
            values["price"] = list_price

        if "百亿补贴" in text:
            values["promotionTag"] = "百亿补贴"
        elif "国家补贴" in text:
            values["promotionTag"] = "国家补贴"

        quantity = self._first_number(text, [r"数量\s*(\d+)\s*件", r"已选数量\s*(\d+)\s*件"])
        if quantity is not None:
            values["quantity"] = int(quantity)

        delivery_method = self._first_match(text, [r"配送方式为([^，。；]+)"])
        if delivery_method:
            values["deliveryMethod"] = delivery_method

        delivery_time = self._first_match(text, [r"送货上门时间([^；，。]+)"])
        if delivery_time:
            values["deliveryTime"] = delivery_time

        if "默认地址" in text:
            values["address"] = "默认地址"

        values.setdefault("processor", "")
        values.setdefault("rating", 4.7)
        values.setdefault("salesVolume", 28000)
        return values

    def _extract_business_id_fields(self, template: Dict[str, Any]) -> List[str]:
        ids = []
        for field_id in self._related_data(template):
            if field_id.endswith("Id") and field_id not in ids:
                ids.append(field_id)
        return ids

    def _related_data(self, template: Dict[str, Any]) -> List[str]:
        related = []
        for event in template.get("events", []):
            related.extend(event.get("relatedData", []))
        return list(dict.fromkeys(related))

    def _field_ids_for_values(self, values: Dict[str, Any]) -> List[str]:
        preferred_order = [
            "brand", "price", "model", "storage", "color", "processor", "rating", "salesVolume",
            "productId", "skuId", "orderId", "addressId", "couponId",
            "subsidyPrice", "subsidyAmount", "maxPrice", "promotionTag",
            "quantity", "deliveryMethod", "deliveryTime", "address",
        ]
        ordered = [fid for fid in preferred_order if fid in values]
        ordered.extend(fid for fid in values if fid not in ordered)
        return ordered

    def _field_definition(self, field_id: str, example: Any = None) -> Dict[str, Any]:
        field = deepcopy(FIELD_CATALOG.get(field_id, {"id": field_id, "name": field_id, "type": "string"}))
        if example not in (None, ""):
            field["example"] = example
        return field

    def _merge_llm_fields(self, fields: List[Dict[str, Any]], llm_fields: List[Dict[str, Any]], values: Dict[str, Any]) -> List[Dict[str, Any]]:
        by_id = {f["id"]: f for f in fields if f.get("id")}
        for field in llm_fields:
            fid = field.get("id")
            if not fid or self._is_forbidden_field(fid):
                continue
            if fid not in values:
                continue
            if fid in by_id:
                continue
            merged = {
                "id": fid,
                "name": field.get("name", fid),
                "type": field.get("type", self._infer_type(values.get(fid))),
            }
            if values.get(fid) not in (None, ""):
                merged["example"] = values[fid]
            fields.append(merged)
            by_id[fid] = merged
        return fields

    def _merge_llm_values(self, rule_values: Dict[str, Any], llm_values: Dict[str, Any], utg: Dict[str, Any]) -> Dict[str, Any]:
        values = dict(rule_values)
        for field_id, value in llm_values.items():
            if self._is_forbidden_field(field_id):
                continue
            if value in (None, ""):
                continue
            if field_id.endswith("Id"):
                values.setdefault(field_id, str(value))
            else:
                values.setdefault(field_id, value)
        for field_id in [fid for fid in values if fid.endswith("Id")]:
            values[field_id] = values.get(field_id) or self._make_id_value(field_id, values, utg)
        return values

    def _build_mock_instance(self, values: Dict[str, Any]) -> Dict[str, Any]:
        brand_slug = self._slug(values.get("brand", "product"))
        model_slug = self._slug(values.get("model", "item"))
        storage_slug = self._slug(values.get("storage", ""))
        color_slug = self._slug(values.get("color", ""))
        parts = [p for p in [brand_slug, model_slug, storage_slug, color_slug] if p]
        instance_id = "digital-utg-" + "-".join(parts)
        image_name = "-".join(parts) or "product"
        return {
            "instanceId": instance_id,
            "imageUrl": f"mock-data/digital/{image_name}.png",
            "values": values,
        }

    def _make_id_value(self, field_id: str, values: Dict[str, Any], utg: Dict[str, Any]) -> str:
        uuid = str(utg.get("uuid", "utg"))[:8]
        brand = self._slug(values.get("brand", "product"))
        model = self._slug(values.get("model", "item"))
        storage = self._slug(values.get("storage", ""))
        color = self._slug(values.get("color", ""))
        suffix = "-".join([p for p in [brand, model, storage, color] if p])

        if field_id == "productId":
            return f"product-{suffix or uuid}"
        if field_id == "skuId":
            return f"sku-{suffix or uuid}"
        if field_id == "orderId":
            return f"order-utg-{uuid}"
        if field_id == "addressId":
            return "address-default-001"
        if field_id == "couponId":
            return "coupon-none"
        return f"{field_id}-{uuid}"

    def _find_matching_instance(self, instances: List[Dict[str, Any]], values: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        brand = values.get("brand")
        model = values.get("model")
        for inst in instances:
            inst_values = inst.get("values", {})
            if brand and model and inst_values.get("brand") == brand and inst_values.get("model") == model:
                return inst
        for inst in instances:
            if brand and inst.get("values", {}).get("brand") == brand:
                return inst
        return None

    def _ensure_instance_values(self, topic: Dict[str, Any]):
        """确保每个 mockInstance.values 都覆盖 fields 中声明的字段。"""
        field_ids = [f.get("id") for f in topic.get("fields", []) if f.get("id")]
        for index, inst in enumerate(topic.get("mockInstances", []), start=1):
            values = inst.setdefault("values", {})
            for field_id in field_ids:
                if field_id in values:
                    continue
                values[field_id] = self._default_instance_value(field_id, values, index)

    def _default_instance_value(self, field_id: str, values: Dict[str, Any], index: int) -> Any:
        if field_id in {"productId", "skuId", "orderId", "addressId", "couponId"}:
            return self._make_id_value(field_id, values, {"uuid": f"{index:08d}"})
        return None

    def _validate_extraction(
        self,
        fields: List[Dict[str, Any]],
        instance: Dict[str, Any],
        business_id_fields: List[str],
        text: str,
        template: Dict[str, Any],
    ) -> Dict[str, Any]:
        field_ids = [f.get("id") for f in fields if f.get("id")]
        values = instance.get("values", {})
        issues = []

        missing_defs = sorted(set(values) - set(field_ids))
        if missing_defs:
            issues.append(f"mockInstance.values 缺少字段定义: {missing_defs}")

        forbidden = sorted(fid for fid in field_ids if self._is_forbidden_field(fid))
        if forbidden:
            issues.append(f"包含轨迹/控件元数据字段: {forbidden}")

        for field_id in business_id_fields:
            if field_id not in values:
                issues.append(f"缺少业务 ID 值: {field_id}")

        if values.get("brand") and str(values["brand"]) not in text:
            issues.append(f"品牌值未在 UTG 中出现: {values['brand']}")
        if values.get("model") and str(values["model"]) not in text:
            issues.append(f"型号值未在 UTG 中出现: {values['model']}")

        result = {
            "passed": not issues,
            "score": 1.0 if not issues else max(0.4, 1.0 - len(issues) * 0.2),
            "issues": issues,
            "suggestions": [],
            "source": "rules",
        }

        if self.validate_with_llm and self.llm:
            prompt = LLM_VALIDATE_PROMPT.format(
                utg_text=text[:8000],
                related_data=json.dumps(self._related_data(template), ensure_ascii=False),
                extracted=json.dumps({"fields": fields, "mockInstance": instance}, ensure_ascii=False),
            )
            try:
                llm_result = self.llm.extract_json(self.llm.chat(prompt))
                result["llm"] = llm_result
                if llm_result.get("passed") is False:
                    result["passed"] = False
                    result["issues"].extend(llm_result.get("issues", []))
                result["score"] = min(float(llm_result.get("score", result["score"])), result["score"])
            except Exception as e:
                result["llm"] = {"passed": False, "issues": [f"LLM 验证失败: {e}"]}
        return result

    def _collect_utg_text(self, utg: Dict[str, Any]) -> str:
        parts = [utg.get("query", ""), utg.get("appName", "")]
        for step in utg.get("stepData", []):
            parts.extend([
                step.get("thought", ""),
                step.get("ui_summary", ""),
                step.get("action_type", ""),
            ])
        return "\n".join(p for p in parts if p)

    @staticmethod
    def _first_match(text: str, patterns: List[str]) -> Optional[str]:
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    @staticmethod
    def _first_number(text: str, patterns: List[str]) -> Optional[float]:
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = float(match.group(1))
                return int(value) if value.is_integer() else value
        return None

    @staticmethod
    def _slug(value: Any) -> str:
        raw = str(value).strip().lower()
        if not raw:
            return ""
        replacements = {
            "华为": "huawei",
            "畅享": "enjoy",
            "雪域白": "white",
            "苹果": "apple",
            "小米": "xiaomi",
            "三星": "samsung",
        }
        for src, dst in replacements.items():
            raw = raw.replace(src, dst)
        raw = re.sub(r"[^a-z0-9]+", "-", raw)
        return raw.strip("-")

    @staticmethod
    def _infer_type(value: Any) -> str:
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, (int, float)):
            return "number"
        if isinstance(value, list):
            return "array"
        return "string"

    @staticmethod
    def _is_forbidden_field(field_id: str) -> bool:
        lowered = field_id.lower()
        return (
            lowered in {"stepid", "imageid", "actiontype", "costtime", "thought"}
            or lowered.startswith("step")
            or lowered.startswith("image")
            or bool(re.fullmatch(r"\d+(?:_\d+)+", field_id))
        )

    @staticmethod
    def _load_json(path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _save_json(data: Dict[str, Any], path: str):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
