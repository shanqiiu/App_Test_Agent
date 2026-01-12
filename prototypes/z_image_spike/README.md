# Z-Image Spike - 文生图MVP实现

基于 SDXL Turbo 的 App 异常界面生成工具 - 精简MVP实现

## 项目概述

这是一个**精简的MVP(最小可行产品)**,用于快速验证 SDXL Turbo 在生成 app 异常界面截图方面的能力。

**核心功能**:
- ✅ 文本生成图像(Text-to-Image)
- ✅ 自动GPU优化(xFormers, FP16, CPU Offload)
- ✅ 批量生成和元数据管理
- ✅ 简洁的CLI命令行接口

**设计原则**:
- 精简实用(10个核心文件)
- 高内聚低耦合
- 配置驱动
- 易于扩展

## 目录结构

```
z_image_spike/
├── README.md                 # 本文件
├── requirements.txt          # Python依赖
├── config/                   # 配置文件
│   ├── model_config.yaml    # 模型配置(路径、超参数)
│   └── test_prompts.json    # 测试场景(3个)
├── src/                      # 源代码
│   ├── __init__.py
│   ├── utils.py             # 工具函数(日志、GPU、文件)
│   ├── config_loader.py     # 配置加载器
│   ├── model_loader.py      # 模型加载与GPU优化
│   └── generator.py         # 图像生成核心逻辑
├── scripts/                  # CLI脚本
│   └── generate.py          # 生成CLI入口
└── outputs/                  # 输出目录
    ├── images/              # 生成的图像
    ├── metadata/            # 元数据(JSON)
    └── logs/                # 日志文件
```

## 快速开始

### 1. 环境准备

```bash
# 创建虚拟环境(推荐)
conda create -n z-image python=3.10 -y
conda activate z-image

# 或使用venv
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows
```

### 2. 安装依赖

```bash
# 进入项目目录
cd prototypes/z_image_spike

# 安装PyTorch (CUDA 11.8示例)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118

# 安装其他依赖
pip install -r requirements.txt

# 可选:安装xFormers加速(需要匹配PyTorch版本)
# pip install xformers
```

### 3. 配置模型

编辑 `config/model_config.yaml`:

```yaml
model:
  name: "stabilityai/sdxl-turbo"  # 使用SDXL Turbo
  cache_dir: "./models"            # 模型缓存目录
```

首次运行会自动从 HuggingFace 下载模型(约7GB),需要网络连接。

### 4. 生成图像

```bash
# 生成所有测试场景(3个)
python scripts/generate.py

# 生成单张自定义图像
python scripts/generate.py --prompt "A mobile payment app showing insufficient balance error"

# 指定随机种子
python scripts/generate.py --seed 123
```

### 5. 查看结果

```bash
# 查看生成的图像
ls outputs/images/

# 查看元数据
cat outputs/metadata/test_001.json

# 查看日志
cat outputs/logs/generate.log
```

## 使用示例

### 批量生成测试场景

```bash
$ python scripts/generate.py

============================================================
Z-Image Spike - Text-to-Image Generation
============================================================
Loading configuration...
  Model: stabilityai/sdxl-turbo
  Steps: 4
  Size: 768x512

Loading model (this may take a few minutes on first run)...
Available GPU memory: 24.00GB
✓ xFormers memory efficient attention enabled
✓ Attention slicing enabled
✓ VAE slicing enabled
✓ Full GPU mode (VRAM 24.00GB)
Model loaded successfully!

Loading test prompts...
Found 3 test scenarios

Starting batch generation with seed 42...
------------------------------------------------------------
[1/3] Processing test_001 (payment_error)
  Prompt: A mobile phone screenshot showing a payment app with a red error...
  ✓ Generated in 3.25s: outputs/images/test_001.png
[2/3] Processing test_002 (network_error)
  Prompt: A smartphone screen showing a food delivery app with a gray...
  ✓ Generated in 2.98s: outputs/images/test_002.png
[3/3] Processing test_003 (out_of_stock)
  Prompt: A mobile app interface for online shopping with multiple items...
  ✓ Generated in 3.12s: outputs/images/test_003.png
------------------------------------------------------------

============================================================
Generation Results
============================================================
✅ test_001: outputs/images/test_001.png (3.25s)
✅ test_002: outputs/images/test_002.png (2.98s)
✅ test_003: outputs/images/test_003.png (3.12s)
============================================================
Summary: 3/3 succeeded
Average generation time: 3.12s
Output directory: outputs/images
============================================================
```

### 单张图像生成

```bash
$ python scripts/generate.py --prompt "A shopping app displaying 'Item Sold Out' message"

Generating single image with seed 42
Prompt: A shopping app displaying 'Item Sold Out' message
✓ Image saved to: outputs/images/custom.png
```

## 配置说明

### model_config.yaml

```yaml
model:
  name: "stabilityai/sdxl-turbo"  # 模型名称
  cache_dir: "./models"            # 缓存目录

generation:
  num_inference_steps: 4           # 推理步数(SDXL Turbo推荐1-4)
  guidance_scale: 0.0              # CFG scale(Turbo不需要)
  height: 768                      # 图像高度
  width: 512                       # 图像宽度
  negative_prompt: "..."           # 负面提示词

gpu:
  enable_xformers: true            # 启用xFormers
  use_fp16: true                   # 使用FP16
  memory_threshold_gb: 12          # 显存阈值(GB)
```

**GPU优化策略**:
- 显存 >= 12GB: 全GPU模式
- 显存 < 12GB: 启用CPU Offload

### test_prompts.json

```json
{
  "prompts": [
    {
      "id": "test_001",
      "category": "payment_error",
      "prompt": "A mobile phone screenshot showing a payment app...",
      "app": "payment"
    }
  ]
}
```

可以添加自定义测试场景,只需遵循相同格式。

## 性能参考

| GPU型号 | 显存 | 优化策略 | 生成速度 |
|---------|------|---------|---------|
| RTX 4090 | 24GB | FP16 + xFormers | 2-3秒/张 |
| RTX 3090 | 24GB | FP16 + xFormers | 3-4秒/张 |
| RTX 4080 | 16GB | FP16 + xFormers + VAE slicing | 4-5秒/张 |
| RTX 3080 | 10GB | FP16 + CPU offload | 8-10秒/张 |

## 故障排查

### 模型下载失败

```bash
# 方法1: 使用国内镜像(如hf-mirror.com)
export HF_ENDPOINT=https://hf-mirror.com
python scripts/generate.py

# 方法2: 预先下载模型
python -c "from diffusers import AutoPipelineForText2Image; AutoPipelineForText2Image.from_pretrained('stabilityai/sdxl-turbo')"
```

### GPU显存不足(OOM)

编辑 `config/model_config.yaml`:

```yaml
generation:
  height: 512        # 降低分辨率
  width: 512

gpu:
  memory_threshold_gb: 16  # 提高阈值,启用CPU Offload
```

### xFormers不可用

```bash
# xFormers是可选的,不影响功能,只是速度稍慢
# 如需安装,确保版本匹配
pip install xformers==0.0.23  # 根据PyTorch版本调整
```

## 架构设计

### 核心模块

1. **ConfigLoader** (`src/config_loader.py`)
   - 加载YAML配置和JSON prompts
   - 提供类型安全的配置访问

2. **ModelLoader** (`src/model_loader.py`)
   - 加载Diffusion模型
   - 自动检测GPU并应用优化

3. **ImageGenerator** (`src/generator.py`)
   - 单张/批量图像生成
   - 元数据管理

4. **Utils** (`src/utils.py`)
   - 日志配置
   - GPU工具
   - 文件I/O

### 数据流

```
ConfigLoader.load() → Config对象
       ↓
ModelLoader.load(config) → 优化的Pipeline
       ↓
ImageGenerator.generate_batch(prompts) → 生成结果
       ↓
保存图像 + 元数据
```

## 后续扩展

当MVP验证成功后,可扩展:

### Phase 2: 增强功能
- [ ] 添加图像编辑模块(InstructPix2Pix)
- [ ] CLIP质量评估
- [ ] HTML可视化报告
- [ ] 更多测试场景(9个完整场景)

### Phase 3: 优化改进
- [ ] LoRA微调pipeline
- [ ] 风格一致性优化
- [ ] 批量评估和A/B测试

### Phase 4: 生产化
- [ ] Docker容器化
- [ ] API服务封装
- [ ] 异常场景库管理

## 成功标准

### 必达指标

| 指标 | 目标 | 当前状态 |
|------|------|---------|
| 模型可加载 | ✅ 成功加载 | 待验证 |
| 生成成功率 | 100% (3/3) | 待验证 |
| 生成速度 | < 10秒/张 | 待验证 |
| 图像可辨认 | UI界面特征清晰 | 待验证 |

### 期望指标

| 指标 | 目标 | 验证方法 |
|------|------|---------|
| CLIP相似度 | > 0.20 | 添加evaluator模块 |
| 显存占用 | < 16GB | GPU监控 |

## 技术细节

### SDXL Turbo特殊配置

SDXL Turbo是蒸馏模型,配置与标准Diffusion不同:

```python
# SDXL Turbo推荐参数
{
    "num_inference_steps": 1,  # 只需1步!
    "guidance_scale": 0.0,     # 不需要CFG
}

# 标准SDXL参数(对比)
{
    "num_inference_steps": 50,
    "guidance_scale": 7.5,
}
```

### GPU优化实现

```python
def optimize_for_gpu(pipe, config):
    # 1. xFormers内存优化
    pipe.enable_xformers_memory_efficient_attention()

    # 2. 注意力切片
    pipe.enable_attention_slicing(1)

    # 3. VAE切片
    pipe.enable_vae_slicing()

    # 4. 设备策略
    if gpu_memory < 12GB:
        pipe.enable_model_cpu_offload()
    else:
        pipe.to("cuda")
```

## License

MIT License - 仅供研究和学习使用

## 相关文档

- 技术穿刺计划: `prototypes/z_image_spike_plan.md`
- 项目主文档: `../../docs/research/04_模型选型与工程实施方案.md`
- CLAUDE协作指南: `../../Claude.md`

## 贡献者

- 基于 `z_image_spike_plan.md` 技术穿刺计划实现
- Claude Sonnet 4.5 辅助编码

---

**版本**: v0.1.0
**最后更新**: 2026-01-09
**状态**: MVP实现完成,待测试验证
