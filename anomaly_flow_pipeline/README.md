# anomaly_flow_pipeline

基于 `utg_info.json` 操作序列 + LLM 决策的**异常注入与 Flow 模板生成**工具链。

将低质量的操作轨迹数据（页面状态快照）转化为高质量、动作驱动、数据一致的异常测试 Flow，用于 AI Agent 仿真 App 生成。

## 架构概览：5 Phase 质量管道

```
原始 utg_info.json (N步, 页面状态快照, 数据不一致)
    │
    ▼
┌──────────────────────────────────────────────────────┐
│ Phase 0: UTG 预处理器                                  │
│  ┣ 去重合并 (Rule-based: 页面指纹去重)                   │
│  ┣ 动作驱动重写 (LLM: 状态快照→用户动作→系统响应)        │
│  ┣ 数据对齐 (LLM: 跨步骤商品名/价格一致性修正)            │
│  ┗ 页面补齐 (LLM: 补充缺失的 ProductDetail 等关键页面)   │
└──────────────────┬───────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────┐
│ Phase 1: 异常注入器 (增强)                              │
│  ┣ 上下文感知改写 — 引入前后步骤作为上下文窗口            │
│  ┣ 相邻步联动微调 — 自动调整前后步骤保持因果链            │
│  ┣ 晦涩表述检测 — 黑名单过滤 + 自然语言约束               │
│  ┗ 多步注入 — 一次支持多个异常场景                        │
└──────────────────┬───────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────┐
│ Phase 2: 智能 Flow 转换                                │
│  ┣ targetPage 映射 (Rule + LLM 兜底)                   │
│  ┣ mockInstances 数据绑定 (从 UTG stepData 抽取，       │
│  │                      确保与 mainFlow.steps 同源)    │
│  ┗ 智能合并 (smart模式: UTG为主体+模板补齐关键页面)       │
└──────────────────┬───────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────┐
│ Phase 3: 质量验证器                                    │
│  ┣ Schema 合规性 — 模板驱动字段验证，不检查模板不存在    │
│  │                    的字段（如 targetPage）           │
│  ┣ 数据一致性 — 价格归一化去重 + 关键词过滤非商品售价    │
│  │                （补贴金额/筛选上限不误报）            │
│  ┣ 步骤连贯性 — 相邻步骤因果链、无断裂                   │
│  ┣ 可读性 — 无晦涩表述、口语化程度                      │
│  ┗ 流程拓扑 — 仅在含 targetPage 时执行页面路径验证      │
└──────────────────┬───────────────────────────────────┘
                   ▼
最终 Flow JSON (符合 Schema, 数据一致, 自然连贯)
```

## 目录结构

```
anomaly_flow_pipeline/
├── core/                              # 核心模块
│   ├── llm_client.py                  # LLM 调用客户端 (.env 配置)
│   ├── utg_loader.py                  # UTG 数据加载器（纯 Python）
│   ├── utg_preprocessor.py            # Phase 0: 预处理器（新增）
│   ├── utg_anomaly_injector.py        # Phase 1: 异常注入器（增强）
│   ├── flow_converter.py              # Phase 2: Flow 转换器（重写）
│   ├── quality_validator.py           # Phase 3: 质量验证器（新增）
│   └── page_spec_extractor.py         # 页面类型 Spec 抽取
├── scripts/                           # CLI 入口
│   ├── run_pipeline.py                # 一键端到端 pipeline（新增）
│   ├── run_inject.py                  # 异常注入（增强）
│   ├── run_convert.py                 # Flow 转换（增强）
│   └── run_extract_spec.py            # Spec 抽取
├── example_data/
│   ├── utg_info.json                  # 原始输入样例
│   ├── shopping-flow-search-and-buy.json        # 旧版模板
│   ├── shopping-flow-search-and-buy_new.json    # 新版模板（含 mockInstances）
│   └── 诊断优化报告.md                 # 质量诊断报告
├── .env.example
├── requirements.txt
├── start.sh                           # 快速启动脚本
└── README.md
```

## 安装

```bash
pip install -r requirements.txt
```

配置 `.env`（复制 `.env.example` 并填入 API Key）：

```
VLM_API_KEY=your-api-key-here
VLM_API_URL=https://api.openai-next.com/v1/chat/completions
VLM_MODEL=gpt-4o
```

## 使用方式

### 1. 一键端到端（推荐）

```bash
python -m anomaly_flow_pipeline.scripts.run_pipeline \
    --utg example_data/utg_info.json \
    --scenario "搜索结果页加载失败，显示网络错误提示" \
    --template example_data/shopping-flow-search-and-buy_new.json \
    --output-dir ./outputs/demo
```

输出目录包含：
- `phase0_preprocessed.json` — 预处理后的 UTG
- `phase1_injected.json` — 注入异常后的 UTG
- `phase2_flow.json` — 最终 Flow JSON
- `pipeline_report.json` — 各阶段质量报告

### 2. 多异常场景

```bash
python -m anomaly_flow_pipeline.scripts.run_pipeline \
    --utg example_data/utg_info.json \
    --scenarios '["搜索结果页加载失败", "购物车价格显示异常"]' \
    --template example_data/shopping-flow-search-and-buy_new.json \
    --output-dir ./outputs/multi_anomaly
```

### 3. 分步执行

#### Phase 0 + 1: 预处理 + 异常注入

```bash
python -m anomaly_flow_pipeline.scripts.run_inject \
    --utg example_data/utg_info.json \
    --scenario "搜索列表加载失败，显示网络错误提示" \
    --template example_data/shopping-flow-search-and-buy_new.json \
    --preprocess \
    --output ./outputs/injected.json
```

#### Phase 2: Flow 转换

```bash
python -m anomaly_flow_pipeline.scripts.run_convert \
    --utg ./outputs/injected.json \
    --template example_data/shopping-flow-search-and-buy_new.json \
    --output ./outputs/flow.json \
    --mode smart
```

### 4. start.sh 快速启动

```bash
bash start.sh \
    --utg example_data/utg_info.json \
    --scenario "搜索结果列表加载失败，显示网络错误提示" \
    --output-dir ./outputs/quick
```

### 5. 质量验证（单独使用）

```bash
python -c "
from anomaly_flow_pipeline.core.quality_validator import validate_flow
result = validate_flow('./outputs/flow.json', template_path='example_data/shopping-flow-search-and-buy_new.json')
print(f'评分: {result[\"score\"]}/1.0')
print(f'通过: {result[\"passed\"]}')
"
```

## 核心特性

### 上下文感知改写

传统方案只改写目标步的 ui_summary，导致异常"凭空出现"。本工具在改写 Prompt 中引入前后步骤作为上下文窗口：

```
改写要求:
1. 保持上下文逻辑连贯 — 从前一步操作自然过渡到异常状态
2. 异常状态能被后一步感知（后一步会看到异常的影响）
3. ... 
```

### 相邻步联动微调

注入后自动微调前后相邻步骤的 ui_summary，使异常产生自然"涟漪效应"：

```
Step i-1: "用户点击搜索按钮，页面开始加载..."        (微调前)
Step i:   "页面加载失败，显示'网络连接失败，轻触重试'"  (注入异常)
Step i+1: "用户点击重试按钮，页面重新请求数据..."      (微调后)
```

### 晦涩表述防御

三层机制避免注入后生成开发/测试视角的晦涩描述：

| 层 | 方式 | 示例 |
|----|------|------|
| Prompt 约束 | 写入正面/反面示例 | ✅"页面提示'网络连接失败'" ❌"系统抛出NetworkErrorException" |
| 规则过滤 | 黑名单检测 + 自动清理 | `exception`, `null`, `HTTP 500`, `数据库查询` → 替换 |
| LLM 验证 | 独立调用检查改写质量 | 发现晦涩表述 → 标记 warnings |

### 数据绑定 — 从 stepData 抽取 mock 实例

Phase 2 的 mock 实例不再从 `query` 字段独立 LLM 生成（避免无中生有），改为**从 stepData 的实际步骤描述中抽取**：

- LLM 输入是拼接后的各步骤 `ui_summary`，而非用户的模糊 query
- 强制要求型号/价格必须来源于步骤中明确提到的信息
- 后备：仅当步骤抽取失败时才用 query 兜底，日志会标记为 `(后备)`

效果：`topics[].mockInstances` 与 `mainFlow.steps` 共享同一数据源，不会出现 mock 实例与步骤内容脱节的问题。

### 验证器 — 模板驱动 + 价格归一化

**Schema 验证**不再硬编码 `OPTIONAL_FIELDS`，改为读取模板 `mainFlow.steps[0].keys()` 动态推导。仅验证模板中存在的步骤字段，避免对 `targetPage` 等模板不存在的字段误报。

**价格一致性检查**（纯规则，不调 LLM）：

| 策略 | 处理方式 | 解决的问题 |
|------|---------|-----------|
| 归一化 | `float()` 解析去重 | `¥1648元` vs `1648元` 视为同一价格 |
| 关键词过滤 | 检查价格前 20 字上下文 | `已补贴109.65元` → 过滤；`价格上限3000元` → 过滤 |
| 多商品宽容 | 搜索结果页不同商品有不同的价格是合法的 | 不要求所有步骤价格一致 |

## Python API

```python
from anomaly_flow_pipeline import UTGPreprocessor, UTGAnomalyInjector, FlowConverter, QualityValidator

# Phase 0: 预处理
preprocessor = UTGPreprocessor()
pre_result = preprocessor.run(utg_path="utg_info.json", template_path="template_new.json")

# Phase 1: 异常注入（上下文感知）
injector = UTGAnomalyInjector()
inject_result = injector.inject(
    utg_path="utg_info.json",
    anomaly_scenario="搜索结果列表加载失败",
    enable_neighbor_adjust=True,
)

# Phase 2: Flow 转换（含 targetPage + 数据绑定）
converter = FlowConverter()
convert_result = converter.convert(
    utg_path="/tmp/modified.json",
    template_path="template_new.json",
    output_path="/tmp/flow.json",
    mode="smart",
)

# Phase 3: 质量验证
validator = QualityValidator()
with open("/tmp/flow.json") as f:
    flow_data = json.load(f)
validation = validator.validate(flow_data, template_path="template_new.json")
print(f"质量评分: {validation['score']}/1.0")
```

## 与主项目关系

本包独立于 `ui_semantic_patch/` 目录，所有依赖仅 `requests` + `python-dotenv`，可复制到任意项目使用。

输出 Flow JSON 的步骤字段与模板 `mainFlow.steps` 声明对齐（默认仅 `order` + `action`），模板不存在的字段会被过滤：

```json
{
  "order": 1,
  "action": "用户在搜索框输入'iPhone 16 Pro'，系统展示搜索结果列表"
}
```

若模板步骤声明了 `targetPage` 或 `boundMockId`，则这些字段也会出现在输出中。

## 质量基准

参考 `example_data/诊断优化报告.md` 的诊断维度，本管道针对以下问题提供系统性解决方案：

| 问题 | 严重度 | 解决方案 | 对应 Phase |
|------|--------|---------|-----------|
| 页面状态快照非动作驱动 | 致命 | 动作驱动重写 | Phase 0-2 |
| 步骤冗余（18步→~8步） | 严重 | 页面指纹去重 | Phase 0-1 |
| 商品名/价格不一致 | 严重 | stepData 抽取 mock 实例 + 数据绑定 | Phase 2 |
| mock 实例与步骤脱节 | 严重 | `_extract_mock_from_steps` 代替 query 生成 | Phase 2 |
| 缺少 ProductDetail 等关键页面 | 中等 | 页面补齐 | Phase 0-4 |
| 含无关页面（消息界面） | 严重 | 去重 + 补齐机制过滤 | Phase 0-1/4 |
| 异常注入后逻辑断裂 | 致命 | 上下文感知改写 + 相邻步联动 | Phase 1 |
| 晦涩表述 | 中等 | 三层防御机制 | Phase 1 |
| 验证器误报（缺 targetPage） | 中等 | 模板驱动字段验证，仅检查模板存在的字段 | Phase 3 |
| 验证器误报（补贴/筛选为价格） | 低 | 价格归一化 + 关键词前缀过滤 | Phase 3 |
