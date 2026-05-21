# UTG 文本决策架构

本文档描述当前仓库中基于 `utg_info.json` 的文本决策链路，以及它和视觉序列分析链路的边界。

## 1. 目标

UTG 模式用于在已经拥有执行轨迹语义描述时，直接通过文本 LLM 选择注入点，避免逐帧图片分析。

输入不是截图本身，而是云端执行过程中已经产生的：

- `query`
- `stepData[].thought`
- `stepData[].ui_summary`
- `stepData[].imageId`

## 2. 核心链路

```text
utg_info.json
  -> UTGLoader
  -> UTGDecisionMaker
  -> 选出 injection_step
  -> run_pipeline.py 生成单张异常图
  -> 批量脚本组装 modified_sequence
```

对应实现：

- `ui_semantic_patch/app/injection/utg_loader.py`
- `ui_semantic_patch/app/injection/utg_decision.py`
- `ui_semantic_patch/scripts/batch_utg_injection.py`

## 3. 输入格式

当前实际读取文件名为 `utg_info.json`。

典型结构：

```json
{
  "query": "到天猫帮买一双黑色的37码运动鞋",
  "uuid": "14a37b63-550e-489d-a55b-50e8cfc6b38a",
  "appName": "天猫",
  "stepData": [
    {
      "stepId": "4",
      "action_type": "set_text(...)",
      "thought": "【0】修改搜索词",
      "ui_summary": "页面顶部为搜索框，下面是推荐列表",
      "imageId": "001"
    }
  ]
}
```

`UTGLoader` 的实际处理规则：

1. 读取顶层 `stepData`。
2. 过滤 `home`、`start`、`end` 这类标记步骤。
3. 过滤没有 `ui_summary` 的步骤。
4. 保留 `thought`、`action_type`、`imageId` 供 prompt 使用。

## 4. `UTGLoader` 产物

`UTGLoader.get_summary_text()` 会把有效步骤整理成供 LLM 直接消费的文本：

```text
Step 0 [截图: 001]
  意图: ...
  UI: ...

Step 1 [截图: 002]
  意图: ...
  UI: ...
```

这一步的意义是把多步操作轨迹压缩成一次可分析的文本上下文。

## 5. `UTGDecisionMaker` 两种模式

### 5.1 自由模式

触发条件：

- 未提供 `mapping_config`
- 未直接传 `injection_config`

LLM 需要同时决定：

- `injection_step`
- `anomaly_mode`
- `instruction`

### 5.2 约束模式

触发条件：

- 传入 `mapping_config`
- 或直接传入 `injection_config`

此时异常模式和指令已经确定，LLM 只需要对每一步打分并选出最自然的注入点。

当前约束模式输出会包含：

- `scores`
- `best_candidate`
- `injection_step`
- `reason`

阈值逻辑：

- 最高分 `< 5` 时，返回 `injection_step = -1`，表示本条任务应跳过注入。

## 6. 批量脚本 `batch_utg_injection.py`

### 6.1 扫描与匹配

脚本会扫描 `data/examples/` 或指定目录下所有包含 `utg_info.json` 的 UUID 目录。

映射匹配优先级：

1. `uuid == query_id`
2. `query` 精确匹配
3. `query` 模糊匹配

### 6.2 生成过程

每个样例的处理流程：

1. 加载 `utg_info.json`
2. 用 `UTGDecisionMaker` 决策注入点
3. 找到对应截图
4. 调 `run_pipeline.py` 生成异常图
5. 将结果写入：
   - `modified_sequence/`
   - `anomaly_generated/`
   - `metadata.json`
   - `decision_log.json`

### 6.3 序列语义

批量脚本内部也遵循与 `SequenceRewriter` 一致的三种语义：

- `dialog` / `area_loading` / `content_duplicate`
  - 输出 `{ref}_anomaly.jpg` + `{ref}_normal.jpg`
- `text_overlay` / `modify_text*` / `image_broken`
  - 只输出 `{ref}_anomaly.jpg`
- `response_delay`
  - 当前由 `SequenceRewriter` 支持；UTG 批量链路的主要模式仍然是前两类

## 7. 和视觉序列分析的关系

| 维度 | UTG 文本决策 | 视觉序列分析 |
|---|---|---|
| 输入 | `utg_info.json` | 截图序列 |
| 决策成本 | 一次文本 LLM | 多次图片 LLM |
| 依赖 | 必须已有 `ui_summary` | 不依赖前置语义 |
| 当前入口 | `batch_utg_injection.py` | `injection_pipeline.py` |
| 适合场景 | 已有执行轨迹 | 只有截图、没有结构化语义 |

结论：

- 如果已经有可靠 `ui_summary`，优先用 UTG 模式。
- 如果只有截图，没有轨迹语义，使用视觉序列分析。

## 8. 当前约束和注意点

1. UTG 只是替代“注入点决策”，不会替代单图渲染器。
2. 约束模式强依赖 mapping 质量；错误的 `instruction` 会直接传递到渲染阶段。
3. `batch_utg_injection.py` 的序列组装逻辑和 `SequenceRewriter` 相近，但不是同一个实现，后续若继续演进，建议统一。
