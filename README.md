# App_Test_Agent

**AI 智能体测试技术研究 — 异常场景自动生成平台**

[![Project Status](https://img.shields.io/badge/status-prototype-blue)]()
[![Phase](https://img.shields.io/badge/phase-3_optimization-green)]()
[![Last Updated](https://img.shields.io/badge/updated-2026--05--20-brightgreen)]()

---

## 项目简介

本项目专注于**AI 智能体（AI Agent）异常测试场景自动生成**。核心能力包括：

1. **单图异常生成**：对单张 APP 截图注入弹窗、加载异常、文字覆盖等效果
2. **序列注入决策（VLM 视觉方案）**：逐帧 VLM 图像分析 → 页面分类 → 规则引擎 → 注入点决策
3. **序列注入决策（UTG 文本方案）** ⭐ 新：基于云端 Agent 执行时已有的 `ui_summary` 语义描述，通过文本 LLM 一次调用完成全序列批量打分 + 注入点决策，免去逐帧 VLM 图像分析

### 解决方案演进

```
VLM 视觉方案（旧）:
截图序列 → 逐帧 VLM 图像分析 → 页面分类 → 规则引擎 → 注入决策
  ↑ 每帧编码图片、调 VLM API，成本高、不稳定

UTG 文本方案（新）:
utg_info.json（已有 ui_summary） → 文本 LLM 一次调用 → 全序列打分 → 注入决策
  ↑ 已有语义数据、纯文本调用，成本仅 1/10，决策更精准
```

---

## 核心能力

### 异常渲染模式

| 异常模式 | 说明 | 序列影响 |
|----------|------|---------|
| `dialog` | 弹窗覆盖注入 | 可关闭：加 anomaly + normal 恢复 |
| `area_loading` | 区域加载异常 | 可关闭：加 anomaly + normal 恢复 |
| `content_duplicate` | 内容重复/歧义 | 可关闭：加 anomaly + normal 恢复 |
| `modify_text` | 文字修改（OCR + PIL） | 永久修改 |
| `text_overlay` | 局部文字覆盖 | 永久修改 |
| `image_broken` | 图片资源损坏 | 永久修改 |

### 注入决策模式

| 模式 | 输入 | 决策方式 | 适用场景 |
|------|------|---------|---------|
| **VLM 视觉** | 截图序列 | 逐帧 VLM 图像分析 → 规则引擎 | 无预标注数据的场景 |
| **UTG 文本** ⭐ | `utg_info.json` | 全量 ui_summary 文本 LLM 批量打分 | 已有云端 Agent 执行数据 |

---

## 快速开始

### 1. 环境准备

```bash
cp .env.example .env
pip install -r ui_semantic_patch/requirements.txt
```

必需环境变量：`VLM_API_KEY`、`VLM_API_URL`、`VLM_MODEL`

### 2. 单图异常生成

```bash
cd ui_semantic_patch/scripts
python run_pipeline.py \
  --screenshot ../../data/gt-category/dialog/example.jpg \
  --instruction "生成优惠券广告弹窗" \
  --anomaly-mode dialog \
  --output ./output/demo
```

### 3. UTG 批量异常注入（推荐）

```bash
# 扫描 data/examples/ 下所有 UUID 目录，匹配 mapping.json，批量生成
python batch_utg_injection.py \
  --examples-dir ../data/examples \
  --mapping-config ../tmp/mapping.json \
  --output-dir ../outputs/utg_batch

# Dry-run：仅 LLM 打分预览，不生成图片
python batch_utg_injection.py --examples-dir ../data/examples --dry-run
```

### 4. Web UI

```bash
cd ui_semantic_patch/scripts/web_ui
python server.py
# 浏览器打开 http://localhost:8767
```

---

## 数据格式

### UTG 示例目录 (`data/examples/{uuid}/`)

```
data/examples/14a37b63-550e-489d-a55b-50e8cfc6b38a/
├── uitg_info.json       # query + stepData (ui_summary + thought + imageId)
├── 001.jpg              # step 0 截图
├── 002.jpg              # step 1 截图
└── ...
```

### utg_info.json 结构

```json
{
  "query": "到天猫帮买一双黑色的37码运动鞋",
  "uuid": "14a37b63-550e-489d-a55b-50e8cfc6b38a",
  "appName": "天猫",
  "stepData": [
    {
      "stepId": "4",
      "action_type": "set_text(...)",
      "thought": "【0】直接将搜索框内容改为...",
      "ui_summary": "页面顶部为搜索框，当前内容为...",
      "imageId": "001"
    }
  ]
}
```

### mapping.json 结构

```json
{
  "mappings": [
    {
      "query": "到天猫帮买一双黑色的37码运动鞋",
      "query_id": "14a37b63-550e-489d-a55b-50e8cfc6b38a",
      "injection_config": {
        "anomaly_mode": "image_broken",
        "instruction": "在购买页面注入遮挡层..."
      }
    }
  ]
}
```

### 注入输出

```
outputs/utg_batch/14a37b63-550e-489d-a55b-50e8cfc6b38a/
├── modified_sequence/
│   ├── 001.jpg              # 原图不动
│   ├── 002.jpg
│   ├── 003.jpg              # 注入点参考图
│   ├── 003_anomaly.jpg      # 异常图
│   ├── 003_normal.jpg       # 恢复图（可关闭类）
│   ├── 004.jpg
│   └── ...
├── anomaly_generated/
│   └── final_*.png
├── metadata.json
└── decision_log.json
```

---

## 项目结构

```
App_Test_Agent/
├── README.md
├── .env.example
│
├── data/
│   ├── examples/              # 示例任务（UUID 目录 + 旧 injection_demo）
│   └── gt-category/           # GT 模板（参考图 + meta.json）
│
├── docs/                      # 当前文档
│   ├── README.md              # 文档索引
│   ├── architecture.md        # 系统架构
│   ├── utg-architecture.md    # UTG 文本决策架构 ⭐
│   ├── mapping-generation.md  # Mapping 与定位机制
│   └── 技术难题业界与项目方案对照.md
│
├── outputs/                   # 输出目录
├── tmp/                       # 临时/开发文件
│   ├── mapping.json           # 异常映射配置
│   └── examples/              # 测试用示例
│
└── ui_semantic_patch/         # 核心框架
    ├── app/
    │   ├── injection/         # 注入决策引擎
    │   │   ├── sequence_analyzer.py    # VLM 增量式序列分析（旧）
    │   │   ├── rule_engine.py          # 规则引擎
    │   │   ├── sequence_rewriter.py    # 序列改写器
    │   │   ├── utg_loader.py          # UTG 数据加载器 ⭐
    │   │   ├── utg_decision.py        # UTG 文本决策器 ⭐
    │   │   └── ...
    │   ├── renderers/         # 异常渲染引擎
    │   ├── stages/            # 流水线阶段（OmniParser 等）
    │   ├── core/              # 配置与数据模型
    │   └── utils/             # 工具库
    ├── scripts/
    │   ├── run_pipeline.py            # 单图异常生成
    │   ├── injection_pipeline.py      # 注入流水线（VLM + UTG 双模式）
    │   ├── batch_utg_injection.py     # UTG 批量注入 ⭐
    │   ├── batch_injection_with_mapping.py  # VLM 批量注入（旧）
    │   └── web_ui/                    # Web 管理界面
    ├── config/                # 映射配置文件
    └── third_party/OmniParser/  # OmniParser 本地集成
```

---

## 技术栈

| 层次 | 技术 |
|------|------|
| **AI 感知** | OmniParser (YOLO + PaddleOCR + Florence2) |
| **文本决策** ⭐ | 纯文本 LLM（复用 VLM_API_KEY），全序列批量打分 |
| **视觉决策** | VLM (GPT-4o / qwen-vl-max) 图像分析 + 规则引擎 |
| **图像生成** | DashScope AI / 华为 MLOps / Local SD / PIL (多后端) |
| **渲染** | 程序化合成 · Alpha 混合 · AI 图像编辑 |
| **Web** | FastAPI + WebSocket 流式推送 |

---

## 文档导航

| 类别 | 链接 | 说明 |
|------|------|------|
| 文档索引 | [docs/README.md](./docs/README.md) | 当前保留文档与清理原则 |
| 系统架构 | [docs/architecture.md](./docs/architecture.md) | 整体系统架构 |
| UTG 架构 ⭐ | [docs/utg-architecture.md](./docs/utg-architecture.md) | UTG 文本决策设计与实现 |
| Mapping 与定位 | [docs/mapping-generation.md](./docs/mapping-generation.md) | Mapping 生成和目标定位机制 |
| 技术难题 | [docs/技术难题业界与项目方案对照.md](./docs/技术难题业界与项目方案对照.md) | 技术挑战与当前方案对照 |
| 框架说明 | [ui_semantic_patch/README.md](./ui_semantic_patch/README.md) | 框架架构与使用 |

---

## 许可证

待定

---

**最后更新**: 2026-05-20
**项目状态**: Phase 3 优化进行中
