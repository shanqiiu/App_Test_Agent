"""
测试开源 Qwen-Image 模型的图像生成效果
通过 Hugging Face Spaces Gradio API 调用
地址: https://huggingface.co/spaces/Qwen/Qwen-Image
"""

import os
import time
from pathlib import Path
from gradio_client import Client


# 输出目录
OUTPUT_DIR = Path(__file__).parent.parent / "output" / "qwen_image_open_test"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def generate_image(
    client: Client,
    prompt: str,
    aspect_ratio: str = "9:16",
    guidance_scale: float = 4.0,
    num_inference_steps: int = 50,
    prompt_enhance: bool = True,
    seed: int = 0,
    randomize_seed: bool = True,
) -> str:
    """
    调用 Qwen-Image 开源模型生成图像

    Returns:
        生成图像的本地文件路径
    """
    print(f"  生成中... prompt: {prompt[:60]}...")
    start = time.time()

    result = client.predict(
        prompt=prompt,
        seed=seed,
        randomize_seed=randomize_seed,
        aspect_ratio=aspect_ratio,
        guidance_scale=guidance_scale,
        num_inference_steps=num_inference_steps,
        prompt_enhance=prompt_enhance,
        api_name="/infer",
    )

    elapsed = time.time() - start
    # result 格式: (image_path, seed)
    image_path, used_seed = result
    print(f"  完成! 耗时 {elapsed:.1f}s, seed={used_seed}")
    return image_path


def run_tests():
    """运行一组与项目场景相关的测试用例"""

    print("=" * 60)
    print("Qwen-Image 开源模型生成效果测试")
    print("=" * 60)

    # 连接 HF Space
    print("\n连接 Hugging Face Space...")
    client = Client("Qwen/Qwen-Image")
    print("连接成功!\n")

    # 测试用例：覆盖项目中的典型异常 UI 场景
    test_cases = [
        {
            "name": "01_popup_dialog_cn",
            "prompt": (
                "A mobile app popup dialog on a dark semi-transparent overlay background. "
                "The popup has rounded corners, white background, a title in Chinese '限时优惠', "
                "a subtitle '新用户专享8折优惠券', a red button with text '立即领取', "
                "and a close X button at top-right corner. "
                "Clean UI design, flat style, high quality."
            ),
            "aspect_ratio": "9:16",
            "prompt_enhance": False,
        },
        {
            "name": "02_loading_spinner",
            "prompt": (
                "A circular loading spinner icon on a semi-transparent dark background, "
                "centered on screen. The spinner is white/light gray with a rotating animation feel. "
                "Below the spinner there is Chinese text '加载中...'. "
                "Mobile app UI style, clean and minimal."
            ),
            "aspect_ratio": "9:16",
            "prompt_enhance": False,
        },
        {
            "name": "03_error_toast",
            "prompt": (
                "A mobile app error notification toast at the top of screen. "
                "Red background with white text '网络连接失败，请检查网络设置'. "
                "Has a warning icon on the left side. "
                "Flat UI design, modern mobile app style, high resolution."
            ),
            "aspect_ratio": "9:16",
            "prompt_enhance": False,
        },
        {
            "name": "04_coupon_banner",
            "prompt": (
                "A promotional coupon banner for a mobile e-commerce app. "
                "Red and gold color scheme, Chinese text '满100减20' as the main offer, "
                "with a '立即使用' button. Festive design with subtle decorative elements. "
                "Isolated on a pure black background, PNG style with clean edges."
            ),
            "aspect_ratio": "16:9",
            "prompt_enhance": False,
        },
    ]

    results = []
    for i, case in enumerate(test_cases):
        print(f"\n[{i+1}/{len(test_cases)}] {case['name']}")
        print(f"  Prompt: {case['prompt'][:80]}...")

        try:
            image_path = generate_image(
                client=client,
                prompt=case["prompt"],
                aspect_ratio=case.get("aspect_ratio", "9:16"),
                prompt_enhance=case.get("prompt_enhance", False),
            )

            # 复制到输出目录
            import shutil
            dest = OUTPUT_DIR / f"{case['name']}.png"
            shutil.copy2(image_path, dest)
            print(f"  保存至: {dest}")
            results.append({"name": case["name"], "status": "success", "path": str(dest)})

        except Exception as e:
            print(f"  失败: {e}")
            results.append({"name": case["name"], "status": "failed", "error": str(e)})

    # 汇总
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    for r in results:
        status = "OK" if r["status"] == "success" else "FAIL"
        print(f"  [{status}] {r['name']}")
        if r["status"] == "success":
            print(f"         {r['path']}")
        else:
            print(f"         {r.get('error', 'unknown error')}")

    print(f"\n输出目录: {OUTPUT_DIR}")
    return results


if __name__ == "__main__":
    run_tests()
