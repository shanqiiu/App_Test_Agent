"""
UTG Anomaly Injector — 独立异常注入决策与 ui_summary 改写模块

基于输入的异常场景文本描述 + utg_info.json，实现：
1. LLM 决策：在序列的哪一步注入该异常最合理
2. LLM 改写：将该步的 ui_summary 改写为异常状态描述
3. 输出：完整的修改后 utg_info.json

与 UTGDecisionMaker 的区别：
- UTGDecisionMaker 只决策注入点 + 异常类型，不修改 utg.json 内容
- UTGAnomalyInjector 以改写 ui_summary 为核心产出，输出完整的修改后 utg_info.json

使用方式：
    from app.injection.utg_anomaly_injector import UTGAnomalyInjector

    injector = UTGAnomalyInjector()
    result = injector.inject(
        utg_path="path/to/utg_info.json",
        anomaly_scenario="搜索列表第一条数据加载失败，显示空白占位",
    )
    # result["modified_utg"] 即为修改后的完整 utg_info.json
    injector.save(result["modified_utg"], "path/to/output.json")
"""

import importlib.util
import json
import logging
import os
import re
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Any

import requests

logger = logging.getLogger(__name__)


# ── 独立模块加载器 ────────────────────────────────────────
# 避免通过 app.injection.__init__ 间接导入（该 init 会级联导入其他有
# 外部依赖的模块）。直接从文件路径加载 sibling 模块，实现真正的独立导入。

def _load_sibling_module(module_name: str, filename: str):
    """从同一目录按文件路径加载模块，不触发 package __init__"""
    module_dir = Path(__file__).resolve().parent
    filepath = module_dir / filename
    if not filepath.exists():
        raise ImportError(
            f"无法加载 sibling 模块 {module_name}: {filepath} 不存在"
        )
    spec = importlib.util.spec_from_file_location(module_name, str(filepath))
    mod = importlib.util.module_from_spec(spec)
    # 设置 __package__ 以便相对导入正常工作（utg_loader.py 内部无相对导入，安全）
    mod.__package__ = __package__ or "app.injection"
    spec.loader.exec_module(mod)
    return mod


# 延迟加载 UTGLoader（在 inject() 首次调用前不会触发）
_utg_loader_mod = None


def _get_utg_loader():
    global _utg_loader_mod
    if _utg_loader_mod is None:
        _utg_loader_mod = _load_sibling_module("utg_loader", "utg_loader.py")
    return _utg_loader_mod

# ============================================================
# Prompt 模板
# ============================================================

DECISION_PROMPT = """你是一个 App 异常测试场景生成专家。给定一个 App 操作序列中每步的 UI 状态描述，以及一个待注入的异常场景描述，你需要选择在序列的哪一步注入该异常最合理。

## 异常场景描述
{anomaly_scenario}

## 操作序列 UI 状态描述（按时间顺序）
{steps_text}

## 决策原则
1. 选择与异常场景描述**最自然契合**的步骤——即该步骤的页面类型、用户操作与异常发生的场景匹配度最高
2. 优先选择用户刚完成关键操作后、进入关键页面的时机（如搜索结果页、商品详情页、支付页等）
3. 避免选在首页、加载中状态、纯输入步骤
4. 避免选在序列的末尾步骤（最后一步通常没有后续流程）

## 输出格式（仅返回 JSON，不要其他内容）
{{
  "injection_step": <int, 可选步骤的索引，从 0 开始>,
  "reason": "<string, 选择该步骤的理由>"
}}
"""

REWRITE_PROMPT = """你是一个 App 异常测试场景生成专家。你需要改写 App 操作序列中某一步骤的 UI 描述（ui_summary），使其反映指定的异常场景状态。

改写后的 ui_summary 将用于生成异常 App 截图，因此描述必须准确反映异常在页面上的表现。

## 异常场景描述
{anomaly_scenario}

## 当前步骤的原始信息
- 步骤索引: Step {step_index}
- 操作意图: {thought}
- 操作类型: {action_type}
- 原始 UI 描述: {original_ui_summary}

## 改写要求
1. **保持原有核心页面结构**：页面中的主要元素、布局、功能区域不要凭空删除或添加
2. **自然融入异常状态**：在原始描述的基础上，用自然语言描述异常现象在页面上的具体表现
3. **风格一致**：保持与原始 ui_summary 一致的描述风格——客观、简洁、聚焦于 UI 状态
4. **不改变操作意图**：不要修改 thought / action_type，ui_summary 只是反映当前页面实际看到的状态
5. **具体而非抽象**：不要只说"出现异常"，要描述异常的具体表现（如"商品图片区域显示为灰色占位图"、"价格显示为'--'或'加载失败'"、"按钮文字变为灰色不可点击状态"）

## 输出格式
只输出改写后的 ui_summary 文本，不要包含 JSON 包装、markdown 代码块或其他任何内容。
"""


class LLMClient:
    """
    轻量 LLM 调用客户端

    复用项目已有的 VLM_API_KEY / VLM_API_URL / VLM_MODEL 环境变量配置。
    保持独立实现，不依赖 UTGDecisionMaker。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        timeout: int = 180,
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
            raise ValueError(
                "VLM_API_KEY 未设置。请在 .env 中配置或通过参数传入。"
            )

    def chat(self, prompt: str, max_retries: int = 2) -> str:
        """调用 LLM，返回文本响应"""
        headers = {'Content-Type': 'application/json'}
        headers['Authorization'] = f'Bearer {self.api_key}'

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

        raise RuntimeError(
            f"LLM 调用失败，已重试 {max_retries} 次: {last_error}"
        )

    @staticmethod
    def extract_json(text: str) -> Dict:
        """从 LLM 响应中提取 JSON"""
        # 尝试 ```json ... ``` 代码块
        m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if m:
            return json.loads(m.group(1))

        # 尝试 { ... } 块
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            return json.loads(m.group(0))

        # 直接解析
        return json.loads(text)


class UTGAnomalyInjector:
    """
    UTG 异常注入器

    核心流程：
    1. 加载 utg_info.json → UTGLoader
    2. LLM 决策注入步 → _decide_injection_step()
    3. LLM 改写 ui_summary → _rewrite_ui_summary()
    4. 组装修改后 utg_info.json → _build_modified_utg()

    使用方式：
        injector = UTGAnomalyInjector()
        result = injector.inject(
            utg_path="path/to/utg_info.json",
            anomaly_scenario="搜索列表加载失败，显示网络错误提示",
        )
        print(result["modified_utg"])  # 完整的修改后 utg_info.json
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        llm_timeout: int = 180,
    ):
        self.llm = LLMClient(
            api_key=api_key,
            api_url=api_url,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=llm_timeout,
        )

    def inject(
        self,
        utg_path: str,
        anomaly_scenario: str,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        执行完整的异常注入流程

        Args:
            utg_path: utg_info.json 文件路径
            anomaly_scenario: 异常场景文本描述
            output_path: 可选，输出文件路径（保存修改后的 utg_info.json）

        Returns:
            Dict 包含：
            - success: bool
            - modified_utg: Dict（完整的修改后 utg_info.json）
            - injection_step: int（选中的注入步索引）
            - step_id: str（选中的 stepId）
            - original_ui_summary: str（原始 ui_summary）
            - rewritten_ui_summary: str（改写后的 ui_summary）
            - decision_reason: str（LLM 决策理由）
            - anomaly_scenario: str（输入的异常场景描述）
            - error: Optional[str]
        """
        result = {
            "success": False,
            "modified_utg": None,
            "injection_step": None,
            "step_id": None,
            "original_ui_summary": None,
            "rewritten_ui_summary": None,
            "decision_reason": "",
            "anomaly_scenario": anomaly_scenario,
            "error": None,
        }

        try:
            # Step 1: 加载 UTG
            logger.info(f"加载 UTG: {utg_path}")
            loader = _get_utg_loader().UTGLoader(utg_path)
            valid_steps = loader.get_valid_steps()

            if not valid_steps:
                result["error"] = "utg.json 中没有有效的 ui_summary 步骤"
                return result

            logger.info(f"  有效步骤: {len(valid_steps)} / {loader.total_steps} 总步骤")

            # Step 2: 决策注入步
            logger.info("LLM 决策注入步...")
            decision = self._decide_injection_step(loader, anomaly_scenario)
            injection_step = decision.get("injection_step")
            decision_reason = decision.get("reason", "")

            if injection_step is None or injection_step < 0:
                result["error"] = f"LLM 未返回有效的注入步: {decision}"
                result["decision"] = decision
                return result

            if injection_step >= len(valid_steps):
                result["error"] = (
                    f"LLM 返回的注入步 {injection_step} 超出有效范围 "
                    f"(0-{len(valid_steps) - 1})"
                )
                return result

            target_step = valid_steps[injection_step]
            logger.info(
                f"  ✓ 注入步: Step {injection_step} "
                f"(stepId={target_step.step_id})"
            )
            logger.info(f"  理由: {decision_reason[:120]}")

            # Step 3: 改写 ui_summary
            logger.info("LLM 改写 ui_summary...")
            rewritten = self._rewrite_ui_summary(
                target_step, injection_step, anomaly_scenario
            )
            logger.info(f"  ✓ 改写完成 ({len(rewritten)} chars)")

            # Step 4: 组装修改后 utg
            modified_utg = self._build_modified_utg(
                loader, injection_step, rewritten
            )

            # Step 5: 可选保存
            if output_path:
                self.save(modified_utg, output_path)
                logger.info(f"  ✓ 已保存: {output_path}")

            result["success"] = True
            result["modified_utg"] = modified_utg
            result["injection_step"] = injection_step
            result["step_id"] = target_step.step_id
            result["original_ui_summary"] = target_step.ui_summary
            result["rewritten_ui_summary"] = rewritten
            result["decision_reason"] = decision_reason
            return result

        except Exception as e:
            logger.exception("异常注入流程失败")
            result["error"] = str(e)
            return result

    def _decide_injection_step(
        self,
        loader: "Any",  # UTGLoader — lazy import
        anomaly_scenario: str,
    ) -> Dict:
        """
        LLM 决策注入步

        使用 DECISION_PROMPT，让 LLM 分析序列并选择最自然的注入步骤。
        """
        steps_text = loader.get_summary_text()
        prompt = DECISION_PROMPT.format(
            anomaly_scenario=anomaly_scenario,
            steps_text=steps_text,
        )

        raw = self.llm.chat(prompt)
        parsed = self.llm.extract_json(raw)

        injection_step = parsed.get("injection_step")
        reason = parsed.get("reason", "")

        # 归一化为 int
        if isinstance(injection_step, str):
            # 尝试从 stepId 反查 index
            valid_steps = loader.get_valid_steps()
            for i, s in enumerate(valid_steps):
                if s.step_id == injection_step or str(i) == injection_step:
                    injection_step = i
                    break
            else:
                injection_step = int(injection_step) if injection_step.isdigit() else -1

        return {
            "injection_step": injection_step,
            "reason": reason,
            "raw_response": raw,
        }

    def _rewrite_ui_summary(
        self,
        step: "Any",  # UTGStep — lazy import
        step_index: int,
        anomaly_scenario: str,
    ) -> str:
        """
        LLM 改写指定步骤的 ui_summary

        使用 REWRITE_PROMPT，让 LLM 在保持原始描述风格的基础上，
        融入异常场景描述。
        """
        prompt = REWRITE_PROMPT.format(
            anomaly_scenario=anomaly_scenario,
            step_index=step_index,
            thought=step.thought.strip() if step.thought else "(无)",
            action_type=step.action_type.strip() if step.action_type else "(无)",
            original_ui_summary=step.ui_summary,
        )

        rewritten = self.llm.chat(prompt)

        # 清理：移除可能的 markdown 代码块包裹
        rewritten = rewritten.strip()
        if rewritten.startswith("```") and rewritten.endswith("```"):
            # 移除 ``` 或 ```text ... ```
            rewritten = re.sub(r'^```(?:text|plain|json)?\s*', '', rewritten)
            rewritten = re.sub(r'\s*```$', '', rewritten)
        rewritten = rewritten.strip()

        # 保底：如果改写结果为空，返回原始
        if not rewritten:
            logger.warning("LLM 返回空改写结果，使用原始 ui_summary")
            return step.ui_summary

        return rewritten

    def _build_modified_utg(
        self,
        loader: "Any",  # UTGLoader — lazy import
        injection_step: int,
        rewritten_ui_summary: str,
    ) -> Dict:
        """
        组装修改后的 utg_info.json

        在原始数据基础上，替换目标步骤的 ui_summary。
        """
        valid_steps = loader.get_valid_steps()
        target = valid_steps[injection_step]
        target_step_id = target.step_id

        # 深拷贝原始数据以避免修改引用
        modified = deepcopy(loader._raw)

        # 遍历 stepData，找到匹配 stepId 的项并替换 ui_summary
        replaced = False
        for item in modified.get("stepData", []):
            sid = str(item.get("stepId", ""))
            if sid == target_step_id:
                logger.info(
                    f"  替换 stepId={sid} 的 ui_summary: "
                    f"({len(item.get('ui_summary',''))} → {len(rewritten_ui_summary)} chars)"
                )
                item["ui_summary"] = rewritten_ui_summary
                replaced = True
                break

        if not replaced:
            # 保底：按 valid_steps 的顺序匹配
            valid_idx = 0
            for item in modified.get("stepData", []):
                sid = str(item.get("stepId", ""))
                if not sid.lower() in {"home", "end", "start"} and item.get("ui_summary", "").strip():
                    if valid_idx == injection_step:
                        item["ui_summary"] = rewritten_ui_summary
                        replaced = True
                        break
                    valid_idx += 1

        if not replaced:
            logger.warning(
                f"未找到 stepId={target_step_id} 的原始项，ui_summary 可能未修改"
            )

        return modified

    @staticmethod
    def save(modified_utg: Dict, output_path: str) -> str:
        """
        保存修改后的 utg_info.json 到文件

        Args:
            modified_utg: 修改后的 utg_info.json dict
            output_path: 输出文件路径

        Returns:
            实际写入的文件路径
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(modified_utg, f, ensure_ascii=False, indent=2)
        return str(path)


def run_anomaly_inject(
    utg_path: str,
    anomaly_scenario: str,
    output_path: Optional[str] = None,
    api_key: Optional[str] = None,
    api_url: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    便捷函数：一键执行异常注入

    Args:
        utg_path: utg_info.json 文件路径
        anomaly_scenario: 异常场景文本描述
        output_path: 可选，输出文件路径
        api_key: VLM API Key，默认从环境变量读取
        api_url: VLM API URL，默认从环境变量读取
        model: VLM 模型名，默认从环境变量读取

    Returns:
        UTGAnomalyInjector.inject() 的返回结果
    """
    injector = UTGAnomalyInjector(
        api_key=api_key,
        api_url=api_url,
        model=model,
    )
    return injector.inject(
        utg_path=utg_path,
        anomaly_scenario=anomaly_scenario,
        output_path=output_path,
    )
