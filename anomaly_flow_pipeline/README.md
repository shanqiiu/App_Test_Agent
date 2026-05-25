# anomaly_flow_pipeline

独立的异常注入与 Flow 模板转换工具链。

基于 utg.json 的操作序列 + LLM 决策，改写 ui_summary 并合并到 Flow 模板。

## 目录结构

```
anomaly_flow_pipeline/
├── core/                          # 核心模块
│   ├── llm_client.py              # LLM 调用客户端 (.env 配置)
│   ├── utg_loader.py              # UTG 数据加载器（纯 Python）
│   ├── utg_anomaly_injector.py    # 异常注入：决策注入步 + 改写 ui_summary
│   ├── flow_converter.py          # Flow 模板转换器
│   └── page_spec_extractor.py     # 页面类型 Spec 抽取
├── scripts/                       # CLI 入口
│   ├── run_inject.py              # 异常注入
│   ├── run_convert.py             # Flow 转换
│   └── run_extract_spec.py        # Spec 抽取
├── example_data/
│   └── shopping-flow-search-and-buy.json
├── .env.example
├── requirements.txt
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

## 使用

### 1. 异常注入

```bash
python -m anomaly_flow_pipeline.scripts.run_inject \
    --utg path/to/utg.json \
    --scenario "搜索列表加载失败，显示网络错误提示" \
    --output /tmp/modified_utg.json
```

一次调用 LLM 两次：决策注入步 + 改写 ui_summary。

### 2. 转换到 Flow 模板

```bash
python -m anomaly_flow_pipeline.scripts.run_convert \
    --utg /tmp/modified_utg.json \
    --template anomaly_flow_pipeline/example_data/shopping-flow-search-and-buy.json \
    --output /tmp/flow.json
```

纯数据拼接，不调 LLM。

### 3. 链式使用

```bash
# 注入异常
python -m anomaly_flow_pipeline.scripts.run_inject \
    --utg tmp/utg.json \
    --scenario "商品详情页价格显示异常" \
    --output /tmp/modified.json

# 合并到 Flow 模板
python -m anomaly_flow_pipeline.scripts.run_convert \
    --utg /tmp/modified.json \
    --template anomaly_flow_pipeline/example_data/shopping-flow-search-and-buy.json \
    --output /tmp/flow.json
```

### 4. 页面类型 Spec 抽取

```bash
python -m anomaly_flow_pipeline.scripts.run_extract_spec \
    --data-dir path/to/utg_data \
    --output-dir ./output
```

## Python API

```python
from anomaly_flow_pipeline.core.utg_anomaly_injector import UTGAnomalyInjector
from anomaly_flow_pipeline.core.flow_converter import FlowConverter

# 异常注入
injector = UTGAnomalyInjector()
result = injector.inject(utg_path="path/to/utg.json", anomaly_scenario="搜索列表加载失败")

# 转换到 Flow 模板
converter = FlowConverter()
result = converter.convert(
    utg_path="/tmp/modified_utg.json",
    template_path="path/to/template.json",
    output_path="/tmp/flow.json",
)
```

## 不修改现有代码

本包是独立的，与项目原有 `ui_semantic_patch/` 目录完全无关。
所有依赖仅 `requests` + `python-dotenv`，可复制到任意项目使用。
