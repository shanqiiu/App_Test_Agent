# App_Test_Agent

**AI智能体测试技术研究 — 异常场景自动生成平台**

[![Project Status](https://img.shields.io/badge/status-prototype-blue)]()
[![Phase](https://img.shields.io/badge/phase-2_prototype-green)]()
[![Last Updated](https://img.shields.io/badge/updated-2026--03--26-brightgreen)]()

---

## 项目简介

本项目专注于**AI智能体（AI Agent）异常测试场景自动生成**，通过对真实 APP 截图进行语义理解和程序化异常注入，批量生成高仿真的异常 UI 测试数据。

### 核心问题

当前 AI 智能体测试对**异常场景的覆盖能力极度匮乏** — 异常 UI 截图获取成本高、种类单一、难以规模化。

### 解决方案

```
原始截图 → [Stage 1] OmniParser UI检测 → [Stage 2] VLM 语义分组 → [Stage 3] 异常渲染 → 异常截图
```

---

## 核心能力

| 异常模式 | 说明 | 典型场景 |
|----------|------|----------|
| `dialog` | 弹窗覆盖注入 | 优惠券弹窗、广告弹窗、权限请求 |
| `area_loading` | 区域加载异常 | 列表加载超时、网络错误 |
| `content_duplicate` | 内容重复/歧义 | 底部浮层重复、信息冗余 |
| `text_overlay` | 局部文字覆盖 | 价格篡改、文案插入 |
| `modify_text_ai` | AI 图像编辑（组件级） | 席位状态、难 OCR 文案替换 |
| `modify_text_ocr` / `modify_text` | OCR 定位 + PIL 重绘 | 表格文字、规整 UI 文案 |
| `modify_text_e2e` | 端到端图像编辑（可跳过检测） | 细粒度文本、检测难覆盖区域 |

此外，**注入决策流水线**（`injection_pipeline.py`）可基于操作序列自动分析注入点并推荐异常类型。

---

## 快速开始

### 1. 环境准备

```bash
cp .env.example .env                                          # 填写 VLM_API_KEY
pip install -r ui_semantic_patch/requirements.txt  # 安装核心依赖
```

### 2. 运行示例

```bash
cd ui_semantic_patch/scripts

# 一键启动（交互式菜单）
bash launch.sh

# 或直接运行单图生成
python run_pipeline.py \
  --screenshot ../data/原图/app首页类-开屏广告弹窗/携程旅行01.jpg \
  --instruction "生成优惠券广告弹窗" \
  --gt-category "弹窗覆盖原UI" \
  --gt-sample "弹出广告.jpg" \
  --output ./output/demo
```

### 3. 探索更多

- 异常模式与文字编辑系列详解 → [ui_semantic_patch README](./ui_semantic_patch/README.md)
- 脚本命令行参数速查 → [scripts README](./ui_semantic_patch/scripts/README.md)
- 模块架构与接口文档 → [代码手册](./docs/plans/2026-03-06-code-manual.md)

---

## 项目结构

```
App_Test_Agent/
├── README.md                              # 项目概览（本文件）
├── Claude.md                              # AI 协作配置（CLAUDE.md）
├── .env.example                           # 环境变量模板
│
├── ui_semantic_patch/          # 核心原型框架
│   ├── scripts/
│   │   ├── run_pipeline.py                # 三阶段主流水线
│   │   ├── batch_pipeline.py              # 批量生成
│   │   ├── injection_pipeline.py          # 注入决策流水线
│   │   ├── launch.sh                      # 一键启动
│   │   ├── analysis/                      # AI 感知层（OmniParser + VLM）
│   │   ├── renderers/                     # 异常渲染层（dialog 等 + 文字编辑）
│   │   ├── generators/                    # 元数据生成层
│   │   ├── injection/                     # 注入决策层
│   │   ├── utils/                         # 工具库
│   │   └── tests/                         # 测试
│   ├── data/                              # GT 模板与原图数据
│   └── third_party/OmniParser/            # 本地集成
│
├── docs/
│   ├── research/                          # 调研文档（5 篇）
│   ├── technical/                         # 技术栈、术语表
│   ├── references/                        # 学术研究、开源项目
│   ├── planning/                          # 研究路线图、待研究问题
│   ├── plans/                             # 设计文档与实施计划
│   └── setup/                             # 环境搭建指南
│
└── third_party/GUI-Odyssey/               # UI 数据集
```

---

## 文档导航

| 类别 | 链接 | 说明 |
|------|------|------|
| 调研文档 | [docs/research/](./docs/research/) | 方案可行性分析、异常生成技术调研（5 篇） |
| 技术文档 | [docs/technical/](./docs/technical/) | 技术栈与工具、术语表 |
| 参考资源 | [docs/references/](./docs/references/) | 学术论文（15 篇）、开源项目（12 个） |
| 研究规划 | [docs/planning/](./docs/planning/) | 路线图、待研究问题清单 |
| 设计文档 | [docs/plans/](./docs/plans/) | 重构设计、注入决策模块设计、代码手册 |
| 原型代码 | [ui_semantic_patch/](./ui_semantic_patch/) | 框架架构、使用说明 |
| 环境搭建 | [docs/setup/环境搭建指南.md](./docs/setup/环境搭建指南.md) | 开发环境配置 |

---

## 当前进展

### 项目阶段
**Phase 2: 原型开发与优化** — 进行中

### 最新里程碑

**Milestone 4: 架构重构与注入决策** (2026-03-09)
- 完成脚本层重构：拆分为 `analysis/`、`renderers/`、`generators/`、`injection/` 四个子包
- 实现渲染器统一基类（`renderers/base.py`）
- 新增 `text_overlay` 文字覆盖模式；扩展 `modify_text_ai` / `modify_text_ocr` / `modify_text_e2e` 等细粒度文字编辑路径
- 持续扩充 GT 模板与 bounds；文档示例与根目录 `Claude.md` 对齐（如 `弹窗覆盖原UI/05.jpg` + `modify_text_ai`）
- 实现异常注入决策模块：操作序列分析 → 异常推荐 → 序列改写
- 新增 `injection_pipeline.py` 注入决策流水线

**Milestone 3: 辅助工具链完善** (2026-02-25)
- 批量生成流水线、一键启动脚本
- VLM 驱动 meta.json 自动生成
- 精确边界框提取、风格迁移工具
- 扩展 GT 模板数据集

**Milestone 2: 原型开发** (2026-02-03)
- 完成三阶段流水线（OmniParser → VLM 融合 → 异常渲染）
- 实现 dialog / area_loading / content_duplicate 三种模式

**Milestone 1: POC 完成** (2024-12-30)
- 技术调研与可行性验证

### 下一步工作
- [ ] 端到端测试完善
- [ ] ControlNet 精细控制
- [ ] 异常场景样式库
- [ ] 闭环验证体系

---

## 技术栈速览

**AI 感知**: OmniParser (YOLO + PaddleOCR + Florence2) · VLM (qwen-vl-max / GPT-4o)

**图像生成**: DashScope AI · PIL/Pillow

**异常渲染**: 程序化合成 · Alpha 混合 · 组件裁剪

**注入决策**: VLM 语义分析 · GT 模板匹配 · 操作序列建模

---

## 许可证

待定

---

**最后更新**: 2026-03-26
**文档同步**: AI 协作、环境与 `run_pipeline` 示例以 [Claude.md](./Claude.md) 为准。
**项目状态**: Phase 2 进行中
**里程碑**: Milestone 4 完成
