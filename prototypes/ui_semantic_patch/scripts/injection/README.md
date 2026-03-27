# Injection 模块技术说明

`prototypes/ui_semantic_patch/scripts/injection` 封装异常注入决策流水线的核心组件：增量式语义分析、异常类型推荐、序列改写以及离线 mock 能力。该目录内的模块既可以直接被 `injection_pipeline.py` 调用，也可以按需嵌入到其他自动化测试框架。

## 目录与职责

| 文件 | 作用 |
| --- | --- |
| `__init__.py` | 暴露标准接口：`SequenceAnalyzer`、`AnomalyRecommender`、`SequenceRewriter` 及 mock 相关类。 |
| `sequence_analyzer.py` | 基于视觉大模型（VLM）的增量式截图理解器，负责逐步决策是否注入异常。 |
| `anomaly_recommender.py` | 读取 GT 模板库，整理可注入的异常类型及描述，供 VLM 提示词使用。 |
| `sequence_rewriter.py` | 连接已有的 `run_pipeline.py` 异常生成脚本，把异常截图写回操作序列并生成元数据。 |
| `mock_provider.py` | 定义 `MockConfig`、`MockSequenceAnalyzer`、`MockSequenceRewriter`，用于离线或内网无法调用生成模型时的兜底策略。 |
| `prompts.py` | 管理注入决策、步骤摘要、异常指令扩写、用户指令扩写等提示词模板。 |
| `mock_config_example.json` | mock 模式参考配置，只包含 `anomaly_images_dir` 占位字段。 |

> 依赖模块：`utils.history_manager.HistoryManager` 与 `StepRecord` 负责维护上下文窗口；`utils.common.encode_image/get_mime_type` 负责图像编码；`utils.meta_loader.MetaLoader` 提供 GT 模板元数据。

## 整体流程

```
原始截图序列
    │
    ▼
SequenceAnalyzer (VLM)
  - 累积历史 <think> 片段
  - 构建 INJECTION_DECISION_PROMPT
  - 返回 {decision, anomaly_type, instruction}
    │
    ├─若 decision=SKIP → 继续下一帧
    └─若 decision=INJECT → 进入序列改写
           │
           ├─SequenceRewriter → 调 run_pipeline.py 生成异常图
           └─MockSequenceRewriter → 复制预置/GT 图片
    ▼
输出：改写序列、异常截图、metadata、decision_log
```

## 组件要点

### SequenceAnalyzer
- 初始化参数：`task_description`、`max_history_steps`、`min_steps_before_inject`、`temperature`，以及 VLM 连接信息（`VLM_API_KEY`、`VLM_API_URL`、`VLM_MODEL`，可通过 `.env` 覆盖）。
- `HistoryManager` 以窗口方式存储最近 N 步分析结果，并把 `<think><decision><conclusion>` 片段拼接进提示词，让 VLM 拥有上下文记忆。
- `build_injection_prompt()` 注入任务描述、可用异常类型（来自 `AnomalyRecommender`）以及历史摘要；强制要求输出结构化标签。
- `_call_vlm()` 负责把当前截图编码为 `data:{mime};base64,...`，并通过 `requests` POST 到指定 VLM，包含指数退避的 429/5xx 重试逻辑。
- `_parse_vlm_response()` 解析 `<think>`/`<decision>` 等标签；若 decision 异常则兜底为 `SKIP`。结果在 `min_steps_before_inject` 之前会被强制改写为 `SKIP`，防止缺少上下文。
- `run()` 逐帧遍历，一旦遇到 `INJECT` 就返回注入点、异常类型、生成指令及完整历史，可直接写入 `decision_log.json`。

### AnomalyRecommender
- 默认搜索 `data/Agent执行遇到的典型异常UI类型/analysis/gt_templates`，委托 `MetaLoader` 列出所有类别和样本。
- 若 `meta.json` 内未提供文案，则 fallback 到 `DEFAULT_CATEGORY_DESCRIPTIONS`（覆盖弹窗、内容重复、loading_timeout 等常见类型）。
- `get_categories_description()` 使用 `prompts.format_anomaly_category()` 生成带编号的多行文本，直接嵌入 VLM 提示词；`get_default_sample()` / `get_sample_path()` 供改写阶段确定 GT 参考。

### SequenceRewriter
- 负责把决策结构落地成新的截图序列。`rewrite()` 的关键步骤：
  1. 复制原序列中注入点及之前的截图到 `modified_sequence/step_{idx}.png`。
  2. 通过 `_call_generator()` 启动 `python run_pipeline.py --screenshot ... --instruction ... --anomaly-mode ... --gt-category ... --gt-sample ...`。`_get_anomaly_mode()` 会把中文类别映射为生成脚本需要的模式（如弹窗→`dialog`，loading_timeout→`area_loading`）。
  3. 把生成出来的异常截图（或 fallback 占位图）插入到序列之后，并放入 `anomaly_generated/`。
  4. 写入 `metadata.json`（包含注入点、截断步数、原/改写长度、异常截图路径等）以及可选的 `decision_log.json`。
- `_find_generated_images()` 过滤 `annotated/debug/mask` 等中间文件，只保留真正的异常输出。

### MockProvider
- `MockConfig` 读取 JSON（或使用默认配置），为每个 `step` 预置 `decision/anomaly_type/instruction`，还可配置 `fallback_inject_step` 以及 `anomaly_images_dir`。
- `MockSequenceAnalyzer` 在 `run()` 中完全跳过 VLM，按配置返回结果，但同样遵守 `min_steps_before_inject`。
- `MockSequenceRewriter` 不运行生成模型，而是按优先级获取异常图片：① `anomaly_images_dir` 中的自定义素材；② GT 模板库；③ 当前截图占位。输出结构与真实改写保持一致，并在元数据中标记 `mock_mode=True`。
- `mock_config_example.json` 提供最小示例，实际落地时可加入 `decisions` 数组及 fallback 字段。

### Prompts
- `INJECTION_DECISION_PROMPT`：强制 VLM 输出 `<think>/<decision>/<anomaly_type>/<instruction>/<conclusion>` 标签，强调“前两步不注入”“语义合理”等约束。
- `STEP_SUMMARY_PROMPT`：用于复用历史摘要，如果需要额外压缩步骤描述可用该模板调用语言模型。
- `INSTRUCTION_GENERATION_PROMPT`、`USER_INSTRUCTION_GENERATION_PROMPT`：支持扩写异常生成指令和用户意图数据，方便构建更大的训练语料。

## 运行方式与配置

1. **准备输入**：`input_dir` 需包含 `task.json`（如 `{"description": "在携程预订酒店"}`）与 `screenshots/step_xx.png` 序列。若没有 `task.json`，可通过 `--task` 直接传入描述。
2. **环境变量**：在仓库根目录配置 `.env`（参见 `injection_pipeline.py` 自动加载逻辑），至少需要 `VLM_API_KEY`，可选 `VLM_API_URL`、`VLM_MODEL`。
3. **GT 模板**：保持默认路径或通过 `--gt-template-dir` 指向自定义的 `analysis/gt_templates`。
4. **执行命令**（真实生成）：
   ```bash
   python prototypes/ui_semantic_patch/scripts/injection_pipeline.py \
     --input-dir examples/injection_demo \
     --output-dir output/injected \
     --max-history 10 \
     --min-steps 2
   ```
5. **Mock 模式**：无生成模型权限时可运行
   ```bash
   python injection_pipeline.py \
     --input-dir ./screenshots \
     --output-dir ./mock_output \
     --mock \
     --mock-config prototypes/ui_semantic_patch/scripts/injection/mock_config_example.json
   ```
   该模式仍使用真实 `SequenceAnalyzer`（除非显式替换为 `MockSequenceAnalyzer`），但序列改写阶段会直接复制预置异常图片。
6. **交互确认**：默认 `--interactive`。若批量运行，可添加 `--no-interactive` 跳过人工确认步骤。

## 输出

`SequenceRewriter`/`MockSequenceRewriter` 会在 `output_dir/injection_YYYYMMDD_HHMMSS/` 下生成：
- `modified_sequence/`：包含注入点之前的原始截图 + 生成的异常截图。
- `anomaly_generated/`：保留生成器原始输出或 mock 素材。
- `metadata.json`：记录注入点、异常类型、gt_sample、instruction、原/改写长度、截断数量等。
- `decision_log.json`（若传入）：完整的推理历史与 `SequenceAnalyzer.run()` 返回结构；若未找到注入点，则写入 `decision_log_no_injection.json`。

## 扩展建议

- **新的异常类型**：在 GT 模板目录中新增子目录与 `meta.json`，`AnomalyRecommender` 会自动读取；必要时在 `SequenceRewriter._get_anomaly_mode()` 映射新类型。
- **替换 VLM**：只需在 `.env` 中更新 `VLM_API_URL` 和 `VLM_MODEL`，或在实例化 `SequenceAnalyzer` 时传入参数；`encode_image()` 支持常见图片格式。
- **定制 Prompt**：可以在 `prompts.py` 中添加新的模板函数，然后在 `SequenceAnalyzer` 或其他上游组件中引用，保持标签式输出便于解析。
- **离线回归**：结合 `MockSequenceAnalyzer` + `MockSequenceRewriter` 可以模拟整条流水线，验证 UI 序列改写逻辑而无需任何外部模型依赖。

以上内容即可作为 `injection` 目录的 README，帮助快速理解并配置异常注入模块。

---

**最后更新**: 2026-03-26
**文档同步**: 环境与流水线总览以仓库根目录 [Claude.md](../../../../Claude.md) 为准。
