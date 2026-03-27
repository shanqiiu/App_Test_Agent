# 技术文档索引

本目录包含AI智能体异常测试场景生成项目的技术文档和参考资料。

**最后更新**: 2026-03-26
**文档同步**: 环境变量与命令行参数以仓库根目录 [Claude.md](../../Claude.md) 为准。

---

## 📚 文档列表

### [技术栈与工具](./技术栈与工具.md)
**用途**: 记录项目使用的核心技术栈、工具和框架

**主要内容**:
- **核心生成模型**: Z-Image Turbo、Z-Image-Edit、Flux 12B
- **微调技术**: LoRA、QLoRA
- **控制技术**: ControlNet、IP-Adapter
- **量化技术**: SVDQuant、GGUF
- **评估工具**: CLIP、FID、LPIPS
- **开发框架**: PyTorch、Diffusers、PEFT
- **硬件配置**: RTX 4090显存需求
- **数据管理**: 采集、标注、存储工具
- **部署工具**: FastAPI、Docker

**适用场景**:
- 技术选型决策
- 环境搭建参考
- 工具使用指南

---

### [术语表](./术语表.md)
**用途**: 定义项目中使用的核心术语和概念

**主要内容**:
- **生成模型**: Z-Image、Flux、Diffusion Models
- **微调技术**: LoRA、QLoRA、PEFT
- **控制技术**: ControlNet、IP-Adapter
- **量化技术**: SVDQuant、GGUF、bitsandbytes
- **评估指标**: CLIP、FID、LPIPS
- **优化技术**: Gradient Checkpointing、Mixed Precision
- **缩写索引**: 40+技术缩写
- **技术分类索引**: 按功能分组快速查找

**适用场景**:
- 快速查阅术语定义
- 保持团队术语统一
- 理解技术概念

---

## 🔍 按主题分类

### 图像生成模型
- Z-Image Turbo（首选） → [技术栈与工具](./技术栈与工具.md#🌟-z-image-turbo首选方案) | [术语表](./术语表.md#z-image)
- Z-Image-Edit → [技术栈与工具](./技术栈与工具.md#z-image-edit图像编辑专用)
- Flux 12B（备选） → [技术栈与工具](./技术栈与工具.md#flux-12b备选方案) | [术语表](./术语表.md#flux)
- Diffusion Models → [术语表](./术语表.md#diffusion-models-扩散模型)

### 微调与优化
- LoRA微调 → [技术栈与工具](./技术栈与工具.md#lora-low-rank-adaptation) | [术语表](./术语表.md#lora-low-rank-adaptation)
- QLoRA量化微调 → [技术栈与工具](./技术栈与工具.md#qlora-quantized-lora) | [术语表](./术语表.md#qlora-quantized-lora)
- PEFT库 → [技术栈与工具](./技术栈与工具.md#peft-hugging-face) | [术语表](./术语表.md#peft-parameter-efficient-fine-tuning)
- 梯度检查点 → [术语表](./术语表.md#gradient-checkpointing-梯度检查点)
- 混合精度训练 → [术语表](./术语表.md#mixed-precision-training-混合精度训练)

### 生成控制
- ControlNet → [技术栈与工具](./技术栈与工具.md#controlnet) | [术语表](./术语表.md#controlnet)
- IP-Adapter → [技术栈与工具](./技术栈与工具.md#ip-adapter) | [术语表](./术语表.md#ip-adapter-image-prompt-adapter)

### 模型量化
- SVDQuant → [技术栈与工具](./技术栈与工具.md#svdquant) | [术语表](./术语表.md#svdquant)
- GGUF量化 → [技术栈与工具](./技术栈与工具.md#gguf量化) | [术语表](./术语表.md#gguf-gpt-generated-unified-format)
- bitsandbytes → [技术栈与工具](./技术栈与工具.md#bitsandbytes) | [术语表](./术语表.md#bitsandbytes)

### 质量评估
- CLIP相似度 → [技术栈与工具](./技术栈与工具.md#clip-contrastive-language-image-pre-training) | [术语表](./术语表.md#clip-contrastive-language-image-pre-training)
- FID分数 → [技术栈与工具](./技术栈与工具.md#fid-fréchet-inception-distance) | [术语表](./术语表.md#fid-fréchet-inception-distance)
- LPIPS → [技术栈与工具](./技术栈与工具.md#lpips-learned-perceptual-image-patch-similarity) | [术语表](./术语表.md#lpips-learned-perceptual-image-patch-similarity)

### 硬件与部署
- RTX 4090配置 → [技术栈与工具](./技术栈与工具.md#硬件配置)
- 显存需求估算 → [技术栈与工具](./技术栈与工具.md#显存需求估算)
- 部署工具 → [技术栈与工具](./技术栈与工具.md#部署工具)

### 数据管理
- 数据采集 → [技术栈与工具](./技术栈与工具.md#数据采集)
- 数据标注 → [技术栈与工具](./技术栈与工具.md#数据标注)
- 数据存储 → [技术栈与工具](./技术栈与工具.md#数据存储)

---

## 📖 使用指南

### 新成员入门
1. **了解概念**: 阅读 [术语表](./术语表.md) 了解核心术语（Z-Image、LoRA、ControlNet等）
2. **技术选型**: 查看 [技术栈与工具](./技术栈与工具.md) 了解推荐的技术方案
3. **方案理解**: 参考 [模型选型与工程实施方案](../research/04_模型选型与工程实施方案.md) 了解整体设计
4. **背景调研**: 查阅 [调研文档](../research/) 了解研究背景

### 技术调研
1. **查找工具**: 在 [技术栈与工具](./技术栈与工具.md) 查找相关技术和工具
2. **理解术语**: 在 [术语表](./术语表.md) 查阅专业术语定义
3. **学术资源**: 参考 [学术研究资源](../references/学术研究.md) 了解理论基础
4. **开源参考**: 查看 [开源项目资源](../references/开源项目.md) 寻找实现案例

### 方案设计
1. **明确概念**: 查阅 [术语表](./术语表.md) 确保术语使用准确
2. **选择技术**: 参考 [技术栈与工具](./技术栈与工具.md) 进行技术选型
3. **硬件规划**: 查看 [显存需求估算表](./技术栈与工具.md#显存需求估算)
4. **整体规划**: 参考 [研究路线图](../planning/研究路线图.md) 了解项目阶段

### 环境搭建
1. **硬件准备**: 参考 [硬件配置](./技术栈与工具.md#硬件配置) 准备GPU
2. **框架安装**: 查看 [开发框架与库](./技术栈与工具.md#开发框架与库) 安装依赖
3. **模型下载**: 从Hugging Face下载Z-Image Turbo或Flux模型
4. **环境验证**: 运行推理测试验证环境

---

## 🔗 相关资源

### 项目文档
- [模型选型与工程实施方案](../research/04_模型选型与工程实施方案.md) - 核心技术方案
- [调研文档](../research/) - 技术调研和可行性分析
- [参考资源](../references/) - 学术论文和开源项目
- [研究规划](../planning/) - 路线图和任务清单

### 外部资源
- [Hugging Face](https://huggingface.co/) - 模型下载和文档
- [PyTorch](https://pytorch.org/) - 深度学习框架
- [Diffusers](https://huggingface.co/docs/diffusers/) - 扩散模型库
- [PEFT](https://huggingface.co/docs/peft/) - 参数高效微调库

---

## 📊 快速参考

### 核心技术栈
```
生成模型: Z-Image Turbo (6B) [首选]
         └── Z-Image-Edit (编辑)
         └── Flux 12B (备选)

微调技术: LoRA (FP16)
         └── QLoRA (4-bit量化)

控制技术: ControlNet (布局)
         └── IP-Adapter (风格)

评估指标: CLIP > 0.85, FID < 50, LPIPS < 0.2

硬件: RTX 4090 (16-24GB显存)
```

### 常用指标目标值
| 指标 | 目标值 | 用途 |
|------|--------|------|
| CLIP相似度 | > 0.85 | 风格一致性 |
| FID分数 | < 50 | 视觉保真度 |
| LPIPS | < 0.2 | 感知质量 |

### 显存需求速查
| 任务 | 模型 | 显存 |
|------|------|------|
| Z-Image推理 | 6B | ~12GB |
| Z-Image微调 | 6B+LoRA | ~16GB |
| Flux推理 | 12B (4-bit) | ~14GB |
| Flux微调 | 12B+QLoRA | ~18GB |

---

**文档版本**: v2.0
**最后更新**: 2026-03-26
**文档同步**: 环境变量与命令行参数以仓库根目录 [Claude.md](../../Claude.md) 为准。
**重大变更**: 基于模型选型方案重构，聚焦图像生成技术栈
