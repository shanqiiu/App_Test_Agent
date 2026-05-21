# App_Test_Agent

面向 AI Agent 测试的异常场景自动生成工具链。

项目当前聚焦两件事：

1. 对单张 App 截图生成异常 UI。
2. 在真实操作轨迹中选择合适时机插入异常，并输出可回放的异常截图序列。

## 当前主线

仓库现在有三条主要链路：

### 1. 单图异常生成

入口：

- `ui_semantic_patch/scripts/run_pipeline.py`

用途：

- 对单张截图生成 `dialog`、`area_loading`、`content_duplicate`、`text_overlay`、`modify_text*`、`image_broken` 等异常图。

### 2. 视觉序列注入

入口：

- `ui_semantic_patch/scripts/injection_pipeline.py`

流程：

- 截图序列
- `PageClassifier`
- `RuleEngine`
- `SequenceAnalyzer`
- `SequenceRewriter`

适合场景：

- 只有截图，没有 `ui_summary` 语义轨迹。

### 3. UTG 文本注入

入口：

- `ui_semantic_patch/scripts/batch_utg_injection.py`

流程：

- `utg_info.json`
- `UTGLoader`
- `UTGDecisionMaker`
- `run_pipeline.py`

适合场景：

- 已经有云端执行轨迹，且每步带 `ui_summary`。

## 核心能力

### 异常模式

当前主要模式：

- `dialog`
- `area_loading`
- `content_duplicate`
- `text_overlay`
- `modify_text`
- `modify_text_ai`
- `modify_text_ocr`
- `modify_text_e2e`
- `image_broken`
- `response_delay`

说明：

- `response_delay` 是序列层异常，不走单图渲染器。
- `dialog` 是最依赖 GT 模板的一类模式。

### 决策方式

当前支持两种注入点决策：

1. 视觉决策
   - 基于截图做页面分类和规则匹配。
2. UTG 文本决策
   - 基于 `utg_info.json` 中的 `ui_summary` 做全序列文本打分。

## 快速开始

### 1. 安装

```bash
pip install -r ui_semantic_patch/requirements.txt
pip install -r ui_semantic_patch/third_party/OmniParser/requirements.txt
```

准备 `.env`，至少配置：

- `VLM_API_KEY`
- `VLM_API_URL`
- `VLM_MODEL`

### 2. 单图生成

```bash
cd ui_semantic_patch/scripts

python run_pipeline.py \
  --screenshot ../../data/gt-category/dialog/京东到家-外卖页面-优惠券弹窗.jpg \
  --instruction "生成优惠券广告弹窗" \
  --anomaly-mode dialog \
  --output ../../outputs/demo_single
```

### 3. UTG 批量注入

```bash
python batch_utg_injection.py \
  --examples-dir ../../data/examples \
  --mapping-config ../../tmp/mapping.json \
  --output-dir ../../outputs/utg_batch
```

### 4. Web UI

```bash
cd ui_semantic_patch/scripts/web_ui
python server.py
```

默认地址：

- `http://localhost:8767`

更完整的脚本说明、核心目录职责和运行入口见：

- [ui_semantic_patch/README.md](./ui_semantic_patch/README.md)

## 关键数据

### UTG 输入目录

```text
data/examples/{uuid}/
├── utg_info.json
├── 001.jpg
├── 002.jpg
└── ...
```

### UTG 核心字段

```json
{
  "query": "...",
  "uuid": "...",
  "appName": "...",
  "stepData": [
    {
      "stepId": "4",
      "thought": "...",
      "ui_summary": "...",
      "imageId": "001"
    }
  ]
}
```

### 常见输出

```text
outputs/.../
├── modified_sequence/
├── anomaly_generated/
├── metadata.json
└── decision_log.json
```

## 仓库结构

```text
App_Test_Agent/
├── data/                     # 示例数据、GT 模板、mapping 生成脚本
├── docs/                     # 当前有效文档
├── outputs/                  # 生成结果
├── tmp/                      # 临时 mapping、样例、调试文件
└── ui_semantic_patch/        # 核心实现
    ├── app/
    │   ├── core/
    │   ├── stages/
    │   ├── renderers/
    │   ├── injection/
    │   └── utils/
    ├── scripts/
    ├── config/
    └── third_party/
```

## 文档入口

- [docs/README.md](./docs/README.md)
- [docs/architecture.md](./docs/architecture.md)
- [docs/utg-architecture.md](./docs/utg-architecture.md)
- [docs/mapping-generation.md](./docs/mapping-generation.md)
- [ui_semantic_patch/README.md](./ui_semantic_patch/README.md)

## 说明

1. 根目录 `docs/` 负责说明系统现状和设计边界。
2. `ui_semantic_patch/README.md` 负责说明核心实现目录和常用入口。
3. 如果文档和代码冲突，以当前代码实现为准。
