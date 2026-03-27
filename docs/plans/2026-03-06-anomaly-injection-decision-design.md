# 异常注入决策模块设计文档

**文档类型**: 设计文档
**创建日期**: 2026-03-06
**状态**: 待实现
**标签**: `异常注入` `决策引擎` `UI-Venus借鉴`

---

## 概述

本文档定义了 App_Test_Agent 项目中**异常注入决策模块**的设计方案。该模块负责分析操作序列（UI截图序列），决策在何处注入何种异常，并调用已有的异常生成器完成序列改写。

### 核心目标

将一段正常的操作序列（由 UI 截图构成）改写为包含异常场景的测试序列。

### 与 UI-Venus 的关系

本设计借鉴了 UI-Venus 项目的**增量式上下文理解机制**，将其从"实时执行 Agent"场景适配到"离线序列处理"场景。

---

## 设计决策

| 决策点 | 选择 | 理由 |
|-------|------|------|
| 处理模式 | 增量式（逐步决策） | 上下文累积，理解更深；符合 Agent 思维模式 |
| 注入策略 | 单点注入 | 简化逻辑，MVP 阶段聚焦核心功能 |
| 注入后处理 | 立即终止 | 异常注入后原序列逻辑已中断，截断更合理 |
| 异常选择 | 混合模式（VLM推荐 + 用户确认） | 平衡自动化与可控性 |

---

## 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    异常注入决策流水线                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  输入: 截图序列 [s0, s1, s2, ..., sN] + 任务描述                   │
│                          ↓                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              增量式语义分析器 (借鉴 UI-Venus)              │   │
│  │  ┌─────┐    ┌─────┐    ┌─────┐         ┌─────┐         │   │
│  │  │ s0  │ →  │ s1  │ →  │ s2  │ → ... → │ sK  │ ← 决策点 │   │
│  │  └─────┘    └─────┘    └─────┘         └─────┘         │   │
│  │  history=[] history+   history++       发现注入机会！    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          ↓                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              异常推荐器 (读取 GT 模板库)                    │   │
│  │  推荐: ["弹窗覆盖原UI", "loading_timeout"]                 │   │
│  │  理由: "当前界面为商品列表，适合注入加载超时或广告弹窗"       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          ↓                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              用户确认 (可选)                               │   │
│  │  [确认] / [换一个] / [指定其他异常类型]                     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          ↓                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              异常生成器 (已有实现)                         │   │
│  │  调用: run_pipeline.py --anomaly-mode dialog ...          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          ↓                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              序列改写器                                    │   │
│  │  输入:  [s0, s1, s2, ..., sK, sK+1, ..., sN]              │   │
│  │  输出:  [s0, s1, s2, ..., sK, 异常截图, 异常截图2]         │   │
│  │         (在 sK 后插入异常，截断后续)                        │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          ↓                                      │
│  输出: 改写后的截图序列 + 决策日志                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 核心模块设计

### 1. 增量式语义分析器

**职责**: 逐步分析截图序列，累积上下文，决策注入点

**输入输出**:
```python
输入:
  - screenshots: List[Path]      # 截图序列
  - task_description: str        # 任务描述（如"在携程预订酒店"）
  - gt_categories: List[str]     # 可用的异常类别（从 GT 模板库读取）

输出:
  - injection_point: int         # 注入位置（截图索引）
  - recommended_anomaly: str     # 推荐的异常类型
  - reasoning: str               # 决策理由
  - context_history: List[dict]  # 完整的分析历史
```

**VLM 提示词模板**（借鉴 UI-Venus）:

```
###你是一个异常注入决策器
分析当前界面截图，结合历史步骤，判断此处是否适合注入异常。

###用户任务
{task_description}

###可注入的异常类型
{gt_categories_with_descriptions}

###先前的步骤分析
{previous_steps}

###当前步骤
这是第 {step_index} 步的界面截图。

###输出格式
<think>分析当前界面语义，判断是否适合注入异常</think>
<decision>INJECT / SKIP</decision>
<anomaly_type>如果 INJECT，选择的异常类型</anomaly_type>
<instruction>如果 INJECT，异常生成指令（如"在列表区域添加加载超时提示"）</instruction>
<conclusion>本步骤总结</conclusion>
```

### 2. 异常推荐器

**职责**: 读取 GT 模板库，为 VLM 提供可选异常类型及其描述

```python
# 从已有 GT 模板目录结构读取
gt_templates/
├── 弹窗覆盖原UI/
│   ├── meta.json          # 包含视觉特征描述
│   └── 弹出广告.jpg
├── 内容歧义、重复/
│   └── ...
└── loading_timeout/
    └── ...

# 输出给 VLM 的格式
gt_categories_with_descriptions = """
1. 弹窗覆盖原UI: 全屏或半屏弹窗遮挡原有界面，如广告、优惠券、系统提示
2. 内容歧义、重复: 界面内容重复显示或语义冲突
3. loading_timeout: 加载超时、网络错误等状态
"""
```

### 3. 序列改写器

**职责**: 根据决策结果，生成改写后的序列

```python
输入:
  - original_sequence: [s0, s1, ..., sN]
  - injection_point: K
  - anomaly_images: [异常截图1, 异常截图2]  # 由已有生成器产出

输出:
  - modified_sequence: [s0, s1, ..., sK, 异常截图1, 异常截图2]
  - metadata: {
      "original_length": N+1,
      "injection_point": K,
      "anomaly_type": "弹窗覆盖原UI",
      "truncated_steps": N-K
    }
```

---

## 数据流

### 完整处理流程

```
Step 1: 初始化
────────────────────────────────────────────────────────
输入目录结构:
  input/
  ├── task.json              # {"description": "在携程预订酒店"}
  └── screenshots/
      ├── step_00.png
      ├── step_01.png
      └── ...

GT模板库 (已有):
  data/Agent执行遇到的典型异常UI类型/analysis/gt_templates/
  ├── 弹窗覆盖原UI/
  ├── 内容歧义、重复/
  └── loading_timeout/


Step 2: 增量式分析 (循环)
────────────────────────────────────────────────────────
for i, screenshot in enumerate(screenshots):

    VLM 输入:
    ┌──────────────────────────────────────┐
    │ 任务: "在携程预订酒店"                 │
    │ 历史: [Step0分析, Step1分析, ...]     │
    │ 当前截图: step_{i}.png               │
    │ 可选异常: [弹窗覆盖原UI, loading...]   │
    └──────────────────────────────────────┘
                    ↓
    VLM 输出:
    ┌──────────────────────────────────────┐
    │ <think>当前是酒店列表页...</think>    │
    │ <decision>INJECT</decision>          │
    │ <anomaly_type>弹窗覆盖原UI</anomaly>  │
    │ <instruction>添加优惠券弹窗</instruct>│
    └──────────────────────────────────────┘
                    ↓
    if decision == "INJECT":
        break  # 立即终止循环


Step 3: 用户确认 (可选)
────────────────────────────────────────────────────────
显示:
  注入位置: Step 3 (酒店列表页)
  推荐异常: 弹窗覆盖原UI
  生成指令: "添加优惠券弹窗"

用户选择: [确认] / [换一个] / [自定义]


Step 4: 调用已有异常生成器
────────────────────────────────────────────────────────
python run_pipeline.py \
  --screenshot input/screenshots/step_03.png \
  --instruction "添加优惠券弹窗" \
  --anomaly-mode dialog \
  --gt-category "弹窗覆盖原UI" \
  --output output/anomaly/


Step 5: 序列改写
────────────────────────────────────────────────────────
原序列:  [step_00, step_01, step_02, step_03, step_04, step_05]
                                      ↑ 注入点
改写后: [step_00, step_01, step_02, step_03, anomaly_01, anomaly_02]
                                              ↑ 异常截图  ↑ 可选后续


Step 6: 输出
────────────────────────────────────────────────────────
output/
├── modified_sequence/
│   ├── step_00.png          # 原始
│   ├── step_01.png          # 原始
│   ├── step_02.png          # 原始
│   ├── step_03.png          # 原始（注入点基准）
│   ├── step_04_anomaly.png  # 生成的异常
│   └── step_05_anomaly.png  # 可选的异常后续状态
├── decision_log.json        # 决策过程记录
└── metadata.json            # 序列元数据
```

### 核心接口

```python
# 主入口
def inject_anomaly_pipeline(
    input_dir: Path,           # 输入目录（含 task.json + screenshots/）
    output_dir: Path,          # 输出目录
    interactive: bool = True,  # 是否启用用户确认
    gt_template_dir: Path = None,  # GT模板库路径，默认使用已有路径
) -> dict:
    """
    返回:
    {
        "success": True,
        "injection_point": 3,
        "anomaly_type": "弹窗覆盖原UI",
        "original_length": 6,
        "modified_length": 5,
        "output_path": "output/modified_sequence/"
    }
    """
```

---

## UI-Venus 借鉴点总结

| 借鉴点 | UI-Venus 原实现 | App_Test_Agent 应用 |
|-------|----------------|-------------------|
| **增量式历史维护** | `_build_query()` 中 `history_entries` 累积 | 每步分析结果累积到 `previous_steps` |
| **思考链格式** | `<think>...</think><action>...</action>` | `<think>...</think><decision>...</decision>` |
| **结构化输出解析** | `extract_tag_content()` 正则提取 | 复用相同解析逻辑 |
| **历史窗口限制** | `history_length` 控制上下文长度 | 可配置 `max_history_steps` |
| **步骤格式化** | `f"Step {i}: ..."` | 相同格式，便于 VLM 理解 |

---

## 文件结构

### 新增文件

```
prototypes/ui_semantic_patch/
├── scripts/
│   ├── run_pipeline.py              # 已有：异常生成入口
│   ├── injection_pipeline.py        # 新增：异常注入决策主入口
│   ├── injection/                   # 新增：注入决策模块目录
│   │   ├── __init__.py
│   │   ├── sequence_analyzer.py     # 增量式语义分析器
│   │   ├── anomaly_recommender.py   # 异常推荐器
│   │   ├── sequence_rewriter.py     # 序列改写器
│   │   └── prompts.py               # VLM 提示词模板
│   └── utils/
│       ├── common.py                # 已有
│       └── history_manager.py       # 新增：历史记录管理（借鉴UI-Venus）
├── data/
│   └── ...                          # 已有 GT 模板
└── examples/
    └── injection_demo/              # 新增：示例输入序列
        ├── task.json
        └── screenshots/
```

### 与已有模块的集成

```
                    injection_pipeline.py (新增)
                            │
            ┌───────────────┼───────────────┐
            ↓               ↓               ↓
    sequence_analyzer   anomaly_recommender  sequence_rewriter
            │               │               │
            │               ↓               │
            │       meta_loader.py (已有)   │
            │       gt_manager.py (已有)    │
            │               │               │
            └───────────────┼───────────────┘
                            ↓
                    run_pipeline.py (已有)
                    ├── patch_renderer.py
                    ├── area_loading_renderer.py
                    └── content_duplicate_renderer.py
```

---

## 成功标准

| 维度 | 指标 | 目标值 |
|------|------|--------|
| **功能完整性** | 能完成完整的注入决策→生成→改写流程 | 100% |
| **决策合理性** | VLM 推荐的注入点和异常类型语义合理（人工评估） | ≥ 80% |
| **生成质量** | 复用已有生成器，质量与现有一致 | 保持现有水平 |
| **处理效率** | 10 步序列的决策时间 | < 60 秒 |

---

## MVP 范围

### 包含

- 增量式语义分析器（核心）
- 异常推荐器（读取已有 GT 模板）
- 序列改写器
- 命令行交互确认
- 决策日志输出

### 不包含（后续迭代）

- Web UI 交互界面
- 批量序列处理
- 多点注入支持
- 异常类型自动扩展

---

## 风险与应对

| 风险 | 可能性 | 影响 | 应对措施 |
|------|--------|------|---------|
| VLM 决策不稳定 | 中 | 中 | 增加 `temperature=0` 确定性输出；多次采样投票 |
| 上下文过长超限 | 低 | 高 | 设置 `max_history_steps` 窗口限制 |
| 异常类型不匹配 | 中 | 中 | 用户确认环节兜底；支持自定义指令 |
| 与已有生成器集成问题 | 低 | 中 | 复用已验证的调用方式 |

---

## 依赖项

### 已有依赖（无需新增）

- VLM API（已配置 VLM_API_KEY）
- OmniParser（已集成）
- 异常生成器（run_pipeline.py 已实现）
- GT 模板库（已有数据）

### 新增依赖

- 无（复用现有技术栈）

---

**创建日期**: 2026-03-06
**基于**: UI-Venus 项目分析 + App_Test_Agent 需求澄清
**下一步**: 创建实现计划

---

**文档同步**: 2026-03-26 — 环境变量与流水线入口说明以仓库根目录 [Claude.md](../../Claude.md) 为准。
