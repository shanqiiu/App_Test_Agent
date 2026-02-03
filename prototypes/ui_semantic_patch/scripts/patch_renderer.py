#!/usr/bin/env python3
"""
patch_renderer.py - 异常弹窗渲染引擎

生成异常弹窗并合成到原始截图。当前仅支持 add 操作（弹窗生成）。
"""

import json
import argparse
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFilter
from typing import Optional, Tuple

from utils.gt_manager import GTManager
from utils.semantic_dialog_generator import SemanticDialogGenerator


class PatchRenderer:
    """
    Patch 渲染引擎

    当前仅支持 add 操作：新增弹窗组件
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
            fonts_dir: 字体目录（可选）
            render_mode: 渲染模式（semantic_ai / semantic_pil）
            api_key: VLM API 密钥
            gt_dir: GT样本目录
            vlm_api_url: VLM API 端点
            vlm_model: VLM 模型名称
            reference_path: 参考弹窗图片路径

        Note:
            AI 图像生成使用 DashScope API，Key 从环境变量 DASHSCOPE_API_KEY 获取
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

        # 初始化GT管理器
        self.gt_manager = None
        if gt_dir:
            self.gt_manager = GTManager(gt_dir)
            print(f"  ✓ GT模板目录: {gt_dir}")

    def find_component(self, target: str) -> Optional[dict]:
        """根据 id 或 index 查找组件"""
        if target in self.components:
            return self.components[target]

        try:
            index = int(target)
            for comp in self.ui_json.get('components', []):
                if comp.get('index') == index:
                    return comp
        except ValueError:
            pass

        return None

    def apply_add(self, action: dict, instruction: str = None) -> None:
        """
        执行 add 操作：新增弹窗组件

        Args:
            action: 操作描述
            instruction: 异常指令
        """
        component = action.get('component', {})
        comp_class = component.get('class', 'Unknown')
        bounds = component.get('bounds', {})
        z_index = action.get('zIndex', 100)

        x, y = bounds.get('x', 0), bounds.get('y', 0)
        w, h = bounds.get('width', 200), bounds.get('height', 100)

        # 居中处理
        if x == 0 and y == 0:
            x = (self.width - w) // 2
            y = (self.height - h) // 2

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

        # 2. 使用语义弹窗生成器
        if layer is None and self.semantic_generator and comp_class in ['Dialog', 'AlertDialog', 'Toast']:
            semantic_info = component.get('semantic', {})

            # 参考风格尺寸
            ref_bounds = self.semantic_generator.get_dialog_bounds_from_reference(self.width, self.height)
            if ref_bounds:
                w = ref_bounds['width']
                h = ref_bounds['height']
                x = ref_bounds['x']
                y = ref_bounds['y']
                print(f"  ✓ 使用参考风格布局: ({x}, {y}) {w}x{h}")

            # 生成语义内容
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
                content = self.semantic_generator.generate_semantic_content(
                    ui_json=self.ui_json,
                    instruction=instruction or component.get('text', ''),
                    screenshot_path=self.screenshot_path
                )

            # 根据渲染模式选择生成方式
            if self.render_mode == 'semantic_ai':
                layer = self.semantic_generator.generate_dialog_ai(
                    content, w, h, self.screenshot_path
                )
                if layer:
                    is_ai_generated = True
                    print(f"  ✓ 使用 AI 生成语义弹窗: {content.get('title')}")
            else:
                layer = self.semantic_generator.generate_dialog_pil(
                    content, w, h, self.width, self.height
                )
                if layer:
                    print(f"  ✓ 使用 PIL 生成语义弹窗: {content.get('title')}")

        # 3. 回退到基础绘制
        if layer is None:
            layer = self._create_basic_dialog(component, w, h)
            print(f"  ✓ 使用基础绘制 {comp_class}")

        # 添加遮罩层（非 AI 模式）
        if comp_class in ['Dialog', 'AlertDialog'] and z_index >= 100:
            if self.render_mode != 'semantic_ai':
                self._add_overlay_mask()

        # 合成到原图
        if is_ai_generated and comp_class in ['Dialog', 'AlertDialog']:
            self.screenshot = self._merge_dialog_center(layer, max_ratio=0.8)
            print(f"  ✓ 新增组件: {comp_class} (居中合成)")
        else:
            self.screenshot = self._overlay(self.screenshot, layer, (x, y))
            print(f"  ✓ 新增组件: {comp_class} at ({x}, {y})")

    def _overlay(self, base: Image.Image, layer: Image.Image, position: Tuple[int, int]) -> Image.Image:
        """将图层叠加到基础图像上"""
        result = base.copy()
        if layer.mode != 'RGBA':
            layer = layer.convert('RGBA')
        result.paste(layer, position, layer)
        return result

    def _merge_dialog_center(
        self,
        dialog: Image.Image,
        max_ratio: float = 0.8
    ) -> Image.Image:
        """将弹窗图片居中合成到截图上"""
        if self.screenshot.mode != 'RGBA':
            self.screenshot = self.screenshot.convert('RGBA')

        if dialog.mode != 'RGBA':
            dialog = dialog.convert('RGBA')

        # 缩放
        max_width = int(self.width * max_ratio)
        max_height = int(self.height * max_ratio)
        scale = min(max_width / dialog.width, max_height / dialog.height, 1.0)

        if scale < 1.0:
            new_size = (int(dialog.width * scale), int(dialog.height * scale))
            dialog = dialog.resize(new_size, Image.Resampling.LANCZOS)
            print(f"  ℹ 弹窗已缩放: {scale:.2%} -> {new_size}")

        # 居中
        x = (self.width - dialog.width) // 2
        y = (self.height - dialog.height) // 2

        result = self.screenshot.copy()
        result.paste(dialog, (x, y), dialog)

        print(f"  ℹ 弹窗合成位置: ({x}, {y}), 尺寸: {dialog.size}")
        return result

    def _add_overlay_mask(self, opacity: int = 128) -> None:
        """添加全屏半透明遮罩"""
        mask = Image.new('RGBA', (self.width, self.height), (0, 0, 0, opacity))
        self.screenshot = Image.alpha_composite(self.screenshot, mask)

    def _create_basic_dialog(self, component: dict, width: int, height: int) -> Image.Image:
        """创建基础弹窗（使用 PIL 直接绘制）"""
        style = component.get('style', 'info')
        text = component.get('text', '提示')

        dialog = Image.new('RGBA', (width, height), (255, 255, 255, 255))
        draw = ImageDraw.Draw(dialog)

        # 边框
        draw.rectangle([0, 0, width - 1, height - 1], outline='#DDDDDD', width=1)

        # 标题颜色
        title_color = {
            'error': '#FF4D4F',
            'warning': '#FAAD14',
            'info': '#1890FF',
            'success': '#52C41A'
        }.get(style, '#333333')

        # 简单文字（使用默认字体）
        if text:
            draw.text((width // 2, 30), text, fill=title_color, anchor='mt')

        # 确定按钮
        btn_y = height - 50
        btn_x = (width - 80) // 2
        draw.rectangle([btn_x, btn_y, btn_x + 80, btn_y + 36], fill='#1890FF')
        draw.text((btn_x + 40, btn_y + 18), '确定', fill='#FFFFFF', anchor='mm')

        return dialog

    def generate_dialog_and_merge(
        self,
        screenshot_path: str,
        instruction: str
    ) -> Image.Image:
        """
        直接生成异常弹窗并合并到截图

        Args:
            screenshot_path: 原始截图路径
            instruction: 异常指令

        Returns:
            合成后的截图
        """
        print(f"  正在生成异常弹窗...")

        if not self.semantic_generator:
            raise RuntimeError("语义弹窗生成器未初始化")

        dialog, content = self.semantic_generator.generate(
            ui_json=self.ui_json,
            instruction=instruction,
            screenshot_path=screenshot_path,
            mode='ai'
        )

        print(f"  ✓ 弹窗已生成: {content.get('title')}")

        result = self._merge_dialog_center(dialog)
        self.screenshot = result

        return result

    def apply_patch(self, patch: dict) -> Image.Image:
        """
        应用 Patch（仅支持 add 操作）

        Args:
            patch: UI-Edit-Action 字典

        Returns:
            修改后的截图
        """
        actions = patch.get('actions', [])
        instruction = patch.get('metadata', {}).get('instruction', '')

        add_actions = [a for a in actions if a.get('type') == 'add']
        other_actions = len(actions) - len(add_actions)

        if other_actions > 0:
            print(f"  ⚠ 忽略 {other_actions} 个非 add 操作")

        print(f"  执行 {len(add_actions)} 个 add 操作:")

        for action in add_actions:
            self.apply_add(action, instruction=instruction)

        return self.screenshot

    def save(self, output_path: str) -> None:
        """保存结果"""
        if output_path.lower().endswith('.jpg') or output_path.lower().endswith('.jpeg'):
            self.screenshot.convert('RGB').save(output_path)
        else:
            self.screenshot.save(output_path)


def main():
    parser = argparse.ArgumentParser(description='异常弹窗渲染引擎')
    parser.add_argument('--screenshot', '-s', required=True, help='原始截图路径')
    parser.add_argument('--ui-json', '-u', required=True, help='UI-JSON 文件路径')
    parser.add_argument('--patch', '-p', required=True, help='JSON Patch 文件路径')
    parser.add_argument('--output', '-o', help='输出图片路径')
    parser.add_argument('--fonts-dir', help='字体目录')
    parser.add_argument('--api-key', help='VLM API 密钥')
    parser.add_argument('--gt-dir', help='GT样本目录')
    parser.add_argument('--vlm-api-url',
                        default='https://api.openai-next.com/v1/chat/completions',
                        help='VLM API 端点')
    parser.add_argument('--vlm-model', default='gpt-4o', help='VLM 模型名称')
    parser.add_argument('--reference', '-r', help='参考弹窗图片路径')

    args = parser.parse_args()

    with open(args.patch, 'r', encoding='utf-8') as f:
        patch = json.load(f)

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

    renderer.apply_patch(patch)

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
