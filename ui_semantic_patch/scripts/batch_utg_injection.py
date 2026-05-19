#!/usr/bin/env python3
"""
batch_utg_injection.py — UTG 批量异常注入

扫描 tmp/examples/ 下所有 UUID 目录（含 utga_info.json + 截图），
匹配 mapping.json 中对应 query 的 injection_config，
通过 LLM 批量打分决定注入点，调用 run_pipeline.py 生成异常。

用法:
    python batch_utg_injection.py \
        --examples-dir tmp/examples \
        --mapping-config tmp/mapping.json \
        --output-dir outputs/utg_batch

    # Dry-run: 仅 LLM 打分，不生成图片
    python batch_utg_injection.py --examples-dir tmp/examples ... --dry-run
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# UTF-8输出
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    from dotenv import load_dotenv
    for p in [_project_root / ".env", _project_root.parent / ".env"]:
        if p.exists():
            load_dotenv(p)
except ImportError:
    pass

from app.injection.utg_loader import UTGLoader
from app.injection.utg_decision import UTGDecisionMaker, _load_injection_config
from app.core.config import config

# 默认路径
DEFAULT_EXAMPLES_DIR = _project_root / "tmp" / "examples"
DEFAULT_MAPPING_CONFIG = _project_root / "tmp" / "mapping.json"
DEFAULT_OUTPUT_DIR = _project_root / "outputs" / "utg_batch"
RUN_PIPELINE_SCRIPT = Path(__file__).parent / "run_pipeline.py"

# 不需要 GT 参考图的模式
NO_GT_MODES = {
    'modify_text', 'modify_text_ai', 'modify_text_ocr', 'modify_text_e2e',
    'text_overlay', 'area_loading', 'content_duplicate', 'response_delay',
    'image_broken',
}

logger = logging.getLogger(__name__)


def scan_examples(examples_dir: Path) -> List[Dict]:
    """扫描示例目录，返回所有含 utga_info.json 的 UUID 目录信息"""
    items = []
    for d in sorted(examples_dir.iterdir()):
        if not d.is_dir():
            continue
        utg_path = d / "utg_info.json"
        if not utg_path.exists():
            continue
        try:
            with open(utg_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"  ⚠ 跳过 {d.name}: {e}")
            continue
        items.append({
            "dir": str(d),
            "uuid": data.get("uuid", d.name),
            "query": data.get("query", ""),
            "appName": data.get("appName", ""),
            "step_count": len(data.get("stepData", [])),
            "has_images": any(
                f.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp'}
                for f in d.iterdir() if f.is_file()
            ),
        })
    return items


def match_mapping(example: Dict, mapping_entries: List[Dict]) -> Optional[Dict]:
    """将 example 匹配到 mapping 中对应的 injection_config

    匹配优先级：
    1. UUID 精确匹配 query_id（同一个 ID，最快最准）
    2. query 文本精确匹配
    3. query 文本模糊匹配
    """
    uuid = example["uuid"]
    query = (example.get("query") or "").strip()

    # 构建 query_id → entry 索引
    id_index = {e.get("query_id", ""): e for e in mapping_entries if e.get("query_id")}

    # 优先级 1: UUID 匹配
    if uuid in id_index:
        return id_index[uuid]

    for entry in mapping_entries:
        mq = (entry.get("query") or "").strip()
        # 优先级 2: 精确匹配
        if query and mq and query == mq:
            return entry
        # 优先级 3: 模糊匹配
        if query and mq and (query in mq or mq in query or _fuzzy_match(query, mq)):
            return entry

    return None


def _fuzzy_match(a: str, b: str, threshold: float = 0.7) -> bool:
    """简单模糊匹配：提取括号中的 app 名和关键词"""
    import re

    def _keywords(s):
        # 提取括号中的 app 名 + 去掉 app 名后的关键词
        apps = re.findall(r'[（(]([^）)]+)[）)]', s)
        rest = re.sub(r'[（(][^）)]*[）)]', '', s).strip()
        return set(apps + [rest])

    ka = _keywords(a)
    kb = _keywords(b)
    if not ka or not kb:
        return False
    overlap = len(ka & kb)
    return overlap / max(len(ka), len(kb)) >= threshold


def run_single_generation(
    screenshot_path: Path,
    instruction: str,
    anomaly_mode: str,
    output_dir: Path,
    gt_category: str = "",
    gt_sample: str = "",
    reference_path: str = "",
    timeout: int = 1800,
) -> Dict:
    """调用 run_pipeline.py 生成异常截图"""
    cmd = [
        sys.executable, str(RUN_PIPELINE_SCRIPT),
        "--screenshot", str(screenshot_path),
        "--instruction", instruction,
        "--anomaly-mode", anomaly_mode,
        "--output", str(output_dir),
        "--no-visualize",
    ]
    if gt_category:
        cmd.extend(["--gt-category", gt_category])
    if gt_sample:
        cmd.extend(["--gt-sample", gt_sample])
    if reference_path:
        cmd.extend(["--reference", str(reference_path)])

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            env=env, cwd=str(RUN_PIPELINE_SCRIPT.parent), timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "timeout"}
    except Exception as e:
        return {"success": False, "error": str(e)}

    return {
        "success": proc.returncode == 0,
        "stdout": proc.stdout[-500:] if proc.stdout else "",
        "stderr": proc.stderr[-500:] if proc.stderr else "",
        "error": "" if proc.returncode == 0 else f"exit code {proc.returncode}",
    }


def process_example(
    example: Dict,
    mapping_entry: Dict,
    output_dir: Path,
    decision_maker: UTGDecisionMaker,
    dry_run: bool = False,
    gt_template_dir: str = None,
) -> Dict:
    """处理单个 example：决策 + 生成"""
    example_dir = Path(example["dir"])
    uuid = example["uuid"]
    inj = mapping_entry.get("injection_config", {})
    anomaly_mode = inj.get("anomaly_mode", "dialog")
    instruction = inj.get("instruction", "")

    result = {
        "uuid": uuid,
        "query": example["query"],
        "anomaly_mode": anomaly_mode,
        "instruction": instruction,
        "injection_step": None,
        "success": False,
        "generated": False,
    }

    print(f"\n{'='*60}")
    print(f"处理: {example['appName']} — {example['query'][:40]}...")
    print(f"  UUID: {uuid}")
    print(f"  异常: {anomaly_mode} | {instruction[:50]}...")

    # Step 1: LLM 打分决策（约束模式，直接传 injection_config）
    loader = UTGLoader(str(example_dir / "utg_info.json"))
    decision = decision_maker.decide(
        loader,
        task_override=example.get("query"),
        injection_config=inj,  # 直接传 dict，免文件加载
    )
    result["decision"] = decision
    result["injection_step"] = decision.get("injection_step")

    if decision.get("injection_step", -1) < 0:
        print(f"  ⏭ 跳过: {decision.get('reason', '无合适注入点')[:80]}")
        result["reason"] = decision.get("reason", "")
        return result

    step = decision["injection_step"]
    print(f"  ✓ 注入点: Step {step} (score={decision.get('score', '?')})")

    if dry_run:
        result["success"] = True
        result["reason"] = f"[DRY-RUN] 将在 Step {step} 注入"
        return result

    # Step 2: 找对应截图
    # 截图命名: 001.jpg, 002.jpg ... 从 1 开始
    image_exts = {'.jpg', '.jpeg', '.png', '.webp'}
    screenshot = None
    for ext in image_exts:
        # step 0 → 001, step 1 → 002
        candidate = example_dir / f"{step + 1:03d}{ext}"
        if candidate.exists():
            screenshot = candidate
            break
    if screenshot is None:
        # 回退：按文件名排序取第 step 张
        images = sorted(
            [f for f in example_dir.iterdir()
             if f.is_file() and f.suffix.lower() in image_exts],
            key=lambda f: f.name
        )
        if step < len(images):
            screenshot = images[step]
        else:
            print(f"  ✗ 找不到 Step {step} 的截图")
            result["error"] = f"screenshot not found for step {step}"
            return result

    print(f"  截图: {screenshot.name}")

    # Step 3: 准备 GT（dialog 模式需要）
    need_gt = anomaly_mode not in NO_GT_MODES
    gt_category = ""
    gt_sample = ""
    if need_gt:
        gt_category = mapping_entry.get("injection_config", {}).get("gt_category", "dialog")
        gt_sample = mapping_entry.get("injection_config", {}).get("gt_sample", "")
        if not gt_sample and gt_template_dir:
            gt_dir = Path(gt_template_dir) / gt_category if gt_category else None
            if gt_dir and gt_dir.exists():
                for ext in ['.jpg', '.jpeg', '.png']:
                    samples = list(gt_dir.glob(f"*{ext}"))
                    if samples:
                        gt_sample = samples[0].name
                        break

    # Step 4: 序列注入（生成 + 组装）
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    inject_dir = output_dir / f"injection_{uuid[:8]}_{timestamp}"
    sequence_dir = inject_dir / "modified_sequence"
    anomaly_out_dir = inject_dir / "anomaly_generated"
    sequence_dir.mkdir(parents=True, exist_ok=True)
    anomaly_out_dir.mkdir(parents=True, exist_ok=True)

    # 4a. 收集全部原始截图
    all_images = sorted(
        [f for f in example_dir.iterdir()
         if f.is_file() and f.suffix.lower() in image_exts],
        key=lambda f: f.name
    )
    original_count = len(all_images)
    print(f"  原始序列: {original_count} 张")

    # 4b. 调用 run_pipeline.py 生成异常图
    print(f"  生成中... (mode={anomaly_mode})")
    gen_result = run_single_generation(
        screenshot_path=screenshot,
        instruction=instruction,
        anomaly_mode=anomaly_mode,
        output_dir=anomaly_out_dir,
        gt_category=gt_category,
        gt_sample=gt_sample,
        reference_path=mapping_entry.get("injection_config", {}).get("reference_path", ""),
    )
    if not gen_result.get("success"):
        print(f"  ✗ 生成失败: {gen_result.get('error', '未知错误')}")
        result["error"] = gen_result.get("error", "")
        return result

    # 查找生成的 final_*.png
    anomaly_images = sorted(
        [f for f in anomaly_out_dir.rglob("final_*.png")
         if f.is_file()],
        key=lambda f: f.stat().st_mtime, reverse=True,
    )
    if not anomaly_images:
        print(f"  ✗ 未找到生成的异常图")
        result["error"] = "no anomaly image generated"
        return result
    anomaly_img = anomaly_images[0]

    # 4c. 复制全部原图到 modified_sequence/
    if all_images:
        for i, img in enumerate(all_images):
            dst = sequence_dir / f"step_{i:03d}{img.suffix}"
            shutil.copy2(img, dst)

    # 4d. 判断是否可关闭类异常
    dismissible_modes = {'dialog', 'area_loading', 'content_duplicate'}
    is_dismissible = anomaly_mode in dismissible_modes
    shift = 2 if is_dismissible else 1
    insert_pos = step + 1

    # 4e. 将注入点之后的原图平移 shift 位
    for i in range(original_count - 1, step, -1):
        for ext in ['.jpg', '.jpeg', '.png', '.webp']:
            src = sequence_dir / f"step_{i:03d}{ext}"
            if src.exists():
                dst = sequence_dir / f"step_{i + shift:03d}{ext}"
                src.rename(dst)
                break

    # 4f. 插入异常图
    anomaly_dst = sequence_dir / f"step_{insert_pos:03d}_anomaly{anomaly_img.suffix}"
    shutil.copy2(anomaly_img, anomaly_dst)
    print(f"  异常注入: {anomaly_img.name} → {anomaly_dst.name}")

    # 4g. 可关闭类：插入恢复图（注入点原图副本）
    if is_dismissible:
        restore_dst = sequence_dir / f"step_{insert_pos + 1:03d}{screenshot.suffix}"
        shutil.copy2(screenshot, restore_dst)
        print(f"  恢复界面: {screenshot.name} → {restore_dst.name}")

    # 4h. 最终序列排序
    modified_sequence = sorted(
        sequence_dir.glob("step_*.*"),
        key=lambda p: p.name
    )

    # 4i. 保存元数据
    metadata = {
        "timestamp": timestamp,
        "uuid": uuid,
        "query": example["query"],
        "app_name": example.get("appName", ""),
        "anomaly_mode": anomaly_mode,
        "instruction": instruction,
        "injection_step": step,
        "injection_score": decision.get("score"),
        "is_dismissible": is_dismissible,
        "original_count": original_count,
        "modified_count": len(modified_sequence),
        "original_images": [f.name for f in all_images],
        "modified_sequence": [f.name for f in modified_sequence],
    }
    metadata_path = inject_dir / "metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    # 4j. 保存决策日志
    log_path = inject_dir / "decision_log.json"
    with open(log_path, 'w', encoding='utf-8') as f:
        json.dump(decision, f, ensure_ascii=False, indent=2)

    print(f"  ✓ 注入完成: {inject_dir.name}")
    print(f"    序列: {original_count} → {len(modified_sequence)} 张 "
          f"({'可关闭' if is_dismissible else '永久修改'})")

    result["success"] = True
    result["generated"] = True
    result["output_dir"] = str(inject_dir)
    result["metadata"] = metadata
    return result


def main():
    parser = argparse.ArgumentParser(description="UTG 批量异常注入")
    parser.add_argument("--examples-dir", default=str(DEFAULT_EXAMPLES_DIR),
                        help=f"示例目录 (默认: {DEFAULT_EXAMPLES_DIR})")
    parser.add_argument("--mapping-config", default=str(DEFAULT_MAPPING_CONFIG),
                        help=f"mapping 配置路径 (默认: {DEFAULT_MAPPING_CONFIG})")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR),
                        help=f"输出目录 (默认: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--gt-template-dir", default=None,
                        help="GT 模板目录 (dialog 模式需要)")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅 LLM 打分，不生成图片")
    parser.add_argument("--uuid", default=None,
                        help="仅处理指定 UUID（调试用）")

    args = parser.parse_args()

    examples_dir = Path(args.examples_dir)
    mapping_path = Path(args.mapping_config)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not examples_dir.exists():
        print(f"❌ 示例目录不存在: {examples_dir}")
        sys.exit(1)
    if not mapping_path.exists():
        print(f"❌ mapping 文件不存在: {mapping_path}")
        sys.exit(1)

    # 加载 mapping
    with open(mapping_path, 'r', encoding='utf-8') as f:
        mapping_data = json.load(f)
    mapping_entries = mapping_data.get("mappings", [])

    print(f"{'='*60}")
    print(f"UTG 批量异常注入")
    print(f"{'='*60}")
    print(f"示例目录: {examples_dir}")
    print(f"Mapping: {mapping_path} ({len(mapping_entries)} 条)")
    print(f"输出目录: {output_dir}")
    print(f"模式: {'Dry-Run (仅打分)' if args.dry_run else '完整生成'}")
    print(f"GT模板: {args.gt_template_dir or '自动检测'}")

    # 扫描示例
    examples = scan_examples(examples_dir)
    print(f"\n扫描到 {len(examples)} 个示例:")
    for e in examples:
        print(f"  {e['uuid'][:8]}... {e['appName']:4s} | {e['query'][:40]}")

    # 过滤
    if args.uuid:
        examples = [e for e in examples if e["uuid"].startswith(args.uuid)]
        if not examples:
            print(f"❌ 未找到匹配的 UUID: {args.uuid}")
            sys.exit(1)

    # 初始化决策器
    decision_maker = UTGDecisionMaker()

    # 批量处理
    results = []
    success_count = 0
    skip_count = 0
    fail_count = 0

    for example in examples:
        entry = match_mapping(example, mapping_entries)
        if not entry:
            print(f"\n{'─'*40}")
            print(f"⚠ 未匹配到 mapping: {example['query'][:40]} (UUID={example['uuid'][:8]}...)")
            results.append({
                "uuid": example["uuid"],
                "query": example["query"],
                "error": "no matching mapping entry",
                "success": False,
            })
            fail_count += 1
            continue

        result = process_example(
            example, entry, output_dir, decision_maker,
            dry_run=args.dry_run,
            gt_template_dir=args.gt_template_dir,
        )
        results.append(result)

        if result.get("injection_step", -1) < 0:
            skip_count += 1
        elif result.get("success", False):
            success_count += 1
        else:
            fail_count += 1

    # 汇总
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary = {
        "timestamp": timestamp,
        "total": len(results),
        "success": success_count,
        "skipped": skip_count,
        "failed": fail_count,
        "dry_run": args.dry_run,
        "results": results,
    }

    summary_path = output_dir / f"utg_batch_summary_{timestamp}.json"
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"批量处理完成")
    print(f"{'='*60}")
    print(f"  总数: {len(results)}")
    print(f"  ✓ 成功: {success_count}")
    print(f"  ⏭ 跳过: {skip_count}")
    print(f"  ✗ 失败: {fail_count}")
    print(f"  汇总: {summary_path}")


if __name__ == "__main__":
    main()
