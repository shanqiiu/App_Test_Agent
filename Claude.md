# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

本项目专注于AI智能体测试技术研究，特别是**异常场景测试的自动化生成**。

---

## 项目定位

- **项目类型**: 技术研究
- **当前阶段**: 原型开发与优化（Phase 2）
- **核心目标**: 构建异常测试场景自动生成平台
- **项目规模**: 17,186 行 Python 代码，7 个主控脚本，4 个分析模块，5 个渲染器，8 个工具库

---

## 环境配置

```bash
# 1. 复制并填写 API 密钥
cp .env.example .env

# 2. 安装 ui_semantic_patch 核心依赖
pip install -r ui_semantic_patch/requirements.txt

# 3. 安装 OmniParser 依赖（需要 GPU/CUDA 推荐）
pip install -r ui_semantic_patch/third_party/OmniParser/requirements.txt
```

`.env` 必需变量：
- `VLM_API_KEY` — OpenAI 兼容接口密钥（UI 分析/语义理解）
- `DASHSCOPE_API_KEY` — 阿里云 DashScope 密钥（AI 图像生成，可选）

---

## 运行原型代码

所有脚本从 `ui_semantic_patch/scripts/` 目录执行。

### 一键启动（推荐）

```bash
cd ui_semantic_patch/scripts
bash launch.sh              # 交互式菜单
bash launch.sh single       # 单图模式（使用脚本内默认配置）
bash launch.sh batch --run  # 批量模式
bash launch.sh list         # 列出所有可用异常类别
```

### 主要流水线

#### 1. 异常生成流水线（run_pipeline.py）

```bash
cd ui_semantic_patch/scripts

# 弹窗模式（meta-driven，推荐）
python run_pipeline.py \
  --screenshot ../data/原图/app首页类-开屏广告弹窗/携程旅行01.jpg \
  --instruction "生成优惠券广告弹窗" \
  --gt-category "弹窗覆盖原UI" \
  --gt-sample "弹出广告.jpg" \
  --output ./output/demo

# 区域加载模式
python run_pipeline.py \
  --screenshot ../data/原图/影视剧集类-内容歧义、重复/腾讯视频.jpg \
  --instruction "模拟列表加载超时" \
  --anomaly-mode area_loading \
  --output ./output/demo

# 内容重复模式
python run_pipeline.py \
  --screenshot ../data/原图/影视剧集类-内容歧义、重复/腾讯视频.jpg \
  --instruction "模拟底部信息重复显示" \
  --anomaly-mode content_duplicate \
  --gt-category "内容歧义、重复" \
  --gt-sample "部分信息重复.jpg" \
  --output ./output/demo

# 文字编辑模式（AI 图像编辑）
python run_pipeline.py \
  --screenshot "../data/Agent执行遇到的典型异常UI类型/analysis/gt_templates/弹窗覆盖原UI/05.jpg" \
  --instruction "将硬卧席位状态从有票改为灰色无票字样，预订按钮置灰" \
  --anomaly-mode modify_text_ai \
  --output ./output/12306无座_modify_text

# 文字编辑模式（OCR 精定位）
python run_pipeline.py \
  --screenshot ../data/原图/app首页类-开屏广告弹窗/携程旅行01.jpg \
  --instruction "将租车服务价格从99元改为199元" \
  --anomaly-mode modify_text_ocr \
  --output ./output/demo

# 文字编辑模式（端到端）
python run_pipeline.py \
  --screenshot ../data/原图/app首页类-开屏广告弹窗/携程旅行01.jpg \
  --instruction "在租车服务卡片中插入优惠信息" \
  --anomaly-mode modify_text_e2e \
  --output ./output/demo
```

#### 2. 注入决策流水线（injection_pipeline.py）

```bash
cd ui_semantic_patch/scripts

# 分析操作序列并推荐异常注入点
python injection_pipeline.py \
  --screenshots-dir ../examples/injection_demo/screenshots \
  --task-file ../examples/injection_demo/task.json \
  --output ./output/injection_demo
```

#### 3. 批量生成（batch_pipeline.py）

```bash
cd ui_semantic_patch/scripts
python batch_pipeline.py \
  --input-dir ../data/原图/app首页类-开屏广告弹窗 \
  --gt-category "弹窗覆盖原UI" \
  --output ./batch_output \
  --run  # 加 --run 实际执行，否则为 dry-run
```

#### 4. GT 元数据生成（generate_meta.py）

```bash
cd ui_semantic_patch/scripts

# 为 GT 模板目录生成 meta.json
python generate_meta.py \
  --gt-dir ../data/Agent执行遇到的典型异常UI类型/analysis/gt_templates/弹窗覆盖原UI \
  --output ../data/Agent执行遇到的典型异常UI类型/analysis/gt_templates/弹窗覆盖原UI/meta.json
```

---

## 核心架构

### 1. 三阶段流水线（run_pipeline.py）

```
截图输入 → Stage 1: OmniParser → Stage 2: VLM 语义分组 → Stage 3: 异常渲染 → 输出图像
```

| 阶段 | 模块 | 技术栈 | 输入 | 输出 |
|------|------|--------|------|------|
| **Stage 1** | `analysis/omni_extractor.py` | YOLO + PaddleOCR + Florence2 | 原始截图 | `*_stage1_omni_raw_*.json` |
| **Stage 2** | `analysis/omni_vlm_fusion.py` | VLM 语义分组 | Stage 1 结果 | `*_stage2_grouping_*.json` |
| **Stage 3** | `renderers/*` | 模式专用渲染器 | Stage 2 结果 + 指令 | `*_final_*.png` |

### 2. 目录结构

```
ui_semantic_patch/
├── scripts/                           # 核心脚本层（17,186 行）
│   ├── 主控层
│   │   ├── run_pipeline.py            # 三阶段主流水线
│   │   ├── batch_pipeline.py          # 批量生成
│   │   ├── injection_pipeline.py      # 注入决策流水线
│   │   ├── generate_meta.py           # meta.json 自动生成
│   │   ├── generate_instructions.py   # 测试指令泛化生成
│   │   ├── apply_edit_plan.py         # 编辑计划执行
│   │   ├── vlm_component_edit_pipeline.py  # VLM 组件编辑
│   │   └── launch.sh                  # 一键启动脚本
│   │
│   ├── analysis/                      # AI 感知层（Stage 1+2）
│   │   ├── omni_extractor.py          # OmniParser 本地推理
│   │   ├── omni_vlm_fusion.py         # VLM 语义分组
│   │   ├── gt_bounds.py               # GT 边界框提取
│   │   └── visualize.py               # 检测结果可视化
│   │
│   ├── renderers/                     # 异常渲染层（Stage 3）
│   │   ├── base.py                    # 渲染器统一接口
│   │   ├── patch.py                   # Dialog 弹窗渲染
│   │   ├── area_loading.py            # 区域加载异常
│   │   ├── content_duplicate.py       # 内容重复
│   │   └── text_overlay.py            # 文字覆盖/编辑
│   │
│   ├── generators/                    # 元数据生成层
│   │   ├── meta.py                    # meta.json 生成
│   │   └── filename_descriptions.py   # 文件名描述生成
│   │
│   ├── injection/                     # 注入决策层
│   │   ├── sequence_analyzer.py       # 操作序列分析
│   │   ├── anomaly_recommender.py     # 异常推荐
│   │   ├── sequence_rewriter.py       # 序列改写
│   │   ├── prompts.py                 # VLM 提示词模板
│   │   └── mock_provider.py           # Mock 模式实现
│   │
│   ├── utils/                         # 工具库
│   │   ├── common.py                  # 公共工具
│   │   ├── meta_loader.py             # GT 元数据加载
│   │   ├── semantic_dialog_generator.py  # 弹窗生成器
│   │   ├── component_position_resolver.py  # 组件定位
│   │   ├── gt_manager.py              # GT 管理
│   │   ├── reference_analyzer.py      # 参考图分析
│   │   ├── anomaly_sample_manager.py  # 异常样本管理
│   │   └── history_manager.py         # 历史记录管理
│   │
│   └── tests/                         # 测试模块
│       ├── test_api_auth.py           # API 认证测试
│       └── test_qwen_image_open.py    # 通义万相 API 测试
│
├── data/                              # 数据集
│   ├── 原图/                          # 原始 APP 截图（7 类 30+ 张）
│   │   ├── 12306无票/                 # 18 张火车票截图
│   │   ├── app首页类-开屏广告弹窗/     # 5 张
│   │   ├── 个人主页类-控件点击弹窗/    # 2 张
│   │   ├── 双按钮干扰/                # 3 张
│   │   ├── 外卖类优惠信息干扰/        # 2 张
│   │   ├── 影视剧集类-内容歧义、重复/ # 1 张
│   │   └── 订票优惠编辑/              # 2 张
│   │
│   ├── Agent执行遇到的典型异常UI类型/  # GT 模板（3 类 16 个样本）
│   │   └── analysis/gt_templates/
│   │       ├── 弹窗覆盖原UI/          # 14 个样本 + meta.json
│   │       ├── 内容歧义、重复/        # 1 个样本 + meta.json
│   │       └── loading_timeout/       # 1 个样本 + meta.json
│   │
│   └── scenarios/                     # 业务场景配置
│       └── flight_booking/
│           ├── scenario.json          # 订机票场景定义
│           └── instructions.json      # 测试指令集
│
├── third_party/OmniParser/            # 本地集成的 OmniParser
│   ├── omni_inference.py              # OmniParser 推理引擎
│   ├── weights/                       # 预训练权重
│   │   ├── icon_detect/               # YOLO 检测模型
│   │   └── icon_caption_florence/     # Florence2 图标描述模型
│   └── requirements.txt               # OmniParser 依赖
│
├── examples/                          # 示例文件
│   └── injection_demo/                # 注入流水线示例
│       ├── task.json                  # 任务描述
│       └── screenshots/               # 13 张操作序列截图
│
└── requirements.txt                   # 项目依赖

```

### 3. 异常渲染模式

| 模式 | 渲染器 | 功能 | 应用场景 |
|------|--------|------|---------|
| `dialog` | `renderers/patch.py` | 弹窗覆盖 | 广告、提示、引导弹窗 |
| `area_loading` | `renderers/area_loading.py` | 区域加载异常 | 加载超时、转圈、骨架屏 |
| `content_duplicate` | `renderers/content_duplicate.py` | 内容重复 | 列表项重复、卡片重复 |
| `modify_text_ai` | `renderers/text_overlay.py` | AI 图像编辑 | 基于组件区域的精确编辑 |
| `modify_text_ocr` | `renderers/text_overlay.py` | OCR 精定位 | 文字替换、信息修改 |
| `modify_text_e2e` | `renderers/text_overlay.py` | 端到端编辑 | 跳过检测、整图编辑 |

### 4. 数据流与输出文件

```
原始截图
    ↓
[Stage 1] OmniParser 检测
    ├─ YOLO 检测框
    ├─ PaddleOCR 文本
    └─ Florence2 图标描述
    ↓ 输出: *_stage1_omni_raw_*.json
    ↓
[Stage 2] VLM 语义分组
    ├─ 判断框的分组关系
    ├─ 合并坐标（代码计算）
    └─ 输出分组后的 UI-JSON
    ↓ 输出: *_stage2_grouping_*.json
    ↓
[Stage 3] 异常渲染
    ├─ 根据异常模式选择渲染器
    ├─ 执行渲染操作
    └─ 输出异常截图 + 元数据
    ↓ 输出: *_final_*.png + *_pipeline_meta_*.json
```

**输出文件说明**:

| 文件模式 | 生成阶段 | 说明 |
|---------|--------|------|
| `*_stage1_omni_raw_*.json` | Stage 1 | OmniParser 原始检测结果 |
| `*_stage1_annotated_*.png` | Stage 1 | 检测框可视化 |
| `*_stage2_filtered_*.json` | Stage 2 | VLM 过滤后的结果 |
| `*_stage2_grouping_*.json` | Stage 2 | 分组后的 UI-JSON |
| `*_stage2_annotated_*.png` | Stage 2 | 分组结果可视化 |
| `edit_plan_*.json` | Stage 3 | 文本编辑执行计划 |
| `diff_*.png` | Stage 3 | 编辑像素差异可视化 |
| `*_final_*.png` | Stage 3 | 最终异常截图 |
| `*_pipeline_meta_*.json` | 完成时 | 流水线元数据（耗时、参数、告警） |

### 5. GT 模板驱动机制

**meta.json 结构**：
```json
{
  "category": "dialog_blocking",
  "samples": [
    {
      "filename": "弹出广告.jpg",
      "anomaly_type": "advertisement_popup",
      "anomaly_description": "优惠券广告弹窗",
      "visual_features": {
        "colors": ["#FF6B6B", "#FFFFFF"],
        "position": "center",
        "size": "medium",
        "style": "rounded_corners"
      },
      "generation_template": {
        "instruction": "生成优惠券广告弹窗",
        "patch_operation": "overlay"
      }
    }
  ]
}
```

**MetaLoader 接口**：
- `list_categories()` — 列出所有异常类别
- `list_samples(category)` — 列出指定类别的样本
- `load_sample_meta(category, sample_name)` — 加载样本元数据

### 6. 注入决策流水线（injection_pipeline.py）

```
操作序列（截图 1..N）
    ↓
[SequenceAnalyzer] 增量式分析
    ├─ 逐步分析每张截图
    ├─ 累积上下文（历史步骤）
    └─ 每步决策：INJECT 或 SKIP
    ↓
[AnomalyRecommender] 异常推荐
    ├─ 根据当前界面推荐异常类型
    ├─ 考虑语义合理性、测试价值
    └─ 输出推荐的异常 + 生成指令
    ↓
[用户确认] 交互式确认（可选）
    ↓
[异常生成] 调用 run_pipeline.py
    ↓
[SequenceRewriter] 序列改写
    ├─ 在指定位置注入异常截图
    └─ 输出改写后的序列 + 日志
```

---

## 文档结构

```
docs/
├── research/        # 调研文档（命名：NN_描述.md）
├── technical/       # 技术栈与工具.md、术语表.md
├── references/      # 学术研究.md、开源项目.md
├── planning/        # 研究路线图.md、待研究问题.md
└── setup/           # 环境搭建指南.md
```

**文档管理规则**:
- 新调研文档 → `docs/research/NN_描述.md`，更新 `docs/research/README.md`
- 新工具/术语 → 对应技术文档，不重复创建
- 优先级标记：🔥 高 / ⭐ 中 / 💡 探索

---

## 提交规范

- `docs:` — 文档更新
- `feat:` — 新功能原型
- `refactor:` — 代码或文档重构
- `experiment:` — 实验性代码
- `chore:` — 配置、依赖等

---

## 核心术语

| 术语 | 英文 | 说明 |
|------|------|------|
| 智能体 | AI Agent | 能够感知、决策、执行的AI系统 |
| 异常场景 | Anomaly Scenario | 偏离正常行为的测试场景 |
| GT 模板 | Ground Truth Template | 真实异常截图，作为生成参考 |
| UI-JSON | - | Stage 2 输出的结构化界面表示 |
| meta-driven | - | 由 meta.json 驱动的精准生成模式 |
| OmniParser | - | 本地 UI 检测模型（YOLO + PaddleOCR + Florence2） |
| VLM | Vision Language Model | 视觉语言模型，用于语义理解和分组 |
| 注入决策 | Injection Decision | 在操作序列中自动推荐异常注入点 |
| 序列改写 | Sequence Rewriting | 在操作序列中插入异常截图 |

---

## 技术栈

| 组件 | 技术 | 用途 |
|------|------|------|
| UI 检测 | YOLO + PaddleOCR + Florence2 | Stage 1 组件检测 |
| 语义理解 | VLM (GPT-4o / Qwen-VL) | Stage 2 语义分组 |
| 图像生成 | DashScope (qwen-image-max) | Dialog 弹窗生成 |
| 图像编辑 | DashScope (qwen-image-edit-max) | 文字编辑模式 |
| 图像处理 | Pillow | 渲染、合成、裁剪 |
| 环境管理 | python-dotenv | API 密钥管理 |

---

**配置版本**: v5.0
**最后更新**: 2026-04-08
**文档角色**: 项目权威配置文档，定义流水线架构、异常模式、数据结构和工具接口。
