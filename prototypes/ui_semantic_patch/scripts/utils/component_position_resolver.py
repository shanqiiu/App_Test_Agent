#!/usr/bin/env python3
"""
component_position_resolver.py - UI组件精确定位解析器

功能：
1. 从instruction中提取目标组件关键词
2. 在UI-JSON组件列表中搜索匹配的组件
3. 根据dialog_position类型计算相对于目标组件的弹窗位置
"""

from typing import Optional, Dict, List, Tuple
import re


class ComponentPositionResolver:
    """
    UI组件精确定位解析器

    Usage:
        resolver = ComponentPositionResolver(ui_json, screen_width, screen_height)
        position = resolver.resolve_position(
            instruction="作品控件处增加下拉弹窗",
            dialog_position="bottom-left-inline",
            dialog_width=200,
            dialog_height=100
        )
        # Returns: {'x': 48, 'y': 1496, 'matched_component': {...}, 'match_type': 'text_contains'}
    """

    # 目标关键词提取正则模式（按优先级排序）
    KEYWORD_PATTERNS = [
        # Pattern: "X控件处"
        r'[「""]?([^「」""控件处增加弹窗下拉菜单，。]+)[」""]?控件处',
        # Pattern: "X处增加/添加/显示"
        r'[「""]?([^「」""处增加弹窗下拉菜单，。]+)[」""]?处(?:增加|添加|显示|弹出)',
        # Pattern: "在X旁边/附近/下方/上方"
        r'在[「""]?([^「」""旁边附近下方上方，。]+)[」""]?(?:旁边|附近|下方|上方|左侧|右侧)',
        # Pattern: "点击X后"
        r'点击[「""]?([^「」""后，。]+)[」""]?后',
        # Pattern: "X按钮/标签/文本/图标"
        r'[「""]?([^「」""按钮标签文本图标，。]+)[」""]?(?:按钮|标签|文本|图标|区域)',
    ]

    # dialog_position 到空间关系的映射
    POSITION_RELATIONSHIP = {
        # 组件下方
        'bottom-left-inline': 'below_left',       # 下拉菜单：下方左对齐
        'bottom-center-floating': 'below_center', # 下方居中浮动
        'bottom-fixed': 'below_fixed',            # 固定在组件底部
        'bottom-floating': 'below_floating',      # 下方浮动
        'bottom': 'below_center',
        'bottom-center': 'below_center',

        # 组件上方
        'top': 'above_center',

        # 覆盖在组件上
        'center': 'overlay_center',               # 居中覆盖
        'multi-layer': 'overlay_center',
    }

    # 组件类型中英文映射
    CLASS_NAME_MAP = {
        '按钮': ['Button', 'ImageButton'],
        '输入框': ['InputField', 'EditText', 'TextInput'],
        '图片': ['ImageView', 'Image'],
        '文本': ['TextView', 'Text'],
        '卡片': ['Card'],
        '列表': ['ListView', 'RecyclerView', 'List'],
        '导航': ['NavigationBar', 'TabBar'],
        '状态栏': ['StatusBar'],
    }

    def __init__(
        self,
        ui_json: Dict,
        screen_width: int,
        screen_height: int
    ):
        """
        初始化解析器

        Args:
            ui_json: Stage 2 过滤后的 UI-JSON
            screen_width: 截图宽度
            screen_height: 截图高度
        """
        self.ui_json = ui_json
        self.components = ui_json.get('components', [])
        self.screen_width = screen_width
        self.screen_height = screen_height

    def extract_target_keyword(self, instruction: str) -> Optional[str]:
        """
        从instruction中提取目标组件关键词

        Args:
            instruction: 用户指令，如 "作品控件处增加下拉弹窗"

        Returns:
            提取到的关键词（如 "作品"），或 None
        """
        for pattern in self.KEYWORD_PATTERNS:
            match = re.search(pattern, instruction)
            if match:
                keyword = match.group(1).strip()
                # 清理常见的前缀/后缀
                keyword = keyword.strip('的在于')
                # 过滤过长或过短的关键词
                if keyword and 1 <= len(keyword) <= 10:
                    return keyword

        return None

    def find_component_by_text(
        self,
        keyword: str,
    ) -> Optional[Tuple[Dict, str]]:
        """
        在组件列表中搜索匹配关键词的组件

        Args:
            keyword: 要搜索的关键词（如 "作品"）

        Returns:
            Tuple of (matched_component, match_type) 或 None
        """
        keyword_lower = keyword.lower()

        # 优先级 1: 精确匹配
        for comp in self.components:
            text = comp.get('text', '')
            if text and text.lower() == keyword_lower:
                return (comp, 'text_exact')

        # 优先级 2: 以关键词开头
        for comp in self.components:
            text = comp.get('text', '')
            if text and text.lower().startswith(keyword_lower):
                return (comp, 'text_startswith')

        # 优先级 3: 包含关键词
        for comp in self.components:
            text = comp.get('text', '')
            if text and keyword_lower in text.lower():
                return (comp, 'text_contains')

        # 优先级 4: 组件类型名匹配
        for comp in self.components:
            comp_class = comp.get('class', '')
            for keyword_cn, class_names in self.CLASS_NAME_MAP.items():
                if keyword_cn in keyword:
                    if comp_class in class_names:
                        return (comp, 'class_match')

        return None

    def calculate_position_relative_to_component(
        self,
        component: Dict,
        dialog_position: str,
        dialog_width: int,
        dialog_height: int,
        margin: int = 10
    ) -> Dict[str, int]:
        """
        计算相对于目标组件的弹窗位置

        Args:
            component: 匹配到的组件
            dialog_position: meta.json 中的位置类型
            dialog_width: 弹窗宽度
            dialog_height: 弹窗高度
            margin: 组件和弹窗之间的间距

        Returns:
            {'x': int, 'y': int}
        """
        bounds = component.get('bounds', {})
        comp_x = bounds.get('x', 0)
        comp_y = bounds.get('y', 0)
        comp_width = bounds.get('width', 0)
        comp_height = bounds.get('height', 0)

        relationship = self.POSITION_RELATIONSHIP.get(dialog_position, 'below_left')

        if relationship == 'below_left':
            # 下拉菜单：正下方，左对齐
            pos_x = comp_x
            pos_y = comp_y + comp_height + margin

        elif relationship == 'below_center':
            # 下方居中（相对于组件）
            pos_x = comp_x + (comp_width - dialog_width) // 2
            pos_y = comp_y + comp_height + margin

        elif relationship == 'below_floating':
            # 下方浮动，水平方向屏幕居中
            pos_x = (self.screen_width - dialog_width) // 2
            pos_y = comp_y + comp_height + margin * 3

        elif relationship == 'below_fixed':
            # 固定在组件正下方
            pos_x = (self.screen_width - dialog_width) // 2
            pos_y = comp_y + comp_height

        elif relationship == 'above_center':
            # 上方居中
            pos_x = comp_x + (comp_width - dialog_width) // 2
            pos_y = comp_y - dialog_height - margin

        elif relationship == 'overlay_center':
            # 居中覆盖在组件上
            pos_x = comp_x + (comp_width - dialog_width) // 2
            pos_y = comp_y + (comp_height - dialog_height) // 2

        else:
            # 默认：下方左对齐
            pos_x = comp_x
            pos_y = comp_y + comp_height + margin

        # 边界约束，确保弹窗不超出屏幕
        pos_x = max(0, min(pos_x, self.screen_width - dialog_width))
        pos_y = max(0, min(pos_y, self.screen_height - dialog_height))

        return {'x': pos_x, 'y': pos_y}

    def resolve_position(
        self,
        instruction: str,
        dialog_position: str,
        dialog_width: int,
        dialog_height: int
    ) -> Optional[Dict]:
        """
        主入口：从instruction解析弹窗位置

        Args:
            instruction: 用户指令
            dialog_position: meta.json 中的位置类型
            dialog_width: 弹窗宽度
            dialog_height: 弹窗高度

        Returns:
            {
                'x': int,
                'y': int,
                'matched_component': dict or None,
                'match_type': str or None,
                'keyword': str or None,
                'used_fallback': bool
            }
            如果未能匹配到组件，返回 None（由调用方使用回退逻辑）
        """
        # Step 1: 从instruction提取关键词
        keyword = self.extract_target_keyword(instruction)

        if not keyword:
            return None  # 由调用方使用回退逻辑

        # Step 2: 查找匹配的组件
        match_result = self.find_component_by_text(keyword)

        if not match_result:
            return None  # 由调用方使用回退逻辑

        component, match_type = match_result

        # Step 3: 计算位置
        position = self.calculate_position_relative_to_component(
            component=component,
            dialog_position=dialog_position,
            dialog_width=dialog_width,
            dialog_height=dialog_height
        )

        return {
            'x': position['x'],
            'y': position['y'],
            'matched_component': component,
            'match_type': match_type,
            'keyword': keyword,
            'used_fallback': False
        }


def resolve_popup_position(
    ui_json: Dict,
    instruction: str,
    dialog_position: str,
    dialog_width: int,
    dialog_height: int,
    screen_width: int,
    screen_height: int
) -> Dict:
    """
    便捷函数：解析弹窗位置（带回退逻辑）

    如果未能匹配到目标组件，自动回退到百分比定位。

    Returns:
        {
            'x': int,
            'y': int,
            'matched_component': dict or None,
            'match_type': str or None,
            'keyword': str or None,
            'used_fallback': bool
        }
    """
    resolver = ComponentPositionResolver(ui_json, screen_width, screen_height)
    result = resolver.resolve_position(
        instruction=instruction,
        dialog_position=dialog_position,
        dialog_width=dialog_width,
        dialog_height=dialog_height
    )

    if result:
        return result

    # 回退到百分比定位
    pos_x, pos_y = _calculate_fallback_position(
        dialog_position, dialog_width, dialog_height,
        screen_width, screen_height
    )

    return {
        'x': pos_x,
        'y': pos_y,
        'matched_component': None,
        'match_type': None,
        'keyword': None,
        'used_fallback': True
    }


def _calculate_fallback_position(
    dialog_position: str,
    dialog_width: int,
    dialog_height: int,
    screen_width: int,
    screen_height: int
) -> Tuple[int, int]:
    """
    回退的百分比定位计算
    （与 run_pipeline.py 中原有逻辑一致）
    """
    if dialog_position == 'center':
        pos_x = (screen_width - dialog_width) // 2
        pos_y = (screen_height - dialog_height) // 2

    elif dialog_position == 'bottom-left-inline':
        pos_x = 30
        pos_y = int(screen_height * 0.50)

    elif dialog_position == 'bottom-center-floating':
        pos_x = (screen_width - dialog_width) // 2
        pos_y = int(screen_height * 0.75)

    elif dialog_position == 'bottom-fixed':
        pos_x = (screen_width - dialog_width) // 2
        pos_y = screen_height - dialog_height - 20

    elif dialog_position == 'bottom-floating':
        pos_x = (screen_width - dialog_width) // 2
        pos_y = screen_height - dialog_height - 80

    elif dialog_position in ('bottom', 'bottom-center'):
        pos_x = (screen_width - dialog_width) // 2
        pos_y = screen_height - dialog_height - 100

    elif dialog_position == 'top':
        pos_x = (screen_width - dialog_width) // 2
        pos_y = 100

    else:  # 'multi-layer', unknown, etc.
        pos_x = (screen_width - dialog_width) // 2
        pos_y = (screen_height - dialog_height) // 2

    return pos_x, pos_y
