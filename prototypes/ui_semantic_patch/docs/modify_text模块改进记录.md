# modify_text 模块改进记录

> **日期**: 2026-03-20
> **涉及文件**:
> - `scripts/renderers/text_overlay.py`
> - `scripts/run_pipeline.py`
> - `scripts/apply_edit_plan.py`

---

## 七、2026-03-23 增量更新：`modify_text_e2e` 端到端编辑模式

### 7.1 新增背景

在部分细粒度文本场景中，OmniParser 检测框和 Stage 2 分组难以稳定覆盖目标文字，导致局部编辑路径（`modify_text_ai` / `modify_text_ocr`）定位误差累积。为此新增端到端路径，允许直接基于原图+指令进行编辑。

### 7.2 新增能力

- 新增 `--anomaly-mode modify_text_e2e`
  - 跳过 Stage 1 检测与 Stage 2 分组
  - Stage 3 直接调用 `qwen-image-edit-max`
- 新增 `--e2e-full-image` 开关
  - 默认关闭：指令驱动粗裁剪后编辑并贴回原图
  - 开启后：整图端到端编辑（不做裁剪）

### 7.3 提示词策略

- 正向提示词：直接使用用户原始指令（`instruction.strip()`）
- 负向提示词：沿用 `generate_image_dashscope()` 默认 `negative_prompt`

### 7.4 适用建议

| 场景 | 推荐模式 |
|------|----------|
| OCR 可识别、追求局部可控 | `modify_text_ocr`（或 `modify_text`） |
| OCR 难识别、组件定位可用 | `modify_text_ai` |
| 细粒度目标且检测分组不稳定 | `modify_text_e2e --e2e-full-image` |

---

## 一、背景与问题

### 原始方案

`modify_text` 模式最初使用 **VLM 像素级坐标估算 + PIL 擦除重绘** 的方式替换 UI 文字：

```
用户指令 → VLM 估算文字像素坐标 → PIL 填充背景色 → PIL 绘制新文字
```

**问题**：VLM 估算的坐标精度有限，PIL 简单擦除重绘的视觉保真度差。

### AI 图像编辑方案（中间版本）

引入 `qwen-image-edit-max` 图像编辑模型，利用 Stage 2 UI-JSON 组件 bounds 定位卡片区域：

```
用户指令 → VLM 选择 UI-JSON 组件 index → 裁切卡片区域 → AI 图像编辑 → 贴回原位
```

**问题**：
- **检测框过大**：卡片级 bounds（如 1136×1346）导致 AI 模型重建大面积无关像素，造成画质失真
- **AI 模型乱改**：VLM 误规划的组件（目标文字不存在于该组件）交给 AI 后，模型强行在错误位置生成文字
- **执行顺序冲突**：OCR+PIL 精确修改 → AI 整卡重绘，后者覆盖前者结果

### 最终方案：拆分为两种独立模式

将 AI 和 OCR 两种方式彻底解耦，作为独立模式分别可用。

---

## 二、架构设计

### 两种模式对比

| 维度 | `modify_text_ai` | `modify_text_ocr` |
|------|-------------------|---------------------|
| **规划** | VLM 定位 UI-JSON 组件 + text_changes | 同左（复用 VLM 组件定位） |
| **定位** | 组件 bounds（卡片级） | PaddleOCR 精定位（文字级） |
| **编辑** | `qwen-image-edit-max` 整区域重绘 | PIL 擦除 + 重绘（单文字） |
| **编辑区域** | ~1136×1346（整张卡片） | ~80×36（单个文字） |
| **画质影响** | 可能失真（大面积重建） | 零失真（仅改目标像素） |
| **适用场景** | OCR 无法识别的特殊文字（如手写体） | 标准 UI 文字替换（推荐） |
| **VLM 误规划防护** | 无（全部交给 AI） | 有（OCR 0/N 匹配时跳过） |

### 数据流

```
                     ┌─────────────────────────────────────────┐
                     │  VLM + UI-JSON → 卡片级 EditOps         │
                     │  (target_component + text_changes)       │
                     └──────────────┬──────────────────────────┘
                                    │
                ┌───────────────────┴───────────────────┐
                ▼                                       ▼
        modify_text_ai                          modify_text_ocr
                │                                       │
                ▼                                       ▼
        对每个卡片 op:                          对每个卡片 op:
        裁切卡片区域                            裁切卡片区域
        + padding                               PaddleOCR (中文)
                │                                       │
                ▼                                       ▼
        qwen-image-edit-max                     逐一匹配 text_changes
        整区域重绘                              与 OCR 结果
                │                                       │
                ▼                               ┌───────┴───────┐
        缩放 + 羽化边缘                         ▼               ▼
        贴回原位                             匹配成功          0/N 匹配
                                             文字级 EditOp     跳过该操作
                                             (PIL 渲染)        (VLM 误规划)
                                                │
                                                ▼
                                          PIL 擦除 + 重绘
                                          精确到像素
```

---

## 三、关键实现

### 3.1 新增方法 (`text_overlay.py`)

#### `_get_paddle_ocr()`
- **功能**：懒加载 PaddleOCR 实例（中文模式 `lang='ch'`）
- **GPU 支持**：自动检测 CUDA 可用性
- **容错**：PaddleOCR 未安装时返回 None，不影响 AI 模式

#### `_text_match(target, ocr_text)`
- **功能**：判断 OCR 识别文字是否匹配目标文字
- **策略**：精确匹配 → 包含匹配（互相包含且长度比 ≥ 50%）
- **用途**：容忍 OCR 轻微识别偏差

#### `_refine_ops_with_ocr(card_ops, screenshot_path)`
- **功能**：将卡片级 EditOps 拆解为文字级 EditOps
- **流程**：
  1. 裁切卡片区域（精确 bounds）
  2. PaddleOCR 检测所有文字
  3. 逐一匹配 `text_changes['from']` 与 OCR 结果
  4. 匹配到 → 转为绝对坐标，生成文字级 EditOp（`use_ai_edit=False`）
  5. 0/N 全部未匹配 → 判定 VLM 误规划，跳过该操作
  6. 部分未匹配 → 仅处理匹配到的，跳过未匹配的
- **字号估算**：`font_size = bbox_height × 0.75`

### 3.2 `plan_edits()` 路由逻辑

```python
if mode == 'modify_text_ai':
    # 纯 AI：VLM 定位 → AI 图像编辑
    _plan_modify_text_ai_edits() → 直接返回卡片级 ops

if mode in ('modify_text_ocr', 'modify_text'):
    # 纯 OCR：VLM 定位 → OCR 精定位 → PIL 渲染
    _plan_modify_text_ai_edits() → _refine_ops_with_ocr() → 返回文字级 ops
```

### 3.3 VLM 误规划防护（OCR 模式独有）

当 PaddleOCR 在目标组件中找不到任何 `text_changes['from']` 指定的文字（0/N 匹配）时，
说明 VLM 错误地为该组件规划了不存在的修改，此时直接跳过该操作。

**实际案例**：
- Z112 卡片包含 "有票""3张""8张" → OCR 3/4 匹配 → 执行 PIL 修改 ✓
- Z156 卡片不含上述文字 → OCR 0/3 匹配 → 跳过 ✓（避免 AI 模型乱改）

### 3.4 `_plan_modify_text_ai_edits()` 变更

此方法现在是纯 VLM 规划步骤，不再内含 OCR 调用。返回的 EditOps 全部为卡片级
（`use_ai_edit=True`），由调用方决定后续走 AI 还是 OCR 路径。

---

## 四、使用方式

### 命令行参数

```bash
# OCR 精定位模式（推荐，默认）
python run_pipeline.py \
  --screenshot ./page.png \
  --instruction "将硬座、硬卧、软卧的票量状态改为无票" \
  --anomaly-mode modify_text_ocr \
  --output ./output/

# modify_text 是 modify_text_ocr 的别名
python run_pipeline.py \
  --screenshot ./page.png \
  --instruction "将硬座、硬卧、软卧的票量状态改为无票" \
  --anomaly-mode modify_text \
  --output ./output/

# AI 图像编辑模式
python run_pipeline.py \
  --screenshot ./page.png \
  --instruction "将硬座、硬卧、软卧的票量状态改为无票" \
  --anomaly-mode modify_text_ai \
  --output ./output/
```

### apply_edit_plan.py 手工 Edit Plan

```bash
python apply_edit_plan.py \
  --screenshot ./page.png \
  --plan ./edit_plan.json \
  --ui-json ./stage2_filtered.json \
  --output ./output/
```

Edit Plan JSON 中通过 `style_hint.use_ai_edit` 控制走哪种执行路径：

```json
[
  {
    "action": "modify_text",
    "region": {"x": 443, "y": 892, "width": 80, "height": 36},
    "content": "无票",
    "style_hint": {"use_ai_edit": false, "font_size": 24}
  }
]
```

---

## 五、效果对比

以 12306 购票弹窗截图为例，指令："将硬卧、软卧、无座的票量状态改为无票"

| 指标 | 原始像素级 VLM | AI 图像编辑 | OCR 精定位 (最终) |
|------|---------------|------------|-------------------|
| 修改像素占比 | 0.06% | 42.54% | ~0.06% |
| Z112 "有票"→"无票" | ✓ (VLM 坐标) | ✓ (AI 重绘) | ✓ (OCR+PIL) |
| Z112 "3张"→"无票" | ✓ | ✓ | ✓ |
| Z112 "8张"→"无票" | ✓ | ✓ | ✓ |
| Z156 误修改 | ✗ 不涉及 | ✗ 被 AI 乱改 | ✓ 跳过 |
| 画质保真 | 中（PIL 填充） | 差（大面积重建） | 高（仅改目标文字） |
| 耗时 (Stage 3) | ~12s | ~57s | ~15s |

---

## 六、已知限制

| 限制 | 说明 | 规避方式 |
|------|------|---------|
| OCR 无法识别的文字 | 如手写体、艺术字、"售磬"（生僻字） | 使用 `modify_text_ai` 模式 |
| OCR 匹配依赖文字完全可见 | 被遮挡或截断的文字无法匹配 | 使用 `modify_text_ai` 模式 |
| PaddleOCR 依赖 | 需安装 paddleocr 和 paddlepaddle | 未安装时自动回退到像素级 VLM 规划 |
| PIL 字体渲染 | 简体中文字体需系统安装或指定 `--fonts-dir` | 确保系统有中文字体 |
