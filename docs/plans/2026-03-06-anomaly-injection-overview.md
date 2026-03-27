# 异常注入决策模块实现概览

**创建日期**: 2026-03-06
**状态**: ✅ 已完成
**相关文档**:
- [设计文档](./2026-03-06-anomaly-injection-decision-design.md)
- [实现计划](./2026-03-06-anomaly-injection-implementation-plan.md)

---

## 模块概述

基于 UI-Venus 的增量式上下文理解机制，实现操作序列（UI截图序列）的异常注入决策功能。

### 核心流程

```
截图序列输入 → 增量式语义分析 → 注入点决策 → 用户确认 → 异常生成 → 序列改写 → 输出
```

---

## 文件结构

```
prototypes/ui_semantic_patch/
├── scripts/
│   ├── injection/
│   │   ├── __init__.py              # 模块初始化，导出核心类
│   │   ├── prompts.py               # VLM 提示词模板（借鉴 UI-Venus 格式）
│   │   ├── anomaly_recommender.py   # 异常推荐器，读取 GT 模板库
│   │   ├── sequence_analyzer.py     # 增量式语义分析器（核心模块）
│   │   └── sequence_rewriter.py     # 序列改写器，调用生成器并改写序列
│   ├── injection_pipeline.py        # 命令行主入口
│   └── utils/
│       └── history_manager.py       # 历史记录管理器（借鉴 UI-Venus）
└── examples/
    └── injection_demo/
        ├── task.json                # 示例任务配置
        └── screenshots/             # 放置测试截图
```

---

## 使用方法

### 命令行调用

```bash
cd prototypes/ui_semantic_patch/scripts

# 交互式模式（推荐）
python injection_pipeline.py \
  --input-dir examples/injection_demo \
  --output-dir output/injected

# 非交互式模式（自动确认）
python injection_pipeline.py \
  --input-dir examples/injection_demo \
  --output-dir output/injected \
  --no-interactive

# 指定任务描述
python injection_pipeline.py \
  --input-dir ./my_screenshots \
  --output-dir ./output \
  --task "在携程App预订杭州酒店"
```

### 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--input-dir, -i` | 输入目录（必需） | - |
| `--output-dir, -o` | 输出目录（必需） | - |
| `--task, -t` | 任务描述 | 从 task.json 读取 |
| `--interactive` | 启用用户确认 | True |
| `--no-interactive` | 禁用用户确认 | - |
| `--max-history` | 最大历史步数 | 10 |
| `--min-steps` | 最少分析步数后才注入 | 2 |
| `--gt-template-dir` | GT 模板目录 | 项目默认路径 |

### 输入目录结构

```
input/
├── task.json           # {"description": "任务描述"}
└── screenshots/
    ├── step_00.png
    ├── step_01.png
    ├── step_02.png
    └── ...
```

### 输出目录结构

```
output/injection_YYYYMMDD_HHMMSS/
├── modified_sequence/
│   ├── step_00.png           # 原始截图
│   ├── step_01.png           # 原始截图
│   ├── step_02.png           # 注入点截图
│   ├── step_03_anomaly.png   # 生成的异常截图
│   └── step_04_anomaly.png   # 可选的后续异常状态
├── anomaly_generated/        # 异常生成器原始输出
├── metadata.json             # 序列元数据
└── decision_log.json         # 决策过程日志
```

---

## 核心模块说明

### 1. SequenceAnalyzer（增量式语义分析器）

**职责**: 逐步分析截图序列，累积上下文，决策注入点

```python
from injection import SequenceAnalyzer, AnomalyRecommender

recommender = AnomalyRecommender()
analyzer = SequenceAnalyzer(
    recommender=recommender,
    task_description="在携程预订酒店"
)

result = analyzer.run(screenshots)
# result = {
#     "success": True,
#     "injection_point": 3,
#     "anomaly_type": "弹窗覆盖原UI",
#     "instruction": "添加优惠券弹窗",
#     "reasoning": "当前是酒店列表页...",
#     "history": [...]
# }
```

### 2. AnomalyRecommender（异常推荐器）

**职责**: 读取 GT 模板库，提供可选异常类型

```python
from injection import AnomalyRecommender

recommender = AnomalyRecommender()
categories = recommender.get_available_categories()
# ['弹窗覆盖原UI', '内容歧义、重复', 'loading_timeout']

description = recommender.get_categories_description()
# 格式化的异常类型描述（供 VLM 使用）
```

### 3. SequenceRewriter（序列改写器）

**职责**: 调用已有生成器，改写操作序列

```python
from injection import SequenceRewriter

rewriter = SequenceRewriter(output_dir="./output")
result = rewriter.rewrite(
    original_screenshots=screenshots,
    injection_point=3,
    anomaly_type="弹窗覆盖原UI",
    instruction="添加优惠券弹窗"
)
# result = {
#     "success": True,
#     "output_path": Path(...),
#     "modified_sequence": [...],
#     "anomaly_images": [...]
# }
```

---

## UI-Venus 借鉴点

| 借鉴点 | UI-Venus 原实现 | 本模块实现 |
|-------|----------------|-----------|
| 增量式历史累积 | `_build_query()` 中 `history_entries` | `HistoryManager.build_history_text()` |
| 思考链格式 | `<think>...</think><action>...</action>` | `<think>...</think><decision>...</decision>` |
| 结构化输出解析 | `extract_tag_content()` | `SequenceAnalyzer._parse_vlm_response()` |
| 历史窗口限制 | `history_length` | `max_history_steps` |
| 步骤格式化 | `f"Step {i}: ..."` | `StepRecord.to_history_entry()` |

---

## 设计决策

| 决策点 | 选择 | 理由 |
|-------|------|------|
| 处理模式 | 增量式（逐步决策） | 上下文累积更深，符合 Agent 思维 |
| 注入策略 | 单点注入 | MVP 阶段简化逻辑 |
| 注入后处理 | 立即终止 | 异常后原序列逻辑中断 |
| 异常选择 | VLM推荐 + 用户确认 | 平衡自动化与可控性 |

---

## 环境要求

### 环境变量

```bash
# .env 文件
VLM_API_KEY=your_api_key          # 必需
VLM_API_URL=https://api.xxx.com   # 可选，默认 OpenAI
VLM_MODEL=gpt-4o                  # 可选，默认 gpt-4o
```

### 依赖

复用现有依赖，无需额外安装。

---

## 后续工作

1. **准备测试数据**: 在 `examples/injection_demo/screenshots/` 放入实际操作序列截图
2. **端到端测试**: 验证完整流程
3. **提示词调优**: 根据实际效果调整 `prompts.py`
4. **批量处理**: 支持多序列批量注入（后续迭代）

---

**最后更新**: 2026-03-26
**文档同步**: 原型总览见仓库根目录 [Claude.md](../../Claude.md)。
