#!/usr/bin/env python3
"""
area_loading_renderer.py - 区域加载异常渲染器（独立模块）

功能：在UI区域中心覆盖加载/超时图标，支持风格自适应
特点：
- 纯代码实现尺寸计算（精确、快速、可靠）
- VLM提取APP视觉风格（仅做识别）
- AI生成风格匹配的图标
- 与现有的弹窗生成功能完全独立

使用场景：
- 商品列表加载超时
- 图片加载失败
- 视频加载中断
- 评论区网络异常
"""

import json
import base64
import requests
import re
import os
from typing import Dict, Tuple, Optional
from PIL import Image, ImageDraw
from pathlib import Path

# DashScope API Key（优先使用环境变量）
DASHSCOPE_API_KEY = os.environ.get('DASHSCOPE_API_KEY')


class AreaLoadingRenderer:
    """区域加载异常渲染器 - 风格自适应版本"""

    def __init__(
        self,
        api_key: str,
        vlm_api_url: str = 'https://api.openai-next.com/v1/chat/completions',
        vlm_model: str = 'gpt-4o',
        reference_icon_path: str = None
    ):
        """
        初始化渲染器

        Args:
            api_key: API密钥
            vlm_api_url: VLM API地址
            vlm_model: VLM模型名称
            reference_icon_path: 参考加载图标路径（可选，提供后生成效果更真实）
        """
        self.api_key = api_key
        self.vlm_api_url = vlm_api_url
        self.vlm_model = vlm_model
        self.reference_icon_path = reference_icon_path
        self._style_cache = {}  # 缓存风格分析结果
        self._reference_features = None  # 缓存参考图标特征

    # ==================== 代码算法：尺寸计算（无LLM） ====================

    def calculate_icon_size(
        self,
        region_width: int,
        region_height: int,
        region_type: str = 'general'
    ) -> Dict[str, int]:
        """
        纯算法计算图标尺寸配置

        根据区域面积和类型自适应计算，完全由代码驱动，无LLM参与。

        Args:
            region_width: 区域宽度
            region_height: 区域高度
            region_type: 区域类型 (list/image/video/map/general)

        Returns:
            {
                'icon_size': 图标总尺寸,
                'symbol_size': 中心符号尺寸,
                'text_title_size': 标题字体,
                'text_message_size': 消息字体,
                'button_height': 按钮高度,
                'button_width': 按钮宽度,
                'padding': 内边距,
                'card_width': 卡片宽度,
                'card_height': 卡片高度
            }
        """
        region_area = region_width * region_height
        min_dimension = min(region_width, region_height)

        # 根据区域面积自适应比例
        if region_area > 1000000:  # 大区域 (>1000x1000)
            ratio = 0.15
        elif region_area > 400000:  # 中等区域
            ratio = 0.25
        elif region_area > 100000:  # 小区域
            ratio = 0.35
        else:  # 极小区域
            ratio = 0.50

        # 计算基础图标尺寸
        base_size = int(min_dimension * ratio)

        # 限制范围 [100, 400]
        icon_size = max(100, min(base_size, 400))

        # 根据区域类型微调（确保通用性）
        type_adjustments = {
            'list': 1.0,      # 列表：标准尺寸
            'image': 0.8,     # 图片：稍小（不遮挡太多）
            'video': 1.2,     # 视频：稍大（更显眼）
            'map': 1.0,       # 地图：标准尺寸
            'general': 1.0    # 通用：标准尺寸
        }
        adjustment = type_adjustments.get(region_type, 1.0)
        icon_size = int(icon_size * adjustment)

        # 计算子元素尺寸（固定比例，确保布局一致）
        return {
            'icon_size': icon_size,
            'symbol_size': int(icon_size * 0.30),      # 中心符号 30%
            'text_title_size': int(icon_size * 0.10),  # 标题文字 10%
            'text_message_size': int(icon_size * 0.07), # 消息文字 7%
            'button_height': int(icon_size * 0.18),    # 按钮高度 18%
            'button_width': int(icon_size * 0.60),     # 按钮宽度 60%
            'padding': int(icon_size * 0.10),          # 内边距 10%
            'card_width': int(icon_size * 0.85),       # 卡片宽度 85%
            'card_height': int(icon_size * 0.85)       # 卡片高度 85%
        }

    def calculate_icon_position(
        self,
        region_x: int,
        region_y: int,
        region_width: int,
        region_height: int,
        icon_size: int
    ) -> Tuple[int, int]:
        """纯几何计算图标居中位置"""
        icon_x = region_x + (region_width - icon_size) // 2
        icon_y = region_y + (region_height - icon_size) // 2
        return icon_x, icon_y

    def calculate_corner_radius(
        self,
        icon_size: int,
        style: str = 'medium'
    ) -> int:
        """根据尺寸和风格计算圆角半径"""
        radius_map = {
            'none': 0,
            'small': max(4, int(icon_size * 0.04)),
            'medium': max(8, int(icon_size * 0.08)),
            'large': max(12, int(icon_size * 0.12)),
            'circular': icon_size // 2
        }
        return radius_map.get(style, radius_map['medium'])

    # ==================== VLM：风格提取（仅做视觉识别） ====================

    def extract_app_style(
        self,
        screenshot_path: str,
        use_cache: bool = True
    ) -> Dict:
        """
        使用 VLM 提取 APP 视觉风格

        VLM在此仅负责视觉识别和分类，不涉及任何计算。
        提取的是颜色值和风格类别，便于后续的AI图标生成。

        Returns:
            {
                "primary_color": "#FF6600",           # 主色调
                "secondary_color": "#999999",         # 辅助色
                "background_color": "#F5F5F5",        # 背景色
                "text_primary_color": "#333333",      # 主文字色
                "text_secondary_color": "#666666",    # 辅助文字色
                "icon_style": "outlined",             # filled/outlined/two-tone
                "corner_style": "large",              # small/medium/large/circular
                "shadow_style": "subtle",             # none/subtle/prominent
                "design_language": "ios",             # ios/material/custom
                "app_type": "ecommerce"               # 应用类型
            }
        """
        # 使用缓存避免重复分析
        cache_key = str(screenshot_path)
        if use_cache and cache_key in self._style_cache:
            return self._style_cache[cache_key]

        # 编码图片
        with open(screenshot_path, 'rb') as f:
            image_base64 = base64.b64encode(f.read()).decode('utf-8')

        prompt = """分析这个APP截图的视觉设计风格，仅做识别和分类，不做任何计算。

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

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }

        payload = {
            'model': self.vlm_model,
            'messages': [{
                'role': 'user',
                'content': [
                    {
                        'type': 'image_url',
                        'image_url': {'url': f'data:image/png;base64,{image_base64}'}
                    },
                    {'type': 'text', 'text': prompt}
                ]
            }],
            'temperature': 0.3,
            'max_tokens': 300
        }

        try:
            response = requests.post(self.vlm_api_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()

            content = response.json()['choices'][0]['message']['content']

            # 提取 JSON
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                style = json.loads(json_match.group(0))
                self._style_cache[cache_key] = style
                return style

            raise ValueError("无法解析 VLM 返回的风格信息")

        except Exception as e:
            print(f"  ⚠ 风格提取失败，使用默认风格: {e}")
            return self._get_default_style()

    # ==================== 参考图标：从真实图标学习 ====================

    def analyze_reference_icon(self) -> Optional[Dict]:
        """
        使用 VLM 分析参考加载图标的视觉特征

        提取的特征用于指导 AI 生成更真实的图标。

        Returns:
            {
                "shape": "circular/linear/dots",      # 加载动画形状
                "color_scheme": "monochrome/colorful", # 配色方案
                "primary_colors": ["#FF6600", ...],   # 主要颜色
                "animation_style": "smooth/discrete",  # 动画风格
                "size_ratio": 0.3,                     # 图标相对区域的大小
                "icon_type": "spinner/progress/pulse", # 图标类型
                "design_level": "simple/complex"       # 设计复杂度
            }
        """
        if not self.reference_icon_path:
            return None

        # 使用缓存避免重复分析
        if self._reference_features:
            return self._reference_features

        try:
            with open(self.reference_icon_path, 'rb') as f:
                image_base64 = base64.b64encode(f.read()).decode('utf-8')

            prompt = """分析这个加载图标的视觉设计特征，用于指导生成类似风格的图标。

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

            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }

            payload = {
                'model': self.vlm_model,
                'messages': [{
                    'role': 'user',
                    'content': [
                        {
                            'type': 'image_url',
                            'image_url': {'url': f'data:image/png;base64,{image_base64}'}
                        },
                        {'type': 'text', 'text': prompt}
                    ]
                }],
                'temperature': 0.3,
                'max_tokens': 400
            }

            response = requests.post(self.vlm_api_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()

            content = response.json()['choices'][0]['message']['content']

            # 提取 JSON
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                features = json.loads(json_match.group(0))
                self._reference_features = features
                return features

            raise ValueError("无法解析参考图标特征")

        except Exception as e:
            print(f"  ⚠ 参考图标分析失败，仅使用 APP 风格: {e}")
            return None

    # ==================== AI生成：风格匹配的图标 ====================

    def generate_styled_icon(
        self,
        anomaly_type: str,
        size_config: Dict[str, int],
        app_style: Dict,
        app_type: str = 'general'
    ) -> Optional[Image.Image]:
        """
        使用 DashScope 生成风格匹配的加载图标

        策略：
        1. DashScope 要求最小 512×512，所以固定生成 512 尺寸
        2. 生成后缩小到目标尺寸，保证高质量和自适应
        3. 所有的尺寸比例计算都是相对的（symbol 30%, padding 10% 等）

        Args:
            anomaly_type: timeout / network_error / loading / image_broken / empty_data
            size_config: 代码计算的精确尺寸配置
            app_style: VLM提取的风格特征
            app_type: APP类型

        Returns:
            生成的透明背景图标，失败返回None
        """
        target_size = size_config['icon_size']

        # DashScope 最小要求 512×512，我们固定用 512 生成高质量图标
        generation_size = 512

        # 获取文案内容
        content = self._get_content_text(anomaly_type, app_type)

        # 计算圆角（基于生成尺寸 512）
        corner_radius = self.calculate_corner_radius(
            generation_size,
            app_style.get('corner_style', 'medium')
        )

        # 按比例缩放尺寸配置（512 vs 目标尺寸）
        scale_factor = generation_size / target_size
        scaled_config = {
            k: int(v * scale_factor) for k, v in size_config.items()
        }
        scaled_config['icon_size'] = generation_size

        # 分析参考图标特征（如果提供了参考图）
        reference_features = self.analyze_reference_icon()
        if reference_features:
            print(f"    ℹ 参考图标: {reference_features.get('icon_type')} / {reference_features.get('shape')}")
            print(f"      设计风格: {reference_features.get('visual_description', 'N/A')[:50]}...")

        # 构建精确的生成提示词（使用生成尺寸 512）
        prompt = f"""Generate a loading/error indicator icon that perfectly matches the APP's visual style.

## Style Requirements (match APP exactly):
- Primary color: {app_style.get('primary_color', '#1890FF')}
- Secondary color: {app_style.get('secondary_color', '#999999')}
- Background: {app_style.get('background_color', '#FFFFFF')}
- Text primary: {app_style.get('text_primary_color', '#333333')}
- Text secondary: {app_style.get('text_secondary_color', '#666666')}
- Icon style: {app_style.get('icon_style', 'outlined')} (filled/outlined/two-tone)
- Corner style: {app_style.get('corner_style', 'medium')} rounded corners
- Shadow: {app_style.get('shadow_style', 'subtle')} shadow effect
- Design language: {app_style.get('design_language', 'ios')} style

## Layout Specifications (EXACT pixel values for 512×512):
- Total canvas: {generation_size}×{generation_size} pixels
- Card background: {scaled_config['card_width']}×{scaled_config['card_height']} pixels, centered
- Corner radius: {corner_radius}px
- Center symbol: {scaled_config['symbol_size']}px height
- Title text size: {scaled_config['text_title_size']}px
- Message text size: {scaled_config['text_message_size']}px
- Button: {scaled_config['button_width']}×{scaled_config['button_height']}px
- Padding: {scaled_config['padding']}px

## Content (exactly as specified):
- Icon type: {content['icon_symbol']}
- Title: "{content['title']}"
- Message: "{content['message']}"
- Button text: "{content['action']}"

{self._build_reference_prompt_section(reference_features)}## Technical Requirements:
- Background: PURE TRANSPARENT (alpha=0), only the card itself has color
- The card should float with a subtle shadow
- High quality Chinese text rendering (crisp, anti-aliased)
- Professional mobile UI quality, native look
- Match the APP's color scheme and design language precisely

Generate the icon image now."""

        # 调用 DashScope 生成（需要 dashscope SDK）
        try:
            # 导入生成函数
            import dashscope
            from dashscope import MultiModalConversation

            # 使用环境变量的 DashScope API Key
            dashscope_key = DASHSCOPE_API_KEY
            if not dashscope_key:
                print("  ⚠ DASHSCOPE_API_KEY 环境变量未设置")
                return None

            dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'

            messages = [{
                "role": "user",
                "content": [{"text": prompt}]
            }]

            response = MultiModalConversation.call(
                api_key=dashscope_key,
                model="qwen-image-max",
                messages=messages,
                result_format='message',
                stream=False,
                watermark=False,
                prompt_extend=True,
                negative_prompt="blurry text, distorted text, wrong colors, generic style, low quality",
                size=f"{generation_size}*{generation_size}"
            )

            if response.status_code == 200:
                # 提取图片URL
                content_list = response.output.choices[0].message.content
                for item in content_list:
                    if "image" in item:
                        image_url = item["image"]

                        # 下载图片
                        img_response = requests.get(image_url, timeout=60)
                        if img_response.status_code == 200:
                            import io
                            icon = Image.open(io.BytesIO(img_response.content)).convert('RGBA')

                            # 确保背景透明
                            icon = self._ensure_transparent_bg(icon)

                            # 缩小到目标尺寸（如果生成尺寸 > 目标尺寸）
                            if target_size < generation_size:
                                icon = icon.resize(
                                    (target_size, target_size),
                                    Image.Resampling.LANCZOS
                                )
                                print(f"    ℹ 生成尺寸 512→{target_size}px (质量优先)")

                            return icon

            print(f"  ⚠ AI生成失败: {response.message if hasattr(response, 'message') else 'Unknown error'}")
            return None

        except ImportError:
            print("  ⚠ dashscope 模块未安装，请先安装: pip install dashscope")
            return None
        except Exception as e:
            print(f"  ⚠ 图标生成异常: {e}")
            return None

    def _ensure_transparent_bg(self, image: Image.Image) -> Image.Image:
        """确保背景透明（将纯黑背景变透明）"""
        if image.mode != 'RGBA':
            image = image.convert('RGBA')

        # 简单实现：纯黑色背景变透明
        pixels = image.load()
        width, height = image.size

        for y in range(height):
            for x in range(width):
                r, g, b, a = pixels[x, y]
                # 如果接近纯黑色，变为透明
                if r < 30 and g < 30 and b < 30:
                    pixels[x, y] = (0, 0, 0, 0)

        return image

    def _build_reference_prompt_section(self, features: Optional[Dict]) -> str:
        """构建参考图标的 prompt 段落"""
        if not features:
            return ""

        lines = ["## Reference Icon Style (CRITICAL - closely match this style):"]
        lines.append(f"- Loading shape: {features.get('shape', 'circular')}")
        lines.append(f"- Icon type: {features.get('icon_type', 'spinner')}")
        lines.append(f"- Color scheme: {features.get('color_scheme', 'monochrome')}")

        colors = features.get('primary_colors', [])
        if colors:
            lines.append(f"- Reference colors: {', '.join(colors)}")

        lines.append(f"- Design complexity: {features.get('design_level', 'simple')}")

        desc = features.get('visual_description', '')
        if desc:
            lines.append(f"- Visual reference: {desc}")

        lines.append("- IMPORTANT: The generated icon MUST closely resemble the reference icon's style and visual feel")
        lines.append("")

        return '\n'.join(lines) + '\n'

    def _get_content_text(self, anomaly_type: str, app_type: str) -> Dict[str, str]:
        """根据异常类型和APP类型返回文案（纯数据库）"""
        content_library = {
            ('timeout', 'ecommerce'): {
                'icon_symbol': 'clock/timeout icon',
                'title': '加载超时',
                'message': '商品信息加载失败',
                'action': '点击重试'
            },
            ('timeout', 'social'): {
                'icon_symbol': 'clock/timeout icon',
                'title': '加载超时',
                'message': '内容加载失败',
                'action': '轻触重试'
            },
            ('timeout', 'video'): {
                'icon_symbol': 'clock/timeout icon',
                'title': '加载超时',
                'message': '视频加载失败',
                'action': '重新加载'
            },
            ('network_error', 'general'): {
                'icon_symbol': 'wifi disconnected / network error icon',
                'title': '网络异常',
                'message': '请检查网络连接',
                'action': '重试'
            },
            ('image_broken', 'general'): {
                'icon_symbol': 'broken image / picture frame icon',
                'title': '图片加载失败',
                'message': '请稍后重试',
                'action': '重新加载'
            },
            ('empty_data', 'ecommerce'): {
                'icon_symbol': 'empty box / package icon',
                'title': '暂无商品',
                'message': '该分类暂无商品',
                'action': '看看其他'
            },
            ('empty_data', 'social'): {
                'icon_symbol': 'empty inbox / folder icon',
                'title': '暂无内容',
                'message': '这里还没有动态',
                'action': '去发现'
            }
        }

        # 查找匹配的文案
        key = (anomaly_type, app_type)
        if key not in content_library:
            key = (anomaly_type, 'general')
        if key not in content_library:
            key = ('timeout', 'general')

        if key not in content_library:
            # 最后的兜底
            return {
                'icon_symbol': 'error icon',
                'title': '加载失败',
                'message': '请稍后重试',
                'action': '重试'
            }

        return content_library[key]

    # ==================== 图像处理：覆盖和暗化 ====================

    def _add_dimming(
        self,
        image: Image.Image,
        x: int,
        y: int,
        w: int,
        h: int,
        opacity: int = 100
    ) -> Image.Image:
        """代码实现区域暗化（半透明遮罩）"""
        result = image.copy()
        dimming = Image.new('RGBA', (w, h), (0, 0, 0, opacity))

        region = result.crop((x, y, x + w, y + h))
        region = Image.alpha_composite(region, dimming)
        result.paste(region, (x, y))

        return result

    def _infer_region_type(self, component: Dict) -> str:
        """根据组件类推断区域类型"""
        comp_class = component.get('class', '').lower()

        if 'list' in comp_class or 'recycler' in comp_class:
            return 'list'
        elif 'image' in comp_class or 'picture' in comp_class:
            return 'image'
        elif 'video' in comp_class or 'player' in comp_class:
            return 'video'
        elif 'map' in comp_class:
            return 'map'
        else:
            return 'general'

    def _get_default_style(self) -> Dict:
        """默认风格（当VLM提取失败时使用）"""
        return {
            'primary_color': '#1890FF',
            'secondary_color': '#999999',
            'background_color': '#FFFFFF',
            'text_primary_color': '#333333',
            'text_secondary_color': '#666666',
            'icon_style': 'outlined',
            'corner_style': 'medium',
            'shadow_style': 'subtle',
            'design_language': 'ios',
            'app_type': 'general'
        }

    # ==================== 完整渲染流程 ====================

    def render_area_loading(
        self,
        screenshot: Image.Image,
        component: Dict,
        anomaly_type: str,
        screenshot_path: str = None,
        add_dimming: bool = True
    ) -> Optional[Image.Image]:
        """
        完整的区域加载异常渲染流程

        Args:
            screenshot: 原始截图 PIL Image
            component: 目标组件信息（包含bounds）
            anomaly_type: timeout/network_error/loading/image_broken/empty_data
            screenshot_path: 截图路径（用于风格提取）
            add_dimming: 是否添加区域暗化

        Returns:
            渲染后的截图，失败返回None
        """
        bounds = component.get('bounds', {})
        region_x = bounds.get('x', 0)
        region_y = bounds.get('y', 0)
        region_w = bounds.get('width', 200)
        region_h = bounds.get('height', 200)
        region_type = self._infer_region_type(component)

        print(f"\n  [区域加载异常] {component.get('class', 'Unknown')} ({region_x}, {region_y}) {region_w}×{region_h}px")

        # Step 1: 代码计算尺寸
        print("  [Step 1] 计算图标尺寸...")
        size_config = self.calculate_icon_size(region_w, region_h, region_type)
        icon_size = size_config['icon_size']
        print(f"    ✓ 图标: {icon_size}×{icon_size}px (区域的 {icon_size*100//min(region_w, region_h)}%)")

        # Step 2: VLM提取风格
        if screenshot_path:
            print("  [Step 2] 分析APP视觉风格...")
            app_style = self.extract_app_style(screenshot_path)
            print(f"    ✓ 风格: {app_style.get('design_language')} / {app_style.get('app_type')}")
            print(f"      主色: {app_style.get('primary_color')}, 圆角: {app_style.get('corner_style')}")
        else:
            print("  [Step 2] 使用默认风格...")
            app_style = self._get_default_style()

        # Step 3: AI生成图标
        print("  [Step 3] 生成风格匹配的图标...")
        icon = self.generate_styled_icon(
            anomaly_type=anomaly_type,
            size_config=size_config,
            app_style=app_style,
            app_type=app_style.get('app_type', 'general')
        )

        if not icon:
            print("    ✗ 图标生成失败")
            return None

        print(f"    ✓ 图标生成成功: {icon.size}")

        # Step 4: 代码计算位置
        print("  [Step 4] 计算覆盖位置...")
        icon_x, icon_y = self.calculate_icon_position(
            region_x, region_y, region_w, region_h, icon_size
        )
        print(f"    ✓ 位置: ({icon_x}, {icon_y}) - 居中")

        # Step 5: 图像合成
        print("  [Step 5] 合成图像...")
        result = screenshot.convert('RGBA')

        # 可选：区域暗化
        if add_dimming and anomaly_type in ['timeout', 'network_error']:
            result = self._add_dimming(result, region_x, region_y, region_w, region_h, opacity=100)
            print(f"    ✓ 添加区域暗化")

        # 粘贴图标
        result.paste(icon, (icon_x, icon_y), icon)
        print(f"    ✓ 图标覆盖完成")

        return result


def main():
    """测试示例"""
    import os

    api_key = os.environ.get('API_KEY')
    if not api_key:
        print("请设置环境变量 API_KEY")
        return

    # 初始化渲染器
    renderer = AreaLoadingRenderer(api_key=api_key)

    # 示例使用（需要真实的截图文件）
    print("区域加载异常渲染器 - 测试模式")
    print("=" * 60)

    # 模拟组件信息
    component = {
        'class': 'ListView',
        'bounds': {'x': 0, 'y': 250, 'width': 1080, 'height': 1500}
    }

    print("\n示例组件信息:")
    print(f"  类型: {component['class']}")
    print(f"  区域: {component['bounds']}")

    # 测试尺寸计算
    print("\n测试尺寸计算:")
    size_config = renderer.calculate_icon_size(1080, 1500, 'list')
    print(f"  图标尺寸: {size_config['icon_size']}×{size_config['icon_size']}px")
    print(f"  按钮尺寸: {size_config['button_width']}×{size_config['button_height']}px")

    print("\n注：完整测试需要真实的截图文件和API密钥")


if __name__ == '__main__':
    main()
