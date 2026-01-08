# Z-Image模型技术穿刺计划

**文档类型**: 技术穿刺实施手册
**创建日期**: 2026-01-08
**预计周期**: 1周
**目标**: 快速验证Z-Image在app异常界面生成中的可行性

---

## 执行摘要

本技术穿刺旨在验证Z-Image Turbo和Z-Image-Edit模型在生成app异常界面截图方面的能力，为后续大规模应用提供决策依据。

### 核心验证点

1. ✅ **文生图能力**: 从文本描述直接生成app异常界面
2. ✅ **图像编辑能力**: 在正常界面上注入异常元素
3. ✅ **质量评估**: 生成图像的可用性和真实感
4. ✅ **性能表现**: 在现有GPU上的运行效率

### 测试场景

- 🍔 **外卖类**: 美团（商品缺货、广告遮挡、配送超时）
- 💰 **支付类**: 支付宝/微信（余额不足、支付超时、网络错误）
- 🚗 **出行类**: 携程/滴滴（余票为0、无可用车辆、价格异常）

---

## Day 0: 环境准备

### 硬件要求

**现有硬件**: RTX 3090/4080等（非4090）

**优化策略**:
```bash
# 根据显存调整策略：
# RTX 3090 (24GB): 可运行完整Z-Image Turbo
# RTX 4080 (16GB): 需要适当优化
# RTX 3080 (10-12GB): 需要降低分辨率或使用量化
```

### 软件环境搭建

#### Step 1: 创建Python环境

```bash
# 创建虚拟环境
conda create -n z-image python=3.10 -y
conda activate z-image

# 安装PyTorch (CUDA 11.8)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

#### Step 2: 安装核心依赖

```bash
# 安装Hugging Face生态
pip install transformers diffusers accelerate
pip install safetensors
pip install pillow opencv-python

# 安装评估工具
pip install lpips clip scikit-image
pip install gradio  # 用于快速构建测试界面

# 可选：安装xFormers加速推理
pip install xformers
```

#### Step 3: 下载模型

```python
# download_models.py
from huggingface_hub import snapshot_download
import os

# 设置缓存目录
cache_dir = "./models"
os.makedirs(cache_dir, exist_ok=True)

# 下载Z-Image Turbo（假设模型名称）
# 注意：实际模型名称需要从Hugging Face查找
models_to_download = [
    # "stabilityai/z-image-turbo",  # 文生图基础模型
    # "stabilityai/z-image-edit",    # 图像编辑模型
]

print("注意：请手动从Hugging Face搜索Z-Image的实际模型名称")
print("搜索关键词：Z-Image, Z-Image Turbo, Z-Image Edit")
print("模型仓库示例：https://huggingface.co/models?search=z-image")

# 如果找到模型，使用以下代码下载：
# for model_name in models_to_download:
#     print(f"Downloading {model_name}...")
#     snapshot_download(
#         repo_id=model_name,
#         cache_dir=cache_dir,
#         resume_download=True
#     )
```

**执行下载**:
```bash
cd prototypes
python download_models.py
```

### 项目结构

```bash
# 创建项目目录
mkdir -p prototypes/z_image_spike
cd prototypes/z_image_spike

mkdir -p {data,outputs,scripts,notebooks}
mkdir -p data/{reference_images,test_prompts}
mkdir -p outputs/{text2img,img2img,comparisons}
```

**目录说明**:
- `data/reference_images/`: 存放正常app截图（用于编辑测试）
- `data/test_prompts/`: 测试提示词文件
- `outputs/text2img/`: 文生图结果
- `outputs/img2img/`: 图像编辑结果
- `outputs/comparisons/`: 对比评估结果
- `scripts/`: Python脚本
- `notebooks/`: Jupyter实验笔记本

### 数据准备

#### 采集参考图像

```bash
# 手动采集或使用以下工具
# 方式1：手机截图传输
adb devices  # 检查Android设备连接
adb pull /sdcard/Screenshots/*.png data/reference_images/

# 方式2：使用现有图库
# 从网络搜索"美团app界面"、"支付宝界面"等关键词
# 或使用公开数据集
```

**数据清单** (每类app准备5-10张):
- `meituan_normal_*.png`: 美团正常界面
- `alipay_normal_*.png`: 支付宝正常界面
- `ctrip_normal_*.png`: 携程正常界面

---

## Day 1-2: 基础推理测试

### 目标
验证模型能否正常加载和运行，测试基本的文生图能力

### Step 1: 简单推理脚本

创建 `scripts/test_basic_inference.py`:

```python
"""
基础推理测试脚本
验证Z-Image模型是否能正常运行
"""
import torch
from diffusers import DiffusionPipeline
from PIL import Image
import os

# 配置
MODEL_PATH = "path/to/z-image-turbo"  # 替换为实际路径
OUTPUT_DIR = "outputs/text2img"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 显存优化配置
ENABLE_XFORMERS = True
ENABLE_CPU_OFFLOAD = False  # 如果显存不足，设为True
USE_FP16 = True

def load_model():
    """加载Z-Image模型"""
    print("Loading model...")

    # 根据显存情况调整
    if USE_FP16:
        torch_dtype = torch.float16
    else:
        torch_dtype = torch.float32

    pipe = DiffusionPipeline.from_pretrained(
        MODEL_PATH,
        torch_dtype=torch_dtype,
        use_safetensors=True
    )

    # 优化设置
    if ENABLE_XFORMERS:
        pipe.enable_xformers_memory_efficient_attention()

    if ENABLE_CPU_OFFLOAD:
        pipe.enable_model_cpu_offload()
    else:
        pipe = pipe.to("cuda")

    print(f"Model loaded. Using dtype: {torch_dtype}")
    return pipe

def generate_test_image(pipe, prompt, seed=42):
    """生成测试图像"""
    generator = torch.Generator(device="cuda").manual_seed(seed)

    # 根据显存调整分辨率
    # 24GB: 1024x1024
    # 16GB: 768x768 或 512x512
    # 12GB: 512x512

    image = pipe(
        prompt=prompt,
        num_inference_steps=20,  # Turbo版本通常需要较少步数
        generator=generator,
        height=512,
        width=512,
    ).images[0]

    return image

def main():
    # 测试提示词
    test_prompts = [
        "A mobile app screenshot showing a food delivery interface",
        "美团外卖app界面，显示商品列表",
        "A payment app showing insufficient balance error",
    ]

    # 加载模型
    pipe = load_model()

    # 生成测试图像
    for i, prompt in enumerate(test_prompts):
        print(f"\nGenerating image {i+1}/{len(test_prompts)}")
        print(f"Prompt: {prompt}")

        image = generate_test_image(pipe, prompt, seed=42+i)

        output_path = f"{OUTPUT_DIR}/test_{i+1}.png"
        image.save(output_path)
        print(f"Saved to {output_path}")

    print("\n✅ Basic inference test completed!")

if __name__ == "__main__":
    main()
```

### Step 2: 运行基础测试

```bash
cd prototypes/z_image_spike
python scripts/test_basic_inference.py
```

### Step 3: 性能基准测试

创建 `scripts/benchmark.py`:

```python
"""
性能基准测试
测量生成速度和显存占用
"""
import torch
import time
from test_basic_inference import load_model, generate_test_image

def benchmark():
    pipe = load_model()

    test_prompt = "A mobile app interface screenshot"

    # 预热
    print("Warming up...")
    _ = generate_test_image(pipe, test_prompt)

    # 正式测试
    print("\nRunning benchmark...")
    times = []
    for i in range(5):
        torch.cuda.synchronize()
        start = time.time()

        _ = generate_test_image(pipe, test_prompt, seed=i)

        torch.cuda.synchronize()
        end = time.time()

        elapsed = end - start
        times.append(elapsed)
        print(f"Run {i+1}: {elapsed:.2f}s")

    # 显存统计
    memory_allocated = torch.cuda.max_memory_allocated() / 1024**3
    print(f"\n📊 Performance Summary:")
    print(f"  Average time: {sum(times)/len(times):.2f}s")
    print(f"  Min time: {min(times):.2f}s")
    print(f"  Max time: {max(times):.2f}s")
    print(f"  Peak memory: {memory_allocated:.2f} GB")

if __name__ == "__main__":
    benchmark()
```

**预期结果**:
- ✅ 模型成功加载
- ✅ 生成速度: 2-5秒/图（取决于硬件）
- ✅ 显存占用: 8-12GB（FP16模式）

---

## Day 3-4: 文生图能力验证

### 目标
测试Z-Image从文本描述直接生成app异常界面的能力

### 测试用例设计

创建 `data/test_prompts/anomaly_prompts.json`:

```json
{
  "meituan": [
    {
      "id": "mt_001",
      "category": "out_of_stock",
      "prompt": "美团外卖app界面截图，显示一个餐厅菜品页面，多个菜品显示红色的"已售罄"标签，界面风格为美团标准的黄色主题",
      "prompt_en": "Meituan food delivery app screenshot, restaurant menu page, multiple dishes showing red 'sold out' tags, yellow Meituan theme"
    },
    {
      "id": "mt_002",
      "category": "ad_blocking",
      "prompt": "美团外卖app主界面，中央出现一个半透明的全屏广告弹窗，遮挡住下方的餐厅列表，广告内容为促销活动",
      "prompt_en": "Meituan app home screen with a semi-transparent full-screen promotional ad popup blocking the restaurant list below"
    },
    {
      "id": "mt_003",
      "category": "delivery_delay",
      "prompt": "美团外卖订单详情页面，顶部显示红色警告横幅提示"配送异常，预计延迟30分钟"，下方是订单信息",
      "prompt_en": "Meituan order details page with red warning banner at top showing 'Delivery delayed by 30 minutes', order info below"
    }
  ],
  "alipay": [
    {
      "id": "ap_001",
      "category": "insufficient_balance",
      "prompt": "支付宝支付界面，显示红色错误提示"账户余额不足"，余额显示为¥0.50，支付金额为¥58.00",
      "prompt_en": "Alipay payment screen showing red error 'Insufficient balance', balance ¥0.50, payment amount ¥58.00"
    },
    {
      "id": "ap_002",
      "category": "payment_timeout",
      "prompt": "支付宝界面，中央显示一个灰色的超时图标，下方文字"支付超时，请重试"，背景为支付宝蓝色主题",
      "prompt_en": "Alipay interface with gray timeout icon in center, text 'Payment timeout, please retry', blue Alipay theme"
    },
    {
      "id": "ap_003",
      "category": "network_error",
      "prompt": "支付宝页面显示网络断开图标，提示"网络连接失败，请检查网络设置"，顶部状态栏显示无网络信号",
      "prompt_en": "Alipay page showing network disconnection icon, message 'Network connection failed', no signal in status bar"
    }
  ],
  "ctrip": [
    {
      "id": "ct_001",
      "category": "no_tickets",
      "prompt": "携程火车票查询结果页面，显示"无票"的灰色标签，多个车次都显示已售罄状态",
      "prompt_en": "Ctrip train ticket search results showing gray 'No tickets' labels, multiple trains sold out"
    },
    {
      "id": "ct_002",
      "category": "no_vehicles",
      "prompt": "滴滴打车界面，地图中央显示"附近暂无可用车辆"的提示，地图上没有车辆图标",
      "prompt_en": "DiDi ride-hailing interface, map center showing 'No vehicles available nearby', no car icons on map"
    },
    {
      "id": "ct_003",
      "category": "price_surge",
      "prompt": "携程酒店预订页面，价格显示为红色，旁边有"价格异常上涨"的警告图标和文字",
      "prompt_en": "Ctrip hotel booking page, price in red with warning icon and text 'Abnormal price increase'"
    }
  ]
}
```

### 批量生成脚本

创建 `scripts/generate_from_text.py`:

```python
"""
文生图批量测试脚本
从提示词生成app异常界面
"""
import torch
from diffusers import DiffusionPipeline
from PIL import Image
import json
import os
from pathlib import Path

# 配置
MODEL_PATH = "path/to/z-image-turbo"
PROMPTS_FILE = "data/test_prompts/anomaly_prompts.json"
OUTPUT_DIR = "outputs/text2img"

def load_prompts():
    """加载测试提示词"""
    with open(PROMPTS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def generate_batch(pipe, prompts_data):
    """批量生成图像"""

    for app_name, prompts in prompts_data.items():
        print(f"\n{'='*50}")
        print(f"Processing {app_name.upper()}")
        print(f"{'='*50}")

        app_output_dir = os.path.join(OUTPUT_DIR, app_name)
        os.makedirs(app_output_dir, exist_ok=True)

        for prompt_item in prompts:
            prompt_id = prompt_item["id"]
            category = prompt_item["category"]
            prompt = prompt_item["prompt"]
            prompt_en = prompt_item.get("prompt_en", "")

            print(f"\n[{prompt_id}] {category}")
            print(f"Prompt: {prompt[:50]}...")

            # 尝试中文prompt
            try:
                image = pipe(
                    prompt=prompt,
                    negative_prompt="blurry, low quality, distorted, watermark",
                    num_inference_steps=20,
                    guidance_scale=7.5,
                    height=768,
                    width=512,  # 手机竖屏比例
                ).images[0]

                output_path = os.path.join(app_output_dir, f"{prompt_id}_cn.png")
                image.save(output_path)
                print(f"  ✅ Saved (Chinese prompt): {output_path}")

            except Exception as e:
                print(f"  ❌ Error with Chinese prompt: {e}")

            # 如果有英文prompt，也尝试生成
            if prompt_en:
                try:
                    image = pipe(
                        prompt=prompt_en,
                        negative_prompt="blurry, low quality, distorted, watermark",
                        num_inference_steps=20,
                        guidance_scale=7.5,
                        height=768,
                        width=512,
                    ).images[0]

                    output_path = os.path.join(app_output_dir, f"{prompt_id}_en.png")
                    image.save(output_path)
                    print(f"  ✅ Saved (English prompt): {output_path}")

                except Exception as e:
                    print(f"  ❌ Error with English prompt: {e}")

def main():
    # 加载模型
    print("Loading Z-Image Turbo model...")
    pipe = DiffusionPipeline.from_pretrained(
        MODEL_PATH,
        torch_dtype=torch.float16,
        use_safetensors=True
    ).to("cuda")

    pipe.enable_xformers_memory_efficient_attention()

    # 加载提示词
    prompts_data = load_prompts()

    # 批量生成
    generate_batch(pipe, prompts_data)

    print("\n" + "="*50)
    print("✅ Text-to-image generation completed!")
    print(f"Check results in: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
```

### 运行生成

```bash
python scripts/generate_from_text.py
```

### 质量评估（人工）

创建评估表格 `outputs/text2img/evaluation.md`:

```markdown
# 文生图质量评估

评分标准：
- 5分：完美，完全符合预期
- 4分：优秀，轻微瑕疵
- 3分：合格，基本可用
- 2分：较差，需要改进
- 1分：失败，无法使用

| ID | App | 异常类型 | 界面风格 | 异常元素 | 文字清晰度 | 整体真实感 | 总分 | 备注 |
|----|-----|---------|---------|---------|-----------|-----------|------|------|
| mt_001 | 美团 | 缺货 | /5 | /5 | /5 | /5 | /20 | |
| mt_002 | 美团 | 广告遮挡 | /5 | /5 | /5 | /5 | /20 | |
| ... | ... | ... | ... | ... | ... | ... | ... | ... |

**关键观察点**:
1. 文字是否清晰可辨认（中文支持）
2. UI控件（按钮、输入框）是否真实
3. 颜色风格是否符合目标app
4. 异常元素位置是否合理
5. 整体布局是否协调
```

---

## Day 5-6: 图像编辑能力验证

### 目标
测试Z-Image-Edit在正常界面上注入异常元素的能力

### Step 1: 准备编辑任务

创建 `data/test_prompts/edit_tasks.json`:

```json
{
  "edit_tasks": [
    {
      "id": "edit_001",
      "source_image": "data/reference_images/meituan_normal_1.png",
      "edit_instruction": "在商品列表的第二个商品上添加红色的"已售罄"标签",
      "expected_result": "商品显示缺货状态"
    },
    {
      "id": "edit_002",
      "source_image": "data/reference_images/meituan_normal_1.png",
      "edit_instruction": "在界面中央添加一个半透明的促销广告弹窗，遮挡部分内容",
      "expected_result": "广告遮挡界面"
    },
    {
      "id": "edit_003",
      "source_image": "data/reference_images/alipay_normal_1.png",
      "edit_instruction": "在余额数字位置显示红色的"余额不足"错误提示",
      "expected_result": "显示余额不足异常"
    },
    {
      "id": "edit_004",
      "source_image": "data/reference_images/ctrip_normal_1.png",
      "edit_instruction": "将票价旁边的"有票"改为灰色的"无票"，并禁用购买按钮",
      "expected_result": "显示无票状态"
    }
  ]
}
```

### Step 2: 图像编辑脚本

创建 `scripts/edit_images.py`:

```python
"""
图像编辑测试脚本
使用Z-Image-Edit在正常界面上注入异常
"""
import torch
from diffusers import StableDiffusionInstructPix2PixPipeline
from PIL import Image
import json
import os

# 配置
EDIT_MODEL_PATH = "path/to/z-image-edit"  # 或使用InstructPix2Pix作为替代
TASKS_FILE = "data/test_prompts/edit_tasks.json"
OUTPUT_DIR = "outputs/img2img"

def load_edit_model():
    """加载图像编辑模型"""
    print("Loading image editing model...")

    # 如果Z-Image-Edit不可用，可以使用InstructPix2Pix作为替代
    pipe = StableDiffusionInstructPix2PixPipeline.from_pretrained(
        "timbrooks/instruct-pix2pix",  # 备用方案
        torch_dtype=torch.float16,
        safety_checker=None
    ).to("cuda")

    pipe.enable_xformers_memory_efficient_attention()

    return pipe

def edit_image(pipe, source_path, instruction, output_path):
    """编辑单张图像"""
    # 加载源图像
    image = Image.open(source_path).convert("RGB")

    # 执行编辑
    edited = pipe(
        prompt=instruction,
        image=image,
        num_inference_steps=20,
        image_guidance_scale=1.5,
        guidance_scale=7.5,
    ).images[0]

    # 保存结果
    edited.save(output_path)

    # 创建对比图
    comparison = Image.new('RGB', (image.width * 2, image.height))
    comparison.paste(image, (0, 0))
    comparison.paste(edited, (image.width, 0))
    comparison_path = output_path.replace('.png', '_comparison.png')
    comparison.save(comparison_path)

    return edited, comparison_path

def main():
    # 加载模型
    pipe = load_edit_model()

    # 加载编辑任务
    with open(TASKS_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 执行编辑
    for task in data["edit_tasks"]:
        task_id = task["id"]
        source_path = task["source_image"]
        instruction = task["edit_instruction"]

        print(f"\n[{task_id}]")
        print(f"Source: {source_path}")
        print(f"Instruction: {instruction}")

        if not os.path.exists(source_path):
            print(f"  ⚠️  Source image not found, skipping...")
            continue

        output_path = os.path.join(OUTPUT_DIR, f"{task_id}.png")

        try:
            edited, comparison_path = edit_image(
                pipe, source_path, instruction, output_path
            )
            print(f"  ✅ Saved: {output_path}")
            print(f"  ✅ Comparison: {comparison_path}")
        except Exception as e:
            print(f"  ❌ Error: {e}")

    print("\n✅ Image editing completed!")

if __name__ == "__main__":
    main()
```

### Step 3: 对比不同编辑强度

创建 `scripts/edit_strength_comparison.py`:

```python
"""
编辑强度对比测试
测试不同参数对编辑效果的影响
"""
import torch
from diffusers import StableDiffusionInstructPix2PixPipeline
from PIL import Image
import os

def compare_edit_strengths():
    """对比不同编辑强度"""

    pipe = StableDiffusionInstructPix2PixPipeline.from_pretrained(
        "timbrooks/instruct-pix2pix",
        torch_dtype=torch.float16,
    ).to("cuda")

    # 测试参数
    source_image = "data/reference_images/meituan_normal_1.png"
    instruction = "在界面顶部添加一个红色的错误提示横幅"

    image = Image.open(source_image).convert("RGB")

    # 测试不同的guidance scale
    scales = [1.0, 1.5, 2.0, 3.0]

    output_dir = "outputs/img2img/strength_comparison"
    os.makedirs(output_dir, exist_ok=True)

    for scale in scales:
        print(f"\nTesting image_guidance_scale={scale}")

        edited = pipe(
            prompt=instruction,
            image=image,
            num_inference_steps=20,
            image_guidance_scale=scale,
            guidance_scale=7.5,
        ).images[0]

        output_path = f"{output_dir}/scale_{scale}.png"
        edited.save(output_path)
        print(f"  Saved: {output_path}")

if __name__ == "__main__":
    compare_edit_strengths()
```

### 运行编辑测试

```bash
# 基础编辑测试
python scripts/edit_images.py

# 参数对比测试
python scripts/edit_strength_comparison.py
```

---

## Day 7: 评估与总结

### 自动化质量评估

创建 `scripts/evaluate_quality.py`:

```python
"""
自动化质量评估
使用CLIP、LPIPS等指标评估生成质量
"""
import torch
from PIL import Image
import clip
import lpips
import os
import json
from pathlib import Path

def load_evaluators():
    """加载评估模型"""
    # CLIP for semantic similarity
    device = "cuda"
    clip_model, preprocess = clip.load("ViT-B/32", device=device)

    # LPIPS for perceptual similarity
    lpips_model = lpips.LPIPS(net='alex').to(device)

    return clip_model, preprocess, lpips_model, device

def evaluate_text2img(image_path, text_prompt, clip_model, preprocess, device):
    """评估文生图质量"""
    image = preprocess(Image.open(image_path)).unsqueeze(0).to(device)
    text = clip.tokenize([text_prompt]).to(device)

    with torch.no_grad():
        image_features = clip_model.encode_image(image)
        text_features = clip_model.encode_text(text)

        # Cosine similarity
        similarity = torch.nn.functional.cosine_similarity(
            image_features, text_features
        ).item()

    return similarity

def evaluate_img2img(original_path, edited_path, lpips_model, device):
    """评估图像编辑质量"""
    # Load images
    img1 = lpips.im2tensor(lpips.load_image(original_path)).to(device)
    img2 = lpips.im2tensor(lpips.load_image(edited_path)).to(device)

    # Compute distance
    with torch.no_grad():
        distance = lpips_model(img1, img2).item()

    return distance

def main():
    """运行完整评估"""
    clip_model, preprocess, lpips_model, device = load_evaluators()

    results = {
        "text2img": [],
        "img2img": []
    }

    # 评估文生图
    print("Evaluating text-to-image results...")
    prompts_file = "data/test_prompts/anomaly_prompts.json"
    with open(prompts_file, 'r', encoding='utf-8') as f:
        prompts_data = json.load(f)

    for app_name, prompts in prompts_data.items():
        for prompt_item in prompts:
            prompt_id = prompt_item["id"]
            prompt = prompt_item["prompt"]
            image_path = f"outputs/text2img/{app_name}/{prompt_id}_cn.png"

            if os.path.exists(image_path):
                score = evaluate_text2img(
                    image_path, prompt, clip_model, preprocess, device
                )
                results["text2img"].append({
                    "id": prompt_id,
                    "app": app_name,
                    "clip_score": score
                })
                print(f"  {prompt_id}: CLIP score = {score:.4f}")

    # 评估图像编辑
    print("\nEvaluating image editing results...")
    tasks_file = "data/test_prompts/edit_tasks.json"
    with open(tasks_file, 'r', encoding='utf-8') as f:
        tasks_data = json.load(f)

    for task in tasks_data["edit_tasks"]:
        task_id = task["id"]
        original_path = task["source_image"]
        edited_path = f"outputs/img2img/{task_id}.png"

        if os.path.exists(edited_path) and os.path.exists(original_path):
            distance = evaluate_img2img(
                original_path, edited_path, lpips_model, device
            )
            results["img2img"].append({
                "id": task_id,
                "lpips_distance": distance
            })
            print(f"  {task_id}: LPIPS distance = {distance:.4f}")

    # 保存结果
    output_file = "outputs/evaluation_results.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Evaluation completed! Results saved to {output_file}")

    # 打印摘要
    if results["text2img"]:
        avg_clip = sum(r["clip_score"] for r in results["text2img"]) / len(results["text2img"])
        print(f"\n📊 Text-to-Image Summary:")
        print(f"   Average CLIP score: {avg_clip:.4f}")
        print(f"   Target: > 0.25 (higher is better)")

    if results["img2img"]:
        avg_lpips = sum(r["lpips_distance"] for r in results["img2img"]) / len(results["img2img"])
        print(f"\n📊 Image Editing Summary:")
        print(f"   Average LPIPS distance: {avg_lpips:.4f}")
        print(f"   Target: 0.1-0.3 (moderate change)")

if __name__ == "__main__":
    main()
```

### 生成最终报告

创建 `scripts/generate_report.py`:

```python
"""
生成技术穿刺总结报告
"""
import json
import os
from pathlib import Path
from datetime import datetime

def generate_html_report():
    """生成HTML格式的可视化报告"""

    # 读取评估结果
    with open("outputs/evaluation_results.json", 'r') as f:
        eval_results = json.load(f)

    # 统计图像数量
    text2img_count = len(list(Path("outputs/text2img").rglob("*.png")))
    img2img_count = len(list(Path("outputs/img2img").rglob("*.png")))

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Z-Image技术穿刺报告</title>
    <meta charset="utf-8">
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        h1 {{ color: #2c3e50; }}
        h2 {{ color: #34495e; margin-top: 30px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        th {{ background-color: #3498db; color: white; }}
        .metric {{ background-color: #ecf0f1; padding: 15px; margin: 10px 0; border-radius: 5px; }}
        .success {{ color: #27ae60; }}
        .warning {{ color: #f39c12; }}
        .fail {{ color: #e74c3c; }}
        img {{ max-width: 400px; margin: 10px; border: 1px solid #ddd; }}
    </style>
</head>
<body>
    <h1>🎯 Z-Image模型技术穿刺报告</h1>
    <p><strong>测试日期:</strong> {datetime.now().strftime("%Y-%m-%d")}</p>
    <p><strong>测试目标:</strong> 验证Z-Image在app异常界面生成中的可行性</p>

    <h2>📊 测试概览</h2>
    <div class="metric">
        <p><strong>文生图测试:</strong> {text2img_count} 张图像</p>
        <p><strong>图像编辑测试:</strong> {img2img_count} 张图像</p>
        <p><strong>覆盖场景:</strong> 美团外卖、支付宝、携程/滴滴</p>
    </div>

    <h2>🔬 文生图能力评估</h2>
    <table>
        <tr>
            <th>ID</th>
            <th>App</th>
            <th>CLIP Score</th>
            <th>评价</th>
        </tr>
"""

    for result in eval_results.get("text2img", []):
        score = result["clip_score"]
        rating = "✅ 优秀" if score > 0.3 else "⚠️  一般" if score > 0.2 else "❌ 较差"
        html += f"""
        <tr>
            <td>{result["id"]}</td>
            <td>{result["app"]}</td>
            <td>{score:.4f}</td>
            <td>{rating}</td>
        </tr>
"""

    html += """
    </table>

    <h2>🎨 图像编辑能力评估</h2>
    <table>
        <tr>
            <th>ID</th>
            <th>LPIPS Distance</th>
            <th>评价</th>
        </tr>
"""

    for result in eval_results.get("img2img", []):
        distance = result["lpips_distance"]
        rating = "✅ 适中" if 0.1 < distance < 0.3 else "⚠️  过大" if distance > 0.3 else "⚠️  过小"
        html += f"""
        <tr>
            <td>{result["id"]}</td>
            <td>{distance:.4f}</td>
            <td>{rating}</td>
        </tr>
"""

    html += """
    </table>

    <h2>💡 结论与建议</h2>
    <div class="metric">
        <h3>核心发现</h3>
        <ul>
            <li>待补充：基于实际测试结果填写</li>
            <li>文生图能力: [优秀/一般/较差]</li>
            <li>图像编辑能力: [优秀/一般/较差]</li>
            <li>中文支持: [是/否]</li>
        </ul>

        <h3>后续建议</h3>
        <ul>
            <li>如果效果良好 → 进入LoRA微调阶段</li>
            <li>如果效果一般 → 尝试Flux备选方案</li>
            <li>如果效果较差 → 考虑其他技术路线</li>
        </ul>
    </div>

    <h2>📂 详细结果</h2>
    <p>查看生成的图像:</p>
    <ul>
        <li><a href="../outputs/text2img">文生图结果</a></li>
        <li><a href="../outputs/img2img">图像编辑结果</a></li>
    </ul>
</body>
</html>
"""

    output_path = "outputs/spike_report.html"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"✅ Report generated: {output_path}")
    print(f"Open in browser: file://{os.path.abspath(output_path)}")

if __name__ == "__main__":
    generate_html_report()
```

### 执行评估与报告

```bash
# 运行评估
python scripts/evaluate_quality.py

# 生成报告
python scripts/generate_report.py

# 在浏览器中打开
# Windows: start outputs/spike_report.html
# macOS: open outputs/spike_report.html
# Linux: xdg-open outputs/spike_report.html
```

---

## 成功标准

### 必达指标 (P0)

| 指标 | 目标 | 评估方法 |
|------|------|---------|
| 模型可运行 | ✅ 成功加载和推理 | 基础测试通过 |
| 生成速度 | < 10秒/图 | 性能基准测试 |
| 显存占用 | < 16GB | GPU监控 |
| 文生图可用性 | > 50% 图像可辨认 | 人工评估 |

### 期望指标 (P1)

| 指标 | 目标 | 评估方法 |
|------|------|---------|
| CLIP相似度 | > 0.25 | 自动评估 |
| 中文支持 | 能理解中文提示词 | 对比测试 |
| 异常元素准确性 | > 60% 符合要求 | 人工评估 |
| 编辑保真度 | LPIPS在0.1-0.3 | 自动评估 |

### 优秀指标 (P2)

| 指标 | 目标 | 评估方法 |
|------|------|---------|
| UI风格一致性 | 识别出app特征 | 人工评估 |
| 文字清晰度 | 中文可读 | 人工评估 |
| 布局合理性 | 符合移动端规范 | 专家评审 |

---

## 风险与应对

### 技术风险

#### 风险1: Z-Image模型获取困难

**现象**: Hugging Face上找不到Z-Image Turbo官方模型

**应对措施**:
1. 搜索关键词: "Z-Image", "ZImage", "ZImg"
2. 查看最新的Diffusion模型排行榜
3. 联系相关技术社区确认模型名称
4. **备选方案**: 使用SDXL Turbo或Flux.1-schnell作为替代

```bash
# 备选方案：使用SDXL Turbo
pip install diffusers transformers accelerate
python -c "
from diffusers import AutoPipelineForText2Image
import torch

pipe = AutoPipelineForText2Image.from_pretrained(
    'stabilityai/sdxl-turbo',
    torch_dtype=torch.float16
).to('cuda')
"
```

#### 风险2: 显存不足

**现象**: OOM (Out of Memory) 错误

**应对措施**:
```python
# 方案1: 降低分辨率
height, width = 512, 512  # 而不是768x512

# 方案2: 启用CPU offload
pipe.enable_model_cpu_offload()

# 方案3: 使用更激进的优化
pipe.enable_attention_slicing()
pipe.enable_vae_slicing()

# 方案4: 降低batch size
# 逐张生成，不要批量

# 方案5: 使用FP16甚至INT8
torch_dtype = torch.float16
```

#### 风险3: 生成质量差

**现象**: 生成的图像模糊、失真或无法识别

**应对措施**:
1. **调整提示词**:
   ```python
   # 添加质量提升词
   prompt = "a high-quality mobile app screenshot, " + original_prompt
   negative_prompt = "blurry, low quality, distorted, ugly, bad anatomy"
   ```

2. **增加推理步数**:
   ```python
   num_inference_steps = 50  # 从20增加到50
   ```

3. **调整guidance scale**:
   ```python
   guidance_scale = 9.0  # 从7.5增加到9
   ```

4. **尝试不同的Scheduler**:
   ```python
   from diffusers import DPMSolverMultistepScheduler
   pipe.scheduler = DPMSolverMultistepScheduler.from_config(
       pipe.scheduler.config
   )
   ```

### 工程风险

#### 风险4: 环境配置问题

**应对措施**:
```bash
# 使用Docker容器隔离环境
docker pull pytorch/pytorch:2.1.0-cuda11.8-cudnn8-devel

docker run --gpus all -it \
  -v $(pwd):/workspace \
  pytorch/pytorch:2.1.0-cuda11.8-cudnn8-devel \
  /bin/bash
```

#### 风险5: 数据不足

**应对措施**:
1. 使用网络搜索批量下载app截图
2. 使用模拟器录制app操作视频，提取帧
3. 使用Appium自动化采集
4. 寻找公开的mobile UI数据集

---

## 附录

### A. 完整依赖清单

```bash
# requirements.txt
torch>=2.0.0
torchvision>=0.15.0
transformers>=4.30.0
diffusers>=0.21.0
accelerate>=0.20.0
safetensors>=0.3.1
xformers>=0.0.20
Pillow>=9.5.0
opencv-python>=4.7.0
clip @ git+https://github.com/openai/CLIP.git
lpips>=0.1.4
scikit-image>=0.21.0
gradio>=3.35.0
huggingface-hub>=0.16.0
```

### B. GPU内存优化技巧

```python
# 完整的内存优化示例
import torch
from diffusers import DiffusionPipeline

def load_optimized_pipeline(model_path):
    """加载内存优化的pipeline"""

    pipe = DiffusionPipeline.from_pretrained(
        model_path,
        torch_dtype=torch.float16,  # 使用FP16
        use_safetensors=True,
        variant="fp16",  # 如果有fp16变体
    )

    # 多种优化选项
    pipe.enable_xformers_memory_efficient_attention()  # 最重要
    pipe.enable_attention_slicing(1)  # 注意力切片
    pipe.enable_vae_slicing()  # VAE切片

    # 根据显存选择
    available_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3

    if available_memory < 12:
        # 小显存: 使用CPU offload
        pipe.enable_model_cpu_offload()
        print("Using CPU offload (显存 < 12GB)")
    else:
        # 足够显存: 全部放在GPU
        pipe = pipe.to("cuda")
        print(f"All on GPU (显存 {available_memory:.1f}GB)")

    return pipe
```

### C. 快速调试工具

创建 `scripts/quick_test.py`:

```python
"""
快速测试工具
用于快速验证单个功能
"""
import torch
from diffusers import DiffusionPipeline
from PIL import Image

def quick_text2img_test():
    """快速文生图测试"""
    pipe = DiffusionPipeline.from_pretrained(
        "stabilityai/sdxl-turbo",  # 使用SDXL Turbo作为快速测试
        torch_dtype=torch.float16
    ).to("cuda")

    prompt = "a mobile phone screenshot showing a payment failed error"

    image = pipe(
        prompt=prompt,
        num_inference_steps=1,  # Turbo只需1步
        guidance_scale=0.0,
    ).images[0]

    image.save("quick_test.png")
    print("✅ Quick test passed! Check quick_test.png")

if __name__ == "__main__":
    quick_text2img_test()
```

### D. 常见问题排查

| 问题 | 可能原因 | 解决方案 |
|------|---------|---------|
| CUDA out of memory | 显存不足 | 降低分辨率、启用CPU offload |
| 生成速度很慢 | 未启用xformers | `pip install xformers` |
| 图像模糊 | 推理步数太少 | 增加到50步 |
| 中文提示词无效 | 模型不支持中文 | 使用英文或多语言模型 |
| 模型下载失败 | 网络问题 | 使用镜像站或VPN |

---

## 总结与下一步

### 本次技术穿刺交付物

- ✅ 完整的测试脚本（6个Python脚本）
- ✅ 9个异常场景的测试用例（3个app × 3个场景）
- ✅ 4个图像编辑任务
- ✅ 自动化评估报告
- ✅ HTML可视化报告

### 决策点

根据测试结果，决定后续方向：

**如果文生图效果优秀** (CLIP > 0.3):
- ✅ 继续使用Z-Image作为主方案
- → 进入LoRA微调阶段（2周）
- → 扩展到10+异常场景

**如果文生图效果一般** (CLIP 0.2-0.3):
- ⚠️  需要微调才能实用
- → 收集训练数据（500-1000张/app）
- → 执行两阶段LoRA微调

**如果文生图效果较差** (CLIP < 0.2):
- ❌ 考虑备选方案
- → 测试Flux 12B量化版
- → 或调整技术路线（如LLM+代码生成）

**如果图像编辑效果优秀** (LPIPS 0.1-0.3):
- ✅ 优先使用编辑方案
- → 批量采集正常界面
- → 通过编辑注入异常

### 后续计划

**Phase 2: LoRA微调** (如果基础测试通过):
1. 数据采集: 收集1000+正常截图/app
2. 风格对齐LoRA训练（1-2天）
3. 异常注入LoRA训练（1-2天）
4. 效果验证与优化

**Phase 3: 生产部署**:
1. 构建推理API服务
2. 建立质量评估pipeline
3. 搭建异常场景库（50+场景）

---

**文档版本**: v1.0
**最后更新**: 2026-01-08
**状态**: 待执行
**预计完成**: 2026-01-15
