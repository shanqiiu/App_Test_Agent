# img2text2html2img

UI 截图复刻工具链，将手机 App 截图转换为 HTML/CSS，再渲染回图片进行对比。

## 流程

```
原始截图 (.png/.jpg)
    │
    ▼ img2text.py (Vision-Language 模型)
    │
UI描述文本 (.txt + .json)
    │
    ▼ text2html.py (LLM)
    │
HTML/CSS (.html + .json)
    │
    ▼ html2img.py (Playwright)
    │
复刻图片 (.png)
```

## 目录结构

```
img2text2html2img/
├── scripts/
│   ├── img2text.py          # 图片 → 描述文本
│   ├── text2html.py         # 描述文本 → HTML
│   ├── html2img.py          # HTML → 图片
│   ├── test_api.py          # API 连通性测试工具
│   ├── outputs/             # 生成的描述文本
│   │   ├── *.txt            # UI描述文本
│   │   └── *.json           # 元数据（分辨率、模型、时间戳）
│   ├── dist_html/           # 生成的HTML文件
│   │   ├── *.html           # 渲染的HTML页面
│   │   └── *.json           # HTML元数据
│   └── output_images/       # 最终渲染的图片
│       └── *.png            # 复刻截图
├── .gitignore
└── README.md
```

## 依赖安装

```bash
pip install pillow requests playwright openai
playwright install chromium
```

## 使用方法

### 1. 图片转描述文本

使用 VL（Vision-Language）模型分析截图，生成详细的 UI 描述文本。

```bash
python scripts/img2text.py \
  --api-key YOUR_API_KEY \
  --api-url https://api.openai-next.com/v1/chat/completions \
  --image-path ./test.jpg \
  --output-dir ./scripts/outputs
```

**模型配置**:
- 默认模型: `qwen-vl-max`
- Temperature: 0.3（低随机性，保证一致性）
- Max tokens: 4096

**输出格式**（描述性文本示例）:
```
# UI Description
# Resolution: 1279 x 2774
# Model: qwen-vl-max
# Time: 2026-01-23T11:58:29

[状态栏] (L) 「20:51」
[状态栏] (R) icon:信号格+5G+电池89%_白色
[导航栏] (C) 「微信 (5)」
[第1项] (L) img:圆角方形_50px_包含多图拼贴
[第1项-名称] (L) 「周木😊的伏水」
...
```

### 2. 描述文本转 HTML

LLM 根据描述文本生成可渲染的 HTML/CSS。

```bash
python scripts/text2html.py \
  --api-key YOUR_API_KEY \
  --api-url https://api.openai-next.com/v1/chat/completions \
  --input-file ./scripts/outputs/test_20260123_115829.txt \
  --output-dir ./scripts/dist_html
```

**模型配置**:
- 默认模型: `qwen3-235b-a22b`
- Temperature: 0.2（极低随机性，保证精确性）
- Max tokens: 8192

**特性**:
- 自动从描述文本提取分辨率
- 支持 Font Awesome 图标（CDN）
- CSS Grid/Flexbox 布局
- 3次重试机制（指数退避）

### 3. HTML 转图片

使用 Playwright 将 HTML 渲染为图片，保持原始分辨率。

```bash
python scripts/html2img.py \
  -i ./scripts/dist_html/test_20260123_115829_20260123_120457.html \
  -o ./scripts/output_images/
```

**分辨率检测优先级**:
1. 同名 `.json` 元数据文件
2. 同名 `.txt` 元数据文件
3. HTML 中的 CSS 样式
4. 默认值: 375x667px

**特性**:
- Playwright Chromium 无头渲染
- `clip` 参数实现像素级精确截图
- 可配置渲染等待时间（默认 500ms）

### 4. API 测试工具

测试 API 连通性和可用模型。

```bash
# 测试聊天API
python scripts/test_api.py

# 交互式对话模式
python scripts/test_api.py interactive

# 测试图像生成
python scripts/test_api.py image

# 列出可用模型
python scripts/test_api.py models
```

### 批量处理

```bash
# 批量转换目录下所有图片
python scripts/img2text.py --images-dir ./screenshots/ --output-dir ./scripts/outputs/

# 批量转换所有描述文本
python scripts/text2html.py --input-dir ./scripts/outputs/ --output-dir ./scripts/dist_html/

# 批量转换所有 HTML
python scripts/html2img.py -i ./scripts/dist_html/ -o ./scripts/output_images/
```

## 配置

### 环境变量

创建 `.env` 文件：

```
API_KEY=your_api_key
API_URL=https://api.openai-next.com/v1/chat/completions
VL_MODEL=qwen-vl-max
LLM_MODEL=qwen3-235b-a22b
```

### 命令行参数

| 脚本 | 参数 | 说明 |
|------|------|------|
| img2text.py | `--model` | VL 模型名称（默认 `qwen-vl-max`） |
| img2text.py | `--image-path` | 单个图片文件 |
| img2text.py | `--images-dir` | 图片目录（默认 ./images） |
| text2html.py | `--model` | LLM 模型名称（默认 `qwen3-235b-a22b`） |
| text2html.py | `--input-file` | 单个输入文件 |
| text2html.py | `--input-dir` | 输入目录 |
| html2img.py | `--width/--height` | 强制指定输出尺寸 |
| html2img.py | `--timeout` | 渲染等待时间(ms) |

## 输出示例

```
scripts/
├── outputs/
│   ├── test_20260123_115829.txt   # UI 描述文本
│   └── test_20260123_115829.json  # 元信息（含分辨率）
├── dist_html/
│   ├── test_20260123_115829_20260123_120457.html  # 生成的 HTML
│   └── test_20260123_115829_20260123_120457.json  # 元信息
└── output_images/
    └── test_20260123_115829_20260123_120457.png   # 复刻图片
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

### 组件识别模板

img2text.py 使用详细的提示工程识别常见 UI 组件：
- 功能按钮网格（5x2 等）
- 搜索栏（胶囊形状 + 图标）
- 标签栏（水平可滚动）
- 卡片布局（双列）
- 导航栏（顶部/底部）

### 技术栈

| 组件 | 技术 |
|------|------|
| 图像分析 | Qwen VL (Vision-Language Model) |
| HTML生成 | Qwen LLM |
| 图片渲染 | Playwright + Chromium |
| 图像处理 | Pillow |
| HTTP请求 | requests |
| 图标资源 | Font Awesome (CDN) |
| 布局方案 | CSS Flexbox / Grid |

## 测试结果

已验证的测试用例：
- 微信聊天列表 (1279x2774px)
- 多种移动应用截图 (375-1280px 宽度)

每个测试包含完整的三阶段转换：原始截图 → 描述文本 → HTML → 复刻图片