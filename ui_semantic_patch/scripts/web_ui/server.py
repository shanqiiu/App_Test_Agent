#!/usr/bin/env python3
"""
web_ui/server.py — Web UI 后端

职责：
1. 保留原有单条 mapping 生成接口
2. 新增 batch_injection_with_mapping.py 的可视化运行接口
3. 提供本地输出图片的只读访问，供前端预览生成结果
"""

import argparse
import asyncio
import json
import mimetypes
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
import uvicorn

# 路径和 .env
_WEB_UI_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _WEB_UI_DIR.parents[0]
_UI_ROOT = _SCRIPTS_DIR.parent
_PROJECT_ROOT = _UI_ROOT.parent

_GEN_SCRIPT = _SCRIPTS_DIR / "generate_mapping.py"
_BATCH_SCRIPT = _SCRIPTS_DIR / "batch_injection_with_mapping.py"
_BATCH_UTG_SCRIPT = _SCRIPTS_DIR / "batch_utg_injection.py"
_RUN_PIPELINE_SCRIPT = _SCRIPTS_DIR / "run_pipeline.py"
_INJECTION_PIPELINE_SCRIPT = _SCRIPTS_DIR / "injection_pipeline.py"

_DEFAULT_EXAMPLES_DIR = _PROJECT_ROOT / "data" / "examples"
_DEFAULT_UTG_EXAMPLES_DIR = _PROJECT_ROOT / "data" / "examples"
_DEFAULT_OUTPUT_DIR = _SCRIPTS_DIR / "outputs3"
_DEFAULT_SINGLE_OUTPUT_DIR = _SCRIPTS_DIR / "outputs"
_DEFAULT_MAPPING_CONFIG = _UI_ROOT / "config" / "query_anomaly_mapping.json"
_DEFAULT_GT_TEMPLATE_DIR = _PROJECT_ROOT / "data" / "gt-category"
_DEFAULT_SINGLE_SCREENSHOT = _PROJECT_ROOT / "data" / "examples" / "injection_demo_01" / "screenshots" / "09.jpg"

_ALLOWED_FILE_ROOTS = [
    _PROJECT_ROOT.resolve(),
    _UI_ROOT.resolve(),
]

try:
    from dotenv import load_dotenv
    for p in [_UI_ROOT / ".env", _PROJECT_ROOT / ".env"]:
        if p.exists():
            load_dotenv(p)
            break
except ImportError:
    pass


class RunRequest(BaseModel):
    query: str
    fault_mode: str
    app_name: str = ""
    dry_run: bool = False


class RunResponse(BaseModel):
    success: bool
    entry: dict = Field(default_factory=dict)
    anomaly_mode: str = ""
    anomaly_mode_confidence: float = 0.0
    instruction: str = ""
    gt: dict = Field(default_factory=dict)
    logs: list = Field(default_factory=list)
    error: str = ""


class BatchRunRequest(BaseModel):
    examples_dir: str = str(_DEFAULT_EXAMPLES_DIR)
    output_dir: str = str(_DEFAULT_OUTPUT_DIR)
    mapping_config: str = str(_DEFAULT_MAPPING_CONFIG)
    gt_template_dir: str = str(_DEFAULT_GT_TEMPLATE_DIR)
    fault_mode: str = ""
    enable_verification: bool = False
    quality_threshold: float = 6.0
    verification_retries: int = 2
    enable_rules: bool = True


class BatchRunResponse(BaseModel):
    success: bool
    summary: dict = Field(default_factory=dict)
    runs: list = Field(default_factory=list)
    logs: list = Field(default_factory=list)
    error: str = ""


class PipelineRunRequest(BaseModel):
    screenshot: str = str(_DEFAULT_SINGLE_SCREENSHOT)
    instruction: str
    output: str = str(_DEFAULT_SINGLE_OUTPUT_DIR / "demo_single")
    anomaly_mode: str = "dialog"
    gt_category: str = ""
    gt_sample: str = ""
    gt_dir: str = ""
    reference: str = ""
    reference_icon: str = ""
    structure_model: str = ""
    target_component: str = ""
    edit_plan: str = ""
    no_visualize: bool = False
    e2e_full_image: bool = False


class PipelineRunResponse(BaseModel):
    success: bool
    summary: dict = Field(default_factory=dict)
    outputs: dict = Field(default_factory=dict)
    logs: list = Field(default_factory=list)
    error: str = ""


class UTGRunRequest(BaseModel):
    example_dir: str = ""       # 示例目录（含 info.json + utg.json）
    screenshots_dir: str = ""   # 截图目录（可选，如 example_dir 下已有则自动发现）
    output: str = ""
    dry_run: bool = False
    task: str = ""
    mapping_config: str = ""
    gt_template_dir: str = ""
    enable_verification: bool = False
    quality_threshold: float = 6.0
    verification_retries: int = 2


class UTGRunResponse(BaseModel):
    success: bool
    decision: dict = Field(default_factory=dict)
    outputs: dict = Field(default_factory=dict)
    logs: list = Field(default_factory=list)
    error: str = ""


app = FastAPI(title="UI Semantic Patch Web UI", version="2.0")


@app.get("/")
async def index():
    html_path = _WEB_UI_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>index.html not found</h1>", status_code=404)


def _resolve_path(path_value: Optional[str], fallback: Path) -> Path:
    if path_value and str(path_value).strip():
        return Path(path_value).expanduser().resolve()
    return fallback.resolve()


def _is_allowed_file(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return any(str(resolved).startswith(str(root)) for root in _ALLOWED_FILE_ROOTS)


def _path_to_url(path: Optional[Path]) -> str:
    if not path:
        return ""
    return f"/api/file?path={quote(str(path.resolve()))}"


def _run_mapping_script(query: str, fault_mode: str, app_name: str, dry_run: bool) -> dict:
    """子进程执行 generate_mapping.py（通过 stdin 传参避免 Windows 命令行编码问题）"""
    input_data = json.dumps(
        {
            "query": query,
            "fault_mode": fault_mode,
            "app_name": app_name,
            "dry_run": dry_run,
        },
        ensure_ascii=False,
    )

    cmd = [
        sys.executable,
        str(_GEN_SCRIPT),
        "--stdin",
        "--output-json",
    ]

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        proc = subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            cwd=str(_SCRIPTS_DIR),
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Mapping generation timed out after 120 seconds",
            "logs": ["[timeout] generate_mapping.py exceeded 120 seconds"],
        }
    except Exception as exc:
        return {
            "success": False,
            "error": f"Failed to run mapping script: {exc}",
            "logs": [f"[exception] {exc}"],
        }

    logs: List[str] = []
    if proc.stdout:
        logs = proc.stdout.strip().splitlines()
    if proc.stderr:
        logs.extend(f"[stderr] {line}" for line in proc.stderr.strip().splitlines())

    if proc.returncode != 0:
        return {
            "success": False,
            "error": f"Script exited with code {proc.returncode}",
            "logs": logs,
        }

    entry = {}
    anomaly_mode = ""
    instruction = ""
    confidence = 0.0
    gt = {}

    try:
        json_marker = -1
        for i, line in enumerate(logs):
            if line.strip() == "__JSON_RESULT__":
                json_marker = i
                break
        if json_marker >= 0 and json_marker + 1 < len(logs):
            data = json.loads(logs[json_marker + 1])
            entry = data
            anomaly_mode = data.get("injection_config", {}).get("anomaly_mode", "")
            instruction = data.get("injection_config", {}).get("instruction", "")
            gt["category"] = data.get("injection_config", {}).get("gt_category", "")
            gt["sample"] = data.get("injection_config", {}).get("gt_sample", "")
    except (json.JSONDecodeError, IndexError):
        pass

    if not anomaly_mode:
        for line in logs:
            if "anomaly_mode:" in line:
                anomaly_mode = line.split("anomaly_mode:")[-1].strip()
                break
    if not instruction:
        for line in logs:
            if "instruction:" in line:
                instruction = line.split("instruction:")[-1].strip()
                break
    if not confidence:
        for line in logs:
            if "confidence:" in line:
                try:
                    confidence = float(line.split("confidence:")[-1].strip().rstrip("%")) / 100.0
                except ValueError:
                    pass

    return {
        "success": True,
        "entry": entry,
        "anomaly_mode": anomaly_mode,
        "anomaly_mode_confidence": confidence,
        "instruction": instruction,
        "gt": gt,
        "logs": logs,
    }


def _get_image_gen_health() -> Dict:
    backend = (os.getenv("IMAGE_GEN_BACKEND", "auto") or "auto").strip().lower()
    if backend not in {"auto", "dashscope", "huawei_mlops", "local"}:
        backend = "auto"

    general_model = os.getenv("IMAGE_GEN_MODEL", "").strip()
    dashscope_gen_model = os.getenv("DASHSCOPE_IMAGE_GEN_MODEL", "qwen-image-max").strip()
    dashscope_edit_model = os.getenv("DASHSCOPE_IMAGE_EDIT_MODEL", "qwen-image-edit-max").strip()
    huawei_model = os.getenv("HUAWEI_MLOPS_MODEL", "flux_txt_to_image").strip()
    local_api_url = os.getenv("LOCAL_IMAGE_API_URL", "").strip()

    if backend == "dashscope":
        active_model = general_model or dashscope_gen_model
        edit_model = dashscope_edit_model
        available = bool(os.getenv("IMAGE_GEN_API_KEY", "").strip() or os.getenv("DASHSCOPE_API_KEY", "").strip())
    elif backend == "huawei_mlops":
        active_model = huawei_model
        edit_model = huawei_model
        available = bool(os.getenv("HUAWEI_MLOPS_API_KEY", "").strip() or os.getenv("IMAGE_GEN_API_KEY", "").strip())
    elif backend == "local":
        active_model = local_api_url or "local-api"
        edit_model = local_api_url or "local-api"
        available = bool(local_api_url)
    else:
        # auto: 先看本地服务，其次通用/云端配置
        if local_api_url:
            active_model = local_api_url
            edit_model = local_api_url
            available = True
        else:
            active_model = general_model or dashscope_gen_model
            edit_model = dashscope_edit_model
            available = bool(
                os.getenv("IMAGE_GEN_API_KEY", "").strip()
                or os.getenv("DASHSCOPE_API_KEY", "").strip()
                or os.getenv("HUAWEI_MLOPS_API_KEY", "").strip()
            )

    return {
        "available": available,
        "backend": backend,
        "model": active_model,
        "edit_model": edit_model,
        "local_api_url": local_api_url,
    }


def _snapshot_metadata_files(output_dir: Path) -> Set[str]:
    if not output_dir.exists():
        return set()
    return {str(path.resolve()) for path in output_dir.rglob("metadata.json")}


def _snapshot_pipeline_meta_files(output_dir: Path) -> Set[str]:
    if not output_dir.exists():
        return set()
    return {str(path.resolve()) for path in output_dir.rglob("*pipeline_meta*.json")}


def _load_json(path: Path) -> Dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _find_preview_image(run_dir: Path, metadata: Dict) -> Optional[Path]:
    anomaly_dir = run_dir / "anomaly_generated"
    if anomaly_dir.exists():
        finals = sorted(anomaly_dir.glob("final_*.png"))
        if finals:
            return finals[-1]

    for image_path in metadata.get("anomaly_images", []):
        candidate = Path(image_path)
        if candidate.exists():
            return candidate
    return None


def _to_file_payload(path_value: str) -> Dict:
    if not path_value:
        return {"path": "", "url": ""}
    path = Path(path_value)
    return {
        "path": str(path),
        "url": _path_to_url(path) if path.exists() else "",
    }


def _collect_generated_runs(output_dir: Path, before_snapshot: Set[str]) -> List[Dict]:
    if not output_dir.exists():
        return []

    runs: List[Dict] = []
    metadata_files = sorted(
        output_dir.rglob("metadata.json"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )

    for metadata_path in metadata_files:
        if str(metadata_path.resolve()) in before_snapshot:
            continue

        run_dir = metadata_path.parent
        metadata = _load_json(metadata_path)
        decision_log_path = run_dir / "decision_log.json"
        decision_log = _load_json(decision_log_path) if decision_log_path.exists() else {}
        rule_decision = decision_log.get("rule_decision", {}) or {}
        preview_image = _find_preview_image(run_dir, metadata)

        batch_group = run_dir.parent.name
        demo_name = batch_group
        if "_mode_" in batch_group:
            demo_name = batch_group.rsplit("_mode_", 1)[0]

        runs.append(
            {
                "batch_group": batch_group,
                "demo_name": demo_name,
                "run_dir": str(run_dir),
                "run_dir_name": run_dir.name,
                "metadata_path": str(metadata_path),
                "decision_log_path": str(decision_log_path) if decision_log_path.exists() else "",
                "app_name": decision_log.get("app_name", ""),
                "query": decision_log.get("query", ""),
                "fault_mode": decision_log.get("fault_mode", ""),
                "fault_mode_key": decision_log.get("fault_mode_key", ""),
                "anomaly_mode": metadata.get("anomaly_type_normalized") or metadata.get("anomaly_type", ""),
                "instruction": metadata.get("instruction", ""),
                "injection_point": metadata.get("injection_point"),
                "original_length": metadata.get("original_length"),
                "modified_length": metadata.get("modified_length"),
                "generated_images_count": metadata.get("anomaly_images_count", 0),
                "matched_rule_id": rule_decision.get("matched_rule_id", ""),
                "page_type": rule_decision.get("page_type", ""),
                "match_confidence": rule_decision.get("match_confidence"),
                "preview_image_path": str(preview_image) if preview_image else "",
                "preview_image_url": _path_to_url(preview_image),
            }
        )

    runs.sort(key=lambda item: item["run_dir"], reverse=True)
    return runs


def _extract_batch_counters(logs: List[str]) -> Dict:
    counters = {"success": 0, "failed": 0, "total": 0, "skipped": 0}
    for line in logs:
        stripped = line.strip()
        if "⚠ 跳过:" in stripped:
            counters["skipped"] += 1
            continue
        match = re.match(r"^(成功|失败|总计):\s*(\d+)$", stripped)
        if not match:
            continue
        key_map = {"成功": "success", "失败": "failed", "总计": "total"}
        counters[key_map[match.group(1)]] = int(match.group(2))
    return counters


def _run_batch_script(req: BatchRunRequest) -> Dict:
    examples_dir = _resolve_path(req.examples_dir, _DEFAULT_EXAMPLES_DIR)
    output_dir = _resolve_path(req.output_dir, _DEFAULT_OUTPUT_DIR)
    mapping_config = _resolve_path(req.mapping_config, _DEFAULT_MAPPING_CONFIG)
    gt_template_dir = _resolve_path(req.gt_template_dir, _DEFAULT_GT_TEMPLATE_DIR)

    cmd = [
        sys.executable,
        str(_BATCH_SCRIPT),
        "--examples-dir",
        str(examples_dir),
        "--output-dir",
        str(output_dir),
        "--mapping-config",
        str(mapping_config),
        "--gt-template-dir",
        str(gt_template_dir),
        "--quality-threshold",
        str(req.quality_threshold),
        "--verification-retries",
        str(req.verification_retries),
    ]

    if req.fault_mode in {"mode_1", "mode_2"}:
        cmd.extend(["--fault-mode", req.fault_mode])
    if req.enable_verification:
        cmd.append("--enable-verification")
    if not req.enable_rules:
        cmd.append("--no-rules")

    before_snapshot = _snapshot_metadata_files(output_dir)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            cwd=str(_SCRIPTS_DIR),
            timeout=1800,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "summary": {
                "examples_dir": str(examples_dir),
                "output_dir": str(output_dir),
                "mapping_config": str(mapping_config),
                "gt_template_dir": str(gt_template_dir),
                "fault_mode": req.fault_mode or "all",
                "enable_verification": req.enable_verification,
                "enable_rules": req.enable_rules,
                "quality_threshold": req.quality_threshold,
                "verification_retries": req.verification_retries,
                "produced_runs": 0,
                "success": 0,
                "failed": 0,
                "total": 0,
                "skipped": 0,
            },
            "runs": [],
            "logs": ["[timeout] batch_injection_with_mapping.py exceeded 1800 seconds"],
            "error": "Batch generation timed out after 1800 seconds",
        }
    except Exception as exc:
        return {
            "success": False,
            "summary": {
                "examples_dir": str(examples_dir),
                "output_dir": str(output_dir),
                "mapping_config": str(mapping_config),
                "gt_template_dir": str(gt_template_dir),
                "fault_mode": req.fault_mode or "all",
                "enable_verification": req.enable_verification,
                "enable_rules": req.enable_rules,
                "quality_threshold": req.quality_threshold,
                "verification_retries": req.verification_retries,
                "produced_runs": 0,
                "success": 0,
                "failed": 0,
                "total": 0,
                "skipped": 0,
            },
            "runs": [],
            "logs": [f"[exception] {exc}"],
            "error": f"Failed to run batch script: {exc}",
        }

    logs: List[str] = []
    if proc.stdout:
        logs.extend(proc.stdout.strip().splitlines())
    if proc.stderr:
        logs.extend(f"[stderr] {line}" for line in proc.stderr.strip().splitlines())

    runs = _collect_generated_runs(output_dir, before_snapshot)
    counters = _extract_batch_counters(logs)

    summary = {
        "examples_dir": str(examples_dir),
        "output_dir": str(output_dir),
        "mapping_config": str(mapping_config),
        "gt_template_dir": str(gt_template_dir),
        "fault_mode": req.fault_mode or "all",
        "enable_verification": req.enable_verification,
        "enable_rules": req.enable_rules,
        "quality_threshold": req.quality_threshold,
        "verification_retries": req.verification_retries,
        "produced_runs": len(runs),
        **counters,
    }

    success = proc.returncode == 0
    error = ""
    if not success:
        error = f"Script exited with code {proc.returncode}"

    return {
        "success": success,
        "summary": summary,
        "runs": runs,
        "logs": logs,
        "error": error,
    }


# ---------------------------------------------------------------------------
# 流式版本：batch 生成实时日志推送
# ---------------------------------------------------------------------------

def _build_batch_cmd(req: BatchRunRequest, examples_dir: Path, output_dir: Path,
                     mapping_config: Path, gt_template_dir: Path) -> List[str]:
    """构建 batch_injection_with_mapping.py 的命令行参数"""
    cmd = [
        sys.executable,
        str(_BATCH_SCRIPT),
        "--examples-dir", str(examples_dir),
        "--output-dir", str(output_dir),
        "--mapping-config", str(mapping_config),
        "--gt-template-dir", str(gt_template_dir),
        "--quality-threshold", str(req.quality_threshold),
        "--verification-retries", str(req.verification_retries),
    ]
    if req.fault_mode in {"mode_1", "mode_2"}:
        cmd.extend(["--fault-mode", req.fault_mode])
    if req.enable_verification:
        cmd.append("--enable-verification")
    if not req.enable_rules:
        cmd.append("--no-rules")
    return cmd


async def _stream_subprocess_lines(proc: asyncio.subprocess.Process,
                                    websocket: WebSocket) -> List[str]:
    """逐行读取子进程 stdout 并通过 WebSocket 推送"""
    collected: List[str] = []
    while True:
        line_bytes = await proc.stdout.readline()
        if not line_bytes:
            break
        line = line_bytes.decode("utf-8", errors="replace").rstrip("\n").rstrip("\r")
        collected.append(line)
        try:
            await websocket.send_json({"type": "log", "line": line})
        except Exception:
            # 客户端断开连接时，直接终止子进程
            proc.kill()
            raise
    return collected


async def _run_batch_script_streaming(req: BatchRunRequest, websocket: WebSocket):
    """流式执行 batch_injection_with_mapping.py，通过 WebSocket 实时回传每行输出"""
    examples_dir = _resolve_path(req.examples_dir, _DEFAULT_EXAMPLES_DIR)
    output_dir = _resolve_path(req.output_dir, _DEFAULT_OUTPUT_DIR)
    mapping_config = _resolve_path(req.mapping_config, _DEFAULT_MAPPING_CONFIG)
    gt_template_dir = _resolve_path(req.gt_template_dir, _DEFAULT_GT_TEMPLATE_DIR)
    cmd = _build_batch_cmd(req, examples_dir, output_dir, mapping_config, gt_template_dir)

    before_snapshot = _snapshot_metadata_files(output_dir)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    # 步骤 b1 → 配置加载完成
    await websocket.send_json({"type": "status", "step": "b1", "status": "success"})
    await websocket.send_json({"type": "status", "step": "b2", "status": "running"})

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(_SCRIPTS_DIR),
            env=env,
        )
    except Exception as exc:
        await websocket.send_json({
            "type": "error",
            "message": f"Failed to start batch script: {exc}",
        })
        return

    try:
        collected = await _stream_subprocess_lines(proc, websocket)
    except (WebSocketDisconnect, ConnectionResetError):
        try:
            proc.kill()
        except Exception:
            pass
        return
    finally:
        await proc.wait()

    # 步骤 b4 → 汇总中
    await websocket.send_json({"type": "status", "step": "b4", "status": "running"})

    # 从日志中解析语义分析 / 注入阶段的行，更新步骤状态
    for line in collected:
        if "语义分析" in line:
            await websocket.send_json({"type": "status", "step": "b2", "status": "success"})
            await websocket.send_json({"type": "status", "step": "b3", "status": "running"})
        elif "批量处理完成" in line:
            await websocket.send_json({"type": "status", "step": "b3", "status": "success"})

    runs = _collect_generated_runs(output_dir, before_snapshot)
    counters = _extract_batch_counters(collected)

    summary = {
        "examples_dir": str(examples_dir),
        "output_dir": str(output_dir),
        "mapping_config": str(mapping_config),
        "gt_template_dir": str(gt_template_dir),
        "fault_mode": req.fault_mode or "all",
        "enable_verification": req.enable_verification,
        "enable_rules": req.enable_rules,
        "quality_threshold": req.quality_threshold,
        "verification_retries": req.verification_retries,
        "produced_runs": len(runs),
        **counters,
    }

    success = proc.returncode == 0
    error = "" if success else f"Script exited with code {proc.returncode}"

    await websocket.send_json({
        "type": "done",
        "success": success,
        "summary": summary,
        "runs": runs,
        "logs": collected,
        "error": error,
    })

    # 最终步骤状态
    status_map = {("b2", "success"), ("b3", "success"), ("b4", "success" if success else "error")}
    for step, st in status_map:
        await websocket.send_json({"type": "status", "step": step, "status": st})


def _collect_pipeline_result(output_dir: Path, before_snapshot: Set[str]) -> Dict:
    output_dir = output_dir.resolve()
    if not output_dir.exists():
        return {"summary": {}, "outputs": {}}

    candidates = sorted(
        [path for path in output_dir.rglob("*pipeline_meta*.json") if str(path.resolve()) not in before_snapshot],
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )

    if not candidates:
        return {"summary": {}, "outputs": {}}

    meta_path = candidates[0]
    meta = _load_json(meta_path)
    outputs = meta.get("outputs", {}) or {}
    render_metadata = meta.get("render_metadata", {}) or {}
    render_info = render_metadata.get("render_info", {}) or {}

    normalized_outputs = {
        "pipeline_meta": {
            "path": str(meta_path),
            "url": _path_to_url(meta_path),
        }
    }
    for key, value in outputs.items():
        if isinstance(value, str):
            normalized_outputs[key] = _to_file_payload(value)
        else:
            normalized_outputs[key] = {"value": value}

    final_image = outputs.get("final_image", "")
    final_image_path = Path(final_image) if final_image else None

    summary = {
        "timestamp": meta.get("timestamp", ""),
        "screenshot": meta.get("screenshot", ""),
        "instruction": meta.get("instruction", ""),
        "stage2_status": meta.get("stage2_status", ""),
        "timing": meta.get("timing", {}),
        "warnings": meta.get("warnings", []),
        "gt_category": render_metadata.get("gt_category", ""),
        "gt_sample": render_metadata.get("gt_sample", ""),
        "meta_driven": render_metadata.get("meta_driven", False),
        "position_method": render_info.get("position_method", ""),
        "ui_components_count": render_info.get("ui_components_count"),
        "close_button_drawn": render_info.get("close_button_drawn"),
        "dialog_position_type": render_info.get("dialog_position_type", ""),
        "final_image_path": str(final_image_path) if final_image_path else "",
        "final_image_url": _path_to_url(final_image_path) if final_image_path and final_image_path.exists() else "",
        "pipeline_meta_path": str(meta_path),
        "pipeline_meta_url": _path_to_url(meta_path),
    }

    return {
        "summary": summary,
        "outputs": normalized_outputs,
    }


def _run_single_pipeline(req: PipelineRunRequest) -> Dict:
    screenshot = _resolve_path(req.screenshot, _DEFAULT_SINGLE_SCREENSHOT)
    output_dir = _resolve_path(req.output, _DEFAULT_SINGLE_OUTPUT_DIR / "demo_single")

    cmd = [
        sys.executable,
        str(_RUN_PIPELINE_SCRIPT),
        "--screenshot",
        str(screenshot),
        "--instruction",
        req.instruction,
        "--output",
        str(output_dir),
        "--anomaly-mode",
        req.anomaly_mode,
    ]

    if req.gt_category:
        cmd.extend(["--gt-category", req.gt_category])
    if req.gt_sample:
        cmd.extend(["--gt-sample", req.gt_sample])
    if req.gt_dir:
        cmd.extend(["--gt-dir", str(_resolve_path(req.gt_dir, Path(req.gt_dir)))])
    if req.reference:
        cmd.extend(["--reference", str(_resolve_path(req.reference, Path(req.reference)))])
    if req.reference_icon:
        cmd.extend(["--reference-icon", str(_resolve_path(req.reference_icon, Path(req.reference_icon)))])
    if req.structure_model:
        cmd.extend(["--structure-model", req.structure_model])
    if req.target_component:
        cmd.extend(["--target-component", req.target_component])
    if req.edit_plan:
        cmd.extend(["--edit-plan", str(_resolve_path(req.edit_plan, Path(req.edit_plan)))])
    if req.no_visualize:
        cmd.append("--no-visualize")
    if req.e2e_full_image:
        cmd.append("--e2e-full-image")

    before_snapshot = _snapshot_pipeline_meta_files(output_dir)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            cwd=str(_SCRIPTS_DIR),
            timeout=1800,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "summary": {
                "screenshot": str(screenshot),
                "instruction": req.instruction,
                "output_dir": str(output_dir),
                "anomaly_mode": req.anomaly_mode,
            },
            "outputs": {},
            "logs": ["[timeout] run_pipeline.py exceeded 1800 seconds"],
            "error": "Single pipeline generation timed out after 1800 seconds",
        }
    except Exception as exc:
        return {
            "success": False,
            "summary": {
                "screenshot": str(screenshot),
                "instruction": req.instruction,
                "output_dir": str(output_dir),
                "anomaly_mode": req.anomaly_mode,
            },
            "outputs": {},
            "logs": [f"[exception] {exc}"],
            "error": f"Failed to run pipeline script: {exc}",
        }

    logs: List[str] = []
    if proc.stdout:
        logs.extend(proc.stdout.strip().splitlines())
    if proc.stderr:
        logs.extend(f"[stderr] {line}" for line in proc.stderr.strip().splitlines())

    result = _collect_pipeline_result(output_dir, before_snapshot)
    summary = {
        "screenshot": str(screenshot),
        "instruction": req.instruction,
        "output_dir": str(output_dir),
        "anomaly_mode": req.anomaly_mode,
        **result.get("summary", {}),
    }

    success = proc.returncode == 0
    error = ""
    if not success:
        error = f"Script exited with code {proc.returncode}"

    return {
        "success": success,
        "summary": summary,
        "outputs": result.get("outputs", {}),
        "logs": logs,
        "error": error,
    }


@app.post("/api/run", response_model=RunResponse)
async def api_run(req: RunRequest):
    result = _run_mapping_script(
        query=req.query,
        fault_mode=req.fault_mode,
        app_name=req.app_name,
        dry_run=req.dry_run,
    )
    return RunResponse(**result)


@app.post("/api/batch-run", response_model=BatchRunResponse)
async def api_batch_run(req: BatchRunRequest):
    result = _run_batch_script(req)
    return BatchRunResponse(**result)


@app.websocket("/ws/batch-run")
async def ws_batch_run(websocket: WebSocket):
    """WebSocket 端点：实时流式推送 batch 脚本终端输出"""
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        req = BatchRunRequest(**data)
        await _run_batch_script_streaming(req, websocket)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Batch streaming failed: {exc}",
            })
        except Exception:
            pass


@app.post("/api/pipeline-run", response_model=PipelineRunResponse)
async def api_pipeline_run(req: PipelineRunRequest):
    result = _run_single_pipeline(req)
    return PipelineRunResponse(**result)


class UTGBatchRequest(BaseModel):
    examples_dir: str = str(_DEFAULT_UTG_EXAMPLES_DIR)
    mapping_config: str = str(_DEFAULT_MAPPING_CONFIG)
    output_dir: str = str(_DEFAULT_OUTPUT_DIR / "utg_batch")
    gt_template_dir: str = ""
    dry_run: bool = False


@app.websocket("/ws/utg-batch-run")
async def ws_utg_batch_run(websocket: WebSocket):
    """WebSocket 端点：实时流式推送 UTG 批量脚本输出"""
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        req = UTGBatchRequest(**data)
        await _run_utg_batch_streaming(req, websocket)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass


async def _run_utg_batch_streaming(req: UTGBatchRequest, websocket: WebSocket):
    examples_dir = _resolve_path(Path(req.examples_dir), _DEFAULT_UTG_EXAMPLES_DIR)
    mapping_config = _resolve_path(Path(req.mapping_config), Path("tmp/mapping.json"))
    output_dir = _resolve_path(Path(req.output_dir), _DEFAULT_OUTPUT_DIR / "utg_batch")
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, str(_BATCH_UTG_SCRIPT),
        "--examples-dir", str(examples_dir),
        "--mapping-config", str(mapping_config),
        "--output-dir", str(output_dir),
    ]
    if req.dry_run:
        cmd.append("--dry-run")
    if req.gt_template_dir:
        cmd.extend(["--gt-template-dir", str(Path(req.gt_template_dir))])

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    await websocket.send_json({"type": "status", "step": "start", "message": "UTG 批量处理启动..."})

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(_SCRIPTS_DIR),
            env=env,
        )
    except Exception as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        return

    try:
        collected = await _stream_subprocess_lines(proc, websocket)
    except (WebSocketDisconnect, ConnectionResetError):
        try:
            proc.kill()
        except Exception:
            pass
        return
    finally:
        await proc.wait()

    # 找最新的 summary
    summaries = sorted(
        [f for f in output_dir.iterdir() if f.name.startswith("utg_batch_summary_")],
        key=lambda f: f.stat().st_mtime, reverse=True,
    )
    summary_data = {}
    if summaries:
        summary_data = _load_json(summaries[0])

    await websocket.send_json({
        "type": "done",
        "success": proc.returncode == 0,
        "summary": summary_data,
        "logs": collected,
        "error": "" if proc.returncode == 0 else f"exit code {proc.returncode}",
    })


@app.get("/api/file")
async def api_file(path: str = Query(..., description="Absolute file path")):
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if not _is_allowed_file(file_path):
        raise HTTPException(status_code=403, detail="File path is not allowed")

    media_type, _ = mimetypes.guess_type(str(file_path))
    return FileResponse(file_path, media_type=media_type or "application/octet-stream")


# ---------------------------------------------------------------------------
# UTG 文本决策 + 生成接口
# ---------------------------------------------------------------------------

def _run_utg_pipeline(req: UTGRunRequest) -> Dict:
    """执行 UTG 模式注入决策（dry_run 仅决策不生成）"""
    # 示例目录：tmp/examples/{uuid}/ → 含 utga_info.json + 截图
    example_dir = _resolve_path(Path(req.example_dir), _DEFAULT_UTG_EXAMPLES_DIR)
    utga_path = example_dir / "utg_info.json"
    if not utga_path.exists():
        # 兼容旧格式：单独的 utg.json
        utga_path = example_dir / "utg.json"
    if not utga_path.exists():
        return {"success": False, "decision": {}, "outputs": {},
                "logs": [f"utg_info.json 不存在: {utga_path}"],
                "error": f"utg_info.json not found: {utga_path}"}

    # 任务描述：从 utga_info.json 顶层 query 字段读取
    utga_data = _load_json(utga_path)
    task_from_info = utga_data.get("query", "") or utga_data.get("description", "")

    # 截图目录：优先级 example_dir/（新格式图片与 info.json 同级） >
    #             example_dir/screenshots/（旧格式子目录） >
    #             req.screenshots_dir（手动指定） >
    #             默认目录
    image_exts = {'.png', '.jpg', '.jpeg', '.webp'}
    has_images_in_dir = any(
        f.is_file() and f.suffix.lower() in image_exts
        for f in example_dir.iterdir()
    ) if example_dir.exists() else False

    screenshots_sub = example_dir / "screenshots"
    if has_images_in_dir:
        screenshots_dir = example_dir
    elif screenshots_sub.exists():
        screenshots_dir = screenshots_sub
    elif req.screenshots_dir:
        screenshots_dir = Path(req.screenshots_dir)
    else:
        screenshots_dir = _DEFAULT_EXAMPLES_DIR  # 回退到旧格式

    output_dir = _resolve_path(Path(req.output), _DEFAULT_OUTPUT_DIR / "utg_run")

    if req.dry_run:
        try:
            sys.path.insert(0, str(_UI_ROOT))
            from app.injection.utg_loader import UTGLoader
            from app.injection.utg_decision import UTGDecisionMaker

            loader = UTGLoader(str(utga_path))
            maker = UTGDecisionMaker()
            task_override = req.task or task_from_info or None
            mapping_cfg = req.mapping_config if req.mapping_config else None
            result = maker.decide(
                loader, task_override=task_override,
                mapping_config=mapping_cfg,
            )
            return {
                "success": result.get("success", False),
                "decision": result,
                "outputs": {},
                "logs": [
                    f"UTG: {loader.total_steps} 原始步骤, {loader.valid_count} 有效步骤",
                    f"任务: {task_override or task_from_info or '自动提取'}",
                    f"决策: step={result.get('injection_step')}, mode={result.get('anomaly_mode')}",
                ],
                "error": result.get("error", ""),
            }
        except Exception as exc:
            import traceback
            return {"success": False, "decision": {}, "outputs": {},
                    "logs": [traceback.format_exc()], "error": str(exc)}

    # 完整模式：调用 injection_pipeline.py --utg
    cmd = [
        sys.executable,
        str(_INJECTION_PIPELINE_SCRIPT),
        "--input-dir", str(screenshots_dir),
        "--output-dir", str(output_dir),
        "--utg", str(utga_path),
        "--no-interactive",
    ]

    if req.task:
        cmd.extend(["--task", req.task])
    elif task_from_info:
        cmd.extend(["--task", task_from_info])
    if req.mapping_config:
        map_path = _resolve_path(Path(req.mapping_config), _DEFAULT_MAPPING_CONFIG)
        cmd.extend(["--mapping-config", str(map_path)])
    if req.gt_template_dir:
        gt_dir = _resolve_path(Path(req.gt_template_dir), _DEFAULT_GT_TEMPLATE_DIR)
        cmd.extend(["--gt-template-dir", str(gt_dir)])
    if not req.enable_verification:
        cmd.append("--no-verification")
    else:
        cmd.extend(["--quality-threshold", str(req.quality_threshold)])
        cmd.extend(["--verification-retries", str(req.verification_retries)])

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            cwd=str(_SCRIPTS_DIR),
            timeout=1800,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "decision": {},
            "outputs": {},
            "logs": ["[timeout] injection_pipeline.py exceeded 1800 seconds"],
            "error": "UTG injection pipeline timed out",
        }
    except Exception as exc:
        return {
            "success": False,
            "decision": {},
            "outputs": {},
            "logs": [f"[exception] {exc}"],
            "error": str(exc),
        }

    logs: List[str] = []
    if proc.stdout:
        logs.extend(proc.stdout.strip().splitlines())
    if proc.stderr:
        logs.extend(f"[stderr] {line}" for line in proc.stderr.strip().splitlines())

    # 查找 decision_log.json
    decision = {}
    outputs = {}
    output_dir_path = output_dir.resolve()
    if output_dir_path.exists():
        # 找最新的 injection_* 子目录
        injection_dirs = sorted(
            [d for d in output_dir_path.iterdir() if d.is_dir() and d.name.startswith("injection_")],
            key=lambda d: d.stat().st_mtime, reverse=True,
        )
        if injection_dirs:
            latest = injection_dirs[0]
            decision_log = latest / "decision_log.json"
            if decision_log.exists():
                decision = _load_json(decision_log)
            metadata = latest / "metadata.json"
            if metadata.exists():
                outputs["metadata"] = _to_file_payload(str(metadata))
            # 收集生成的图片
            modified_seq = latest / "modified_sequence"
            if modified_seq.exists():
                for img in sorted(modified_seq.iterdir()):
                    if img.suffix.lower() in {'.png', '.jpg', '.jpeg'}:
                        outputs[img.name] = _to_file_payload(str(img))

    return {
        "success": proc.returncode == 0,
        "decision": decision,
        "outputs": outputs,
        "logs": logs,
        "error": "" if proc.returncode == 0 else f"Script exited with code {proc.returncode}",
    }


@app.post("/api/utg-run", response_model=UTGRunResponse)
async def api_utg_run(req: UTGRunRequest):
    result = _run_utg_pipeline(req)
    return UTGRunResponse(**result)


@app.get("/api/utg/examples")
async def api_utg_examples():
    """列出 tmp/examples/ 下所有可用的 UUID 示例目录"""
    examples_dir = _DEFAULT_UTG_EXAMPLES_DIR
    if not examples_dir.exists():
        return {"examples": [], "base_dir": str(examples_dir)}
    items = []
    for d in sorted(examples_dir.iterdir()):
        if d.is_dir():
            utg_info = d / "utg_info.json"
            utg_json = d / "utg.json"
            utg_file = utg_info if utg_info.exists() else (utg_json if utg_json.exists() else None)
            if utg_file:
                data = _load_json(utg_file)
                items.append({
                    "dir": str(d),
                    "name": d.name,
                    "query": data.get("query", ""),
                    "appName": data.get("appName", ""),
                    "uuid": data.get("uuid", d.name),
                })
    return {"examples": items, "base_dir": str(examples_dir)}


@app.get("/api/health")
async def health():
    has_key = bool(os.getenv("VLM_API_KEY", ""))
    image_gen = _get_image_gen_health()
    return {
        "status": "ok",
        "vlm_available": has_key,
        "vlm_model": os.getenv("VLM_MODEL", "gpt-4o"),
        "image_gen": image_gen,
        "batch_available": _BATCH_SCRIPT.exists(),
        "utg_batch_available": _BATCH_UTG_SCRIPT.exists(),
        "pipeline_available": _RUN_PIPELINE_SCRIPT.exists(),
        "defaults": {
            "examples_dir": str(_DEFAULT_EXAMPLES_DIR),
            "output_dir": str(_DEFAULT_OUTPUT_DIR),
            "mapping_config": str(_DEFAULT_MAPPING_CONFIG),
            "gt_template_dir": str(_DEFAULT_GT_TEMPLATE_DIR),
            "single_screenshot": str(_DEFAULT_SINGLE_SCREENSHOT),
            "single_output_dir": str(_DEFAULT_SINGLE_OUTPUT_DIR / "demo_single"),
            "utg_json_path": str(_PROJECT_ROOT / "tmp" / "utg.json"),
        "utg_examples_dir": str(_DEFAULT_UTG_EXAMPLES_DIR),
        },
        "utg_mode_available": _INJECTION_PIPELINE_SCRIPT.exists(),
    }


def _parse_port() -> int:
    """解析端口：CLI 参数 > WEB_UI_PORT 环境变量 > 默认 8767"""
    parser = argparse.ArgumentParser(description="UI Semantic Patch Web UI")
    parser.add_argument(
        "port",
        nargs="?",
        type=int,
        default=None,
        help="监听端口（默认 8767，可通过 WEB_UI_PORT 环境变量覆盖）",
    )
    parser.add_argument("--port", "-p", dest="port_flag", type=int, default=None, help="监听端口")
    args = parser.parse_args()
    cli_port = args.port_flag or args.port
    if cli_port is not None:
        return cli_port
    return int(os.getenv("WEB_UI_PORT", "8767"))


PORT = _parse_port()


def _kill_existing():
    """杀掉已占用端口的进程（Windows / Linux 兼容）"""
    if sys.platform == "win32":
        try:
            result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10)
            for line in result.stdout.splitlines():
                if f":{PORT}" in line and "LISTENING" in line:
                    parts = line.split()
                    pid = parts[-1]
                    if pid.isdigit():
                        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=10)
                        print(f"  [+] 已杀掉占用端口 {PORT} 的进程 (PID {pid})")
        except Exception:
            pass
    else:
        try:
            result = subprocess.run(["lsof", "-ti", f":{PORT}"], capture_output=True, text=True, timeout=10)
            for pid in result.stdout.strip().splitlines():
                if pid:
                    subprocess.run(["kill", "-9", pid], timeout=10)
                    print(f"  [+] 已杀掉占用端口 {PORT} 的进程 (PID {pid})")
        except Exception:
            pass


if __name__ == "__main__":
    _kill_existing()
    print("=" * 60)
    print("  UI Semantic Patch Web UI")
    print(f"  http://localhost:{PORT}")
    print("=" * 60)
    has_key = bool(os.getenv("VLM_API_KEY", ""))
    if not has_key:
        print("  [!] VLM_API_KEY 未设置")
    else:
        print(f"  [+] VLM 已配置: {os.getenv('VLM_MODEL', 'gpt-4o')}")
    print(f"  [+] Batch script: {'ok' if _BATCH_SCRIPT.exists() else 'missing'}")
    print(f"  [+] Pipeline script: {'ok' if _RUN_PIPELINE_SCRIPT.exists() else 'missing'}")
    print("  [+] 按 Ctrl+C 停止服务器")
    print()
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")