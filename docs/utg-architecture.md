# UTG 文本决策架构

## 1. 背景与动机

### 旧方案（VLM 视觉）的局限

```
截图序列 → 逐帧 VLM 图像分析 → 页面分类 → 规则引擎 → 注入决策
```

问题：
- **成本高**：每帧编码 base64 图片 + VLM API 调用，N 帧 = N 次调用
- **不稳定**：VLM 开放分类可能波动，同一帧不同调用结果不一致
- **冗余**：云端 Agent 执行时已有精准的 UI 语义理解（`ui_summary`），却被丢弃

### 新方案（UTG 文本）

```
utg_info.json（已有 ui_summary） → 文本 LLM 一次调用 → 全序列打分 → 注入决策
```

优势：
- **低成本**：一次纯文本 LLM 调用 ≈ 传统方案单帧图片调用的 1/5 成本
- **更精准**：`ui_summary` 是云端 Agent 执行时的实时语义描述，比事后 VLM 看图理解更准确
- **可解释**：每步返回 0-10 打分 + 理由，决策透明

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                        Web UI                               │
│  ┌──────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │ 单图生成  │  │ UTG 文本决策      │  │ 完整批量(UTG模式) │  │
│  └──────────┘  └────────┬─────────┘  └────────┬─────────┘  │
└─────────────────────────┼──────────────────────┼────────────┘
                          │                      │
                          ▼                      ▼
              POST /api/utg-run       WS /ws/utg-batch-run
                          │                      │
              ┌───────────▼──────────────────────▼───────────┐
              │              Server (server.py)               │
              │  _run_utg_pipeline()    _run_utg_batch_...() │
              └───────────┬──────────────────────┬───────────┘
                          │                      │
                          ▼                      ▼
              ┌─────────────────────┐ ┌──────────────────────┐
              │ injection_pipeline  │ │ batch_utg_injection  │
              │   .py --utg         │ │   .py                │
              └─────────┬───────────┘ └──────────┬───────────┘
                        │                        │
                        ▼                        ▼
              ┌──────────────────────────────────────────────┐
              │           UTG 决策核心                        │
              │                                              │
              │  ┌──────────────┐  ┌──────────────────────┐  │
              │  │ UTGLoader    │  │ UTGDecisionMaker      │  │
              │  │              │  │                       │  │
              │  │ parse        │  │ decide()              │  │
              │  │ utga_info    │──▶  - 自由模式            │  │
              │  │ .json        │  │  - 约束模式(mapping)   │  │
              │  │              │  │  - 批量打分 prompt     │  │
              │  └──────────────┘  └──────────┬───────────┘  │
              │                               │              │
              │                               ▼              │
              │                    ┌──────────────────────┐  │
              │                    │  文本 LLM API         │  │
              │                    │  (GPT-4o / qwen)      │  │
              │                    │  纯文本，不传图        │  │
              │                    └──────────┬───────────┘  │
              │                               │              │
              │                               ▼              │
              │                    ┌──────────────────────┐  │
              │                    │  决策结果              │  │
              │                    │  {scores[], step,     │  │
              │                    │   reason}             │  │
              │                    └──────────┬───────────┘  │
              └───────────────────────────────┼──────────────┘
                                              │
                                              ▼
                              ┌──────────────────────────────┐
                              │  run_pipeline.py（异常生成）   │
                              │  SequenceRewriter（序列组装）  │
                              └──────────────────────────────┘
```

---

## 3. 核心模块

### 3.1 UTGLoader (`app/injection/utg_loader.py`)

**职责**：解析 `utg_info.json`，提取结构化步骤序列

```python
class UTGLoader:
    def __init__(self, utga_path):
        # 解析 JSON，过滤 home/end 标记
        # 提取 valid_steps: 含 ui_summary 的有效步骤

    @property
    def task_description(self) -> str:
        # 优先读取顶层 query 字段
        # 回退: 从 action_type 推断

    def get_summary_text(self) -> str:
        # 生成 LLM prompt 用的格式化文本
        # 格式: Step N [截图:001]
        #         意图: 【0】...
        #         UI: 页面顶部为搜索框...
```

**数据流**：
```
utga_info.json
  ├─ query          → task_description
  ├─ uuid, appName  → 元数据
  └─ stepData[]     → UTGStep[]
       ├─ stepId
       ├─ thought     → 意图描述
       ├─ ui_summary  → UI 描述
       └─ imageId     → 截图编号
```

### 3.2 UTGDecisionMaker (`app/injection/utg_decision.py`)

**职责**：调用文本 LLM 分析全量 ui_summary，输出注入决策

**两种模式**：

| 模式 | 触发条件 | LLM 职责 | 输出 |
|------|---------|---------|------|
| 自由模式 | 不传 `mapping_config` | 决定 anomaly_mode + instruction + step | `{scores[], best_step, best_reason}` |
| 约束模式 | 传 `mapping_config` 或 `injection_config` | 只决定 step（异常已由 mapping 指定） | `{scores[], best_step, best_reason}` |

**约束模式 Prompt 设计**：

```
## 要评估的异常
- 类型: image_broken
- 描述: 在购买页面注入遮挡层，覆盖鞋码选择区域

## 操作序列（每步含意图 + UI 描述）
Step 0 [截图:001]
  意图: 【0】直接将搜索框内容改为"黑色 37码 运动鞋"
  UI: 页面顶部为搜索框...
Step 1 [截图:002]
  意图: 【301】搜索框内容需改为...
  UI: 顶部导航栏显示'推荐'已选中...
...

## 任务: 对每一步打分（0-10）
## 输出: { scores: [{step, score, reason}], best_step, best_reason }
```

**决策算法**：
```
LLM 批量打分 → 按 score 排序 → 选最高分
                              ↓
                  score < 阈值(5) → 跳过注入
                              ↓
                  score ≥ 阈值 → 选中 step
```

### 3.3 Batch UTG (`scripts/batch_utg_injection.py`)

**职责**：扫描所有 UUID 示例目录，逐条匹配 mapping、决策、生成、组装序列

**流程**：

```
1. scan_examples()     → 扫描 data/examples/ 下所有含 utga_info.json 的目录
2. match_mapping()     → UUID ↔ query_id O(1) 匹配 mapping 条目
3. UTGLoader + decide  → LLM 批量打分，选出 injection_step
4. run_pipeline.py     → 在选中截图生成异常图像
5. 序列组装             → 原图不变，插入 {ref}_anomaly.jpg + {ref}_normal.jpg
6. 元数据落盘           → metadata.json + decision_log.json
```

**输出格式**：
```
outputs/utg_batch/{uuid}/
├── modified_sequence/
│   ├── 001.jpg              # 原图
│   ├── 002.jpg
│   ├── 003.jpg              # 注入点
│   ├── 003_anomaly.jpg      # 异常图
│   ├── 003_normal.jpg       # 恢复图（可关闭类）
│   └── ...
├── anomaly_generated/
├── metadata.json
└── decision_log.json
```

---

## 4. 数据流

### 4.1 单条 UTG 决策 (Web UI → API)

```
Web UI                    Server                    UTG Core
  │                         │                          │
  ├─ example_dir ──────────▶│                          │
  │  (UUID 目录)            ├─ utga_info.json ────────▶│
  │                         │                          ├─ UTGLoader.parse()
  │                         │                          ├─ get_summary_text()
  │                         │                          │
  │                         ├─ mapping_config ────────▶│
  │                         │  (可选)                  ├─ _load_injection_config()
  │                         │                          │
  │                         │                          ├─ decide()
  │                         │                          │  ├─ Prompt 构建
  │                         │                          │  ├─ LLM API 调用（纯文本）
  │                         │                          │  └─ _parse_scoring_response()
  │                         │                          │
  │                         │◀── {injection_step,      │
  │                         │     scores[], reason} ───┤
  │                         │                          │
  │◀── 决策结果 ────────────┤                          │
  │                         │                          │
  │  (dry_run: 结束)        │                          │
  │  (full: 继续生成)       ├─ run_pipeline.py ───────▶│ (子进程)
  │                         │  --utg --screenshot ...  │
  │                         │◀── 异常图片 ──────────────┤
  │                         │                          │
  │◀── 生成结果 ────────────┤                          │
```

### 4.2 批量 UTG (WebSocket 流式)

```
Web UI ──WS──▶ Server ──subprocess──▶ batch_utg_injection.py
               │                            │
               │◀── stdout 逐行推送 ────────┤ (实时终端输出)
               │                            │
               │◀── utg_batch_summary.json ─┤ (汇总结果)
```

---

## 5. 与 VLM 视觉方案的对比

| 维度 | VLM 视觉方案 | UTG 文本方案 |
|------|------------|------------|
| **输入** | 截图序列 (PNG/JPG) | `utg_info.json` (纯文本) |
| **语义来源** | 每帧调 VLM 看图分析 | 已有 ui_summary（云端 Agent 产生） |
| **LLM 调用** | N 次（每帧 1 次） | 1 次（全序列批量打分） |
| **每次调用输入量** | 1 张 base64 图片 + text prompt | 全序列 text prompt (~2K tokens) |
| **成本** | N × 图片 token | 1 × 纯文本 token (~1/10) |
| **决策逻辑** | VLM 分类 → 规则匹配 → 分数 | LLM 直接打分 → 代码选最高 |
| **可解释性** | 匹配规则 ID + score | 每步 0-10 分 + 中文理由 |
| **适用场景** | 无预标注数据的截图 | 已有云端 Agent 执行记录 |

---

## 6. 配置与依赖

### 环境变量

```bash
VLM_API_KEY=sk-xxx           # 文本 LLM API 密钥
VLM_API_URL=https://...       # API 端点
VLM_MODEL=gpt-4o              # 模型名称
```

### 文件依赖

```
data/examples/{uuid}/utg_info.json   # UTG 语义数据（必需）
tmp/mapping.json                      # 异常映射配置（约束模式需要）
data/gt-category/                     # GT 模板（dialog 模式渲染需要）
```

### 关键参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--examples-dir` | 示例目录 | `data/examples` |
| `--mapping-config` | mapping 配置路径 | `tmp/mapping.json` |
| `--output-dir` | 输出目录 | `outputs/utg_batch` |
| `--dry-run` | 仅打分不生成 | `False` |
| `--gt-template-dir` | GT 模板目录 | 自动检测 |

---

## 7. 扩展指南

### 新增异常模式

1. 在 `mapping.json` 的 `injection_config.anomaly_mode` 中添加新模式
2. 确保 `run_pipeline.py` 的 `RENDERER_MAP` 中有对应渲染器
3. 在 `batch_utg_injection.py` 的 `dismissible_modes` 中标记是否为可关闭类

### 调整打分阈值

在 `utg_decision.py` 的 `_parse_scoring_response()` 中修改 `SCORE_THRESHOLD`（当前=5）

### 自定义 Prompt

修改 `CONSTRAINED_SCORING_PROMPT`（约束模式）或 `FREE_DECISION_PROMPT`（自由模式）
