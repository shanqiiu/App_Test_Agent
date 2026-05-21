# Mapping 生成与目标定位

本文档覆盖两类当前仍在使用的机制：

1. `data/data_process/generate_mapping.py` 的 mapping 自动生成逻辑
2. `text_overlay.py` / `image_broken.py` 一类模式中的指令关键词定位逻辑

## 1. mapping 在项目中的位置

当前仓库里有三类 mapping 文件：

1. `tmp/mapping.json`
   - 供 UTG 批量注入直接消费。
2. `ui_semantic_patch/config/query_anomaly_mapping.json`
   - 供旧批量流程和 Web UI 默认配置消费。
3. `ui_semantic_patch/config/mapping_*.json`
   - 按异常模式拆分的维护产物。

因此，`generate_mapping.py` 更像“生成和维护工具”，不是唯一运行入口。

## 2. `generate_mapping.py` 的实际流水线

文件：

- `data/data_process/generate_mapping.py`

当前脚本逻辑是三级决策：

```text
fault_mode
  -> anomaly_mode 分类
  -> instruction 展开
  -> GT 模板匹配
  -> 组装 mapping 条目
```

### 2.1 `fault_mode -> anomaly_mode`

采用关键词规则，不是 LLM 自由生成。

典型映射：

| 关键词 | 输出模式 |
|---|---|
| `置灰` | `modify_text_ai` |
| `无票` / `售罄` / `价格` | `modify_text` |
| `遮挡` / `浮层` | `text_overlay` |
| `弹窗` / `广告` / `权限` | `dialog` |
| `重复` / `歧义` | `content_duplicate` |
| `加载` / `超时` | `area_loading` |
| `卡顿` / `延迟` / `未响应` | `response_delay` |

没有命中的情况下，脚本会回退到 `modify_text_ai`。

### 2.2 instruction 展开

脚本会先从 query 中提取一些显式约束，例如：

- 时间段
- 路线
- 航司
- 舱位
- 内容名称

然后再用两种路径之一生成指令：

1. 有文本模型配置时，用 LLM 扩写 instruction
2. 无文本模型配置时，走模板兜底

这意味着脚本不是“纯规则”，而是“规则定模式 + LLM/模板定文案”。

### 2.3 GT 模板匹配

只对以下模式尝试 GT：

- `dialog`
- `area_loading`
- `content_duplicate`

匹配顺序：

1. 文件名包含 `app_name`
2. 同目录下第一个可用样本

返回字段：

- `gt_category`
- `gt_sample`
- `reference_path`

## 3. 生成结果结构

标准条目结构：

```json
{
  "query": "...",
  "query_id": "...",
  "app_name": "...",
  "example_dir": "...",
  "fault_mode": "...",
  "fault_mode_key": "mode_1",
  "injection_config": {
    "anomaly_mode": "modify_text",
    "instruction": "...",
    "gt_category": "dialog",
    "gt_sample": "...",
    "reference_path": "..."
  }
}
```

## 4. 目标定位不是全靠 LLM

对于 `text_overlay`、`modify_text`、`modify_text_ocr`、`image_broken` 一类模式，项目里仍大量使用确定性定位。

关键实现：

- `ui_semantic_patch/app/renderers/text_overlay.py`

主流程：

```text
用户指令
  -> 提取关键词
  -> 在 OCR/组件文本中匹配
  -> 找到目标区域
  -> 再决定如何编辑
```

## 5. 关键词提取逻辑

当前实现的基本思路：

1. 去掉一批噪音词，如“将”“改为”“模拟”等。
2. 提取连续中文词和英文数字串。
3. 去重、过滤过短 token。
4. 用关键词和 OCR 文本做简单打分匹配。

这套机制的优点：

- 快
- 稳定
- 不依赖额外模型调用

局限也很明确：

- 不理解组件类型
- 容易把“同名文本”定位到错误位置
- 缺少更强的上下文判断

所以当前项目的真实策略是：

- 目标定位优先用确定性方法
- 复杂语义编辑再交给 VLM 或图像编辑模型

## 6. 当前实践建议

1. 运行 UTG 批量注入时，优先维护 `tmp/mapping.json`。
2. 维护 Web UI 或旧批量流程时，仍要同步 `ui_semantic_patch/config/query_anomaly_mapping.json`。
3. `generate_mapping.py` 适合生成初稿，不适合直接替代人工审核。
4. 对“按钮遮挡”“价格修改”“名称篡改”这类强定位场景，应优先使用 `text_overlay` 或 `modify_text*`，而不是强行走 `dialog`。
