#!/usr/bin/env python3
"""
component_generator.py - 基于大模型的 UI 组件生成器

使用图像生成模型（Flux/DALL-E/SD）生成真实的 UI 组件图片，
然后合成到原始截图上，实现更逼真的异常场景。
"""

import json
import base64
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple
from PIL import Image
import io


class ComponentGenerator:
    """
    UI 组件生成器

    支持两种模式：
    1. 模板模式：从预定义模板库加载
    2. 生成模式：调用图像生成模型实时生成
    """

    # 组件生成提示词模板
    PROMPT_TEMPLATES = {
        'Toast': {
            'error': "A mobile app error toast notification, dark semi-transparent background with rounded corners, white text '{text}', red error icon on left, minimalist flat design, high resolution, UI component only on transparent background",
            'warning': "A mobile app warning toast notification, dark semi-transparent background with rounded corners, white text '{text}', yellow warning icon on left, minimalist flat design, high resolution, UI component only on transparent background",
            'info': "A mobile app info toast notification, dark semi-transparent background with rounded corners, white text '{text}', blue info icon on left, minimalist flat design, high resolution, UI component only on transparent background",
            'success': "A mobile app success toast notification, dark semi-transparent background with rounded corners, white text '{text}', green checkmark icon on left, minimalist flat design, high resolution, UI component only on transparent background",
        },
        'Dialog': {
            'error': "A mobile app error dialog popup, white background with rounded corners and shadow, title '{text}' in red, one confirm button at bottom, minimalist flat design style like WeChat or iOS, high resolution, UI component only",
            'warning': "A mobile app warning dialog popup, white background with rounded corners and shadow, title '{text}' in orange, two buttons (Cancel/Confirm) at bottom, minimalist flat design style, high resolution, UI component only",
            'info': "A mobile app info dialog popup, white background with rounded corners and shadow, title '{text}' in dark gray, one confirm button at bottom, minimalist flat design style, high resolution, UI component only",
            'confirm': "A mobile app confirmation dialog popup, white background with rounded corners and shadow, title '{text}', two buttons (Cancel/Confirm) at bottom, minimalist flat design like WeChat, high resolution, UI component only",
        },
        'Loading': {
            'default': "A mobile app loading overlay, semi-transparent black background, white circular loading spinner in center, text '{text}' below spinner, minimalist flat design, high resolution",
            'fullscreen': "A fullscreen mobile app loading state, semi-transparent dark overlay covering entire screen, large white circular loading animation in center, text '{text}' below, minimalist design",
        }
    }

    def __init__(
        self,
        api_key: str,
        api_url: str = 'https://api.openai-next.com/v1/images/generations',
        model: str = 'flux-schnell',
        templates_dir: Optional[str] = None
    ):
        """
        初始化组件生成器

        Args:
            api_key: API 密钥
            api_url: 图像生成 API 端点
            model: 图像生成模型名称
            templates_dir: 模板目录（可选）
        """
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
        self.templates_dir = Path(templates_dir) if templates_dir else None

    def generate_component(
        self,
        component_type: str,
        style: str,
        text: str,
        width: int,
        height: int,
        app_style: str = 'wechat'
    ) -> Optional[Image.Image]:
        """
        生成 UI 组件图片

        Args:
            component_type: 组件类型 (Toast/Dialog/Loading)
            style: 样式 (error/warning/info/success)
            text: 显示文本
            width: 目标宽度
            height: 目标高度
            app_style: App 风格参考

        Returns:
            生成的组件图片 (RGBA)
        """
        # 尝试从模板加载
        template = self._load_template(component_type, style)
        if template:
            return self._customize_template(template, text, width, height)

        # 调用图像生成 API
        return self._generate_via_api(
            component_type, style, text, width, height, app_style
        )

    def _load_template(self, component_type: str, style: str) -> Optional[Image.Image]:
        """从模板目录加载预定义组件"""
        if not self.templates_dir:
            return None

        template_path = self.templates_dir / component_type.lower() / f"{style}.png"
        if template_path.exists():
            return Image.open(template_path).convert('RGBA')
        return None

    def _customize_template(
        self,
        template: Image.Image,
        text: str,
        width: int,
        height: int
    ) -> Image.Image:
        """自定义模板（调整尺寸、替换文字）"""
        # 简单缩放
        return template.resize((width, height), Image.Resampling.LANCZOS)

    def _generate_via_api(
        self,
        component_type: str,
        style: str,
        text: str,
        width: int,
        height: int,
        app_style: str
    ) -> Optional[Image.Image]:
        """调用图像生成 API 生成组件"""
        # 获取提示词模板
        templates = self.PROMPT_TEMPLATES.get(component_type, {})
        prompt_template = templates.get(style, templates.get('default', ''))

        if not prompt_template:
            print(f"  ⚠ 未找到 {component_type}/{style} 的提示词模板")
            return None

        # 构建完整提示词
        prompt = prompt_template.format(text=text)
        prompt += f", {app_style} style app design"

        # 调整尺寸（大多数模型有尺寸限制）
        gen_width = min(width, 1024)
        gen_height = min(height, 1024)

        # 调用 API
        try:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }

            payload = {
                'model': self.model,
                'prompt': prompt,
                'n': 1,
                'size': f"{gen_width}x{gen_height}",
                'response_format': 'b64_json'
            }

            print(f"  正在生成 {component_type} 组件...")
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=60
            )
            response.raise_for_status()

            result = response.json()
            image_data = result['data'][0]['b64_json']
            image_bytes = base64.b64decode(image_data)
            image = Image.open(io.BytesIO(image_bytes)).convert('RGBA')

            # 调整到目标尺寸
            if image.size != (width, height):
                image = image.resize((width, height), Image.Resampling.LANCZOS)

            print(f"  ✓ 组件生成成功: {width}x{height}")
            return image

        except Exception as e:
            print(f"  ⚠ 组件生成失败: {e}")
            return None


def generate_dialog_prompt(
    text: str,
    style: str = 'error',
    buttons: list = None,
    app_reference: str = 'WeChat'
) -> str:
    """
    生成弹窗的详细提示词

    Args:
        text: 弹窗文本
        style: 样式类型
        buttons: 按钮列表
        app_reference: 参考 App 风格

    Returns:
        详细的图像生成提示词
    """
    buttons = buttons or ['确定']
    buttons_desc = ' and '.join([f"'{b}' button" for b in buttons])

    color_map = {
        'error': 'red title text',
        'warning': 'orange/yellow title text',
        'info': 'dark gray title text',
        'success': 'green title text'
    }
    title_color = color_map.get(style, 'dark gray title text')

    prompt = f"""A mobile app dialog popup in {app_reference} style:
- White rounded rectangle background with subtle shadow
- {title_color}: "{text}"
- {buttons_desc} at the bottom
- Clean minimalist flat design
- No device frame, UI component only
- High resolution, crisp text
- Similar to iOS or WeChat alert dialog"""

    return prompt


def generate_toast_prompt(
    text: str,
    style: str = 'error',
    position: str = 'center'
) -> str:
    """
    生成 Toast 的详细提示词
    """
    icon_map = {
        'error': 'red X icon or warning symbol',
        'warning': 'yellow/orange warning triangle icon',
        'info': 'blue info circle icon',
        'success': 'green checkmark icon'
    }
    icon = icon_map.get(style, 'info icon')

    bg_map = {
        'error': 'semi-transparent dark red',
        'warning': 'semi-transparent dark orange',
        'info': 'semi-transparent dark gray',
        'success': 'semi-transparent dark green'
    }
    bg_color = bg_map.get(style, 'semi-transparent black')

    prompt = f"""A mobile app toast notification:
- {bg_color} pill-shaped background with rounded corners
- {icon} on the left side
- White text: "{text}"
- Floating notification style
- No device frame, UI component only
- High resolution, clean design
- Similar to Android/iOS system toast"""

    return prompt
