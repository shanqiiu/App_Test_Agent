#!/usr/bin/env python3
"""
reference_analyzer.py - 参考图片分析器

分析参考弹窗图片的风格、布局、配色，用于生成相似风格的弹窗。

功能：
1. 提取弹窗区域和相对位置
2. 分析颜色主题（主色调、按钮颜色等）
3. 识别布局特征（关闭按钮位置、主按钮样式等）
4. 使用 VLM 生成风格描述
"""

import json
import base64
import requests
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
from PIL import Image, ImageDraw, ImageFilter, ImageStat
import numpy as np
from collections import Counter
import colorsys


class ReferenceAnalyzer:
    """
    参考图片分析器

    从参考弹窗截图中提取：
    - 布局信息：位置、尺寸比例
    - 颜色信息：主色调、按钮颜色、背景色
    - 风格特征：圆角大小、阴影效果、关闭按钮样式
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        vlm_api_url: str = 'https://api.openai-next.com/v1/chat/completions',
        vlm_model: str = 'gpt-4o'
    ):
        """
        初始化分析器

        Args:
            api_key: API 密钥（用于 VLM 分析）
            vlm_api_url: VLM API 端点
            vlm_model: VLM 模型名称
        """
        self.api_key = api_key
        self.vlm_api_url = vlm_api_url
        self.vlm_model = vlm_model
        self._cache = {}

    def analyze(self, reference_path: str) -> Dict[str, Any]:
        """
        分析参考图片，提取弹窗风格信息

        Args:
            reference_path: 参考图片路径

        Returns:
            风格信息字典
        """
        # 检查缓存
        if reference_path in self._cache:
            return self._cache[reference_path]

        print(f"  正在分析参考图片: {reference_path}")

        image = Image.open(reference_path).convert('RGB')
        width, height = image.size

        # 1. 检测弹窗区域
        dialog_bounds = self._detect_dialog_region(image)

        # 2. 提取颜色信息
        colors = self._extract_colors(image, dialog_bounds)

        # 3. 分析布局特征
        layout = self._analyze_layout(image, dialog_bounds)

        # 4. 使用 VLM 提取详细风格描述（如果有 API key）
        style_desc = {}
        if self.api_key:
            style_desc = self._vlm_analyze_style(reference_path)

        result = {
            'source': reference_path,
            'screen_size': {'width': width, 'height': height},
            'dialog_bounds': dialog_bounds,
            'relative_bounds': {
                'x_ratio': dialog_bounds['x'] / width,
                'y_ratio': dialog_bounds['y'] / height,
                'width_ratio': dialog_bounds['width'] / width,
                'height_ratio': dialog_bounds['height'] / height
            },
            'colors': colors,
            'layout': layout,
            'style': style_desc
        }

        self._cache[reference_path] = result
        print(f"  ✓ 参考图分析完成")
        return result

    def _detect_dialog_region(self, image: Image.Image) -> Dict[str, int]:
        """
        检测弹窗区域

        通过分析图片中的非半透明区域来定位弹窗
        """
        width, height = image.size
        img_array = np.array(image)

        # 转为灰度图
        gray = np.mean(img_array, axis=2)

        # 检测中心区域的亮度变化
        # 弹窗通常是明亮的白色/浅色背景，而遮罩是半透明暗色

        # 使用边缘检测找到弹窗边界
        # 简化方案：从中心向外扫描，找到亮度急剧变化的位置

        center_x, center_y = width // 2, height // 2

        # 检测顶部边界
        top = 0
        for y in range(center_y, 0, -1):
            row_brightness = np.mean(gray[y, center_x-50:center_x+50])
            if row_brightness < 100:  # 暗色区域（遮罩）
                top = y + 1
                break

        # 检测底部边界
        bottom = height
        for y in range(center_y, height):
            row_brightness = np.mean(gray[y, center_x-50:center_x+50])
            if row_brightness < 100:
                bottom = y
                break

        # 检测左边界
        left = 0
        for x in range(center_x, 0, -1):
            col_brightness = np.mean(gray[center_y-50:center_y+50, x])
            if col_brightness < 100:
                left = x + 1
                break

        # 检测右边界
        right = width
        for x in range(center_x, width):
            col_brightness = np.mean(gray[center_y-50:center_y+50, x])
            if col_brightness < 100:
                right = x
                break

        # 添加一些 padding
        padding = 5
        left = max(0, left - padding)
        top = max(0, top - padding)
        right = min(width, right + padding)
        bottom = min(height, bottom + padding)

        return {
            'x': left,
            'y': top,
            'width': right - left,
            'height': bottom - top
        }

    def _extract_colors(self, image: Image.Image, bounds: Dict[str, int]) -> Dict[str, Any]:
        """
        提取弹窗区域的颜色信息
        """
        # 裁剪弹窗区域
        dialog_region = image.crop((
            bounds['x'], bounds['y'],
            bounds['x'] + bounds['width'],
            bounds['y'] + bounds['height']
        ))

        # 缩小图片以加速颜色分析
        small = dialog_region.resize((100, 100), Image.Resampling.LANCZOS)
        pixels = list(small.getdata())

        # 统计颜色频率
        color_counts = Counter(pixels)
        top_colors = color_counts.most_common(10)

        # 分类颜色
        background_color = None
        button_colors = []
        accent_colors = []

        for color, count in top_colors:
            r, g, b = color
            # 判断颜色类型
            brightness = (r + g + b) / 3

            if brightness > 240:  # 接近白色
                if background_color is None:
                    background_color = self._rgb_to_hex(color)
            elif brightness > 200:  # 浅色
                if background_color is None:
                    background_color = self._rgb_to_hex(color)
            elif self._is_saturated(color):  # 饱和色（可能是按钮或强调色）
                hex_color = self._rgb_to_hex(color)
                if self._is_warm_color(color):
                    button_colors.append(hex_color)
                else:
                    accent_colors.append(hex_color)

        # 提取按钮区域颜色（底部区域）
        button_region = dialog_region.crop((
            0, int(bounds['height'] * 0.8),
            bounds['width'], bounds['height']
        ))
        button_dominant = self._get_dominant_color(button_region)

        return {
            'background': background_color or '#FFFFFF',
            'button_primary': button_colors[0] if button_colors else (button_dominant or '#FFD700'),
            'button_secondary': '#F5F5F5',
            'accent_colors': accent_colors[:3],
            'text_primary': '#333333',
            'text_secondary': '#666666'
        }

    def _analyze_layout(self, image: Image.Image, bounds: Dict[str, int]) -> Dict[str, Any]:
        """
        分析布局特征
        """
        width, height = image.size
        dialog_w, dialog_h = bounds['width'], bounds['height']

        # 检测关闭按钮位置
        close_button = self._detect_close_button(image, bounds)

        # 分析弹窗纵横比
        aspect_ratio = dialog_w / dialog_h if dialog_h > 0 else 1

        # 估算圆角大小（基于弹窗尺寸）
        corner_radius = min(dialog_w, dialog_h) * 0.03

        return {
            'close_button': close_button,
            'aspect_ratio': aspect_ratio,
            'corner_radius': int(corner_radius),
            'has_header': True,  # 假设有标题区域
            'has_image': True,   # 假设有图片区域
            'button_position': 'bottom',  # 按钮在底部
            'button_style': 'rounded',    # 圆角按钮
            'overlay_opacity': 0.5        # 遮罩透明度
        }

    def _detect_close_button(self, image: Image.Image, bounds: Dict[str, int]) -> Dict[str, Any]:
        """
        检测关闭按钮的位置和样式
        """
        # 通常关闭按钮在右上角
        # 在弹窗右上角区域搜索圆形的白色/灰色按钮

        # 简化实现：假设关闭按钮在右上角
        return {
            'position': 'top_right',
            'offset_x': -15,  # 相对于弹窗右边界的偏移
            'offset_y': -15,  # 相对于弹窗上边界的偏移
            'size': 28,
            'style': 'circle',  # circle / square
            'background': '#FFFFFF',
            'icon_color': '#666666'
        }

    def _vlm_analyze_style(self, image_path: str) -> Dict[str, Any]:
        """
        使用 VLM 分析弹窗风格
        """
        try:
            with open(image_path, 'rb') as f:
                image_base64 = base64.b64encode(f.read()).decode('utf-8')

            prompt = """分析这个App弹窗的视觉风格，提取以下信息（返回JSON格式）：

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

            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }

            payload = {
                'model': self.vlm_model,
                'messages': [
                    {
                        'role': 'user',
                        'content': [
                            {
                                'type': 'image_url',
                                'image_url': {'url': f'data:image/jpeg;base64,{image_base64}'}
                            },
                            {'type': 'text', 'text': prompt}
                        ]
                    }
                ],
                'temperature': 0.3,
                'max_tokens': 800
            }

            response = requests.post(self.vlm_api_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()

            content = response.json()['choices'][0]['message']['content']

            # 提取 JSON
            import re
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                return json.loads(json_match.group(0))

        except Exception as e:
            print(f"  ⚠ VLM 风格分析失败: {e}")

        return {}

    def _rgb_to_hex(self, rgb: Tuple[int, int, int]) -> str:
        """RGB 转十六进制"""
        return '#{:02x}{:02x}{:02x}'.format(*rgb)

    def _is_saturated(self, rgb: Tuple[int, int, int]) -> bool:
        """判断颜色是否饱和"""
        r, g, b = [x / 255.0 for x in rgb]
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        return s > 0.3 and v > 0.3

    def _is_warm_color(self, rgb: Tuple[int, int, int]) -> bool:
        """判断是否为暖色"""
        r, g, b = [x / 255.0 for x in rgb]
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        # 暖色 hue 范围：0-60 或 300-360
        return (0 <= h <= 0.17) or (h >= 0.83)

    def _get_dominant_color(self, image: Image.Image) -> Optional[str]:
        """获取图片的主色调"""
        small = image.resize((50, 50), Image.Resampling.LANCZOS)
        pixels = list(small.getdata())

        # 过滤掉接近白色和黑色的像素
        filtered = [p for p in pixels if 30 < sum(p)/3 < 230 and self._is_saturated(p)]

        if not filtered:
            return None

        color_counts = Counter(filtered)
        dominant = color_counts.most_common(1)[0][0]
        return self._rgb_to_hex(dominant)

    def apply_style_to_bounds(
        self,
        style_info: Dict[str, Any],
        target_width: int,
        target_height: int
    ) -> Dict[str, int]:
        """
        将参考风格的相对尺寸应用到目标屏幕尺寸

        Args:
            style_info: 分析得到的风格信息
            target_width: 目标屏幕宽度
            target_height: 目标屏幕高度

        Returns:
            计算后的弹窗绝对坐标
        """
        rel = style_info['relative_bounds']

        dialog_width = int(target_width * rel['width_ratio'])
        dialog_height = int(target_height * rel['height_ratio'])

        # 居中显示
        x = (target_width - dialog_width) // 2
        y = int(target_height * rel['y_ratio'])

        return {
            'x': x,
            'y': y,
            'width': dialog_width,
            'height': dialog_height
        }


class ReferenceStyleApplier:
    """
    参考风格应用器

    将分析得到的风格信息应用到弹窗生成中
    """

    def __init__(self, style_info: Dict[str, Any]):
        """
        初始化应用器

        Args:
            style_info: ReferenceAnalyzer.analyze() 返回的风格信息
        """
        self.style_info = style_info

    def get_colors(self) -> Dict[str, str]:
        """获取颜色配置"""
        return self.style_info.get('colors', {
            'background': '#FFFFFF',
            'button_primary': '#FFD700',
            'button_secondary': '#F5F5F5',
            'text_primary': '#333333',
            'text_secondary': '#666666'
        })

    def get_layout(self) -> Dict[str, Any]:
        """获取布局配置"""
        return self.style_info.get('layout', {})

    def get_corner_radius(self) -> int:
        """获取圆角半径"""
        return self.style_info.get('layout', {}).get('corner_radius', 16)

    def get_close_button_config(self) -> Dict[str, Any]:
        """获取关闭按钮配置"""
        return self.style_info.get('layout', {}).get('close_button', {
            'position': 'top_right',
            'size': 28,
            'style': 'circle',
            'background': '#FFFFFF',
            'icon_color': '#666666'
        })

    def get_ai_prompt(self, title: str, message: str) -> str:
        """
        生成用于 AI 图像生成的提示词

        Args:
            title: 弹窗标题
            message: 弹窗内容

        Returns:
            英文提示词
        """
        style = self.style_info.get('style', {})
        colors = self.get_colors()

        # 使用 VLM 分析得到的提示词，或生成默认提示词
        base_prompt = style.get('suggested_prompt', '')

        if not base_prompt:
            visual_style = style.get('visual_style', 'modern minimalist')
            color_scheme = style.get('color_scheme', 'warm')
            content_type = style.get('content_type', 'image with text')

            base_prompt = f"""A mobile app popup dialog in {visual_style} style:
- {color_scheme} color scheme with primary button color {colors['button_primary']}
- White rounded rectangle background with subtle shadow
- {content_type} layout
- Close button (X) in top right corner
- Main action button at bottom with rounded corners
- High resolution, professional mobile UI design
- Chinese text supported"""

        # 添加具体内容
        full_prompt = f"""{base_prompt}

Content:
- Title: "{title}"
- Message: "{message}"
- Button text: "立即查看" or similar call-to-action

Style reference: Similar to Ctrip/携程 app promotional popup"""

        return full_prompt

    def get_bounds_for_screen(self, screen_width: int, screen_height: int) -> Dict[str, int]:
        """
        根据屏幕尺寸计算弹窗位置

        Args:
            screen_width: 屏幕宽度
            screen_height: 屏幕高度

        Returns:
            弹窗坐标
        """
        rel = self.style_info.get('relative_bounds', {
            'x_ratio': 0.1,
            'y_ratio': 0.15,
            'width_ratio': 0.8,
            'height_ratio': 0.6
        })

        dialog_width = int(screen_width * rel['width_ratio'])
        dialog_height = int(screen_height * rel['height_ratio'])

        x = (screen_width - dialog_width) // 2
        y = int(screen_height * rel['y_ratio'])

        return {
            'x': x,
            'y': y,
            'width': dialog_width,
            'height': dialog_height
        }
