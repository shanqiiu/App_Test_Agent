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
from utils.semantic_dialog_generator import SemanticDialogGenerator


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
        render_mode: str = 'semantic_ai',
        api_key: Optional[str] = None,
        gt_dir: Optional[str] = None,
        vlm_api_url: str = 'https://api.openai-next.com/v1/chat/completions',
        vlm_model: str = 'gpt-4o',
        reference_path: Optional[str] = None
    ):
        """
        初始化渲染引擎

        Args:
            screenshot_path: 原始截图路径
            ui_json_path: UI-JSON 文件路径
            fonts_dir: 字体目录（可选，不指定则使用系统默认字体）
            render_mode: 渲染模式（默认 semantic_ai）
            api_key: VLM API 密钥（用于语义分析）
            gt_dir: GT样本目录（用于模板匹配）
            vlm_api_url: VLM API 端点（用于语义分析）
            vlm_model: VLM 模型名称
            reference_path: 参考弹窗图片路径（用于风格学习）

        Note:
            AI 图像生成使用 DashScope API，API Key 从环境变量 DASHSCOPE_API_KEY 获取
        """
        self.screenshot_path = screenshot_path
        self.screenshot = Image.open(screenshot_path).convert('RGBA')
        self.width, self.height = self.screenshot.size
        self.render_mode = render_mode
        self.api_key = api_key

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

        # 初始化语义弹窗生成器
        self.semantic_generator = None
        self.reference_path = reference_path
        if render_mode.startswith('semantic'):
            self.semantic_generator = SemanticDialogGenerator(
                fonts_dir=fonts_dir,
                api_key=api_key,
                vlm_api_url=vlm_api_url,
                vlm_model=vlm_model,
                reference_path=reference_path
            )
            print(f"  ✓ 语义弹窗生成器已初始化 (mode={render_mode})")
            if reference_path:
                print(f"  ✓ 参考风格图片: {reference_path}")

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

    def apply_add(self, action: dict, instruction: str = None) -> None:
        """
        执行 add 操作：新增组件

        Args:
            action: 操作描述
            instruction: 异常指令（用于语义弹窗生成）
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

        # 渲染优先级: GT模板 > 语义弹窗生成 > 旧版大模型生成 > PIL绘制
        layer = None
        is_ai_generated = False

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

        # 2. 使用语义弹窗生成器（如果启用且是弹窗类型）
        if layer is None and self.semantic_generator and comp_class in ['Dialog', 'AlertDialog', 'Toast']:
            semantic_info = component.get('semantic', {})

            # 如果有参考风格，使用参考风格的尺寸和位置
            ref_bounds = self.semantic_generator.get_dialog_bounds_from_reference(self.width, self.height)
            if ref_bounds:
                w = ref_bounds['width']
                h = ref_bounds['height']
                x = ref_bounds['x']
                y = ref_bounds['y']
                print(f"  ✓ 使用参考风格布局: ({x}, {y}) {w}x{h}")

            # 如果 VLM 已经生成了语义信息，直接使用
            if semantic_info:
                content = {
                    'title': semantic_info.get('title', component.get('text', '提示')),
                    'message': semantic_info.get('message', ''),
                    'style': semantic_info.get('style', component.get('style', 'info')),
                    'buttons': semantic_info.get('buttons', ['确定']),
                    'is_ad': semantic_info.get('is_ad', False),
                    'icon_type': semantic_info.get('dialog_type', 'info')
                }
            else:
                # 否则让语义生成器分析页面并生成内容
                content = self.semantic_generator.generate_semantic_content(
                    ui_json=self.ui_json,
                    instruction=instruction or component.get('text', ''),
                    screenshot_path=self.screenshot_path
                )

            # 根据渲染模式选择生成方式
            if self.render_mode == 'semantic_ai':
                # semantic_ai 模式：坚持使用 AI 生成，不回退
                layer = self.semantic_generator.generate_dialog_ai(
                    content, w, h, self.screenshot_path
                )
                if layer:
                    is_ai_generated = True
                    print(f"  ✓ 使用 AI 生成语义弹窗: {content.get('title')}")
            else:
                # semantic_pil 模式：使用 PIL 绘制
                layer = self.semantic_generator.generate_dialog_pil(
                    content, w, h, self.width, self.height
                )
                if layer:
                    print(f"  ✓ 使用 PIL 生成语义弹窗: {content.get('title')}")

        # 3. 回退到基础 PIL 绘制
        if layer is None:
            if comp_class in ['Dialog', 'AlertDialog']:
                layer = self._create_dialog(component, w, h)
            elif comp_class == 'Toast':
                layer = self._create_toast(component, w, h)
            elif comp_class == 'Loading':
                layer = self._create_loading(component, w, h)
            else:
                layer = self._create_generic_component(component, w, h)
            print(f"  ✓ 使用基础 PIL 绘制 {comp_class}")

        # 如果是弹窗且非 AI 生成模式，添加遮罩层
        # AI 生成的弹窗自带白色背景卡片，直接叠加即可
        if comp_class in ['Dialog', 'AlertDialog'] and z_index >= 100:
            if self.render_mode != 'semantic_ai':
                self._add_overlay_mask()

        # 合成到原图 - 使用改进的合成方法
        if is_ai_generated and comp_class in ['Dialog', 'AlertDialog']:
            # AI 生成的弹窗使用居中合成方法（参考 merge_images.py）
            self.screenshot = self._merge_dialog_center(layer, max_ratio=0.8)
            print(f"  ✓ 新增组件: {comp_class} (居中合成)")
        else:
            # 其他组件使用原有的合成方法
            self.screenshot = self.compositor.overlay(
                self.screenshot, layer, (x, y)
            )
            print(f"  ✓ 新增组件: {comp_class} at ({x}, {y})")

    def _merge_dialog_center(
        self,
        dialog: Image.Image,
        max_ratio: float = 0.8
    ) -> Image.Image:
        """
        将弹窗图片居中合成到截图上（参考 merge_images.py 的成功逻辑）

        Args:
            dialog: 弹窗图片（带透明通道）
            max_ratio: 弹窗最大占屏幕比例

        Returns:
            合成后的图片
        """
        # [调试] 创建调试目录
        from pathlib import Path
        debug_dir = Path("debug_dialog_output")
        debug_dir.mkdir(exist_ok=True)

        # 确保底图是 RGBA 模式
        if self.screenshot.mode != 'RGBA':
            self.screenshot = self.screenshot.convert('RGBA')

        # 确保弹窗是 RGBA 模式
        if dialog.mode != 'RGBA':
            dialog = dialog.convert('RGBA')

        # [调试] 保存合成前的底图和弹窗
        self.screenshot.save(debug_dir / "debug_1_screenshot_before.png")
        dialog.save(debug_dir / "debug_2_dialog_before.png")
        print(f"  [调试] 底图已保存: debug_dialog_output/debug_1_screenshot_before.png")
        print(f"  [调试] 弹窗已保存: debug_dialog_output/debug_2_dialog_before.png")

        # 计算缩放比例，确保弹窗不超过屏幕尺寸的 max_ratio
        max_width = int(self.width * max_ratio)
        max_height = int(self.height * max_ratio)

        scale = min(max_width / dialog.width, max_height / dialog.height, 1.0)

        if scale < 1.0:
            new_size = (int(dialog.width * scale), int(dialog.height * scale))
            dialog = dialog.resize(new_size, Image.Resampling.LANCZOS)
            print(f"  ℹ 弹窗已缩放: {scale:.2%} -> {new_size}")
            # [调试] 保存缩放后的弹窗
            dialog.save(debug_dir / "debug_3_dialog_resized.png")

        # 计算居中位置
        x = (self.width - dialog.width) // 2
        y = (self.height - dialog.height) // 2

        # 合成（使用 alpha 通道作为 mask 以支持透明图片）
        result = self.screenshot.copy()
        result.paste(dialog, (x, y), dialog)

        print(f"  ℹ 弹窗合成位置: ({x}, {y}), 尺寸: {dialog.size}")

        # [调试] 保存合成后的结果用于对比
        result.save(debug_dir / "debug_4_merge_result.png")
        print(f"  [调试] 合成结果已保存: debug_dialog_output/debug_4_merge_result.png")

        return result

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
        # 解析颜色并确保包含 alpha 通道
        if color.startswith('#'):
            color_hex = color[1:]
            if len(color_hex) == 6:
                # RGB 格式，添加完全不透明的 alpha
                r = int(color_hex[0:2], 16)
                g = int(color_hex[2:4], 16)
                b = int(color_hex[4:6], 16)
                fill_color = (r, g, b, 255)
            elif len(color_hex) == 8:
                # RGBA 格式
                r = int(color_hex[0:2], 16)
                g = int(color_hex[2:4], 16)
                b = int(color_hex[4:6], 16)
                a = int(color_hex[6:8], 16)
                fill_color = (r, g, b, a)
            else:
                fill_color = color
        else:
            fill_color = color

        draw = ImageDraw.Draw(self.screenshot)
        draw.rectangle(region, fill=fill_color)

    def _blur_region(self, region: Tuple[int, int, int, int], radius: int = 10) -> None:
        """对区域进行高斯模糊"""
        x1, y1, x2, y2 = region
        cropped = self.screenshot.crop(region)
        blurred = cropped.filter(ImageFilter.GaussianBlur(radius))
        self.screenshot.paste(blurred, (x1, y1))

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

    def generate_dialog_and_merge(
        self,
        screenshot_path: str,
        instruction: str
    ) -> Image.Image:
        """
        直接生成异常弹窗并合并到截图（跳过 JSON Patch 中间格式）

        Args:
            screenshot_path: 原始截图路径
            instruction: 异常指令

        Returns:
            合成后的截图
        """
        print(f"  正在生成异常弹窗...")

        if not self.semantic_generator:
            raise RuntimeError("语义弹窗生成器未初始化")

        # 生成弹窗（使用Stage 2过滤后的UI JSON来辅助场景识别）
        dialog, content = self.semantic_generator.generate(
            ui_json=self.ui_json,
            instruction=instruction,
            screenshot_path=screenshot_path,
            mode='ai'
        )

        print(f"  ✓ 弹窗已生成: {content.get('title')}")

        # 合并到截图
        result = self._merge_dialog_center(dialog)

        # 关键：保存合成后的结果，以便 save() 方法能正确保存
        self.screenshot = result

        return result

    def apply_patch(self, patch: dict) -> Image.Image:
        """
        应用完整的 Patch

        Args:
            patch: UI-Edit-Action 字典

        Returns:
            修改后的截图
        """
        actions = patch.get('actions', [])
        # 从 metadata 中获取原始指令，用于语义弹窗生成
        instruction = patch.get('metadata', {}).get('instruction', '')

        # 只执行 add 操作（生成异常弹窗）
        # 不执行 delete 和 modify 操作，因为它们基于 AI 推理不可靠
        add_actions = [a for a in actions if a.get('type') == 'add']
        delete_actions = [a for a in actions if a.get('type') == 'delete']
        modify_actions = [a for a in actions if a.get('type') == 'modify']

        # 如果 patch 中包含 delete 或 modify 操作，输出警告但不执行
        if delete_actions:
            print(f"⚠ 警告: 检测到 {len(delete_actions)} 个 delete 操作，已忽略（不执行）")
        if modify_actions:
            print(f"⚠ 警告: 检测到 {len(modify_actions)} 个 modify 操作，已忽略（不执行）")

        print(f"开始应用 Patch，共 {len(add_actions)} 个操作 (仅执行 add 操作):")

        # 执行 add 操作（弹窗等在最上层）
        for action in add_actions:
            self.apply_add(action, instruction=instruction)

        return self.screenshot

    def save(self, output_path: str) -> None:
        """保存结果"""
        # [调试] 保存前再次输出调试图，对比是否与 _merge_dialog_center 中的一致
        from pathlib import Path
        debug_dir = Path("debug_dialog_output")
        debug_dir.mkdir(exist_ok=True)
        self.screenshot.save(debug_dir / "debug_before_save.png")
        print(f"  [调试] save前图像已保存: debug_dialog_output/debug_before_save.png")

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
                        help='字体目录（可选，不指定则使用系统默认字体）')
    parser.add_argument('--api-key',
                        help='VLM API 密钥（用于语义分析）')
    parser.add_argument('--gt-dir',
                        help='GT样本目录（用于模板匹配）')
    parser.add_argument('--vlm-api-url',
                        default='https://api.openai-next.com/v1/chat/completions',
                        help='VLM API 端点（用于语义分析）')
    parser.add_argument('--vlm-model',
                        default='gpt-4o',
                        help='VLM 模型名称（用于语义分析）')
    parser.add_argument('--reference', '-r',
                        help='参考弹窗图片路径（用于风格学习，生成相似风格的弹窗）')

    args = parser.parse_args()

    # 加载 Patch
    with open(args.patch, 'r', encoding='utf-8') as f:
        patch = json.load(f)

    # 创建渲染器
    renderer = PatchRenderer(
        screenshot_path=args.screenshot,
        ui_json_path=args.ui_json,
        fonts_dir=args.fonts_dir,
        api_key=args.api_key,
        gt_dir=args.gt_dir,
        vlm_api_url=args.vlm_api_url,
        vlm_model=args.vlm_model,
        reference_path=args.reference
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
