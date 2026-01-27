#!/usr/bin/env python3
"""
inpainting.py - 背景修复工具

对指定区域进行背景修复（Inpainting），用于擦除文字后填充背景。
"""

from PIL import Image, ImageFilter, ImageDraw
import numpy as np
from typing import Tuple, Optional


class BackgroundInpainter:
    """
    背景修复器

    支持多种修复策略：
    - 边缘采样填充
    - 纯色填充
    - 高斯模糊填充
    """

    def __init__(self):
        pass

    def inpaint_region(
        self,
        image: Image.Image,
        region: Tuple[int, int, int, int],
        method: str = 'edge_sample'
    ) -> Image.Image:
        """
        对指定区域进行 Inpainting

        Args:
            image: 原始图片
            region: 要修复的区域 (x1, y1, x2, y2)
            method: 修复方法
                - 'edge_sample': 从边缘采样颜色填充
                - 'solid': 纯色填充
                - 'blur': 高斯模糊填充

        Returns:
            修复后的图片
        """
        result = image.copy()
        x1, y1, x2, y2 = region

        # 确保坐标有效
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(image.width, x2)
        y2 = min(image.height, y2)

        if x2 <= x1 or y2 <= y1:
            return result

        if method == 'edge_sample':
            result = self._inpaint_edge_sample(result, (x1, y1, x2, y2))
        elif method == 'solid':
            result = self._inpaint_solid(result, (x1, y1, x2, y2))
        elif method == 'blur':
            result = self._inpaint_blur(result, (x1, y1, x2, y2))
        else:
            result = self._inpaint_edge_sample(result, (x1, y1, x2, y2))

        return result

    def _inpaint_edge_sample(
        self,
        image: Image.Image,
        region: Tuple[int, int, int, int]
    ) -> Image.Image:
        """
        从边缘采样颜色进行填充

        策略：采样区域四周的像素颜色，计算平均值作为填充色
        """
        x1, y1, x2, y2 = region
        result = image.copy()

        # 采样边缘像素
        edge_colors = []

        # 上边缘
        if y1 > 0:
            for x in range(x1, x2):
                edge_colors.append(image.getpixel((x, y1 - 1)))

        # 下边缘
        if y2 < image.height:
            for x in range(x1, x2):
                edge_colors.append(image.getpixel((x, y2)))

        # 左边缘
        if x1 > 0:
            for y in range(y1, y2):
                edge_colors.append(image.getpixel((x1 - 1, y)))

        # 右边缘
        if x2 < image.width:
            for y in range(y1, y2):
                edge_colors.append(image.getpixel((x2, y)))

        if not edge_colors:
            # 如果没有边缘像素，使用白色
            fill_color = (255, 255, 255, 255) if image.mode == 'RGBA' else (255, 255, 255)
        else:
            # 计算平均颜色
            fill_color = self._average_color(edge_colors, image.mode)

        # 填充区域
        draw = ImageDraw.Draw(result)
        draw.rectangle([x1, y1, x2 - 1, y2 - 1], fill=fill_color)

        return result

    def _inpaint_solid(
        self,
        image: Image.Image,
        region: Tuple[int, int, int, int],
        color: Optional[Tuple] = None
    ) -> Image.Image:
        """
        纯色填充

        如果未指定颜色，尝试检测背景色
        """
        x1, y1, x2, y2 = region
        result = image.copy()

        if color is None:
            # 尝试检测背景色（采样角落像素）
            color = self._detect_background_color(image, region)

        draw = ImageDraw.Draw(result)
        draw.rectangle([x1, y1, x2 - 1, y2 - 1], fill=color)

        return result

    def _inpaint_blur(
        self,
        image: Image.Image,
        region: Tuple[int, int, int, int],
        radius: int = 15
    ) -> Image.Image:
        """
        高斯模糊填充

        扩大区域后模糊，再裁剪回原区域
        """
        x1, y1, x2, y2 = region
        result = image.copy()

        # 扩大采样区域
        expand = radius * 2
        ex1 = max(0, x1 - expand)
        ey1 = max(0, y1 - expand)
        ex2 = min(image.width, x2 + expand)
        ey2 = min(image.height, y2 + expand)

        # 裁剪扩大区域
        expanded_region = image.crop((ex1, ey1, ex2, ey2))

        # 应用高斯模糊
        blurred = expanded_region.filter(ImageFilter.GaussianBlur(radius))

        # 计算目标区域在模糊图中的位置
        inner_x1 = x1 - ex1
        inner_y1 = y1 - ey1
        inner_x2 = x2 - ex1
        inner_y2 = y2 - ey1

        # 裁剪出目标区域
        fill_region = blurred.crop((inner_x1, inner_y1, inner_x2, inner_y2))

        # 粘贴回原图
        result.paste(fill_region, (x1, y1))

        return result

    def _average_color(self, colors: list, mode: str) -> Tuple:
        """计算颜色列表的平均值"""
        if not colors:
            return (255, 255, 255, 255) if mode == 'RGBA' else (255, 255, 255)

        arr = np.array(colors)
        avg = arr.mean(axis=0).astype(int)

        return tuple(avg)

    def _detect_background_color(
        self,
        image: Image.Image,
        region: Tuple[int, int, int, int]
    ) -> Tuple:
        """
        检测区域的背景色

        策略：采样区域外围像素，取出现频率最高的颜色
        """
        x1, y1, x2, y2 = region
        colors = []

        # 采样区域上方和下方的像素
        sample_distance = 5

        # 上方
        if y1 > sample_distance:
            for x in range(x1, x2, 3):
                colors.append(image.getpixel((x, y1 - sample_distance)))

        # 下方
        if y2 + sample_distance < image.height:
            for x in range(x1, x2, 3):
                colors.append(image.getpixel((x, y2 + sample_distance)))

        if not colors:
            return (255, 255, 255, 255) if image.mode == 'RGBA' else (255, 255, 255)

        # 取平均值（简化处理）
        return self._average_color(colors, image.mode)

    def smart_inpaint(
        self,
        image: Image.Image,
        region: Tuple[int, int, int, int],
        complexity_threshold: float = 0.3
    ) -> Image.Image:
        """
        智能 Inpainting

        根据区域复杂度自动选择修复方法：
        - 简单背景（颜色变化小）：纯色填充
        - 复杂背景（颜色变化大）：模糊填充
        """
        x1, y1, x2, y2 = region

        # 计算区域边缘的颜色复杂度
        complexity = self._calculate_edge_complexity(image, region)

        if complexity < complexity_threshold:
            return self._inpaint_edge_sample(image, region)
        else:
            return self._inpaint_blur(image, region)

    def _calculate_edge_complexity(
        self,
        image: Image.Image,
        region: Tuple[int, int, int, int]
    ) -> float:
        """
        计算区域边缘的颜色复杂度

        Returns:
            0-1 之间的复杂度值，越大越复杂
        """
        x1, y1, x2, y2 = region
        edge_colors = []

        # 采样边缘
        if y1 > 0:
            for x in range(x1, x2, 2):
                edge_colors.append(image.getpixel((x, y1 - 1)))

        if not edge_colors:
            return 0.0

        # 计算颜色标准差
        arr = np.array(edge_colors)
        std = arr.std(axis=0).mean()

        # 归一化到 0-1
        return min(std / 128.0, 1.0)
