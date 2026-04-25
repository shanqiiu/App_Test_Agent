# UI 异常分析提示词模板

PROMPT_DIALOG_BLOCKING = """你是一个 UI 异常分析专家。请仔细分析这张移动 APP 异常 UI 截图，提取详细的结构化元数据。

## 分析要求

### 1. anomaly_type（英文 snake_case）
根据异常 UI 元素的功能给出描述性 ID，例如：
reward_badge_dialog, promotional_coupon_dialog, permission_dialog, context_menu_dropdown, tutorial_guide, tooltip_bubble, floating_tip_banner, ad_popup, update_dialog 等

### 2. anomaly_description（中文）
简要描述异常 UI 元素的内容和特征，例如："支付成功弹窗覆盖在订单详情页上方"

### 3. 视觉特征提取

#### 3.1 app_style
提取 APP 的整体风格特征，从以下几个方面描述：
- 整体色调：明亮/暗沉/鲜艳/柔和
- 设计风格：扁平化/拟物化/新拟态/玻璃态
- 布局特点：简洁/密集/留白多

例如："明亮色调，扁平化设计，布局简洁，大量留白"

#### 3.2 primary_color
提取界面的主色调，使用标准十六进制颜色码格式，例如：#3498db

#### 3.3 layout_composition
提取界面的布局构成元素，用英文逗号分隔，例如：
- 顶部导航栏、内容区域、底部标签栏
- 侧边栏、内容区、操作按钮
- 全屏弹窗、背景遮罩

#### 3.4 ui_components
提取界面中包含的 UI 组件，用英文逗号分隔，例如：
button, text, icon, image, list, input, slider, checkbox

#### 3.5 text_elements
提取界面中的重要文本元素，用英文逗号分隔，包括标题、按钮文字、提示文字等，例如：
"确认支付￥99.00", "取消订单", "返回", "关闭"

#### 3.6 color_scheme
提取界面的配色方案，用中文描述，例如：
主色为蓝色 (#3498db)，辅助色为橙色 (#f39c12)，背景为白色 (#ffffff)，文字为深灰色 (#333333)

#### 3.7 spatial_arrangement
提取 UI 元素的空间排列方式，用中文描述，例如：
垂直排列、水平排列、网格布局、卡片式布局、浮动布局

### 4. 生成修复指令

#### 4.1 instruction（中文）
用一句话描述如何修复这个异常 UI，例如："移除覆盖在内容上方的优惠券弹窗"

#### 4.2 patch_operations
列出需要执行的 UI 编辑操作，每个操作包含：
- type: "add"（添加元素）、"remove"（移除元素）、"modify"（修改元素）
- component: 组件类型，如 button, text, image 等
- position: 组件位置，如 top, center, bottom 等
- overlay: 是否覆盖在其他元素之上（布尔值）
- close_button: 是否需要关闭按钮（布尔值）

#### 4.3 key_points
提取 5 个关键修复要点，每个要点不超过 20 个字，用于指导后续的 UI 修复工作。

### 5. 其他信息

#### 5.1 屏幕方向
- 垂直（portrait）：高度大于宽度
- 水平（landscape）：宽度大于高度

#### 5.2 交互状态
当前界面的交互状态，例如：
- 待办状态：可点击，等待用户操作
- 不可用状态：置灰，点击无反应

#### 5.3 异常严重性
- critical：完全阻塞用户操作
- major：严重影响用户体验
- minor：轻微影响，但可使用

### 6. 输出格式
请严格按以下 JSON 格式输出，不要包含任何 Markdown 格式或额外文字：

```json
{
  "anomaly_type": "",
  "anomaly_description": "",
  "visual_features": {
    "app_style": "",
    "primary_color": "#XXXXXX",
    "layout_composition": "",
    "ui_components": "",
    "text_elements": "",
    "color_scheme": "",
    "spatial_arrangement": ""
  },
  "screen_orientation": "portrait/landscape",
  "interaction_state": "",
  "severity": "critical/major/minor",
  "generation_template": {
    "instruction": "",
    "patch_operations": [
      {
        "type": "add/remove/modify",
        "component": "",
        "position": "",
        "overlay": false,
        "close_button": false
      }
    ],
    "key_points": ["", "", "", "", ""]
  }
}
```"""

PROMPT_CONTENT_DUPLICATE = """你是一个 UI 内容分析专家。请分析这张移动 APP 界面截图，检测是否存在内容重复或歧义问题。

## 分析要求

### 1. content_duplicates（内容重复检测）
识别界面中完全相同或高度相似的内容块，例如：
- 重复的列表项
- 重复的图片或图标
- 重复的文本内容
- 重复的按钮或操作项

格式：
- description: 重复内容的描述
- occurrences: 重复次数
- positions: 重复位置列表 [位置 1, 位置 2, ...]

### 2. ambiguous_content（内容歧义检测）
识别可能存在歧义或不清晰的内容，例如：
- 模糊的图标或缺少标签
- 模棱两可的按钮文字
- 不明确的提示信息
- 难以理解的操作流程

格式：
- description: 歧义内容的描述
- ambiguity_type: 歧义类型（unclear_icon, vague_text, unclear_action, confusing_flow）
- suggestion: 改进建议

### 3. 重复内容分类
- exact_duplicate: 完全相同的复制
- near_duplicate: 高度相似但有细微差异
- layout_repetition: 重复的布局模式

### 4. 严重性评估
- critical: 严重影响功能或导致误解
- major: 明显影响用户体验
- minor: 轻微问题，不影响主要功能

### 5. 输出格式
请严格按以下 JSON 格式输出：

```json
{
  "has_issues": true/false,
  "content_duplicates": [
    {
      "description": "",
      "occurrences": 0,
      "positions": [],
      "duplicate_type": "exact_duplicate/near_duplicate/layout_repetition"
    }
  ],
  "ambiguous_content": [
    {
      "description": "",
      "ambiguity_type": "unclear_icon/vague_text/unclear_action/confusing_flow",
      "suggestion": ""
    }
  ],
  "severity": "critical/major/minor/none",
  "analysis": "详细分析说明"
}
```"""

PROMPT_LOADING_TIMEOUT = """你是一个 UI 异常分析专家，专注于识别加载超时类异常。

## 任务
分析当前界面截图，判断是否存在加载超时、白屏或资源加载失败问题。

## 分析要点

### 1. 白屏检测
- 屏幕完全空白无内容
- 页面核心区域空白
- 加载动画持续无内容

### 2. 加载状态识别
- 加载 spinner/进度条持续显示
- 加载中提示文字
- 骨架屏长时间未消失

### 3. 资源加载失败
- 图片未加载显示占位符
- 视频/媒体内容无法播放
- 列表数据未加载

### 4. 超时状态
- 页面长时间无响应
- 操作后无反馈
- 超时错误提示

## 判断标准
符合以下条件之一即可判定为 loading_timeout：
- 页面处于长时间加载状态无内容
- 明显的加载失败或超时提示
- 关键资源未加载成功

## 输出格式
请严格按以下 JSON 格式输出：

```json
{
  "is_loading_timeout": true/false,
  "confidence": 0.0-1.0 的置信度分数，
  "timeout_type": "加载超时类型描述",
  "loading_state": "白屏/加载中/加载失败/超时",
  "analysis": "详细分析说明"
}
```"""

# VLM 语义分组提示词
PROMPT_VLM_GROUPING = """请分析这张 App 截图，结合下方的自动检测结果，判断哪些检测框共同构成一个功能组件。

## 图片分辨率：{img_width}x{img_height} 像素

## 自动检测结果（共 {num_components} 个检测框）

{components_text}

请输出分组结果 JSON。每个检测框 index 必须出现在且仅出现在一个 group 中。

**重要要求**：
1. 必须返回纯JSON格式，不要使用Markdown格式
2. 不要添加任何解释性文字
3. JSON格式示例：

```json
{{"groups": [
  {{"name": "顶部状态栏", "indices": [0, 1, 2], "class": "StatusBar", "text": "时间、电量"}},
  {{"name": "搜索框", "indices": [3, 4], "class": "SearchBar", "text": "搜索"}}
]}}
```

请直接返回JSON，不要使用```json```代码块标记。
"""

# 区域加载图标生成提示词
PROMPT_AREA_LOADING_STYLE = """分析这个APP截图的视觉设计风格，仅做识别和分类，不做任何计算。

## 需要提取的信息

1. **配色方案**（识别精确的颜色值）
   - primary_color: 主色调（按钮、标题栏）
   - secondary_color: 辅助色
   - background_color: 背景色
   - text_primary_color: 主文字颜色
   - text_secondary_color: 辅助文字颜色

2. **图标风格**（分类）
   - filled: 实心填充
   - outlined: 线性轮廓
   - two-tone: 双色调

3. **圆角风格**（分类）
   - small: 小圆角
   - medium: 中等圆角
   - large: 大圆角
   - circular: 完全圆形

4. **阴影风格**（分类）
   - none: 无阴影
   - subtle: 轻微阴影
   - prominent: 明显阴影

5. **设计语言**（分类）
   - ios: iOS原生
   - material: Material Design
   - custom: 自定义风格

6. **APP类型**（分类）
   - ecommerce: 电商购物
   - social: 社交通讯
   - video: 视频播放
   - finance: 金融支付
   - travel: 旅行出行
   - food: 美食外卖
   - news: 新闻资讯
   - general: 通用

**重要：只做识别和分类，不要做任何计算！**

返回纯JSON：
```json
{
    "primary_color": "#FF6600",
    "secondary_color": "#999999",
    "background_color": "#F5F5F5",
    "text_primary_color": "#333333",
    "text_secondary_color": "#666666",
    "icon_style": "outlined",
    "corner_style": "large",
    "shadow_style": "subtle",
    "design_language": "ios",
    "app_type": "ecommerce"
}
```"""

PROMPT_AREA_LOADING_ICON = """分析这个加载图标的视觉设计特征，用于指导生成类似风格的图标。

## 需要提取的特征

1. **加载动画形状**
   - circular: 圆形旋转
   - linear: 线性进度
   - dots: 点阵脉冲

2. **配色方案**
   - monochrome: 单色
   - colorful: 多色

3. **主要颜色**（提取 2-3 个主色）

4. **动画风格**
   - smooth: 平滑过渡
   - discrete: 离散步进

5. **图标类型**
   - spinner: 旋转转子
   - progress: 进度条
   - pulse: 脉冲波形
   - orbit: 环绕轨道

6. **设计复杂度**
   - simple: 极简风格
   - complex: 复杂设计

7. **视觉描述**：用 1-2 句话描述这个图标的整体风格和特点

返回 JSON 格式：
```json
{
    "shape": "circular/linear/dots",
    "color_scheme": "monochrome/colorful",
    "primary_colors": ["#XXXXXX", "#XXXXXX"],
    "animation_style": "smooth/discrete",
    "icon_type": "spinner/progress/pulse/orbit",
    "design_level": "simple/complex",
    "visual_description": "描述文本"
}
```"""

# 内容重复检测提示词
PROMPT_CONTENT_DUPLICATE_PANEL = """分析这张移动App截图中底部浮层/弹出面板的视觉风格。

请仔细观察并提取以下样式参数，返回JSON格式：
{
    "background_color": "浮层背景色 #hex格式",
    "primary_color": "主色调/选中态颜色 #hex格式",
    "text_color": "主要文字颜色 #hex格式",
    "secondary_text_color": "次要文字颜色 #hex格式",
    "grid_columns": 网格列数(整数),
    "cell_border_radius": 单元格圆角大小(整数像素),
    "cell_background": "普通单元格背景色 #hex格式",
    "selected_background": "选中单元格背景色 #hex格式",
    "has_vip_badge": 是否有VIP/会员标签(true/false),
    "vip_badge_color": "VIP标签背景色 #hex格式",
    "cell_height": 单元格高度估计(整数像素)",
    "cell_margin": 单元格间距估计(整数像素),
    "title_visible": 是否显示标题栏(true/false),
    "close_button_visible": 是否有关闭按钮(true/false),
    "close_button_position": "关闭按钮位置(top-right/top-left/bottom-center)",
    "overlay_opacity": 遮罩透明度(0-1的小数)
}

只返回JSON，不要其他内容。基于图片实际观察填写，如果某项无法确定就使用合理的默认值。"""

# 异常样本分析提示词
PROMPT_ANOMALY_SAMPLE_ANALYSIS = """分析这个Agent执行时遇到的UI异常样本，提取关键信息用于样本聚类和风格迁移。

## 分析维度

### 1. 异常类型识别
- **dialog_ad**: 广告弹窗（推广、活动、红包）
- **dialog_tip**: 提示/教程弹窗（使用说明、新功能引导）
- **dialog_system**: 系统弹窗（权限申请、设置确认）
- **loading_timeout**: 加载超时（白屏、转圈、无响应）
- **content_error**: 内容错误（信息重复、显示异常）
- **ui_interference**: UI干扰元素（浮层、悬浮按钮遮挡）
- **network_error**: 网络异常（断网提示、请求失败）

### 2. 根因分析
简要说明导致Agent执行阻塞的原因。

### 3. 视觉风格特征（用于风格迁移）
- APP风格识别（淘宝/京东/微信/抖音/通用）
- 主色调
- 圆角风格（small/medium/large/circular）
- 阴影效果（none/subtle/prominent）

### 4. 关键UI元素
列出图中关键元素（如：广告图片、关闭按钮、"立即查看"按钮）

### 5. 对Agent影响
- **high**: 完全阻塞，必须处理
- **medium**: 部分阻塞，建议处理
- **low**: 轻微影响

### 6. 建议处理方式
- 点击关闭按钮
- 点击返回键
- 等待自动消失
- 重新加载页面

返回纯JSON："""

# 参考图分析提示词
PROMPT_REFERENCE_ANALYSIS = """分析这个App弹窗的视觉风格，提取以下信息（返回JSON格式）：

1. dialog_type: 弹窗类型（ad/alert/confirm/toast）
2. visual_style: 视觉风格描述（如：现代简约、活泼多彩、商务专业等）
3. brand_elements: 是否包含品牌元素（logo、品牌色等）
4. content_type: 内容类型（纯文字/图文混合/大图展示）
5. button_style: 按钮风格描述（颜色、形状、文字）
6. close_button_style: 关闭按钮风格
7. shadow_effect: 是否有阴影效果
8. color_scheme: 主要配色方案（warm/cool/neutral）
9. suggested_prompt: 用于图像生成的提示词（英文，描述如何生成相似风格的弹窗）

只返回JSON，不要其他内容。"""

CATEGORY_TO_PROMPT = {
    'dialog_blocking': PROMPT_DIALOG_BLOCKING,
    'content_duplicate': PROMPT_CONTENT_DUPLICATE,
    'loading_timeout': PROMPT_LOADING_TIMEOUT,
}
