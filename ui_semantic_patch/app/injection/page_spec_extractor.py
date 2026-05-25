"""
PageSpecExtractor — 从 utg.json 的 ui_summary 中抽取页面类型 Spec

三阶段流程：
  Phase 1: 原始页面类型提取
   对每个 utg.json 中每个 step 的 ui_summary
   → LLM 提取页面类型短语（2-6 字）
   → 输出 raw_extractions

  Phase 2: 聚类归一化
   按 appName 分组
   → LLM 将相似描述聚类为标准名称
   → 输出 normalized_page_types

  Phase 3: 构建 Spec
   按 app 聚合，生成指令模板
   → 输出 page_spec.json

使用方式：
    extractor = PageSpecExtractor()
    result = extractor.run("path/to/utg_data_dir")
    # result["page_spec"] 即为最终 spec
"""

import json
import logging
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import requests

logger = logging.getLogger(__name__)

# ============================================================
# Prompt 模板
# ============================================================

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
1. 相似的描述归为一类（"搜索结果"、"搜索列表页"、"搜索结果页" → "搜索结果页面"）
2. 标准名称 4-8 个中文词，带"页面"后缀
3. 统计每类出现次数

输出 JSON（只输出 JSON，不要其他内容）：
{{
  "appName": "{appName}",
  "page_types": [
    {{"name": "搜索结果页面", "aliases": ["搜索结果","搜索列表页","搜索结果页"], "count": 12}},
    ...
  ]
}}"""

SPEC_TEMPLATE_PROMPT = """你是一个 App 异常测试场景专家。为以下页面类型和异常模式生成确定性的指令模板。

App 名称：{appName}
页面类型：{page_type}
页面描述：{page_description}

异常模式列表及其含义：
- dialog: 弹窗覆盖 — 广告弹窗、优惠券弹窗、权限请求弹窗
- area_loading: 加载异常 — 区域加载超时、网络错误
- content_duplicate: 内容重复 — 列表项重复、信息冗余
- text_overlay: 文字覆盖 — 局部文字替换/覆盖（价格篡改、文案插入）
- modify_text: OCR 精定位文字替换（按钮文字修改等）
- modify_text_ai: AI 图像编辑文字替换
- modify_text_ocr: OCR 精定位 + PIL 渲染文字替换
- modify_text_e2e: 端到端全图 AI 编辑
- image_broken: 图片加载失败 — 商品图/头像显示为裂图

要求：
1. 为每种异常模式生成一个指令模板，格式为："在{page_type}，{具体异常操作描述}"
2. 指令模板要具体、可操作，包含页面元素的描述
3. 可选字段用 {{}} 表示（如 {{目标元素}}、{{异常状态}}）
4. 每个模板一句话，20-40 字

输出 JSON（只输出 JSON）：
{{
  "page_type": "{page_type}",
  "appName": "{appName}",
  "templates": [
    {{"anomaly_mode": "dialog", "template": "在{page_type}生成广告弹窗遮挡功能入口"}},
    ...
  ]
}}"""


class LLMClient:
    """轻量 LLM 调用客户端，复用 .env 中的 VLM 配置"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 256,
        timeout: int = 120,
    ):
        self.api_key = api_key or os.getenv('VLM_API_KEY')
        self.api_url = api_url or os.getenv(
            'VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions'
        )
        self.model = model or os.getenv('VLM_MODEL', 'gpt-4o')
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

        if not self.api_key:
            raise ValueError("VLM_API_KEY 未设置。请在 .env 中配置或通过参数传入。")

    def chat(self, prompt: str, max_retries: int = 2) -> str:
        """调用 LLM，返回文本响应"""
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}',
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        last_error = None
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    wait = min(5 * (2 ** (attempt - 1)), 60)
                    logger.info(f"  重试 {attempt + 1}/{max_retries}，等待 {wait}s...")
                    time.sleep(wait)

                resp = requests.post(
                    self.api_url, headers=headers, json=payload,
                    timeout=self.timeout,
                )
                if resp.status_code == 429:
                    last_error = "API 限流 (429)"
                    continue
                elif resp.status_code >= 500:
                    last_error = f"服务器错误 ({resp.status_code})"
                    continue
                resp.raise_for_status()
                content = resp.json()['choices'][0]['message']['content']
                return content.strip()

            except requests.exceptions.RequestException as e:
                last_error = str(e)
                if attempt == max_retries - 1:
                    raise

        raise RuntimeError(f"LLM 调用失败，已重试 {max_retries} 次: {last_error}")

    @staticmethod
    def extract_json(text: str) -> Dict:
        """从 LLM 响应中提取 JSON"""
        m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if m:
            return json.loads(m.group(1))
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            return json.loads(m.group(0))
        return json.loads(text)


class PageSpecExtractor:
    """
    页面类型 Spec 抽取器

    三阶段流程：
    1. 提取原始页面类型（每个 utg 每个 step）
    2. 按 app 聚类归一化
    3. 构建最终 spec 表
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
            max_tokens=256,
        )
        self.llm_spec = LLMClient(
            api_key=api_key,
            api_url=api_url,
            model=model,
            temperature=0.1,
            max_tokens=512,
        )

    # ── Phase 1: 原始页面类型提取 ──────────────────────────

    def scan_utg_files(self, data_dir: str) -> List[Path]:
        """
        扫描目录，找到所有 utg.json / utg_info.json

        支持两种结构：
        1. 平铺：data_dir/*.json
        2. 子目录：data_dir/{uuid}/utg_info.json
        """
        data_path = Path(data_dir)
        if not data_path.exists():
            raise FileNotFoundError(f"目录不存在: {data_dir}")

        utg_files = []

        # 直接 .json 文件
        for f in data_path.glob("*.json"):
            if f.name in ("utg.json", "utg_info.json"):
                utg_files.append(f)

        # 子目录中的 utg_info.json / utg.json
        for subdir in data_path.iterdir():
            if subdir.is_dir():
                for name in ("utg_info.json", "utg.json"):
                    p = subdir / name
                    if p.exists():
                        utg_files.append(p)
                        break

        if not utg_files:
            logger.warning(f"在 {data_dir} 中未找到 utg.json 文件")
        else:
            logger.info(f"找到 {len(utg_files)} 个 utg.json 文件")

        return sorted(set(utg_files))

    def extract_raw_page_types(self, utg_files: List[Path]) -> List[Dict]:
        """
        Phase 1: 对每个 utg.json 中每个有 ui_summary 的 step，
        用 LLM 提取页面类型短语。
        """
        extractions = []

        for utg_path in utg_files:
            try:
                with open(utg_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"  跳过 {utg_path}: {e}")
                continue

            app_name = data.get("appName", data.get("app_name", "未知"))
            query = data.get("query", "")
            uuid = data.get("uuid", utg_path.stem)
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

                # 调用 LLM 提取页面类型
                prompt = PAGE_TYPE_EXTRACT_PROMPT.format(
                    appName=app_name,
                    thought=thought[:200] if thought else "(无)",
                    ui_summary=ui_summary[:500],
                )

                try:
                    page_type = self.llm.chat(prompt)
                    # 清理：只取第一行，去除标点
                    page_type = page_type.split('\n')[0].strip().strip('。，,.')

                    if page_type:
                        extractions.append({
                            "appName": app_name,
                            "uuid": uuid,
                            "query": query,
                            "stepId": step_id,
                            "imageId": step.get("imageId", ""),
                            "thought": thought[:200],
                            "ui_summary": ui_summary[:300],
                            "raw_page_type": page_type,
                        })
                        logger.info(f"    Step {step_id}: {page_type}")
                    else:
                        logger.warning(f"    Step {step_id}: LLM 返回空")

                except Exception as e:
                    logger.error(f"    Step {step_id}: LLM 提取失败: {e}")

        logger.info(f"\nPhase 1 完成: 共提取 {len(extractions)} 条页面类型")
        return extractions

    # ── Phase 2: 聚类归一化 ─────────────────────────────

    def normalize_page_types(self, extractions: List[Dict]) -> Dict[str, Any]:
        """
        Phase 2: 按 appName 分组，将原始页面类型聚类归一化为标准名称。
        """
        # 按 appName 分组
        by_app: Dict[str, List[str]] = defaultdict(list)
        for ext in extractions:
            by_app[ext["appName"]].append(ext["raw_page_type"])

        result = {
            "version": "1.0",
            "apps": {},
        }

        for app_name, raw_types in sorted(by_app.items()):
            # 去重但保留全部（LLM 需要看重复度来判断主流类型）
            unique_types = list(dict.fromkeys(raw_types))  # 保留顺序去重
            logger.info(f"\n[{app_name}] {len(unique_types)} 种原始页面类型 → 聚类中...")

            prompt = CLUSTER_PROMPT.format(
                appName=app_name,
                raw_types=json.dumps(
                    [{"type": t, "count": raw_types.count(t)}
                     for t in unique_types],
                    ensure_ascii=False,
                ),
            )

            try:
                resp = self.llm.extract_json(self.llm.chat(prompt))
                page_types = resp.get("page_types", [])
                result["apps"][app_name] = page_types
                for pt in page_types:
                    logger.info(f"  ✓ {pt['name']} (×{pt['count']})")

            except Exception as e:
                logger.error(f"  ✗ 聚类失败: {e}")
                result["apps"][app_name] = []

        return result

    # ── Phase 3: 构建 Spec ────────────────────────────────

    def build_spec(self, normalized: Dict[str, Any]) -> Dict[str, Any]:
        """
        Phase 3: 为每个 (app, page_type) 对生成指令模板。
        """
        spec = {
            "version": "1.0",
            "description": "页面类型 Spec — 从 ui_summary 中抽取的标准化页面类型及异常指令模板",
            "categories": {},
        }

        # 简单的 app → category 映射（可扩展）
        APP_CATEGORY_MAP = {
            "淘宝": "shopping",
            "天猫": "shopping",
            "京东": "shopping",
            "拼多多": "shopping",
            "华为商城": "shopping",
            "去哪儿旅行": "travel",
            "铁路12306": "travel",
            "12306": "travel",
            "携程": "travel",
            "腾讯视频": "video",
            "QQ音乐": "music",
            "直播吧": "sports",
            "小红书": "social",
            "美团": "delivery",
            "饿了么": "delivery",
        }

        apps_data = normalized.get("apps", {})

        # 收集 category 下的 apps
        cat_apps: Dict[str, list] = defaultdict(list)
        for app_name in apps_data:
            cat = APP_CATEGORY_MAP.get(app_name, "other")
            cat_apps[cat].append(app_name)

        for category, app_list in sorted(cat_apps.items()):
            cat_entry = {
                "name": category,
                "apps": app_list,
                "page_types": {},
            }

            for app_name in app_list:
                page_types = apps_data.get(app_name, [])
                for pt in page_types:
                    pt_name = pt["name"]
                    if pt_name not in cat_entry["page_types"]:
                        cat_entry["page_types"][pt_name] = {
                            "page_type": pt_name,
                            "aliases": pt.get("aliases", []),
                            "appearance_count": 0,
                            "templates": {},
                        }
                    entry = cat_entry["page_types"][pt_name]
                    entry["appearance_count"] += pt.get("count", 0)
                    # 合并 aliases
                    existing = set(entry.get("aliases", []))
                    existing.update(pt.get("aliases", []))
                    entry["aliases"] = sorted(existing)

            # 为每个 page_type 生成指令模板（使用 LLM）
            logger.info(f"\n[{category}] 生成指令模板...")
            for pt_name, pt_entry in cat_entry["page_types"].items():
                logger.info(f"  {pt_name} (×{pt_entry['appearance_count']})")
                templates = self._generate_templates(
                    app_name=app_list[0],
                    page_type=pt_name,
                    page_description=pt_entry.get("aliases", [pt_name])[0],
                )
                pt_entry["templates"] = templates
                for t in templates:
                    logger.info(f"    {t['anomaly_mode']}: {t['template'][:60]}...")

            spec["categories"][category] = cat_entry

        return spec

    def _generate_templates(
        self,
        app_name: str,
        page_type: str,
        page_description: str,
    ) -> List[Dict]:
        """
        为指定 (app, page_type) 生成各 anomaly_mode 的指令模板。
        """
        anomaly_modes = [
            "dialog", "area_loading", "content_duplicate",
            "text_overlay", "modify_text", "modify_text_ai",
            "modify_text_ocr", "modify_text_e2e", "image_broken",
        ]

        prompt = SPEC_TEMPLATE_PROMPT.format(
            appName=app_name,
            page_type=page_type,
            page_description=page_description,
        )

        try:
            resp = self.llm_spec.extract_json(self.llm_spec.chat(prompt))
            templates = resp.get("templates", [])
            # 过滤：只保留已知的 anomaly_mode
            valid = [t for t in templates if t.get("anomaly_mode") in anomaly_modes]
            if valid:
                return valid
        except Exception as e:
            logger.warning(f"    LLM 模板生成失败: {e}")

        # Fallback: 通用模板
        return [
            {"anomaly_mode": mode, "template": self._fallback_template(page_type, mode)}
            for mode in anomaly_modes
        ]

    @staticmethod
    def _fallback_template(page_type: str, anomaly_mode: str) -> str:
        """LLM 失败时的兜底模板"""
        templates = {
            "dialog": f"在{page_type}生成弹窗遮挡功能入口",
            "area_loading": f"在{page_type}模拟区域加载超时状态",
            "content_duplicate": f"在{page_type}制造内容重复异常",
            "text_overlay": f"在{page_type}生成文字覆盖/遮挡",
            "modify_text": f"在{page_type}将目标文字修改为异常状态",
            "modify_text_ai": f"在{page_type}用 AI 编辑目标文字为异常状态",
            "modify_text_ocr": f"在{page_type}用 OCR 定位并替换目标文字",
            "modify_text_e2e": f"在{page_type}进行端到端文字编辑",
            "image_broken": f"在{page_type}将图片替换为加载失败状态",
        }
        return templates.get(anomaly_mode, f"在{page_type}注入{anomaly_mode}异常")

    # ── 全流程 ────────────────────────────────────────────

    def run(
        self,
        data_dir: str,
        output_dir: Optional[str] = None,
        skip_phase: int = 0,
        resume: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        执行完整的 Spec 抽取流程。

        Args:
            data_dir: utg.json 所在目录
            output_dir: 可选，中间产物和结果保存目录
            skip_phase: 跳过前 N 个阶段（1=跳过 Phase1，以此类推）
            resume: 从指定中间产物文件恢复（如 raw_extractions.json）

        Returns:
            {"page_spec": ..., "normalized": ..., "raw_extractions": ...}
        """
        print(f"\n{'='*60}")
        print("页面类型 Spec 抽取器")
        print(f"  LLM: {self.llm.model}")
        print(f"  数据目录: {data_dir}")
        print(f"{'='*60}\n")

        output_path = Path(output_dir) if output_dir else Path.cwd()
        if output_dir:
            output_path.mkdir(parents=True, exist_ok=True)

        result = {}

        # ── Phase 1 ──
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
                raw_path = output_path / "raw_extractions.json"
                with open(raw_path, 'w', encoding='utf-8') as f:
                    json.dump(extractions, f, ensure_ascii=False, indent=2)
                print(f"  ✓ 已保存: {raw_path}")

        # ── Phase 2 ──
        if skip_phase < 2:
            print("\n>>> Phase 2: 聚类归一化")
            extractions = result.get("raw_extractions", [])
            if not extractions:
                print("  ❌ 无数据跳过 Phase 2")
            else:
                normalized = self.normalize_page_types(extractions)
                result["normalized"] = normalized

                if output_dir:
                    norm_path = output_path / "normalized_page_types.json"
                    with open(norm_path, 'w', encoding='utf-8') as f:
                        json.dump(normalized, f, ensure_ascii=False, indent=2)
                    print(f"  ✓ 已保存: {norm_path}")

        # ── Phase 3 ──
        if skip_phase < 3:
            print("\n>>> Phase 3: 构建 Spec")
            normalized = result.get("normalized", {})
            if not normalized or not normalized.get("apps"):
                print("  ❌ 无数据跳过 Phase 3")
            else:
                page_spec = self.build_spec(normalized)
                result["page_spec"] = page_spec

                if output_dir:
                    spec_path = output_path / "page_spec.json"
                    with open(spec_path, 'w', encoding='utf-8') as f:
                        json.dump(page_spec, f, ensure_ascii=False, indent=2)
                    print(f"\n  ✓ Spec 已保存: {spec_path}")

        print(f"\n{'='*60}")
        print("抽取完成")
        print(f"{'='*60}")
        return result


def run_extraction(
    data_dir: str,
    output_dir: Optional[str] = None,
    api_key: Optional[str] = None,
    api_url: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """便捷函数：一键执行 Spec 抽取"""
    extractor = PageSpecExtractor(
        api_key=api_key,
        api_url=api_url,
        model=model,
    )
    return extractor.run(data_dir=data_dir, output_dir=output_dir)
