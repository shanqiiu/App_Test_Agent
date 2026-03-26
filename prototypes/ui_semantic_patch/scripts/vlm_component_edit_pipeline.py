#!/usr/bin/env python3
"""
vlm_component_edit_pipeline.py - 全模型组件级编辑实验流水线

目标：
1. 使用 VLM 解析原图布局，输出结构化组件
2. 使用 VLM 根据指令定位目标组件并生成编辑计划
3. 使用图像编辑大模型按组件区域执行修改（多候选）
4. 使用 VLM 验证候选结果，打分并选择最佳结果
5. 失败时根据验证反馈重规划并重试
"""

import argparse
import base64
import importlib.util
import json
import os
import re
import time
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from PIL import Image, ImageDraw

try:
    from dotenv import load_dotenv
    ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
except ImportError:
    pass


VLM_API_KEY = os.environ.get("VLM_API_KEY")
VLM_API_URL = os.environ.get("VLM_API_URL", "https://api.openai-next.com/v1/chat/completions")
VLM_MODEL = os.environ.get("VLM_MODEL", "gpt-4o")


def encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def get_mime_type(image_path: str) -> str:
    suffix = Path(image_path).suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    return mime_map.get(suffix, "image/png")


def _iter_fenced_blocks(content: str) -> List[str]:
    return [m.group(1).strip() for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", content)]


def _iter_balanced_json_chunks(content: str) -> List[str]:
    chunks: List[str] = []
    start = -1
    stack: List[str] = []
    in_string = False
    escape = False
    for i, ch in enumerate(content):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch in "{[":
            if not stack:
                start = i
            stack.append(ch)
            continue
        if ch in "}]":
            if not stack:
                continue
            opener = stack[-1]
            if (opener == "{" and ch == "}") or (opener == "[" and ch == "]"):
                stack.pop()
                if not stack and start >= 0:
                    chunks.append(content[start : i + 1].strip())
                    start = -1
            else:
                stack.clear()
                start = -1
    return chunks


def extract_json(content: str) -> Any:
    raw = (content or "").strip()
    if not raw:
        raise ValueError("VLM 返回空文本，无法提取 JSON")

    # 1) 直接解析
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 2) 解析 fenced json（可能有多个，逐个尝试）
    for block in _iter_fenced_blocks(raw):
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue

    # 3) 解析平衡括号块（避免贪婪正则误截取）
    # 优先长度更长的块，通常是完整主体
    candidates = _iter_balanced_json_chunks(raw)
    candidates.sort(key=len, reverse=True)
    for chunk in candidates:
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            continue

    preview = raw[:400].replace("\n", "\\n")
    raise ValueError(f"无法提取有效 JSON，响应片段: {preview}")


def _strip_fence(content: str) -> str:
    raw = (content or "").strip()
    if raw.startswith("```"):
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
        if m:
            return m.group(1).strip()
        return re.sub(r"^```(?:json)?\s*", "", raw).rstrip("`").strip()
    return raw


def _salvage_partial_components_payload(content: str, min_components: int = 8) -> Optional[Dict[str, Any]]:
    """
    当 VLM 返回被截断时，尽量从 components 数组中提取已闭合对象。
    仅用于布局阶段的容错恢复。
    """
    raw = _strip_fence(content)
    key_pos = raw.find('"components"')
    if key_pos < 0:
        return None
    arr_pos = raw.find("[", key_pos)
    if arr_pos < 0:
        return None

    objs: List[Dict[str, Any]] = []
    i = arr_pos + 1
    n = len(raw)
    in_string = False
    escape = False
    depth = 0
    obj_start = -1
    while i < n:
        ch = raw[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
            i += 1
            continue
        if ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and obj_start >= 0:
                    chunk = raw[obj_start : i + 1]
                    try:
                        obj = json.loads(chunk)
                        if isinstance(obj, dict):
                            objs.append(obj)
                    except Exception:
                        pass
                    obj_start = -1
            i += 1
            continue
        if ch == "]" and depth == 0:
            break
        i += 1

    if len(objs) < min_components:
        return None
    return {
        "components": objs,
        "reasoning_summary": "partial_salvage_from_truncated_vlm_response",
    }


def load_generate_image_dashscope():
    module_path = Path(__file__).parent / "utils" / "semantic_dialog_generator.py"
    spec = importlib.util.spec_from_file_location("semantic_dialog_generator", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 semantic_dialog_generator.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.generate_image_dashscope


@dataclass
class LayoutComponent:
    component_id: int
    component_type: str
    text: str
    interactive: bool
    confidence: float
    bbox_norm: Dict[str, float]
    bbox_abs: Dict[str, int]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _read_image_size(path: str) -> Tuple[int, int]:
    with Image.open(path) as img:
        return img.size


def _norm_to_abs(bbox_norm: Dict[str, Any], w: int, h: int) -> Dict[str, int]:
    x = int(round(_clamp(float(bbox_norm.get("x", 0.0)), 0.0, 1.0) * w))
    y = int(round(_clamp(float(bbox_norm.get("y", 0.0)), 0.0, 1.0) * h))
    bw = int(round(_clamp(float(bbox_norm.get("width", 0.1)), 0.0, 1.0) * w))
    bh = int(round(_clamp(float(bbox_norm.get("height", 0.1)), 0.0, 1.0) * h))
    bw = max(1, min(bw, w - x))
    bh = max(1, min(bh, h - y))
    return {"x": x, "y": y, "width": bw, "height": bh}


def _extract_json_list(content: str) -> List[Dict[str, Any]]:
    raw = extract_json(content)
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        return raw["items"]
    raise ValueError("无法解析为 JSON 数组")


def _call_vlm_json(
    image_path: str,
    prompt: str,
    api_key: str,
    api_url: str,
    model: str,
    system_prompt: Optional[str] = None,
    max_tokens: int = 3000,
    temperature: float = 0.2,
    retries: int = 2,
    allow_partial_components: bool = False,
) -> Dict[str, Any]:
    image_base64 = encode_image(image_path)
    mime_type = get_mime_type(image_path)
    messages: List[Dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append(
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_base64}"}},
                {"type": "text", "text": prompt},
            ],
        }
    )
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    last_err = ""
    for i in range(retries + 1):
        try:
            resp = requests.post(api_url, headers=headers, json=payload, timeout=180)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            # 明显截断（常见于 max_tokens 不足）：优先触发重试而不是直接报解析失败
            if (
                ("```json" in content and "```" not in content.split("```json", 1)[1])
                or (content.count("{") > content.count("}") + 8)
                or (content.count("[") > content.count("]") + 8)
            ):
                raise ValueError("VLM 返回疑似截断 JSON（未闭合）")
            try:
                return extract_json(content)
            except Exception:
                if allow_partial_components:
                    partial = _salvage_partial_components_payload(content)
                    if partial is not None:
                        return partial
                # JSON 格式不稳定时，追加一次“修复为严格 JSON”调用
                repair_payload = {
                    "model": model,
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "请将下面文本修复为严格合法的 JSON，并且只输出 JSON，不要任何解释。\n\n"
                                f"{content}"
                            ),
                        }
                    ],
                    "temperature": 0.0,
                    "max_tokens": max_tokens,
                }
                repair_resp = requests.post(api_url, headers=headers, json=repair_payload, timeout=120)
                repair_resp.raise_for_status()
                repaired = repair_resp.json()["choices"][0]["message"]["content"]
                if (
                    ("```json" in repaired and "```" not in repaired.split("```json", 1)[1])
                    or (repaired.count("{") > repaired.count("}") + 8)
                    or (repaired.count("[") > repaired.count("]") + 8)
                ):
                    raise ValueError("修复结果仍疑似截断 JSON（未闭合）")
                try:
                    return extract_json(repaired)
                except Exception:
                    if allow_partial_components:
                        partial = _salvage_partial_components_payload(repaired)
                        if partial is not None:
                            return partial
                    raise
        except Exception as exc:
            last_err = str(exc)
            if i < retries:
                time.sleep(3 * (i + 1))
            else:
                raise RuntimeError(f"VLM 调用失败: {last_err}")
    raise RuntimeError(f"VLM 调用失败: {last_err}")


class VLMComponentEditPipeline:
    def __init__(self, api_key: str, api_url: str, vlm_model: str):
        self.api_key = api_key
        self.api_url = api_url
        self.vlm_model = vlm_model
        self._image_edit_fn = None

    def parse_layout(self, screenshot_path: str) -> Dict[str, Any]:
        w, h = _read_image_size(screenshot_path)
        prompt = f"""请解析这张 App 截图的布局，输出可用于后续精确编辑的组件列表。

输出要求（严格 JSON 对象）：
{{
  "components": [
    {{
      "component_id": 0,
      "component_type": "Button/Text/Card/Image/Tab/ListItem/Input/Dialog/Other",
      "text": "组件主要文字，没有则空字符串",
      "interactive": true,
      "confidence": 0.0,
      "bbox_norm": {{"x":0.1,"y":0.2,"width":0.3,"height":0.1}}
    }}
  ],
  "reasoning_summary": "简要定位依据（1-3 句）"
}}

约束：
1) bbox_norm 坐标范围必须在 [0,1]。
2) 组件尽量覆盖核心可编辑对象（文字块、按钮、卡片、价格、标签）。
3) 输出 30-60 个组件，优先保留可编辑价值高的组件。
4) 必须输出紧凑 JSON（单行或少量换行），不要 markdown 代码块，不要解释文字。
当前图像分辨率：{w}x{h}
"""
        # 布局输出容易超长，做分级重试：先高质量，再压缩组件数量
        last_exc: Optional[Exception] = None
        retry_prompts = [
            (prompt, 2400),
            (
                prompt
                + "\n补充限制：最多 40 个组件；text 字段最多 20 字符；reasoning_summary 最多 40 字。",
                1800,
            ),
            (
                prompt
                + "\n补充限制：最多 30 个组件；禁止输出无文本且不可交互的小装饰元素；只保留关键编辑对象。",
                1400,
            ),
        ]
        result: Dict[str, Any] = {}
        for p, token_limit in retry_prompts:
            try:
                result = _call_vlm_json(
                    image_path=screenshot_path,
                    prompt=p,
                    api_key=self.api_key,
                    api_url=self.api_url,
                    model=self.vlm_model,
                    max_tokens=token_limit,
                    temperature=0.1,
                    retries=1,
                    allow_partial_components=True,
                )
                if len(result.get("components", [])) < 8:
                    raise ValueError("布局组件数量过少，判定为无效输出")
                break
            except Exception as exc:
                last_exc = exc
                continue
        if not result:
            raise RuntimeError(f"布局解析失败（多轮重试后仍失败）: {last_exc}")
        comps_raw = result.get("components", [])
        comps: List[LayoutComponent] = []
        for i, c in enumerate(comps_raw):
            cid = int(c.get("component_id", i))
            bbox_norm = c.get("bbox_norm", {})
            bbox_abs = _norm_to_abs(bbox_norm, w, h)
            comps.append(
                LayoutComponent(
                    component_id=cid,
                    component_type=str(c.get("component_type", "Other"))[:40],
                    text=str(c.get("text", ""))[:120],
                    interactive=bool(c.get("interactive", False)),
                    confidence=float(_clamp(float(c.get("confidence", 0.5)), 0.0, 1.0)),
                    bbox_norm={
                        "x": _clamp(float(bbox_norm.get("x", 0.0)), 0.0, 1.0),
                        "y": _clamp(float(bbox_norm.get("y", 0.0)), 0.0, 1.0),
                        "width": _clamp(float(bbox_norm.get("width", 0.1)), 0.0, 1.0),
                        "height": _clamp(float(bbox_norm.get("height", 0.1)), 0.0, 1.0),
                    },
                    bbox_abs=bbox_abs,
                )
            )
        return {"components": [asdict(c) for c in comps], "reasoning_summary": result.get("reasoning_summary", "")}

    def plan_target_components(
        self,
        screenshot_path: str,
        instruction: str,
        components: List[Dict[str, Any]],
        verifier_feedback: str = "",
    ) -> Dict[str, Any]:
        slim = [
            {
                "component_id": c["component_id"],
                "component_type": c["component_type"],
                "text": c["text"],
                "interactive": c["interactive"],
                "confidence": c["confidence"],
                "bbox_norm": c["bbox_norm"],
            }
            for c in components
        ]
        prompt = f"""你是 UI 组件编辑规划器。基于截图和组件列表，按用户指令选择目标组件并给出编辑计划。

用户指令：
{instruction}

组件列表（JSON）：
{json.dumps(slim, ensure_ascii=False)}

上轮验证反馈（可为空）：
{verifier_feedback or "无"}

请输出严格 JSON：
{{
  "target_component_ids": [1,2],
  "operations": [
    {{
      "component_id": 1,
      "edit_goal": "要修改的目标说明",
      "text_changes": [{{"from":"有票","to":"无票"}}],
      "style_constraints": ["保持字号和字体风格一致","不修改组件外像素"]
    }}
  ],
  "reasoning_summary": "1-3句简要解释为什么选这些组件"
}}

规则：
1) 仅选择与指令强相关的组件，避免过度修改。
2) text_changes.from 必须尽量接近图中真实文本。
3) 若指令提到按钮禁用/变灰，需在 style_constraints 中显式加入。
4) 只输出 JSON。
"""
        result = _call_vlm_json(
            image_path=screenshot_path,
            prompt=prompt,
            api_key=self.api_key,
            api_url=self.api_url,
            model=self.vlm_model,
            max_tokens=3000,
            temperature=0.2,
        )
        target_ids = [int(x) for x in result.get("target_component_ids", [])]
        operations = result.get("operations", [])
        return {
            "target_component_ids": target_ids,
            "operations": operations,
            "reasoning_summary": result.get("reasoning_summary", ""),
        }

    def _blend_edges(self, edited_crop: Image.Image, original_crop: Image.Image, feather_px: int = 3) -> Image.Image:
        if feather_px <= 0:
            return edited_crop
        w, h = edited_crop.size
        if w < 2 * feather_px + 1 or h < 2 * feather_px + 1:
            return edited_crop
        mask = Image.new("L", (w, h), 255)
        draw = ImageDraw.Draw(mask)
        for i in range(feather_px):
            alpha = int(255 * (i + 1) / (feather_px + 1))
            draw.line([(0, i), (w - 1, i)], fill=alpha)
            draw.line([(0, h - 1 - i), (w - 1, h - 1 - i)], fill=alpha)
            draw.line([(i, 0), (i, h - 1)], fill=alpha)
            draw.line([(w - 1 - i, 0), (w - 1 - i, h - 1)], fill=alpha)
        return Image.composite(edited_crop.convert("RGBA"), original_crop.convert("RGBA"), mask)

    def _apply_operation(self, image: Image.Image, op: Dict[str, Any], comp_map: Dict[int, Dict[str, Any]]) -> Image.Image:
        component_id = int(op.get("component_id"))
        comp = comp_map.get(component_id)
        if not comp:
            return image
        b = comp["bbox_abs"]
        x, y, w, h = b["x"], b["y"], b["width"], b["height"]
        img_w, img_h = image.size
        pad = max(8, int(min(w, h) * 0.08))
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(img_w, x + w + pad)
        y2 = min(img_h, y + h + pad)
        cw, ch = x2 - x1, y2 - y1
        if cw <= 0 or ch <= 0:
            return image

        crop = image.crop((x1, y1, x2, y2)).convert("RGB")
        edit_goal = str(op.get("edit_goal", "")).strip()
        text_changes = op.get("text_changes", [])
        constraints = op.get("style_constraints", [])
        lines = [
            "请精确编辑这张局部 UI 图。",
            f"编辑目标：{edit_goal or '按指令修改目标组件'}",
            "文字修改：",
        ]
        for tc in text_changes:
            lines.append(f'- 将 "{tc.get("from", "")}" 改为 "{tc.get("to", "")}"')
        if constraints:
            lines.append("约束：")
            for c in constraints:
                lines.append(f"- {c}")
        lines.extend(
            [
                "- 除目标内容外，其他像素、布局、图标、边框、颜色风格保持不变",
                "- 输出尺寸与输入一致",
            ]
        )
        edit_prompt = "\n".join(lines)

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                temp_path = tmp.name
            crop.save(temp_path, "PNG")
            if self._image_edit_fn is None:
                self._image_edit_fn = load_generate_image_dashscope()
            edited_crop = self._image_edit_fn(
                prompt=edit_prompt,
                size=f"{cw}*{ch}",
                reference_image_path=temp_path,
                force_model="edit",
                prompt_extend=False,
            )
            if edited_crop is None:
                return image
            edited_crop = edited_crop.convert("RGBA")
            if edited_crop.size != (cw, ch):
                edited_crop = edited_crop.resize((cw, ch), Image.Resampling.LANCZOS)
            original_crop = image.crop((x1, y1, x2, y2)).convert("RGBA")
            blended = self._blend_edges(edited_crop, original_crop, feather_px=max(2, pad // 3))
            output = image.copy()
            output.paste(blended, (x1, y1), blended)
            return output
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def generate_candidates(
        self,
        screenshot_path: str,
        components: List[Dict[str, Any]],
        plan: Dict[str, Any],
        candidate_count: int,
        output_dir: Path,
    ) -> List[Dict[str, Any]]:
        comp_map = {int(c["component_id"]): c for c in components}
        base = Image.open(screenshot_path).convert("RGBA")
        ops = plan.get("operations", [])
        results: List[Dict[str, Any]] = []
        for i in range(candidate_count):
            img = base.copy()
            for op in ops:
                img = self._apply_operation(img, op, comp_map)
            cand_path = output_dir / f"candidate_{i+1}.png"
            img.convert("RGB").save(cand_path)
            results.append({"candidate_index": i + 1, "path": str(cand_path)})
        return results

    def verify_candidate(
        self,
        original_path: str,
        edited_path: str,
        instruction: str,
        plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        plan_text = json.dumps(plan.get("operations", []), ensure_ascii=False)
        prompt = f"""你是 UI 编辑验收器。请比较原图与编辑后图，判断是否按指令完成且未破坏无关区域。

用户指令：
{instruction}

计划操作（供参考）：
{plan_text}

输出严格 JSON：
{{
  "score": 0-100,
  "instruction_fulfillment": 0-100,
  "target_accuracy": 0-100,
  "layout_preservation": 0-100,
  "verdict": "pass/fail",
  "issues": ["问题1","问题2"],
  "improvement_suggestion": "下一轮改进建议"
}}

评分准则：
- 指令命中与目标区域准确性优先；
- 误改无关区域严重扣分；
- 只输出 JSON。
"""
        # 双图输入
        orig_b64 = encode_image(original_path)
        edit_b64 = encode_image(edited_path)
        orig_mime = get_mime_type(original_path)
        edit_mime = get_mime_type(edited_path)
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.vlm_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "第一张是原图，第二张是编辑后图。"},
                        {"type": "image_url", "image_url": {"url": f"data:{orig_mime};base64,{orig_b64}"}},
                        {"type": "image_url", "image_url": {"url": f"data:{edit_mime};base64,{edit_b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "temperature": 0.1,
            "max_tokens": 1800,
        }
        resp = requests.post(self.api_url, headers=headers, json=payload, timeout=180)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = extract_json(content)
        return {
            "score": int(data.get("score", 0)),
            "instruction_fulfillment": int(data.get("instruction_fulfillment", 0)),
            "target_accuracy": int(data.get("target_accuracy", 0)),
            "layout_preservation": int(data.get("layout_preservation", 0)),
            "verdict": str(data.get("verdict", "fail")),
            "issues": data.get("issues", []),
            "improvement_suggestion": str(data.get("improvement_suggestion", "")),
        }

    def run(
        self,
        screenshot_path: str,
        instruction: str,
        output_dir: str,
        max_rounds: int = 2,
        candidate_count: int = 3,
    ) -> Dict[str, Any]:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = out / f"vlm_component_edit_{stamp}"
        run_dir.mkdir(parents=True, exist_ok=True)

        meta: Dict[str, Any] = {
            "screenshot": screenshot_path,
            "instruction": instruction,
            "run_dir": str(run_dir),
            "rounds": [],
            "best_result": {},
        }

        # Stage 1: Layout parse
        layout = self.parse_layout(screenshot_path)
        layout_path = run_dir / "stage1_layout.json"
        layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
        components = layout["components"]

        best_global: Optional[Dict[str, Any]] = None
        feedback = ""
        for r in range(1, max_rounds + 1):
            round_dir = run_dir / f"round_{r}"
            round_dir.mkdir(parents=True, exist_ok=True)

            plan = self.plan_target_components(
                screenshot_path=screenshot_path,
                instruction=instruction,
                components=components,
                verifier_feedback=feedback,
            )
            plan_path = round_dir / "stage2_plan.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

            candidates = self.generate_candidates(
                screenshot_path=screenshot_path,
                components=components,
                plan=plan,
                candidate_count=candidate_count,
                output_dir=round_dir,
            )

            verify_rows: List[Dict[str, Any]] = []
            for cand in candidates:
                verify = self.verify_candidate(
                    original_path=screenshot_path,
                    edited_path=cand["path"],
                    instruction=instruction,
                    plan=plan,
                )
                verify_rows.append({"candidate_index": cand["candidate_index"], "path": cand["path"], "verify": verify})

            verify_rows.sort(key=lambda x: x["verify"]["score"], reverse=True)
            best_round = verify_rows[0] if verify_rows else None
            if best_round:
                feedback = best_round["verify"].get("improvement_suggestion", "")

            round_meta = {
                "round_index": r,
                "plan": plan,
                "candidates": verify_rows,
                "best_round": best_round,
            }
            (round_dir / "stage4_verification.json").write_text(
                json.dumps(round_meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            meta["rounds"].append(round_meta)

            if best_round and (best_global is None or best_round["verify"]["score"] > best_global["verify"]["score"]):
                best_global = best_round

            if best_round and best_round["verify"].get("verdict") == "pass":
                break

        meta["best_result"] = best_global or {}
        if best_global:
            final_path = run_dir / "final_best.png"
            Image.open(best_global["path"]).save(final_path)
            meta["best_result"]["final_path"] = str(final_path)

        meta_path = run_dir / "pipeline_meta.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta


def main() -> None:
    parser = argparse.ArgumentParser(
        description="全模型组件级编辑实验流水线（Layout -> Plan -> Edit -> Verify）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
python vlm_component_edit_pipeline.py \
  --screenshot ../data/原图/12306无票/微信图片_20260320112201_63_1364.jpg \
  --instruction "将所有有票状态改为无票，并把可点击按钮改成灰色禁用态" \
  --output ./output
""",
    )
    parser.add_argument("--screenshot", "-s", required=True, help="原始截图路径")
    parser.add_argument("--instruction", "-i", required=True, help="编辑指令")
    parser.add_argument("--output", "-o", default="./output", help="输出目录")
    parser.add_argument("--api-key", default=VLM_API_KEY, help="VLM API Key")
    parser.add_argument("--api-url", default=VLM_API_URL, help="VLM API URL")
    parser.add_argument("--vlm-model", default=VLM_MODEL, help="VLM 模型")
    parser.add_argument("--max-rounds", type=int, default=2, help="最大重试轮次")
    parser.add_argument("--candidate-count", type=int, default=3, help="每轮候选图数量")
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("未设置 VLM_API_KEY")
    if not os.environ.get("DASHSCOPE_API_KEY"):
        raise SystemExit("未设置 DASHSCOPE_API_KEY（图像编辑模型必需）")

    pipeline = VLMComponentEditPipeline(
        api_key=args.api_key,
        api_url=args.api_url,
        vlm_model=args.vlm_model,
    )
    result = pipeline.run(
        screenshot_path=args.screenshot,
        instruction=args.instruction,
        output_dir=args.output,
        max_rounds=max(1, args.max_rounds),
        candidate_count=max(1, args.candidate_count),
    )
    print("=" * 60)
    print("VLM Component Edit Pipeline 完成")
    print("=" * 60)
    print(f"run_dir: {result.get('run_dir')}")
    best = result.get("best_result") or {}
    if best:
        print(f"best_score: {best.get('verify', {}).get('score')}")
        print(f"final_image: {best.get('final_path', best.get('path'))}")
    else:
        print("未生成有效候选结果")


if __name__ == "__main__":
    main()
