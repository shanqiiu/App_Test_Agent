# ui_semantic_patch

UI 语义补丁驱动的受控生成架构，通过 VLM 输出修改逻辑（JSON Patch），结合算法驱动的渲染引擎实现像素级受控编辑。

## 核心思想

**"逻辑层修改 + 物理层绘制"** 的解耦架构：
- VLM 充当 "UI 设计师" → 输出修改指令（JSON Patch）
- 渲染引擎充当 "绘图员" → 执行像素级修改

## 与 img2text2html2img 的区别

| 维度 | img2text2html2img | ui_semantic_patch |
|------|-------------------|-------------------|
| 输入 | 截图 | 截图（可选 XML） |
| 中间表示 | 自然语言描述 | UI-JSON + JSON Patch |
| 渲染方式 | HTML 全页面重建 | 局部像素修改 |
| 文字渲染 | 浏览器字体 | 系统字体引擎直接绘制 |
| 适用场景 | UI 复刻/原型 | 异常场景生成/测试 |

## 流程

支持两种模式：

### 模式1: 纯截图模式（推荐）

无需 UIAutomator，VLM 自动提取 UI 结构：

```
原始截图
    │
    ▼ img2xml.py (VLM 结构提取)
    │
UI-JSON (组件边界框 + 类型)
    │
    ▼ vlm_patch.py (VLM 推理)
    │
UI-Edit-Action (JSON Patch)
    │
    ▼ patch_renderer.py (像素级重绘)
    │
异常场景截图 (.png)
```

### 模式2: XML 模式

如果有 UIAutomator dump：

```
原始截图 + UIAutomator XML
    │
    ▼ xml2json.py (结构解析)
    │
UI-JSON → vlm_patch.py → patch_renderer.py → 异常截图
```

## 目录结构

```
ui_semantic_patch/
├── scripts/
│   ├── img2xml.py            # 截图 → UI-JSON (VLM 提取)
│   ├── xml2json.py           # UIAutomator XML → UI-JSON
│   ├── vlm_patch.py          # VLM 推理生成 JSON Patch
│   ├── patch_renderer.py     # 渲染引擎执行像素级修改
│   ├── run_pipeline.py       # 一键执行完整流程
│   └── utils/
│       ├── text_render.py    # 文字渲染工具
│       ├── inpainting.py     # 背景修复工具
│       ├── compositor.py     # 图层合成工具
│       ├── component_generator.py  # 大模型组件生成
│       └── gt_manager.py     # GT模板管理
├── assets/
│   ├── components/           # 预定义 UI 组件库
│   ├── fonts/                # 系统字体文件
│   └── gt_samples/           # GT样本目录
│       ├── dialogs/
│       ├── toasts/
│       └── loadings/
├── examples/                 # 示例输入/输出
├── .gitignore
└── README.md
```

## 依赖安装

```bash
pip install pillow requests numpy
```

## 快速开始

### 一键执行（推荐）

只需要截图即可，无需 UIAutomator：

```bash
python scripts/run_pipeline.py \
  --screenshot ./page.png \
  --instruction "模拟网络超时弹窗" \
  --api-key YOUR_API_KEY \
  --output ./output/
```

如果有 UIAutomator XML（可选）：

```bash
python scripts/run_pipeline.py \
  --xml ./page.xml \
  --screenshot ./page.png \
  --instruction "模拟登录失败提示" \
  --api-key YOUR_API_KEY
```

### 渲染模式

支持两种渲染模式生成异常组件：

| 模式 | 参数 | 特点 |
|------|------|------|
| PIL | `--render-mode pil` | 纯算法绘制，快速，默认 |
| Generate | `--render-mode generate` | 大模型生成图片，更真实 |

**使用大模型生成更真实的弹窗：**

```bash
python scripts/run_pipeline.py \
  --screenshot ./page.png \
  --instruction "显示网络错误弹窗" \
  --api-key YOUR_API_KEY \
  --render-mode generate \
  --image-model flux-schnell
```

> 注意：`generate` 模式需要图像生成 API 支持，如失败会自动回退到 `pil` 模式。

### GT 模板（推荐）

使用真实异常截图作为模板，生成效果最接近原生：

```bash
python scripts/run_pipeline.py \
  --screenshot ./page.png \
  --instruction "显示网络错误弹窗" \
  --api-key YOUR_API_KEY \
  --gt-dir ./assets/gt_samples
```

**渲染优先级**：GT模板 > 大模型生成 > PIL绘制

#### GT 目录结构

```
assets/gt_samples/
├── dialogs/              # 弹窗模板
│   ├── error_01.png
│   ├── error_01.json     # 元数据
│   └── ...
├── toasts/               # Toast模板
│   └── ...
├── loadings/             # Loading模板
│   └── ...
└── index.json            # 模板索引
```

#### 提取 GT 模板

从真实异常截图中裁剪组件作为模板：

```bash
# 提取弹窗模板
python scripts/utils/gt_manager.py extract \
  --image ./anomaly_screenshot.png \
  --bounds "200,800,680,300" \
  --type dialog \
  --style error \
  --gt-dir ./assets/gt_samples

# 分析GT风格
python scripts/utils/gt_manager.py analyze \
  --image ./anomaly_screenshot.png \
  --bounds "200,800,680,300"

# 查看已有模板
python scripts/utils/gt_manager.py list --gt-dir ./assets/gt_samples
```

## 分步执行

### 1. 结构提取

**方式A: 从截图提取（推荐）**

使用 VLM 自动识别 UI 组件及其边界框：

```bash
python scripts/img2xml.py \
  --image ./page.png \
  --api-key YOUR_API_KEY \
  --output ./ui_structure.json \
  --pretty
```

**方式B: 从 UIAutomator XML 提取**

```bash
python scripts/xml2json.py \
  --xml-path ./page.xml \
  --screenshot ./page.png \
  --output ./ui_structure.json
```

**输出格式**（UI-JSON）：
```json
{
  "metadata": {
    "resolution": {"width": 1080, "height": 2340},
    "extractionMethod": "VLM"
  },
  "components": [
    {
      "index": 0,
      "class": "NavigationBar",
      "bounds": {"x": 0, "y": 0, "width": 1080, "height": 120},
      "text": "登录"
    },
    {
      "index": 1,
      "class": "EditText",
      "bounds": {"x": 100, "y": 300, "width": 880, "height": 80},
      "text": "请输入手机号"
    }
  ],
  "componentCount": 15
}
```

### 2. VLM 推理：生成 JSON Patch

```bash
python scripts/vlm_patch.py \
  --api-key YOUR_API_KEY \
  --screenshot ./page.png \
  --ui-json ./ui_structure.json \
  --instruction "模拟网络超时弹窗" \
  --output ./patch.json
```

**输出格式**（UI-Edit-Action）：
```json
{
  "actions": [
    {
      "type": "modify",
      "target": "login_btn",
      "changes": {"text": "重试", "enabled": false}
    },
    {
      "type": "add",
      "component": {
        "class": "Dialog",
        "bounds": {"x": 200, "y": 800, "width": 680, "height": 300},
        "text": "网络连接超时",
        "style": "error"
      }
    }
  ]
}
```

### 3. 像素级重绘

```bash
python scripts/patch_renderer.py \
  --screenshot ./page.png \
  --ui-json ./ui_structure.json \
  --patch ./patch.json \
  --output ./anomaly_page.png
```

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

### VLM 结构提取的优势

无需连接真实 Android 设备，直接从截图识别：
- 组件类型（Button、EditText、TextView 等）
- 组件边界框（像素级坐标）
- 文本内容
- 可交互性（clickable）

### 局部重绘技术栈

| 操作 | 技术 |
|------|------|
| 文本修改 | Inpainting 擦除 + PIL 字体渲染 |
| 新增组件 | 组件库模板 + Alpha 通道合成 |
| 删除组件 | 背景色填充 / 高斯模糊 |
| 边缘处理 | 抗锯齿 + 羽化过渡 |

## 实施路线

### Phase 1（当前）
- [x] 项目骨架搭建
- [x] XML 解析器实现
- [x] VLM 结构提取（img2xml）
- [x] 文本局部重绘工具
- [x] 基础 VLM Patch 生成
- [x] 一键执行流程

### Phase 2
- [ ] 组件库积累（弹窗、Toast 模板）
- [ ] 高级 Inpainting（复杂背景）
- [ ] 边界框精度优化

### Phase 3
- [ ] ControlNet 辅助处理
- [ ] 样式库（Style-Library）
- [ ] 闭环验证与微调

## 方案优势

1. **无需设备**：纯截图输入，VLM 自动提取结构
2. **文字清晰度极致**：字体引擎渲染，彻底解决 VLM 乱码问题
3. **逻辑与视觉解耦**：可独立优化推理逻辑和视觉表现
4. **天然 Ground Truth**：JSON Patch 本身就是标签，可直接用于训练
5. **环境无关**：直接操作位图，不依赖 Webview

## 异常场景示例

| 指令 | 预期效果 |
|------|---------|
| "模拟网络超时弹窗" | 添加错误弹窗 + 禁用按钮 |
| "显示登录失败提示" | Toast 提示 + 清空密码框 |
| "模拟加载中状态" | Loading 遮罩 + 禁用交互 |
| "显示余额不足" | 修改文案 + 错误提示 |
