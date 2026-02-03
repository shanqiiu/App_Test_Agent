# App_Test_Agent

**AI智能体测试技术研究与实践项目**

[![Project Status](https://img.shields.io/badge/status-research-blue)]()
[![Phase](https://img.shields.io/badge/phase-foundation-green)]()
[![Last Updated](https://img.shields.io/badge/updated-2024--12--30-brightgreen)]()

---

## 项目简介

本项目专注于**AI智能体（AI Agent）异常测试场景自动生成**的研究与探索，旨在构建一套完整的智能体测试体系，提升AI应用的可靠性和鲁棒性。

### 核心问题

当前AI智能体测试对**异常场景的覆盖能力极度匮乏**，我们需要实现异常测试场景的批量生成。

### 解决方案

通过**正常行为采集 → 程序化异常生成 → 动态场景注入**三阶段流程，构建能够自动生成高仿真、上下文相关的异常测试场景的平台。

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│ 正常行为采集    │  →   │ 程序化异常生成  │  →   │ 动态场景注入    │
└─────────────────┘      └─────────────────┘      └─────────────────┘
  • UI自主遍历          • 界面风格提取         • 注入点决策
  • 状态结构化表征      • 约束-生成架构        • 运行时注入
  • 交互图谱构建        • 上下文感知合成       • 状态一致性维护
```

---

## 文档导航

### 📚 调研文档 ([docs/research/](./docs/research/))

深入的技术调研和方案分析

- [方案可行性分析](./docs/research/01_方案可行性分析.md) - 三阶段方案的详细评估
- [程序化异常生成调研](./docs/research/02_程序化异常生成调研.md) - 核心环节的调研方向
- [调研文档索引](./docs/research/README.md) - 完整调研文档列表

### 🔧 技术文档 ([docs/technical/](./docs/technical/))

技术栈、工具和术语说明

- [技术栈与工具](./docs/technical/技术栈与工具.md) - 使用的技术和工具详解
- [术语表](./docs/technical/术语表.md) - 核心概念和术语定义
- [技术文档索引](./docs/technical/README.md) - 技术文档导航

### 📖 参考资源 ([docs/references/](./docs/references/))

学术研究和开源项目资源

- [学术研究资源](./docs/references/学术研究.md) - 相关论文和文献（15篇）
- [开源项目资源](./docs/references/开源项目.md) - 工具和框架（12个）
- [资源索引](./docs/references/README.md) - 资源分类导航

### 🗺️ 研究规划 ([docs/planning/](./docs/planning/))

项目规划和任务清单

- [研究路线图](./docs/planning/研究路线图.md) - 整体规划和实施路线
- [待研究问题清单](./docs/planning/待研究问题.md) - 待解决的技术问题（12个）
- [规划文档索引](./docs/planning/README.md) - 当前状态和任务清单

---

## 快速开始

### 了解项目
1. 阅读本文档了解项目概况
2. 查看 [方案可行性分析](./docs/research/01_方案可行性分析.md) 理解技术方案
3. 浏览 [研究路线图](./docs/planning/研究路线图.md) 把握整体规划

### 环境搭建
1. 查看 [环境搭建指南](./docs/setup/环境搭建指南.md) 配置开发环境
2. 复制 `.env.example` 为 `.env` 并配置 API 密钥
3. 运行测试用例验证安装

### 使用原型
1. **UI 复刻工具**: 查看 [img2text2html2img README](./prototypes/img2text2html2img/README.md)
2. **异常场景生成**: 查看 [ui_semantic_patch README](./prototypes/ui_semantic_patch/README.md)

### 技术调研
1. 参考 [技术栈与工具](./docs/technical/技术栈与工具.md) 了解技术选型
2. 查阅 [学术研究资源](./docs/references/学术研究.md) 获取理论基础
3. 探索 [开源项目资源](./docs/references/开源项目.md) 寻找实现参考

---

## 当前进展

### 项目阶段
**Phase 1: 基础建设** ✅ 已完成

### 最新里程碑
✅ **Milestone 2: 原型开发** (2026-02-03)
- 完成 `img2text2html2img` UI复刻工具链
- 完成 `ui_semantic_patch` 异常场景生成框架
- 集成 OmniParser + VLM 融合方案
- 实现语义感知弹窗生成

✅ **Milestone 1: POC完成** (2024-12-30)
- 完成技术调研
- 确定技术路线
- 验证关键技术可行性

### 下一步工作
- [ ] 实现 ControlNet 精细控制
- [ ] 构建异常场景样式库
- [ ] 建立闭环验证体系
- [ ] 性能优化和工程化

详见 [研究路线图](./docs/planning/研究路线图.md)

---

## 核心技术

### 测试技术
- **UI自动化**: Appium, Espresso, Detox
- **测试方法**: Model-based Testing, Visual Testing

### AI技术
- **生成式AI**: LLM, Diffusion Models, GAN
- **异常检测**: Context-Aware Anomaly Detection
- **对抗性测试**: Adversarial UI Generation, Shadow Injection

### 评估方法
- **质量指标**: Synthetic AUC, Fidelity/Utility Metrics
- **相似度**: Cosine Similarity, LPIPS, FID

详见 [技术栈与工具](./docs/technical/技术栈与工具.md)

---

## 研究方向

### 🔥 高优先级
- 语义一致性建模
- UI交互图谱构建
- 异常生成质量评估体系

### ⭐ 中优先级
- 生成式模型应用
- RAG架构集成
- 工程验证与原型

### 💡 探索性
- 对抗性UI生成
- 多模态状态表征
- 真实用户异常挖掘

详见 [待研究问题清单](./docs/planning/待研究问题.md)

---

## 项目结构

```
App_Test_Agent/
├── README.md                           # 项目概览（本文件）
├── Claude.md                           # AI协作配置
├── .env.example                        # 环境变量模板
│
├── docs/                               # 📚 文档目录
│   ├── research/                       # 调研文档（5篇）
│   │   ├── 01_方案可行性分析.md
│   │   ├── 02_程序化异常生成调研.md
│   │   ├── 03_异常界面生成技术路线分析.md
│   │   ├── 04_模型选型与工程实施方案.md
│   │   ├── 05_移动UI异常截图生成技术调研.md
│   │   └── README.md
│   ├── technical/                      # 技术文档
│   │   ├── 技术栈与工具.md
│   │   ├── 术语表.md
│   │   └── README.md
│   ├── references/                     # 参考资源
│   │   ├── 学术研究.md
│   │   ├── 开源项目.md
│   │   └── README.md
│   ├── planning/                       # 研究规划
│   │   ├── 研究路线图.md
│   │   ├── 待研究问题.md
│   │   └── README.md
│   └── setup/                          # 环境配置
│       └── 环境搭建指南.md
│
├── prototypes/                         # 💻 原型代码
│   ├── img2text2html2img/              # UI截图复刻工具链
│   │   ├── README.md                   # 详细使用文档
│   │   └── scripts/
│   │       ├── pipeline.py             # 端到端流水线
│   │       ├── ui_detector.py          # UI组件检测
│   │       ├── img2text.py             # 图片→描述
│   │       ├── text2html.py            # 描述→HTML
│   │       ├── html2img.py             # HTML→图片
│   │       └── omniparser_adapter.py   # OmniParser适配器
│   │
│   └── ui_semantic_patch/              # 异常场景语义补丁框架
│       ├── README.md                   # 架构文档
│       ├── scripts/
│       │   ├── run_pipeline.py         # 一键执行入口
│       │   ├── omni_vlm_fusion.py      # OmniParser+VLM融合
│       │   ├── patch_renderer.py       # 像素级渲染
│       │   └── utils/                  # 工具模块
│       │       ├── semantic_dialog_generator.py  # 语义弹窗生成
│       │       └── gt_manager.py       # GT模板管理
│       ├── assets/                     # 静态资源
│       ├── examples/                   # 示例文件
│       └── third_party/
│           └── OmniParser/             # 本地集成
│
└── third_party/                        # 📦 第三方依赖
    └── GUI-Odyssey/                    # UI数据集
```

---

## 贡献方式

本项目目前处于研究阶段，欢迎：

- 📚 分享相关技术资料和研究论文
- 💡 提供实际测试场景和需求建议
- 🔬 参与技术方案讨论和评审
- 🐛 报告问题和提出改进建议

通过 [Issues](../../issues) 参与讨论。

---

## 联系方式

- **项目类型**: 技术研究
- **当前状态**: 🔬 研究阶段
- **讨论方式**: GitHub Issues

---

## 许可证

待定

---

**最后更新**: 2026-02-03
**项目状态**: Phase 1 已完成 ✅ | Phase 2 规划中
**里程碑**: Milestone 2 已完成 ✅
