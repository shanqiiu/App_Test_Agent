"""
CLI命令行脚本 - 文本润色

使用方法：
    python scripts/refine.py --text "待润色的文本"           # 单文本润色
    python scripts/refine.py --file input.txt              # 从文件读取
    python scripts/refine.py --batch texts.json            # 批量润色
    python scripts/refine.py --provider deepseek           # 指定API提供商
"""

import sys
import os
import argparse
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config_loader import load_api_config, get_provider_config, ConfigError
from src.text_refiner import create_refiner, TextRefineError
from src.cost_tracker import CostTracker
from src.utils import (
    setup_logging,
    load_env_file,
    print_header,
    print_section,
    print_separator,
    get_timestamp
)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Text Refiner - 文本润色工具",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # 输入方式(互斥)
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument(
        "--text", "-t",
        type=str,
        default=None,
        help="直接输入待润色的文本"
    )
    input_group.add_argument(
        "--file", "-f",
        type=str,
        default=None,
        help="从文本文件读取内容"
    )
    input_group.add_argument(
        "--batch", "-b",
        type=str,
        default=None,
        help="批量模式：JSON文件路径(格式：[{\"id\": \"...\", \"text\": \"...\"}])"
    )

    parser.add_argument(
        "--config",
        type=str,
        default="config/api_config.json",
        help="API配置文件路径 (默认: config/api_config.json)"
    )

    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="API提供商名称 (默认使用配置文件中的active_provider)"
    )

    parser.add_argument(
        "--system-prompt", "-s",
        type=str,
        default=None,
        help="自定义系统提示词"
    )

    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="输出文件路径(仅单文本模式)"
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别 (默认: INFO)"
    )

    parser.add_argument(
        "--no-save",
        action="store_true",
        help="不保存结果到文件"
    )

    return parser.parse_args()


def read_text_file(file_path: str) -> str:
    """读取文本文件内容"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        raise ConfigError(f"File not found: {file_path}")
    except Exception as e:
        raise ConfigError(f"Failed to read file: {e}")


def read_batch_file(file_path: str) -> list:
    """读取批量任务文件"""
    import json
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 支持两种格式：直接数组或包含texts字段的对象
        if isinstance(data, list):
            texts = data
        elif isinstance(data, dict) and "texts" in data:
            texts = data["texts"]
        else:
            raise ConfigError("Invalid batch file format. Expected array or {texts: [...]}")

        # 验证格式
        for i, item in enumerate(texts):
            if "text" not in item:
                raise ConfigError(f"Missing 'text' field in item {i}")
            if "id" not in item:
                item["id"] = f"text_{i+1}"

        return texts

    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON: {e}")
    except FileNotFoundError:
        raise ConfigError(f"File not found: {file_path}")


def main():
    """主函数"""
    args = parse_args()

    # 设置日志
    logger = setup_logging(log_level=args.log_level)

    # 加载.env文件
    load_env_file()

    try:
        # 打印标题
        print_header("Text Refiner - 文本润色工具")

        # 1. 加载配置
        print("Loading configuration...")
        try:
            config = load_api_config(args.config)
            provider_name = args.provider or config["active_provider"]
            provider_config = get_provider_config(config, provider_name)

            print(f"  Provider: {provider_name}")
            print(f"  Model: {provider_config['model']}")
            print(f"  Cost per Request: ${provider_config.get('cost_per_request', 0):.4f}")
            print()

        except ConfigError as e:
            logger.error(f"Configuration error: {e}")
            sys.exit(1)

        # 2. 创建成本追踪器
        cost_tracker = CostTracker()

        # 3. 创建文本润色器
        output_config = config.get("output", {
            "text_dir": "outputs/texts",
            "report_dir": "outputs/reports"
        })

        refiner = create_refiner(
            provider_config=provider_config,
            cost_tracker=cost_tracker,
            output_config=output_config
        )

        # 4. 执行润色
        if args.text:
            # 直接输入文本模式
            print("Input text:")
            print(f"  '{args.text[:80]}{'...' if len(args.text) > 80 else ''}'")
            print()

            result = refiner.refine(
                text=args.text,
                system_prompt=args.system_prompt,
                task_id="cli_input",
                save_result=not args.no_save
            )

            _print_single_result(result, args.output)

        elif args.file:
            # 文件输入模式
            print(f"Reading from file: {args.file}")
            text = read_text_file(args.file)
            print(f"  Text length: {len(text)} characters")
            print()

            task_id = Path(args.file).stem
            result = refiner.refine(
                text=text,
                system_prompt=args.system_prompt,
                task_id=task_id,
                save_result=not args.no_save
            )

            _print_single_result(result, args.output)

        elif args.batch:
            # 批量模式
            print(f"Reading batch file: {args.batch}")
            texts = read_batch_file(args.batch)
            print(f"  Found {len(texts)} texts to refine")
            print()

            results = refiner.refine_batch(
                texts=texts,
                system_prompt=args.system_prompt
            )

            _print_batch_results(results, output_config)

        else:
            # 交互模式
            print("No input specified. Enter text to refine (Ctrl+D or empty line to finish):")
            print()

            lines = []
            try:
                while True:
                    line = input()
                    if not line:
                        break
                    lines.append(line)
            except EOFError:
                pass

            if not lines:
                print("No input provided.")
                sys.exit(0)

            text = "\n".join(lines)
            print()

            result = refiner.refine(
                text=text,
                system_prompt=args.system_prompt,
                task_id="interactive",
                save_result=not args.no_save
            )

            _print_single_result(result, args.output)

        # 5. 保存成本报告
        report_dir = output_config.get("report_dir", "outputs/reports")
        timestamp = get_timestamp()
        report_path = f"{report_dir}/refine_cost_{timestamp}.json"

        cost_tracker.save_report(report_path)

        # 6. 打印成本汇总
        print()
        print_separator("=", 60)
        print("Cost Summary".center(60))
        print_separator("=", 60)

        summary = cost_tracker.get_summary()
        print(f"Requests: {summary['total_images']}")
        print(f"Total Cost: ${summary['total_cost']:.4f}")
        print(f"Cost Report: {report_path}")
        print_separator("=", 60)

        logger.info("Text refinement completed successfully")

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)

    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


def _print_single_result(result: dict, output_path: str = None):
    """打印单个润色结果"""
    print()
    print_separator("=", 60)
    print("Refinement Result".center(60))
    print_separator("=", 60)

    if result["success"]:
        print("Status: SUCCESS")
        print(f"Time: {result['generation_time']:.2f}s")
        print(f"Cost: ${result['cost']:.4f}")
        print()
        print_separator("-", 60)
        print("Refined Text:")
        print_separator("-", 60)
        print(result["refined_text"])
        print_separator("-", 60)

        # 保存到指定文件
        if output_path:
            try:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(result["refined_text"])
                print(f"Output saved to: {output_path}")
            except Exception as e:
                print(f"Failed to save output: {e}")

        if "output_path" in result:
            print(f"Full result saved to: {result['output_path']}")

    else:
        print("Status: FAILED")
        print(f"Error: {result['error']}")

    print_separator("=", 60)


def _print_batch_results(results: list, output_config: dict):
    """打印批量润色结果汇总"""
    print()
    print_separator("=", 60)
    print("Batch Results".center(60))
    print_separator("=", 60)

    success_count = 0
    total_time = 0.0

    for result in results:
        task_id = result["task_id"]
        if result["success"]:
            print(f"  {task_id}: {result.get('output_path', 'N/A')} ({result['generation_time']:.2f}s)")
            success_count += 1
            total_time += result["generation_time"]
        else:
            print(f"  {task_id}: FAILED - {result['error']}")

    print_separator("=", 60)
    print(f"Summary: {success_count}/{len(results)} succeeded")

    if success_count > 0:
        avg_time = total_time / success_count
        print(f"Average time: {avg_time:.2f}s")

    print(f"Output directory: {output_config.get('text_dir', 'outputs/texts')}")
    print_separator("=", 60)


if __name__ == "__main__":
    main()
