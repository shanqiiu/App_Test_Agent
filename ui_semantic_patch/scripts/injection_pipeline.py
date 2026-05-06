#!/usr/bin/env python3
"""
injection_pipeline.py - 异常注入决策主入口

基于操作序列（UI截图序列）进行异常注入决策：
1. 增量式分析截图序列，决策注入点和异常类型
2. 用户确认（可选）
3. 调用已有生成器生成异常截图
4. 改写序列并输出

用法：
    python injection_pipeline.py \\
        --input-dir examples/injection_demo \\
        --output-dir output/injected \\
        --interactive

输入目录结构：
    input/
    ├── task.json           # {"description": "任务描述"}
    └── screenshots/
        ├── step_00.png
        ├── step_01.png
        └── ...
"""

import logging
import os
import sys
import json
import argparse
from pathlib import Path

# 设置 UTF-8 编码输出（Windows 兼容）
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 确保能导入 app 模块（将项目根目录加入 Python 路径）
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 自动加载项目根目录的 .env 文件
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parents[2] / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv 未安装，使用系统环境变量
from typing import List, Optional

# 确保能导入本地模块
sys.path.insert(0, str(Path(__file__).parent))

from app.injection import SequenceAnalyzer, AnomalyRecommender, SequenceRewriter, QualityVerifier
from app.utils.logging_utils import setup_logging


def load_task(input_dir: Path) -> dict:
    """加载任务配置"""
    task_file = input_dir / "task.json"
    if task_file.exists():
        with open(task_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"description": "未指定任务描述"}


def load_screenshots(input_dir: Path) -> List[Path]:
    """加载截图序列"""
    screenshots_dir = input_dir / "screenshots"
    if not screenshots_dir.exists():
        # 尝试直接从 input_dir 加载
        screenshots_dir = input_dir

    image_extensions = {'.png', '.jpg', '.jpeg', '.webp'}
    screenshots = []

    for f in screenshots_dir.iterdir():
        if f.is_file() and f.suffix.lower() in image_extensions:
            screenshots.append(f)

    # 按文件名排序
    screenshots.sort(key=lambda x: x.name)
    return screenshots


def user_confirm(
    injection_point: int,
    anomaly_type: str,
    instruction: str,
    reasoning: str,
    available_categories: List[str]
) -> dict:
    """
    用户确认交互

    Returns:
        {
            "confirmed": True/False,
            "anomaly_type": str,  # 可能被用户修改
            "instruction": str    # 可能被用户修改
        }
    """
    print("\n" + "="*60)
    print("📋 异常注入决策结果")
    print("="*60)
    print(f"\n注入位置: Step {injection_point}")
    print(f"推荐异常: {anomaly_type}")
    print(f"生成指令: {instruction}")
    print(f"\n决策理由:\n{reasoning[:300]}..." if len(reasoning) > 300 else f"\n决策理由:\n{reasoning}")
    print("\n" + "-"*60)

    print("\n请选择操作:")
    print("  [1] 确认并继续")
    print("  [2] 更换异常类型")
    print("  [3] 修改生成指令")
    print("  [4] 取消注入")

    while True:
        choice = input("\n请输入选项 (1/2/3/4): ").strip()

        if choice == "1":
            return {
                "confirmed": True,
                "anomaly_type": anomaly_type,
                "instruction": instruction
            }

        elif choice == "2":
            print("\n可用的异常类型:")
            for i, cat in enumerate(available_categories, 1):
                print(f"  [{i}] {cat}")

            cat_choice = input("\n请选择异常类型编号: ").strip()
            try:
                idx = int(cat_choice) - 1
                if 0 <= idx < len(available_categories):
                    new_type = available_categories[idx]
                    new_instruction = input(f"请输入生成指令 (回车保持原指令): ").strip()
                    return {
                        "confirmed": True,
                        "anomaly_type": new_type,
                        "instruction": new_instruction if new_instruction else instruction
                    }
            except ValueError:
                pass
            print("⚠ 无效选择，请重试")

        elif choice == "3":
            new_instruction = input("请输入新的生成指令: ").strip()
            if new_instruction:
                return {
                    "confirmed": True,
                    "anomaly_type": anomaly_type,
                    "instruction": new_instruction
                }
            print("⚠ 指令不能为空")

        elif choice == "4":
            return {
                "confirmed": False,
                "anomaly_type": anomaly_type,
                "instruction": instruction
            }

        else:
            print("⚠ 无效选项，请重试")


def main():
    parser = argparse.ArgumentParser(
        description="异常注入决策流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 交互式模式
    python injection_pipeline.py --input-dir examples/injection_demo --output-dir output/injected

    # 非交互式模式（自动确认）
    python injection_pipeline.py --input-dir examples/injection_demo --output-dir output/injected --no-interactive

    # 禁用 VLM 质量验证
    python injection_pipeline.py --input-dir examples/injection_demo --output-dir output/injected --no-verification

    # 自定义质量阈值和重试次数
    python injection_pipeline.py --input-dir examples/injection_demo --output-dir output/injected --quality-threshold 7.0 --verification-retries 3

    # 指定任务描述
    python injection_pipeline.py --input-dir ./screenshots --output-dir ./output --task "在携程预订酒店"
        """
    )

    parser.add_argument(
        "--input-dir", "-i",
        type=str,
        required=True,
        help="输入目录，包含 task.json 和 screenshots/"
    )

    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        required=True,
        help="输出目录"
    )

    parser.add_argument(
        "--task", "-t",
        type=str,
        default=None,
        help="任务描述（覆盖 task.json 中的描述）"
    )

    parser.add_argument(
        "--interactive",
        action="store_true",
        default=True,
        help="启用用户确认（默认启用）"
    )

    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="禁用用户确认，自动执行"
    )

    parser.add_argument(
        "--gt-template-dir",
        type=str,
        default=None,
        help="GT 模板目录路径"
    )

    parser.add_argument(
        "--mock",
        action="store_true",
        help="启用 Mock 模式，不调用生成模型 API，使用预置结果"
    )

    parser.add_argument(
        "--mock-config",
        type=str,
        default=None,
        help="Mock 配置文件路径（JSON），不指定则使用内置默认配置"
    )

    parser.add_argument(
        "--max-history",
        type=int,
        default=10,
        help="最大历史步数（默认 10）"
    )

    parser.add_argument(
        "--min-steps",
        type=int,
        default=2,
        help="最少分析步数后才考虑注入（默认 2）"
    )

    parser.add_argument(
        "--no-verification",
        action="store_true",
        help="跳过 VLM 质量验证（默认启用验证）"
    )

    parser.add_argument(
        "--verification-retries",
        type=int,
        default=2,
        help="质量验证不通过时的最大重试次数（默认 2）"
    )

    parser.add_argument(
        "--quality-threshold",
        type=float,
        default=6.0,
        help="质量阈值，quality_score >= threshold 才算通过（默认 6.0）"
    )

    args = parser.parse_args()

    # 处理交互模式参数
    interactive = not args.no_interactive
    mock_mode = args.mock

    # 路径处理
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    gt_template_dir = Path(args.gt_template_dir) if args.gt_template_dir else None

    if not input_dir.exists():
        print(f"❌ 输入目录不存在: {input_dir}")
        sys.exit(1)

    # ===== 配置日志 =====
    logger = logging.getLogger(__name__)
    output_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(log_dir=str(output_dir), log_name="injection_pipeline")
    logger.info("日志文件: %s", output_dir / "injection_pipeline.log")

    # 加载任务和截图
    task = load_task(input_dir)
    task_description = args.task or task.get("description", "未指定任务")

    screenshots = load_screenshots(input_dir)
    if not screenshots:
        logger.error("❌ 未找到截图文件: %s", input_dir)
        sys.exit(1)

    logger.info("")
    logger.info("%s", "="*60)
    logger.info("🚀 异常注入决策流水线")
    logger.info("%s", "="*60)
    logger.info("")
    logger.info("输入目录: %s", input_dir)
    logger.info("输出目录: %s", output_dir)
    logger.info("任务描述: %s", task_description)
    logger.info("截图数量: %d", len(screenshots))
    logger.info("交互模式: %s", '启用' if interactive else '禁用')
    if mock_mode:
        print(f"Mock 模式: 启用")
        if args.mock_config:
            print(f"Mock 配置: {args.mock_config}")

    # 初始化组件
    print("\n初始化组件...")

    try:
        recommender = AnomalyRecommender(gt_template_dir)
        print(f"  ✓ 异常推荐器: {len(recommender.get_available_categories())} 个类别")

        # 语义分析器：始终使用真实 VLM（多模态视觉理解）
        analyzer = SequenceAnalyzer(
            recommender=recommender,
            task_description=task_description,
            max_history_steps=args.max_history,
            min_steps_before_inject=args.min_steps
        )
        print(f"  ✓ 语义分析器 (VLM)")

        if mock_mode:
            # Mock 模式：仅 mock 生成器（不调用 run_pipeline.py 生成异常图片）
            mock_config = MockConfig(args.mock_config)
            rewriter = MockSequenceRewriter(
                output_dir=output_dir,
                gt_template_dir=gt_template_dir,
                mock_config=mock_config
            )
            print(f"  ✓ 序列改写器 [Mock — 跳过图像生成]")
        else:
            # 正常模式：调用 run_pipeline.py 生成异常图片
            rewriter = SequenceRewriter(
                output_dir=output_dir,
                gt_template_dir=gt_template_dir
            )
            print(f"  ✓ 序列改写器")

    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        sys.exit(1)

    # 执行分析
    print("\n开始分析...")
    result = analyzer.run(screenshots)

    if not result["success"]:
        print("\n❌ 未找到合适的注入点")
        print(f"分析历史已保存到决策日志")

        # 保存历史记录
        output_dir.mkdir(parents=True, exist_ok=True)
        log_path = output_dir / "decision_log_no_injection.json"
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"日志: {log_path}")
        sys.exit(0)

    # 用户确认
    injection_point = result["injection_point"]
    anomaly_type = result["anomaly_type"]
    instruction = result["instruction"]
    reasoning = result["reasoning"]

    if interactive:
        confirm_result = user_confirm(
            injection_point=injection_point,
            anomaly_type=anomaly_type,
            instruction=instruction,
            reasoning=reasoning,
            available_categories=recommender.get_available_categories()
        )

        if not confirm_result["confirmed"]:
            print("\n❌ 用户取消注入")
            sys.exit(0)

        # 使用用户确认/修改后的值
        anomaly_type = confirm_result["anomaly_type"]
        instruction = confirm_result["instruction"]

    # 执行序列改写
    print("\n执行序列改写...")

    # ===== VLM 质量验证配置 =====
    max_verification_retries = args.verification_retries if hasattr(args, 'verification_retries') else 2
    quality_threshold = args.quality_threshold if hasattr(args, 'quality_threshold') else 6.0

    try:
        rewrite_result = rewriter.rewrite(
            original_screenshots=screenshots,
            injection_point=injection_point,
            anomaly_type=anomaly_type,
            instruction=instruction,
            decision_log=result
        )

        if not rewrite_result["success"]:
            print("\n❌ 序列改写失败")
            sys.exit(1)

        print(f"\n原始序列: {rewrite_result['original_length']} 步")
        print(f"改写序列: {rewrite_result['modified_length']} 步")
        print(f"异常截图: {len(rewrite_result['anomaly_images'])} 张")

        # ===== VLM 质量验证 =====
        if not args.no_verification:
            print("\n" + "="*60)
            print("🔍 VLM 质量验证")
            print("="*60)

            try:
                verifier = QualityVerifier(
                    quality_threshold=quality_threshold,
                    max_retries=max_verification_retries
                )

                base_screenshot = screenshots[injection_point]
                verification_result = verifier.verify(
                    base_screenshot=base_screenshot,
                    generated_images=rewrite_result["anomaly_images"],
                    anomaly_type=anomaly_type,
                    instruction=instruction
                )

                # 打印验证结果
                print(f"\n验证结果:")
                print(f"  通过: {'✓' if verification_result['passed'] else '✗'}")
                print(f"  质量得分: {verification_result['quality_score']:.1f}/10")
                print(f"  异常存在: {'✓' if verification_result['dimensions'].get('anomaly_present') else '✗'}")
                print(f"  语义一致: {'✓' if verification_result['dimensions'].get('semantic_match') else '✗'}")
                print(f"  视觉质量: {verification_result['dimensions'].get('visual_quality', 0):.1f}")
                print(f"  自然度: {verification_result['dimensions'].get('naturalness', 0):.1f}")
                print(f"  尝试次数: {verification_result['attempts']}")
                if verification_result.get('issues'):
                    print(f"  问题: {'; '.join(verification_result['issues'])}")

                # 保存验证结果到元数据
                rewrite_result["metadata"]["verification"] = {
                    "passed": verification_result["passed"],
                    "quality_score": verification_result["quality_score"],
                    "dimensions": verification_result["dimensions"],
                    "issues": verification_result["issues"],
                    "attempts": verification_result["attempts"],
                    "reasoning": verification_result["reasoning"]
                }

                # 验证未通过时记录警告
                if not verification_result["passed"]:
                    print(f"\n⚠ 警告: 质量验证未通过 (score={verification_result['quality_score']:.1f})")
                    print(f"  将继续使用当前结果（可配置重试次数或降级策略）")

            except Exception as e:
                print(f"\n⚠ VLM 质量验证失败: {e}")
                print(f"  将继续使用当前结果")
                import traceback
                traceback.print_exc()
        else:
            print("\nℹ 跳过 VLM 质量验证")

        print("\n" + "="*60)
        print("✅ 异常注入完成!")
        print("="*60)
        print(f"\n输出目录: {rewrite_result['output_path']}")

    except Exception as e:
        print(f"\n❌ 序列改写失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
