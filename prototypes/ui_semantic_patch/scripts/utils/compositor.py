#!/usr/bin/env python3
"""
compositor.py - 图层合成工具

处理多图层的合成，包括 Alpha 通道混合、阴影效果、边缘羽化等。
"""

from PIL import Image, ImageFilter, ImageDraw
from typing import Tuple, Optional


class LayerCompositor:
    """
    图层合成器

    支持：
    - Alpha 通道混合
    - 阴影效果
    - 边缘羽化/抗锯齿
    - 图层叠加模式
    """

    def __init__(self):
        pass

    def overlay(
        self,
        base: Image.Image,
        layer: Image.Image,
        position: Tuple[int, int],
        opacity: float = 1.0
    ) -> Image.Image:
        """
        将图层叠加到底图上

        Args:
            base: 底图
            layer: 要叠加的图层
            position: 叠加位置 (x, y)
            opacity: 不透明度 (0.0 - 1.0)

        Returns:
            合成后的图片
        """
        result = base.copy()
        x, y = position

        # 确保两个图片都是 RGBA 模式
        if result.mode != 'RGBA':
            result = result.convert('RGBA')
        if layer.mode != 'RGBA':
            layer = layer.convert('RGBA')

        # 处理不透明度
        if opacity < 1.0:
            layer = self._adjust_opacity(layer, opacity)

        # 计算实际粘贴区域（处理超出边界的情况）
        paste_region = self._calculate_paste_region(
            result.size, layer.size, position
        )

        if paste_region is None:
            return result

        crop_x, crop_y, paste_x, paste_y, width, height = paste_region

        # 裁剪图层（如果超出边界）
        if crop_x > 0 or crop_y > 0 or width < layer.width or height < layer.height:
            layer = layer.crop((crop_x, crop_y, crop_x + width, crop_y + height))

        # Alpha 合成
        result.paste(layer, (paste_x, paste_y), layer)

        return result

    def overlay_with_shadow(
        self,
        base: Image.Image,
        layer: Image.Image,
        position: Tuple[int, int],
        shadow_offset: Tuple[int, int] = (4, 4),
        shadow_blur: int = 8,
        shadow_opacity: float = 0.3
    ) -> Image.Image:
        """
        带阴影效果的图层叠加

        Args:
            base: 底图
            layer: 要叠加的图层
            position: 叠加位置
            shadow_offset: 阴影偏移 (x, y)
            shadow_blur: 阴影模糊半径
            shadow_opacity: 阴影不透明度

        Returns:
            合成后的图片
        """
        # 创建阴影图层
        shadow = self._create_shadow(layer, shadow_blur, shadow_opacity)

        # 先叠加阴影
        shadow_pos = (
            position[0] + shadow_offset[0],
            position[1] + shadow_offset[1]
        )
        result = self.overlay(base, shadow, shadow_pos)

        # 再叠加原图层
        result = self.overlay(result, layer, position)

        return result

    def _create_shadow(
        self,
        layer: Image.Image,
        blur_radius: int = 8,
        opacity: float = 0.3
    ) -> Image.Image:
        """创建阴影图层"""
        # 提取 Alpha 通道作为阴影形状
        if layer.mode != 'RGBA':
            layer = layer.convert('RGBA')

        # 创建纯黑阴影
        shadow = Image.new('RGBA', layer.size, (0, 0, 0, 0))
        alpha = layer.split()[3]

        # 调整阴影不透明度
        shadow_alpha = alpha.point(lambda x: int(x * opacity))
        shadow.putalpha(shadow_alpha)

        # 设置阴影颜色为黑色
        black = Image.new('RGB', layer.size, (0, 0, 0))
        shadow = Image.merge('RGBA', (*black.split(), shadow_alpha))

        # 模糊阴影
        shadow = shadow.filter(ImageFilter.GaussianBlur(blur_radius))

        return shadow

    def _adjust_opacity(self, image: Image.Image, opacity: float) -> Image.Image:
        """调整图层不透明度"""
        if image.mode != 'RGBA':
            image = image.convert('RGBA')

        r, g, b, a = image.split()
        a = a.point(lambda x: int(x * opacity))
        return Image.merge('RGBA', (r, g, b, a))

    def _calculate_paste_region(
        self,
        base_size: Tuple[int, int],
        layer_size: Tuple[int, int],
        position: Tuple[int, int]
    ) -> Optional[Tuple[int, int, int, int, int, int]]:
        """
        计算实际粘贴区域

        Returns:
            (crop_x, crop_y, paste_x, paste_y, width, height) 或 None（如果完全超出边界）
        """
        base_w, base_h = base_size
        layer_w, layer_h = layer_size
        x, y = position

        # 计算裁剪偏移（如果 position 为负数）
        crop_x = max(0, -x)
        crop_y = max(0, -y)

        # 计算实际粘贴位置
        paste_x = max(0, x)
        paste_y = max(0, y)

        # 计算实际宽高
        width = min(layer_w - crop_x, base_w - paste_x)
        height = min(layer_h - crop_y, base_h - paste_y)

        if width <= 0 or height <= 0:
            return None

        return (crop_x, crop_y, paste_x, paste_y, width, height)

    def feather_edge(
        self,
        layer: Image.Image,
        feather_radius: int = 3
    ) -> Image.Image:
        """
        边缘羽化处理

        对图层边缘进行羽化，使其与底图融合更自然

        Args:
            layer: 图层
            feather_radius: 羽化半径

        Returns:
            羽化后的图层
        """
        if layer.mode != 'RGBA':
            layer = layer.convert('RGBA')

        # 提取 Alpha 通道
        r, g, b, a = layer.split()

        # 对 Alpha 通道进行模糊（实现羽化效果）
        a_blurred = a.filter(ImageFilter.GaussianBlur(feather_radius))

        # 保持原有 Alpha 的最大值，只羽化边缘
        # 使用 composite 保持中心不变
        a_feathered = Image.composite(a, a_blurred, a)

        return Image.merge('RGBA', (r, g, b, a_feathered))

    def blend(
        self,
        base: Image.Image,
        layer: Image.Image,
        position: Tuple[int, int],
        mode: str = 'normal'
    ) -> Image.Image:
        """
        混合模式叠加

        Args:
            base: 底图
            layer: 图层
            position: 位置
            mode: 混合模式
                - 'normal': 正常（Alpha 混合）
                - 'multiply': 正片叠底
                - 'screen': 滤色
                - 'overlay': 叠加

        Returns:
            混合后的图片
        """
        if mode == 'normal':
            return self.overlay(base, layer, position)

        # 其他混合模式需要逐像素处理
        result = base.copy()
        x, y = position

        if result.mode != 'RGBA':
            result = result.convert('RGBA')
        if layer.mode != 'RGBA':
            layer = layer.convert('RGBA')

        for ly in range(layer.height):
            for lx in range(layer.width):
                bx, by = x + lx, y + ly
                if 0 <= bx < result.width and 0 <= by < result.height:
                    base_pixel = result.getpixel((bx, by))
                    layer_pixel = layer.getpixel((lx, ly))

                    blended = self._blend_pixel(base_pixel, layer_pixel, mode)
                    result.putpixel((bx, by), blended)

        return result

    def _blend_pixel(
        self,
        base: Tuple[int, int, int, int],
        layer: Tuple[int, int, int, int],
        mode: str
    ) -> Tuple[int, int, int, int]:
        """混合单个像素"""
        br, bg, bb, ba = base
        lr, lg, lb, la = layer

        if la == 0:
            return base

        # 归一化到 0-1
        br, bg, bb = br / 255, bg / 255, bb / 255
        lr, lg, lb = lr / 255, lg / 255, lb / 255
        alpha = la / 255

        if mode == 'multiply':
            rr = br * lr
            rg = bg * lg
            rb = bb * lb
        elif mode == 'screen':
            rr = 1 - (1 - br) * (1 - lr)
            rg = 1 - (1 - bg) * (1 - lg)
            rb = 1 - (1 - bb) * (1 - lb)
        elif mode == 'overlay':
            rr = 2 * br * lr if br < 0.5 else 1 - 2 * (1 - br) * (1 - lr)
            rg = 2 * bg * lg if bg < 0.5 else 1 - 2 * (1 - bg) * (1 - lg)
            rb = 2 * bb * lb if bb < 0.5 else 1 - 2 * (1 - bb) * (1 - lb)
        else:
            rr, rg, rb = lr, lg, lb

        # Alpha 混合
        fr = rr * alpha + br * (1 - alpha)
        fg = rg * alpha + bg * (1 - alpha)
        fb = rb * alpha + bb * (1 - alpha)
        fa = la + ba * (1 - alpha)

        return (
            int(min(255, fr * 255)),
            int(min(255, fg * 255)),
            int(min(255, fb * 255)),
            int(min(255, fa))
        )
