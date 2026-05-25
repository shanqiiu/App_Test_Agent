# UTG Anomaly Injector — ui_summary 改写模块

本文档描述 `UTGAnomalyInjector` 模块的设计、接口和使用方式。它是独立的异常注入决策 + ui_summary 改写模块，与已有的 `UTGDecisionMaker`（只决策注入点）互补。

## 1. 目标

给定一个异常场景的文本描述 + `utg_info.json`，自动完成两件事：

1. **决策**：在操作序列中选出与该异常最自然契合的注入步。
2. **改写**：将该步的 `ui_summary` 改写为异常状态描述。

最终输出一个完整的修改后 `utg_info.json`，可直接用于下游的异常 App 截图生成。

### 和 UTGDecisionMaker 的边界

| 维度 | UTGDecisionMaker | UTGAnomalyInjector |
|------|------------------|---------------------|
| 核心产出 | 注入点 + 异常类型 + instruction | 修改后的 `utg_info.json`（含改写后 ui_summary） |
| 是否修改 utg.json | 否 | 是 |
| 输入异常来源 | mapping.json 或自由决策 | 直接传入异常场景文本 |
| 使用场景 | 批量匹配 mapping 生成异常图 | 给定具体异常场景，输出适配后的语义轨迹 |

## 2. 核心流程

```text
utg_info.json + 异常场景文本描述
        │
        ▼
┌─────────────────────────────────┐
│  UTGAnomalyInjector.inject()    │
│                                 │
│  1. UTGLoader 加载 utg_info     │
│                                 │
│  2. LLM DECISION_PROMPT         │
│     → 从序列中选择注入步         │
│                                 │
│  3. LLM REWRITE_PROMPT          │
│     → 改写该步的 ui_summary     │
│                                 │
│  4. 深拷贝原数据，替换 ui_summary│
│     → 组装 modified_utg         │
└─────────────────────────────────┘
        │
        ▼
modified_utg_info.json
```

## 3. 接口

### 3.1 UTGAnomalyInjector

```python
class UTGAnomalyInjector:
    def __init__(
        self,
        api_key: str = None,        # 默认从 VLM_API_KEY 环境变量读取
        api_url: str = None,        # 默认从 VLM_API_URL 环境变量读取
        model: str = None,          # 默认从 VLM_MODEL 环境变量读取
        temperature: float = 0.1,
        max_tokens: int = 1024,
        llm_timeout: int = 180,
    )

    def inject(
        self,
        utg_path: str,              # utg_info.json 文件路径
        anomaly_scenario: str,      # 异常场景文本描述
        output_path: str = None,    # 可选，输出文件路径
    ) -> Dict[str, Any]:
        """返回包含 modified_utg 的完整结果"""

    @staticmethod
    def save(modified_utg: Dict, output_path: str) -> str:
        """将修改后的 utg 写入文件"""
```

### 3.2 inject() 返回值结构

```python
{
    "success": bool,               # 是否成功
    "modified_utg": Dict,          # 完整的修改后 utg_info.json
    "injection_step": int,         # 选中的注入步索引（从 0 开始）
    "step_id": str,                # 选中的 stepId（如 "4", "5"）
    "original_ui_summary": str,    # 原始 ui_summary
    "rewritten_ui_summary": str,   # LLM 改写后的 ui_summary
    "decision_reason": str,        # LLM 选择该步的理由
    "anomaly_scenario": str,       # 输入的异常场景
    "error": str or None,          # 错误信息
}
```

### 3.3 便捷函数

```python
def run_anomaly_inject(
    utg_path: str,
    anomaly_scenario: str,
    output_path: str = None,
    api_key: str = None,
    api_url: str = None,
    model: str = None,
) -> Dict[str, Any]:
    """一键执行，等效于 UTGAnomalyInjector().inject()"""
```

## 4. Prompt 设计

### DECISION_PROMPT

将异常场景描述 + 整个操作序列的 `ui_summary`/`thought` 打包给 LLM，让 LLM 选出最自然的注入步。

决策原则：

- 选择与异常场景最契合的页面类型（搜索结果页 → 列表加载异常，详情页 → 价格异常）
- 优先选在关键操作之后、关键页面之前
- 避免首页、加载中、纯输入步骤
- 避免末尾步骤

输出格式：

```json
{
  "injection_step": 2,
  "reason": "该步为搜索结果页，与'搜索列表加载失败'场景高度匹配"
}
```

### REWRITE_PROMPT

将异常场景 + 该步的原始 `ui_summary`、`thought`、`action_type` 发给 LLM，要求：

1. 保持原有核心页面结构
2. 自然融入异常状态表现
3. 与原始描述风格一致（客观、简洁、聚焦 UI 状态）
4. 不修改 thought / action_type
5. 具体描述异常表现，而非抽象说"出现异常"

输出仅为纯文本（改写后的 `ui_summary`），不包含 JSON 包装。

## 5. 独立性设计

模块通过以下方式保持独立，不依赖 `app.injection` 包中的其他模块：

### 5.1 绕过 package __init__ 导入

`app/injection/__init__.py` 会级联导入 `SequenceAnalyzer` 等依赖可选外部库（如 `dashscope`）的模块。`UTGAnomalyInjector` 通过 `importlib.util.spec_from_file_location()` 直接从文件路径加载 `UTGLoader`，**不触发** `__init__.py` 的执行链。

```python
# 模块内部 — 独立加载 sibling 模块
def _load_sibling_module(module_name, filename):
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "app.injection"
    spec.loader.exec_module(mod)
    return mod
```

### 5.2 自有 LLM 客户端

`LLMClient` 是独立实现，复用同一组环境变量（`VLM_API_KEY` / `VLM_API_URL` / `VLM_MODEL`），但不依赖 `UTGDecisionMaker`。

### 5.3 零额外依赖

模块仅依赖：`requests` + Python 标准库。不新增 `requirements.txt` 条目。

## 6. CLI 入口

### 6.1 用法

```bash
# 输出到终端
python scripts/run_utg_anomaly_injector.py \
  --utg path/to/utg_info.json \
  --scenario "搜索列表加载失败，显示网络错误提示"

# 指定输出文件
python scripts/run_utg_anomaly_injector.py \
  --utg path/to/utg_info.json \
  --scenario "商品详情页价格显示异常" \
  --output outputs/anomaly_injected/utg_info.json

# 指定模型
python scripts/run_utg_anomaly_injector.py \
  --utg path/to/utg_info.json \
  --scenario "按钮不可点击" \
  --model gpt-4o \
  --verbose
```

### 6.2 参数

| 参数 | 说明 |
|------|------|
| `--utg` | `utg_info.json` 路径（必需） |
| `--scenario` | 异常场景文本描述（必需） |
| `--output, -o` | 输出文件路径 |
| `--verbose, -v` | 详细日志 |
| `--api-key` | 自定义 API Key |
| `--api-url` | 自定义 API URL |
| `--model` | 自定义模型名 |
| `--dry-run` | 仅决策注入步，不改写（调试用） |

### 6.3 脚本导入方式

CLI 脚本同样绕过 `app.injection.__init__`，直接通过文件路径加载模块：

```python
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "utg_anomaly_injector",
    str(Path(__file__).parent.parent / "app" / "injection" / "utg_anomaly_injector.py")
)
_mod = importlib.util.module_from_spec(_spec)
_mod.__package__ = "app.injection"
_spec.loader.exec_module(_mod)
UTGAnomalyInjector = _mod.UTGAnomalyInjector
```

## 7. 示例

### 7.1 Python API 方式

```python
from pathlib import Path
import importlib.util

# 独立加载（推荐）
injector_path = Path("ui_semantic_patch/app/injection/utg_anomaly_injector.py")
spec = importlib.util.spec_from_file_location("injector", str(injector_path))
mod = importlib.util.module_from_spec(spec)
mod.__package__ = "app.injection"
spec.loader.exec_module(mod)

injector = mod.UTGAnomalyInjector()
result = injector.inject(
    utg_path="tmp/utg.json",
    anomaly_scenario="搜索结果列表中，商品图片全部显示为裂图",
    output_path="outputs/anomaly_injected/utg_info.json",
)

if result["success"]:
    print(f"注入步: Step {result['injection_step']}")
    print(f"改写前: {result['original_ui_summary'][:80]}...")
    print(f"改写后: {result['rewritten_ui_summary'][:80]}...")
```

### 7.2 输入输出示例

**输入异常场景**：
```
搜索结果列表中，商品图片全部显示为裂图
```

**改写效果**（以样例 `tmp/utg.json` 的 Step 1 / stepId=4 为例）：

| 字段 | 内容 |
|------|------|
| 原始 ui_summary | "当前页面为京东自营加湿器的搜索结果页，顶部搜索框显示关键词"加湿器 京东自营"，下方可选择排序选项..." |
| 改写后 ui_summary | "当前页面为京东自营加湿器的搜索结果页，顶部搜索框显示关键词"加湿器 京东自营"，下方可选择排序选项，商品列表中每个商品的**图片区域显示为灰色裂图占位，无法正常加载商品图片**，其余文案信息和排序功能正常。" |

## 8. 实现文件

| 文件 | 说明 |
|------|------|
| `ui_semantic_patch/app/injection/utg_anomaly_injector.py` | 核心模块：LLMClient, UTGAnomalyInjector, run_anomaly_inject |
| `ui_semantic_patch/scripts/run_utg_anomaly_injector.py` | CLI 入口脚本 |
| `ui_semantic_patch/app/injection/__init__.py` | 包导出（try/except 安全导入） |
