"""
UTG 文本决策器

基于 utg.json 的全量 ui_summary 语义序列，通过纯文本 LLM 一次性决策注入点、异常类型和注入指令。

替代原 SequenceAnalyzer 的逐帧 VLM 图像分析流程。
"""

import json
import logging
import os
import re
import time
from typing import Dict, List, Optional

import requests

from .utg_loader import UTGLoader

logger = logging.getLogger(__name__)

# ==================== Prompt 模板 ====================

UTG_DECISION_PROMPT = """你是一个 App 异常测试场景生成专家。给定一个 App 操作序列中每步的 UI 状态描述，你需要决策在哪个步骤注入什么类型的异常最合理、最自然。

## 任务背景
{task_description}

## 操作序列 UI 状态描述
以下按时间顺序列出每一步的 UI 状态：
{steps_text}

## 可用异常类型
{anomaly_options}

## 决策原则
1. **注入位置**：选择用户刚完成一个关键操作后、进入新页面的时机。优先选择：
   - 页面加载完成后的稳定状态
   - 有明确交互元素（按钮、列表、价格）的页面
   - 不是首步（home页）也不是最后一步
2. **异常类型**：选择与当前 UI 状态自然契合的异常。例如：
   - 搜索结果/商品列表页 → dialog（优惠券弹窗）、content_duplicate
   - 商品详情页（有价格、购买按钮）→ dialog（促销弹窗）、text_overlay
   - 加载/等待状态 → area_loading
3. **注入指令**：用中文描述要生成的异常效果，需结合当前页面的具体内容。

## 输出格式（仅返回 JSON，不要其他内容）
{{
  "injection_step": <int>,
  "anomaly_mode": "<string>",
  "instruction": "<string>",
  "reason": "<string>"
}}
"""

ANOMALY_OPTIONS_TEMPLATE = """- dialog: 弹窗覆盖 — 在页面中央或底部弹出广告弹窗、优惠券弹窗、权限请求弹窗
- area_loading: 加载异常 — 在页面某区域显示加载超时、网络错误状态
- content_duplicate: 内容重复 — 底部浮层重复、列表信息冗余
- text_overlay: 文字覆盖 — 局部文字替换/覆盖（价格篡改、文案插入）"""


class UTGDecisionMaker:
    """UTG 文本决策器

    职责：
    1. 接收 UTGLoader 解析后的全量 ui_summary 序列
    2. 构造纯文本 prompt
    3. 调用文本 LLM（无需传图）
    4. 解析并验证 LLM 输出
    """

    def __init__(
        self,
        api_key: str = None,
        api_url: str = None,
        model: str = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ):
        """
        Args:
            api_key: LLM API 密钥，默认从 VLM_API_KEY 环境变量读取
            api_url: API 端点
            model: 模型名称
            temperature: 温度（0 为确定性输出）
            max_tokens: 最大输出 token
        """
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
    ) -> Dict:
        """
        分析全量 ui_summary 序列，输出注入决策

        Args:
            loader: UTGLoader 实例（已加载 utg.json）
            max_retries: LLM 调用最大重试次数

        Returns:
            {
                "success": True/False,
                "injection_step": int 或 None,
                "anomaly_mode": str 或 None,
                "instruction": str 或 None,
                "reason": str,
                "error": str 或 None
            }
        """
        valid_steps = loader.get_valid_steps()
        if not valid_steps:
            return {
                "success": False,
                "injection_step": None,
                "anomaly_mode": None,
                "instruction": None,
                "reason": "",
                "error": "utg.json 中没有有效的 ui_summary 步骤"
            }

        # 构建 prompt
        task_desc = loader.task_description
        steps_text = loader.get_summary_text()
        prompt = UTG_DECISION_PROMPT.format(
            task_description=task_desc,
            steps_text=steps_text,
            anomaly_options=ANOMALY_OPTIONS_TEMPLATE,
        )

        logger.info("UTG 决策: %d 个有效步骤, prompt 长度 %d 字符",
                      len(valid_steps), len(prompt))
        print(f"  [UTG决策] 分析 {len(valid_steps)} 个步骤的 UI 状态...")

        # 调用文本 LLM
        raw_response = self._call_llm(prompt, max_retries)

        # 解析
        result = self._parse_response(raw_response, len(valid_steps))

        # 验证
        if result["success"]:
            idx = result["injection_step"]
            step = valid_steps[idx]
            print(f"  [UTG决策] ✓ 注入点: Step {idx} (stepId={step.step_id})")
            print(f"  [UTG决策]   异常类型: {result['anomaly_mode']}")
            print(f"  [UTG决策]   指令: {result['instruction'][:60]}...")
            print(f"  [UTG决策]   理由: {result['reason'][:80]}...")
        else:
            print(f"  [UTG决策] ✗ 失败: {result.get('error', '未知错误')}")

        return result

    def _call_llm(self, prompt: str, max_retries: int = 2) -> str:
        """调用纯文本 LLM API"""
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }

        last_error = None
        base_wait = 5

        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    wait_time = min(base_wait * (2 ** (attempt - 1)), 60)
                    print(f"    ⏳ 等待 {wait_time}s 后重试 ({attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)

                response = requests.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=180
                )

                if response.status_code == 429:
                    print(f"    ⚠ API 限流 (429)，准备重试...")
                    last_error = "API 限流 (429)"
                    continue
                elif response.status_code >= 500:
                    print(f"    ⚠ 服务器错误 ({response.status_code})，准备重试...")
                    last_error = f"服务器错误 ({response.status_code})"
                    continue

                response.raise_for_status()
                result = response.json()
                return result['choices'][0]['message']['content']

            except requests.exceptions.RequestException as e:
                print(f"    ⚠ API 请求失败: {e}")
                last_error = str(e)
                if attempt == max_retries - 1:
                    raise

        raise Exception(f"LLM 调用失败，已重试 {max_retries} 次。最后错误: {last_error}")

    def _parse_response(self, response: str, total_steps: int) -> Dict:
        """解析 LLM 的 JSON 响应"""
        VALID_MODES = {
            "dialog", "area_loading", "content_duplicate", "text_overlay",
            "modify_text", "modify_text_ai", "modify_text_ocr", "modify_text_e2e",
            "image_broken",
        }

        default = {
            "success": False,
            "injection_step": None,
            "anomaly_mode": None,
            "instruction": None,
            "reason": "",
            "error": "LLM 响应解析失败"
        }

        try:
            # 提取 JSON（LLM 可能在 JSON 前后加 markdown 代码块标记）
            json_str = response
            # 去掉可能的 markdown 代码块
            code_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response)
            if code_match:
                json_str = code_match.group(1)
            else:
                # 直接找 JSON 对象
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    json_str = json_match.group(0)

            data = json.loads(json_str)

            # 校验 injection_step
            injection_step = data.get("injection_step")
            if not isinstance(injection_step, int) or injection_step < 0:
                return {**default, "error": f"injection_step 无效: {injection_step}"}
            if injection_step >= total_steps:
                return {**default, "error": f"injection_step ({injection_step}) 超出范围 (0-{total_steps - 1})"}

            # 校验 anomaly_mode
            anomaly_mode = data.get("anomaly_mode", "").strip().lower()
            if anomaly_mode not in VALID_MODES:
                # 尝试模糊匹配
                for vm in VALID_MODES:
                    if vm in anomaly_mode or anomaly_mode in vm:
                        anomaly_mode = vm
                        break
                else:
                    anomaly_mode = "dialog"  # 默认回退

            # 校验 instruction
            instruction = data.get("instruction", "").strip()
            if not instruction:
                return {**default, "error": "instruction 为空", "injection_step": injection_step}

            return {
                "success": True,
                "injection_step": injection_step,
                "anomaly_mode": anomaly_mode,
                "instruction": instruction,
                "reason": data.get("reason", ""),
                "error": None,
                "raw_response": response,
            }

        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.warning("UTG 决策响应解析失败: %s\n原始响应: %s", e, response[:500])
            return {**default, "error": f"JSON 解析失败: {e}"}


def make_utg_decision(
    utg_path: str,
    api_key: str = None,
    api_url: str = None,
    model: str = None,
) -> Dict:
    """
    便捷函数：加载 utg.json → 文本 LLM 决策

    Args:
        utg_path: utg.json 路径
        api_key: LLM API 密钥（默认环境变量）
        api_url: API 端点（默认环境变量）
        model: LLM 模型（默认环境变量）

    Returns:
        决策结果字典
    """
    loader = UTGLoader(utg_path)
    print(f"  [UTG] 加载: {loader.total_steps} 个原始步骤, "
          f"{loader.valid_count} 个有效步骤")

    maker = UTGDecisionMaker(
        api_key=api_key,
        api_url=api_url,
        model=model,
    )
    return maker.decide(loader)
