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
| Stage 3 | VLM | 根据指令生成 JSON Patch |
| Stage 4 | PIL/AI | 像素级渲染 |

## 流程

```
原始截图
    │
    ▼ [Stage 1] OmniParser 粗检测
    │           YOLO + PaddleOCR + Florence2
    │           输出: stage1_omni_raw_*.json
    │
    ▼ [Stage 2] VLM 语义过滤
    │           合并海报/卡片内的文字，过滤噪声
    │           输出: stage2_filtered_*.json
    │
    ▼ [Stage 3] VLM 推理生成 Patch
    │           根据异常指令生成修改逻辑
    │           输出: stage3_patch_*.json
    │
    ▼ [Stage 4] 像素级渲染
    │           执行 JSON Patch，生成异常场景
    │           输出: final_*.png
    │
异常场景截图 + 中间结果
```

**所有中间结果均保存，便于调试和优化。**

## 目录结构

```
ui_semantic_patch/
├── scripts/
│   ├── run_pipeline.py          # 一键执行完整流程（入口）
│   ├── omni_vlm_fusion.py       # Stage 1+2: OmniParser + VLM 融合
│   ├── omni_extractor.py        # OmniParser 本地提取
│   ├── img2xml.py               # VLM 结构提取（备用）
│   ├── vlm_patch.py             # Stage 3: VLM 推理生成 JSON Patch
│   ├── patch_renderer.py        # Stage 4: 渲染引擎执行像素级修改
│   └── utils/
│       ├── text_render.py       # 文字渲染工具
│       ├── inpainting.py        # 背景修复工具
│       ├── compositor.py        # 图层合成工具
│       ├── component_generator.py   # 大模型组件生成
│       ├── gt_manager.py        # GT模板管理
│       ├── semantic_dialog_generator.py  # 语义感知弹窗生成
│       └── reference_analyzer.py    # 参考图片风格分析
├── assets/
│   ├── components/              # 预定义 UI 组件库
│   ├── fonts/                   # 系统字体文件
│   └── gt_samples/              # GT样本目录
│       ├── dialogs/
│       ├── toasts/
│       └── loadings/
├── examples/                    # 示例输入/输出
│   └── 广告弹窗.jpg             # 参考弹窗样例
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
# 确保 OmniParser 在同级目录
# prototypes/
# ├── OmniParser/        # OmniParser 项目
# └── ui_semantic_patch/ # 本项目

# 安装 OmniParser 依赖
cd ../OmniParser
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

**2. 区域加载模式（新功能）**
```bash
# 智能推荐目标区域
python scripts/run_pipeline.py \
  --screenshot ./page.png \
  --instruction "模拟列表加载超时" \
  --anomaly-mode area_loading \
  --output ./output/

# 指定目标组件
python scripts/run_pipeline.py \
  --screenshot ./page.png \
  --instruction "模拟图片加载失败" \
  --anomaly-mode area_loading \
  --target-component 5 \
  --output ./output/

# 使用参考加载图标（推荐！显著提升生成真实性）
python scripts/run_pipeline.py \
  --screenshot ./page.png \
  --instruction "模拟列表加载超时" \
  --anomaly-mode area_loading \
  --reference-icon ./reference_loading_icon.png \
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
├── page_stage1_omni_raw_20240101_120000.json    # OmniParser 原始检测
├── page_stage2_filtered_20240101_120000.json    # VLM 语义过滤后
├── page_stage3_patch_20240101_120000.json       # JSON Patch
├── page_final_20240101_120000.png               # 最终异常截图
└── page_pipeline_meta_20240101_120000.json      # 流水线元数据
```

## 渲染模式

支持多种渲染模式生成异常组件：

| 模式 | 参数 | 特点 |
|------|------|------|
| **语义 PIL** | `--render-mode semantic_pil` | **语义感知 + PIL 绘制（推荐，默认）** |
| 语义 AI | `--render-mode semantic_ai` | 语义感知 + AI 生成（最逼真但较慢） |
| 基础 PIL | `--render-mode pil` | 纯算法绘制，快速但简单 |
| 旧版生成 | `--render-mode generate` | 大模型生成图片 |

### 语义感知弹窗生成

根据页面内容自动生成符合场景的弹窗内容：

```bash
python scripts/run_pipeline.py \
  --screenshot ./train_ticket_page.png \
  --instruction "生成余票为0的弹窗" \
  --render-mode semantic_pil
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
  --render-mode semantic_pil \
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

### GT 模板

使用真实异常截图作为模板，生成效果最接近原生：

```bash
python scripts/run_pipeline.py \
  --screenshot ./page.png \
  --instruction "显示网络错误弹窗" \
  --gt-dir ./assets/gt_samples
```

**渲染优先级**：GT模板 > 大模型生成 > PIL绘制

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
| `--anomaly-mode` | 异常模式：`dialog` / `area_loading` | `dialog` |
| `--target-component` | 目标组件 ID（area_loading 模式） | 自动推荐 |
| `--reference, -r` | 参考弹窗图片路径（dialog 模式） | - |
| `--reference-icon` | 参考加载图标路径（area_loading 模式，推荐！） | - |
| `--gt-dir` | GT样本目录 | - |
| `--omni-device` | OmniParser 设备 (`cuda`/`cpu`) | 从 `OMNIPARSER_DEVICE` 环境变量读取 |
| `--no-visualize` | 禁用检测结果可视化 | False |

## JSON Patch 操作类型

### modify - 修改现有组件

```json
{
  "type": "modify",
  "target": "组件ID 或 index",
  "changes": {
    "text": "新文本",
    "enabled": false,
    "textColor": "#FF0000",
    "background": "#EEEEEE"
  }
}
```

### add - 新增组件

```json
{
  "type": "add",
  "component": {
    "class": "Toast | Dialog | Loading",
    "bounds": {"x": 0, "y": 0, "width": 100, "height": 50},
    "text": "内容",
    "style": "error | warning | info"
  },
  "zIndex": 100
}
```

### delete - 隐藏组件

```json
{
  "type": "delete",
  "target": "组件ID 或 index",
  "mode": "hide | blur | placeholder"
}
```

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

### 局部重绘技术栈

| 操作 | 技术 |
|------|------|
| 文本修改 | Inpainting 擦除 + PIL 字体渲染 |
| 新增组件 | 组件库模板 + Alpha 通道合成 |
| 删除组件 | 背景色填充 / 高斯模糊 |
| 边缘处理 | 抗锯齿 + 羽化过渡 |

## 异常场景示例

| 指令 | 预期效果 |
|------|---------|
| "模拟网络超时弹窗" | 添加错误弹窗 + 禁用按钮 |
| "显示登录失败提示" | Toast 提示 + 清空密码框 |
| "模拟加载中状态" | Loading 遮罩 + 禁用交互 |
| "显示余额不足" | 修改文案 + 错误提示 |

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
