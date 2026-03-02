# ui_semantic_patch

UI 语义补丁驱动的受控生成架构，通过 VLM 输出修改逻辑（JSON Patch），结合算法驱动的渲染引擎实现像素级受控编辑。

## 核心思想

**"逻辑层修改 + 物理层绘制"** 的解耦架构：
- VLM 充当 "UI 设计师" → 输出修改指令（JSON Patch）
- 渲染引擎充当 "绘图员" → 执行像素级修改

## 与 img2text2html2img 的区别

| 维度 | img2text2html2img | ui_semantic_patch |
|------|-------------------|-------------------|
| 输入 | 截图 | 截图 |
| 中间表示 | 自然语言描述 | UI-JSON + JSON Patch |
| 渲染方式 | HTML 全页面重建 | 局部像素修改 |
| 文字渲染 | 浏览器字体 | 系统字体引擎直接绘制 |
| 适用场景 | UI 复刻/原型 | 异常场景生成/测试 |

## 技术架构

采用 **OmniParser + VLM 融合模式**，结合本地精确检测与云端语义理解：

| 阶段 | 技术 | 说明 |
|------|------|------|
| Stage 1 | OmniParser | YOLO + PaddleOCR + Florence2 精确检测 |
| Stage 2 | VLM | 语义过滤，合并海报/卡片内的文字 |
| Stage 3 | PIL/AI | 异常场景渲染（弹窗/加载/内容重复） |

## 流程

```
原始截图
    │
    ▼ [Stage 1] OmniParser 粗检测
    │           YOLO + PaddleOCR + Florence2
    │           输出: *_stage1_omni_raw_*.json + *_stage1_annotated_*.png
    │
    ▼ [Stage 2] VLM 语义过滤
    │           合并海报/卡片内的文字，过滤噪声
    │           输出: *_stage2_filtered_*.json + *_stage2_annotated_*.png
    │
    ▼ [Stage 3] 异常场景渲染
    │           根据异常模式（dialog/area_loading/content_duplicate）生成异常场景
    │           输出: *_final_*.png + *_pipeline_meta_*.json
    │
异常场景截图 + 中间结果
```

**所有中间结果均保存，便于调试和优化。**

## 目录结构

```
ui_semantic_patch/
├── scripts/
│   ├── run_pipeline.py          # 主流水线入口（Stage 1→2→3）
│   ├── omni_extractor.py        # Stage 1: OmniParser UI 检测
│   ├── omni_vlm_fusion.py       # Stage 1+2: OmniParser + VLM 融合
│   ├── patch_renderer.py        # Stage 3: dialog 弹窗渲染引擎
│   ├── area_loading_renderer.py # Stage 3: area_loading 区域加载渲染
│   ├── content_duplicate_renderer.py  # Stage 3: content_duplicate 内容重复渲染
│   ├── text_overlay_renderer.py # Stage 3: text_overlay 文字覆盖编辑渲染
│   ├── visualize_omni.py        # 检测结果可视化（标注边界框）
│   ├── batch_pipeline.py        # 批量生成（原图 × GT 样本笛卡尔积）
│   ├── generate_meta.py         # VLM 驱动 meta.json 自动生成
│   ├── extract_gt_bounds.py     # OmniParser + IoU 精确提取弹窗边界框
│   ├── style_transfer.py        # 异常 UI 风格提取与迁移
│   ├── anomaly_sample_manager.py  # 异常样本聚类与 GT 模板导出
│   ├── generate_filename_descriptions.py  # 基于文件名的异常描述生成
│   ├── launch.sh                # Linux/macOS 一键启动脚本（交互式菜单）
│   ├── launch.bat               # Windows 一键启动脚本
│   ├── test_style_transfer.py   # 风格迁移测试
│   ├── test_integration_content_duplicate.py  # 内容重复集成测试
│   └── utils/
│       ├── __init__.py
│       ├── common.py                  # 公共工具（encode_image, extract_json, parse_color）
│       ├── semantic_dialog_generator.py  # 语义感知弹窗生成（DashScope AI + PIL）
│       ├── meta_loader.py             # GT 元数据加载与管理
│       ├── gt_manager.py              # GT 模板提取、风格分析、Few-shot 参考
│       ├── component_position_resolver.py  # UI-JSON 精确组件定位
│       └── reference_analyzer.py      # 参考图片风格分析
├── docs/
│   └── 技术实现文档.md          # 详细技术实现文档
├── data/
│   ├── 原图/                    # 原始 APP 截图
│   │   ├── app首页类-开屏广告弹窗/   # 携程旅行（2 张）
│   │   ├── 个人主页类-控件点击弹窗/   # 抖音（2 张）
│   │   ├── 外卖类优惠信息干扰/        # 饿了么（1 张）
│   │   └── 影视剧集类-内容歧义、重复/  # 腾讯视频（1 张）
│   └── Agent执行遇到的典型异常UI类型/
│       └── analysis/gt_templates/     # GT 模板
│           ├── 弹窗覆盖原UI/          # 8 个样本 + meta.json
│           ├── 内容歧义、重复/         # 1 个样本 + meta.json
│           └── loading_timeout/       # 1 个样本 + meta.json
├── third_party/
│   └── OmniParser/              # 本地集成 OmniParser
│       ├── omni_inference.py    # 推理引擎
│       ├── weights/             # 模型权重
│       └── util/                # 工具模块
├── assets/                      # 静态资源
├── examples/                    # 示例文件
│   └── 广告弹窗.jpg             # 参考弹窗样例
├── requirements.txt
├── .gitignore
└── README.md
```

## 依赖安装

### 1. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

核心依赖：
- `pillow` - 图像处理
- `requests` - HTTP 请求
- `python-dotenv` - 环境变量加载
- `dashscope` - AI 图像生成（可选，推荐安装）

### 2. 配置环境变量

项目需要 API 密钥来运行。配置步骤：

**Step 1：复制配置模板**
```bash
cd ../..  # 进入项目根目录
cp .env.example .env
```

**Step 2：编辑 .env 文件，填入实际密钥**
```bash
# .env 文件内容
VLM_API_KEY=your-actual-api-key
VLM_API_URL=https://api.openai-next.com/v1/chat/completions
VLM_MODEL=gpt-4o

# AI 图像生成（可选，但推荐配置用于高保真效果）
DASHSCOPE_API_KEY=your-dashscope-key
```

**Step 3：获取 API 密钥**

| 服务 | 用途 | 获取地址 |
|------|------|---------|
| VLM API | UI 分析、语义理解、风格提取 | [api.openai-next.com](https://api.openai-next.com) |
| DashScope | AI 图像生成（高保真弹窗和加载图标） | [阿里云 DashScope](https://dashscope.aliyun.com/) |

**优先级说明**：
- 脚本优先使用 `VLM_API_KEY` 环境变量
- 若环境变量未设置，会尝试使用命令行参数 `--api-key`
- 若都未设置，脚本会报错提示配置 .env 文件

### OmniParser 集成（必需）

OmniParser 提供精确的本地 UI 结构提取：

```bash
# OmniParser 已集成在项目内部
# ui_semantic_patch/
# └── third_party/
#     └── OmniParser/        # 本地集成

# 安装 OmniParser 依赖
cd third_party/OmniParser
pip install -r requirements.txt

# 下载模型权重
huggingface-cli download microsoft/OmniParser-v2.0 --local-dir weights
mv weights/icon_caption weights/icon_caption_florence
```

## 快速开始

### 环境检查

确保已配置 `.env` 文件：
```bash
# 检查环境变量是否生效
python -c "import os; from dotenv import load_dotenv; load_dotenv('../../.env'); print('API Key:', os.getenv('VLM_API_KEY')[:20] + '...' if os.getenv('VLM_API_KEY') else 'NOT SET')"
```

### 基本用法

**1. 全屏弹窗模式（默认）**
```bash
python scripts/run_pipeline.py \
  --screenshot ./page.png \
  --instruction "模拟网络超时弹窗" \
  --output ./output/
```

**2. 区域加载模式**
```bash
# 智能推荐目标区域
python scripts/run_pipeline.py \
  --screenshot ./page.png \
  --instruction "模拟列表加载超时" \
  --anomaly-mode area_loading \
  --output ./output/

# 使用参考加载图标（推荐！显著提升生成真实性）
python scripts/run_pipeline.py \
  --screenshot ./page.png \
  --instruction "模拟列表加载超时" \
  --anomaly-mode area_loading \
  --reference-icon ./reference_loading_icon.png \
  --output ./output/
```

**3. 内容重复模式**
```bash
python scripts/run_pipeline.py \
  --screenshot ./腾讯视频.jpg \
  --instruction "选集控件处显示重复列表" \
  --anomaly-mode content_duplicate \
  --output ./output/
```

**4. 文字覆盖编辑模式**
```bash
python scripts/run_pipeline.py \
  --screenshot ./携程旅行01.jpg \
  --instruction "在租车服务卡片中插入优惠信息：订阅该服务，机票满500减200元" \
  --anomaly-mode text_overlay \
  --output ./output/
```

### 指定 GPU/CPU

```bash
python scripts/run_pipeline.py \
  --screenshot ./page.png \
  --instruction "模拟网络超时弹窗" \
  --omni-device cuda \
  --output ./output/
```

### 输出结果

执行后在输出目录生成：

```
output/
├── page_stage1_omni_raw_20240101_120000.json    # OmniParser 原始检测结果
├── page_stage1_annotated_20240101_120000.png     # Stage 1 检测可视化
├── page_stage2_filtered_20240101_120000.json     # VLM 语义过滤后
├── page_stage2_annotated_20240101_120000.png     # Stage 2 过滤可视化
├── page_final_20240101_120000.png                # 最终异常截图
└── page_pipeline_meta_20240101_120000.json       # 流水线元数据
```

## 渲染模式

弹窗渲染引擎（`patch_renderer.py`）内部支持两种渲染模式：

| 模式 | 说明 |
|------|------|
| **semantic_ai** | 语义感知 + DashScope AI 图像生成（当前默认，最逼真） |
| semantic_pil | 语义感知 + PIL 纯算法绘制（无需 DashScope，作为回退方案） |

> **注意**：渲染模式当前在代码中硬编码为 `semantic_ai`，未暴露为命令行参数。若 DashScope API 不可用，会自动回退到 PIL 绘制。

### 语义感知弹窗生成

根据页面内容自动生成符合场景的弹窗内容：

```bash
python scripts/run_pipeline.py \
  --screenshot ./train_ticket_page.png \
  --instruction "生成余票为0的弹窗"
```

语义感知功能会：
- 自动识别页面类型（火车票/电商/视频/金融等）
- 生成符合场景的弹窗内容（如火车票页面 → "余票不足"弹窗）
- 从页面提取关键信息融入弹窗文案

### 参考图片风格学习

使用参考弹窗图片，生成相似风格的弹窗：

```bash
python scripts/run_pipeline.py \
  --screenshot ./page.png \
  --instruction "生成广告弹窗" \
  --reference ./examples/广告弹窗.jpg
```

**从参考图学习的特征：**

| 特征 | 说明 |
|------|------|
| 相对位置 | 弹窗在屏幕中的位置比例 |
| 尺寸比例 | 宽度/高度占屏幕的比例 |
| 按钮样式 | 颜色、圆角、位置 |
| 关闭按钮 | 位置、样式（右上角外侧白色圆形） |
| 阴影效果 | 投影大小和模糊程度 |

### GT 模板驱动生成（推荐）

使用真实异常截图 meta.json 驱动生成，效果最接近原生：

```bash
# dialog 模式 + GT 模板
python scripts/run_pipeline.py \
  --screenshot ./page.png \
  --instruction "生成优惠券弹窗" \
  --gt-category "弹窗覆盖原UI" \
  --gt-sample "弹出广告.jpg"

# content_duplicate 模式 + GT 模板
python scripts/run_pipeline.py \
  --screenshot ./腾讯视频.jpg \
  --instruction "剧集控件处显示重复列表" \
  --anomaly-mode content_duplicate \
  --gt-category "内容歧义、重复" \
  --gt-sample "部分信息重复.jpg"
```

**渲染优先级**：GT模板 > 大模型生成 > PIL绘制

### 批量生成

```bash
# 预览执行计划
python scripts/batch_pipeline.py \
  --input-dir data/原图/app首页类-开屏广告弹窗 \
  --gt-category "弹窗覆盖原UI"

# 实际执行
python scripts/batch_pipeline.py \
  --input-dir data/原图/app首页类-开屏广告弹窗 \
  --gt-category "弹窗覆盖原UI" \
  --output scripts/batch_output \
  --run
```

### 一键启动

```bash
# 交互式菜单
cd scripts
bash launch.sh          # Linux/macOS
launch.bat              # Windows

# 直接运行
bash launch.sh single   # 单图模式
bash launch.sh batch    # 批量预览
bash launch.sh list     # 列出异常类别
```

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--screenshot, -s` | 原始截图路径 | （必需） |
| `--instruction, -i` | 异常指令 | （必需） |
| `--output, -o` | 输出目录 | `./output` |
| `--api-key` | VLM API 密钥 | 从 `VLM_API_KEY` 环境变量读取 |
| `--api-url` | VLM API 端点 | 从 `VLM_API_URL` 环境变量读取 |
| `--structure-model` | 结构提取/语义过滤模型 | 从 `STRUCTURE_MODEL` 环境变量读取 |
| `--vlm-model` | VLM 模型名称 | 从 `VLM_MODEL` 环境变量读取 |
| `--anomaly-mode` | 异常模式：`dialog` / `area_loading` / `content_duplicate` / `text_overlay` | `dialog` |
| `--target-component` | 目标组件 ID（area_loading 模式） | 自动推荐 |
| `--reference, -r` | 参考弹窗图片路径（dialog 模式） | - |
| `--reference-icon` | 参考加载图标路径（area_loading 模式，推荐！） | - |
| `--gt-dir` | GT样本目录 | - |
| `--gt-category` | GT 模板类别名（如"弹窗覆盖原UI"） | - |
| `--gt-sample` | GT 模板样本文件名（如"弹出广告.jpg"） | - |
| `--omni-device` | OmniParser 设备 (`cuda`/`cpu`) | 从 `OMNIPARSER_DEVICE` 环境变量读取 |
| `--no-visualize` | 禁用检测结果可视化 | False |

## 异常渲染机制

当前实现中，异常场景通过模式专用渲染器直接生成，而非通过中间 JSON Patch 文件：

| 异常模式 | 渲染器 | 机制 |
|---------|--------|------|
| `dialog` | `patch_renderer.py` | VLM 语义分析 + PIL/AI 弹窗合成叠加 |
| `area_loading` | `area_loading_renderer.py` | VLM 推荐目标区域 + Loading 图标覆盖 |
| `content_duplicate` | `content_duplicate_renderer.py` | 检测重复区域 + 底部浮层扩展渲染 |
| `text_overlay` | `text_overlay_renderer.py` | VLM 编辑规划 + PIL 局部文字精确绘制（insert_text / replace_region / modify_text / add_badge） |

每个渲染器接收 Stage 2 输出的 UI-JSON 组件列表和用户指令，直接在原图上进行像素级修改。

> **设计说明**：项目名称中的 "Patch" 体现的是 **语义层面的修改逻辑**（对 UI 结构的局部修改），而非字面的 JSON Patch 文件格式。

## 技术说明

### 为什么不用 Diffusion 重绘全图？

1. **文字清晰度**：字体引擎渲染 vs 像素生成，前者无乱码/模糊
2. **可控性**：局部修改可精确控制，全图重绘不可预测
3. **效率**：局部修改远快于全图生成
4. **一致性**：与 Native 原生效果高度一致

### 融合模式的优势

解决 OmniParser 的语义理解局限：

| 问题 | 说明 | 解决方案 |
|------|------|----------|
| 海报内文字 | YOLO 会检测海报内的装饰文字 | VLM 识别整体语义，合并为 ImageView |
| 卡片内元素 | 多个元素被分别检测 | VLM 合并为单个 Card 组件 |
| 重复检测 | OCR 和 YOLO 重复检测 | VLM 去重，保留更合理的结果 |

### 渲染技术栈

| 操作 | 技术 |
|------|------|
| 弹窗叠加 | PIL 绘制 / DashScope AI 生成 + Alpha 通道合成 |
| 遮罩层 | 半透明背景填充 + 高斯模糊 |
| 文字绘制 | PIL ImageFont 系统字体引擎 |
| 边缘处理 | 抗锯齿 + 羽化过渡 |

## 异常场景示例

| 指令 | 模式 | 预期效果 |
|------|------|---------|
| "模拟网络超时弹窗" | dialog | 添加错误弹窗 + 禁用按钮 |
| "显示登录失败提示" | dialog | Toast 提示 + 清空密码框 |
| "生成优惠券广告弹窗" | dialog | 优惠券弹窗 + 半透明遮罩 |
| "模拟列表加载超时" | area_loading | Loading 图标 + 区域遮罩 |
| "选集控件处显示重复列表" | content_duplicate | 底部浮层 + 扩展内容 |
| "模拟底部信息重复显示" | content_duplicate | 复制组件到底部浮层 |
| "在租车卡片中插入优惠信息" | text_overlay | 局部插入文字，区域外像素不变 |
| "将价格从299修改为199" | text_overlay | 原地替换已有文字 |

## 语义感知场景支持

自动识别以下页面类型，生成符合场景的弹窗：

| 页面类型 | 关键词识别 | 典型弹窗 |
|---------|-----------|---------|
| 火车票/机票 | 火车票、机票、余票、12306、携程 | 余票不足、票价变动、抢票失败 |
| 电商购物 | 购物车、商品、价格、淘宝、京东 | 库存不足、优惠券弹窗、限时抢购 |
| 视频/音乐 | 视频、VIP、会员、抖音、B站 | VIP会员推荐、版权提示、广告弹窗 |
| 金融支付 | 余额、支付、转账、银行卡 | 支付失败、余额不足、安全验证 |
| 登录注册 | 登录、注册、密码、验证码 | 登录过期、认证失败、账号锁定 |
| 社交聊天 | 好友、消息、朋友圈、微信 | 好友请求、隐私提醒、权限申请 |
| 网络异常 | 网络、加载、刷新、超时 | 网络错误、请求超时、服务器错误 |

## 实施路线

### Phase 1 ✅
- [x] 项目骨架搭建
- [x] VLM 结构提取（img2xml）
- [x] 文本局部重绘工具
- [x] 基础 VLM Patch 生成
- [x] 一键执行流程

### Phase 2 ✅
- [x] OmniParser + VLM 融合模式
- [x] 语义感知弹窗生成
- [x] 参考图片风格学习
- [x] 增强 PIL 弹窗渲染
- [x] AI 图像直接生成模式
- [x] 中间结果全保存
- [x] GT 模板驱动生成（meta.json）
- [x] 内容重复异常模式 (content_duplicate)
- [x] 文字覆盖编辑模式 (text_overlay)
- [x] 批量生成流水线 (batch_pipeline)
- [x] 一键启动脚本 (launch.sh / launch.bat)
- [x] VLM 驱动 meta.json 自动生成
- [x] 精确边界框提取 (extract_gt_bounds)
- [x] 风格迁移与样本管理工具
- [x] 原图数据集（4 类 6 张）
- [x] GT 模板扩展（3 类 10 个样本）
- [ ] 组件库积累（弹窗、Toast 模板）
- [ ] 高级 Inpainting（复杂背景）

### Phase 3
- [ ] ControlNet 辅助处理
- [ ] 样式库（Style-Library）
- [ ] 闭环验证与微调

## 方案优势

1. **无需设备**：纯截图输入，OmniParser + VLM 自动提取结构
2. **文字清晰度极致**：字体引擎渲染，彻底解决 VLM 乱码问题
3. **逻辑与视觉解耦**：可独立优化推理逻辑和视觉表现
4. **天然 Ground Truth**：JSON Patch 本身就是标签，可直接用于训练
5. **环境无关**：直接操作位图，不依赖 Webview
6. **可调试性强**：所有中间结果保存，便于问题定位
