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

from base_renderer import BaseRenderer, RenderResult
from utils.gt_manager import GTManager
from utils.semantic_dialog_generator import SemanticDialogGenerator


class PatchRenderer(BaseRenderer):
    """
    Patch 渲染引擎

    当前仅支持 add 操作：新增弹窗组件
    """

    def __init__(
        self,
        screenshot_path: Optional[str] = None,
        ui_json_path: Optional[str] = None,
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
            screenshot_path: 原始截图路径（可选，render() 会通过 screenshot 参数传入）
            ui_json_path:    UI-JSON 文件路径（可选，render() 会通过 ui_json 参数传入）
            fonts_dir:       字体目录（可选）
            render_mode:     渲染模式（semantic_ai / semantic_pil）
            api_key:         VLM API 密钥
            gt_dir:          GT样本目录
            vlm_api_url:     VLM API 端点
            vlm_model:       VLM 模型名称
            reference_path:  参考弹窗图片路径

        Note:
            AI 图像生成使用 DashScope API，Key 从环境变量 DASHSCOPE_API_KEY 获取
            当通过 BaseRenderer.render() 接口调用时，screenshot_path/ui_json_path 可为 None
        """
        self.screenshot_path = screenshot_path
        self.screenshot = Image.open(screenshot_path).convert('RGBA') if screenshot_path else None
        self.width, self.height = self.screenshot.size if self.screenshot else (0, 0)
        self.render_mode = render_mode
        self.api_key = api_key
        self.fonts_dir = fonts_dir
        self.vlm_api_url = vlm_api_url
        self.vlm_model = vlm_model

        if ui_json_path:
            with open(ui_json_path, 'r', encoding='utf-8') as f:
                self.ui_json = json.load(f)
        else:
            self.ui_json = {}

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

    # ==================== BaseRenderer 统一接口 ====================

    def render(
        self,
        screenshot: Image.Image,
        ui_json: dict,
        instruction: str,
        output_dir: str,
        **kwargs,
    ) -> RenderResult:
        """
        BaseRenderer 统一接口（dialog 模式 meta-driven 弹窗生成）。

        kwargs:
            screenshot_path (str): 截图文件路径（必需，供 VLM 分析使用）
            gt_category (str):     GT 异常类别（必需）
            gt_sample (str):       GT 样本文件名（必需）
            gt_dir (str):          GT 模板根目录
            reference_path (str):  参考图路径（可选）
        """
        screenshot_path = kwargs.get('screenshot_path', '')
        gt_category = kwargs.get('gt_category')
        gt_sample = kwargs.get('gt_sample')
        gt_dir = kwargs.get('gt_dir')
        reference_path = kwargs.get('reference_path')

        result_img, warnings = self._render_dialog_meta_driven(
            screenshot=screenshot,
            screenshot_path=screenshot_path,
            ui_json=ui_json,
            instruction=instruction,
            gt_category=gt_category,
            gt_sample=gt_sample,
            gt_dir=gt_dir,
            reference_path=reference_path,
        )

        output_path = Path(output_dir) / f"final_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result_img.save(str(output_path))

        metadata = {'gt_category': gt_category, 'gt_sample': gt_sample, 'meta_driven': True}
        if warnings:
            metadata['warnings'] = warnings

        return RenderResult(image=result_img, output_path=str(output_path), metadata=metadata)

    def _render_dialog_meta_driven(
        self,
        screenshot: Image.Image,
        screenshot_path: str,
        ui_json: dict,
        instruction: str,
        gt_category: str,
        gt_sample: str,
        gt_dir: str,
        reference_path: Optional[str] = None,
    ) -> Tuple[Image.Image, list]:
        """
        Meta-driven 弹窗生成核心逻辑（从 run_pipeline.py 迁移）。

        Returns:
            (合成后截图, 告警列表)
        """
        from utils.meta_loader import MetaLoader
        from utils.component_position_resolver import resolve_popup_position
        import logging
        logger = logging.getLogger(__name__)
        warnings = []

        if not (gt_category and gt_sample and gt_dir):
            logger.error("dialog 模式需要指定 gt_category、gt_sample 和 gt_dir")
            return screenshot.convert('RGB'), warnings

        meta_loader = MetaLoader(gt_dir)
        visual_style_prompt = meta_loader.extract_visual_style_prompt(gt_category, gt_sample)
        meta_features = meta_loader.extract_visual_features_dict(gt_category, gt_sample)

        if not visual_style_prompt or not meta_features:
            logger.error(f"无法加载 meta 信息: {gt_category}/{gt_sample}")
            return screenshot.convert('RGB'), warnings

        screen_width, screen_height = screenshot.size
        ref_path = reference_path or meta_loader.get_sample_path(gt_category, gt_sample)
        print(f"  参考图: {ref_path}")

        # 计算弹窗尺寸
        bounds_px = meta_features.get('dialog_bounds_px')
        if bounds_px:
            dialog_width = bounds_px['width']
            dialog_height = bounds_px['height']
            print(f"  弹窗尺寸: {dialog_width}x{dialog_height} (来源: dialog_bounds_px)")
        else:
            width_ratio = meta_features.get('dialog_width_ratio', 0.8)
            height_ratio = meta_features.get('dialog_height_ratio', 0.5)
            dialog_width = int(screen_width * width_ratio)
            dialog_height = int(screen_height * height_ratio)
            print(f"  弹窗尺寸: {dialog_width}x{dialog_height} (比例: {width_ratio}x{height_ratio})")

        # 初始化生成器
        generator = SemanticDialogGenerator(
            fonts_dir=self.fonts_dir,
            api_key=self.api_key,
            vlm_api_url=self.vlm_api_url,
            vlm_model=self.vlm_model,
            reference_path=ref_path,
        )

        # 生成语义文案
        print("  正在分析目标页面语义...")
        target_content = generator.generate_content_for_target_page(
            screenshot_path=screenshot_path,
            instruction=instruction,
            anomaly_type=meta_features.get('anomaly_type', 'promotional_dialog'),
            app_style=meta_features.get('app_style'),
        )
        if target_content:
            print(f"  ✓ 语义内容: {target_content.get('title', '')} - {target_content.get('message', '')[:30]}...")
        else:
            print("  ⚠ VLM 语义生成失败，使用默认内容")

        # 生成弹窗图像
        dialog_img = generator.generate_dialog_ai_from_meta(
            meta_semantic=visual_style_prompt,
            meta_features=meta_features,
            reference_path=ref_path,
            width=dialog_width,
            height=dialog_height,
            target_content=target_content,
        )

        if not dialog_img:
            logger.warning("弹窗图像生成失败，返回原始截图")
            return screenshot.convert('RGB'), warnings

        # 计算位置
        dialog_position = meta_features.get('dialog_position', 'center')
        position_result = resolve_popup_position(
            ui_json=ui_json,
            instruction=instruction,
            dialog_position=dialog_position,
            dialog_width=dialog_width,
            dialog_height=dialog_height,
            screen_width=screen_width,
            screen_height=screen_height,
        )

        pos_x, pos_y = position_result['x'], position_result['y']

        if position_result.get('_fallback'):
            warn_msg = f"位置回退：未找到关键词对应组件，使用百分比定位 ({pos_x}, {pos_y})"
            logger.warning(warn_msg)
            warnings.append({'type': 'position_fallback', 'message': warn_msg})
        elif position_result.get('matched_component'):
            matched = position_result['matched_component']
            print(f"  ✓ 精确定位: [{matched.get('index')}] \"{matched.get('text', '')[:20]}\" → ({pos_x}, {pos_y})")
        else:
            print(f"  ℹ 百分比定位: {dialog_position} → ({pos_x}, {pos_y})")

        # 合成图像
        result_img = screenshot.convert('RGBA')

        # 遮罩层
        if meta_features.get('overlay_enabled', True):
            overlay_opacity = int(meta_features.get('overlay_opacity', 0.7) * 255)
            overlay = Image.new('RGBA', result_img.size, (0, 0, 0, overlay_opacity))
            result_img = Image.alpha_composite(result_img, overlay)

        # 粘贴弹窗
        result_img.paste(dialog_img, (pos_x, pos_y), dialog_img)

        # 关闭按钮
        close_button_pos = meta_features.get('close_button_position', 'none')
        close_button_style = meta_features.get('close_button_style', 'gray_circle_x')
        if close_button_pos != 'none':
            button_size = max(36, min(50, dialog_width // 14))
            if close_button_pos == 'bottom-center':
                btn_x = pos_x + dialog_width // 2 - button_size // 2
                btn_y = pos_y + dialog_height + 15
            elif close_button_pos == 'top-right':
                btn_x = pos_x + dialog_width - button_size // 2
                btn_y = pos_y - button_size // 2
            elif close_button_pos == 'top-left':
                btn_x = pos_x - button_size // 2
                btn_y = pos_y - button_size // 2
            else:
                btn_x = pos_x + dialog_width // 2 - button_size // 2
                btn_y = pos_y + dialog_height + 15

            button_layer = Image.new('RGBA', result_img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(button_layer)
            bg_color = (255, 255, 255, 230) if 'white' in close_button_style else (80, 80, 80, 220)
            x_color = (150, 150, 150, 255) if 'white' in close_button_style else (255, 255, 255, 255)
            draw.ellipse([btn_x, btn_y, btn_x + button_size, btn_y + button_size], fill=bg_color)
            margin = button_size // 4
            line_width = max(2, button_size // 12)
            draw.line([(btn_x + margin, btn_y + margin), (btn_x + button_size - margin, btn_y + button_size - margin)],
                      fill=x_color, width=line_width)
            draw.line([(btn_x + margin, btn_y + button_size - margin), (btn_x + button_size - margin, btn_y + margin)],
                      fill=x_color, width=line_width)
            result_img = Image.alpha_composite(result_img, button_layer)
            print(f"  ✓ 关闭按钮: {close_button_pos} → ({btn_x}, {btn_y}), {button_size}px")

        print("  ✓ Meta-driven 弹窗合成完成")
        return result_img, warnings

    # ==================== 原有方法（保留不删） ====================

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
