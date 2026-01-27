"""
Pipeline - 端到端UI复刻流水线
一键执行: 图片 → 描述文本 → HTML → 复刻图片

支持两种模式：
- precise（精确模式）：OmniParser 检测 + VL 模型分析
- fast（快速模式）：仅 VL 模型分析
"""

import argparse
import os
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

# 导入各模块
from img2text import ImageAnalyzer, ImageMetadata
from text2html import HTMLGenerator
from html2img import html_to_image


def run_pipeline(
    image_path: str,
    output_dir: str = "./pipeline_output",
    api_key: str = None,
    api_url: str = "https://api.openai-next.com/v1/chat/completions",
    vl_model: str = "qwen-vl-max",
    llm_model: str = "qwen3-235b-a22b",
    timeout: int = 500,
    verbose: bool = True,
    resume: bool = True,
    mode: str = "fast",  # 新增：工作模式 (precise/fast)
    detector_device: str = "cuda"  # 新增：检测器设备
) -> dict:
    """
    执行完整的UI复刻流水线

    Args:
        image_path: 输入图片路径
        output_dir: 输出目录
        api_key: API密钥
        api_url: API地址
        vl_model: VL模型名称
        llm_model: LLM模型名称
        timeout: HTML渲染超时(ms)
        verbose: 是否打印详细信息
        resume: 是否启用断点续传（跳过已完成阶段）
        mode: 工作模式 ("precise" 使用 OmniParser, "fast" 仅 VL)
        detector_device: 检测器推理设备 (cuda/cpu)

    Returns:
        包含各阶段输出路径的字典
    """

    # 默认API Key
    if api_key is None:
        api_key = os.environ.get("API_KEY", "sk-K9B2ccVeW4VdAcobD53b16E06b104aA1B5A82593FdFb2557")

    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"图片不存在: {image_path}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 创建子目录
    desc_dir = output_dir / "descriptions"
    html_dir = output_dir / "html"
    img_dir = output_dir / "images"
    for d in [desc_dir, html_dir, img_dir]:
        d.mkdir(exist_ok=True)

    results = {
        "input": str(image_path),
        "mode": mode,
        "stages": {},
        "success": False,
        "error": None
    }

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = image_path.stem

    # 检测结果（精确模式使用）
    detection = None

    try:
        # ==================== Stage 0: UI 组件检测（精确模式）====================
        if mode == "precise":
            # 检查是否已存在检测文件
            existing_det = None
            if resume:
                for f in desc_dir.glob(f"{base_name}_*_detection.json"):
                    existing_det = f
                    break

            if existing_det and resume:
                if verbose:
                    print(f"\n{'='*60}")
                    print(f"[Stage 0/3] UI 组件检测 (跳过 - 已存在)")
                    print(f"{'='*60}")
                    print(f"  复用: {existing_det.name}")

                import json
                detection = json.loads(existing_det.read_text(encoding="utf-8"))
                results["stages"]["detection"] = {
                    "output": str(existing_det),
                    "component_count": len(detection.get("components", [])),
                    "time": 0,
                    "skipped": True
                }
            else:
                if verbose:
                    print(f"\n{'='*60}")
                    print(f"[Stage 0/3] UI 组件检测 (OmniParser)")
                    print(f"{'='*60}")
                    print(f"  输入: {image_path.name}")
                    print(f"  设备: {detector_device}")

                t0 = time.time()

                try:
                    from ui_detector import get_detector
                    detector = get_detector("omniparser", device=detector_device)
                    detection = detector.detect(str(image_path))

                    # 保存检测结果
                    det_file = desc_dir / f"{base_name}_{ts}_detection.json"
                    detector.save(detection, str(det_file))

                    t1 = time.time()

                    results["stages"]["detection"] = {
                        "output": str(det_file),
                        "component_count": len(detection.get("components", [])),
                        "time": round(t1 - t0, 2)
                    }

                    if verbose:
                        print(f"  组件数: {len(detection.get('components', []))}")
                        print(f"  耗时: {t1-t0:.1f}s")
                        print(f"  输出: {det_file}")

                except ImportError as e:
                    if verbose:
                        print(f"  [WARN] OmniParser 未安装，回退到快速模式")
                        print(f"  错误: {e}")
                    mode = "fast"
                    results["mode"] = "fast"
                    detection = None

        # ==================== Stage 1: 图片 → 描述 ====================
        # 检查是否已存在描述文件
        existing_desc = None
        if resume:
            for f in desc_dir.glob(f"{base_name}_*.txt"):
                existing_desc = f
                break

        if existing_desc and resume:
            if verbose:
                print(f"\n{'='*60}")
                print(f"[Stage 1/3] 图片分析 (跳过 - 已存在)")
                print(f"{'='*60}")
                print(f"  复用: {existing_desc.name}")
            desc_file = str(existing_desc)
            # 读取元数据
            json_file = existing_desc.with_suffix('.json')
            if json_file.exists():
                import json
                metadata = json.loads(json_file.read_text())["metadata"]
            else:
                metadata = ImageMetadata(image_path).to_dict()
            results["stages"]["img2text"] = {
                "output": desc_file,
                "resolution": metadata,
                "time": 0,
                "skipped": True
            }
        else:
            stage_label = "1/3" if mode == "fast" else "1/3"
            mode_label = "精确模式" if detection else "快速模式"

            if verbose:
                print(f"\n{'='*60}")
                print(f"[Stage {stage_label}] 图片分析 (img2text - {mode_label})")
                print(f"{'='*60}")
                print(f"  输入: {image_path.name}")
                print(f"  模型: {vl_model}")
                if detection:
                    print(f"  融合检测: {len(detection.get('components', []))} 个组件")

            t0 = time.time()
            analyzer = ImageAnalyzer(api_key, api_url, vl_model)
            analysis_result = analyzer.analyze(str(image_path), detection)
            desc_file = analyzer.save(analysis_result, base_name, str(desc_dir))
            t1 = time.time()

            results["stages"]["img2text"] = {
                "output": desc_file,
                "resolution": analysis_result["metadata"],
                "mode": analysis_result.get("mode", "fast"),
                "time": round(t1 - t0, 2)
            }

            if verbose:
                w, h = analysis_result["metadata"]["width"], analysis_result["metadata"]["height"]
                print(f"  分辨率: {w} x {h} px")
                print(f"  耗时: {t1-t0:.1f}s")
                print(f"  输出: {desc_file}")

        # ==================== Stage 2: 描述 → HTML ====================
        # 检查是否已存在HTML文件
        existing_html = None
        if resume:
            desc_stem = Path(desc_file).stem
            for f in html_dir.glob(f"{desc_stem}_*.html"):
                existing_html = f
                break

        if existing_html and resume:
            if verbose:
                print(f"\n{'='*60}")
                print(f"[Stage 2/3] HTML生成 (跳过 - 已存在)")
                print(f"{'='*60}")
                print(f"  复用: {existing_html.name}")
            html_file = str(existing_html)
            # 读取元数据
            json_file = existing_html.with_suffix('.json')
            if json_file.exists():
                import json
                html_metadata = json.loads(json_file.read_text())
                resolution = html_metadata.get("resolution", {"width": 0, "height": 0})
            else:
                resolution = {"width": 0, "height": 0}
            results["stages"]["text2html"] = {
                "output": html_file,
                "resolution": resolution,
                "time": 0,
                "skipped": True
            }
        else:
            if verbose:
                print(f"\n{'='*60}")
                print(f"[Stage 2/3] HTML生成 (text2html)")
                print(f"{'='*60}")
                print(f"  模型: {llm_model}")

            t0 = time.time()
            generator = HTMLGenerator(api_key, api_url, llm_model)
            desc_content = Path(desc_file).read_text(encoding="utf-8")
            html_result = generator.generate(desc_content)
            html_file = generator.save(html_result, str(html_dir), Path(desc_file).stem)
            t1 = time.time()

            results["stages"]["text2html"] = {
                "output": html_file,
                "resolution": html_result["resolution"],
                "time": round(t1 - t0, 2)
            }

            if verbose:
                res = html_result["resolution"]
                print(f"  分辨率: {res['width']} x {res['height']} px")
                print(f"  耗时: {t1-t0:.1f}s")
                print(f"  输出: {html_file}")

        # ==================== Stage 3: HTML → 图片 ====================
        # 检查是否已存在输出图片
        output_image = img_dir / f"{Path(html_file).stem}.png"

        if output_image.exists() and resume:
            if verbose:
                print(f"\n{'='*60}")
                print(f"[Stage 3/3] 图片渲染 (跳过 - 已存在)")
                print(f"{'='*60}")
                print(f"  复用: {output_image.name}")
            results["stages"]["html2img"] = {
                "output": str(output_image),
                "time": 0,
                "skipped": True
            }
        else:
            if verbose:
                print(f"\n{'='*60}")
                print(f"[Stage 3/3] 图片渲染 (html2img)")
                print(f"{'='*60}")

            t0 = time.time()
            success = html_to_image(html_file, str(output_image), timeout=timeout)
            t1 = time.time()

            if not success:
                raise RuntimeError("HTML渲染失败")

            results["stages"]["html2img"] = {
                "output": str(output_image),
                "time": round(t1 - t0, 2)
            }

            if verbose:
                print(f"  耗时: {t1-t0:.1f}s")
                print(f"  输出: {output_image}")

        # ==================== 完成 ====================
        results["output"] = str(output_image)
        results["success"] = True

        if verbose:
            total_time = sum(s["time"] for s in results["stages"].values())
            mode_label = "精确模式" if results["mode"] == "precise" else "快速模式"
            print(f"\n{'='*60}")
            print(f"[完成] 流水线执行成功!")
            print(f"{'='*60}")
            print(f"  工作模式: {mode_label}")
            print(f"  原始图片: {image_path}")
            print(f"  复刻图片: {output_image}")
            print(f"  总耗时: {total_time:.1f}s")

    except Exception as e:
        results["error"] = str(e)
        if verbose:
            print(f"\n[错误] {e}")
        raise

    return results


def compare_images(original: str, generated: str, output: str = None):
    """生成原图与复刻图的对比图"""
    try:
        from PIL import Image

        img1 = Image.open(original)
        img2 = Image.open(generated)

        # 创建并排对比图
        w1, h1 = img1.size
        w2, h2 = img2.size

        # 统一高度
        if h1 != h2:
            ratio = h1 / h2
            img2 = img2.resize((int(w2 * ratio), h1), Image.Resampling.LANCZOS)
            w2 = img2.size[0]

        # 创建对比图（原图 | 复刻图）
        gap = 20
        comparison = Image.new("RGB", (w1 + w2 + gap, h1), (255, 255, 255))
        comparison.paste(img1, (0, 0))
        comparison.paste(img2, (w1 + gap, 0))

        if output is None:
            output = Path(generated).parent / f"{Path(generated).stem}_comparison.png"

        comparison.save(output)
        print(f"[对比图] {output}")
        return str(output)

    except ImportError:
        print("[警告] 未安装Pillow，无法生成对比图")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="UI复刻流水线 - 一键执行图片到复刻图片的完整流程",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 快速模式（仅 VL 模型）
  python pipeline.py -i screenshot.jpg --mode fast

  # 精确模式（OmniParser + VL）
  python pipeline.py -i screenshot.jpg --mode precise

  # 指定输出目录
  python pipeline.py -i screenshot.jpg -o ./output --mode precise

  # 批量处理目录
  python pipeline.py --input-dir ./screenshots --mode precise

  # 生成对比图
  python pipeline.py -i screenshot.jpg --mode precise --compare

  # 使用 CPU 进行检测（无 GPU 时）
  python pipeline.py -i screenshot.jpg --mode precise --detector-device cpu

  # 使用自定义模型
  python pipeline.py -i screenshot.jpg --vl-model qwen-vl-max --llm-model qwen3-235b-a22b
"""
    )

    # 输入参数
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("-i", "--input", help="单个输入图片路径")
    input_group.add_argument("--input-dir", help="输入图片目录（批量处理）")

    # 输出参数
    parser.add_argument("-o", "--output", default="./pipeline_output", help="输出目录")

    # API参数
    parser.add_argument("--api-url", default="https://api.openai-next.com/v1/chat/completions")
    parser.add_argument("--api-key", help="API密钥（或设置环境变量API_KEY）")
    parser.add_argument("--vl-model", default="qwen-vl-max", help="VL模型")
    parser.add_argument("--llm-model", default="qwen3-235b-a22b", help="LLM模型")

    # 工作模式
    parser.add_argument(
        "--mode",
        default="fast",
        choices=["precise", "fast"],
        help="工作模式: precise(OmniParser+VL) / fast(仅VL)"
    )
    parser.add_argument(
        "--detector-device",
        default=os.environ.get("OMNIPARSER_DEVICE", "cuda"),
        help="检测器推理设备 (cuda/cpu)"
    )

    # 其他参数
    parser.add_argument("--timeout", type=int, default=500, help="渲染超时(ms)")
    parser.add_argument("--compare", action="store_true", help="生成原图与复刻图对比")
    parser.add_argument("--no-resume", action="store_true", help="禁用断点续传，强制重新处理")
    parser.add_argument("-q", "--quiet", action="store_true", help="静默模式")

    args = parser.parse_args()

    # 确定输入文件列表
    if args.input:
        images = [Path(args.input)]
    else:
        input_dir = Path(args.input_dir)
        images = [f for f in sorted(input_dir.iterdir())
                  if f.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}]

    if not images:
        print("[错误] 未找到图片文件")
        sys.exit(1)

    mode_label = "精确模式 (OmniParser + VL)" if args.mode == "precise" else "快速模式 (仅 VL)"
    print(f"\n{'#'*60}")
    print(f"# UI复刻流水线")
    print(f"# 模式: {mode_label}")
    print(f"# 输入: {len(images)} 张图片")
    print(f"# 输出: {args.output}")
    print(f"{'#'*60}")

    success_count = 0
    fail_count = 0

    for i, img_path in enumerate(images, 1):
        print(f"\n[{i}/{len(images)}] 处理: {img_path.name}")

        try:
            result = run_pipeline(
                image_path=str(img_path),
                output_dir=args.output,
                api_key=args.api_key,
                api_url=args.api_url,
                vl_model=args.vl_model,
                llm_model=args.llm_model,
                timeout=args.timeout,
                verbose=not args.quiet,
                resume=not args.no_resume,
                mode=args.mode,
                detector_device=args.detector_device
            )

            # 生成对比图
            if args.compare and result["success"]:
                compare_images(str(img_path), result["output"])

            success_count += 1

        except Exception as e:
            print(f"[失败] {e}")
            fail_count += 1

    # 汇总
    print(f"\n{'#'*60}")
    print(f"# 完成: 成功 {success_count}, 失败 {fail_count}")
    print(f"{'#'*60}")

    sys.exit(0 if fail_count == 0 else 1)


if __name__ == "__main__":
    main()
