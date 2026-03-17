# 脚本文档

UI 异常场景生成流水线的完整脚本参考。

---

## 目录

- [整体流程概述](#整体流程概述)
- [快速命令](#快速命令)
- [Pipeline 执行脚本](#pipeline-执行脚本)
  - [单图执行 run_pipeline.py](#单图执行-run_pipelinepy)
  - [批量执行 batch_pipeline.py](#批量执行-batch_pipelinepy)
  - [注入决策 injection_pipeline.py](#注入决策-injection_pipelinepy)
  - [一键启动 launch.sh](#一键启动-launchsh)
- [中间结果与元数据脚本](#中间结果与元数据脚本)
  - [meta.json 生成/更新 generate_meta.py](#metajson-生成更新-generate_metapy)
  - [GT 边界框提取 gt_bounds.py](#gt-边界框提取-gt_boundspy)
  - [指令生成 generate_instructions.py](#指令生成-generate_instructionspy)
- [可视化命令](#可视化命令)
  - [检测结果可视化 visualize.py](#检测结果可视化-visualizepy)
  - [Pipeline 内置可视化](#pipeline-内置可视化)
  - [中间结果文件一览](#中间结果文件一览)
- [子模块架构](#子模块架构)
- [环境变量](#环境变量)
- [故障排查](#故障排查)

---

## 整体流程概述

### 三阶段生成流水线

从一张正常 APP 截图出发，经过 AI 感知 → 语义理解 → 异常渲染三个阶段，生成一张带有目标异常的截图。

```
原始截图
  │
  ▼
Stage 1: OmniParser 粗检测（omni_extractor.py）
  ├─ YOLO 目标检测 → 所有 UI 组件边界框
  ├─ PaddleOCR 文字识别 → 组件文本内容
  └─ Florence2 图标描述 → 非文字组件语义
  → 输出: *_stage1_omni_raw_*.json + *_stage1_annotated_*.png
  │
  ▼
Stage 2: VLM 语义分组（omni_vlm_fusion.py）
  ├─ 合并: 属于同一逻辑组件的多个检测框合并为一个
  ├─ 过滤: 去除海报装饰文字等非交互元素
  └─ 去重: OCR 与 YOLO 重复检测的合并
  → 输出: *_stage2_filtered_*.json + *_stage2_annotated_*.png
  │
  ▼
Stage 3: 异常渲染（renderers/*）
  ├─ dialog        → PatchRenderer（弹窗覆盖）
  ├─ area_loading  → AreaLoadingRenderer（区域加载异常）
  ├─ content_duplicate → ContentDuplicateRenderer（内容重复）
  └─ text_overlay  → TextOverlayRenderer（文字覆盖编辑）
  → 输出: *_final_*.png + *_pipeline_meta_*.json
```

### 注入决策流水线（可选）

对 Agent 操作序列（多张截图）进行增量分析，智能决定在哪一步注入什么异常：

```
操作序列（task.json + screenshots/）
  │
  ▼
逐步语义分析（sequence_analyzer.py）
  ├─ 累积上下文理解当前操作阶段
  └─ 结合异常推荐器决定 INJECT / SKIP
  │
  ▼
异常生成（调用 run_pipeline.py）
  │
  ▼
序列改写（sequence_rewriter.py）
  ├─ 在注入点插入异常截图
  └─ 截断后续步骤
  → 输出: 改写后的操作序列
```

---

## 快速命令

```bash
cd prototypes/ui_semantic_patch/scripts

# ===== Pipeline 执行 =====

# 单图生成（弹窗模式）
python run_pipeline.py \
  --screenshot ../data/原图/app首页类-开屏广告弹窗/携程旅行01.jpg \
  --instruction "生成优惠券广告弹窗" \
  --gt-category "弹窗覆盖原UI" --gt-sample "弹出广告.jpg" \
  --output ./output/demo

# 批量生成
python batch_pipeline.py \
  --input-dir ../data/原图/app首页类-开屏广告弹窗 \
  --gt-category "弹窗覆盖原UI" --output ./batch_output --run

# 注入决策流水线
python injection_pipeline.py \
  --input-dir examples/injection_demo \
  --output-dir output/injected --interactive

# 一键启动（交互式菜单）
bash launch.sh

# ===== 中间结果与元数据 =====

# 生成/更新 meta.json（dry-run 预览）
python generate_meta.py --dir "../data/Agent执行遇到的典型异常UI类型/analysis/gt_templates/弹窗覆盖原UI"

# 生成 meta.json（实际写入）
python generate_meta.py --dir "../data/.../弹窗覆盖原UI" --run

# 提取 GT 弹窗边界框
python -m analysis.gt_bounds --category "弹窗覆盖原UI"

# 生成测试指令
python generate_instructions.py --scenario flight_booking --type both --count 30

# ===== 可视化 =====

# 独立可视化任意 UI-JSON
python -m analysis.visualize \
  --screenshot ./screenshot.png \
  --ui-json ./output/screenshot_stage2_filtered_xxx.json \
  --output ./annotated.png
```

---

## Pipeline 执行脚本

### 单图执行 `run_pipeline.py`

三阶段主流水线入口，输入一张截图 + 异常指令，输出异常截图和全部中间结果。

```bash
python run_pipeline.py \
  --screenshot <截图路径> \
  --instruction <异常指令> \
  [--anomaly-mode dialog|area_loading|content_duplicate|text_overlay] \
  [--gt-category <GT类别>] [--gt-sample <GT样本>] \
  [--output <输出目录>]
```

**四种异常模式示例**：

```bash
# 1. dialog — 弹窗覆盖（默认模式）
python run_pipeline.py \
  --screenshot ../data/原图/app首页类-开屏广告弹窗/携程旅行01.jpg \
  --instruction "生成优惠券广告弹窗" \
  --gt-category "弹窗覆盖原UI" --gt-sample "弹出广告.jpg" \
  --output ./output/demo

# 2. area_loading — 区域加载异常
python run_pipeline.py \
  --screenshot ../data/原图/影视剧集类-内容歧义、重复/腾讯视频.jpg \
  --instruction "模拟列表加载超时" \
  --anomaly-mode area_loading \
  --output ./output/demo

# 3. content_duplicate — 内容重复
python run_pipeline.py \
  --screenshot ../data/原图/影视剧集类-内容歧义、重复/腾讯视频.jpg \
  --instruction "模拟底部信息重复显示" \
  --anomaly-mode content_duplicate \
  --gt-category "内容歧义、重复" --gt-sample "部分信息重复.jpg" \
  --output ./output/demo

# 4. text_overlay — 局部文字覆盖
python run_pipeline.py \
  --screenshot ../data/原图/app首页类-开屏广告弹窗/携程旅行01.jpg \
  --instruction "在租车服务卡片中插入优惠信息" \
  --anomaly-mode text_overlay \
  --output ./output/demo
```

**完整参数表**：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--screenshot, -s` | 原始截图路径 | 必需 |
| `--instruction, -i` | 异常指令 | 必需 |
| `--output, -o` | 输出目录 | `./output` |
| `--anomaly-mode` | 异常模式 | `dialog` |
| `--gt-category` | GT 模板类别名 | - |
| `--gt-sample` | GT 模板样本文件名 | - |
| `--gt-dir` | GT 样本目录 | 自动检测 |
| `--reference, -r` | 参考弹窗图片（dialog 模式） | - |
| `--reference-icon` | 参考加载图标（area_loading 模式） | - |
| `--target-component` | 目标组件 ID（area_loading 模式） | 自动推荐 |
| `--api-key` | VLM API 密钥 | `VLM_API_KEY` 环境变量 |
| `--api-url` | VLM API 端点 | `VLM_API_URL` 环境变量 |
| `--vlm-model` | VLM 模型名称 | `VLM_MODEL` 环境变量 |
| `--structure-model` | 结构提取模型 | `STRUCTURE_MODEL` 环境变量 |
| `--omni-device` | OmniParser 设备 (`cuda`/`cpu`) | `OMNIPARSER_DEVICE` 环境变量 |
| `--no-visualize` | 禁用检测结果可视化 | False |

---

### 批量执行 `batch_pipeline.py`

对指定原图目录 × GT 类别下的所有样本做笛卡尔积批量生成。

```bash
python batch_pipeline.py \
  --input-dir <原图目录> \
  --gt-category <GT类别> \
  [--output <输出目录>] \
  [--run]                 # 默认 dry-run，加 --run 实际执行
```

**示例**：

```bash
# 预览（dry-run，查看将要执行的组合）
python batch_pipeline.py \
  --input-dir ../data/原图/app首页类-开屏广告弹窗 \
  --gt-category "弹窗覆盖原UI" \
  --output ./batch_output

# 实际执行
python batch_pipeline.py \
  --input-dir ../data/原图/app首页类-开屏广告弹窗 \
  --gt-category "弹窗覆盖原UI" \
  --output ./batch_output --run

# 列出所有可用类别和样本
python batch_pipeline.py --list-categories
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--input-dir` | 原图目录 | 必需 |
| `--gt-category` | GT 模板类别 | 必需 |
| `--output` | 输出目录 | `./batch_output` |
| `--pattern` | 图片文件匹配模式 | `*.jpg` |
| `--run` | 实际执行（默认 dry-run） | False |
| `--list-categories` | 列出所有可用类别和样本 | - |

---

### 注入决策 `injection_pipeline.py`

对 Agent 操作截图序列进行增量语义分析，自动决定在哪一步注入异常。

```bash
python injection_pipeline.py \
  --input-dir <输入目录> \
  --output-dir <输出目录> \
  [--interactive]          # 每步需用户确认
```

**输入目录结构**：

```
input/
├── task.json           # {"description": "在携程预订酒店"}
└── screenshots/
    ├── step_00.png
    ├── step_01.png
    ├── step_02.png
    └── ...
```

**示例**：

```bash
python injection_pipeline.py \
  --input-dir ./examples/injection_demo \
  --output-dir ./output/injected \
  --interactive
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--input-dir` | 输入目录（含 `task.json` + `screenshots/`） | 必需 |
| `--output-dir` | 输出目录 | 必需 |
| `--interactive` | 启用用户确认流程 | False |

---

### 一键启动 `launch.sh`

交互式菜单启动器，自动检查环境（.env、API Key、Python 等）。

```bash
bash launch.sh              # 交互式菜单选择
bash launch.sh single       # 单图模式（使用脚本内默认配置）
bash launch.sh batch --run  # 批量模式
bash launch.sh list         # 列出所有可用异常类别
```

内置 5 个预配置场景：弹窗广告、关闭按钮干扰、内容重复、加载超时、普通弹窗。

---

## 中间结果与元数据脚本

### meta.json 生成/更新 `generate_meta.py`

使用 VLM 自动分析 GT 模板目录下的异常截图，生成结构化的 `meta.json` 文件。`meta.json` 描述了每个 GT 样本的视觉特征（颜色、布局、按钮样式、遮罩等），是 `dialog` 模式弹窗生成的核心驱动数据。

```bash
# 预览模式（默认 dry-run，不写入文件）
python generate_meta.py --dir "../data/Agent执行遇到的典型异常UI类型/analysis/gt_templates/弹窗覆盖原UI"

# 实际写入
python generate_meta.py --dir "../data/.../弹窗覆盖原UI" --run

# 覆盖已有 meta.json（默认为 merge 仅添加新样本）
python generate_meta.py --dir "../data/.../弹窗覆盖原UI" --run --force

# 批量扫描所有 GT 子目录
python generate_meta.py --scan-all "../data/Agent执行遇到的典型异常UI类型/analysis/gt_templates" --run

# 手动指定类别（目录名无法自动推断时）
python generate_meta.py --dir "./custom_dir" --category dialog_blocking --run

# 同时提取弹窗边界框（需要 OmniParser）
python generate_meta.py --dir "../data/.../弹窗覆盖原UI" --run --extract-bounds
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--dir, -d` | 单个 GT 模板目录路径 | 与 `--scan-all` 二选一 |
| `--scan-all` | GT 模板根目录，遍历所有子目录 | 与 `--dir` 二选一 |
| `--category, -c` | 类别 ID（`dialog_blocking` / `content_duplicate` / `loading_timeout`） | 从目录名自动推断 |
| `--description` | 类别中文描述 | 自动推断 |
| `--run` | 实际写入文件 | 默认 dry-run |
| `--force` | 覆盖已有 meta.json | 默认 merge |
| `--extract-bounds` | 同时提取 `dialog_bounds_px`（需 OmniParser） | False |
| `--omni-device` | OmniParser 设备（与 `--extract-bounds` 配合） | - |
| `--output, -o` | 输出路径 | `<dir>/meta.json` |
| `--api-key` | VLM API 密钥 | `VLM_API_KEY` |
| `--vlm-model` | VLM 模型名 | `VLM_MODEL` |
| `--retry` | 失败重试次数 | 2 |
| `--verbose, -v` | 显示 VLM 原始返回 | False |

**meta.json 输出结构**：

```json
{
  "category": "dialog_blocking",
  "description": "弹窗覆盖UI - 用于生成各类遮挡弹窗异常",
  "count": 8,
  "samples": {
    "弹出广告.jpg": {
      "anomaly_type": "promotional_coupon_dialog",
      "anomaly_description": "携程首页弹出优惠券广告弹窗",
      "visual_features": {
        "app_style": "携程",
        "dialog_position": "center",
        "dialog_size_ratio": {"width": 0.85, "height": 0.55},
        "overlay_enabled": true,
        "overlay_opacity": 0.5,
        "close_button_position": "bottom-center",
        "main_button_text": "立即领取",
        "...": "..."
      },
      "generation_template": {
        "instruction": "生成优惠券广告弹窗",
        "patch_operations": [...],
        "key_points": [...]
      },
      "dialog_bounds_px": {"x": 45, "y": 320, "width": 390, "height": 480}
    }
  }
}
```

---

### GT 边界框提取 `gt_bounds.py`

从 GT 参考图中精确提取弹窗的像素级边界框，写入 `meta.json` 的 `dialog_bounds_px` 字段。Pipeline 在 dialog 模式下使用此信息精确控制弹窗叠加位置和大小。

```bash
# 提取所有样本的边界框
python -m analysis.gt_bounds --category "弹窗覆盖原UI"

# 只提取指定样本
python -m analysis.gt_bounds --category "弹窗覆盖原UI" --sample "弹出广告.jpg"

# 强制重新提取（覆盖已有）
python -m analysis.gt_bounds --category "弹窗覆盖原UI" --force

# 预览模式（不写入 meta.json）
python -m analysis.gt_bounds --category "弹窗覆盖原UI" --dry-run

# 跳过 VLM 过滤，仅用 OmniParser
python -m analysis.gt_bounds --category "弹窗覆盖原UI" --skip-vlm
```

**提取流程**：

1. 对 GT 参考图运行 OmniParser（Stage 1）获取所有检测框
2. 运行 VLM 语义过滤（Stage 2）合并弹窗子元素
3. 根据 meta.json 中的 `dialog_position` + `dialog_size_ratio` 计算预期区域
4. 用 IoU 匹配找到最佳弹窗组件
5. 对有遮罩的弹窗（`overlay_enabled=true`）使用亮度分割法辅助定位
6. 将精确像素边界 `dialog_bounds_px` 写回 meta.json

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--gt-dir` | GT 模板目录 | 自动查找 |
| `--category` | 处理的类别名称 | `弹窗覆盖原UI` |
| `--sample` | 只处理指定样本 | 处理所有 |
| `--force` | 强制重新提取 | False |
| `--skip-vlm` | 跳过 VLM 过滤，只用 OmniParser | False |
| `--dry-run` | 只分析不写入 | False |
| `--api-key` | VLM API 密钥 | `VLM_API_KEY` |
| `--vlm-model` | VLM 模型名称 | `STRUCTURE_MODEL` |
| `--omni-device` | OmniParser 运行设备 | - |

---

### 指令生成 `generate_instructions.py`

基于业务场景配置 + LLM 推理，批量生成多样化的测试指令。

```bash
# 列出可用场景
python generate_instructions.py --list-scenarios

# 预览提示词（dry-run，不调用 API）
python generate_instructions.py --scenario flight_booking --dry-run

# 生成异常注入指令
python generate_instructions.py --scenario flight_booking --type anomaly --count 30

# 生成用户意图指令
python generate_instructions.py --scenario flight_booking --type user --count 30

# 同时生成两种指令
python generate_instructions.py --scenario flight_booking --type both --count 20
```

**指令类型说明**：

| 类型 | 说明 | 示例 |
|------|------|------|
| `anomaly` | 异常注入指令 — 描述要注入的故障 | "在支付页面弹出网络超时弹窗" |
| `user` | 用户意图指令 — 模拟用户自然语言 | "帮我预订明天北京到上海的机票" |
| `both` | 同时生成两种（默认） | - |

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--scenario, -s` | 场景名称（对应 `data/scenarios/` 目录） | 必需 |
| `--type, -t` | 指令类型 | `both` |
| `--count, -n` | 每种类型的生成数量 | 20 |
| `--output, -o` | 输出文件路径 | `<场景目录>/instructions.json` |
| `--dry-run` | 仅输出提示词，不调用 API | False |
| `--list-scenarios` | 列出所有可用场景 | - |

**场景配置**：在 `data/scenarios/<场景名>/scenario.json` 中定义业务步骤、异常模式映射等。

---

## 可视化命令

### 检测结果可视化 `visualize.py`

将 OmniParser / VLM 语义分组的 UI-JSON 检测结果叠加到原始截图上，绘制彩色边界框和标签，便于验证和调试。

```bash
# 可视化指定的 UI-JSON 文件
python -m analysis.visualize \
  --screenshot ./screenshot.png \
  --ui-json ./output/screenshot_stage2_filtered_xxx.json \
  --output ./annotated.png

# 调整字体和线宽
python -m analysis.visualize \
  --screenshot ./screenshot.png \
  --ui-json ./output/screenshot_stage1_omni_raw_xxx.json \
  --output ./annotated.png \
  --font-size 12 --border-width 3

# 不显示文本标签（仅边界框）
python -m analysis.visualize \
  --screenshot ./screenshot.png \
  --ui-json ./stage2.json \
  --output ./boxes_only.png \
  --no-text

# 仅显示，不保存文件
python -m analysis.visualize \
  --screenshot ./screenshot.png \
  --ui-json ./stage2.json \
  --no-save
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--screenshot, -s` | 原始截图路径 | 必需 |
| `--ui-json, -j` | UI-JSON 文件路径 | 必需 |
| `--output, -o` | 输出图片路径 | 自动命名 `*_annotated.png` |
| `--no-save` | 不保存文件，仅显示 | False |
| `--font-size` | 标签字体大小 | 10 |
| `--border-width` | 边界框线宽 | 2 |
| `--no-text` | 不显示文本标签 | False |

**颜色编码规则**：

| 组件类型 | 颜色 | HEX |
|---------|------|-----|
| Button | 红色 | `#FF6B6B` |
| TextView | 青色 | `#4ECDC4` |
| ImageView | 浅绿 | `#95E1D3` |
| Card | 浅蓝 | `#A8D8EA` |
| Dialog | 深粉 | `#FF6B9D` |
| NavigationBar | 深绿 | `#2A9D8F` |
| 其他 | 紫色 | `#8E44AD` |

---

### Pipeline 内置可视化

`run_pipeline.py` 默认自动生成 Stage 1 和 Stage 2 的可视化标注图（除非指定 `--no-visualize`）：

```bash
# 正常运行（自动生成可视化）
python run_pipeline.py -s screenshot.png -i "生成弹窗" -o ./output

# 禁用可视化（加速执行）
python run_pipeline.py -s screenshot.png -i "生成弹窗" -o ./output --no-visualize
```

运行后在输出目录对比 Stage 1 和 Stage 2 的标注图，可以验证 VLM 语义分组是否正确合并了检测框。

---

### 中间结果文件一览

Pipeline 运行后，输出目录包含以下文件：

| 文件模式 | 说明 | 生成阶段 | 获取方式 |
|---------|------|--------|---------|
| `*_stage1_omni_raw_*.json` | OmniParser 原始检测结果（所有组件坐标） | Stage 1 | `run_pipeline.py` 自动生成 |
| `*_stage1_annotated_*.png` | Stage 1 检测框可视化 | Stage 1 | `run_pipeline.py` 自动生成 |
| `*_stage2_filtered_*.json` | VLM 语义过滤/分组后的 UI-JSON | Stage 2 | `run_pipeline.py` 自动生成 |
| `*_stage2_annotated_*.png` | Stage 2 分组结果可视化 | Stage 2 | `run_pipeline.py` 自动生成 |
| `*_final_*.png` | 最终异常截图 | Stage 3 | `run_pipeline.py` 自动生成 |
| `*_pipeline_meta_*.json` | 流水线执行元数据（参数、耗时等） | 完成时 | `run_pipeline.py` 自动生成 |
| `meta.json` | GT 模板视觉特征描述 | 预处理 | `generate_meta.py` 生成 |
| `instructions.json` | 批量测试指令 | 预处理 | `generate_instructions.py` 生成 |

**单独获取某一阶段的中间结果**：

```bash
# 如果只需要 Stage 1 + Stage 2 的 JSON（不需要最终渲染），
# 直接运行 pipeline 后从 output 目录获取对应的 json 文件即可

# 如果需要对已有的 JSON 做可视化：
python -m analysis.visualize \
  --screenshot <原始截图> \
  --ui-json <stage1或stage2的json文件> \
  --output <输出路径>

# 如果需要更新 meta.json：
python generate_meta.py --dir <GT目录> --run

# 如果需要更新 dialog_bounds_px：
python -m analysis.gt_bounds --category "弹窗覆盖原UI" --force
```

---

## 子模块架构

### analysis/ — AI 感知层

| 模块 | 职责 |
|------|------|
| `omni_extractor.py` | OmniParser 本地推理（YOLO + PaddleOCR + Florence2） |
| `omni_vlm_fusion.py` | VLM 语义分组：合并/过滤/去重 |
| `gt_bounds.py` | GT 模板精确边界框提取 |
| `visualize.py` | 检测结果可视化（边界框标注） |

### renderers/ — 异常渲染层

| 模块 | 对应模式 | 机制 |
|------|---------|------|
| `base.py` | - | 渲染器统一基类 |
| `patch.py` | `dialog` | VLM 语义分析 + PIL/AI 弹窗合成叠加 |
| `area_loading.py` | `area_loading` | VLM 推荐目标区域 + Loading 图标覆盖 |
| `content_duplicate.py` | `content_duplicate` | 组件裁剪 + 底部浮层扩展渲染 |
| `text_overlay.py` | `text_overlay` | VLM 编辑规划 + PIL 局部文字精确绘制 |

### generators/ — 元数据生成层

| 模块 | 职责 |
|------|------|
| `meta.py` | VLM 驱动 meta.json 自动生成（GT 模板视觉特征描述） |
| `filename_descriptions.py` | 基于文件名的异常描述生成 |

### injection/ — 注入决策层

| 模块 | 职责 |
|------|------|
| `sequence_analyzer.py` | 增量式操作序列语义分析 |
| `anomaly_recommender.py` | 基于语义上下文的异常推荐决策 |
| `sequence_rewriter.py` | 将推荐转化为修改后的操作序列 |
| `prompts.py` | VLM 提示词模板 |

### utils/ — 工具库

| 模块 | 职责 |
|------|------|
| `common.py` | 图片编码（base64）、JSON 提取、颜色解析 |
| `semantic_dialog_generator.py` | 语义感知弹窗生成（DashScope AI + PIL） |
| `meta_loader.py` | GT 元数据加载与管理 |
| `gt_manager.py` | GT 模板提取、风格分析、Few-shot 参考 |
| `component_position_resolver.py` | UI-JSON 精确组件定位（多级匹配 + 百分比回退） |
| `reference_analyzer.py` | 参考图片风格分析 |
| `anomaly_sample_manager.py` | 异常样本聚类与导出 |
| `history_manager.py` | 注入历史记录管理 |

---

## 环境变量

```bash
VLM_API_KEY=sk-xxx           # VLM API 密钥（必需）
VLM_API_URL=https://...      # VLM API 端点
VLM_MODEL=gpt-4o             # VLM 模型名称
STRUCTURE_MODEL=qwen-vl-max  # 结构提取模型
DASHSCOPE_API_KEY=sk-xxx     # DashScope（可选，用于 AI 图像生成）
OMNIPARSER_DEVICE=cuda       # OmniParser 设备
```

---

## 故障排查

| 问题 | 解决方案 |
|------|----------|
| OmniParser 导入失败 | `cd ../third_party/OmniParser && pip install -r requirements.txt` |
| VLM API 超时 | 检查网络连接，增加脚本中的 `timeout=180` |
| CUDA 内存不足 | 使用 `--omni-device cpu` |
| meta.json 字段缺失 | 使用 `generate_meta.py --force --run` 重新生成 |
| dialog_bounds_px 不准 | 使用 `python -m analysis.gt_bounds --force` 重新提取 |
| 批量执行报错某个样本 | 查看 `*_pipeline_meta_*.json` 中的错误日志 |
| 弹窗背景不是纯黑色 | 检查 `utils/semantic_dialog_generator.py` 提示词 |

---

## 性能指标

| 阶段 | 耗时 | 主要成本 |
|-----|------|--------|
| Stage 1 (OmniParser) | 10-30s | YOLO + OCR 推理 |
| Stage 2 (VLM 过滤) | 30-60s | API 调用 |
| Stage 3 (弹窗生成) | 20-40s | AI 图像生成 |
| Stage 3 (内容重复) | 10-30s | 组件裁剪 + 浮层合成 |
| **总计** | **60-130s** | - |

优化建议：
- 使用 GPU 加速 Stage 1（`--omni-device cuda`）
- 缓存 Stage 1 结果，避免重复检测
- 批量处理时共享 VLM 连接

---

**最后更新**: 2026-03-16
