#!/usr/bin/env python3
"""
patch_renderer.py - 像素级受控重绘引擎

根据 JSON Patch 对原始截图进行局部修改，生成异常场景截图。
"""

import json
import argparse
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from typing import Optional, Tuple
import copy

from utils.text_render import TextRenderer
from utils.inpainting import BackgroundInpainter
from utils.compositor import LayerCompositor
from utils.gt_manager import GTManager


class PatchRenderer:
    """
    Patch 渲染引擎

    负责执行三种操作：
    - modify: 修改现有组件（文本、颜色等）
    - add: 新增组件（弹窗、Toast 等）
    - delete: 隐藏/移除组件
    """

    def __init__(
        self,
        screenshot_path: str,
        ui_json_path: str,
        fonts_dir: Optional[str] = None,
        components_dir: Optional[str] = None,
        render_mode: str = 'pil',
        api_key: Optional[str] = None,
        api_url: str = 'https://api.openai-next.com/v1/images/generations',
        image_model: str = 'flux-schnell',
        gt_dir: Optional[str] = None
    ):
        """
        初始化渲染引擎

        Args:
            screenshot_path: 原始截图路径
            ui_json_path: UI-JSON 文件路径
            fonts_dir: 字体目录
            components_dir: 组件库目录
            render_mode: 渲染模式 ('pil' 纯算法 / 'generate' 大模型生成)
            api_key: 图像生成 API 密钥（render_mode='generate' 时需要）
            api_url: 图像生成 API 端点
            image_model: 图像生成模型名称
            gt_dir: GT样本目录（用于模板匹配）
        """
        self.screenshot = Image.open(screenshot_path).convert('RGBA')
        self.width, self.height = self.screenshot.size
        self.render_mode = render_mode

        with open(ui_json_path, 'r', encoding='utf-8') as f:
            self.ui_json = json.load(f)

        self.components = {
            comp.get('id', str(comp.get('index'))): comp
            for comp in self.ui_json.get('components', [])
        }

        # 初始化工具
        self.text_renderer = TextRenderer(fonts_dir)
        self.inpainter = BackgroundInpainter()
        self.compositor = LayerCompositor()

        # 初始化组件生成器（如果使用生成模式）
        self.component_generator = None
        if render_mode == 'generate' and api_key:
            from utils.component_generator import ComponentGenerator
            self.component_generator = ComponentGenerator(
                api_key=api_key,
                api_url=api_url,
                model=image_model,
                templates_dir=components_dir
            )

        # 初始化GT管理器（如果提供GT目录）
        self.gt_manager = None
        if gt_dir:
            self.gt_manager = GTManager(gt_dir)
            print(f"  ✓ GT模板目录: {gt_dir}")

    def find_component(self, target: str) -> Optional[dict]:
        """根据 id 或 index 查找组件"""
        # 先尝试按 id 查找
        if target in self.components:
            return self.components[target]

        # 再尝试按 index 查找
        try:
            index = int(target)
            for comp in self.ui_json.get('components', []):
                if comp.get('index') == index:
                    return comp
        except ValueError:
            pass

        return None

    def apply_modify(self, action: dict) -> None:
        """
        执行 modify 操作：修改现有组件
        """
        target = action.get('target')
        changes = action.get('changes', {})

        component = self.find_component(target)
        if not component:
            print(f"  ⚠ 未找到组件: {target}")
            return

        bounds = component.get('bounds', {})
        x, y = bounds.get('x', 0), bounds.get('y', 0)
        w, h = bounds.get('width', 0), bounds.get('height', 0)

        if w <= 0 or h <= 0:
            print(f"  ⚠ 组件尺寸无效: {target}")
            return

        # 处理文本修改
        if 'text' in changes:
            new_text = changes['text']
            text_color = changes.get('textColor', '#000000')

            # 1. 先对原区域进行 Inpainting（修复背景）
            self.screenshot = self.inpainter.inpaint_region(
                self.screenshot, (x, y, x + w, y + h)
            )

            # 2. 渲染新文本
            text_layer = self.text_renderer.render_text(
                text=new_text,
                width=w,
                height=h,
                color=text_color,
                font_size=changes.get('fontSize'),
                align=changes.get('textAlign', 'center')
            )

            # 3. 合成到原图
            self.screenshot = self.compositor.overlay(
                self.screenshot, text_layer, (x, y)
            )

            print(f"  ✓ 修改文本: {target} → \"{new_text}\"")

        # 处理背景色修改
        if 'background' in changes:
            bg_color = changes['background']
            self._fill_region((x, y, x + w, y + h), bg_color)
            print(f"  ✓ 修改背景: {target} → {bg_color}")

        # 处理禁用状态
        if changes.get('enabled') is False:
            self._apply_disabled_effect((x, y, x + w, y + h))
            print(f"  ✓ 禁用组件: {target}")

    def apply_add(self, action: dict) -> None:
        """
        执行 add 操作：新增组件
        """
        component = action.get('component', {})
        comp_class = component.get('class', 'Unknown')
        bounds = component.get('bounds', {})
        z_index = action.get('zIndex', 100)

        x, y = bounds.get('x', 0), bounds.get('y', 0)
        w, h = bounds.get('width', 200), bounds.get('height', 100)

        # 居中处理（如果没有指定 x, y）
        if x == 0 and y == 0:
            x = (self.width - w) // 2
            y = (self.height - h) // 2

        # 渲染优先级: GT模板 > 大模型生成 > PIL绘制
        layer = None

        # 1. 优先尝试从GT模板获取
        if self.gt_manager:
            style = component.get('style', 'default')
            layer = self.gt_manager.get_template(
                component_type=comp_class,
                style=style,
                target_size=(w, h)
            )
            if layer:
                print(f"  ✓ 使用GT模板: {comp_class}/{style}")

        # 2. 尝试使用大模型生成组件（如果启用）
        if layer is None and self.render_mode == 'generate' and self.component_generator:
            text = component.get('text', '')
            style = component.get('style', 'info')
            layer = self.component_generator.generate_component(
                component_type=comp_class,
                style=style,
                text=text,
                width=w,
                height=h
            )
            if layer:
                print(f"  ✓ 使用生成模型创建 {comp_class}")

        # 3. 回退到 PIL 绘制
        if layer is None:
            if comp_class in ['Dialog', 'AlertDialog']:
                layer = self._create_dialog(component, w, h)
            elif comp_class == 'Toast':
                layer = self._create_toast(component, w, h)
            elif comp_class == 'Loading':
                layer = self._create_loading(component, w, h)
            else:
                layer = self._create_generic_component(component, w, h)

        # 如果是弹窗，先添加遮罩层
        if comp_class in ['Dialog', 'AlertDialog'] and z_index >= 100:
            self._add_overlay_mask()

        # 合成到原图
        self.screenshot = self.compositor.overlay(
            self.screenshot, layer, (x, y)
        )

        print(f"  ✓ 新增组件: {comp_class} at ({x}, {y})")

    def apply_delete(self, action: dict) -> None:
        """
        执行 delete 操作：隐藏/移除组件
        """
        target = action.get('target')
        mode = action.get('mode', 'hide')

        component = self.find_component(target)
        if not component:
            print(f"  ⚠ 未找到组件: {target}")
            return

        bounds = component.get('bounds', {})
        x, y = bounds.get('x', 0), bounds.get('y', 0)
        w, h = bounds.get('width', 0), bounds.get('height', 0)
        region = (x, y, x + w, y + h)

        if mode == 'hide':
            # 用背景色填充
            self.screenshot = self.inpainter.inpaint_region(
                self.screenshot, region
            )
        elif mode == 'blur':
            # 高斯模糊
            self._blur_region(region)
        elif mode == 'placeholder':
            # 灰色占位符
            self._fill_region(region, '#CCCCCC')

        print(f"  ✓ 删除组件: {target} (mode={mode})")

    def _fill_region(self, region: Tuple[int, int, int, int], color: str) -> None:
        """用纯色填充区域"""
        draw = ImageDraw.Draw(self.screenshot)
        draw.rectangle(region, fill=color)

    def _blur_region(self, region: Tuple[int, int, int, int], radius: int = 10) -> None:
        """对区域进行高斯模糊"""
        x1, y1, x2, y2 = region
        cropped = self.screenshot.crop(region)
        blurred = cropped.filter(ImageFilter.GaussianBlur(radius))
        self.screenshot.paste(blurred, (x1, y1))

    def _apply_disabled_effect(self, region: Tuple[int, int, int, int]) -> None:
        """应用禁用效果（半透明灰色覆盖）"""
        x1, y1, x2, y2 = region
        overlay = Image.new('RGBA', (x2 - x1, y2 - y1), (128, 128, 128, 100))
        self.screenshot = self.compositor.overlay(
            self.screenshot, overlay, (x1, y1)
        )

    def _add_overlay_mask(self, opacity: int = 128) -> None:
        """添加全屏半透明遮罩"""
        mask = Image.new('RGBA', (self.width, self.height), (0, 0, 0, opacity))
        self.screenshot = Image.alpha_composite(self.screenshot, mask)

    def _create_dialog(self, component: dict, width: int, height: int) -> Image.Image:
        """创建弹窗组件"""
        style = component.get('style', 'info')
        text = component.get('text', '')
        children = component.get('children', [])

        # 弹窗背景
        dialog = Image.new('RGBA', (width, height), (255, 255, 255, 255))
        draw = ImageDraw.Draw(dialog)

        # 圆角矩形效果（简化版）
        draw.rectangle([0, 0, width - 1, height - 1], outline='#DDDDDD', width=1)

        # 标题/内容
        title_color = {
            'error': '#FF4D4F',
            'warning': '#FAAD14',
            'info': '#1890FF',
            'success': '#52C41A'
        }.get(style, '#333333')

        # 渲染文本
        if text:
            text_layer = self.text_renderer.render_text(
                text=text,
                width=width - 40,
                height=40,
                color=title_color,
                font_size=18,
                align='center'
            )
            dialog.paste(text_layer, (20, 30), text_layer)

        # 渲染子组件（按钮等）
        btn_y = height - 60
        for i, child in enumerate(children):
            if child.get('class') == 'Button':
                btn_text = child.get('text', '确定')
                btn_layer = self._create_button(btn_text, 100, 40)
                btn_x = (width - 100) // 2
                dialog.paste(btn_layer, (btn_x, btn_y), btn_layer)

        return dialog

    def _create_toast(self, component: dict, width: int, height: int) -> Image.Image:
        """创建 Toast 提示"""
        text = component.get('text', '')
        style = component.get('style', 'info')

        bg_color = {
            'error': (255, 77, 79, 230),
            'warning': (250, 173, 20, 230),
            'info': (24, 144, 255, 230),
            'success': (82, 196, 26, 230)
        }.get(style, (51, 51, 51, 230))

        toast = Image.new('RGBA', (width, height), bg_color)

        # 渲染文本
        text_layer = self.text_renderer.render_text(
            text=text,
            width=width - 20,
            height=height,
            color='#FFFFFF',
            font_size=14,
            align='center'
        )
        toast.paste(text_layer, (10, 0), text_layer)

        return toast

    def _create_loading(self, component: dict, width: int, height: int) -> Image.Image:
        """创建 Loading 指示器（简化版）"""
        loading = Image.new('RGBA', (width, height), (0, 0, 0, 180))
        draw = ImageDraw.Draw(loading)

        # 绘制圆形 loading 指示器（简化为圆环）
        center_x, center_y = width // 2, height // 2 - 20
        radius = min(width, height) // 6
        draw.ellipse(
            [center_x - radius, center_y - radius,
             center_x + radius, center_y + radius],
            outline='#FFFFFF', width=3
        )

        # 加载文字
        text = component.get('text', '加载中...')
        text_layer = self.text_renderer.render_text(
            text=text,
            width=width,
            height=30,
            color='#FFFFFF',
            font_size=14,
            align='center'
        )
        loading.paste(text_layer, (0, center_y + radius + 20), text_layer)

        return loading

    def _create_button(self, text: str, width: int, height: int) -> Image.Image:
        """创建按钮"""
        button = Image.new('RGBA', (width, height), (24, 144, 255, 255))
        draw = ImageDraw.Draw(button)

        # 圆角效果（简化）
        draw.rectangle([0, 0, width - 1, height - 1], outline='#1890FF', width=1)

        # 文字
        text_layer = self.text_renderer.render_text(
            text=text,
            width=width,
            height=height,
            color='#FFFFFF',
            font_size=14,
            align='center'
        )
        button.paste(text_layer, (0, 0), text_layer)

        return button

    def _create_generic_component(self, component: dict, width: int, height: int) -> Image.Image:
        """创建通用组件"""
        bg_color = component.get('background', '#FFFFFF')
        text = component.get('text', '')

        layer = Image.new('RGBA', (width, height), bg_color)

        if text:
            text_color = component.get('textColor', '#333333')
            text_layer = self.text_renderer.render_text(
                text=text,
                width=width,
                height=height,
                color=text_color,
                font_size=14,
                align='center'
            )
            layer.paste(text_layer, (0, 0), text_layer)

        return layer

    def apply_patch(self, patch: dict) -> Image.Image:
        """
        应用完整的 Patch

        Args:
            patch: UI-Edit-Action 字典

        Returns:
            修改后的截图
        """
        actions = patch.get('actions', [])

        print(f"开始应用 Patch，共 {len(actions)} 个操作:")

        for action in actions:
            action_type = action.get('type')

            if action_type == 'modify':
                self.apply_modify(action)
            elif action_type == 'add':
                self.apply_add(action)
            elif action_type == 'delete':
                self.apply_delete(action)
            else:
                print(f"  ⚠ 未知操作类型: {action_type}")

        return self.screenshot

    def save(self, output_path: str) -> None:
        """保存结果"""
        # 转换为 RGB 保存（PNG 支持 RGBA，JPG 不支持）
        if output_path.lower().endswith('.jpg') or output_path.lower().endswith('.jpeg'):
            self.screenshot.convert('RGB').save(output_path)
        else:
            self.screenshot.save(output_path)


def main():
    parser = argparse.ArgumentParser(
        description='像素级受控重绘引擎'
    )
    parser.add_argument('--screenshot', '-s', required=True,
                        help='原始截图路径')
    parser.add_argument('--ui-json', '-u', required=True,
                        help='UI-JSON 文件路径')
    parser.add_argument('--patch', '-p', required=True,
                        help='JSON Patch 文件路径')
    parser.add_argument('--output', '-o',
                        help='输出图片路径')
    parser.add_argument('--fonts-dir',
                        help='字体目录')
    parser.add_argument('--components-dir',
                        help='组件库目录')
    parser.add_argument('--render-mode',
                        choices=['pil', 'generate'],
                        default='pil',
                        help='渲染模式: pil(纯算法，默认) / generate(大模型生成)')
    parser.add_argument('--api-key',
                        help='图像生成 API 密钥（render-mode=generate时需要）')
    parser.add_argument('--image-api-url',
                        default='https://api.openai-next.com/v1/images/generations',
                        help='图像生成 API 端点')
    parser.add_argument('--image-model',
                        default='flux-schnell',
                        help='图像生成模型名称')
    parser.add_argument('--gt-dir',
                        help='GT样本目录（用于模板匹配）')

    args = parser.parse_args()

    # 加载 Patch
    with open(args.patch, 'r', encoding='utf-8') as f:
        patch = json.load(f)

    # 创建渲染器
    renderer = PatchRenderer(
        screenshot_path=args.screenshot,
        ui_json_path=args.ui_json,
        fonts_dir=args.fonts_dir,
        components_dir=args.components_dir,
        render_mode=args.render_mode,
        api_key=args.api_key,
        api_url=args.image_api_url,
        image_model=args.image_model,
        gt_dir=args.gt_dir
    )

    # 应用 Patch
    result = renderer.apply_patch(patch)

    # 保存结果
    if args.output:
        output_path = args.output
    else:
        screenshot_path = Path(args.screenshot)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = screenshot_path.parent / f"{screenshot_path.stem}_anomaly_{timestamp}.png"

    renderer.save(str(output_path))
    print(f"\n✓ 异常截图已保存: {output_path}")


if __name__ == '__main__':
    main()
