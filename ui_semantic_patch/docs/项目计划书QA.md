# 项目计划书 QA 解答

> **文档类型**: QA 解答文档
> **基于版本**: 项目计划书 v2.0
> **日期**: 2026-03-10
> **背景**: 基于项目当前完成进度，对计划书评审中提出的关键问题逐一解答

---

## Q1: 输入形式 — 输入为遍历路径，是否支持图片序列形式？

**支持。** 系统提供三种输入模式，其中 `injection_pipeline.py` 原生支持图片序列（遍历路径）：

| 入口 | 输入形式 | 序列感知 | 适用场景 |
|------|---------|---------|---------|
| `run_pipeline.py` | 单张截图 `--screenshot` | 无 | 单图异常生成 |
| `batch_pipeline.py` | 目录扫描 `--input-dir` | 无（无序集合） | 批量生成 |
| `injection_pipeline.py` | **截图序列目录** `--input-dir` | **有（按步骤顺序）** | 遍历路径注入 |

### 序列输入规范

参见 `injection_pipeline.py:57-73`，期望的目录结构：

```
input_dir/
├── task.json              # {"description": "打开携程→搜索酒店→下单"}
└── screenshots/
    ├── step_00.png        # 按文件名排序 → 步骤顺序
    ├── step_01.png
    ├── step_02.png
    └── ...
```

- 支持格式：`.png / .jpg / .jpeg / .webp`
- 排序机制：依赖文件名字典序（需命名为 `step_00`, `step_01`... 保证顺序）
- `task.json` 为可选文件，提供任务上下文描述

### 序列处理流程

```
step_00 → step_01 → step_02 → ... → step_N
   │         │         │
  SKIP      SKIP     INJECT  ← SequenceAnalyzer 逐步 VLM 分析
                       │
                  SequenceRewriter
                       │
              ┌────────┴────────┐
              ▼                  ▼
         复制 step_00~02    生成异常截图
              │                  │
              └──► 改写后完整序列 ◄┘
```

`SequenceAnalyzer.run()` 从 step_00 开始逐步分析，每步调用 VLM 判断 `INJECT` 或 `SKIP`。找到注入点后，`SequenceRewriter` 生成异常截图并截断后续步骤，输出改写后的完整序列。

### 当前限制与后续规划

| 限制项 | 现状 | 后续规划 |
|--------|------|---------|
| 注入点数量 | 仅支持单点注入（找到第一个注入点即停止） | Phase 2 遗留项：多点注入支持 |
| 注入后续步骤 | 注入点之后的步骤被截断 | 待扩展：异常恢复路径生成 |
| 批量序列处理 | 仅支持单条序列 | 待扩展：批量序列注入 |

---

## Q2: 工程化要求 — 截图留存与外部资源规范

### 2.1 截图与中间结果留存机制

**已实现全阶段中间结果留存。** 每次执行生成以下文件，可完整溯源：

#### 单图模式输出结构

```
output/
├── {name}_stage1_omni_raw_{ts}.json      # Stage 1 OmniParser 原始检测结果
├── {name}_stage1_annotated_{ts}.png       # Stage 1 检测结果可视化（标注框）
├── {name}_stage2_filtered_{ts}.json       # Stage 2 VLM 语义分组后
├── {name}_stage2_annotated_{ts}.png       # Stage 2 分组结果可视化
├── final_{ts}.png                         # Stage 3 最终异常截图
├── {name}_pipeline_meta_{ts}.json         # 全流水线元数据（含所有路径引用）
└── (text_overlay 模式额外输出)
    ├── diff_{ts}.png                      # 修改前后差异对比图
    └── edit_plan_{ts}.json                # 编辑操作计划
```

#### 溯源元数据 `pipeline_meta.json`

记录完整的输入-处理-输出链路：

```json
{
  "timestamp": "20260210_143000",
  "screenshot": "/原图绝对路径.jpg",
  "instruction": "异常指令文本",
  "stage2_status": "success|fallback",
  "outputs": {
    "stage1_omni_raw": "/stage1检测结果.json",
    "stage1_annotated": "/stage1可视化.png",
    "stage2_filtered": "/stage2分组结果.json",
    "stage2_annotated": "/stage2可视化.png",
    "final_image": "/最终异常截图.png",
    "pipeline_meta": "/本文件自引用.json",
    "meta_driven": true
  },
  "render_metadata": {
    "gt_category": "弹窗覆盖原UI",
    "gt_sample": "弹出广告.jpg",
    "render_info": {
      "dialog_bounds": {"x": 60, "y": 400, "width": 960, "height": 540},
      "screen_size": {"width": 1080, "height": 1920},
      "position_method": "component_match",
      "matched_component": {"index": 5, "class": "Button", "text": "搜索"},
      "ui_components_count": 13,
      "ui_components_preview": ["..."]
    }
  },
  "warnings": [
    {"type": "position_fallback", "message": "未找到关键词对应组件，使用百分比定位"}
  ]
}
```

#### 批量模式额外输出

```
batch_output/
└── batch_{category}_{ts}/
    ├── {screenshot}__{sample}/     # 每个任务独立目录
    │   ├── (完整的单图输出文件)
    │   └── ...
    └── batch_report.json           # 汇总报告
```

`batch_report.json` 记录所有任务的 成功/失败/耗时/路径。

#### 注入决策模式额外留存

```
output/injection_{ts}/
├── modified_sequence/              # 改写后完整序列
│   ├── step_00.png                # 原始截图（复制保留）
│   ├── step_01.png
│   └── step_02_anomaly.png        # 生成的异常截图
├── anomaly_generated/              # run_pipeline 原始输出（含全部中间结果）
├── metadata.json                   # 序列改写元数据
└── decision_log.json               # 完整决策过程记录（含每步 VLM 推理）
```

### 2.2 外部资源部署与使用规范

| 资源 | 类型 | 配置方式 | 必需性 | 备注 |
|------|------|---------|--------|------|
| **VLM API** | 远程 API（OpenAI 兼容格式） | `.env` → `VLM_API_KEY` | 必需 | 语义理解、决策推理 |
| **DashScope API** | 远程 API（阿里云） | `.env` → `DASHSCOPE_API_KEY` | 可选 | AI 图像生成（弹窗素材） |
| **OmniParser** | 本地部署 | `third_party/OmniParser/` | 必需 | YOLO + PaddleOCR + Florence2 |
| **GT 模板库** | 本地文件 | `data/Agent执行遇到的典型异常UI类型/` | 必需 | 含 meta.json 视觉特征描述 |
| **系统字体** | 本地系统 | PIL ImageFont | 必需 | 中文字体渲染 |

**配置优先级**: 环境变量 > 命令行参数 > 默认值

```bash
# .env 文件配置示例
VLM_API_KEY=sk-xxxxxxxxxxxxxxxx
VLM_API_URL=https://api.openai.com/v1/chat/completions   # 可选，默认 OpenAI
VLM_MODEL=gpt-4o                                         # 可选，默认 gpt-4o
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx                     # 可选
OMNI_DEVICE=cuda                                         # 可选，默认 cuda
```

### 2.3 当前不足与改进方向

| 不足 | 影响 | 改进方向（Phase 5） |
|------|------|---------------------|
| VLM/DashScope 依赖远程 API | 数据安全风险、网络依赖 | InferenceBackend 抽象 + 本地模型替代 |
| 原图路径为绝对引用 | 跨机器不可复现 | 改为相对路径 + 项目根目录配置 |
| 无统一 config.yaml | 配置分散 | 统一配置文件驱动 |

---

## Q3: 架构设计 — 异常注入决策模块的部署位置

### 当前部署架构

异常注入决策模块作为 `run_pipeline.py` 的 **上游决策层**，以本地 CLI 脚本形式部署。两者通过 subprocess 松耦合：

```
┌─────────────────────────────────────────────────────────────┐
│              injection_pipeline.py (CLI 入口)                │
│              职责: 决策 WHERE & WHAT                         │
└──────────────┬────────────────────────────┬──────────────────┘
               │                            │
         ┌─────▼────────┐           ┌───────▼──────────────┐
         │ Analyzer      │           │  Recommender         │
         │ - VLM逐步分析 │◄──────────┤  - GT模板库索引      │
         │ - 历史窗口管理 │ 可选类别  │  - 类别描述生成      │
         │ - 注入决策     │           │                      │
         └─────┬─────────┘           └──────────────────────┘
               │
        决策结果 (injection_point, anomaly_type, instruction)
               │
         ┌─────▼──────────────────────────────────┐
         │       Sequence Rewriter                 │
         │  1. 复制注入点前的原始截图               │
         │  2. subprocess 调用 run_pipeline.py     │  ← 松耦合
         │  3. 收集生成的异常截图                   │
         │  4. 组装改写后序列                       │
         └─────┬──────────────────────────────────┘
               │
         改写后输出 (modified_sequence/ + metadata.json + decision_log.json)
```

### 关键设计决策

| 决策 | 方案 | 理由 |
|------|------|------|
| 与主流水线的关系 | 上游决策层，subprocess 调用 | 不修改主流水线代码，向后兼容 |
| 历史窗口机制 | 借鉴 UI-Venus 增量式分析 | `max_history_steps=10`，控制 VLM 上下文长度 |
| VLM 调用策略 | `temperature=0.0` | 确保决策稳定性、可复现 |
| 最小注入步数 | `min_steps_before_inject=2` | 避免序列起始即注入，确保有足够上下文 |

### 部署演进路线（Phase 5 规划）

```
当前                    中期                        远期
CLI 脚本              FastAPI 服务化              Docker Compose
(本地调用)     →     (HTTP 接口，远程可调)   →   (一键容器化部署)
                            │
                     进程内调用替代 subprocess
                     (避免进程启动开销)
```

---

## Q4: 控件定位 — 弹窗信息中如何实现控件精准定位与捕获？

控件定位由 `component_position_resolver.py` 实现，采用 **关键词提取 + 4 级优先匹配 + 空间关系计算** 的三步策略。

### Step 1: 关键词提取

从异常指令中提取目标关键词（5 种正则模式，按优先级匹配）：

```python
# 示例："作品控件处增加下拉弹窗" → 提取 "作品"
patterns = [
    r'(\w+)控件处',              # "X控件处"
    r'(\w+)处增加',              # "X处增加"
    r'在(\w+)旁边',              # "在X旁边"
    r'点击(\w+)后',              # "点击X后"
    r'(\w+)(按钮|标签|文本)',     # "X按钮/标签/文本"
]
```

### Step 2: 4 级组件匹配

基于 Stage 2 输出的 UI-JSON（含所有 UI 组件的 `{index, bounds, text, class}`），逐级尝试匹配：

| 优先级 | 匹配方式 | 说明 | 示例 |
|--------|---------|------|------|
| 1 | `text_exact` | 文本精确匹配 | 关键词 "作品" = 组件文本 "作品" |
| 2 | `text_startswith` | 文本前缀匹配 | 关键词 "作品" → 组件文本 "作品推荐" |
| 3 | `text_contains` | 文本包含匹配 | 关键词 "作品" → 组件文本 "我的作品集" |
| 4 | `class_match` | 组件类别匹配 | 关键词 "按钮" → CLASS_NAME_MAP → `['Button', 'ImageButton']` |

**CLASS_NAME_MAP** 将中文类别名映射到 OmniParser 检测类别：

```python
CLASS_NAME_MAP = {
    '按钮': ['Button', 'ImageButton'],
    '输入框': ['EditText', 'TextInput'],
    '图片': ['ImageView'],
    '标签': ['TextView', 'Label'],
    ...
}
```

### Step 3: 空间关系计算

匹配到组件后，根据 meta.json 中的 `dialog_position` 属性计算弹窗放置坐标：

```python
POSITION_RELATIONSHIP = {
    'below_left':      # 基于组件左下方
    'below_center':    # 基于组件正下方居中
    'below_floating':  # 基于组件下方浮动（加偏移量）
    'below_fixed':     # 基于组件下方固定位置
    'above_center':    # 组件上方居中
    'overlay_center':  # 组件中心覆盖
}
```

**位置约束**：确保弹窗不超出屏幕边界 `max(0, min(pos_x, screen_width - dialog_width))`

### 兜底机制

若所有匹配均失败：

1. 使用 meta.json 中的 `dialog_size_ratio` 百分比定位
2. 在 `pipeline_meta.json` 中记录 `position_fallback` 警告
3. 默认居中放置

### 返回结构

```python
{
    'x': 120, 'y': 450,                    # 计算后的像素坐标
    'matched_component': {                  # 匹配到的组件信息
        'index': 5, 'class': 'Button',
        'text': '搜索', 'bounds': [100, 430, 200, 470]
    },
    'match_type': 'text_exact',            # 匹配方式
    'keyword': '搜索',                     # 提取的关键词
    'used_fallback': False                 # 是否触发兜底
}
```

---

## Q5: 校验机制 — meta.json 的校验是否包含对生成效果的验证？

### 结论：当前不包含生成效果验证

meta.json 的校验仅覆盖 **结构完整性**，不包含对最终生成图像的质量验证。

### 已有校验能力

| 校验维度 | 实现方式 | 范围 |
|---------|---------|------|
| JSON 格式合法性 | `json.load()` 异常捕获 | ✅ 已实现 |
| 必填字段存在性 | `validate_and_fill()` 检查 `anomaly_type`, `visual_features` 等 | ✅ 已实现 |
| 缺失字段默认值填充 | `VISUAL_DEFAULTS` 字典 (`overlay_enabled`, `close_button_position` 等) | ✅ 已实现 |
| 品牌/敏感词过滤 | `extract_visual_style_prompt()` 过滤华为/淘宝/京东等关键词 | ✅ 已实现 |
| API 调用异常处理 | 429 重试 + 指数退避 + HTTP 状态码检查 | ✅ 已实现 |

### 间接验证手段

虽然无自动化质量评估，但提供了以下辅助验证信息：

| 验证手段 | 内容 | 文件位置 |
|---------|------|---------|
| 渲染元数据 | 弹窗边界、定位方法、匹配组件 | `pipeline_meta.json → render_info` |
| 警告记录 | 回退事件（位置匹配失败、Stage 2 降级等） | `pipeline_meta.json → warnings` |
| 差异对比图 | 修改前后视觉对比 | `diff_{ts}.png`（text_overlay / modify_text* / modify_text_e2e 模式） |
| Stage 可视化 | Stage 1/2 检测与分组结果标注 | `*_annotated_*.png` |

以上均供 **人工检查** 使用，无自动化评分。

### 待补充的验证能力（Phase 4 规划）

| 序号 | 验证能力 | 方案 |
|------|---------|------|
| 1 | 评估数据集 | ≥ 50 组 {输入截图, 异常指令} → {期望输出} 对 |
| 2 | 自动化评估脚本 | 保真度（SSIM/LPIPS）、语义相关性（VLM 打分）、文字清晰度 |
| 3 | VLM 辅助质量评分 | 用 VLM 对生成结果进行 1-5 分评分 |
| 4 | 回归测试 | 提示词版本变更后自动对比评估 |

---

## Q6: 自动化能力 — 是否支持自动化生成？

**支持。** 系统的三个入口均支持全自动化执行，无需人工介入：

### 自动化调用方式

| 场景 | 命令 | 人工介入 |
|------|------|---------|
| 单图自动生成 | `python run_pipeline.py -s X -i Y -o Z` | 无 |
| 批量自动生成 | `python batch_pipeline.py -i DIR -c CATEGORY --run` | 无 |
| 序列注入（交互式） | `python injection_pipeline.py -i DIR -o OUT` | 注入决策确认 |
| 序列注入（全自动） | `python injection_pipeline.py -i DIR -o OUT --no-interactive` | 无 |
| 一键启动 | `bash launch.sh single` / `bash launch.sh batch --run` | 无 |

### 自动化全链路

```
截图输入
  → [自动] OmniParser 检测 (Stage 1)
  → [自动] VLM 语义分组 (Stage 2)
  → [自动] 渲染器选择 + 异常生成 (Stage 3)
  → [自动] 保存全部中间结果 + 元数据
  → [自动] 批量报告生成 (batch 模式)
```

### 批量自动化示例

```bash
# 扫描目录所有图片 × 所有GT样本，生成笛卡尔积
python batch_pipeline.py \
  --input-dir ../data/原图/app首页类-开屏广告弹窗 \
  --gt-category "弹窗覆盖原UI" \
  --output ./batch_output \
  --run                       # 加此参数直接执行（否则为 dry-run 预览）

# 输出: batch_report.json 汇总所有任务成功/失败/耗时
```

### 序列注入全自动示例

```bash
python injection_pipeline.py \
  --input-dir examples/injection_demo \
  --output-dir output/injected \
  --no-interactive              # 跳过人工确认，全自动执行
```

---

## Q7: 文档规范 — 框图表达需参考 Skill 模块的细节描述粒度

当前计划书中的框图为 ASCII + Mermaid 双版本。以下补充各模块的接口契约摘要，达到 Skill 模块级别的描述粒度：

### 模块接口契约表

| 模块 | 输入 | 输出 | 关键方法 | 数据格式 |
|------|------|------|---------|---------|
| **omni_extractor** | `screenshot: PIL.Image`, `device: str` | OmniParser 原始检测 | `run_omniparser()` | `{components: [{index: int, bounds: [x1,y1,x2,y2], text: str, class: str}...], componentCount: int}` |
| **omni_vlm_fusion** | Stage1 JSON + screenshot | UI-JSON（语义过滤后） | `omni_vlm_fusion()` | 同上格式，`componentCount` 减少（57→~13），附加 `metadata.processing.merge_log` |
| **sequence_analyzer** | `screenshots: List[Path]` | 注入决策结果 | `run()`, `analyze_step()` | `{success: bool, injection_point: int, anomaly_type: str, instruction: str, reasoning: str, history: List[StepRecord]}` |
| **anomaly_recommender** | GT 模板目录路径 | 类别描述文本 | `get_categories_description()`, `get_available_categories()` | `List[{name: str, description: str, samples: List[str]}]` |
| **sequence_rewriter** | 原始序列 + 决策结果 | 改写序列 + 元数据 | `rewrite()` | `{modified_sequence: List[Path], metadata: dict, decision_log: dict}` |
| **renderers/\*** | `screenshot: Image`, `ui_json: dict`, `instruction: str` | 渲染结果 | `render()` | `RenderResult{image: Image, output_path: Path, metadata: dict, warnings: List}` |
| **component_position_resolver** | `instruction: str`, `ui_json: dict`, `meta_features: dict` | 定位结果 | `resolve()` | `{x: int, y: int, matched_component: dict\|None, match_type: str, keyword: str, used_fallback: bool}` |
| **meta_loader** | GT 模板目录 | 视觉特征字典 | `extract_visual_features_dict()`, `extract_visual_style_prompt()` | `{dialog_width_ratio: float, dialog_height_ratio: float, dialog_position: str, overlay_enabled: bool, ...}` |
| **history_manager** | 步骤分析记录 | 格式化历史文本 | `add_record()`, `build_history_text()` | `StepRecord{step_index, screenshot_path, think, decision, anomaly_type, instruction, conclusion}` |

### 细化框图（含接口签名）

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          入口层                                          │
│                                                                          │
│  run_pipeline.py                injection_pipeline.py                    │
│  ┌──────────────────────┐       ┌────────────────────────────────────┐   │
│  │ run_pipeline(         │       │ main(                              │   │
│  │   screenshot: str,    │       │   --input-dir: Path,               │   │
│  │   instruction: str,   │       │   --output-dir: Path,              │   │
│  │   anomaly_mode: str,  │       │   --no-interactive: bool,          │   │
│  │   gt_category: str,   │       │   --min-steps: int=2,              │   │
│  │   gt_sample: str,     │       │   --max-history: int=10            │   │
│  │   output_dir: str     │       │ )                                  │   │
│  │ ) → dict              │       │ ) → None                           │   │
│  └──────────┬────────────┘       └──────────┬─────────────────────────┘   │
│             │                               │                             │
│  batch_pipeline.py                          │                             │
│  ┌──────────────────────┐                   │                             │
│  │ run_batch(            │                   │                             │
│  │   input_dir: str,     │──► run_pipeline   │                             │
│  │   gt_category: str,   │    (循环调用)      │                             │
│  │   pattern: str='*.jpg'│                   │                             │
│  │ ) → batch_report      │                   │                             │
│  └──────────────────────┘                   │                             │
└─────────────────────────────────────────────┼─────────────────────────────┘
                                              │
┌─────────────────────────────────────────────▼─────────────────────────────┐
│                          AI 感知层 (analysis/)                            │
│                                                                          │
│  omni_extractor.py                    omni_vlm_fusion.py                 │
│  ┌─────────────────────────┐          ┌─────────────────────────────┐    │
│  │ run_omniparser(          │          │ omni_vlm_fusion(             │    │
│  │   image: PIL.Image,      │ ──────► │   raw_result: dict,          │    │
│  │   device: str='cuda'     │ Stage1  │   screenshot: PIL.Image,     │    │
│  │ ) → {                    │ JSON    │   api_key: str               │    │
│  │   components: List,      │         │ ) → {                        │    │
│  │   componentCount: int,   │         │   components: List,          │    │
│  │   annotated_image: Image │         │   componentCount: int,       │    │
│  │ }                        │         │   metadata: {merge_log}      │    │
│  └─────────────────────────┘          │ }                            │    │
│                                       └──────────────┬──────────────┘    │
│  gt_bounds.py                                        │                   │
│  ┌─────────────────────────┐                         │ UI-JSON           │
│  │ extract_bounds(          │                         │                   │
│  │   gt_image: Image        │                         │                   │
│  │ ) → {x,y,width,height}  │                         │                   │
│  └─────────────────────────┘                         │                   │
└──────────────────────────────────────────────────────┼───────────────────┘
                                                       │
┌──────────────────────────────────────────────────────▼───────────────────┐
│                        注入决策层 (injection/)                            │
│                                                                          │
│  sequence_analyzer.py              anomaly_recommender.py                │
│  ┌──────────────────────────┐      ┌────────────────────────────────┐    │
│  │ run(                      │      │ get_categories_description()   │    │
│  │   screenshots: List[Path] │◄─────│ → str (可用异常类别描述)       │    │
│  │ ) → {                     │      │                                │    │
│  │   injection_point: int,   │      │ get_available_categories()     │    │
│  │   anomaly_type: str,      │      │ → List[str]                   │    │
│  │   instruction: str,       │      └────────────────────────────────┘    │
│  │   reasoning: str,         │                                           │
│  │   history: List[Record]   │      sequence_rewriter.py                 │
│  │ }                         │      ┌────────────────────────────────┐    │
│  └────────────┬──────────────┘      │ rewrite(                       │    │
│               │ 决策结果             │   original_screenshots,        │    │
│               └────────────────────►│   injection_point: int,        │    │
│                                     │   anomaly_type: str,           │    │
│  prompts.py                         │   instruction: str             │    │
│  ┌──────────────────────────┐       │ ) → {                          │    │
│  │ INJECTION_DECISION_PROMPT│       │   modified_sequence: List,     │    │
│  │ STEP_SUMMARY_PROMPT      │       │   metadata: dict               │    │
│  │ ANOMALY_CATEGORY_TEMPLATE│       │ }                              │    │
│  └──────────────────────────┘       └──────────┬─────────────────────┘    │
│                                                │ subprocess              │
│  history_manager.py                            │ 调用 run_pipeline       │
│  ┌──────────────────────────┐                  │                         │
│  │ HistoryManager(           │                  │                         │
│  │   max_steps: int=10       │                  │                         │
│  │ )                         │                  │                         │
│  │ .add_record(StepRecord)   │                  │                         │
│  │ .build_history_text()→str │                  │                         │
│  └──────────────────────────┘                  │                         │
└────────────────────────────────────────────────┼─────────────────────────┘
                                                 │
┌────────────────────────────────────────────────▼─────────────────────────┐
│                        异常渲染层 (renderers/)                           │
│                                                                          │
│  base.py (ABC)                                                           │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │ render(screenshot, ui_json, instruction, **kwargs) → RenderResult│    │
│  │ get_mode_name() → str                                            │    │
│  └───────────────────────────┬──────────────────────────────────────┘    │
│           ┌──────────────────┼──────────────────┬──────────────┐         │
│           ▼                  ▼                  ▼              ▼         │
│  ┌──────────────┐ ┌──────────────┐ ┌─────────────────┐ ┌───────────┐   │
│  │ patch.py      │ │area_loading │ │content_duplicate│ │text_overlay│   │
│  │ mode="dialog" │ │mode="area_  │ │mode="content_   │ │mode="text_│   │
│  │               │ │  loading"   │ │  duplicate"     │ │  overlay" │   │
│  │ meta-driven   │ │加载图标覆盖 │ │底部浮层复制     │ │局部文字   │   │
│  │ 弹窗渲染      │ │             │ │                 │ │编辑替换   │   │
│  └──────────────┘ └─────────────┘ └─────────────────┘ └───────────┘   │
│                                                                          │
│  RenderResult = {image: Image, output_path: Path,                       │
│                  metadata: dict, warnings: List[str]}                    │
└──────────────────────────────────────────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼────────────────────────────────────────┐
│                   工具与生成层 (utils/ + generators/)                     │
│                                                                          │
│  component_position_resolver.py      meta_loader.py                      │
│  ┌──────────────────────────────┐    ┌────────────────────────────────┐  │
│  │ resolve(                      │    │ extract_visual_features_dict() │  │
│  │   instruction, ui_json, meta  │    │ → {width_ratio, height_ratio, │  │
│  │ ) → {x, y,                   │    │    position, overlay, ...}     │  │
│  │   matched_component,          │    │                                │  │
│  │   match_type, keyword,        │    │ extract_visual_style_prompt()  │  │
│  │   used_fallback}              │    │ → str (过滤敏感词后的风格描述) │  │
│  └──────────────────────────────┘    └────────────────────────────────┘  │
│                                                                          │
│  semantic_dialog_generator.py        reference_analyzer.py               │
│  ┌──────────────────────────────┐    ┌────────────────────────────────┐  │
│  │ generate_dialog(              │    │ analyze(reference_image)       │  │
│  │   instruction, meta_features, │    │ → {colors, layout, buttons,   │  │
│  │   screenshot                  │    │    shadows, style}             │  │
│  │ ) → PIL.Image                 │    └────────────────────────────────┘  │
│  └──────────────────────────────┘                                        │
└──────────────────────────────────────────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼────────────────────────────────────────┐
│                          外部依赖层                                      │
│                                                                          │
│  ┌──────────────────┐  ┌──────────────┐  ┌─────────────────────────┐    │
│  │ VLM API           │  │ DashScope    │  │ OmniParser (本地)       │    │
│  │ OpenAI兼容格式    │  │ AI图像生成   │  │ YOLO+PaddleOCR+Florence2│    │
│  │ temperature=0.0   │  │ 5次重试+退避 │  │ cuda/cpu 可切换         │    │
│  └──────────────────┘  └──────────────┘  └─────────────────────────┘    │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │ 🔮 未来: 本地化替代                                               │    │
│  │   VLM → vLLM/Ollama    DashScope → Stable Diffusion/SDXL        │    │
│  │   InferenceBackend 统一接口, config.yaml 驱动切换                 │    │
│  └──────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Q8: 工程化相关疑问与建议 + 合作方成果集成

### 8.1 当前工程化现状评估

| 维度 | 现状 | 差距 | 对应计划 |
|------|------|------|---------|
| 部署方式 | 本地 CLI 脚本 | 无 Docker / 无 REST API | Phase 5 |
| 推理后端 | 远程 API 调用 | 无本地化方案 | Phase 5 |
| 扩展接口 | 渲染器有 `BaseRenderer` 基类 | 无动态注册、无插件规范文档 | Phase 5 |
| 配置管理 | `.env` + 命令行参数 | 无统一 `config.yaml` | Phase 5 |
| 测试覆盖 | 无自动化测试 | 需端到端测试 + 单元测试 | Phase 2 遗留 |
| 包管理 | `requirements.txt` | 未 SDK 化（无 `pip install`） | Phase 5 |
| 质量评估 | 人工检查 | 无自动化评估 | Phase 4 |

### 8.2 合作方（老师）成果集成方案

#### 背景

此前 UI Test Agent 及异常挖掘的技术合作中，部分合作方已转向其他任务。需将合作方（老师）的成果集成至本系统，并预留相应接口。

#### 接口预留设计

**1. 渲染器插件接口** — 合作方可开发自定义异常渲染器：

```python
from renderers.base import BaseRenderer, RenderResult

class CustomAnomalyRenderer(BaseRenderer):
    """合作方自定义渲染器 — 只需实现两个方法"""

    def get_mode_name(self) -> str:
        return "custom_anomaly"

    def render(self, screenshot, ui_json, instruction, **kwargs) -> RenderResult:
        # 合作方实现具体渲染逻辑
        modified_image = self._apply_custom_anomaly(screenshot, ui_json)
        return RenderResult(
            image=modified_image,
            output_path=output_path,
            metadata={"custom_field": "value"},
            warnings=[]
        )
```

**2. 动态注册机制** — 新渲染器无需修改核心代码：

```python
from injection.anomaly_recommender import AnomalyRegistry

registry = AnomalyRegistry()
registry.register_mode(
    mode_name="custom_anomaly",
    renderer_cls=CustomAnomalyRenderer,
    meta={"description": "合作方自定义异常模式", "category": "custom"}
)
```

**3. 推理后端可替换** — 合作方可使用自有模型：

```python
from utils.inference_backend import InferenceBackend

class TeacherModelBackend(InferenceBackend):
    """合作方自有模型后端"""
    def chat_completion(self, messages, **kwargs) -> str:
        # 对接合作方模型服务
        return self._call_teacher_model(messages)

# 使用合作方模型
pipeline = Pipeline(backend=TeacherModelBackend(endpoint="http://teacher-server:8080"))
```

**4. 标准数据接口** — 统一输入输出格式：

```python
from utils.data_adapter import DataAdapter

class TeacherDataAdapter(DataAdapter):
    """对接合作方数据格式"""
    def load_screenshots(self, source) -> List[Screenshot]:
        # 将合作方数据格式转换为标准格式
        ...
    def export_results(self, results, format="teacher_format") -> None:
        # 将结果转换为合作方需要的格式
        ...
```

#### 集成优先级建议

| 阶段 | 任务 | 目标 |
|------|------|------|
| **近期** | 定义渲染器插件规范文档 + 示例模板 | 合作方可先行开发自定义渲染器 |
| **中期** | 实现 `AnomalyRegistry` 动态注册 + FastAPI 服务化 | 合作方渲染器可热插拔 |
| **远期** | SDK 打包发布 (`pip install app-test-agent`) | 合作方一行命令即可使用 |

---

**文档版本**: v1.0
**最后更新**: 2026-03-26
**文档同步**: 流水线约定见仓库根目录 [Claude.md](../../../Claude.md)。
