# img2text2html2img

UI 截图复刻工具链，将手机 App 截图转换为 HTML/CSS，再渲染回图片进行对比。

## 流程

```
原始截图 (.png/.jpg)
    │
    ▼ img2text.py (VL模型)
    │
UI描述文本 (.txt + .json)
    │
    ▼ text2html.py (LLM)
    │
HTML/CSS (.html)
    │
    ▼ html2img.py (Playwright)
    │
复刻图片 (.png)
```

## 目录结构

```
img2text2html2img/
├── scripts/
│   ├── img2text.py    # 图片 → 描述文本
│   ├── text2html.py   # 描述文本 → HTML
│   └── html2img.py    # HTML → 图片
├── .gitignore
└── README.md
```

## 依赖安装

```bash
pip install pillow requests playwright
playwright install chromium
```

## 使用方法

### 1. 图片转描述文本

使用 VL（Vision-Language）模型分析截图，生成详细的 UI 描述文本。

```bash
python scripts/img2text.py \
  --api-key YOUR_API_KEY \
  --api-url YOUR_API_URL \
  --image-path ./screenshot.png \
  --output-dir ./outputs
```

**输出格式**（描述性文本示例）:
```
# UI Description
# Resolution: 1080 x 2340
# Model: qwen3-vl-30b
# Time: 2025-01-22T14:30:52

### 1. 整体概述
- 这是一个电商App的首页
- 整体配色风格：主色调为红色(#FF4D4F)，背景色白色(#FFFFFF)
- 页面主要功能：商品展示、搜索、导航

### 2. 页面结构
#### 顶部区域
- 状态栏：白色背景，高度约44px
- 导航栏：白色背景，高度约50px，包含搜索框和购物车图标
...
```

### 2. 描述文本转 HTML

LLM 根据描述文本生成可渲染的 HTML/CSS。

```bash
python scripts/text2html.py \
  --api-key YOUR_API_KEY \
  --api-url YOUR_API_URL \
  --input-file ./outputs/screenshot_20250122_143052.txt \
  --output-dir ./dist_html
```

### 3. HTML 转图片

使用 Playwright 将 HTML 渲染为图片，保持原始分辨率。

```bash
python scripts/html2img.py \
  -i ./dist_html/screenshot_20250122_143512.html \
  -o ./final/screenshot.png
```

**自动分辨率检测**：从 HTML 中的 `.container` 样式或同名 `.json` 文件提取原始尺寸。

### 批量处理

```bash
# 批量转换目录下所有图片
python scripts/img2text.py --images-dir ./screenshots/ --output-dir ./outputs/

# 批量转换所有描述文本
python scripts/text2html.py --input-dir ./outputs/ --output-dir ./dist_html/

# 批量转换所有 HTML
python scripts/html2img.py -i ./dist_html/ -o ./final/
```

## 配置

### 环境变量

创建 `.env` 文件：

```
API_KEY=your_api_key
API_URL=your_api_url
VL_MODEL=qwen3-vl-30b
LLM_MODEL=qwen3-235b
```

### 命令行参数

| 脚本 | 参数 | 说明 |
|------|------|------|
| img2text.py | `--model` | VL 模型名称（默认 qwen3-vl-30b） |
| img2text.py | `--image-path` | 单个图片文件 |
| img2text.py | `--images-dir` | 图片目录（默认 ./images） |
| text2html.py | `--model` | LLM 模型名称（默认 qwen3-235b） |
| text2html.py | `--input-file` | 单个输入文件 |
| text2html.py | `--input-dir` | 输入目录 |
| html2img.py | `--width/--height` | 强制指定输出尺寸 |
| html2img.py | `--timeout` | 渲染等待时间(ms) |

## 输出示例

```
outputs/
├── screenshot_20250122_143052.txt   # UI 描述文本
├── screenshot_20250122_143052.json  # 元信息（含分辨率）
dist_html/
├── screenshot_20250122_143512.html  # 生成的 HTML
├── screenshot_20250122_143512.json  # 元信息
final/
├── screenshot.png                   # 复刻图片
```

## 技术说明

### 为什么使用描述性文本而非结构化格式？

经过多轮测试，发现结构化格式（如 JSON 或自定义 DSL）存在以下问题：

1. **Token 消耗大**：JSON 格式冗余，容易超出 VL 模型输出限制
2. **还原度低**：结构化数据难以捕捉 UI 的细微设计细节
3. **LLM 理解困难**：复杂的嵌套结构增加 LLM 处理负担

描述性文本的优势：

1. **信息密度高**：自然语言可高效描述复杂布局
2. **灵活性强**：VL 模型可自由表达观察到的细节
3. **LLM 友好**：LLM 擅长理解和处理自然语言描述
