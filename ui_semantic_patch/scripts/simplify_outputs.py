"""
简化生成结果，提取关键信息另存为干净目录。
每个 query_异常模式 只保留最新时间戳的 injection 结果。

输入: outputs 目录
输出: outputs_clean 目录

每个 query_异常模式 文件夹下:
  <uuid>/
    screenshot.png     - 异常截图（弹窗渲染后的完整截图）
    info.json          - 包含 uuid、弹窗关闭按钮坐标、query 信息等

运行: python simplify_outputs.py
"""

import json
from pathlib import Path
import shutil
import uuid
import re
from datetime import datetime

INPUT_DIR = Path(r"D:\workspace\projects\activate\App_Test_Agent\ui_semantic_patch\scripts\outputs")
OUTPUT_DIR = Path(r"D:\workspace\projects\activate\App_Test_Agent\ui_semantic_patch\scripts\outputs_clean")


def parse_injection_timestamp(folder_name: str) -> datetime:
    """从 injection_YYYYMMDD_HHMMSS 格式解析时间戳"""
    match = re.match(r"injection_(\d{8})_(\d{6})", folder_name)
    if match:
        date_str, time_str = match.groups()
        return datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
    return datetime.min  # 如果无法解析，返回最早时间


def find_latest_injection_per_query(root: Path):
    """
    为每个 query_folder 找到最新时间戳的 injection 子文件夹
    返回: [(query_folder_name, injection_folder_path, pipeline_meta_path)]
    """
    results = []

    for query_folder in sorted(root.iterdir()):
        if not query_folder.is_dir():
            continue
        if query_folder.name == OUTPUT_DIR.name:
            continue

        # 查找所有 injection_YYYYMMDD_HHMMSS 子文件夹
        injection_folders = []
        for subfolder in query_folder.iterdir():
            if not subfolder.is_dir():
                continue
            if subfolder.name.startswith("injection_"):
                timestamp = parse_injection_timestamp(subfolder.name)
                injection_folders.append((timestamp, subfolder))

        if not injection_folders:
            print(f"  [SKIP] {query_folder.name}: 未找到 injection 子文件夹")
            continue

        # 按时间戳排序，取最新的
        injection_folders.sort(key=lambda x: x[0], reverse=True)
        latest_timestamp, latest_folder = injection_folders[0]

        # 在最新的 injection 文件夹中查找 pipeline_meta 文件
        pipeline_metas = list(latest_folder.rglob("*_pipeline_meta_*.json"))

        if not pipeline_metas:
            print(f"  [SKIP] {query_folder.name}/{latest_folder.name}: 未找到 pipeline_meta 文件")
            continue

        # 通常只有一个 pipeline_meta，取第一个
        results.append((query_folder.name, latest_folder, pipeline_metas[0]))
        print(f"  [SELECT] {query_folder.name}: {latest_folder.name} ({len(injection_folders)} 个 injection 中最新)")

    return results


def get_query_info(query_folder_name: str, injection_folder: Path) -> tuple[dict, str]:
    """从 decision_log.json 或文件夹名中提取 query/app 等信息，返回 (info_dict, query_id)"""
    candidates = [
        injection_folder / "decision_log.json",
        injection_folder.parent / "decision_log.json",
    ]
    for c in candidates:
        if c.exists():
            try:
                data = json.loads(c.read_text(encoding="utf-8"))
                query_id = data.get("mapping", {}).get("query_id", "")
                return {
                    "query": data.get("query", ""),
                    "app_name": data.get("app_name", ""),
                    "fault_mode": data.get("fault_mode", ""),
                    "fault_mode_key": data.get("fault_mode_key", ""),
                    "query_id": query_id,
                    "anomaly_instruction": data.get("mapping", {}).get("injection_config", {}).get("instruction", ""),
                    "gt_sample": data.get("mapping", {}).get("injection_config", {}).get("gt_sample", ""),
                    "anomaly_mode": data.get("mapping", {}).get("injection_config", {}).get("anomaly_mode", ""),
                    "matched_rule_id": data.get("rule_decision", {}).get("matched_rule_id", ""),
                    "injection_point": data.get("rule_decision", {}).get("injection_point", ""),
                }, query_id
            except Exception:
                pass

    return {
        "query": "",
        "app_name": query_folder_name,
        "fault_mode": "",
        "fault_mode_key": query_folder_name.split("_mode_")[-1] if "_mode_" in query_folder_name else "",
        "query_id": "",
        "anomaly_instruction": "",
        "gt_sample": "",
        "anomaly_mode": "",
        "matched_rule_id": "",
        "injection_point": "",
    }, ""


def process():
    if not INPUT_DIR.exists():
        print(f"[ERROR] 输入目录不存在: {INPUT_DIR}")
        return

    # 清理输出目录
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    print(f"扫描 {INPUT_DIR} 中的 query 文件夹...")
    selected = find_latest_injection_per_query(INPUT_DIR)

    if not selected:
        print("[WARN] 未找到有效的 injection 数据")
        return

    print(f"\n处理 {len(selected)} 个 query 的最新 injection 数据...")

    stats = {"ok": 0, "skipped_no_final_image": 0, "skipped_no_close_button": 0}

    for query_folder_name, injection_folder, pm_path in selected:
        try:
            pm_data = json.loads(pm_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [SKIP] {query_folder_name}: 无法解析 {pm_path.name}: {e}")
            continue

        # --- 提取 close_button 坐标（核心数据）---
        render_info = pm_data.get("render_metadata", {}).get("render_info", {})
        close_button = render_info.get("close_button")
        if not close_button:
            stats["skipped_no_close_button"] += 1
            print(f"  [SKIP] {query_folder_name}: 无 close_button 信息")
            continue

        # --- 获取最终异常截图路径 ---
        final_image_rel = pm_data.get("outputs", {}).get("final_image", "")
        final_image_path = Path(final_image_rel)
        if not final_image_path.exists():
            final_image_path = pm_path.parent / final_image_path.name
            if not final_image_path.exists():
                finals = list(pm_path.parent.glob("final_*.png"))
                if finals:
                    final_image_path = finals[0]
                else:
                    stats["skipped_no_final_image"] += 1
                    print(f"  [SKIP] {query_folder_name}: 找不到 final_image ({final_image_rel})")
                    continue

        # --- 组装信息 ---
        query_info, query_id = get_query_info(query_folder_name, injection_folder)
        # 使用 decision_log.json 中的 query_id 作为文件夹名，如果没有则生成 uuid
        uid = query_id if query_id else str(uuid.uuid4())

        # 目标目录: outputs_clean/query_folder/<query_id>/
        target_dir = OUTPUT_DIR / query_folder_name / uid
        target_dir.mkdir(parents=True, exist_ok=True)

        # 1. 复制异常截图
        screenshot_dest = target_dir / "screenshot.png"
        shutil.copy2(final_image_path, screenshot_dest)

        # 2. 写入 info.json
        info = {
            "uuid": uid,
            "close_button": {
                "x": close_button.get("x"),
                "y": close_button.get("y"),
                "width": close_button.get("width"),
                "height": close_button.get("height"),
                "position": close_button.get("position", ""),
            },
            "dialog_bounds": render_info.get("dialog_bounds"),
            "screen_size": render_info.get("screen_size"),
            "instruction": pm_data.get("instruction", ""),
            "gt_sample": pm_data.get("render_metadata", {}).get("gt_sample", ""),
            "screenshot_source": str(final_image_path.resolve()),
            "pipeline_meta_source": str(pm_path.resolve()),
            "pipeline_timestamp": pm_data.get("timestamp", ""),
            "position_method": render_info.get("position_method", ""),
            "injection_folder": injection_folder.name,
            **query_info,
        }
        (target_dir / "info.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        stats["ok"] += 1
        print(f"  [OK] {query_folder_name}/{uid}: close=({close_button.get('x')}, {close_button.get('y')})")

    # --- 打印统计 ---
    print("\n" + "=" * 50)
    print(f"处理完成!")
    print(f"  成功: {stats['ok']} 条")
    print(f"  跳过(无 final_image): {stats['skipped_no_final_image']}")
    print(f"  跳过(无 close_button): {stats['skipped_no_close_button']}")
    print(f"输出目录: {OUTPUT_DIR}")


if __name__ == "__main__":
    process()
