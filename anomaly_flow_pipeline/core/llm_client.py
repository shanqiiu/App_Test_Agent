"""
llm_client.py — 独立 LLM 调用客户端

复用项目已有的 VLM_API_KEY / VLM_API_URL / VLM_MODEL 环境变量配置。
纯 requests 实现，无外部 SDK 依赖。
"""

import json
import logging
import os
import re
import time
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)


class LLMClient:
    """轻量 LLM 调用客户端"""

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
        """从 LLM 响应中提取 JSON，带自动修复"""

        def _clean_json(raw: str) -> str:
            raw = re.sub(r'^```(?:json)?\s*', '', raw.strip())
            raw = re.sub(r'\s*```$', '', raw.strip())
            brace_start = raw.find('{')
            brace_end = raw.rfind('}')
            if brace_start >= 0 and brace_end > brace_start:
                raw = raw[brace_start:brace_end + 1]
            raw = re.sub(r',\s*}', '}', raw)
            raw = re.sub(r',\s*]', ']', raw)
            return raw

        raw = _clean_json(text)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            try:
                raw = raw.replace("'", '"')
                return json.loads(raw)
            except json.JSONDecodeError:
                m = re.search(r'"page_types"\s*:\s*(\[[\s\S]*?\])', raw)
                if m:
                    partial = '{"page_types": ' + m.group(1) + '}'
                    return json.loads(partial)
                raise
