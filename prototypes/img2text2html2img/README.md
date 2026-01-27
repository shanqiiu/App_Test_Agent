# img2text2html2img

UI 截图复刻工具链，将手机 App 截图转换为 HTML/CSS，再渲染回图片进行对比。

## 架构概览

```
原始截图 (.png/.jpg)
    │
    ├─────────────────────────────────┐
    │                                 │
    ▼                                 ▼
[OmniParser]                    [VL 模型]
UI组件检测 + OCR                 语义理解
    │                                 │
    ▼                                 ▼
精确边界框 (.json)              语义描述 (.txt)
{                               [搜索框] 圆角设计
  "components": [                 有放大镜图标...
    {"type": "search",
     "bbox": [16,120,359,170],
     "text": "搜索"}
  ]
}
    │                                 │
    └────────────┬────────────────────┘
                 │
                 ▼
           [融合模块]
      边界框 + 语义 → 增强描述
                 │
                 ▼
         text2html.py (LLM)
                 │
                 ▼
         HTML/CSS (.html)
                 │
                 ▼
         html2img.py (Playwright)
                 │
                 ▼
         复刻图片 (.png)
```

### 两种工作模式

| 模式 | 说明 | 精度 | 速度 |
|------|------|------|------|
| **精确模式** | OmniParser + VL 融合 | 高（像素级定位） | 较慢 |
| **快速模式** | 仅 VL 模型（原有流程） | 中（估算定位） | 较快 |

## 目录结构

```
img2text2html2img/
├── scripts/
│   ├── ui_detector.py       # UI组件检测（多后端支持）
│   ├── omniparser_adapter.py # [NEW] OmniParser 输出适配器
│   ├── img2text.py          # 图片 → 描述文本（支持边界框融合）
│   ├── text2html.py         # 描述文本 → HTML
│   ├── html2img.py          # HTML → 图片
│   ├── pipeline.py          # 端到端流水线
│   ├── parse_json/          # OmniParser 原始解析结果
│   ├── outputs/             # 生成的描述文本
│   │   ├── *.txt            # UI描述文本
│   │   └── *.json           # 元数据 + 检测结果
│   ├── dist_html/           # 生成的HTML文件
│   └── output_images/       # 最终渲染的图片
├── .gitignore
└── README.md
```

## 依赖安装

### 基础依赖

```bash
pip install pillow requests playwright openai
playwright install chromium
```

### OmniParser（精确模式）

```bash
# 方式1: pip 安装
pip install omniparser-v2

# 方式2: 从源码安装
git clone https://github.com/microsoft/OmniParser.git
cd OmniParser
pip install -e .
```

**OmniParser 模型下载**：

```bash
# 下载预训练模型（约 2GB）
python -c "from omniparser import OmniParser; OmniParser(download=True)"
```

## 使用方法

### 1. UI 组件检测

支持多种检测后端，推荐使用预解析的 JSON 文件（无需安装额外依赖）。

#### 方式 A：使用预解析的 JSON 文件（推荐）

如果已有 OmniParser 的解析结果（如 `parse1.json`），可直接使用适配器转换：

```bash
# 转换 OmniParser 原始输出为框架格式
python scripts/omniparser_adapter.py \
  --input ./scripts/parse_json/parse1.json \
  --image ./test.jpg \
  --output ./scripts/outputs/test_detection.json

# 或在检测器中直接使用
python scripts/ui_detector.py \
  --image-path ./test.jpg \
  --detector omniparser_raw \
  --json-path ./scripts/parse_json/parse1.json
```

**OmniParser 原始格式**（归一化坐标 0-1）：

```json
[
  {"id": 0, "type": "text", "bbox": [0.1, 0.2, 0.3, 0.4], "content": "文本", "interactivity": false},
  {"id": 1, "type": "icon", "bbox": [0.5, 0.6, 0.7, 0.8], "content": "图标描述", "interactivity": true}
]
```

#### 方式 B：实时检测（需安装 OmniParser）

```bash
python scripts/ui_detector.py \
  --image-path ./test.jpg \
  --output-dir ./scripts/outputs \
  --detector omniparser
```

**框架统一格式** (`*_detection.json`)：

```json
{
  "image_size": [1080, 2340],
  "components": [
    {
      "id": 0,
      "type": "text",
      "bbox": [108, 480, 324, 960],
      "bbox_normalized": [0.1, 0.2, 0.3, 0.4],
      "text": "搜索商品",
      "interactivity": false,
      "confidence": 0.90,
      "source": "box_ocr_content_ocr"
    }
  ],
  "statistics": {
    "total_components": 74,
    "interactive_count": 48,
    "type_distribution": {"text": 26, "icon": 48}
  }
}
```

**支持的检测器**：

| 检测器 | 说明 | 依赖 |
|--------|------|------|
| `omniparser_raw` | 加载预解析 JSON（推荐） | 无 |
| `omniparser` | OmniParser 实时检测 | omniparser-v2 |
| `mock` | 模拟检测器（测试用） | 无 |

**支持的组件类型**：

| 类型 | 说明 | 可交互 |
|------|------|--------|
| `text` | 文本标签 | 否 |
| `icon` | 图标/按钮 | 是 |
| `button` | 按钮 | 是 |
| `input` | 输入框 | 是 |
| `image` | 图片 | 否 |

### 2. 图片转描述文本（增强版）

使用 VL 模型分析截图，结合检测结果生成增强描述。

```bash
# 精确模式（推荐）：使用检测结果
python scripts/img2text.py \
  --image-path ./test.jpg \
  --detection-file ./scripts/outputs/test_detection.json \
  --output-dir ./scripts/outputs

# 快速模式：仅使用 VL 模型
python scripts/img2text.py \
  --image-path ./test.jpg \
  --output-dir ./scripts/outputs
```

**增强描述格式**（精确模式）：

```
# UI Description (Enhanced)
# Resolution: 1080 x 2340
# Detection: OmniParser v2
# Model: qwen-vl-max

[搜索框] bbox:[16,120,359,170] 尺寸:343x50px
  ├─ 背景: #F5F5F5 圆角:25px
  ├─ (L) icon:放大镜 bbox:[24,130,44,150] 颜色:#999
  └─ (C) placeholder:「搜索商品」字号:14px 颜色:#999

[功能区] bbox:[0,180,1080,400] 尺寸:1080x220px
  ├─ 布局: grid_5x2 间距:12px
  ├─ 按钮1: bbox:[16,180,200,290] bg:#FF6B00 radius:12px
  │    └─ 「外卖」字号:14px 颜色:#FFF
  ...
```

### 3. 描述文本转 HTML

LLM 根据增强描述生成精确定位的 HTML/CSS。

```bash
python scripts/text2html.py \
  --input-file ./scripts/outputs/test_20260123_115829.txt \
  --output-dir ./scripts/dist_html
```

**特性**：
- 精确模式下使用绝对定位（`position: absolute`）
- 快速模式下使用 Flexbox/Grid 布局
- 支持 Font Awesome 图标（CDN）
- 3次重试机制（指数退避）

### 4. HTML 转图片

使用 Playwright 将 HTML 渲染为图片。

```bash
python scripts/html2img.py \
  -i ./scripts/dist_html/test_20260123_115829.html \
  -o ./scripts/output_images/
```

### 5. 端到端流水线

一键执行完整流程。

```bash
# 精确模式（含 OmniParser 检测）
python scripts/pipeline.py \
  -i ./test.jpg \
  -o ./pipeline_output \
  --mode precise

# 快速模式（跳过检测）
python scripts/pipeline.py \
  -i ./test.jpg \
  -o ./pipeline_output \
  --mode fast

# 批量处理 + 生成对比图
python scripts/pipeline.py \
  --input-dir ./screenshots \
  --mode precise \
  --compare
```

## 配置

### 环境变量

创建 `.env` 文件：

```bash
API_KEY=your_api_key
API_URL=https://api.openai-next.com/v1/chat/completions
VL_MODEL=qwen-vl-max
LLM_MODEL=qwen3-235b-a22b

# OmniParser 配置（可选）
OMNIPARSER_MODEL_PATH=/path/to/models
OMNIPARSER_DEVICE=cuda  # cuda / cpu
```

### 命令行参数

| 脚本 | 参数 | 说明 |
|------|------|------|
| omniparser_adapter.py | `--input` | OmniParser 原始 JSON |
| omniparser_adapter.py | `--image` | 原始图片（获取尺寸） |
| omniparser_adapter.py | `--format` | 输出格式（json/prompt） |
| ui_detector.py | `--detector` | 检测器类型 |
| ui_detector.py | `--json-path` | 预解析 JSON 路径 |
| ui_detector.py | `--device` | 推理设备（cuda/cpu） |
| img2text.py | `--detection-file` | 检测结果 JSON |
| img2text.py | `--model` | VL 模型名称 |
| text2html.py | `--model` | LLM 模型名称 |
| pipeline.py | `--mode` | 工作模式（precise/fast） |
| pipeline.py | `--compare` | 生成对比图 |

## 技术说明

### OmniParser 集成优势

| 维度 | 仅 VL 模型 | OmniParser + VL |
|------|------------|-----------------|
| **位置精度** | 估算（误差 10-50px） | 像素级精确 |
| **组件识别** | 依赖提示工程 | 自动检测分类 |
| **OCR 文本** | VL 模型识别 | 专用 OCR 引擎 |
| **嵌套结构** | 难以准确描述 | 层级关系清晰 |
| **处理速度** | 较快 | 增加检测耗时 |

### 为什么采用融合方案？

单独使用 OmniParser 或 VL 模型都有局限：

**OmniParser 局限**：
- 只提供边界框和类型，缺乏样式细节（颜色、圆角、渐变）
- 不理解组件的语义用途

**VL 模型局限**：
- 位置描述不精确（"大约"、"约30%"）
- 可能遗漏小组件

**融合方案**：
- OmniParser 提供精确的「在哪里」
- VL 模型提供丰富的「是什么样」
- 两者互补，提升整体复刻精度

### 技术栈

| 组件 | 技术 | 作用 |
|------|------|------|
| UI检测 | OmniParser v2 | 组件检测 + OCR |
| 图像理解 | Qwen VL | 语义分析 + 样式识别 |
| HTML生成 | Qwen LLM | 代码生成 |
| 图片渲染 | Playwright + Chromium | HTML → PNG |
| 图像处理 | Pillow | 对比图生成 |
| 图标资源 | Font Awesome (CDN) | 图标渲染 |

## 性能参考

| 阶段 | 耗时（单张 1080p） | 说明 |
|------|-------------------|------|
| OmniParser 检测 | 2-5s | GPU 推荐 |
| VL 模型分析 | 10-30s | 依赖 API 响应 |
| LLM 生成 HTML | 15-45s | 依赖 API 响应 |
| Playwright 渲染 | 1-2s | 本地执行 |
| **总计（精确模式）** | 30-80s | - |
| **总计（快速模式）** | 25-75s | 跳过检测 |

## 输出示例

```
pipeline_output/
├── descriptions/
│   ├── test_20260123_115829.txt        # 增强描述文本
│   ├── test_20260123_115829.json       # 元信息
│   └── test_20260123_115829_det.json   # 检测结果
├── html/
│   ├── test_20260123_115829.html       # 生成的 HTML
│   └── test_20260123_115829.json       # HTML 元信息
└── images/
    ├── test_20260123_115829.png        # 复刻图片
    └── test_20260123_115829_cmp.png    # 对比图（原图 | 复刻）
```

## 已验证测试用例

- 微信聊天列表 (1279x2774px)
- 美团外卖首页 (1080x2340px)
- 淘宝商品详情 (1080x1920px)
- 多种移动应用截图 (375-1280px 宽度)

## 新增功能 (2026-01)

### OmniParser 适配器

支持直接加载 OmniParser 原始解析结果，无需安装 pip 包：

```python
from omniparser_adapter import OmniParserAdapter, format_for_prompt

# 加载并转换
adapter = OmniParserAdapter()
result = adapter.load_from_file("parse1.json", "screenshot.png")

# 生成 VL 模型提示词
prompt = format_for_prompt(result)
print(prompt)
```

**输出示例**：
```
## 检测结果 (共 74 个组件, 48 个可交互)
- [text] 位置:上中 bbox:[534,671,773,717] (239x46px) 内容:「+12^Ez7-5」 置信度:0.90
- [icon] 位置:上左 bbox:[12,279,234,463] (222x184px) 内容:「XG」 [可点击] 置信度:0.85
...
```

### 增强的位置描述

检测结果自动添加位置区域标注（上/中/下 + 左/中/右），便于 VL 模型理解空间布局。

## 后续规划

- [ ] 支持更多检测后端（SAM2、GroundingDINO）
- [ ] 添加生成-对比-修正闭环
- [ ] 支持动态内容（列表滚动）
- [ ] Web UI 界面
- [x] OmniParser 原始输出适配器
- [x] 可交互元素标记

## 相关资源

- [OmniParser](https://github.com/microsoft/OmniParser) - Microsoft UI 解析器
- [GUI-Odyssey](https://huggingface.co/datasets/hflqf88888/GUIOdyssey) - UI 截图数据集
- [Qwen-VL](https://github.com/QwenLM/Qwen-VL) - 视觉语言模型
