"""
CLI命令行脚本 - 生成异常UI截图

使用方法：
    python scripts/generate.py                          # 生成所有测试场景
    python scripts/generate.py --provider qwen          # 指定API提供商
    python scripts/generate.py --prompt "自定义提示词"   # 单张生成
"""

import sys
import os
import argparse
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config_loader import load_api_config, load_test_scenarios, get_provider_config, ConfigError
from src.image_generator import create_generator
from src.cost_tracker import CostTracker
from src.utils import (
    setup_logging,
    load_env_file,
    print_header,
    print_section,
    print_separator,
    get_timestamp,
    format_time
)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Model API Use Spike - 云端文生图API验证",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "--config",
        type=str,
        default="config/api_config.json",
        help="API配置文件路径 (默认: config/api_config.json)"
    )

    parser.add_argument(
        "--scenarios",
        type=str,
        default="config/test_scenarios.json",
        help="测试场景配置文件路径 (默认: config/test_scenarios.json)"
    )

    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="API提供商名称 (flux, qwen等, 默认使用配置文件中的active_provider)"
    )

    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="自定义提示词(单张生成模式)"
    )

    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出图像路径(仅单张生成模式)"
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别 (默认: INFO)"
    )

    return parser.parse_args()


def main():
    """主函数"""
    args = parse_args()

    # 设置日志
    logger = setup_logging(log_level=args.log_level)

    # 加载.env文件(如果存在)
    load_env_file()

    try:
        # 打印标题
        print_header("Model API Use Spike - API验证")

        # 1. 加载配置
        print("Loading configuration...")
        try:
            config = load_api_config(args.config)
            provider_name = args.provider or config["active_provider"]
            provider_config = get_provider_config(config, provider_name)

            print(f"  Active Provider: {provider_name}")
            print(f"  Model: {provider_config['model']}")
            print(f"  Cost per Image: ${provider_config['cost_per_image']:.4f}")
            print()

        except ConfigError as e:
            logger.error(f"Configuration error: {e}")
            sys.exit(1)

        # 2. 创建成本追踪器
        cost_tracker = CostTracker()

        # 3. 创建图像生成器
        try:
            output_config = config.get("output", {
                "image_dir": "outputs/images",
                "metadata_dir": "outputs/metadata",
                "report_dir": "outputs/reports"
            })

            generator = create_generator(
                provider_name=provider_name,
                provider_config=provider_config,
                cost_tracker=cost_tracker,
                output_config=output_config
            )

        except Exception as e:
            logger.error(f"Failed to create generator: {e}")
            sys.exit(1)

        # 4. 生成图像
        if args.prompt:
            # 单张生成模式
            print(f"Generating single image with prompt:")
            print(f"  '{args.prompt[:80]}{'...' if len(args.prompt) > 80 else ''}'")
            print()

            scenario = {
                "id": "custom",
                "prompt": args.prompt,
                "title": "Custom prompt"
            }

            result = generator.generate_single(scenario, save_image=True)

            if result["success"]:
                print(f"\n✓ Image generated successfully!")
                print(f"  Path: {result.get('image_path', 'N/A')}")
                print(f"  Time: {result['generation_time']:.2f}s")
                print(f"  Cost: ${result['cost']:.4f}")
            else:
                print(f"\n✗ Generation failed: {result['error']}")
                sys.exit(1)

        else:
            # 批量生成模式
            try:
                scenarios = load_test_scenarios(args.scenarios)
                print(f"Loading test prompts...")
                print(f"Found {len(scenarios)} test scenarios")
                print()

            except ConfigError as e:
                logger.error(f"Scenarios error: {e}")
                sys.exit(1)

            # 批量生成
            results = generator.generate_batch(scenarios)

            # 5. 打印结果汇总
            print()
            print_separator("=", 60)
            print("Generation Results".center(60))
            print_separator("=", 60)

            success_count = 0
            total_time = 0.0

            for result in results:
                scenario_id = result["scenario_id"]
                if result["success"]:
                    print(f"✅ {scenario_id}: {result.get('image_path', 'N/A')} ({result['generation_time']:.2f}s)")
                    success_count += 1
                    total_time += result["generation_time"]
                else:
                    print(f"❌ {scenario_id}: {result['error']}")

            print_separator("=", 60)
            print(f"Summary: {success_count}/{len(results)} succeeded")

            if success_count > 0:
                avg_time = total_time / success_count
                print(f"Average generation time: {avg_time:.2f}s")

            print(f"Output directory: {output_config.get('image_dir', 'outputs/images')}")
            print_separator("=", 60)

        # 6. 保存成本报告
        report_dir = output_config.get("report_dir", "outputs/reports")
        timestamp = get_timestamp()
        report_path = f"{report_dir}/cost_report_{timestamp}.json"

        cost_tracker.save_report(report_path)

        # 7. 打印成本汇总
        print()
        print_separator("=", 60)
        print("Cost Summary".center(60))
        print_separator("=", 60)

        summary = cost_tracker.get_summary()
        print(f"✅ {summary['total_images']} images generated")
        print(f"💰 Total Cost: ${summary['total_cost']:.4f}")
        print(f"📊 Cost Report: {report_path}")
        print_separator("=", 60)

        logger.info("Generation completed successfully")

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)

    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
