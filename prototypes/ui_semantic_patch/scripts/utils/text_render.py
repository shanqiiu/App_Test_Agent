#!/usr/bin/env python3
"""
text_render.py - 文字渲染工具

使用 PIL/Pillow 进行像素级文字渲染，支持多种字体和对齐方式。
"""

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from typing import Optional, Tuple
import os


class TextRenderer:
    """
    文字渲染器

    特点：
    - 使用系统字体引擎渲染，文字清晰无模糊
    - 支持中英文混排
    - 支持多种对齐方式
    """

    # 默认字体回退列表
    DEFAULT_FONTS = [
        # Windows
        'C:/Windows/Fonts/msyh.ttc',      # 微软雅黑
        'C:/Windows/Fonts/simhei.ttf',    # 黑体
        'C:/Windows/Fonts/simsun.ttc',    # 宋体
        'C:/Windows/Fonts/arial.ttf',     # Arial
        # macOS
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/STHeiti Light.ttc',
        # Linux
        '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]

    # Android 默认字体（Roboto）
    ANDROID_FONTS = [
        'Roboto-Regular.ttf',
        'Roboto-Medium.ttf',
        'Roboto-Bold.ttf',
    ]

    def __init__(self, fonts_dir: Optional[str] = None):
        """
        初始化渲染器

        Args:
            fonts_dir: 自定义字体目录
        """
        self.fonts_dir = fonts_dir
        self.font_cache = {}

    def _find_font(self, font_size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        """查找可用字体"""
        cache_key = (font_size, bold)
        if cache_key in self.font_cache:
            return self.font_cache[cache_key]

        # 优先使用自定义字体目录
        if self.fonts_dir:
            font_dir = Path(self.fonts_dir)
            for font_file in font_dir.glob('*.ttf'):
                try:
                    font = ImageFont.truetype(str(font_file), font_size)
                    self.font_cache[cache_key] = font
                    return font
                except Exception:
                    continue
            for font_file in font_dir.glob('*.ttc'):
                try:
                    font = ImageFont.truetype(str(font_file), font_size)
                    self.font_cache[cache_key] = font
                    return font
                except Exception:
                    continue

        # 回退到系统字体
        for font_path in self.DEFAULT_FONTS:
            if os.path.exists(font_path):
                try:
                    font = ImageFont.truetype(font_path, font_size)
                    self.font_cache[cache_key] = font
                    return font
                except Exception:
                    continue

        # 最终回退到默认字体
        font = ImageFont.load_default()
        self.font_cache[cache_key] = font
        return font

    def _parse_color(self, color: str) -> Tuple[int, int, int, int]:
        """解析颜色字符串"""
        if color.startswith('#'):
            color = color[1:]
            if len(color) == 3:
                color = ''.join(c * 2 for c in color)
            if len(color) == 6:
                r = int(color[0:2], 16)
                g = int(color[2:4], 16)
                b = int(color[4:6], 16)
                return (r, g, b, 255)
            elif len(color) == 8:
                r = int(color[0:2], 16)
                g = int(color[2:4], 16)
                b = int(color[4:6], 16)
                a = int(color[6:8], 16)
                return (r, g, b, a)
        return (0, 0, 0, 255)

    def render_text(
        self,
        text: str,
        width: int,
        height: int,
        color: str = '#000000',
        font_size: Optional[int] = None,
        align: str = 'center',
        bold: bool = False,
        line_spacing: int = 4
    ) -> Image.Image:
        """
        渲染文字到透明图层

        Args:
            text: 要渲染的文本
            width: 图层宽度
            height: 图层高度
            color: 文字颜色（十六进制）
            font_size: 字号（None 则自动计算）
            align: 对齐方式（left/center/right）
            bold: 是否粗体
            line_spacing: 行间距

        Returns:
            带透明通道的文字图层
        """
        # 创建透明图层
        layer = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)

        # 自动计算字号
        if font_size is None:
            font_size = min(height // 2, 24)
            font_size = max(font_size, 12)

        font = self._find_font(font_size, bold)
        text_color = self._parse_color(color)

        # 计算文本尺寸
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # 计算位置
        if align == 'left':
            x = 0
        elif align == 'right':
            x = width - text_width
        else:  # center
            x = (width - text_width) // 2

        y = (height - text_height) // 2

        # 绘制文字
        draw.text((x, y), text, font=font, fill=text_color)

        return layer

    def render_multiline_text(
        self,
        text: str,
        width: int,
        height: int,
        color: str = '#000000',
        font_size: int = 14,
        align: str = 'left',
        line_spacing: int = 4
    ) -> Image.Image:
        """
        渲染多行文本（自动换行）

        Args:
            text: 要渲染的文本
            width: 图层宽度
            height: 图层高度
            color: 文字颜色
            font_size: 字号
            align: 对齐方式
            line_spacing: 行间距

        Returns:
            带透明通道的文字图层
        """
        layer = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)

        font = self._find_font(font_size)
        text_color = self._parse_color(color)

        # 自动换行
        lines = self._wrap_text(text, width, font, draw)

        # 计算总高度
        total_height = len(lines) * (font_size + line_spacing) - line_spacing

        # 起始 Y 坐标（垂直居中）
        y = (height - total_height) // 2

        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            line_width = bbox[2] - bbox[0]

            if align == 'left':
                x = 0
            elif align == 'right':
                x = width - line_width
            else:
                x = (width - line_width) // 2

            draw.text((x, y), line, font=font, fill=text_color)
            y += font_size + line_spacing

        return layer

    def _wrap_text(self, text: str, max_width: int, font: ImageFont.FreeTypeFont, draw: ImageDraw.ImageDraw) -> list:
        """文本自动换行"""
        lines = []
        current_line = ""

        for char in text:
            test_line = current_line + char
            bbox = draw.textbbox((0, 0), test_line, font=font)
            line_width = bbox[2] - bbox[0]

            if line_width <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = char

        if current_line:
            lines.append(current_line)

        return lines
