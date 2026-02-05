"""
utils - UI Semantic Patch 工具模块

包含：
- common: 公共工具函数
- gt_manager: Ground Truth 模板管理
- semantic_dialog_generator: 语义弹窗生成器
- component_position_resolver: UI组件精确定位解析器
"""

from .gt_manager import GTManager
from .semantic_dialog_generator import SemanticDialogGenerator
from .component_position_resolver import ComponentPositionResolver, resolve_popup_position

__all__ = ['GTManager', 'SemanticDialogGenerator', 'ComponentPositionResolver', 'resolve_popup_position']
