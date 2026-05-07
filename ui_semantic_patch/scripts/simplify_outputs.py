"""
简化生成结果，提取关键信息另存为干净目录。

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

INPUT_DIR = Path(r"D:\workspace\projects\activate\App_Test_Agent\ui_semantic_patch\scripts\outputs")
OUTPUT_DIR = Path(r"D:\workspace\projects\activate\App_Test_Agent\ui_semantic_patch\scripts\outputs_clean")


def find_all_pipeline_metas(root: Path):
    """递归查找所有 *_pipeline_meta_*.json 文件，返回 (query_folder_name, pipeline_meta_path) 列表"""
    results = []
    for f in sorted(root.rglob("*_pipeline_meta_*.json")):
        # 跳过已在 outputs_clean 中的
        if OUTPUT_DIR in f.parents:
            continue
        # 上级目录结构: .../query_folder/.../pipeline_meta.json
        # 推断 query_folder 为 outputs/xxx/ 下的第一级子目录
        rel = f.relative_to(root)
        query_folder = rel.parts[0]  # 如 injection_demo_01_mode_1
        results.append((query_folder, f))
    return results


def get_query_info(query_folder_name: str, pipeline_meta_path: Path) -> dict:
    """从 decision_log.json 或文件夹名中提取 query/app 等信息"""
    # 尝试从 pipeline_meta_path 回溯找到同级的 decision_log.json
    # 查找路径：pipeline_meta 同一级、上一级、或上两级
    candidates = [
        pipeline_meta_path.parent / "decision_log.json",
        pipeline_meta_path.parent.parent / "decision_log.json",
    ]
    for c in candidates:
        if c.exists():
            try:
                data = json.loads(c.read_text(encoding="utf-8"))
                return {
                    "query": data.get("query", ""),
                    "app_name": data.get("app_name", ""),
                    "fault_mode": data.get("fault_mode", ""),
                    "fault_mode_key": data.get("fault_mode_key", ""),
                    "query_id": data.get("mapping", {}).get("query_id", ""),
                    "anomaly_instruction": data.get("mapping", {}).get("injection_config", {}).get("instruction", ""),
                    "gt_sample": data.get("mapping", {}).get("injection_config", {}).get("gt_sample", ""),
                    "anomaly_mode": data.get("mapping", {}).get("injection_config", {}).get("anomaly_mode", ""),
                    "matched_rule_id": data.get("rule_decision", {}).get("matched_rule_id", ""),
                    "injection_point": data.get("rule_decision", {}).get("injection_point", ""),
                }
            except Exception:
                pass

    # 如果找不到 decision_log，从 pipeline_meta 和文件夹名推断部分信息
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
    }


def process():
    if not INPUT_DIR.exists():
        print(f"[ERROR] 输入目录不存在: {INPUT_DIR}")
        return

    # 清理输出目录
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    pipeline_metas = find_all_pipeline_metas(INPUT_DIR)
    if not pipeline_metas:
        print("[WARN] 未找到任何 *_pipeline_meta_*.json 文件")
        return

    print(f"找到 {len(pipeline_metas)} 个 pipeline_meta 文件，正在处理...")

    stats = {"ok": 0, "skipped_no_final_image": 0, "skipped_no_close_button": 0}

    for query_folder_name, pm_path in pipeline_metas:
        try:
            pm_data = json.loads(pm_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [SKIP] 无法解析 {pm_path.name}: {e}")
            continue

        # --- 提取 close_button 坐标（核心数据）---
        render_info = pm_data.get("render_metadata", {}).get("render_info", {})
        close_button = render_info.get("close_button")
        if not close_button:
            stats["skipped_no_close_button"] += 1
            print(f"  [SKIP] {pm_path.name}: 无 close_button 信息")
            continue

        # --- 获取最终异常截图路径 ---
        final_image_rel = pm_data.get("outputs", {}).get("final_image", "")
        final_image_path = Path(final_image_rel)
        if not final_image_path.exists():
            # 尝试相对路径拼接
            final_image_path = pm_path.parent / final_image_path.name
            if not final_image_path.exists():
                # 最后尝试同级目录下找 final_*.png
                finals = list(pm_path.parent.glob("final_*.png"))
                if finals:
                    final_image_path = finals[0]
                else:
                    stats["skipped_no_final_image"] += 1
                    print(f"  [SKIP] {pm_path.name}: 找不到 final_image ({final_image_rel})")
                    continue

        # --- 组装信息 ---
        uid = str(uuid.uuid4())
        query_info = get_query_info(query_folder_name, pm_path)

        # 目标目录: outputs_clean/query_folder/uuid/
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
