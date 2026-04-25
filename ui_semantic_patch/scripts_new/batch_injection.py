#!/usr/bin/env python3
"""
batch_injection.py - 批量异常注入执行器

并发执行多个 injection_pipeline.py 任务，充分利用多核 CPU 和 API 并发能力。

用法:
    python batch_injection.py \\
        --input-dir ../data/examples \\
        --output-dir ../output/batch_injected \\
        --workers 4

    # 禁用 VLM 质量验证加速
    python batch_injection.py \\
        --input-dir ../data/examples \\
        --output-dir ../output/batch_injected \\
        --no-verification

    # 干跑（仅列任务不执行）
    python batch_injection.py --input-dir ../data/examples --dry-run
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


# 设置 UTF-8 编码输出（Windows 兼容）
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


@dataclass
class TaskResult:
    """单个任务执行结果"""
    task_name: str
    success: bool
    exit_code: int
    duration: float  # 秒
    output_path: Optional[Path] = None
    error: Optional[str] = None
    retry_count: int = 0


@dataclass
class BatchResult:
    """批量执行总结果"""
    total: int
    success: int
    failed: int
    skipped: int
    total_duration: float  # 秒
    total_wall_time: float  # 墙钟时间
    task_results: List[TaskResult] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"批量执行完成: {self.success}/{self.total} 成功, "
            f"{self.failed} 失败, {self.skipped} 跳过 | "
            f"总计耗时 {self.total_duration:.1f}s, "
            f"墙钟时间 {self.total_wall_time:.1f}s, "
            f"加速比 {self.total_duration/max(self.total_wall_time, 0.01):.1f}x"
        )


def scan_tasks(input_dir: Path, require_task_json: bool = True) -> List[Path]:
    """
    扫描输入目录，找出所有可执行的任务目录

    Args:
        input_dir: 数据根目录（每个子目录是一个任务，截图在 screenshots/ 子目录）
        require_task_json: 是否要求存在 task.json

    Returns:
        任务目录路径列表
    """
    if not input_dir.exists():
        raise FileNotFoundError(f"输入目录不存在: {input_dir}")

    tasks = []
    image_extensions = {'.png', '.jpg', '.jpeg', '.webp'}

    for subdir in sorted(input_dir.iterdir()):
        if not subdir.is_dir():
            continue
        if require_task_json and not (subdir / 'task.json').exists():
            continue
        # 检查 screenshots/ 子目录中是否有截图
        screenshots_dir = subdir / 'screenshots'
        if screenshots_dir.exists():
            has_images = any(
                f.suffix.lower() in image_extensions
                for f in screenshots_dir.iterdir() if f.is_file()
            )
        else:
            # 兼容：截图直接在子目录
            has_images = any(
                f.suffix.lower() in image_extensions and f.is_file()
                for f in subdir.iterdir()
            )
        if has_images:
            tasks.append(subdir)

    return tasks


def run_single_task(
    task_dir: Path,
    output_dir: Path,
    script_path: Path,
    pipeline_args: List[str],
    env: Dict[str, str]
) -> TaskResult:
    """
    执行单个 injection_pipeline.py 任务

    Args:
        task_dir: 任务输入目录
        output_dir: 批量输出根目录（每个任务创建子目录）
        script_path: injection_pipeline.py 脚本路径
        pipeline_args: 传递给 pipeline 的额外参数
        env: 环境变量

    Returns:
        任务执行结果
    """
    start_time = time.time()
    task_name = task_dir.name
    task_output_dir = output_dir / task_name

    # 构建命令
    cmd = [
        sys.executable,
        str(script_path),
        "--input-dir", str(task_dir),
        "--output-dir", str(task_output_dir),
        "--no-interactive",  # 批量模式强制非交互
    ] + pipeline_args

    try:
        result = subprocess.run(
            cmd,
            env=env,
            cwd=str(script_path.parent),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=1800  # 单任务超时 30 分钟
        )

        duration = time.time() - start_time

        # 检查输出目录是否生成
        output_path = None
        if task_output_dir.exists():
            # 查找生成的目录
            subdirs = [d for d in task_output_dir.iterdir() if d.is_dir() and d.name.startswith('injection_')]
            if subdirs:
                output_path = subdirs[0]

        success = result.returncode == 0
        error = None
        if not success:
            # 只保留最后 500 字符的错误信息
            error = (result.stderr or result.stdout or '')[-500:]

        return TaskResult(
            task_name=task_name,
            success=success,
            exit_code=result.returncode,
            duration=duration,
            output_path=output_path,
            error=error,
            retry_count=0
        )

    except subprocess.TimeoutExpired:
        return TaskResult(
            task_name=task_name,
            success=False,
            exit_code=-1,
            duration=time.time() - start_time,
            error=f"任务执行超时 (30分钟)",
            retry_count=0
        )
    except Exception as e:
        return TaskResult(
            task_name=task_name,
            success=False,
            exit_code=-2,
            duration=time.time() - start_time,
            error=str(e),
            retry_count=0
        )


def run_batch(
    tasks: List[Path],
    output_dir: Path,
    script_path: Path,
    workers: int,
    pipeline_args: List[str],
    env: Dict[str, str],
    use_threads: bool = False,
    rate_limit_delay: float = 0.5,
    progress_callback=None
) -> BatchResult:
    """
    批量执行任务

    Args:
        tasks: 任务目录列表
        output_dir: 输出根目录
        script_path: 脚本路径
        workers: 并发 worker 数
        pipeline_args: pipeline 额外参数
        env: 环境变量
        use_threads: True=线程池, False=进程池
        rate_limit_delay: 任务间最小间隔（秒），用于 API 限流保护
        progress_callback: 进度回调 (completed, total)

    Returns:
        批量执行结果
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    total_start = time.time()
    task_results: List[TaskResult] = []
    total_duration = 0.0
    success_count = 0
    failed_count = 0
    skipped_count = 0

    executor_class = ThreadPoolExecutor if use_threads else ProcessPoolExecutor

    print(f"\n{'='*60}")
    print(f"开始批量执行: {len(tasks)} 任务, 并发数={workers}")
    print(f"{'='*60}\n")

    completed = 0
    with executor_class(max_workers=workers) as executor:
        # 提交所有任务
        future_to_task = {
            executor.submit(
                run_single_task,
                task_dir,
                output_dir,
                script_path,
                pipeline_args,
                env
            ): task_dir
            for task_dir in tasks
        }

        # 收集结果（按完成顺序）
        for future in as_completed(future_to_task):
            task_dir = future_to_task[future]
            try:
                result = future.result()
            except Exception as e:
                result = TaskResult(
                    task_name=task_dir.name,
                    success=False,
                    exit_code=-3,
                    duration=0.0,
                    error=f"Future 执行异常: {e}",
                    retry_count=0
                )

            task_results.append(result)
            total_duration += result.duration

            if result.success:
                success_count += 1
                status = "✅"
            else:
                failed_count += 1
                status = "❌"

            completed += 1

            print(f"[{completed}/{len(tasks)}] {status} {result.task_name} "
                  f"({result.duration:.1f}s)"
                  + (f" → {result.output_path}" if result.output_path else "")
            )

            if not result.success and result.error:
                print(f"      错误: {result.error[:200]}...")

            if progress_callback:
                progress_callback(completed, len(tasks))

            # API 限流保护：任务间添加延迟
            if rate_limit_delay > 0 and completed < len(tasks):
                time.sleep(rate_limit_delay)

    wall_time = time.time() - total_start

    return BatchResult(
        total=len(tasks),
        success=success_count,
        failed=failed_count,
        skipped=skipped_count,
        total_duration=total_duration,
        total_wall_time=wall_time,
        task_results=task_results
    )


def save_results(result: BatchResult, output_dir: Path) -> None:
    """保存执行结果"""
    # 保存详细 JSON
    result_file = output_dir / "batch_results.json"
    result_data = {
        "timestamp": datetime.now().isoformat(),
        "summary": result.summary(),
        "total": result.total,
        "success": result.success,
        "failed": result.failed,
        "skipped": result.skipped,
        "total_duration": round(result.total_duration, 2),
        "total_wall_time": round(result.total_wall_time, 2),
        "speedup": round(result.total_duration / max(result.total_wall_time, 0.01), 2),
        "tasks": [
            {
                "task_name": r.task_name,
                "success": r.success,
                "exit_code": r.exit_code,
                "duration": round(r.duration, 2),
                "output_path": str(r.output_path) if r.output_path else None,
                "error": r.error,
                "retry_count": r.retry_count
            }
            for r in result.task_results
        ]
    }
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {result_file}")

    # 保存成功/失败列表
    success_file = output_dir / "batch_success.txt"
    failed_file = output_dir / "batch_failed.txt"

    with open(success_file, 'w', encoding='utf-8') as f:
        for r in result.task_results:
            if r.success:
                f.write(f"{r.task_name}\n")

    with open(failed_file, 'w', encoding='utf-8') as f:
        for r in result.task_results:
            if not r.success:
                f.write(f"{r.task_name}: {r.error or 'unknown'}\n")


def main():
    parser = argparse.ArgumentParser(
        description="批量异常注入执行器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 4 个并发 worker（默认）
    python batch_injection.py --input-dir ../data/examples --output-dir ../output/batch

    # 8 个并发 worker（需要 API 容量支持）
    python batch_injection.py --input-dir ../data/examples --output-dir ../output/batch --workers 8

    # 禁用验证加速执行
    python batch_injection.py --input-dir ../data/examples --output-dir ../output/batch --no-verification

    # 线程池（Windows 友好，共享 API 连接池）
    python batch_injection.py --input-dir ../data/examples --output-dir ../output/batch --use-threads

    # 干跑（只列出任务，不执行）
    python batch_injection.py --input-dir ../data/examples --dry-run

并发策略说明:
    - 默认使用 ProcessPoolExecutor（进程池），绕过 GIL，CPU 密集型任务（如 OmniParser）效率高
    - --use-threads 使用 ThreadPoolExecutor（线程池），I/O 密集型任务（如 VLM API 调用）更友好
    - --rate-limit-delay 控制任务间隔，避免 API 限流
"""
    )

    parser.add_argument(
        "--input-dir", "-i",
        type=str,
        required=True,
        help="数据根目录（包含多个任务子目录）"
    )

    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        required=True,
        help="批量输出根目录"
    )

    parser.add_argument(
        "--script",
        type=str,
        default=None,
        help="injection_pipeline.py 脚本路径（默认自动查找）"
    )

    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=4,
        help="并发 worker 数（默认 4）"
    )

    parser.add_argument(
        "--use-threads",
        action="store_true",
        help="使用线程池而非进程池（Windows 推荐，避免进程创建开销）"
    )

    parser.add_argument(
        "--rate-limit-delay",
        type=float,
        default=0.5,
        help="任务间最小延迟（秒），避免 API 限流（默认 0.5）"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只列出任务，不执行"
    )

    # ===== 透传给 injection_pipeline.py 的参数 =====
    parser.add_argument(
        "--no-verification",
        action="store_true",
        help="跳过 VLM 质量验证（加速执行）"
    )

    parser.add_argument(
        "--verification-retries",
        type=int,
        default=2,
        help="质量验证重试次数（默认 2）"
    )

    parser.add_argument(
        "--quality-threshold",
        type=float,
        default=6.0,
        help="质量阈值（默认 6.0）"
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
        help="最少分析步数（默认 2）"
    )

    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="跳过已存在的输出目录（断点续传）"
    )

    parser.add_argument(
        "--gt-template-dir",
        type=str,
        default=None,
        help="GT 模板目录路径"
    )

    args = parser.parse_args()

    # 解析路径
    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    # 查找脚本
    if args.script:
        script_path = Path(args.script).resolve()
    else:
        # 自动查找：同目录或父目录
        script_path = Path(__file__).resolve().parent / "injection_pipeline.py"
        if not script_path.exists():
            script_path = Path(__file__).resolve().parents[1] / "scripts" / "injection_pipeline.py"

    if not script_path.exists():
        print(f"❌ 找不到 injection_pipeline.py: {script_path}")
        sys.exit(1)

    print(f"脚本: {script_path}")
    print(f"输入: {input_dir}")
    print(f"输出: {output_dir}")

    # 扫描任务
    tasks = scan_tasks(input_dir)
    if not tasks:
        print("❌ 未找到可执行的任务目录")
        sys.exit(1)

    print(f"找到 {len(tasks)} 个任务\n")

    # 干跑模式
    if args.dry_run:
        print("干跑模式 - 任务列表:")
        for i, task in enumerate(tasks, 1):
            print(f"  [{i:02d}] {task.name}")
        print(f"\n共 {len(tasks)} 个任务")
        sys.exit(0)

    # 过滤已存在的任务（断点续传）
    if args.skip_existing:
        filtered = []
        skipped = 0
        for task in tasks:
            task_output = output_dir / task.name
            # 检查是否已有注入结果
            if task_output.exists() and any(
                d.is_dir() and d.name.startswith('injection_')
                for d in task_output.iterdir()
            ):
                skipped += 1
                continue
            filtered.append(task)
        print(f"断点续传: 跳过 {skipped} 个已完成任务，剩余 {len(filtered)} 个")
        tasks = filtered

    if not tasks:
        print("⚠ 所有任务已完成（断点续传模式）")
        sys.exit(0)

    # 构建传递给 pipeline 的参数
    pipeline_args = []
    if args.no_verification:
        pipeline_args.append("--no-verification")
    pipeline_args.extend([
        "--verification-retries", str(args.verification_retries),
        "--quality-threshold", str(args.quality_threshold),
        "--max-history", str(args.max_history),
        "--min-steps", str(args.min_steps),
    ])
    if args.gt_template_dir:
        pipeline_args.extend(["--gt-template-dir", args.gt_template_dir])

    # 构建环境变量
    env = os.environ.copy()

    # 加载 .env 文件
    try:
        from dotenv import load_dotenv
        env_file = script_path.parents[2] / '.env'
        if env_file.exists():
            load_dotenv(env_file)
            print(f"已加载环境配置: {env_file}")
        else:
            env_file = script_path.parents[1] / '.env'
            if env_file.exists():
                load_dotenv(env_file)
                print(f"已加载环境配置: {env_file}")
    except ImportError:
        pass

    # 确保环境变量同步
    env.update(os.environ)

    # 打印配置摘要
    print(f"\n配置摘要:")
    print(f"  任务数: {len(tasks)}")
    print(f"  并发数: {args.workers} ({'线程池' if args.use_threads else '进程池'})")
    print(f"  任务间隔: {args.rate_limit_delay}s")
    print(f"  验证: {'禁用' if args.no_verification else f'启用 (阈值={args.quality_threshold})'}")
    print(f"  pipeline 参数: {' '.join(pipeline_args)}")

    # 执行批量任务
    result = run_batch(
        tasks=tasks,
        output_dir=output_dir,
        script_path=script_path,
        workers=args.workers,
        pipeline_args=pipeline_args,
        env=env,
        use_threads=args.use_threads,
        rate_limit_delay=args.rate_limit_delay
    )

    # 打印结果摘要
    print(f"\n{'='*60}")
    print("批量执行结果")
    print(f"{'='*60}")
    print(f"\n{result.summary()}")

    if result.failed > 0:
        print(f"\n失败任务:")
        for r in result.task_results:
            if not r.success:
                print(f"  ❌ {r.task_name}: {r.error or 'unknown'}")

    # 保存结果
    save_results(result, output_dir)


if __name__ == "__main__":
    main()
