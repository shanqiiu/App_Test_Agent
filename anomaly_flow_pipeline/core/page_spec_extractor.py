"""
page_spec_extractor.py — 从 utg.json 的 ui_summary 中抽取页面类型 Spec

三阶段流程：
  Phase 1: 原始页面类型提取（每个 step 的 ui_summary → LLM → 页面类型短语）
  Phase 2: 聚类归一化（按 app 分组 → LLM → 标准 page_type 名称）
  Phase 3: 构建 Spec（生成 instruction 模板 → page_spec.json）
"""

import json
import logging
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Any

from .llm_client import LLMClient

logger = logging.getLogger(__name__)

# ── Prompt 模板 ──────────────────────────────────────────

PAGE_TYPE_EXTRACT_PROMPT = """你是一个 App 页面类型分类专家。判断当前页面的类型。

App 名称：{appName}
用户操作意图：{thought}
当前页面 UI 描述：{ui_summary}

用 2-6 个中文词描述页面类型，聚焦页面功能。
例如：搜索结果页、商品详情页、确认订单页、首页搜索框。

只输出页面类型名称，不要其他内容。"""

CLUSTER_PROMPT = """你是一个 App 页面类型分类专家。以下是 {appName} App 操作序列中提取出的所有原始页面类型描述，请将它们聚类并归一化为标准名称。

原始列表：
{raw_types}

要求：
1. 相似的描述归为一类
2. 标准名称 4-8 个中文词，带"页面"后缀
3. 统计每类出现次数

输出 JSON（只输出 JSON，不要其他内容）：
{{
  "appName": "{appName}",
  "page_types": [
    {{"name": "搜索结果页面", "aliases": ["搜索结果","搜索列表页"], "count": 12}},
    ...
  ]
}}"""

SPEC_TEMPLATE_PROMPT = """你是一个 App 异常测试场景专家。为以下页面类型和异常模式生成确定性的指令模板。

App 名称：{appName}
页面类型：{page_type}
页面描述：{page_description}

异常模式：dialog, area_loading, content_duplicate, text_overlay, modify_text, modify_text_ai, modify_text_ocr, modify_text_e2e, image_broken

要求：
1. 为每种异常模式生成一个指令模板，格式为："在{page_type}，{{具体异常操作描述}}"
2. 每个模板一句话，20-40 字

输出 JSON（只输出 JSON）：
{{
  "page_type": "{page_type}",
  "appName": "{appName}",
  "templates": [
    {{"anomaly_mode": "dialog", "template": "在{page_type}生成广告弹窗"}},
    ...
  ]
}}"""


class PageSpecExtractor:
    """页面类型 Spec 抽取器"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.llm = LLMClient(api_key=api_key, api_url=api_url, model=model, temperature=0.0, max_tokens=256)
        self.llm_spec = LLMClient(api_key=api_key, api_url=api_url, model=model, temperature=0.1, max_tokens=512)

    # ── Phase 1 ─────────────────────────────────────────

    def scan_utg_files(self, data_dir: str) -> List[Path]:
        data_path = Path(data_dir)
        if not data_path.exists():
            raise FileNotFoundError(f"目录不存在: {data_dir}")
        utg_files = []
        for f in data_path.glob("*.json"):
            if f.name in ("utg.json", "utg_info.json"):
                utg_files.append(f)
        for subdir in data_path.iterdir():
            if subdir.is_dir():
                for name in ("utg_info.json", "utg.json"):
                    p = subdir / name
                    if p.exists():
                        utg_files.append(p)
                        break
        return sorted(set(utg_files))

    def extract_raw_page_types(self, utg_files: List[Path]) -> List[Dict]:
        """Phase 1: 提取原始页面类型"""
        extractions = []
        for utg_path in utg_files:
            try:
                with open(utg_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"  跳过 {utg_path}: {e}")
                continue

            app_name = data.get("appName", data.get("app_name", "未知"))
            step_data = data.get("stepData", [])
            logger.info(f"  [{app_name}] {utg_path.name} ({len(step_data)} steps)")

            for step in step_data:
                step_id = str(step.get("stepId", ""))
                if step_id.lower() in {"home", "end", "start"}:
                    continue
                ui_summary = (step.get("ui_summary") or "").strip()
                thought = (step.get("thought") or "").strip()
                if not ui_summary:
                    continue

                prompt = PAGE_TYPE_EXTRACT_PROMPT.format(
                    appName=app_name, thought=thought[:200] or "(无)", ui_summary=ui_summary[:500],
                )
                try:
                    page_type = self.llm.chat(prompt).split('\n')[0].strip().strip('。，,.')
                    if page_type:
                        extractions.append({
                            "appName": app_name,
                            "stepId": step_id,
                            "raw_page_type": page_type,
                            "ui_summary": ui_summary[:300],
                        })
                        logger.info(f"    Step {step_id}: {page_type}")
                except Exception as e:
                    logger.error(f"    Step {step_id}: LLM 提取失败: {e}")

        logger.info(f"\nPhase 1 完成: 共提取 {len(extractions)} 条页面类型")
        return extractions

    # ── Phase 2 ─────────────────────────────────────────

    def normalize_page_types(self, extractions: List[Dict]) -> Dict[str, Any]:
        """Phase 2: 按 appName 聚类归一化"""
        by_app = defaultdict(list)
        for ext in extractions:
            by_app[ext["appName"]].append(ext["raw_page_type"])

        result = {"version": "1.0", "apps": {}}

        for app_name, raw_types in sorted(by_app.items()):
            unique_types = list(dict.fromkeys(raw_types))
            logger.info(f"\n[{app_name}] {len(unique_types)} 种原始页面类型 → 聚类中...")

            prompt = CLUSTER_PROMPT.format(
                appName=app_name,
                raw_types=json.dumps(
                    [{"type": t, "count": raw_types.count(t)} for t in unique_types],
                    ensure_ascii=False,
                ),
            )
            try:
                raw = self.llm.chat(prompt)
                resp = self.llm.extract_json(raw)
                page_types = resp.get("page_types", [])
                result["apps"][app_name] = page_types
                for pt in page_types:
                    logger.info(f"  ✓ {pt['name']} (×{pt['count']})")
            except Exception as e:
                logger.warning(f"  首次解析失败，重试中: {e}")
                try:
                    retry_prompt = prompt + "\n\n重要：只输出纯 JSON，不要 markdown 代码块，不要任何额外文字。确保 JSON 格式正确，不要尾随逗号。"
                    raw = self.llm.chat(retry_prompt)
                    resp = self.llm.extract_json(raw)
                    page_types = resp.get("page_types", [])
                    result["apps"][app_name] = page_types
                    for pt in page_types:
                        logger.info(f"  ✓ {pt['name']} (×{pt['count']}) [重试成功]")
                except Exception as e2:
                    logger.error(f"  ✗ 聚类失败 (重试后): {e2}")
                    result["apps"][app_name] = []

        return result

    # ── Phase 3 ─────────────────────────────────────────

    def build_spec(self, normalized: Dict[str, Any]) -> Dict[str, Any]:
        """Phase 3: 构建 Spec"""
        APP_CATEGORY_MAP = {
            "淘宝": "shopping", "天猫": "shopping", "京东": "shopping", "拼多多": "shopping",
            "华为商城": "shopping", "去哪儿旅行": "travel", "铁路12306": "travel", "12306": "travel",
            "携程": "travel", "腾讯视频": "video", "QQ音乐": "music", "直播吧": "sports",
            "小红书": "social", "美团": "delivery", "饿了么": "delivery",
        }

        spec = {"version": "1.0", "description": "页面类型 Spec", "categories": {}}
        cat_apps = defaultdict(list)
        apps_data = normalized.get("apps", {})

        for app_name in apps_data:
            cat = APP_CATEGORY_MAP.get(app_name, "other")
            cat_apps[cat].append(app_name)

        for category, app_list in sorted(cat_apps.items()):
            cat_entry = {"name": category, "apps": app_list, "page_types": {}}
            for app_name in app_list:
                for pt in apps_data.get(app_name, []):
                    pt_name = pt["name"]
                    if pt_name not in cat_entry["page_types"]:
                        cat_entry["page_types"][pt_name] = {
                            "page_type": pt_name, "aliases": pt.get("aliases", []),
                            "appearance_count": 0, "templates": {},
                        }
                    entry = cat_entry["page_types"][pt_name]
                    entry["appearance_count"] += pt.get("count", 0)
                    existing = set(entry.get("aliases", []))
                    existing.update(pt.get("aliases", []))
                    entry["aliases"] = sorted(existing)

            logger.info(f"\n[{category}] 生成指令模板...")
            for pt_name, pt_entry in cat_entry["page_types"].items():
                templates = self._generate_templates(app_list[0], pt_name, pt_entry.get("aliases", [pt_name])[0])
                pt_entry["templates"] = templates
                for t in templates:
                    logger.info(f"    {t['anomaly_mode']}: {t['template'][:60]}...")

            spec["categories"][category] = cat_entry

        return spec

    def _generate_templates(self, app_name: str, page_type: str, page_description: str) -> List[Dict]:
        prompt = SPEC_TEMPLATE_PROMPT.format(appName=app_name, page_type=page_type, page_description=page_description)
        anomaly_modes = ["dialog", "area_loading", "content_duplicate", "text_overlay",
                         "modify_text", "modify_text_ai", "modify_text_ocr", "modify_text_e2e", "image_broken"]
        try:
            resp = self.llm_spec.extract_json(self.llm_spec.chat(prompt))
            templates = resp.get("templates", [])
            valid = [t for t in templates if t.get("anomaly_mode") in anomaly_modes]
            if valid:
                return valid
        except Exception as e:
            logger.warning(f"    LLM 模板生成失败: {e}")

        fallback = {
            "dialog": f"在{page_type}生成弹窗",
            "area_loading": f"在{page_type}模拟加载超时",
            "content_duplicate": f"在{page_type}制造内容重复",
            "text_overlay": f"在{page_type}生成文字遮挡",
            "modify_text": f"在{page_type}将目标文字修改为异常状态",
            "modify_text_ai": f"在{page_type}用 AI 编辑目标文字",
            "modify_text_ocr": f"在{page_type}用 OCR 定位替换文字",
            "modify_text_e2e": f"在{page_type}进行端到端文字编辑",
            "image_broken": f"在{page_type}将图片替换为加载失败",
        }
        return [{"anomaly_mode": mode, "template": fallback.get(mode, f"在{page_type}注入{mode}异常")} for mode in anomaly_modes]

    # ── 全流程 ──────────────────────────────────────────

    def run(self, data_dir: str, output_dir: Optional[str] = None,
            skip_phase: int = 0, resume: Optional[str] = None) -> Dict[str, Any]:
        print(f"\n{'='*60}\n页面类型 Spec 抽取器\n  LLM: {self.llm.model}\n  数据目录: {data_dir}\n{'='*60}\n")
        output_path = Path(output_dir) if output_dir else Path.cwd()
        if output_dir:
            output_path.mkdir(parents=True, exist_ok=True)

        result = {}

        if skip_phase < 1:
            print("\n>>> Phase 1: 原始页面类型提取")
            if resume and Path(resume).exists():
                with open(resume, 'r', encoding='utf-8') as f:
                    extractions = json.load(f)
                print(f"  从文件恢复: {resume} ({len(extractions)} 条)")
            else:
                utg_files = self.scan_utg_files(data_dir)
                if not utg_files:
                    print("  ❌ 未找到 utg.json 文件")
                    return result
                extractions = self.extract_raw_page_types(utg_files)
            result["raw_extractions"] = extractions
            if output_dir:
                with open(output_path / "raw_extractions.json", 'w', encoding='utf-8') as f:
                    json.dump(extractions, f, ensure_ascii=False, indent=2)

        if skip_phase < 2:
            print("\n>>> Phase 2: 聚类归一化")
            extractions = result.get("raw_extractions", [])
            if extractions:
                normalized = self.normalize_page_types(extractions)
                result["normalized"] = normalized
                if output_dir:
                    with open(output_path / "normalized_page_types.json", 'w', encoding='utf-8') as f:
                        json.dump(normalized, f, ensure_ascii=False, indent=2)

        if skip_phase < 3:
            print("\n>>> Phase 3: 构建 Spec")
            normalized = result.get("normalized", {})
            if normalized and normalized.get("apps"):
                page_spec = self.build_spec(normalized)
                result["page_spec"] = page_spec
                if output_dir:
                    with open(output_path / "page_spec.json", 'w', encoding='utf-8') as f:
                        json.dump(page_spec, f, ensure_ascii=False, indent=2)

        print(f"\n{'='*60}\n抽取完成\n{'='*60}")
        return result
