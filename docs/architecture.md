# UI 异常场景生成系统 - 架构文档

## 1. 项目概览

**目标**：对移动端 App 操作序列截图，在语义合理的时机注入异常场景（弹窗、加载失败、内容异常等），生成带有异常的截图序列，用于测试 AI Agent 的异常处理能力。

**核心流程**：`用户指令 → 映射配置 → 选择注入点 → 异常生成 → 序列改写 → 质量验证`

## 2. 目录结构

```
App_Test_Agent/
├── ui_semantic_patch/          # 核心代码
│   ├── app/
│   │   ├── injection/          # 异常注入决策与执行
│   │   │   ├── sequence_analyzer.py        # VLM 增量式序列分析器（旧方案）
│   │   │   ├── anomaly_recommender.py      # 异常类型推荐器
│   │   │   ├── anomaly_mapping_resolver.py # 映射配置解析器
│   │   │   ├── sequence_rewriter.py        # 序列改写执行器
│   │   │   ├── quality_verifier.py         # VLM 质量验证器
│   │   │   ├── prompts.py                  # VLM 提示词模板
│   │   │   └── verification_prompts.py     # 质量验证提示词
│   │   ├── renderers/          # 异常渲染引擎
│   │   │   ├── patch.py                    # 弹窗渲染引擎（核心）
│   │   │   ├── base.py                     # 渲染器基类
│   │   │   └── text_overlay.py             # 文字覆盖渲染
│   │   ├── stages/             # 流水线各阶段
│   │   │   └── visualize.py                # 组件可视化
│   │   ├── core/
│   │   │   ├── schemas.py                  # 数据模型定义
│   │   │   └── config.py                   # 集中配置
│   │   └── utils/
│   │       ├── semantic_dialog_generator.py # 语义弹窗生成器（核心）
│   │       ├── meta_loader.py              # GT 元数据加载
│   │       ├── component_position_resolver.py # 组件位置解析
│   │       ├── reference_analyzer.py       # 参考图分析
│   │       ├── history_manager.py          # 步骤历史管理
│   │       └── common.py                   # 通用工具函数
│   ├── scripts/                # 可执行脚本
│   │   ├── batch_injection_with_mapping.py # 映射驱动的批量注入（当前主入口）
│   │   ├── run_pipeline.py                 # 单例异常生成流水线
│   │   ├── batch_injection.py              # 批量注入（旧版）
│   │   ├── injection_pipeline.py           # 注入流水线
│   │   └── convert_queries_to_demo.py      # 查询转换工具
│   └── config/
│       └── query_anomaly_mapping.json      # 映射配置文件（关键）
├── data/
│   ├── examples/               # 示例任务
│   │   ├── injection_demo_01/  # 铁路12306 订票
│   │   ├── injection_demo_02/  # 瑞幸咖啡 点单
│   │   └── injection_demo_03/  # 去哪儿旅行 订机票
│   └── gt-category/            # GT 模板库（参考图 + meta.json）
│       └── dialog/             # 弹窗类模板
└── docs/                       # 文档
    └── architecture.md         # 本文件
```

## 3. 架构分层

```
┌──────────────────────────────────────────────────────────────┐
│                      Entry Scripts                            │
│  batch_utg_injection.py ⭐ / batch_injection_with_mapping.py  │
│  injection_pipeline.py / run_pipeline.py                      │
├──────────────────────────────────────────────────────────────┤
│                   Injection Decision                          │
│  ┌────────────────────┐  ┌─────────────────────────────────┐ │
│  │ UTG Text Decision ⭐│  │ VLM Visual Decision             │ │
│  │ (utga_loader +     │  │ (sequence_analyzer +            │ │
│  │  utga_decision)    │  │  page_classifier + rule_engine) │ │
│  │ 全量 ui_summary    │  │ 逐帧 VLM 图像分析               │ │
│  │ 一次文本 LLM 打分   │  │ 页面分类 → 规则匹配             │ │
│  └────────────────────┘  └─────────────────────────────────┘ │
├──────────────────────────────────────────────────────────────┤
│                   Anomaly Generation                          │
│  ┌──────────────┐  ┌──────────────────────────────────────┐  │
│  │ OmniParser   │→ │ VLM Semantic Grouping (Stage 2)      │  │
│  │ (YOLO+OCR)   │  └──────────┬───────────────────────────┘  │
│  └──────────────┘             ▼                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Anomaly Renderer                         │    │
│  │  ┌────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐ │    │
│  │  │ Dialog │ │  Modify  │ │  Area    │ │  Image    │ │    │
│  │  │ (弹窗) │ │  Text    │ │ Loading  │ │  Broken   │ │    │
│  │  └────────┘ └──────────┘ └──────────┘ └───────────┘ │    │
│  └──────────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────────┤
│                  Sequence Rewriter                            │
│  ┌──────────────────────────────────────────────────────────┐│
│  │  原图不变 + 插入 {ref}_anomaly.jpg + {ref}_normal.jpg   ││
│  │  保存 metadata.json + decision_log.json                  ││
│  └──────────────────────────────────────────────────────────┘│
├──────────────────────────────────────────────────────────────┤
│                  Quality Verification                         │
│  ┌──────────────────────────────────────────────────────────┐│
│  │  VLM 质量评分 + 维度评估 + 重试机制                      ││
│  └──────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
```

## 4. 数据流

### 4.1 UTG 批量注入流程 ⭐ (`batch_utg_injection.py`)

```
data/examples/{uuid}/
  ├── utga_info.json  (query + stepData)
  └── 001.jpg, 002.jpg ...

tmp/mapping.json  (injection_config for each query)
  │
  ▼
batch_utg_injection.py
  │
  ├── 1. scan_examples() → 扫描所有 UUID 目录
  │
  ├── 2. match_mapping() → UUID ↔ query_id O(1) 匹配
  │
  ├── 3. UTGDecisionMaker.decide()
  │   ├── 约束模式: injection_config 来自 mapping
  │   ├── LLM 批量打分: 每步 0-10 分 + 理由
  │   └── 选最高分 step（score ≥ 5）
  │
  ├── 4. run_pipeline.py → 生成异常图像
  │
  ├── 5. 序列组装
  │   ├── 原图不变（001.jpg, 002.jpg...）
  │   ├── 插入 {ref}_anomaly.jpg
  │   └── 插入 {ref}_normal.jpg（可关闭类）
  │
  └── 6. 输出: {uuid}/modified_sequence/ + metadata.json + decision_log.json
```

### 4.2 映射驱动流程（旧 `batch_injection_with_mapping.py`）

```
query_anomaly_mapping.json
  │
  ▼
batch_injection_with_mapping.py
  │
  ├── 1. 加载映射配置 (6 条规则, 覆盖 3 个示例)
  │
  ├── 2. 遍历 examples/ 目录
  │   ├── 读取 task.json → description + app_name
  │   └── 匹配 mapping → fault_mode + injection_config
  │
  ├── 3. 确定注入点
  │   └── injection_point = len(screenshots) // 2  ← 当前策略，无语义
  │
  ├── 4. 调用 SequenceRewriter.rewrite()
  │   ├── 复制注入点前的所有截图
  │   ├── 调用 run_pipeline.py 生成异常截图
  │   └── 插入异常截图，截断后续步骤
  │
  └── 5. (可选) VLM 质量验证
```

### 4.3 单例流水线流程（`run_pipeline.py`）

```
输入: screenshot + instruction + anomaly_mode + gt-category + gt-sample
  │
  ├── Stage 1: OmniParser 组件检测
  │   ├── YOLO 目标检测 → 组件框
  │   ├── PaddleOCR 文字识别
  │   └── Florence2 语义理解
  │   └── 输出: UI 组件列表 (42个组件)
  │
  ├── Stage 2: VLM 语义分组
  │   ├── VLM 分析组件关系 → 合并分组
  │   └── 输出: 结构化 UI-JSON (12个组件)
  │
  └── Stage 3: 异常渲染
      ├── dialog 模式 → PatchRenderer._render_dialog_meta_driven()
      │   ├── 加载 meta.json 视觉特征
      │   ├── VLM 生成语义文案
      │   ├── AI 生成弹窗图像 (DashScope)
      │   ├── 后处理: 去背景 → 擦除AI关闭按钮 → 裁切 → resize
      │   ├── 遮罩层绘制
      │   ├── 弹窗合成到原图
      │   └── 关闭按钮绘制 (PIL 代码绘制，不依赖 AI)
      └── 其他模式 → 对应渲染器
```

## 5. 异常注入决策（核心问题）

### 5.1 演进历史

| 阶段 | 方案 | 文件 | 效果 |
|------|------|------|------|
| V1 | VLM 逐帧自由决策 | `sequence_analyzer.py` | ❌ 不稳定，VLM 三维决策空间过大 |
| V2 | 固定中间位置 | `batch_injection_with_mapping.py` | ❌ 无语义，忽略截图内容 |
| V3 | VLM 分类 + 规则引擎 | `page_classifier.py` + `rule_engine.py` | ⚠️ VLM 图像分析仍成本高 |
| V4 ⭐ | **UTG 文本决策** | `utga_decision.py` + `utga_loader.py` | ✅ 已有语义数据，一次文本 LLM 批量打分 |

### 5.2 UTG 文本决策（当前推荐）⭐

核心思路：云端 Agent 执行时已产生精准的 `ui_summary` 语义描述，直接用文本 LLM 分析，替代 VLM 看图。

```
utga_info.json (已有 ui_summary + thought)
        ↓
  文本 LLM 一次调用（不传图）
        ↓
  全序列 0-10 打分: Step 0=3, Step 1=8, Step 2=5 ...
        ↓
  代码选最高分: Step 1 (score=8) → injection_step=1
```

优势：
- **成本低**：一次纯文本调用 ≈ N 次图片调用的 1/10
- **更精准**：`ui_summary` 是执行时的实时描述，比事后看图更准确
- **可解释**：每步返回分数 + 中文理由

详见 [UTG 架构文档](./utg-architecture.md)。

### 5.3 VLM 分类 + 规则引擎（旧，保留兼容）

VLM 任务从"开放式决策"降级为"封闭式分类"，
规则引擎基于分类结果做确定性匹配。

**VLM 承担**：页面类型分类 + 关键元素提取（封闭式，高准确率）
**规则引擎承担**：page_type → anomaly_mode 映射（确定性，可维护）
**注入点决策**：时序约束 + 页面类型优先级（可预测，可调优）

**关键组件**：
```
1. Rule Table (JSON):  page_type → anomaly_mode + instruction 模板
2. VLM Classifier:     截图 → {page_type, elements, user_waiting}
3. Rule Matcher:       分类结果 → anomaly_config
4. Timing Validator:   时序约束 (min_steps, 同类型优先级)
5. Fallback:           len//2 + dialog (兜底，不弱于当前)
```

## 6. 异常模式详解

系统实际业务涉及以下四大类异常模式：

### 6.1 dialog（弹窗覆盖）

需依赖 GT 参考截图，AI 生成弹窗后合成到原图。

| 属性 | 值 |
|------|-----|
| 描述 | 各类遮挡弹窗异常（广告推广、优惠券、系统提示、权限请求） |
| 生成方式 | AI 图像生成（DashScope）→ 后处理（去背景/擦除关闭按钮/裁切）→ PIL 合成到原图 |
| 依赖 GT 参考图 | ✅ 是 — 需要 meta.json 视觉特征 + 参考弹窗截图 |
| 参考图作用 | 提取弹窗布局、配色、圆角风格、按钮样式 |
| 关闭按钮 | PIL 代码绘制（不依赖 AI） |
| 典型场景 | 首页广告弹窗、无票提示弹窗、权限请求弹窗 |

### 6.2 area_loading（区域加载异常）

| 属性 | 值 |
|------|-----|
| 描述 | 在 UI 区域中心覆盖加载/超时图标 |
| 生成方式 | VLM 提取风格 → AI 生成图标（DashScope qwen-image-max）→ PIL 合成 |
| 依赖 GT 参考图 | ❌ 否，但可选 `--reference-icon` 提供参考图标提升真实性 |
| 依赖 Stage1 OmniParser | ✅ 需要 UI-JSON 获取目标组件位置 |
| 关闭按钮 | 无 |
| 典型场景 | 网络请求等待、数据加载、页面渲染 |

**实现细节**（`app/renderers/area_loading.py`）：

```
render() 入口
  │
  ├── 组件定位: 优先使用 target_component，否则选取最大区域组件
  │
  ├── Step 1: calculate_icon_size()      — 纯算法计算图标尺寸，无LLM
  │   └── 根据区域面积自适应比例 (15%~50%)
  │
  ├── Step 2: extract_app_style()        — VLM 提取 APP 视觉风格
  │   └── 提取主色、辅助色、圆角风格、设计语言等
  │
  ├── Step 2.5: analyze_reference_icon() — (可选) VLM 分析参考加载图标
  │   └── 提取形状、配色、动画风格等特征
  │
  ├── Step 3: generate_styled_icon()     — DashScope AI 生成图标
  │   ├── 固定生成 512×512（DashScope 最小要求）
  │   └── 缩小到目标尺寸（质量优先）
  │
  ├── Step 4: calculate_icon_position()  — 纯几何居中
  │
  └── Step 5: PIL 合成
      ├── _add_loading_overlay()         — 区域模糊+白色淡化（仅 timeout/network_error）
      └── paste(icon)                    — 粘贴 AI 生成的图标
```

**支持的异常子类型**（通过 `--instruction` 自动解析）：

| 指令关键词 | anomaly_type | 图标文案 |
|-----------|-------------|---------|
| 超时/timeout | `timeout` | "加载超时" / "视频加载失败" |
| 网络 | `network_error` | "网络异常，请检查网络连接" |
| 图片/image | `image_broken` | "图片加载失败，请稍后重试" |
| 空/empty | `empty_data` | "暂无商品" / "暂无内容" |
| 其他 | `loading` | 通用加载状态 |

**注意**：虽然 `area_loading` 内部支持 `image_broken`、`empty_state` 等文案，但这些仅作为加载图标的**内容文案**使用，并非独立的异常渲染模式。系统层面的 `image_broken`、`empty_state` 等独立模式未实现。

### 6.3 content_duplicate（内容重复）

| 属性 | 值 |
|------|-----|
| 描述 | UI 元素重复显示导致操作歧义 |
| 生成方式 | UI-JSON 组件复制 |
| 依赖 GT 参考图 | ❌ 否 |
| 关闭按钮 | 无 |
| 典型场景 | 列表加载异常、数据同步错误、缓存问题 |

### 6.4 文字编辑类异常（不依赖参考截图，共 4 种）

| 子模式 | 描述 | 生成方式 |
|--------|------|---------|
| `modify_text` / `modify_text_ocr` | OCR 精定位 + PIL 渲染文字替换 | OCR 定位文字区域 → PIL 渲染新文字 |
| `modify_text_ai` | AI 图像编辑文字替换 | AI 全图编辑（传入指令） |
| `modify_text_e2e` | 端到端全图 AI 编辑 | 跳过检测分组，直接 AI 编辑 |
| `text_overlay` | 局部文字编辑（插入额外信息） | VLM 定位 + PIL 渲染 |

| 公共属性 | 值 |
|---------|-----|
| 依赖 GT 参考图 | ❌ 否 |
| 关闭按钮 | 无 |
| 典型场景 | 按钮置灰、价格修改、插入优惠信息、文字替换 |

### 异常模式汇总

| 模式 | 依赖 GT | 关闭按钮 | 生成方式 | 当前状态 |
|------|---------|---------|---------|---------|
| `dialog` | ✅ | ✅ PIL 绘制 | AI 生成 + PIL 合成 | 已实现 |
| `area_loading` | ❌ (可参考图标) | ❌ | VLM→AI 生成图标→PIL 合成 | 已实现 |
| `content_duplicate` | ❌ | ❌ | UI-JSON 复制 | 已实现 |
| `modify_text` / `ocr` | ❌ | ❌ | OCR + PIL | 已实现 |
| `modify_text_ai` | ❌ | ❌ | AI 全图编辑 | 已实现 |
| `modify_text_e2e` | ❌ | ❌ | AI 全图编辑 | 已实现 |
| `text_overlay` | ❌ | ❌ | VLM + PIL | 已实现 |

## 7. GT 模板系统

### 7.1 目录结构

```
data/gt-category/
└── dialog/                      # 弹窗类 GT
    ├── 12306-首页-系统提示弹窗.jpg
    ├── 12306-查询结果-无票弹窗.jpg
    ├── 美团-首页-使用教程弹窗.jpg
    ├── 去哪儿-首页-权限类弹窗.jpg
    ├── 携程-首页-广告弹窗.jpg
    └── 京东到家-外卖页面-优惠券弹窗.jpg
```

### 7.2 每个 GT 样本关联的 meta.json

```json
{
  "app_style": "京东到家",
  "primary_color": "#FF1744",
  "background": "外层白色圆角卡片，内容区红色珊瑚渐变 #FF1744 → #FF6B35",
  "dialog_position": "bottom-fixed",
  "dialog_bounds_px": {"x": 0, "y": 2390, "width": 1201, "height": 300},
  "close_button_position": "none",
  "overlay_enabled": true,
  "overlay_opacity": 0.7,
  "buttons": ["立即领取"],
  "source_brand_keywords": ["京东到家", "京东秒送", "京东"]
}
```

### 7.3 加载链路

```
MetaLoader.extract_visual_features_dict(category, sample)
  → 加载 dialog/xxx/meta.json
  → 返回 {dialog_position, dialog_bounds_px, primary_color, ...}

MetaLoader.extract_visual_style_prompt(category, sample)
  → 生成 AI 图像风格的语义描述
```

## 8. 映射配置系统

### 8.1 配置结构 (`config/query_anomaly_mapping.json`)

```json
{
  "version": "2.0",
  "statistics": {"total_queries": 3, "total_fault_modes": 6},
  "mappings": [
    {
      "query": "进入(铁路12306)购买从{origin}到{destination}的火车票...",
      "app_name": "铁路12306",
      "example_dir": "injection_demo_01",
      "fault_mode": "弹窗广告遮挡查询按钮",
      "fault_mode_key": "mode_1",
      "injection_config": {
        "anomaly_mode": "dialog",
        "gt_category": "dialog",
        "gt_sample": "12306-首页-系统提示弹窗.jpg",
        "instruction": "在首页生成广告弹窗遮挡查询功能"
      }
    }
    // ... 共 6 条 (3 query × 2 fault_mode)
  ]
}
```

### 8.2 匹配机制

```python
# anomaly_mapping_resolver.py
class AnomalyMappingResolver:
    def resolve(query, app_name):
        1. app_name 精确匹配
        2. query_pattern 子串匹配
        3. 正则模糊匹配
        4. 兜底 fallback_config
```

## 9. 弹窗生成细节

### 9.1 AI 弹窗生成流程

```
generate_dialog_ai_from_meta()
  │
  ├── _crop_reference_to_dialog()    → 裁切参考图到弹窗区域
  ├── _build_ai_prompt_from_meta()   → 构建 prompt
  ├── generate_image()               → DashScope API / 本地服务
  │
  ├── 后处理:
  │   ├── resize()                   → 尺寸规范化
  │   ├── _remove_background()       → 移除黑色背景
  │   ├── _erase_ai_close_button()   → 擦除AI自行画的关闭按钮
  │   ├── _remove_extra_layers()     → 清理多余弹窗层（横幅类型）
  │   └── _crop_to_content_and_resize() → 裁切到内容区域
  │
  └── 返回: dialog_img (透明背景弹窗)
```

### 9.2 关闭按钮策略（四层防御）

| 层级 | 位置 | 方法 | 作用 |
|------|------|------|------|
| 1 | Negative Prompt | `semantic_dialog_generator.py:1695` | 排除 "close button, X button, 关闭按钮" |
| 2 | Positive Prompt | `semantic_dialog_generator.py:3090` | 明确描述 "NO X button" |
| 3 | AI 后处理擦除 | `_erase_ai_close_button()` | 扫描角落，检测 X 按钮并擦除 |
| 4 | 代码精确绘制 | `patch.py:305-341` | PIL 绘制关闭按钮，确保障碍和一致性 |

### 9.3 合成到原图

```python
# patch.py _render_dialog_meta_driven()
1. screenshot.convert('RGBA')
2. 叠加遮罩层 (overlay, 透明度 0.7)
3. result_img.paste(dialog_img, (pos_x, pos_y), dialog_img)
4. 绘制关闭按钮 (圆形背景 + X 线条)
5. 保存: final_{timestamp}.png
6. 保存: dialog_only_{timestamp}.png    (单独弹窗)
7. 保存: vis_bbox_{timestamp}.png       (关闭按钮检测框可视化)
```

## 10. 配置文件索引

| 文件 | 用途 |
|------|------|
| `config/query_anomaly_mapping.json` | 异常注入映射配置（核心） |
| `app/core/config.py` | 集中配置（路径、默认值） |
| `.env` | 环境变量（API Key、模型配置） |
| `data/gt-category/*/*.jpg` | GT 参考模板图 |
| `data/gt-category/*/meta.json` | GT 模板元数据 |

## 11. 关键数据模型

### 11.1 RenderResult (renderers/base.py)
```python
@dataclass
class RenderResult:
    image: Image.Image
    output_path: str
    metadata: dict       # 包含 render_info、gt_category 等
```

### 11.2 StepRecord (utils/history_manager.py)
```python
@dataclass
class StepRecord:
    step_index: int
    screenshot_path: str
    think: str
    decision: str              # "INJECT" / "SKIP"
    anomaly_type: Optional[str]
    instruction: Optional[str]
    conclusion: str
```

### 11.3 Mapping Config (injection_config)
```python
{
    "anomaly_mode": str,      # dialog / modify_text_ai / ...
    "gt_category": str,       # dialog / area_loading / ...
    "gt_sample": str,         # 参考图文件名
    "reference_path": str,    # 参考图完整路径
    "instruction": str,       # 异常生成指令
}
```

## 12. 已知问题与改进方向

### 12.1 注入点决策
- **问题**：当前 `len(screenshots)//2` 无视截图语义
- **方案**：VLM 页面分类 + 规则引擎（详见第 5.4 节）

### 12.2 GT 样本覆盖
- **问题**：配置引用的 `gt_sample` 与实际文件不匹配（如 `12306-查询结果-无票弹窗.jpg` 不存在）
- **方案**：同步配置与文件系统，或添加缺失的 GT 样本

### 12.3 故障模式分布不均
- **问题**：当前 6 条映射规则全部使用 `dialog` 模式，未利用 `area_loading`、`content_duplicate`、文字编辑类等其他已实现模式
- **方案**：根据页面类型合理分配异常模式——搜索结果页用 `modify_text`（无票提示）、列表页用 `content_duplicate`、等待页用 `area_loading`

### 12.4 异常注入多样性
- **问题**：每个示例仅注入 2 种故障模式，且模式固定
- **方案**：增加每个 query 的故障模式数量，支持随机选择

---

*文档版本: 1.0*
*最后更新: 2026-04-30*
