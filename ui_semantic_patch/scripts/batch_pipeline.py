#!/usr/bin/env python3
"""
batch_pipeline.py - 批量异常场景生成

扫描指定目录下的所有原图，对每张原图 × 指定异常类别下的所有GT样本，
循环调用 run_pipeline() 生成异常截图。

用法:
  # 对 data/ 目录下所有原图，生成"内容歧义、重复"类别的所有异常
  python batch_pipeline.py \
    --input-dir ../data \
    --gt-category "内容歧义、重复" \
    --output ./batch_output

  # 对原图目录生成"弹窗覆盖原UI"类别的所有异常
  python batch_pipeline.py \
    --input-dir ../data \
    --gt-category "弹窗覆盖原UI" \
    --output ./batch_output

  # 列出所有可用的异常类别和样本
  python batch_pipeline.py --list-categories

  # 只处理匹配模式的原图
  python batch_pipeline.py \
    --input-dir ../data \
    --gt-category "弹窗覆盖原UI" \
    --pattern "*.jpg" \
    --output ./batch_output
"""

import argparse
import json
import os
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

# 自动加载项目根目录的 .env 文件
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parents[3] / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

# 从环境变量读取配置
VLM_API_KEY = os.environ.get('VLM_API_KEY')
VLM_API_URL = os.environ.get('VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions')
VLM_MODEL = os.environ.get('VLM_MODEL', 'gpt-4o')
STRUCTURE_MODEL = os.environ.get('STRUCTURE_MODEL', 'qwen-vl-max')

# 默认GT模板目录
DEFAULT_GT_DIR = Path(__file__).parent.parent / 'data' / 'Agent执行遇到的典型异常UI类型' / 'analysis' / 'gt_templates'

# meta.json category 字段到 anomaly_mode 的映射
CATEGORY_TO_MODE = {
    'dialog_blocking': 'dialog',
    'content_duplicate': 'content_duplicate',
    'loading_timeout': 'area_loading',
}


def scan_screenshots(input_dir: str, pattern: str = '*.jpg') -> List[Path]:
    """扫描目录下的所有截图文件"""
    input_path = Path(input_dir)
    if not input_path.exists():
        print(f"[ERROR] 输入目录不存在: {input_dir}")
        return []

    # 支持多种图片格式
    extensions = ['*.jpg', '*.jpeg', '*.png']
    if pattern not in extensions:
        extensions = [pattern]

    screenshots = []
    for ext in extensions:
        screenshots.extend(input_path.glob(ext))

    # 排除 GT 模板目录下的图片（只处理用户原图）
    screenshots = [
        s for s in screenshots
        if 'gt_templates' not in str(s) and 'analysis' not in str(s)
    ]

    # 按文件名排序
    screenshots.sort(key=lambda p: p.name)
    return screenshots


def resolve_anomaly_mode(meta: Dict) -> str:
    """从 meta.json 解析对应的 anomaly_mode"""
    category_id = meta.get('category', '')

    # 优先从映射表查找
    if category_id in CATEGORY_TO_MODE:
        return CATEGORY_TO_MODE[category_id]

    # 尝试从 usage 字段解析
    usage = meta.get('usage', '')
    mode_match = re.search(r'--anomaly-mode\s+(\S+)', usage)
    if mode_match:
        return mode_match.group(1)

    # 默认弹窗模式
    return 'dialog'


def get_instruction(sample_meta: Dict, gt_category: str) -> str:
    """从样本 meta 获取生成指令"""
    gen_template = sample_meta.get('generation_template', {})
    instruction = gen_template.get('instruction', '')

    if not instruction:
        anomaly_desc = sample_meta.get('anomaly_description', '')
        instruction = f"生成{anomaly_desc}" if anomaly_desc else f"生成{gt_category}异常"

    return instruction


def list_all_categories(gt_dir: Path):
    """列出所有可用的异常类别和样本"""
    from utils.meta_loader import MetaLoader
    loader = MetaLoader(str(gt_dir))

    categories = loader.list_categories()
    if not categories:
        print("未找到任何异常类别")
        return

    print(f"\n可用异常类别 ({len(categories)} 个):")
    print("=" * 60)

    for cat in categories:
        samples = loader.list_samples(cat)
        cat_data = loader.categories[cat]['meta']
        mode = resolve_anomaly_mode(cat_data)
        desc = cat_data.get('description', '')

        print(f"\n  [{cat}]")
        print(f"    描述: {desc}")
        print(f"    异常模式: {mode}")
        print(f"    样本数: {len(samples)}")
        for s in samples:
            print(f"      - {s}")

    print()


def run_batch(
    input_dir: str,
    gt_category: str,
    output_dir: str,
    gt_dir: str = None,
    pattern: str = '*.jpg',
    api_key: str = None,
    api_url: str = None,
    structure_model: str = None,
    vlm_api_url: str = None,
    vlm_model: str = None,
    omni_device: str = None,
    no_visualize: bool = False,
    dry_run: bool = False,
):
    """
    批量执行异常场景生成

    Args:
        input_dir: 原图目录
        gt_category: 异常类别（目录名，如 "内容歧义、重复"）
        output_dir: 输出根目录
        gt_dir: GT模板根目录
        pattern: 文件匹配模式
        api_key: VLM API 密钥
        api_url: VLM API 端点
        structure_model: 结构提取模型
        vlm_api_url: VLM API 端点
        vlm_model: VLM 模型
        omni_device: OmniParser 设备
        no_visualize: 禁用可视化
        dry_run: 只打印计划，不实际执行
    """
    from utils.meta_loader import MetaLoader
    from run_pipeline import run_pipeline

    gt_dir = gt_dir or str(DEFAULT_GT_DIR)
    api_key = api_key or VLM_API_KEY
    api_url = api_url or VLM_API_URL
    structure_model = structure_model or STRUCTURE_MODEL
    vlm_api_url = vlm_api_url or VLM_API_URL
    vlm_model = vlm_model or VLM_MODEL

    if not api_key:
        print("[ERROR] 未设置 VLM_API_KEY 环境变量，请配置 .env 文件")
        return

    # 1. 扫描原图
    screenshots = scan_screenshots(input_dir, pattern)
    if not screenshots:
        print(f"[ERROR] 在 {input_dir} 中未找到匹配 {pattern} 的图片")
        return

    print(f"\n扫描到 {len(screenshots)} 张原图:")
    for s in screenshots:
        print(f"  - {s.name}")

    # 2. 加载GT模板
    loader = MetaLoader(gt_dir)
    if gt_category not in loader.list_categories():
        print(f"\n[ERROR] 异常类别不存在: {gt_category}")
        print(f"  可用类别: {', '.join(loader.list_categories())}")
        return

    samples = loader.list_samples(gt_category)
    cat_meta = loader.categories[gt_category]['meta']
    anomaly_mode = resolve_anomaly_mode(cat_meta)

    print(f"\n异常类别: {gt_category}")
    print(f"异常模式: {anomaly_mode}")
    print(f"GT样本数: {len(samples)}")
    for s in samples:
        print(f"  - {s}")

    # 3. 计算任务总量
    total_tasks = len(screenshots) * len(samples)
    print(f"\n总任务数: {len(screenshots)} 张原图 × {len(samples)} 个样本 = {total_tasks} 个")
    print("=" * 60)

    if dry_run:
        print("\n[DRY RUN] 以下为执行计划:")
        for i, screenshot in enumerate(screenshots):
            for j, sample in enumerate(samples):
                sample_meta = loader.load_sample_meta(gt_category, sample)
                instruction = get_instruction(sample_meta, gt_category)
                print(f"  [{i*len(samples)+j+1}/{total_tasks}] {screenshot.name} × {sample}")
                print(f"    指令: {instruction}")
                print(f"    模式: {anomaly_mode}")
        print("\n[DRY RUN] 使用 --run 来实际执行")
        return

    # 4. 创建输出目录
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    batch_output = Path(output_dir) / f"batch_{gt_category}_{timestamp}"
    batch_output.mkdir(parents=True, exist_ok=True)

    # 5. 批量执行
    results = []
    success_count = 0
    fail_count = 0

    for i, screenshot in enumerate(screenshots):
        for j, sample in enumerate(samples):
            task_idx = i * len(samples) + j + 1
            sample_meta = loader.load_sample_meta(gt_category, sample)
            instruction = get_instruction(sample_meta, gt_category)
            reference_path = loader.get_sample_path(gt_category, sample)

            # 为每对（原图, GT样本）创建子目录
            safe_screenshot_name = screenshot.stem
            safe_sample_name = Path(sample).stem
            task_output = batch_output / f"{safe_screenshot_name}__{safe_sample_name}"
            task_output.mkdir(parents=True, exist_ok=True)

            print(f"\n{'='*60}")
            print(f"[{task_idx}/{total_tasks}] {screenshot.name} × {sample}")
            print(f"  指令: {instruction}")
            print(f"  输出: {task_output}")
            print(f"{'='*60}")

            task_result = {
                'screenshot': str(screenshot),
                'gt_sample': sample,
                'gt_category': gt_category,
                'instruction': instruction,
                'anomaly_mode': anomaly_mode,
                'output_dir': str(task_output),
                'status': 'pending'
            }

            try:
                pipeline_result = run_pipeline(
                    screenshot_path=str(screenshot),
                    instruction=instruction,
                    output_dir=str(task_output),
                    api_key=api_key,
                    api_url=api_url,
                    structure_model=structure_model,
                    gt_dir=gt_dir,
                    vlm_api_url=vlm_api_url,
                    vlm_model=vlm_model,
                    reference_path=reference_path,
                    omni_device=omni_device,
                    visualize=not no_visualize,
                    anomaly_mode=anomaly_mode,
                    gt_category=gt_category,
                    gt_sample=sample
                )

                final_image = pipeline_result.get('outputs', {}).get('final_image')
                if final_image and Path(final_image).exists():
                    task_result['status'] = 'success'
                    task_result['final_image'] = final_image
                    success_count += 1
                    print(f"\n  [OK] 生成成功: {final_image}")
                else:
                    task_result['status'] = 'failed'
                    task_result['error'] = '未生成最终图片'
                    fail_count += 1
                    print(f"\n  [FAIL] 未生成最终图片")

            except Exception as e:
                task_result['status'] = 'error'
                task_result['error'] = str(e)
                fail_count += 1
                print(f"\n  [ERROR] {e}")

            results.append(task_result)

    # 6. 保存批量处理报告
    report = {
        'timestamp': timestamp,
        'input_dir': str(input_dir),
        'gt_category': gt_category,
        'anomaly_mode': anomaly_mode,
        'total_tasks': total_tasks,
        'success': success_count,
        'failed': fail_count,
        'results': results
    }

    report_path = batch_output / 'batch_report.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 7. 打印总结
    print(f"\n{'='*60}")
    print(f"批量生成完成!")
    print(f"{'='*60}")
    print(f"  总任务: {total_tasks}")
    print(f"  成功: {success_count}")
    print(f"  失败: {fail_count}")
    print(f"  输出目录: {batch_output}")
    print(f"  批量报告: {report_path}")

    # 列出所有生成的最终图片
    if success_count > 0:
        print(f"\n生成的异常截图:")
        for r in results:
            if r['status'] == 'success':
                print(f"  [OK] {Path(r['final_image']).name}")
                print(f"       原图: {Path(r['screenshot']).name}")
                print(f"       样本: {r['gt_sample']}")

    if fail_count > 0:
        print(f"\n失败的任务:")
        for r in results:
            if r['status'] != 'success':
                print(f"  [FAIL] {Path(r['screenshot']).name} × {r['gt_sample']}")
                print(f"         原因: {r.get('error', 'unknown')}")


def main():
    parser = argparse.ArgumentParser(
        description='批量 UI 异常场景生成',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 列出所有异常类别
  python batch_pipeline.py --list-categories

  # 预览执行计划（不实际执行）
  python batch_pipeline.py \\
    --input-dir ../data \\
    --gt-category "内容歧义、重复" \\
    --dry-run

  # 实际执行批量生成
  python batch_pipeline.py \\
    --input-dir ../data \\
    --gt-category "内容歧义、重复" \\
    --output ./batch_output \\
    --run
"""
    )

    parser.add_argument('--input-dir', '-i',
                        help='原图目录，扫描该目录下所有图片文件')
    parser.add_argument('--gt-category', '-c',
                        help='异常类别名称（目录名），如 "内容歧义、重复"、"弹窗覆盖原UI"')
    parser.add_argument('--output', '-o', default='./batch_output',
                        help='输出根目录（默认 ./batch_output）')
    parser.add_argument('--gt-dir',
                        help=f'GT模板根目录（默认 {DEFAULT_GT_DIR}）')
    parser.add_argument('--pattern', default='*.jpg',
                        help='文件匹配模式（默认 *.jpg，设为 * 则匹配所有图片格式）')
    parser.add_argument('--list-categories', action='store_true',
                        help='列出所有可用的异常类别和样本')
    parser.add_argument('--dry-run', action='store_true',
                        help='只打印执行计划，不实际执行')
    parser.add_argument('--run', action='store_true',
                        help='实际执行批量生成（默认为 dry-run 模式）')

    # API 配置
    parser.add_argument('--api-key', default=VLM_API_KEY)
    parser.add_argument('--api-url', default=VLM_API_URL)
    parser.add_argument('--structure-model', default=STRUCTURE_MODEL)
    parser.add_argument('--vlm-api-url', default=VLM_API_URL)
    parser.add_argument('--vlm-model', default=VLM_MODEL)
    parser.add_argument('--omni-device', help='OmniParser 设备 (cuda/cpu)')
    parser.add_argument('--no-visualize', action='store_true',
                        help='禁用中间结果可视化')

    args = parser.parse_args()

    gt_dir = Path(args.gt_dir) if args.gt_dir else DEFAULT_GT_DIR

    # 列出类别模式
    if args.list_categories:
        list_all_categories(gt_dir)
        return

    # 检查必需参数
    if not args.input_dir:
        parser.error("请指定原图目录: --input-dir <path>")
    if not args.gt_category:
        parser.error("请指定异常类别: --gt-category <name>（使用 --list-categories 查看可用类别）")

    # 默认为 dry-run，除非指定 --run
    dry_run = not args.run

    if dry_run and not args.dry_run:
        print("[提示] 默认为预览模式，添加 --run 来实际执行")

    run_batch(
        input_dir=args.input_dir,
        gt_category=args.gt_category,
        output_dir=args.output,
        gt_dir=str(gt_dir),
        pattern=args.pattern,
        api_key=args.api_key,
        api_url=args.api_url,
        structure_model=args.structure_model,
        vlm_api_url=args.vlm_api_url,
        vlm_model=args.vlm_model,
        omni_device=args.omni_device,
        no_visualize=args.no_visualize,
        dry_run=dry_run,
    )


if __name__ == '__main__':
    main()
