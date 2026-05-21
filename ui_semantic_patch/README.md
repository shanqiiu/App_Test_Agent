# UI 语义补丁框架

**"逻辑层修改 + 物理层绘制"** 的解耦架构 — 通过 OmniParser 精确检测 + VLM 语义理解 + 程序化渲染，实现异常 UI 场景的自动生成。

---

## 技术架构

```
原始截图 → [Stage 1] OmniParser 粗检测 → [Stage 2] VLM 语义分组 → [Stage 3] 异常渲染 → 异常截图
              YOLO + PaddleOCR + Florence2     合并/过滤/语义分组       多模式专用渲染器
```


| 阶段      | 技术                                        | 输出                         |
| ------- | ----------------------------------------- | -------------------------- |
| Stage 1 | OmniParser (YOLO + PaddleOCR + Florence2) | `*_stage1_omni_raw_*.json` |
| Stage 2 | VLM 语义过滤与分组                               | `*_stage2_filtered_*.json` |
| Stage 3 | 模式专用渲染器                                   | `*_final_*.png`            |


所有中间结果均保存，便于调试和优化。

---

## 快速上手

### 环境准备

```bash
cp ../../.env.example ../../.env              # 填写 VLM_API_KEY、图像生成配置
pip install -r requirements.txt               # 核心依赖
pip install -r third_party/OmniParser/requirements.txt  # OmniParser（需 GPU 推荐）
```

推荐在 `.env` 中显式配置图像生成后端：

```env
# 图像生成后端：dashscope / huawei_mlops / local / auto
IMAGE_GEN_BACKEND=dashscope

# 【推荐】通用图像生成配置（兼容任意 OpenAI 格式 API）
IMAGE_GEN_API_KEY=your-key
IMAGE_GEN_API_URL=https://api.provider.com/v1
IMAGE_GEN_MODEL=your-model

# DashScope 专属配置（向后兼容）
DASHSCOPE_API_KEY=your-key
DASHSCOPE_IMAGE_GEN_MODEL=qwen-image-max
DASHSCOPE_IMAGE_EDIT_MODEL=qwen-image-edit-max

# 华为 MLOps 配置
HUAWEI_MLOPS_API_KEY=your-key
HUAWEI_MLOPS_API_URL=http://mlops.huawei.com/...
HUAWEI_MLOPS_MODEL=flux_txt_to_image

# 本地服务配置
LOCAL_IMAGE_API_URL=
LOCAL_IMAGE_API_STEPS=9
LOCAL_IMAGE_API_TIMEOUT=120
LOCAL_IMAGE_API_SEED=
```

**配置优先级说明：**
- `IMAGE_GEN_BACKEND=huawei_mlops`: 使用华为 MLOps 服务
- `IMAGE_GEN_BACKEND=dashscope`: 使用 DashScope SDK
- `IMAGE_GEN_BACKEND=local`: 使用本地文生图服务
- `IMAGE_GEN_BACKEND=auto`: 优先本地服务，未配置时回退到云端 API
- API Key 读取优先级：`IMAGE_GEN_API_KEY` → `DASHSCOPE_API_KEY`

### 异常模式示例

```bash
cd scripts

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

# 5. modify_text_ai — 基于组件区域的 AI 图像编辑文字替换
python run_pipeline.py \
  --screenshot ../data/Agent执行遇到的典型异常UI类型/analysis/gt_templates/弹窗覆盖原UI/12306无票弹窗.jpg \
  --instruction "将z112次车座位信息弹窗卡片第三列的硬卧、软卧车票席位状态改为灰色无票字样" \
  --anomaly-mode modify_text_ai \
  --output ./output/demo

# 5b. modify_text_ai — GT 样本 05.jpg（与仓库根目录 Claude.md 示例一致）
python run_pipeline.py \
  --screenshot ../data/Agent执行遇到的典型异常UI类型/analysis/gt_templates/弹窗覆盖原UI/05.jpg \
  --instruction "将z156次车座位信息弹窗卡片的硬卧席位右侧第三列的状态从有票改为灰色无票字样，预订按钮置灰" \
  --anomaly-mode modify_text_ai \
  --output ./output/12306无座_modify_text

# 6. modify_text_ocr / modify_text — OCR精定位 + PIL渲染文字替换
python run_pipeline.py \
  --screenshot ../data/Agent执行遇到的典型异常UI类型/analysis/gt_templates/弹窗覆盖原UI/12306无票弹窗.jpg \
  --instruction "将z112次车座位信息弹窗卡片第三列的硬卧、软卧车票席位状态改为灰色无票字样" \
  --anomaly-mode modify_text_ocr \
  --output ./output/demo

# 7. modify_text_e2e — 端到端图像编辑（跳过检测/分组）
# 默认是指令驱动粗裁剪编辑；加 --e2e-full-image 强制整图编辑
python run_pipeline.py \
  --screenshot ../data/Agent执行遇到的典型异常UI类型/analysis/gt_templates/弹窗覆盖原UI/12306无票弹窗.jpg \
  --instruction "将z112次车座位信息弹窗卡片第三列的硬卧、软卧车票席位状态改为灰色无票字样" \
  --anomaly-mode modify_text_e2e \
  --e2e-full-image \
  --output ./output/demo
```

### 切换图像生成后端

```bash
# 1. 使用 DashScope（阿里云）
IMAGE_GEN_BACKEND=dashscope
DASHSCOPE_API_KEY=your-key
DASHSCOPE_IMAGE_GEN_MODEL=qwen-image-max

# 2. 使用华为 MLOps（OpenAI 兼容格式）
IMAGE_GEN_BACKEND=huawei_mlops
HUAWEI_MLOPS_API_KEY=your-key
HUAWEI_MLOPS_API_URL=http://mlops.huawei.com/...
HUAWEI_MLOPS_MODEL=flux_txt_to_image

# 3. 使用本地文生图服务（适合部署在服务器）
IMAGE_GEN_BACKEND=local
LOCAL_IMAGE_API_URL=http://10.85.177.2:8042/generate

# 4. 自动模式：优先本地服务，未配置时回退到云端 API
IMAGE_GEN_BACKEND=auto
```

### 注入决策流水线

```bash
cd scripts

# 正常模式（需要 VLM + 生成模型 API）
python injection_pipeline.py \
  --input-dir ./examples/injection_demo \
  --output-dir ./output/injected \
  --interactive

# Mock 模式（仅需 VLM，跳过图像生成）
python injection_pipeline.py \
  --input-dir ./examples/injection_demo \
  --output-dir ./output/injected \
  --mock --no-interactive
```

### 一键启动

```bash
cd scripts
bash launch.sh              # 交互式菜单
bash launch.sh single       # 单图模式
bash launch.sh batch --run  # 批量模式
bash launch.sh list         # 列出异常类别
```

---

## 模块架构

```
┌─────────────────────────────────────────────────────────────┐
│                      run_pipeline.py                        │
│              batch_pipeline.py (批量入口)                    │
│          injection_pipeline.py (注入决策)                    │
│                        (主控层)                              │
└──────────────────┬──────────────────┬───────────────────────┘
                   │                  │
        ┌──────────▼──────────┐ ┌─────▼─────────────┐
        │     analysis/       │ │    injection/      │
        │ (Stage 1+2 AI感知)  │ │ (注入决策层)       │
        └──────────┬──────────┘ └─────┬─────────────┘
                   │                  │
        ┌──────────▼──────────────────▼───────┐
        │              renderers/              │
        │        (Stage 3 异常渲染层)           │
        └──────────────────┬──────────────────┘
                           │
        ┌──────────────────▼──────────────────┐
        │    utils/ + generators/ + tests/     │
        │   (工具库 + 元数据生成 + 测试)        │
        └─────────────────────────────────────┘
```


| 层级        | 模块                                     | 职责                            |
| --------- | -------------------------------------- | ----------------------------- |
| **主控**    | `run_pipeline.py`                      | 三阶段串联，单图入口                    |
|           | `batch_pipeline.py`                    | 批量执行（原图 × GT 笛卡尔积）            |
|           | `injection_pipeline.py`                | 注入决策流水线（操作序列分析）               |
| **AI 感知** | `analysis/omni_extractor.py`           | OmniParser 本地推理               |
|           | `analysis/omni_vlm_fusion.py`          | VLM 语义分组                      |
|           | `analysis/gt_bounds.py`                | GT 边界框精确提取                    |
|           | `analysis/visualize.py`                | 检测结果可视化                       |
| **异常渲染**  | `renderers/base.py`                    | 渲染器统一基类                       |
|           | `renderers/patch.py`                   | dialog 弹窗渲染                   |
|           | `renderers/area_loading.py`            | 区域加载异常                        |
|           | `renderers/content_duplicate.py`       | 内容重复                          |
|           | `renderers/text_overlay.py`            | 文字覆盖 + modify_text_ai/ocr/e2e |
| **注入决策**  | `injection/sequence_analyzer.py`       | 操作序列语义分析                      |
|           | `injection/anomaly_recommender.py`     | 异常推荐决策                        |
|           | `injection/sequence_rewriter.py`       | 序列改写                          |
|           | `injection/prompts.py`                 | VLM 提示词模板                     |
|           | `injection/mock_provider.py`           | Mock 模式（内网离线测试）               |
| **元数据**   | `generators/meta.py`                   | meta.json 自动生成                |
|           | `generators/filename_descriptions.py`  | 文件名描述生成                       |
| **工具库**   | `utils/common.py`                      | 图片编码、JSON 提取                  |
|           | `utils/meta_loader.py`                 | GT 元数据加载                      |
|           | `utils/component_position_resolver.py` | 组件定位                          |
|           | `utils/semantic_dialog_generator.py`   | 弹窗生成器（支持 DashScope / 本地服务切换） |
|           | `utils/history_manager.py`             | 注入历史记录管理                      |


> 当前以仓库根目录的 [docs/architecture.md](../docs/architecture.md) 和 [docs/mapping-generation.md](../docs/mapping-generation.md) 为准。

---

## 目录结构

```
ui_semantic_patch/
├── scripts/
│   ├── run_pipeline.py                # 三阶段主流水线
│   ├── batch_pipeline.py              # 批量生成
│   ├── injection_pipeline.py          # 注入决策流水线
│   ├── generate_meta.py               # meta.json 生成
│   ├── generate_instructions.py       # 测试指令生成
│   ├── launch.sh                      # 一键启动
│   ├── analysis/                      # AI 感知层
│   │   ├── omni_extractor.py          #   OmniParser 推理
│   │   ├── omni_vlm_fusion.py         #   VLM 语义分组
│   │   ├── gt_bounds.py               #   GT 边界框提取
│   │   └── visualize.py               #   检测结果可视化
│   ├── renderers/                     # 异常渲染层
│   │   ├── base.py                    #   渲染器基类
│   │   ├── patch.py                   #   dialog 弹窗
│   │   ├── area_loading.py            #   区域加载
│   │   ├── content_duplicate.py       #   内容重复
│   │   └── text_overlay.py            #   文字覆盖
│   ├── generators/                    # 元数据生成层
│   │   ├── meta.py                    #   meta.json 生成
│   │   └── filename_descriptions.py   #   文件名描述
│   ├── injection/                     # 注入决策层
│   │   ├── sequence_analyzer.py       #   操作序列分析
│   │   ├── anomaly_recommender.py     #   异常推荐
│   │   ├── sequence_rewriter.py       #   序列改写
│   │   ├── prompts.py                 #   VLM 提示词
│   │   ├── mock_provider.py           #   Mock 模式实现
│   │   └── mock_config_example.json   #   Mock 配置示例
│   ├── utils/                         # 工具库
│   │   ├── common.py
│   │   ├── semantic_dialog_generator.py
│   │   ├── meta_loader.py
│   │   ├── component_position_resolver.py
│   │   ├── gt_manager.py
│   │   ├── reference_analyzer.py
│   │   ├── anomaly_sample_manager.py
│   │   └── history_manager.py
│   └── tests/                         # 测试
│       ├── test_api_auth.py
│       └── test_qwen_image_open.py
├── data/
│   ├── 原图/                          # 原始 APP 截图（5 类 11 张）
│   │   ├── app首页类-开屏广告弹窗/     #   5 张
│   │   ├── 个人主页类-控件点击弹窗/     #   2 张
│   │   ├── 外卖类优惠信息干扰/         #   2 张
│   │   ├── 影视剧集类-内容歧义、重复/   #   1 张
│   │   └── 订票优惠编辑/               #   2 张
│   ├── Agent执行遇到的典型异常UI类型/  # GT 模板（3 类 16 个样本）
│   │   └── analysis/gt_templates/
│   │       ├── 弹窗覆盖原UI/           #   14 个样本
│   │       ├── 内容歧义、重复/          #   1 个样本
│   │       ├── loading_timeout/        #   1 个样本
│   │       ├── dialogs/                #   预留
│   │       ├── loadings/               #   预留
│   │       └── toasts/                 #   预留
│   └── scenarios/                     # 业务场景配置
│       └── flight_booking/
├── examples/                          # 示例文件
│   └── injection_demo/                # 注入流水线示例输入
├── third_party/OmniParser/            # 本地集成
├── requirements.txt
└── README.md
```

---

## 命令行参数速查

### run_pipeline.py


| 参数                  | 说明                                                                                                                                          | 默认值        |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| `--screenshot, -s`  | 原始截图路径                                                                                                                                      | 必需         |
| `--instruction, -i` | 异常指令                                                                                                                                        | 必需         |
| `--output, -o`      | 输出目录                                                                                                                                        | `./output` |
| `--anomaly-mode`    | `dialog` / `area_loading` / `content_duplicate` / `text_overlay` / `modify_text` / `modify_text_ai` / `modify_text_ocr` / `modify_text_e2e` | `dialog`   |
| `--gt-category`     | GT 模板类别                                                                                                                                     | -          |
| `--gt-sample`       | GT 模板样本                                                                                                                                     | -          |
| `--reference, -r`   | 参考弹窗图片                                                                                                                                      | -          |
| `--reference-icon`  | 参考加载图标                                                                                                                                      | -          |
| `--edit-plan`       | 文本编辑模式使用预设 Edit Plan JSON                                                                                                                   | -          |
| `--e2e-full-image`  | `modify_text_e2e` 下启用整图端到端编辑                                                                                                                | `False`    |
| `--fonts-dir`       | 自定义字体目录                                                                                                                                     | 系统默认       |
| `--omni-device`     | OmniParser 设备 (`cuda`/`cpu`)                                                                                                                | 环境变量       |
| `--api-key`         | VLM API 密钥                                                                                                                                  | 环境变量       |


### injection_pipeline.py


| 参数                                   | 说明                                   | 默认值   |
| ------------------------------------ | ------------------------------------ | ----- |
| `--input-dir`                        | 输入目录（含 `task.json` + `screenshots/`） | 必需    |
| `--output-dir`                       | 输出目录                                 | 必需    |
| `--interactive` / `--no-interactive` | 是否启用用户确认                             | True  |
| `--mock`                             | Mock 模式（跳过图像生成）                      | False |
| `--mock-config`                      | Mock 配置文件路径                          | 内置默认  |
| `--max-history`                      | 最大历史步数                               | 10    |
| `--min-steps`                        | 最少分析步数后才考虑注入                         | 2     |


---

## 输出文件说明


| 文件模式                       | 说明              | 生成阶段    |
| -------------------------- | --------------- | ------- |
| `*_stage1_omni_raw_*.json` | OmniParser 原始检测 | Stage 1 |
| `*_stage1_annotated_*.png` | Stage 1 可视化     | Stage 1 |
| `*_stage2_filtered_*.json` | VLM 语义过滤后       | Stage 2 |
| `*_stage2_annotated_*.png` | Stage 2 可视化     | Stage 2 |
| `diff_*.png`               | 编辑像素差异可视化       | Stage 3 |
| `edit_plan_*.json`         | 文本编辑执行计划        | Stage 3 |
| `*_final_*.png`            | 最终异常截图          | Stage 3 |
| `*_pipeline_meta_*.json`   | 流水线元数据          | 完成时     |


---

## 实施路线

### Phase 1 - POC ✅

- OmniParser + VLM 融合模式
- 语义感知弹窗生成、参考图风格学习

### Phase 2 - 工具链 ✅

- 基础四种模式（dialog / area_loading / content_duplicate / text_overlay）+ 文字编辑系列（`modify_text*`）
- GT 模板驱动、批量生成、一键启动
- 架构重构：analysis / renderers / generators / injection 子包
- 注入决策流水线（含 Mock 模式）
- 图像生成后端切换（DashScope / 本地服务 / 自动回退）
- 测试指令批量生成

### Phase 3 - 待实施

- ControlNet 精细控制
- 样式库（Style-Library）
- 闭环验证与微调

---

## 技术说明

### 为什么不用 Diffusion 重绘全图？

1. **文字清晰度** — 字体引擎渲染无乱码/模糊
2. **可控性** — 局部修改精确可控
3. **效率** — 远快于全图生成
4. **一致性** — 与 Native 原生效果高度一致

### 融合模式解决了什么？


| 问题    | 说明            | 解决方案              |
| ----- | ------------- | ----------------- |
| 海报内文字 | YOLO 检测海报装饰文字 | VLM 合并为 ImageView |
| 卡片内元素 | 多个元素被分别检测     | VLM 合并为 Card      |
| 重复检测  | OCR 和 YOLO 重复 | VLM 去重            |


### 图像生成后端选择


| 后端 | 配置 | 适用场景 | API 格式 |
| ---- | ---- | ---- | ---- |
| `dashscope` | `IMAGE_GEN_BACKEND=dashscope` | 阿里云 DashScope | 阿里云 SDK |
| `huawei_mlops` | `IMAGE_GEN_BACKEND=huawei_mlops` | 华为 MLOps 服务 | OpenAI 兼容 |
| `local` | `IMAGE_GEN_BACKEND=local` | 本地 Stable Diffusion 服务 | 自定义 HTTP |
| `auto` | `IMAGE_GEN_BACKEND=auto` | 自动选择（本地优先） | - |

**配置优先级（自动回退）：**
```
IMAGE_GEN_API_KEY → DASHSCOPE_API_KEY
IMAGE_GEN_API_URL → DASHSCOPE_API_URL
IMAGE_GEN_MODEL  → DASHSCOPE_IMAGE_GEN_MODEL
```

**各后端详细配置：**

```bash
# 1. DashScope（阿里云）
IMAGE_GEN_BACKEND=dashscope
DASHSCOPE_API_KEY=sk-xxx
DASHSCOPE_IMAGE_GEN_MODEL=qwen-image-max  # 文生图
DASHSCOPE_IMAGE_EDIT_MODEL=qwen-image-edit-max  # 图生图

# 2. 华为 MLOps（OpenAI 兼容格式）
IMAGE_GEN_BACKEND=huawei_mlops
HUAWEI_MLOPS_API_KEY=sk-xxx
HUAWEI_MLOPS_API_URL=http://mlops.huawei.com/...
HUAWEI_MLOPS_MODEL=flux_txt_to_image
HUAWEI_MLOPS_TIMEOUT=120

# 3. 本地服务
IMAGE_GEN_BACKEND=local
LOCAL_IMAGE_API_URL=http://10.85.177.2:8042/generate
LOCAL_IMAGE_API_STEPS=9
LOCAL_IMAGE_API_TIMEOUT=120

# 4. 通用配置（兼容任意 OpenAI 格式 API）
IMAGE_GEN_API_KEY=your-key
IMAGE_GEN_API_URL=https://api.provider.com/v1
IMAGE_GEN_MODEL=your-model
```

补充说明：

- DashScope 纯文生图模型由 `DASHSCOPE_IMAGE_GEN_MODEL` 控制，默认 `qwen-image-max`
- DashScope 图像编辑模型由 `DASHSCOPE_IMAGE_EDIT_MODEL` 控制，默认 `qwen-image-edit-max`
- 华为 MLOps 响应格式：`choices[0].message.content` (base64)
- `modify_text_ai` / `modify_text_e2e` 这类带参考图的编辑路径会优先使用编辑模型
- `dialog` 主路径会统一读取 `IMAGE_GEN_BACKEND`，不再通过 `--image-model` 切换


---

### 细粒度编辑模式建议


| 场景          | 推荐模式                                     | 说明                |
| ----------- | ---------------------------------------- | ----------------- |
| 结构稳定、组件可定位  | `modify_text_ai` / `modify_text_ocr`     | 依赖检测与分组，局部可控性更强   |
| 细粒度文本且检测难覆盖 | `modify_text_e2e --e2e-full-image`       | 跳过检测/分组，直接整图端到端编辑 |
| 希望降低整图重绘风险  | `modify_text_e2e`（不加 `--e2e-full-image`） | 指令驱动粗裁剪后编辑并贴回     |


---

**最后更新**: 2026-05-07
**文档同步**: 简版与详版命令以仓库根目录 [Claude.md](../../Claude.md) 交叉对齐。

### 最近更新

**2026-05-07**: 新增华为 MLOps 图像生成后端支持
- 新增 `IMAGE_GEN_BACKEND=huawei_mlops` 选项
- 新增通用 `IMAGE_GEN_*` 配置变量，兼容任意 OpenAI 格式 API
- 完善配置回退机制，向后兼容 `DASHSCOPE_*` 配置
