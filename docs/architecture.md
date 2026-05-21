# App Test Agent 架构总览

本文档以当前仓库实现为准，覆盖项目的主入口、核心模块、数据流和输出约定。历史方案和已废弃设计不再在此展开。

## 1. 项目目标

项目目标是基于真实 App 截图或执行轨迹，自动生成可用于 Agent 测试的异常 UI 场景。当前主线分成两部分：

1. 单图异常渲染：对一张截图生成异常版本。
2. 序列注入决策：在一段操作轨迹里找出最合适的注入点，并把异常插入到序列中。

## 2. 当前目录结构

```text
App_Test_Agent/
├── README.md
├── docs/
├── data/
│   ├── examples/                 # 示例任务和 UTG 目录
│   ├── gt-category/              # GT 模板库
│   └── data_process/             # mapping 生成与处理脚本
├── outputs/                      # 生成结果
├── tmp/                          # 临时样例、调试产物、UTG mapping
└── ui_semantic_patch/
    ├── app/
    │   ├── core/                 # 路径配置、Schema
    │   ├── stages/               # Stage 1/2 感知流程
    │   ├── renderers/            # Stage 3 异常渲染器
    │   ├── injection/            # 注入决策、序列改写、质量验证
    │   └── utils/                # 通用工具
    ├── config/                   # legacy mapping 与 query mapping
    ├── scripts/                  # 直接执行脚本与 Web UI
    └── third_party/OmniParser/   # 本地视觉解析依赖
```

## 3. 运行主线

### 3.1 单图渲染

入口：

- `ui_semantic_patch/scripts/run_pipeline.py`

默认三阶段：

1. Stage 1 `omni_extractor.py`
   - 用 OmniParser 做粗检测，产出组件列表和可视化图。
2. Stage 2 `omni_vlm_fusion.py`
   - 结合截图和 Stage 1 检测结果做语义分组，产出更干净的 UI JSON。
3. Stage 3 `renderers/*`
   - 根据 `anomaly_mode` 选择具体渲染器并生成 `final_*.png`。

例外：

- `modify_text_e2e` 会跳过 Stage 1/2，直接在整图或粗裁剪区域上做端到端编辑。

### 3.2 视觉序列注入

入口：

- `ui_semantic_patch/scripts/injection_pipeline.py`

流程：

1. 读取 `task.json` 和截图序列。
2. `PageClassifier` 对每帧做二级分类：
   - `app_category`
   - `page_type`
3. `RuleEngine` 基于 `rules.json` 做规则匹配。
4. `SequenceAnalyzer` 遍历全序列，收集候选注入点并做最终排序。
5. `SequenceRewriter` 调 `run_pipeline.py` 生成异常图，再把异常插入序列。
6. `QualityVerifier` 可选地做 VLM 质量校验。

当前视觉决策不是“逐帧自由决策”，而是“分类 + 规则 + 内容门禁”的确定性混合方案。

### 3.3 UTG 文本注入

入口：

- `ui_semantic_patch/scripts/batch_utg_injection.py`
- `ui_semantic_patch/scripts/injection_pipeline.py --utg ...`

流程：

1. 从 `utg_info.json` 读取 `query`、`stepData`、`ui_summary`。
2. `UTGLoader` 过滤无效步骤，整理成纯文本上下文。
3. `UTGDecisionMaker` 用一次文本 LLM 调用做全序列打分或自由决策。
4. 选出注入点后仍然复用 `run_pipeline.py` 生成单张异常图。
5. 由脚本或 `SequenceRewriter` 组装异常序列。

UTG 模式的优势是复用已有 `ui_summary`，避免对每一帧重新看图。

## 4. 核心模块职责

### 4.1 `app/core`

- `config.py`
  - 统一管理项目根目录、脚本目录、GT 模板目录、OmniParser 路径。
- `schemas.py`
  - 定义 Stage1/Stage2 输出、编辑操作、渲染结果等结构。

### 4.2 `app/stages`

- `omni_extractor.py`
  - 调 OmniParser，生成原始组件检测结果。
- `omni_vlm_fusion.py`
  - 结合 VLM 做组件语义分组与过滤。
- `gt_bounds.py`
  - GT 相关边界框处理。
- `visualize.py`
  - 组件可视化输出。

### 4.3 `app/renderers`

当前已接入 `run_pipeline.py` 的模式：

| `anomaly_mode` | 渲染器 | 说明 |
|---|---|---|
| `dialog` | `patch.py` | 弹窗叠加，依赖 GT 模板 |
| `area_loading` | `area_loading.py` | 区域加载/超时覆盖 |
| `content_duplicate` | `content_duplicate.py` | 复制内容制造重复 |
| `text_overlay` | `text_overlay.py` | 局部加字、遮挡、替换 |
| `modify_text` | `text_overlay.py` | OCR/PIL 文字修改 |
| `modify_text_ai` | `text_overlay.py` | AI 编辑文字 |
| `modify_text_ocr` | `text_overlay.py` | OCR 精定位 + PIL |
| `modify_text_e2e` | `text_overlay.py` | 跳过检测的端到端编辑 |
| `image_broken` | `image_broken.py` | 图片损坏或遮挡 |

说明：

- `response_delay` 是序列层异常，不走单图渲染器。
- `dialog` 是唯一强依赖 GT 模板的主模式；其余模式多数可直接运行。

### 4.4 `app/injection`

- `page_classifier.py`
  - VLM 页面分类器，输出 `app_category`、`page_type`、关键元素、等待态。
- `rule_engine.py`
  - 加载 `rules.json`，根据分类结果挑选规则。
- `sequence_analyzer.py`
  - 全序列视觉分析器，负责候选点比较和最终注入点决策。
- `utg_loader.py`
  - 解析 `utg_info.json`。
- `utg_decision.py`
  - 文本 LLM 决策器，支持自由模式和约束模式。
- `sequence_rewriter.py`
  - 生成异常图并改写原始序列。
- `quality_verifier.py`
  - 生成后 VLM 质量评分。
- `anomaly_mapping_resolver.py`
  - legacy query-to-config 解析器，主要服务旧批量流程和 Web UI。

## 5. 规则和配置

### 5.1 页面规则

- 文件：`ui_semantic_patch/app/injection/rules.json`
- 作用：维护 `app_category × page_type -> anomaly_mode + instruction_template`
- 当前规则覆盖六类应用：
  - `travel`
  - `video`
  - `music`
  - `sports`
  - `social`
  - `delivery`

### 5.2 映射配置

仓库里存在两套映射配置，服务不同链路：

1. `tmp/mapping.json`
   - 主要供 UTG 批量注入使用。
2. `ui_semantic_patch/config/query_anomaly_mapping.json`
   - 主要供 legacy query 映射和 Web UI 默认配置使用。

另外，`ui_semantic_patch/config/mapping_*.json` 是按异常模式拆分的配置产物，更多用于生成和维护，不是唯一运行入口。

### 5.3 GT 模板

- 目录：`data/gt-category/`
- 当前目录与模式基本对应：
  - `dialog/`
  - `area_loading/`
  - `content_duplicate/`
- `meta.json` 提供模板的视觉特征、弹窗位置、关闭按钮样式等信息。

## 6. 序列改写语义

`SequenceRewriter` 目前有三种注入语义：

### 6.1 可关闭类异常

适用模式：

- `dialog`
- `area_loading`
- `content_duplicate`

序列形态：

```text
step_N        原图
step_N+1      异常图
step_N+2      恢复图（复制注入点原图）
step_N+3...   原后续序列
```

### 6.2 永久修改类异常

适用模式：

- `text_overlay`
- `modify_text*`
- `image_broken`

序列形态：

```text
step_N        原图
step_N+1      异常图
step_N+2...   原后续序列
```

### 6.3 响应延迟类异常

适用模式：

- `response_delay`

处理方式：

- 不调用 `run_pipeline.py`
- 直接复制前一帧插入到当前注入点，制造“UI 没有更新”的效果

## 7. 输入输出约定

### 7.1 UTG 输入目录

```text
data/examples/{uuid}/
├── utg_info.json
├── 001.jpg
├── 002.jpg
└── ...
```

### 7.2 单图输出

`run_pipeline.py` 常见产物：

- `*_stage1_omni_raw_*.json`
- `*_stage1_annotated_*.png`
- `*_stage2_filtered_*.json`
- `*_stage2_annotated_*.png`
- `final_*.png`
- `*_pipeline_meta_*.json`

### 7.3 序列输出

常见目录：

```text
outputs/.../{run_id}/
├── modified_sequence/
├── anomaly_generated/
├── metadata.json
└── decision_log.json
```

## 8. 当前文档边界

以下文档仍然是当前实现的有效补充：

- [utg-architecture.md](./utg-architecture.md)
- [mapping-generation.md](./mapping-generation.md)
- [技术难题业界与项目方案对照.md](./技术难题业界与项目方案对照.md)

`ui_semantic_patch/README.md` 保留较多历史说明，遇到冲突时应以本目录文档和实际代码为准。
