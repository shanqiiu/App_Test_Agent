# App_Test_Agent

**AI智能体测试技术研究 — 异常场景自动生成平台**

[![Project Status](https://img.shields.io/badge/status-prototype-blue)]()
[![Phase](https://img.shields.io/badge/phase-2_prototype-green)]()
[![Last Updated](https://img.shields.io/badge/updated-2026--05--15-brightgreen)]()

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
cp .env.example .env                                          # 填写 VLM_API_KEY 和图像生成配置
pip install -r ui_semantic_patch/requirements.txt  # 安装核心依赖
```

**环境变量配置说明：**

```bash
# VLM 配置（必需）
VLM_API_KEY=your-vlm-api-key
VLM_API_URL=https://api.openai-next.com/v1/chat/completions
VLM_MODEL=gpt-4o

# 图像生成配置（4 种后端可选）
IMAGE_GEN_BACKEND=dashscope        # 选项: dashscope / huawei_mlops / local / auto

# 通用图像生成配置（兼容任意 OpenAI 格式 API）
IMAGE_GEN_API_KEY=your-key
IMAGE_GEN_API_URL=https://api.provider.com/v1
IMAGE_GEN_MODEL=your-model

# 华为 MLOps 专属配置（当 backend=huawei_mlops 时使用）
HUAWEI_MLOPS_API_KEY=your-key
HUAWEI_MLOPS_API_URL=http://mlops.huawei.com/...
HUAWEI_MLOPS_MODEL=flux_txt_to_image

# DashScope 专属配置（向后兼容）
DASHSCOPE_API_KEY=your-key
DASHSCOPE_IMAGE_GEN_MODEL=qwen-image-max

# 本地服务配置（当 backend=local 时使用）
LOCAL_IMAGE_API_URL=http://10.85.177.2:8042/generate
```

### 2. 运行示例

```bash
cd ui_semantic_patch/scripts

# 一键启动（交互式菜单）
bash start.sh

# 或直接运行单图生成
python run_pipeline.py \
  --screenshot ../../data/gt-category/dialog/美团-神券页面-权益升级引导弹窗.jpg \
  --instruction "生成优惠券广告弹窗" \
  --gt-category "dialog" \
  --output ./output/demo
```

### 3. 探索更多

- 异常模式与文字编辑系列详解 → [ui_semantic_patch README](./ui_semantic_patch/README.md)
- 系统架构文档 → [docs/architecture.md](./docs/architecture.md)
- 技术难题分析 → [docs/技术难题.md](./docs/技术难题.md)

---

## 项目结构

```
App_Test_Agent/
├── README.md                                    # 项目概览（本文件）
├── .env.example                                 # 环境变量模板
├── .gitignore
│
├── data/                                        # 数据与示例
│   ├── data_process/                            # 数据处理脚本、模板与测试数据
│   ├── examples/                                # 注入演示截图序列（3 组示例）
│   │   ├── injection_demo_01/                   # Demo 1: 携程旅行
│   │   ├── injection_demo_02/                   # Demo 2: 铁路12306
│   │   └── injection_demo_03/                   # Demo 3: 哔哩哔哩
│   └── gt-category/                             # GT 模板（按异常类型分类）
│       ├── dialog/                              # 弹窗模板集
│       ├── area_loading/                        # 加载异常模板
│       └── content_duplicate/                   # 内容重复模板
│
├── docs/                                        # 文档
│   ├── architecture.md                          # 系统架构文档
│   ├── 技术难题.md                              # 技术难题分析
│   ├── 技术难题业界与项目方案对照.md
│   ├── 总结.md                                  # 项目总结
│   ├── 优化说明.md                              # 异常注入与弹窗优化
│   ├── 异常模式输出序列分析.md
│   ├── rule-engine-plan.md                      # 规则引擎实施计划
│   └── plans/                                   # 设计文档
│       ├── mapping-auto-generation-plan.md      # 映射自动生成方案
│       └── page-type-redesign.md                # 页面类型分类 v3
│
├── outputs/                                     # 流水线输出目录
├── tmp/                                         # 临时文件
│
├── ui_semantic_patch/                           # 核心框架
│   ├── README.md                                # 框架详细说明
│   ├── requirements.txt                         # Python 依赖
│   ├── 异常query说明.md                         # 异常 Query 质量说明
│   │
│   ├── app/                                     # 核心应用代码（Python 包）
│   │   ├── cli/pipeline.py                      # CLI 命令行入口
│   │   ├── core/                                # 核心配置 (config.py) 与数据结构 (schemas.py)
│   │   ├── stages/                              # 三阶段流水线
│   │   │   ├── omni_extractor.py                # Stage 1: OmniParser UI 元素检测
│   │   │   ├── omni_vlm_fusion.py               # Stage 2: VLM 语义分组与融合
│   │   │   ├── gt_bounds.py                     # GT 模板边界匹配
│   │   │   └── visualize.py                     # 可视化输出
│   │   ├── renderers/                           # 异常渲染器
│   │   │   ├── base.py                          # 渲染器统一基类
│   │   │   ├── dialog.py                        # 弹窗覆盖渲染
│   │   │   ├── area_loading.py                  # 区域加载异常
│   │   │   ├── content_duplicate.py             # 内容重复
│   │   │   ├── text_overlay.py                  # 文字覆盖
│   │   │   └── patch.py                         # AI 图像编辑渲染
│   │   ├── injection/                           # 注入决策引擎
│   │   │   ├── sequence_analyzer.py             # 操作序列分析
│   │   │   ├── page_classifier.py               # 页面类型分类
│   │   │   ├── anomaly_mapping_resolver.py      # 异常映射解析
│   │   │   ├── anomaly_recommender.py           # 异常类型推荐
│   │   │   ├── sequence_rewriter.py             # 序列改写
│   │   │   ├── rule_engine.py                   # 规则引擎
│   │   │   ├── rules.json                       # 规则定义
│   │   │   └── quality_verifier.py              # 质量验证
│   │   ├── generators/                          # 元数据生成
│   │   └── utils/                               # 工具库（GT 管理、历史管理、日志等）
│   │
│   ├── config/                                  # 异常映射配置
│   │   ├── mapping.json                         # 综合映射
│   │   ├── mapping_dialog.json                  # 弹窗映射
│   │   ├── mapping_area_loading.json            # 加载异常映射
│   │   ├── mapping_content_duplicate.json       # 内容重复映射
│   │   ├── mapping_text_overlay.json            # 文字覆盖映射
│   │   ├── mapping_modify_text.json             # 文字编辑映射
│   │   ├── mapping_modify_text_ai.json          # AI 文字编辑映射
│   │   ├── mapping_response_delay.json          # 响应延迟映射
│   │   └── query_anomaly_mapping.json           # Query 异常映射
│   │
│   ├── scripts/                                 # 入口脚本
│   │   ├── run_pipeline.py                      # 三阶段主流水线
│   │   ├── batch_pipeline.py                    # 批量生成
│   │   ├── injection_pipeline.py                # 注入决策流水线
│   │   ├── batch_injection.py                   # 批量注入
│   │   ├── batch_injection_with_mapping.py     # 带映射的批量注入
│   │   ├── start.sh                             # 一键启动脚本
│   │   └── web_ui/                              # Web 管理界面
│   │       ├── server.py                        # Flask 后端
│   │       └── index.html                       # 前端界面
│   │
│   └── third_party/OmniParser/                  # OmniParser 本地集成
│       ├── omni_inference.py                    # 推理入口
│       └── weights/                             # 模型权重
│           ├── icon_detect/                     # YOLO 图标检测
│           ├── icon_caption_florence/           # Florence2 图标描述
│           └── ocr/                             # PaddleOCR
```

---

## 文档导航

| 类别 | 链接 | 说明 |
|------|------|------|
| 架构文档 | [docs/architecture.md](./docs/architecture.md) | 系统架构、模块设计、数据流 |
| 技术难题 | [docs/技术难题.md](./docs/技术难题.md) | 核心挑战与解决方案 |
| 业界对照 | [docs/技术难题业界与项目方案对照.md](./docs/技术难题业界与项目方案对照.md) | 业界方案与本项目方案对比 |
| 项目总结 | [docs/总结.md](./docs/总结.md) | 项目整体总结 |
| 优化说明 | [docs/优化说明.md](./docs/优化说明.md) | 异常注入与弹窗优化记录 |
| 设计文档 | [docs/plans/](./docs/plans/) | 映射生成方案、页面分类设计 |
| 框架说明 | [ui_semantic_patch/README.md](./ui_semantic_patch/README.md) | 框架架构、使用说明 |
| 异常 Query | [ui_semantic_patch/异常query说明.md](./ui_semantic_patch/异常query说明.md) | 异常 Query 质量与问题说明 |

---

## 当前进展

### 项目阶段
**Phase 2: 原型开发与优化** — 进行中

### 最新里程碑

**Milestone 6: 项目结构重组** (2026-05-15)
- 核心框架重构为 `ui_semantic_patch/app/` 标准 Python 包结构（`cli/`、`core/`、`stages/`、`renderers/`、`injection/`、`generators/`、`utils/`）
- 数据目录独立到根级 `data/`（`data_process/`、`examples/`、`gt-category/`）
- 文档归集到 `docs/`，新增技术难题分析、架构文档等
- 配置文件集中到 `ui_semantic_patch/config/`，支持 8 种异常映射配置
- 清理过时输出文件，新增 Web UI 实时日志流

**Milestone 5: 多后端图像生成支持** (2026-05-07)
- 新增 **华为 MLOps** 图像生成后端支持（OpenAI 兼容格式）
- 新增通用 **IMAGE_GEN_*** 配置变量，兼容任意 OpenAI 格式 API 提供商
- 完善配置回退机制：`IMAGE_GEN_API_KEY` → `DASHSCOPE_API_KEY`
- 支持 4 种图像生成后端：`dashscope` / `huawei_mlops` / `local` / `auto`
- 向后兼容：现有 `DASHSCOPE_*` 配置无需修改即可继续工作

**Milestone 4: 架构重构与注入决策** (2026-03-09)
- 完成脚本层重构：拆分为 `stages/`、`renderers/`、`generators/`、`injection/` 四个子包
- 实现渲染器统一基类（`renderers/base.py`）
- 新增 `text_overlay` 文字覆盖模式；扩展 `modify_text_ai` / `modify_text_ocr` / `modify_text_e2e` 等细粒度文字编辑路径
- 持续扩充 GT 模板与 bounds
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

**图像生成**: DashScope AI · 华为 MLOps · Local SD · PIL/Pillow (多后端自动切换)

**异常渲染**: 程序化合成 · Alpha 混合 · 组件裁剪 · AI 图像编辑

**注入决策**: VLM 语义分析 · GT 模板匹配 · 操作序列建模

---

## 许可证

待定

---

**最后更新**: 2026-05-15
**项目状态**: Phase 2 进行中
**里程碑**: Milestone 6 完成
