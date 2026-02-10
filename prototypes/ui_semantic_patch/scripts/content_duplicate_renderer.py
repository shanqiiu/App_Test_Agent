#!/usr/bin/env python3
"""
content_duplicate_renderer.py - 内容歧义/重复异常渲染器

功能：生成"UI元素重复显示"场景，创建底部浮层显示与页面已有组件相同或扩展的内容。

典型场景：
- 选集列表同时显示在页面内和底部浮层
- 筛选器/Tab同时出现两处
- 功能按钮重复显示导致操作歧义

两种模式：
- simple_crop: 直接裁剪原组件放入底部浮层（快速、无AI依赖）
- expanded_view: AI生成扩展视图（如6集→18集网格）
"""

import os
import re
import json
import base64
import requests
from typing import Dict, List, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pathlib import Path

# DashScope API Key（优先使用环境变量）
DASHSCOPE_API_KEY = os.environ.get('DASHSCOPE_API_KEY')


class ContentDuplicateRenderer:
    """内容重复异常渲染器 - 生成底部浮层复制/扩展现有UI组件"""

    def __init__(
        self,
        api_key: str = None,
        vlm_api_url: str = 'https://api.openai-next.com/v1/chat/completions',
        vlm_model: str = 'gpt-4o',
        fonts_dir: str = None
    ):
        """
        初始化渲染器

        Args:
            api_key: API密钥（VLM和DashScope）
            vlm_api_url: VLM API地址
            vlm_model: VLM模型名称
            fonts_dir: 字体目录路径
        """
        self.api_key = api_key or DASHSCOPE_API_KEY
        self.vlm_api_url = vlm_api_url
        self.vlm_model = vlm_model
        self.fonts_dir = fonts_dir
        self._style_cache = {}

    # ==================== 组件查找 ====================

    def find_duplicatable_component(
        self,
        ui_json: Dict,
        instruction: str
    ) -> Optional[Dict]:
        """
        从UI-JSON中查找可复制的目标组件

        Args:
            ui_json: Stage 2 过滤后的UI结构
            instruction: 用户指令（如"选集控件处显示重复列表"）

        Returns:
            匹配的组件dict，包含 bounds, text, class 等信息
        """
        if not ui_json:
            return None

        components = ui_json.get('components', [])
        if not components:
            return None

        # 提取关键词
        keyword = self._extract_keyword(instruction)
        if not keyword:
            # 尝试通用关键词
            keyword = self._extract_generic_keyword(instruction)

        if not keyword:
            print(f"  ⚠ 无法从指令中提取目标组件关键词")
            return None

        print(f"  提取关键词: \"{keyword}\"")

        # 在组件中搜索匹配项
        for match_type in ['exact', 'startswith', 'contains', 'class']:
            for comp in components:
                text = comp.get('text', '')
                comp_class = comp.get('class', '')

                if match_type == 'exact' and text == keyword:
                    return self._enrich_component(comp, 'exact', keyword)
                elif match_type == 'startswith' and text.startswith(keyword):
                    return self._enrich_component(comp, 'startswith', keyword)
                elif match_type == 'contains' and keyword in text:
                    return self._enrich_component(comp, 'contains', keyword)
                elif match_type == 'class' and keyword in comp_class:
                    return self._enrich_component(comp, 'class', keyword)

        print(f"  ⚠ 未找到匹配组件: \"{keyword}\"")
        return None

    def _extract_keyword(self, instruction: str) -> Optional[str]:
        """从指令中提取目标组件关键词"""
        patterns = [
            r'[「""]?([^「」""控件处重复]+)[」""]?控件处',
            r'[「""]?([^「」""处重复显示]+)[」""]?处(?:重复|显示|弹出)',
            r'([选集列表筛选标签Tab]+)(?:重复|控件)',
            r'(?:重复|复制)[「""]?([^「」""]+)[」""]?',
        ]

        for pattern in patterns:
            match = re.search(pattern, instruction)
            if match:
                keyword = match.group(1).strip()
                if keyword and len(keyword) <= 10:
                    return keyword

        return None

    def _extract_generic_keyword(self, instruction: str) -> Optional[str]:
        """提取通用组件类型关键词"""
        generic_keywords = ['选集', '列表', '筛选', '标签', 'Tab', '按钮', '菜单']
        for kw in generic_keywords:
            if kw in instruction:
                return kw
        return None

    def _enrich_component(self, comp: Dict, match_type: str, keyword: str) -> Dict:
        """丰富组件信息"""
        enriched = comp.copy()
        enriched['_match_type'] = match_type
        enriched['_keyword'] = keyword
        return enriched

    def analyze_component_type(self, component: Dict) -> str:
        """
        分析组件类型以确定渲染策略

        Returns:
            'episode_selector' | 'tab_bar' | 'filter_chips' | 'horizontal_list' | 'generic'
        """
        text = component.get('text', '').lower()
        comp_class = component.get('class', '').lower()

        # 选集/集数选择器
        if any(kw in text for kw in ['选集', '集', '第', '更新']):
            return 'episode_selector'

        # Tab栏
        if 'tab' in comp_class or any(kw in text for kw in ['标签', '推荐', '热门', '最新']):
            return 'tab_bar'

        # 筛选标签
        if any(kw in text for kw in ['筛选', '排序', '分类']):
            return 'filter_chips'

        # 横向列表
        if 'list' in comp_class or 'recycler' in comp_class:
            return 'horizontal_list'

        return 'generic'

    # ==================== 模式1: 简单裁剪 ====================

    def render_simple_crop(
        self,
        screenshot: Image.Image,
        component: Dict,
        meta_features: Dict
    ) -> Optional[Image.Image]:
        """
        简单复制模式：裁剪原组件并放入底部浮层

        Args:
            screenshot: 原始截图
            component: 目标组件信息（含bounds）
            meta_features: meta.json中的视觉特性配置

        Returns:
            合成后的图像
        """
        try:
            bounds = component.get('bounds', {})
            if not bounds:
                print("  ⚠ 组件缺少bounds信息")
                return None

            # 解析bounds
            x = bounds.get('x', 0)
            y = bounds.get('y', 0)
            w = bounds.get('width', 0)
            h = bounds.get('height', 0)

            if w <= 0 or h <= 0:
                print(f"  ⚠ 组件bounds无效: {bounds}")
                return None

            # 扩展裁剪区域（包含周围上下文）
            expand_h = int(h * 1.5)  # 高度扩展150%
            expand_w = int(w * 0.1)   # 宽度两侧各扩展10%

            crop_x1 = max(0, x - expand_w)
            crop_y1 = max(0, y - int(h * 0.25))
            crop_x2 = min(screenshot.width, x + w + expand_w)
            crop_y2 = min(screenshot.height, y + h + expand_h)

            # 裁剪组件区域
            cropped = screenshot.crop((crop_x1, crop_y1, crop_x2, crop_y2))
            print(f"  ✓ 裁剪组件区域: ({crop_x1}, {crop_y1}) - ({crop_x2}, {crop_y2})")

            # 创建底部浮层
            screen_width = screenshot.width
            screen_height = screenshot.height

            # 计算组件底部位置
            component_bottom_y = y + h
            print(f"  组件底部位置: {component_bottom_y}")

            sheet_image, sheet_x, sheet_y = self._create_bottom_sheet(
                content=cropped,
                meta_features=meta_features,
                screen_width=screen_width,
                screen_height=screen_height,
                title=component.get('text', '')[:20],
                component_bottom_y=component_bottom_y  # 传递组件底部位置
            )

            # 合成图像
            result = self._composite_with_overlay(
                screenshot=screenshot,
                bottom_sheet=sheet_image,
                sheet_x=sheet_x,
                sheet_y=sheet_y,
                meta_features=meta_features
            )

            return result

        except Exception as e:
            print(f"  ✗ simple_crop渲染失败: {e}")
            return None

    # ==================== 模式2: 扩展视图（AI生成）====================

    def _analyze_reference_style(self, reference_path: str) -> Optional[Dict]:
        """
        使用 VLM 分析参考图的底部浮层视觉风格

        从参考图中提取：颜色、布局、字体大小、间距等风格参数
        用于指导 PIL 绘制，实现真正的风格迁移

        Args:
            reference_path: 参考图路径

        Returns:
            {
                'background_color': '#1A1A1A',
                'primary_color': '#FF6600',
                'text_color': '#FFFFFF',
                'secondary_text_color': '#999999',
                'grid_columns': 6,
                'cell_border_radius': 8,
                'cell_background': '#3A3A3A',
                'selected_background': '#4A3A35',
                'has_vip_badge': True,
                'vip_badge_color': '#B4964F',
                'title_visible': True,
                'close_button_style': 'circle_x',
                'overlay_opacity': 0.5
            }
        """
        if not self.api_key or not reference_path:
            return None

        try:
            from pathlib import Path
            if not Path(reference_path).exists():
                print(f"  ⚠ 参考图不存在: {reference_path}")
                return None

            # 读取参考图
            with open(reference_path, 'rb') as f:
                img_base64 = base64.b64encode(f.read()).decode('utf-8')

            prompt = """分析这张移动App截图中底部浮层/弹出面板的视觉风格。

请仔细观察并提取以下样式参数，返回JSON格式：
{
    "background_color": "浮层背景色 #hex格式",
    "primary_color": "主色调/选中态颜色 #hex格式",
    "text_color": "主要文字颜色 #hex格式",
    "secondary_text_color": "次要文字颜色 #hex格式",
    "grid_columns": 网格列数(整数),
    "cell_border_radius": 单元格圆角大小(整数像素),
    "cell_background": "普通单元格背景色 #hex格式",
    "selected_background": "选中单元格背景色 #hex格式",
    "has_vip_badge": 是否有VIP/会员标签(true/false),
    "vip_badge_color": "VIP标签背景色 #hex格式",
    "cell_height": 单元格高度估计(整数像素),
    "cell_margin": 单元格间距估计(整数像素),
    "title_visible": 是否显示标题栏(true/false),
    "close_button_visible": 是否有关闭按钮(true/false),
    "close_button_position": "关闭按钮位置(top-right/top-left/bottom-center)",
    "overlay_opacity": 遮罩透明度(0-1的小数)
}

只返回JSON，不要其他内容。基于图片实际观察填写，如果某项无法确定就使用合理的默认值。"""

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
                            {'type': 'text', 'text': prompt},
                            {
                                'type': 'image_url',
                                'image_url': {'url': f'data:image/jpeg;base64,{img_base64}'}
                            }
                        ]
                    }
                ],
                'max_tokens': 1000
            }

            response = requests.post(
                self.vlm_api_url,
                headers=headers,
                json=payload,
                timeout=60
            )

            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content']
                # 提取JSON
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    style = json.loads(json_match.group())
                    print(f"  ✓ 参考图风格提取成功")
                    return style

        except Exception as e:
            print(f"  ⚠ 参考图风格分析异常: {e}")

        return None

    def render_expanded_view(
        self,
        screenshot: Image.Image,
        screenshot_path: str,
        component: Dict,
        meta_features: Dict,
        ui_json: Dict,
        reference_path: str = None
    ) -> Optional[Image.Image]:
        """
        扩展视图模式：学习参考图样式，AI生成底部浮层

        流程（类似 SemanticDialogGenerator）：
        1. 分析参考图的底部浮层样式
        2. 分析目标截图的组件内容
        3. AI 生成匹配样式的底部浮层
        4. 覆盖到原图对应位置

        Args:
            screenshot: 原始截图
            screenshot_path: 截图文件路径
            component: 目标组件信息
            meta_features: meta.json中的视觉特性配置
            ui_json: 完整UI结构
            reference_path: 参考图路径（可选）

        Returns:
            合成后的图像
        """
        try:
            screen_width = screenshot.width
            screen_height = screenshot.height

            # 获取目标组件的位置信息（用于定位浮层）
            bounds = component.get('bounds', {})
            component_x = bounds.get('x', 0)
            component_y = bounds.get('y', 0)
            component_w = bounds.get('width', 0)
            component_h = bounds.get('height', 0)
            component_bottom_y = component_y + component_h

            print(f"  目标组件位置: y={component_y}, 底部={component_bottom_y}")

            # 0. 分析参考图风格（如果提供）
            reference_style = None
            if reference_path:
                print("  分析参考图风格...")
                reference_style = self._analyze_reference_style(reference_path)
                if reference_style:
                    print(f"    背景色: {reference_style.get('background_color')}")
                    print(f"    主色调: {reference_style.get('primary_color')}")
                    print(f"    网格列数: {reference_style.get('grid_columns')}")

            # 1. 分析目标组件内容
            print("  分析目标组件...")
            component_analysis = self._analyze_component_content(
                screenshot_path=screenshot_path,
                component=component,
                ui_json=ui_json
            )

            if not component_analysis:
                # 使用默认分析
                component_analysis = {
                    'component_type': self.analyze_component_type(component),
                    'items': ['1', '2', '3', '4', '5', '6'],
                    'title': component.get('text', '')[:20],
                    'total_count': '36 集全',
                    'style_hints': {}
                }

            # 将参考图风格合并到 style_hints
            if reference_style:
                component_analysis['style_hints'] = {
                    **component_analysis.get('style_hints', {}),
                    **reference_style
                }

            print(f"  ✓ 组件分析: {component_analysis.get('component_type')} - {component_analysis.get('title')}")

            # 2. 计算底部浮层尺寸
            # 关键：浮层放在组件下方，高度根据可用空间动态调整
            margin_top = 10  # 浮层与组件的间距
            available_height = screen_height - component_bottom_y - margin_top

            # 浮层最大高度不超过可用空间，最小保证基本显示
            min_sheet_height = 300
            max_sheet_height = int(screen_height * 0.65)
            sheet_height = min(max(min_sheet_height, int(available_height * 0.95)), max_sheet_height)

            print(f"  可用空间: {available_height}px, 浮层高度: {sheet_height}px")

            sheet_width = screen_width
            content_width = int(sheet_width * 0.95)
            content_height = int(sheet_height * 0.85)

            # 3. 生成底部浮层内容
            # 对于选集类型，PIL生成更精确（使用提取的风格参数）
            print("  生成底部浮层内容...")
            expanded_content = None
            comp_type = component_analysis.get('component_type', 'generic')

            if comp_type == 'episode_selector':
                # 选集类型：使用 PIL 生成（应用参考图风格）
                style_source = "参考图风格" if reference_style else "默认风格"
                print(f"  使用 PIL 生成选集网格（{style_source}）")
                expanded_content = self._generate_expanded_content_pil(
                    component_analysis=component_analysis,
                    meta_features=meta_features,
                    target_width=content_width,
                    target_height=content_height,
                    reference_style=reference_style
                )
            else:
                # 其他类型：尝试 AI 生成
                expanded_content = self._generate_bottom_sheet_ai(
                    component_analysis=component_analysis,
                    meta_features=meta_features,
                    target_width=content_width,
                    target_height=content_height,
                    reference_path=reference_path
                )

            # AI 失败时回退到 PIL
            if not expanded_content:
                print("  回退到 PIL 生成")
                expanded_content = self._generate_expanded_content_pil(
                    component_analysis=component_analysis,
                    meta_features=meta_features,
                    target_width=content_width,
                    target_height=content_height,
                    reference_style=reference_style
                )

            if not expanded_content:
                print("  ✗ 内容生成失败")
                return None

            # 4. 创建底部浮层（带标题和关闭按钮）
            title = component_analysis.get('title', '')
            total_count = component_analysis.get('total_count', '')
            sheet_title = f"{title} {total_count}".strip() if title else None

            sheet_image, sheet_x, sheet_y = self._create_bottom_sheet(
                content=expanded_content,
                meta_features=meta_features,
                screen_width=screen_width,
                screen_height=screen_height,
                title=sheet_title,
                component_bottom_y=component_bottom_y  # 传递组件底部位置
            )

            # 5. 合成图像（遮罩只覆盖浮层上方）
            result = self._composite_with_overlay(
                screenshot=screenshot,
                bottom_sheet=sheet_image,
                sheet_x=sheet_x,
                sheet_y=sheet_y,
                meta_features=meta_features
            )

            return result

        except Exception as e:
            print(f"  ✗ expanded_view渲染失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _generate_bottom_sheet_ai(
        self,
        component_analysis: Dict,
        meta_features: Dict,
        target_width: int,
        target_height: int,
        reference_path: str = None
    ) -> Optional[Image.Image]:
        """
        使用 DashScope AI 生成底部浮层内容

        学习参考图样式，生成匹配的选集/列表面板
        """
        if not self.api_key:
            print("  ⚠ 未配置 API Key")
            return None

        try:
            comp_type = component_analysis.get('component_type', 'generic')
            items = component_analysis.get('items', [])
            total_count = component_analysis.get('total_count', '')

            # 获取颜色配置
            primary_color = meta_features.get('primary_color', '#FF6600')
            bg_color = meta_features.get('background', '#1A1A1A')

            # 扩展选集列表
            expanded_items = self._expand_episode_items(items, total_count)

            # 构建生成 Prompt - 更精确描述选集面板
            if comp_type == 'episode_selector':
                prompt = f"""A dark themed mobile video app episode selection panel screenshot.
Requirements:
- Dark gray background color ({bg_color})
- Grid layout with 6 columns showing episode numbers: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18
- Each episode is a rounded rectangle button with number inside
- Episode 1 has orange ({primary_color}) border indicating selected state
- Episodes 3 and above have small golden "VIP" badge in top-right corner
- Clean minimalist modern mobile app UI style
- No title bar, only the episode grid content area
- Chinese video streaming app style like Mango TV or iQiyi"""
            else:
                prompt = f"""Dark themed mobile app list panel with items: {items[:8]}, modern clean style"""

            # 调用 DashScope API
            import dashscope
            from dashscope import ImageSynthesis

            dashscope.api_key = self.api_key

            # 调整尺寸为支持的格式
            size = f'{min(target_width, 1024)}*{min(target_height, 1024)}'

            rsp = ImageSynthesis.call(
                model='wanx-v1',
                prompt=prompt,
                n=1,
                size=size
            )

            if rsp.status_code == 200 and rsp.output:
                # 正确访问响应结构
                results = rsp.output.get('results', [])
                if results and len(results) > 0:
                    img_url = results[0].get('url')
                    if img_url:
                        img_resp = requests.get(img_url, timeout=30)
                        if img_resp.status_code == 200:
                            from io import BytesIO
                            generated_img = Image.open(BytesIO(img_resp.content))
                            # 调整到目标尺寸
                            if generated_img.size != (target_width, target_height):
                                generated_img = generated_img.resize(
                                    (target_width, target_height),
                                    Image.Resampling.LANCZOS
                                )
                            print(f"  ✓ AI生成成功: {generated_img.size}")
                            return generated_img.convert('RGBA')

            error_msg = rsp.message if hasattr(rsp, 'message') and rsp.message else f'status={rsp.status_code}'
            print(f"  ⚠ DashScope生成失败: {error_msg}")

        except Exception as e:
            print(f"  ⚠ AI生成异常: {e}")
            import traceback
            traceback.print_exc()

        return None

    def _analyze_component_content(
        self,
        screenshot_path: str,
        component: Dict,
        ui_json: Dict
    ) -> Optional[Dict]:
        """
        使用VLM分析组件内容和语义

        Returns:
            {
                'component_type': 'episode_selector',
                'items': ['1', '2', '3', '4', '5', '6'],
                'title': '玉茗茶骨',
                'total_count': '36集全',
                'item_pattern': 'numbered',
                'style_hints': {...}
            }
        """
        if not self.api_key:
            return None

        try:
            # 读取截图
            with open(screenshot_path, 'rb') as f:
                img_base64 = base64.b64encode(f.read()).decode('utf-8')

            bounds = component.get('bounds', {})
            component_type = self.analyze_component_type(component)

            prompt = f"""分析这个移动App截图中的UI组件。

目标组件位置: x={bounds.get('x')}, y={bounds.get('y')}, width={bounds.get('width')}, height={bounds.get('height')}
组件文本: "{component.get('text', '')}"
组件类型推测: {component_type}

请分析该组件及其上下文，返回JSON格式：
{{
  "component_type": "episode_selector|tab_bar|filter_chips|horizontal_list|generic",
  "items": ["组件中包含的各项内容"],
  "title": "组件相关的标题文本",
  "total_count": "总数信息（如36集全）",
  "item_pattern": "numbered|named|dated|mixed",
  "style_hints": {{
    "primary_color": "#颜色代码",
    "background_color": "#背景色",
    "selected_style": "描述选中态样式",
    "has_vip_badge": true/false
  }}
}}

只返回JSON，不要其他文字。"""

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
                            {'type': 'text', 'text': prompt},
                            {
                                'type': 'image_url',
                                'image_url': {'url': f'data:image/jpeg;base64,{img_base64}'}
                            }
                        ]
                    }
                ],
                'max_tokens': 1000
            }

            response = requests.post(
                self.vlm_api_url,
                headers=headers,
                json=payload,
                timeout=60
            )

            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content']
                # 提取JSON
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    return json.loads(json_match.group())

        except Exception as e:
            print(f"  VLM分析异常: {e}")

        return None

    def _expand_episode_items(self, items: List[str], total_count: str) -> List[str]:
        """扩展选集列表项"""
        # 尝试从total_count提取数字
        total_match = re.search(r'(\d+)', total_count or '')
        total = int(total_match.group(1)) if total_match else 18

        # 生成扩展的集数列表
        expanded = [str(i) for i in range(1, min(total + 1, 25))]
        return expanded

    def _generate_expanded_content_pil(
        self,
        component_analysis: Dict,
        meta_features: Dict,
        target_width: int,
        target_height: int,
        reference_style: Dict = None
    ) -> Optional[Image.Image]:
        """
        PIL程序化生成扩展视图（支持参考图风格迁移）

        Args:
            component_analysis: 组件分析结果
            meta_features: meta.json配置
            target_width: 目标宽度
            target_height: 目标高度
            reference_style: VLM从参考图提取的风格参数（可选）

        当提供 reference_style 时，使用提取的参数进行绘制，实现风格迁移
        """
        try:
            comp_type = component_analysis.get('component_type', 'generic')
            items = component_analysis.get('items', [])
            title = component_analysis.get('title', '')
            total_count = component_analysis.get('total_count', '')

            # 合并风格来源：reference_style > style_hints > meta_features > 默认值
            style = component_analysis.get('style_hints', {})
            if reference_style:
                style = {**style, **reference_style}

            # ===== 从风格参数提取绘制配置 =====

            # 背景色
            bg_color_str = style.get('background_color') or meta_features.get('background', '#2A2A2A')
            bg_color = self._parse_color(bg_color_str, (42, 42, 42))

            # 主色调（选中态）
            primary_color_str = style.get('primary_color') or meta_features.get('primary_color', '#FF6600')
            primary_rgb = self._parse_color(primary_color_str, (255, 102, 0))

            # 文字颜色
            text_color_str = style.get('text_color', '#FFFFFF')
            text_color = self._parse_color(text_color_str, (255, 255, 255))

            secondary_text_str = style.get('secondary_text_color', '#999999')
            secondary_text_color = self._parse_color(secondary_text_str, (150, 150, 150))

            # 单元格样式
            cell_bg_str = style.get('cell_background', '#3A3A3A')
            cell_bg = self._parse_color(cell_bg_str, (55, 55, 55))

            selected_bg_str = style.get('selected_background', '#4A3A35')
            selected_bg = self._parse_color(selected_bg_str, (60, 50, 45))

            # VIP标签
            has_vip = style.get('has_vip_badge', True)
            vip_color_str = style.get('vip_badge_color', '#B4964F')
            vip_color = self._parse_color(vip_color_str, (180, 140, 80))

            # 网格参数
            grid_cols = style.get('grid_columns', 6)
            cell_radius = style.get('cell_border_radius', 8)
            cell_height = style.get('cell_height', 70)
            cell_margin = style.get('cell_margin', 15)

            # ===== 创建图像 =====
            img = Image.new('RGBA', (target_width, target_height), (*bg_color, 255))
            draw = ImageDraw.Draw(img)

            # 加载字体
            try:
                font_path = self._find_font()
                font_title = ImageFont.truetype(font_path, 36) if font_path else ImageFont.load_default()
                font_subtitle = ImageFont.truetype(font_path, 28) if font_path else ImageFont.load_default()
                font_button = ImageFont.truetype(font_path, 32) if font_path else ImageFont.load_default()
                font_vip = ImageFont.truetype(font_path, 16) if font_path else ImageFont.load_default()
            except:
                font_title = ImageFont.load_default()
                font_subtitle = ImageFont.load_default()
                font_button = ImageFont.load_default()
                font_vip = ImageFont.load_default()

            if comp_type == 'episode_selector':
                # 绘制标题栏
                title_visible = style.get('title_visible', True)
                title_y = 20
                if title and title_visible:
                    draw.text((30, title_y), title, fill=(*text_color, 255), font=font_title)

                # 绘制集数信息
                if total_count and title_visible:
                    subtitle_y = title_y + 50
                    draw.text((30, subtitle_y), total_count, fill=(*secondary_text_color, 255), font=font_subtitle)

                # 绘制选集网格（使用提取的风格参数）
                self._draw_episode_grid_styled(
                    draw=draw,
                    img=img,
                    items=self._expand_episode_items(items, total_count),
                    primary_rgb=primary_rgb,
                    text_color=text_color,
                    cell_bg=cell_bg,
                    selected_bg=selected_bg,
                    vip_color=vip_color,
                    has_vip=has_vip,
                    grid_cols=grid_cols,
                    cell_radius=cell_radius,
                    cell_height=cell_height,
                    cell_margin=cell_margin,
                    font_button=font_button,
                    font_vip=font_vip,
                    width=target_width,
                    height=target_height,
                    start_y=120 if title_visible else 20
                )
            else:
                # 绘制通用列表
                self._draw_generic_list(
                    draw=draw,
                    items=items,
                    font=font_button,
                    width=target_width,
                    height=target_height
                )

            return img

        except Exception as e:
            print(f"  PIL生成异常: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _parse_color(self, color_str: str, default: Tuple[int, int, int]) -> Tuple[int, int, int]:
        """解析颜色字符串为RGB元组"""
        if isinstance(color_str, str) and color_str.startswith('#'):
            try:
                hex_color = color_str.lstrip('#')
                if len(hex_color) == 6:
                    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
            except:
                pass
        elif isinstance(color_str, (list, tuple)) and len(color_str) >= 3:
            return tuple(color_str[:3])
        return default

    def _draw_episode_grid_styled(
        self,
        draw: ImageDraw.Draw,
        img: Image.Image,
        items: List[str],
        primary_rgb: Tuple[int, int, int],
        text_color: Tuple[int, int, int],
        cell_bg: Tuple[int, int, int],
        selected_bg: Tuple[int, int, int],
        vip_color: Tuple[int, int, int],
        has_vip: bool,
        grid_cols: int,
        cell_radius: int,
        cell_height: int,
        cell_margin: int,
        font_button: ImageFont.FreeTypeFont,
        font_vip: ImageFont.FreeTypeFont,
        width: int,
        height: int,
        start_y: int = 100
    ):
        """绘制选集网格（使用动态风格参数）"""
        padding = 25
        cell_margin_h = cell_margin
        cell_margin_v = cell_margin + 5
        cell_width = (width - padding * 2 - cell_margin_h * (grid_cols - 1)) // grid_cols

        # 计算可显示的行数
        available_height = height - start_y - padding
        max_rows = available_height // (cell_height + cell_margin_v)

        for idx, item in enumerate(items[:grid_cols * max_rows]):
            row = idx // grid_cols
            col = idx % grid_cols

            x = padding + col * (cell_width + cell_margin_h)
            y = start_y + row * (cell_height + cell_margin_v)

            # 第一个为选中态
            if idx == 0:
                draw.rounded_rectangle(
                    [x, y, x + cell_width, y + cell_height],
                    radius=cell_radius,
                    fill=(*selected_bg, 255),
                    outline=primary_rgb,
                    width=2
                )
                current_text_color = primary_rgb
            else:
                draw.rounded_rectangle(
                    [x, y, x + cell_width, y + cell_height],
                    radius=cell_radius,
                    fill=(*cell_bg, 255)
                )
                current_text_color = text_color

            # 绘制集数文字
            text = str(item)
            try:
                bbox = draw.textbbox((0, 0), text, font=font_button)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
            except:
                text_w, text_h = 20, 20
            text_x = x + (cell_width - text_w) // 2
            text_y = y + (cell_height - text_h) // 2
            draw.text((text_x, text_y), text, fill=(*current_text_color, 255), font=font_button)

            # VIP标签（第3集及以后）
            if has_vip and idx >= 2:
                vip_w, vip_h = 30, 16
                vip_x = x + cell_width - vip_w - 5
                vip_y = y + 5
                draw.rounded_rectangle(
                    [vip_x, vip_y, vip_x + vip_w, vip_y + vip_h],
                    radius=3,
                    fill=(*vip_color, 255)
                )
                try:
                    vip_bbox = draw.textbbox((0, 0), "VIP", font=font_vip)
                    vip_tw = vip_bbox[2] - vip_bbox[0]
                    vip_th = vip_bbox[3] - vip_bbox[1]
                except:
                    vip_tw, vip_th = 20, 10
                draw.text(
                    (vip_x + (vip_w - vip_tw) // 2, vip_y + (vip_h - vip_th) // 2 - 1),
                    "VIP",
                    fill=(255, 255, 255, 255),
                    font=font_vip
                )

    def _draw_episode_grid_enhanced(
        self,
        draw: ImageDraw.Draw,
        img: Image.Image,
        items: List[str],
        style: Dict,
        primary_rgb: Tuple[int, int, int],
        font_button: ImageFont.FreeTypeFont,
        font_vip: ImageFont.FreeTypeFont,
        width: int,
        height: int,
        start_y: int = 100
    ):
        """绘制增强版选集网格（匹配参考图样式）"""
        # 网格参数
        cols = 6
        padding = 25
        cell_margin_h = 15
        cell_margin_v = 20
        cell_width = (width - padding * 2 - cell_margin_h * (cols - 1)) // cols
        cell_height = 70

        # 计算可显示的行数
        available_height = height - start_y - padding
        max_rows = available_height // (cell_height + cell_margin_v)

        for idx, item in enumerate(items[:cols * max_rows]):
            row = idx // cols
            col = idx % cols

            x = padding + col * (cell_width + cell_margin_h)
            y = start_y + row * (cell_height + cell_margin_v)

            # 第一个为选中态（橙色边框+浅色背景）
            if idx == 0:
                # 选中态背景
                draw.rounded_rectangle(
                    [x, y, x + cell_width, y + cell_height],
                    radius=8,
                    fill=(60, 50, 45, 255),
                    outline=primary_rgb,
                    width=2
                )
                text_color = primary_rgb
            else:
                # 普通态（深灰背景）
                draw.rounded_rectangle(
                    [x, y, x + cell_width, y + cell_height],
                    radius=8,
                    fill=(55, 55, 55, 255)
                )
                text_color = (220, 220, 220)

            # 绘制集数文字
            text = str(item)
            try:
                bbox = draw.textbbox((0, 0), text, font=font_button)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
            except:
                text_w, text_h = 20, 20
            text_x = x + (cell_width - text_w) // 2
            text_y = y + (cell_height - text_h) // 2
            draw.text((text_x, text_y), text, fill=text_color, font=font_button)

            # VIP标签（第3集及以后）
            if idx >= 2:
                vip_w, vip_h = 30, 16
                vip_x = x + cell_width - vip_w - 5
                vip_y = y + 5
                # VIP背景（金色渐变效果用纯色近似）
                draw.rounded_rectangle(
                    [vip_x, vip_y, vip_x + vip_w, vip_y + vip_h],
                    radius=3,
                    fill=(180, 140, 80, 255)
                )
                # VIP文字
                try:
                    vip_bbox = draw.textbbox((0, 0), "VIP", font=font_vip)
                    vip_tw = vip_bbox[2] - vip_bbox[0]
                    vip_th = vip_bbox[3] - vip_bbox[1]
                except:
                    vip_tw, vip_th = 20, 10
                draw.text(
                    (vip_x + (vip_w - vip_tw) // 2, vip_y + (vip_h - vip_th) // 2 - 1),
                    "VIP",
                    fill=(255, 255, 255, 255),
                    font=font_vip
                )

    def _draw_generic_list(
        self,
        draw: ImageDraw.Draw,
        items: List[str],
        font: ImageFont.FreeTypeFont,
        width: int,
        height: int
    ):
        """绘制通用列表"""
        padding = 20
        item_height = 50

        for idx, item in enumerate(items[:10]):
            y = padding + idx * item_height
            draw.text((padding, y), str(item), fill=(200, 200, 200), font=font)

    def _find_font(self) -> Optional[str]:
        """查找可用的中文字体"""
        font_candidates = [
            # 自定义字体目录
            Path(self.fonts_dir) / 'NotoSansSC-Regular.ttf' if self.fonts_dir else None,
            # Windows
            Path('C:/Windows/Fonts/msyh.ttc'),
            Path('C:/Windows/Fonts/simhei.ttf'),
            # macOS
            Path('/System/Library/Fonts/PingFang.ttc'),
            # Linux
            Path('/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc'),
        ]

        for font_path in font_candidates:
            if font_path and font_path.exists():
                return str(font_path)

        return None

    # ==================== 底部浮层创建 ====================

    def _create_bottom_sheet(
        self,
        content: Image.Image,
        meta_features: Dict,
        screen_width: int,
        screen_height: int,
        title: str = None,
        component_bottom_y: int = None
    ) -> Tuple[Image.Image, int, int]:
        """
        创建底部浮层包装器

        Args:
            content: 内部内容图像
            meta_features: 视觉特性配置
            screen_width: 屏幕宽度
            screen_height: 屏幕高度
            title: 可选标题
            component_bottom_y: 目标组件的底部Y坐标（可选）
                               如果提供，浮层将放在该位置下方而不是覆盖原组件

        Returns:
            (sheet_image, position_x, position_y)
        """
        # 浮层尺寸
        padding = 20
        title_height = 60 if title else 0
        close_btn_area = 50

        content_width = min(content.width, screen_width - padding * 2)
        content_height = min(content.height, int(screen_height * 0.6))

        # 调整内容尺寸
        if content.width != content_width or content.height != content_height:
            content = content.resize((content_width, content_height), Image.Resampling.LANCZOS)

        sheet_width = screen_width
        sheet_height = title_height + content_height + padding * 2 + close_btn_area

        # 背景样式
        bg_color_str = meta_features.get('background', '#2A2A2A')
        if isinstance(bg_color_str, str) and '#' in bg_color_str:
            # 提取颜色代码
            color_match = re.search(r'#([0-9A-Fa-f]{6})', bg_color_str)
            if color_match:
                hex_color = color_match.group(1)
                bg_color = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4)) + (255,)
            else:
                bg_color = (42, 42, 42, 255)
        else:
            bg_color = (42, 42, 42, 255)

        # 创建浮层图像
        sheet = Image.new('RGBA', (sheet_width, sheet_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(sheet)

        # 绘制圆角矩形背景
        corner_radius = 20
        draw.rounded_rectangle(
            [0, 0, sheet_width, sheet_height],
            radius=corner_radius,
            fill=bg_color
        )

        # 绘制顶部拖动条
        handle_width = 40
        handle_height = 4
        handle_x = (sheet_width - handle_width) // 2
        handle_y = 12
        draw.rounded_rectangle(
            [handle_x, handle_y, handle_x + handle_width, handle_y + handle_height],
            radius=2,
            fill=(100, 100, 100, 255)
        )

        # 绘制标题
        if title:
            try:
                font_path = self._find_font()
                title_font = ImageFont.truetype(font_path, 28) if font_path else ImageFont.load_default()
            except:
                title_font = ImageFont.load_default()

            title_y = 30
            draw.text((padding, title_y), title[:30], fill=(255, 255, 255, 255), font=title_font)

        # 粘贴内容
        content_x = (sheet_width - content_width) // 2
        content_y = title_height + padding
        sheet.paste(content, (content_x, content_y))

        # 绘制关闭按钮
        close_pos = meta_features.get('close_button_position', 'top-right')
        close_style = meta_features.get('close_button_style', 'circle_x')

        if close_pos != 'none':
            btn_size = 36
            if close_pos == 'top-right':
                btn_x = sheet_width - btn_size - padding
                btn_y = 20
            elif close_pos == 'bottom-center':
                btn_x = (sheet_width - btn_size) // 2
                btn_y = sheet_height - btn_size - 10
            else:
                btn_x = sheet_width - btn_size - padding
                btn_y = 20

            # 绘制关闭按钮
            if 'white' in close_style:
                btn_bg = (255, 255, 255, 230)
                btn_x_color = (100, 100, 100, 255)
            else:
                btn_bg = (80, 80, 80, 220)
                btn_x_color = (255, 255, 255, 255)

            draw.ellipse(
                [btn_x, btn_y, btn_x + btn_size, btn_y + btn_size],
                fill=btn_bg
            )

            # 绘制X
            margin = btn_size // 4
            line_width = 2
            draw.line(
                [(btn_x + margin, btn_y + margin), (btn_x + btn_size - margin, btn_y + btn_size - margin)],
                fill=btn_x_color,
                width=line_width
            )
            draw.line(
                [(btn_x + margin, btn_y + btn_size - margin), (btn_x + btn_size - margin, btn_y + margin)],
                fill=btn_x_color,
                width=line_width
            )

        # 计算浮层在屏幕上的位置
        pos_x = 0

        if component_bottom_y is not None:
            # 将浮层放在目标组件下方（留出间距）
            margin_top = 10  # 与组件的间距
            pos_y = component_bottom_y + margin_top

            # 如果浮层会超出屏幕底部，需要调整高度
            if pos_y + sheet_height > screen_height:
                # 可用高度 = 屏幕高度 - 浮层起始位置
                available_height = screen_height - pos_y
                if available_height < 200:
                    # 可用空间太小，回退到默认位置
                    pos_y = screen_height - sheet_height
                    print(f"  ℹ 可用空间不足，回退到默认底部位置")
                else:
                    # 这里只调整位置，浮层高度保持不变（因为内容已经生成）
                    # 实际高度限制应在内容生成前处理
                    pass
            print(f"  ✓ 浮层定位: 组件底部Y={component_bottom_y}, 浮层Y={pos_y}")
        else:
            # 默认放在屏幕底部
            pos_y = screen_height - sheet_height

        return sheet, pos_x, pos_y

    # ==================== 图像合成 ====================

    def _composite_with_overlay(
        self,
        screenshot: Image.Image,
        bottom_sheet: Image.Image,
        sheet_x: int,
        sheet_y: int,
        meta_features: Dict
    ) -> Image.Image:
        """
        将底部浮层合成到截图上，带半透明遮罩

        关键：遮罩只覆盖浮层上方区域，保留原组件可见性

        Args:
            screenshot: 原始截图
            bottom_sheet: 底部浮层图像
            sheet_x, sheet_y: 浮层位置
            meta_features: 视觉特性配置

        Returns:
            合成后的图像
        """
        result = screenshot.convert('RGBA')

        # 添加半透明遮罩（只覆盖浮层上方区域）
        overlay_enabled = meta_features.get('overlay_enabled', True)
        overlay_opacity = meta_features.get('overlay_opacity', 0.5)

        if overlay_enabled:
            opacity_value = int(overlay_opacity * 255)
            # 只在浮层上方区域添加遮罩
            overlay = Image.new('RGBA', result.size, (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(overlay)
            # 遮罩区域：从顶部到浮层顶部
            overlay_draw.rectangle(
                [0, 0, result.width, sheet_y],
                fill=(0, 0, 0, opacity_value)
            )
            result = Image.alpha_composite(result, overlay)

        # 粘贴底部浮层
        result.paste(bottom_sheet, (sheet_x, sheet_y), bottom_sheet)

        return result

    # ==================== 主入口 ====================

    def render_content_duplicate(
        self,
        screenshot: Image.Image,
        screenshot_path: str,
        ui_json: Dict,
        instruction: str,
        meta_features: Dict,
        mode: str = 'expanded_view',
        reference_path: str = None
    ) -> Optional[Image.Image]:
        """
        内容重复异常渲染主入口

        Args:
            screenshot: 原始截图 PIL Image
            screenshot_path: 截图文件路径
            ui_json: UI-JSON结构
            instruction: 用户指令
            meta_features: meta.json中的特性配置
            mode: 'simple_crop' 或 'expanded_view'
            reference_path: 参考图路径（用于风格迁移）

        Returns:
            渲染后的异常图像
        """
        print(f"  渲染模式: {mode}")
        if reference_path:
            print(f"  参考图: {reference_path}")

        # 1. 查找目标组件
        component = self.find_duplicatable_component(ui_json, instruction)

        if not component:
            # 尝试使用meta中的duplicate_element
            dup_element = meta_features.get('duplicate_element', '')
            if dup_element:
                print(f"  使用meta配置的组件: {dup_element}")
                component = self.find_duplicatable_component(ui_json, dup_element)

        if not component:
            print("  ✗ 未找到可复制的目标组件")
            return None

        comp_type = self.analyze_component_type(component)
        print(f"  ✓ 找到目标组件: \"{component.get('text', '')[:20]}\" (类型: {comp_type})")

        # 2. 根据模式渲染
        if mode == 'simple_crop':
            return self.render_simple_crop(screenshot, component, meta_features)
        else:  # expanded_view
            return self.render_expanded_view(
                screenshot=screenshot,
                screenshot_path=screenshot_path,
                component=component,
                meta_features=meta_features,
                ui_json=ui_json,
                reference_path=reference_path
            )


# ==================== 便捷函数 ====================

def render_content_duplicate(
    screenshot_path: str,
    ui_json: Dict,
    instruction: str,
    meta_features: Dict,
    api_key: str = None,
    mode: str = 'expanded_view',
    vlm_api_url: str = 'https://api.openai-next.com/v1/chat/completions',
    vlm_model: str = 'gpt-4o',
    reference_path: str = None
) -> Optional[Image.Image]:
    """
    便捷函数：渲染内容重复异常

    Args:
        screenshot_path: 截图文件路径
        ui_json: UI-JSON结构
        instruction: 用户指令
        meta_features: meta.json中的特性配置
        api_key: API密钥
        mode: 'simple_crop' 或 'expanded_view'
        vlm_api_url: VLM API地址
        vlm_model: VLM模型名称
        reference_path: 参考图路径（用于风格迁移）

    Returns:
        渲染后的异常图像
    """
    renderer = ContentDuplicateRenderer(
        api_key=api_key,
        vlm_api_url=vlm_api_url,
        vlm_model=vlm_model
    )

    screenshot = Image.open(screenshot_path)

    return renderer.render_content_duplicate(
        screenshot=screenshot,
        screenshot_path=screenshot_path,
        ui_json=ui_json,
        instruction=instruction,
        meta_features=meta_features,
        mode=mode,
        reference_path=reference_path
    )
