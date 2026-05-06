#!/usr/bin/env python3
"""
batch_injection_with_mapping.py - 批量异常注入脚本（规则引擎版）

使用规则引擎 + VLM 页面分类，智能决定注入点和异常类型。
替代旧的固定中间位置注入策略。

核心变更：
  - 旧：len(screenshots)//2 （无语义）
  - 新：VLM 页面分类 → 规则引擎匹配 → 语义合理的注入点
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
from app.injection.page_classifier import PageClassifier
from app.injection.rule_engine import RuleEngine
from app.injection.sequence_analyzer import SequenceAnalyzer


def load_mapping_config(config_path: str) -> Dict:
    """加载映射配置"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def batch_process(
    examples_dir: str,
    output_base_dir: str,
    mapping_config_path: str,
    gt_template_dir: str = None,
    fault_mode_key: str = None,
    enable_verification: bool = False,
    quality_threshold: float = 6.0,
    max_verification_retries: int = 2,
    enable_rules: bool = True,  # 是否启用规则引擎（False = 回退到旧中间位置）
):
    """
    批量处理异常注入

    Args:
        examples_dir: examples目录路径
        output_base_dir: 输出基础目录
        mapping_config_path: 映射配置文件路径
        gt_template_dir: GT模板目录
        fault_mode_key: 指定处理的故障模式
        enable_verification: 是否启用VLM质量验证
        quality_threshold: 质量阈值
        max_verification_retries: 最大验证重试次数
        enable_rules: 是否启用规则引擎决定注入点
    """
    examples_dir = Path(examples_dir)
    output_base_dir = Path(output_base_dir)

    # 加载映射配置
    print(f"\n加载映射配置: {mapping_config_path}")
    mapping_config = load_mapping_config(mapping_config_path)
    print(f"  总映射数: {len(mapping_config.get('mappings', []))}")
    print(f"  统计: {mapping_config.get('statistics', {})}")

    # 初始化公共组件
    resolver = AnomalyMappingResolver(mapping_config_path)

    if enable_rules:
        # 初始化规则引擎 + 页面分类器
        rules_path = Path(__file__).parent.parent / "app" / "injection" / "rules.json"
        rule_engine = RuleEngine(str(rules_path) if rules_path.exists() else None)
        page_classifier = PageClassifier()
        print(f"\n✓ 已启用规则引擎决策")
    else:
        rule_engine = None
        page_classifier = None
        print(f"\n- 未启用规则引擎，使用旧中间位置策略")

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

        # ===== 规则引擎决定注入点（全局一次，跨所有 fault_mode） =====
        if enable_rules and rule_engine and page_classifier:
            print(f"\n--- 语义分析: {demo_dir.name} ---")
            analyzer = SequenceAnalyzer(
                rule_engine=rule_engine,
                page_classifier=page_classifier,
                task_description=query,
                min_steps_before_inject=2
            )
            decision = analyzer.run(screenshots)
            injection_point = decision.get("injection_point", len(screenshots) // 2)
            print(f"  => 注入点: Step {injection_point}")
        else:
            injection_point = len(screenshots) // 2
            decision = None

        # 处理每个映射（每个query可能对应2个故障模式）
        for mapping in mappings:
            fault_mode = mapping.get('fault_mode', '')
            current_fault_mode_key = mapping.get('fault_mode_key', '')
            injection_config = mapping.get('injection_config', {})

            # 创建输出目录
            output_dir = output_base_dir / f"{demo_dir.name}_{current_fault_mode_key}"
            output_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n处理: {demo_dir.name} - {fault_mode}")

            try:
                # 初始化序列改写器
                rewriter = SequenceRewriter(
                    output_dir=output_dir,
                    gt_template_dir=Path(gt_template_dir) if gt_template_dir else None
                )

                # 异常参数：始终使用映射配置（WHAT），规则引擎只决定注入点（WHERE）
                anomaly_mode = injection_config.get('anomaly_mode')
                instruction = injection_config.get('instruction')
                gt_category = injection_config.get('gt_category', '')
                gt_sample = injection_config.get('gt_sample', '')
                if decision and decision.get("success"):
                    print(f"  [注入点] 规则引擎: Step {injection_point} "
                          f"(规则: {decision.get('matched_rule_id', '?')})")
                else:
                    print(f"  [注入点] 中间位置: Step {injection_point}")

                rewrite_result = rewriter.rewrite(
                    original_screenshots=screenshots,
                    injection_point=injection_point,
                    anomaly_type=anomaly_mode,
                    instruction=instruction,
                    gt_sample=gt_sample,
                    gt_category=gt_category,
                    decision_log={
                        'query': query,
                        'app_name': app_name,
                        'fault_mode': fault_mode,
                        'fault_mode_key': current_fault_mode_key,
                        'mapping': mapping,
                        'rule_decision': decision
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
                                anomaly_type=anomaly_mode,
                                instruction=instruction
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


def find_mappings_for_query(query: str, app_name: str, mapping_config: Dict) -> List[Dict]:
    """查找query对应的所有映射"""
    mappings = []
    for mapping in mapping_config.get('mappings', []):
        if mapping.get('query') == query:
            mappings.append(mapping)
    return mappings


def main():
    parser = argparse.ArgumentParser(
        description="批量异常注入（规则引擎版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:

  # 使用规则引擎（默认）
  python batch_injection_with_mapping.py \\
    --examples-dir data/examples \\
    --output-dir output/batch_injection \\
    --mapping-config config/query_anomaly_mapping.json \\
    --gt-template-dir data/gt-category

  # 回退到旧中间位置策略
  python batch_injection_with_mapping.py \\
    --examples-dir data/examples \\
    --output-dir output/batch_injection \\
    --mapping-config config/query_anomaly_mapping.json \\
    --gt-template-dir data/gt-category \\
    --no-rules
        """
    )

    parser.add_argument('--examples-dir', type=str, required=True, help='examples目录路径')
    parser.add_argument('--output-dir', type=str, required=True, help='输出基础目录')
    parser.add_argument('--mapping-config', type=str, required=True, help='映射配置文件路径')
    parser.add_argument('--gt-template-dir', type=str, default=None, help='GT模板目录路径')
    parser.add_argument('--fault-mode', type=str, choices=['mode_1', 'mode_2'], default=None,
                        help='指定处理的故障模式（mode_1或mode_2），不指定则处理所有')
    parser.add_argument('--enable-verification', action='store_true', help='启用VLM质量验证（默认禁用）')
    parser.add_argument('--no-verification', action='store_true', help='禁用VLM质量验证')
    parser.add_argument('--quality-threshold', type=float, default=6.0, help='质量阈值（默认 6.0）')
    parser.add_argument('--verification-retries', type=int, default=2, help='质量验证最大重试次数（默认 2）')
    parser.add_argument('--no-rules', action='store_true', help='禁用规则引擎，回退到旧中间位置策略')

    args = parser.parse_args()

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
        max_verification_retries=args.verification_retries,
        enable_rules=not args.no_rules,
    )


if __name__ == '__main__':
    main()
