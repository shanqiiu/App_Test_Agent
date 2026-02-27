# 水平并列卡片拆分 — 双保险策略设计

**日期**: 2026-02-27
**状态**: 待实施
**涉及文件**: `prototypes/ui_semantic_patch/scripts/omni_vlm_fusion.py`

---

## 问题分析

### 现象

Stage 2 整合后，页面中**左右并列的独立卡片**（如"口碑榜"和"旅行热点"）被错误合并为一个宽大的检测框，覆盖了整行。

### 根因

1. **Stage 2a 布局分析**：`LAYOUT_ANALYSIS_PROMPT` 只有 `y_range` 概念，VLM 将同一行的并列卡片归为一个 region
2. **Stage 2c 强制合并**：`_force_merge_by_layout` 纯按 Y 间距聚类，同行并列卡片 Y 坐标相同，无法区分
3. **核心缺陷**：整个分区模型只有 Y 轴逻辑，没有 X 轴（水平）分区能力

---

## 设计方案：双保险（VLM 识别 + 规则兜底）

### 改动 1: Stage 2a Prompt — 支持水平并列识别

在 `LAYOUT_ANALYSIS_PROMPT` 中新增"水平并列"规则：

- 当一行内存在 2+ 张独立卡片/模块并排时，标记 `layout: "horizontal_split"`
- 新增 `sub_regions` 列表描述各子区域（从左到右排列）
- 非并列区域默认 `layout: "vertical"`（可省略），行为不变

输出格式示例：

```json
{
  "name": "推荐卡片区",
  "y_range": [570, 890],
  "granularity": "card",
  "layout": "horizontal_split",
  "sub_regions": [
    {
      "name": "口碑榜",
      "x_position": "left",
      "merge_as_class": "Card",
      "merge_as_text": "口碑榜：高档酒店"
    },
    {
      "name": "旅行热点",
      "x_position": "right",
      "merge_as_class": "Card",
      "merge_as_text": "旅行热点：梵蒂冈游 飙升23%"
    }
  ]
}
```

### 改动 2: Stage 2b Prompt — 约束跨子区域合并

在 `SEMANTIC_FILTER_PROMPT` 新增规则：

> 对于标记了 `layout: "horizontal_split"` 的分区，该分区内的检测框需按 X 坐标分为左右组，分别对应 `sub_regions` 中的子区域。每个 sub_region 单独生成一条 merge 操作，绝不能将左右子区域的 index 合并到同一条 merge 中。

### 改动 3: Stage 2c `_force_merge_by_layout` — 支持水平拆分

当 region 包含 `layout: "horizontal_split"` 且有 `sub_regions` 时：

```python
if region.get('layout') == 'horizontal_split' and region.get('sub_regions'):
    sub_regions = region['sub_regions']
    n_subs = len(sub_regions)

    # 按 X 中心点排序分组
    sorted_by_x = sorted(group, key=lambda c: c['bounds']['x'] + c['bounds']['width'] / 2)

    # 找到最大 X 间隙作为分割点（或使用 img_width/n_subs 等分）
    # 对每个子组按对应 sub_region 的粒度和标签进行合并
    for i, sub_group in enumerate(x_groups):
        sub_region = sub_regions[min(i, len(sub_regions)-1)]
        # 合并 sub_group 为一个组件，使用 sub_region 的 merge_as_class/text
```

### 改动 4: Stage 2d — 后处理自动拆分（兜底）

新增 `post_split_wide_components()` 函数，在 Stage 2c 之后调用。

**触发条件**（全部满足才拆分）：
- 组件宽度 > 80% 屏幕宽度
- `source_indices` 的 X 中心分布存在 > 10% 屏幕宽度的间隙
- 组件**不是** atomic 粒度（排除全宽 Banner）

**拆分逻辑**：
1. 收集所有 source_indices 的 X 中心坐标
2. 计算相邻 X 中心之间的最大间隙
3. 以间隙中点为分割线，将 sources 分为左右两组
4. 各自计算最小外接矩形，生成两个独立组件
5. 文本回退使用各组 source 的原始 OCR 文本拼接

**防冲突**：如果 Stage 2a+2c 已正确拆分（组件宽度 < 80%），Stage 2d 自动跳过。

---

## 数据流变化

```
Stage 1: OmniParser (不变)
    ↓
Stage 2a: VLM 布局分析 (新增 horizontal_split + sub_regions)
    ↓
Stage 2b: VLM 语义整合 (新增跨子区域合并约束)
    ↓
Stage 2c: 强制合并 (支持 horizontal_split 的 X 轴拆分)
    ↓
Stage 2d: 后处理自动拆分 [NEW] (兜底，宽组件 X 双峰检测)
    ↓
最终 UI-JSON
```

---

## 改动范围评估

| 改动点 | 预估行数 | 风险 |
|--------|----------|------|
| LAYOUT_ANALYSIS_PROMPT 扩展 | ~30 行 | 低 — 纯 prompt 扩展 |
| SEMANTIC_FILTER_PROMPT 约束 | ~10 行 | 低 — 纯 prompt 扩展 |
| _force_merge_by_layout X 轴 | ~40 行 | 中 — 需测试边界情况 |
| post_split_wide_components | ~60 行 | 低 — 独立函数，不影响现有逻辑 |
| omni_vlm_fusion() 集成调用 | ~10 行 | 低 |
| **总计** | **~150 行** | |

---

## 测试要点

1. **水平并列卡片**：口碑榜+旅行热点、特价专区+直播团购 → 应拆为独立 Card
2. **全宽 Banner**：横贯整个屏幕的广告 Banner → 不应被误拆
3. **非并列区域回归**：导航栏、底部 Tab → 不受影响
4. **VLM 漏标 horizontal_split 时**：Stage 2d 兜底应自动拆分
