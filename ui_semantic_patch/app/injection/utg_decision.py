"""
UTG 文本决策器

基于 utg.json 的全量 ui_summary 语义序列，通过纯文本 LLM 一次性决策注入点。

两种模式：
1. 自由模式（无 mapping_config）：LLM 自由决定 anomaly_mode + instruction + injection_step
2. 约束模式（有 mapping_config）：异常配置已由 mapping.json 确定，LLM 只决策 injection_step
"""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

from .utg_loader import UTGLoader

logger = logging.getLogger(__name__)

# ==================== 自由模式 Prompt ====================

FREE_DECISION_PROMPT = """你是一个 App 异常测试场景生成专家。给定一个 App 操作序列中每步的 UI 状态描述，你需要决策在哪个步骤注入什么类型的异常最合理。

## 任务背景
{task_description}

## 操作序列 UI 状态描述
{steps_text}

## 可用异常类型
{anomaly_options}

## 决策原则
1. 注入位置：选择用户刚完成关键操作后、进入新页面的时机
2. 异常类型：选择与当前 UI 状态自然契合的异常
3. 注入指令：用中文描述异常效果，结合当前页面具体内容

## 输出格式（仅返回 JSON）
{{
  "injection_step": <int>,
  "anomaly_mode": "<string>",
  "instruction": "<string>",
  "reason": "<string>"
}}
"""

# ==================== 约束模式 Prompt（LLM 批量打分） ====================

CONSTRAINED_SCORING_PROMPT = """你是一个 App 异常测试场景评估专家。

## 要评估的异常
- 类型: {anomaly_mode}
- 描述: {instruction}

## 操作序列（按时间顺序，每步包含操作意图和 UI 描述）
{steps_text}

## 任务
对整个操作序列的每一步打分，评估在该步注入上述异常是否自然合理。请结合上下文整体分析（前后步骤的连贯性），而非孤立评判。

## 评分标准（0-10）
- 8-10: 非常适合。页面是明确的业务结果页（如搜索结果、商品详情、订单确认），有交互元素，异常能与页面内容高度契合，且在该步注入不会破坏关键操作用户流程
- 5-7: 尚可。页面有一定相关性，但不够理想
- 0-4: 不适合。首页、加载中、输入中、不在关键路径上

## 额外原则
1. 首页/导航页（stepId 较小且 UI 为首页特征）→ 低分
2. 搜索结果、商品列表、详情页 → 高分
3. 关键操作（点击购买、确认支付）刚要发生之前 → 高分
4. 序列末尾（末步）→ 低分

## 输出格式（仅返回 JSON，不要其他内容）
{{
  "scores": [
    {{"step": 0, "score": <int 0-10>, "reason": "<一句话>"}},
    ...
  ],
  "best_step": <int>,
  "best_reason": "<string>"
}}
"""

ANOMALY_OPTIONS_TEMPLATE = """- dialog: 弹窗覆盖 — 广告弹窗、优惠券弹窗、权限请求弹窗
- area_loading: 加载异常 — 加载超时、网络错误
- content_duplicate: 内容重复 — 底部浮层重复、信息冗余
- text_overlay: 文字覆盖 — 局部文字替换/覆盖（价格篡改、文案插入）"""


def _load_injection_config(
    mapping_config_path: str,
    fault_mode: str = None,
    fault_mode_key: str = None,
) -> Optional[Dict]:
    """
    从 mapping.json 加载单个 injection_config

    查找策略：
    1. 指定 fault_mode → 精确匹配 fault_mode 字段
    2. 指定 fault_mode_key（如 mode_1）→ 匹配 fault_mode_key 字段
    3. 否则取第一条 mapping
    """
    path = Path(mapping_config_path)
    if not path.exists():
        raise FileNotFoundError(f"mapping 配置文件不存在: {mapping_config_path}")

    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    mappings = data.get("mappings", [])
    if not mappings:
        return None

    target = None
    if fault_mode_key:
        for m in mappings:
            if m.get("fault_mode_key") == fault_mode_key:
                target = m
                break
    if target is None and fault_mode:
        for m in mappings:
            if m.get("fault_mode") == fault_mode:
                target = m
                break
    if target is None:
        target = mappings[0]

    inj = target.get("injection_config", {})
    if not inj:
        return None

    return {
        "anomaly_mode": inj.get("anomaly_mode", "dialog"),
        "instruction": inj.get("instruction", ""),
        "gt_category": inj.get("gt_category", ""),
        "gt_sample": inj.get("gt_sample", ""),
        "reference_path": inj.get("reference_path", ""),
        "fault_mode": target.get("fault_mode", ""),
        "app_name": target.get("app_name", ""),
    }


def list_fault_modes(mapping_config_path: str) -> List[Dict]:
    """列出 mapping.json 中所有可用的 fault_mode"""
    path = Path(mapping_config_path)
    if not path.exists():
        return []
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    seen = set()
    modes = []
    for m in data.get("mappings", []):
        fm = m.get("fault_mode", "")
        fk = m.get("fault_mode_key", "")
        key = (fm, fk)
        if key not in seen:
            seen.add(key)
            modes.append({
                "fault_mode": fm, "fault_mode_key": fk,
                "app_name": m.get("app_name", "")
            })
    return modes


class UTGDecisionMaker:

    def __init__(
        self,
        api_key: str = None,
        api_url: str = None,
        model: str = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ):
        self.api_key = api_key or os.getenv('VLM_API_KEY')
        self.api_url = api_url or os.getenv(
            'VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions'
        )
        self.model = model or os.getenv('VLM_MODEL', 'gpt-4o')
        self.temperature = temperature
        self.max_tokens = max_tokens
        if not self.api_key:
            raise ValueError("VLM_API_KEY 环境变量未设置")

    def decide(
        self,
        loader: UTGLoader,
        max_retries: int = 2,
        task_override: str = None,
        mapping_config: str = None,
        fault_mode: str = None,
        fault_mode_key: str = None,
        injection_config: Dict = None,
    ) -> Dict:
        """注入决策。injection_config 优先于 mapping_config（直接传 dict，免文件加载）"""
        valid_steps = loader.get_valid_steps()
        if not valid_steps:
            return self._error("utg.json 中没有有效的 ui_summary 步骤")

        config = injection_config
        if config is None and mapping_config:
            config = _load_injection_config(
                mapping_config, fault_mode=fault_mode, fault_mode_key=fault_mode_key
            )
        if config:
            # 归一化：直接传的 dict 可能缺少字段，补默认值
            config = {
                "anomaly_mode": config.get("anomaly_mode", "dialog"),
                "instruction": config.get("instruction", ""),
                "gt_category": config.get("gt_category", ""),
                "gt_sample": config.get("gt_sample", ""),
                "reference_path": config.get("reference_path", ""),
                "fault_mode": config.get("fault_mode", ""),
                "app_name": config.get("app_name", ""),
            }
            if not config["instruction"]:
                return self._error("injection_config 缺少 instruction")
            print(f"  [UTG决策] 约束模式: {config['fault_mode'] or config['anomaly_mode']}")

        task_desc = task_override or loader.task_description
        steps_text = loader.get_summary_text()
        print(f"  [UTG决策] 分析 {len(valid_steps)} 个步骤...")

        if config:
            prompt = CONSTRAINED_SCORING_PROMPT.format(
                anomaly_mode=config["anomaly_mode"],
                instruction=config["instruction"],
                steps_text=steps_text,
            )
            raw = self._call_llm(prompt, max_retries)
            result = self._parse_scoring_response(raw, len(valid_steps), config)
        else:
            prompt = FREE_DECISION_PROMPT.format(
                task_description=task_desc, steps_text=steps_text,
                anomaly_options=ANOMALY_OPTIONS_TEMPLATE,
            )
            raw = self._call_llm(prompt, max_retries)
            result = self._parse_free(raw, len(valid_steps))

        if result["success"] and result.get("injection_step", -1) >= 0:
            s = valid_steps[result["injection_step"]]
            print(f"  [UTG决策] ✓ Step {result['injection_step']} (stepId={s.step_id})")
            print(f"  [UTG决策]   {result.get('anomaly_mode','?')} | {result.get('instruction','')[:50]}...")
        else:
            print(f"  [UTG决策] 跳过: {result.get('reason', result.get('error', '未知'))}")
        return result

    def _error(self, msg: str) -> Dict:
        return {
            "success": False, "injection_step": None,
            "anomaly_mode": None, "instruction": None,
            "gt_sample": None, "gt_category": None,
            "reason": "", "error": msg,
        }

    def _call_llm(self, prompt: str, max_retries: int = 2) -> str:
        headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {self.api_key}'}
        payload = {"model": self.model, "messages": [{"role": "user", "content": prompt}],
                    "temperature": self.temperature, "max_tokens": self.max_tokens}
        last_error = None
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    time.sleep(min(5 * (2 ** (attempt - 1)), 60))
                resp = requests.post(self.api_url, headers=headers, json=payload, timeout=180)
                if resp.status_code == 429:
                    last_error = "API 限流 (429)"; continue
                elif resp.status_code >= 500:
                    last_error = f"服务器错误 ({resp.status_code})"; continue
                resp.raise_for_status()
                return resp.json()['choices'][0]['message']['content']
            except requests.exceptions.RequestException as e:
                last_error = str(e)
                if attempt == max_retries - 1:
                    raise
        raise Exception(f"LLM 调用失败，已重试 {max_retries} 次: {last_error}")

    def _extract_json(self, response: str) -> str:
        m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response)
        if m:
            return m.group(1)
        m = re.search(r'\{[\s\S]*\}', response)
        return m.group(0) if m else response

    def _parse_free(self, response: str, total_steps: int) -> Dict:
        VALID = {"dialog","area_loading","content_duplicate","text_overlay",
                  "modify_text","modify_text_ai","modify_text_ocr","modify_text_e2e","image_broken"}
        try:
            d = json.loads(self._extract_json(response))
            step = d.get("injection_step")
            if not isinstance(step, int) or step < 0 or step >= total_steps:
                return self._error(f"injection_step 无效: {step}")
            mode = d.get("anomaly_mode","").strip().lower()
            if mode not in VALID:
                mode = next((v for v in VALID if v in mode), "dialog")
            inst = d.get("instruction","").strip()
            if not inst:
                return self._error("instruction 为空")
            return {
                "success": True, "injection_step": step,
                "anomaly_mode": mode, "instruction": inst,
                "gt_sample": "", "gt_category": "",
                "reason": d.get("reason",""), "error": None,
                "raw_response": response,
            }
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            return self._error(f"解析失败: {e}")

    def _parse_scoring_response(
        self, response: str, total_steps: int, config: Dict
    ) -> Dict:
        """解析批量打分响应，选最高分 step"""
        try:
            d = json.loads(self._extract_json(response))
            scores = d.get("scores", [])

            if not scores:
                return self._error("LLM 未返回任何打分")

            # 收集有效候选（score > 0 且 step 合法）
            candidates = []
            for s in scores:
                step = s.get("step", -1)
                score = s.get("score", 0)
                if 0 <= step < total_steps and score > 0:
                    candidates.append({
                        "step": step, "score": score,
                        "reason": s.get("reason", ""),
                    })

            if not candidates:
                return {
                    "success": True, "injection_step": -1,
                    "anomaly_mode": config["anomaly_mode"],
                    "instruction": config["instruction"],
                    "gt_sample": config.get("gt_sample", ""),
                    "gt_category": config.get("gt_category", ""),
                    "reason": d.get("best_reason", "无合适步骤"),
                    "scores": scores, "error": None,
                    "raw_response": response,
                }

            # 按分数排序，选最高
            candidates.sort(key=lambda c: c["score"], reverse=True)
            best = candidates[0]

            # 阈值：低于 5 分视为不合适
            SCORE_THRESHOLD = 5
            if best["score"] < SCORE_THRESHOLD:
                return {
                    "success": True, "injection_step": -1,
                    "anomaly_mode": config["anomaly_mode"],
                    "instruction": config["instruction"],
                    "gt_sample": config.get("gt_sample", ""),
                    "gt_category": config.get("gt_category", ""),
                    "reason": f"最高分 {best['score']} < {SCORE_THRESHOLD} 阈值: {best['reason']}",
                    "scores": scores, "candidates": candidates,
                    "best_candidate": best, "error": None,
                    "raw_response": response,
                }

            return {
                "success": True, "injection_step": best["step"],
                "anomaly_mode": config["anomaly_mode"],
                "instruction": config["instruction"],
                "gt_sample": config.get("gt_sample", ""),
                "gt_category": config.get("gt_category", ""),
                "reference_path": config.get("reference_path", ""),
                "reason": best["reason"],
                "score": best["score"],
                "scores": scores, "candidates": candidates,
                "best_candidate": best,
                "error": None, "raw_response": response,
            }
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            return self._error(f"打分解析失败: {e}")


def make_utg_decision(
    utg_path: str,
    api_key: str = None,
    api_url: str = None,
    model: str = None,
    mapping_config: str = None,
    fault_mode: str = None,
    fault_mode_key: str = None,
) -> Dict:
    loader = UTGLoader(utg_path)
    print(f"  [UTG] 加载: {loader.total_steps} 原始步骤, {loader.valid_count} 有效步骤")
    maker = UTGDecisionMaker(api_key=api_key, api_url=api_url, model=model)
    return maker.decide(
        loader, mapping_config=mapping_config,
        fault_mode=fault_mode, fault_mode_key=fault_mode_key,
    )
