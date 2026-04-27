#!/usr/bin/env python3
"""
batch_injection_with_mapping.py - 批量异常注入脚本（基于映射配置）

使用映射配置文件批量处理examples目录中的所有任务，
自动为每个query选择合适的异常注入参数。
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict

# 设置 UTF-8 编码输出（Windows 兼容）
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 确保能导入 app 模块
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 自动加载环境变量
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parents[2] / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

from app.injection import AnomalyMappingResolver, QualityVerifier
from app.injection.sequence_rewriter import SequenceRewriter


def load_mapping_config(config_path: str) -> Dict:
    """加载映射配置"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def find_mappings_for_query(query: str, app_name: str, mapping_config: Dict) -> List[Dict]:
    """
    查找query对应的所有映射

    Args:
        query: 任务描述
        app_name: 应用名称
        mapping_config: 映射配置

    Returns:
        匹配的映射列表（每个query可能对应2个故障模式）
    """
    mappings = []

    for mapping in mapping_config.get('mappings', []):
        if mapping.get('query') == query:
            mappings.append(mapping)

    return mappings


def batch_process(
    examples_dir: str,
    output_base_dir: str,
    mapping_config_path: str,
    gt_template_dir: str = None,
    fault_mode_key: str = None,  # 'mode_1' or 'mode_2'，如果指定则只处理该模式
    enable_verification: bool = False,
    quality_threshold: float = 6.0,
    max_verification_retries: int = 2
):
    """
    批量处理异常注入

    Args:
        examples_dir: examples目录路径
        output_base_dir: 输出基础目录
        mapping_config_path: 映射配置文件路径
        gt_template_dir: GT模板目录
        fault_mode_key: 指定处理的故障模式（mode_1或mode_2），None表示处理所有
        enable_verification: 是否启用VLM质量验证
        quality_threshold: 质量阈值
        max_verification_retries: 最大验证重试次数
    """
    examples_dir = Path(examples_dir)
    output_base_dir = Path(output_base_dir)

    # 加载映射配置
    print(f"\n加载映射配置: {mapping_config_path}")
    mapping_config = load_mapping_config(mapping_config_path)
    print(f"  总映射数: {len(mapping_config.get('mappings', []))}")
    print(f"  统计: {mapping_config.get('statistics', {})}")

    # 初始化映射解析器
    resolver = AnomalyMappingResolver(mapping_config_path)

    # 遍历examples目录
    demo_dirs = sorted(examples_dir.iterdir())
    total_processed = 0
    total_failed = 0

    print(f"\n开始批量处理...")
    print(f"  输入目录: {examples_dir}")
    print(f"  输出目录: {output_base_dir}")
    print(f"  GT模板目录: {gt_template_dir}")
    print(f"  故障模式: {fault_mode_key or '全部'}")
    print("="*60)

    for demo_dir in demo_dirs:
        if not demo_dir.is_dir():
            continue

        task_file = demo_dir / 'task.json'
        if not task_file.exists():
            continue

        # 读取任务信息
        with open(task_file, 'r', encoding='utf-8') as f:
            task_data = json.load(f)

        query = task_data.get('description', '')
        app_name = task_data.get('app_name', '')

        # 查找映射
        mappings = find_mappings_for_query(query, app_name, mapping_config)

        if not mappings:
            print(f"\n⚠ 跳过: {demo_dir.name} (未找到映射配置)")
            continue

        # 过滤故障模式
        if fault_mode_key:
            mappings = [m for m in mappings if m.get('fault_mode_key') == fault_mode_key]
            if not mappings:
                print(f"\n⚠ 跳过: {demo_dir.name} (未找到 {fault_mode_key} 映射)")
                continue

        # 加载截图
        screenshots_dir = demo_dir / 'screenshots'
        if not screenshots_dir.exists():
            screenshots_dir = demo_dir

        image_extensions = {'.png', '.jpg', '.jpeg', '.webp'}
        screenshots = []
        for f in screenshots_dir.iterdir():
            if f.is_file() and f.suffix.lower() in image_extensions:
                screenshots.append(f)
        screenshots.sort(key=lambda x: x.name)

        if not screenshots:
            print(f"\n⚠ 跳过: {demo_dir.name} (未找到截图)")
            continue

        # 处理每个映射（每个query可能对应2个故障模式）
        for mapping in mappings:
            fault_mode = mapping.get('fault_mode', '')
            fault_mode_key = mapping.get('fault_mode_key', '')
            injection_config = mapping.get('injection_config', {})

            # 创建输出目录
            output_dir = output_base_dir / f"{demo_dir.name}_{fault_mode_key}"
            output_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n处理: {demo_dir.name} - {fault_mode}")

            try:
                # 初始化序列改写器
                rewriter = SequenceRewriter(
                    output_dir=output_dir,
                    gt_template_dir=Path(gt_template_dir) if gt_template_dir else None
                )

                # 执行序列改写
                injection_point = len(screenshots) // 2  # 在中间位置注入

                rewrite_result = rewriter.rewrite(
                    original_screenshots=screenshots,
                    injection_point=injection_point,
                    anomaly_type=injection_config.get('anomaly_mode'),
                    instruction=injection_config.get('instruction'),
                    decision_log={
                        'query': query,
                        'app_name': app_name,
                        'fault_mode': fault_mode,
                        'fault_mode_key': fault_mode_key,
                        'mapping': mapping
                    }
                )

                if rewrite_result['success']:
                    print(f"  ✓ 成功: 注入点={injection_point}, 生成图片={len(rewrite_result.get('anomaly_images', []))}")
                    
                    # ===== VLM 质量验证 =====
                    if enable_verification and rewrite_result.get('anomaly_images'):
                        print(f"\n  🔍 VLM 质量验证")
                        try:
                            verifier = QualityVerifier(
                                quality_threshold=quality_threshold,
                                max_retries=max_verification_retries
                            )
                            
                            base_screenshot = screenshots[injection_point]
                            verification_result = verifier.verify(
                                base_screenshot=base_screenshot,
                                generated_images=rewrite_result["anomaly_images"],
                                anomaly_type=injection_config.get('anomaly_mode'),
                                instruction=injection_config.get('instruction')
                            )
                            
                            # 打印验证结果
                            print(f"    通过: {'✓' if verification_result['passed'] else '✗'}")
                            print(f"    质量得分: {verification_result['quality_score']:.1f}/10")
                            print(f"    尝试次数: {verification_result['attempts']}")
                            
                            # 保存验证结果到元数据
                            rewrite_result["metadata"]["verification"] = {
                                "passed": verification_result["passed"],
                                "quality_score": verification_result["quality_score"],
                                "dimensions": verification_result["dimensions"],
                                "issues": verification_result["issues"],
                                "attempts": verification_result["attempts"],
                                "reasoning": verification_result["reasoning"]
                            }
                            
                            if not verification_result["passed"]:
                                print(f"    ⚠ 警告: 质量验证未通过")
                            
                        except Exception as e:
                            print(f"    ⚠ VLM 质量验证失败: {e}")
                    
                    total_processed += 1
                else:
                    print(f"  ✗ 失败: {rewrite_result.get('error', '未知错误')}")
                    total_failed += 1

            except Exception as e:
                print(f"  ✗ 异常: {e}")
                total_failed += 1
                import traceback
                traceback.print_exc()

    # 打印统计信息
    print("\n" + "="*60)
    print("批量处理完成")
    print("="*60)
    print(f"  成功: {total_processed}")
    print(f"  失败: {total_failed}")
    print(f"  总计: {total_processed + total_failed}")


def main():
    parser = argparse.ArgumentParser(
        description="批量异常注入（基于映射配置）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:

  # 处理所有故障模式（无验证）
  python batch_injection_with_mapping.py \\
    --examples-dir data/examples \\
    --output-dir output/batch_injection \\
    --mapping-config config/query_anomaly_mapping.json \\
    --gt-template-dir data/gt-category

  # 处理所有故障模式（启用VLM质量验证）
  python batch_injection_with_mapping.py \\
    --examples-dir data/examples \\
    --output-dir output/batch_injection \\
    --mapping-config config/query_anomaly_mapping.json \\
    --gt-template-dir data/gt-category \\
    --enable-verification

  # 只处理故障模式1（启用验证，自定义阈值）
  python batch_injection_with_mapping.py \\
    --examples-dir data/examples \\
    --output-dir output/batch_injection \\
    --mapping-config config/query_anomaly_mapping.json \\
    --fault-mode mode_1 \\
    --enable-verification \\
    --quality-threshold 7.0

  # 只处理故障模式2（启用验证，自定义重试次数）
  python batch_injection_with_mapping.py \\
    --examples-dir data/examples \\
    --output-dir output/batch_injection \\
    --mapping-config config/query_anomaly_mapping.json \\
    --fault-mode mode_2 \\
    --enable-verification \\
    --verification-retries 3
        """
    )

    parser.add_argument(
        '--examples-dir',
        type=str,
        required=True,
        help='examples目录路径'
    )

    parser.add_argument(
        '--output-dir',
        type=str,
        required=True,
        help='输出基础目录'
    )

    parser.add_argument(
        '--mapping-config',
        type=str,
        required=True,
        help='映射配置文件路径'
    )

    parser.add_argument(
        '--gt-template-dir',
        type=str,
        default=None,
        help='GT模板目录路径'
    )

    parser.add_argument(
        '--fault-mode',
        type=str,
        choices=['mode_1', 'mode_2'],
        default=None,
        help='指定处理的故障模式（mode_1或mode_2），不指定则处理所有'
    )

    parser.add_argument(
        '--enable-verification',
        action='store_true',
        help='启用VLM质量验证（默认禁用）'
    )

    parser.add_argument(
        '--no-verification',
        action='store_true',
        help='禁用VLM质量验证（默认禁用）'
    )

    parser.add_argument(
        '--quality-threshold',
        type=float,
        default=6.0,
        help='质量阈值，quality_score >= threshold 才算通过（默认 6.0）'
    )

    parser.add_argument(
        '--verification-retries',
        type=int,
        default=2,
        help='质量验证不通过时的最大重试次数（默认 2）'
    )

    args = parser.parse_args()

    # 处理验证参数
    enable_verification = args.enable_verification
    if args.no_verification:
        enable_verification = False

    batch_process(
        examples_dir=args.examples_dir,
        output_base_dir=args.output_dir,
        mapping_config_path=args.mapping_config,
        gt_template_dir=args.gt_template_dir,
        fault_mode_key=args.fault_mode,
        enable_verification=enable_verification,
        quality_threshold=args.quality_threshold,
        max_verification_retries=args.verification_retries
    )


if __name__ == '__main__':
    main()
