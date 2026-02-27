# Stage 2 重构：单次 VLM 语义分组

**日期**: 2026-02-27
**状态**: 已批准
**目标文件**: `prototypes/ui_semantic_patch/scripts/omni_vlm_fusion.py`

---

## 背景

当前 Stage 2 是三步流程：
- **Stage 2a**: VLM 独立布局分析（仅看原图），输出 atomic/card/fine 分区
- **Stage 2b**: VLM 语义整合（原图 + 标注图 + 组件JSON），输出 merge/keep/delete/add 操作指令
- **Stage 2c**: 代码兜底强制合并（当 2b 效果不足时触发）

问题：
1. 两次串行 VLM 调用，总延迟 50-150 秒
2. Stage 2b 传两张图（原图 + 标注图），token 开销大
3. VLM 同时负责语义理解 + 几何操作，出错率高（大量修复代码：坐标修复、文本偏移检测、索引越界处理）
4. 约 850 行代码用于处理 VLM 不擅长的几何计算和错误恢复

## 设计

### 核心思路

将 VLM 职责收窄为**纯语义分组**，几何计算交给代码。

```
旧流程: Stage 1 → 2a(VLM布局) → 2b(VLM操作指令) → 2c(代码兜底)
新流程: Stage 1 → Stage 2(VLM语义分组) → 代码计算合并 → 绘制新检测框
```

### VLM 调用设计

**输入**：1 张原图 + 文本格式检测框列表

```
#0 [x=120, y=45, w=200, h=70] text="返回"
#1 [x=250, y=48, w=400, h=68] text="订单详情"
#2 [x=50, y=300, w=350, h=200] text=""
#3 [x=50, y=510, w=300, h=40] text="¥138"
#4 [x=50, y=555, w=300, h=25] text="贵宾休息室"
```

**Prompt 核心指令**：看原图 + 检测框列表，判断哪些框共同构成一个功能组件，输出分组。

**VLM 输出格式**：

```json
{
  "groups": [
    {
      "name": "状态栏",
      "indices": [0, 1, 2],
      "class": "StatusBar",
      "text": "系统状态栏"
    },
    {
      "name": "返回按钮",
      "indices": [3],
      "class": "Button",
      "text": "返回"
    },
    {
      "name": "贵宾休息室卡片",
      "indices": [5, 6, 7, 8],
      "class": "Card",
      "text": "贵宾休息室 ¥138/份"
    }
  ]
}
```

规则：
- 每个原始检测框 index 必须出现在且仅出现在一个 group 中
- 单个组件也要作为独立 group（indices 长度为 1）
- class 从预定义列表选择：StatusBar, NavigationBar, TextView, Button, ImageView, ImageButton, Card, TabBar, TabItem, SearchBar, Dialog, Avatar, ListItem, InputField 等

### 代码合并层

VLM 返回分组后，代码负责：

1. **校验覆盖率** — 检查所有 OmniParser index 是否被覆盖，未覆盖的自动补为独立 group
2. **计算合并坐标** — 对每个 group，取所有 indices 对应框的最小外接矩形（bounding box 并集）
3. **拼接文本** — VLM 给了 text 就用 VLM 的，否则按空间顺序（y→x）拼接原始框的 text
4. **排序编号** — 按 y → x 排序，重新分配 index
5. **绘制新检测框** — 用合并后的 bounds 在原图上绘制标注框和新编号

### 可删除的代码

| 函数/逻辑 | 行数（约） | 删除原因 |
|-----------|-----------|----------|
| `LAYOUT_ANALYSIS_PROMPT` | ~70 | Stage 2a 不再需要 |
| `SEMANTIC_FILTER_PROMPT` | ~80 | Stage 2b 操作指令格式不再需要 |
| `call_vlm_for_layout_analysis()` | ~60 | Stage 2a 函数 |
| `call_vlm_for_semantic_filter()` | ~100 | 旧 Stage 2b 函数 |
| `apply_vlm_operations()` | ~180 | merge/keep/delete/add 操作处理 |
| `_force_merge_by_layout()` | ~160 | Stage 2c 兜底 |
| `fix_component_bounds()` | ~90 | VLM 坐标修复 |
| `validate_and_fix_text_assignments()` | ~110 | 文本偏移修复 |
| **合计** | **~850** | — |

### 新增的代码

| 函数 | 职责 | 预估行数 |
|------|------|---------|
| `GROUPING_PROMPT` | 新 prompt 模板 | ~40 |
| `call_vlm_for_grouping()` | 单次 VLM 调用（原图 + 坐标文本） | ~50 |
| `apply_grouping()` | 校验覆盖率 + 合并坐标 + 拼接文本 | ~60 |
| `draw_merged_boxes()` | 在原图上绘制合并后检测框 | ~40（或复用已有绘制逻辑） |
| **合计** | — | **~190** |

净减少约 660 行代码。

### 对外接口变化

`omni_vlm_fusion()` 函数签名：

```python
# 删除参数
- annotated_image_path: str = None  # 不再需要标注图

# 保留参数不变
image_path, api_key, api_url, vlm_model, omni_device,
box_threshold, iou_threshold, omni_components, output_dir
```

调用方 `run_pipeline.py` 同步修改：去掉传入 `annotated_image_path` 的逻辑。

### 错误处理

- VLM 调用失败 → 回退到 OmniParser 原始结果
- JSON 解析失败 → 重试（复用 `_call_vlm_with_retry`，重试次数从 5 降到 3）
- 分组中出现无效 index → 忽略该 index，记录 warning
- 未被任何分组覆盖的 index → 自动补为独立 group

### 收益

1. **延迟减半**：1 次 VLM 调用（~30s）替代 2 次串行调用（50-150s）
2. **token 减少**：去掉标注图（base64 图片是 token 大户），prompt 大幅缩短
3. **出错率降低**：VLM 只做语义分组，不做几何操作，输出格式简单
4. **代码量减少 ~660 行**：删除大量修复/兜底逻辑
5. **合并结果确定性**：坐标计算由代码完成，精确无误
