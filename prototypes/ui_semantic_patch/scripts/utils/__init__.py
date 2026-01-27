"""
utils - UI Semantic Patch 工具模块

包含：
- text_render: 文字渲染
- inpainting: 背景修复
- compositor: 图层合成
- component_generator: 大模型组件生成
- gt_manager: Ground Truth 模板管理
"""

from .text_render import TextRenderer
from .inpainting import BackgroundInpainter
from .compositor import LayerCompositor
from .component_generator import ComponentGenerator
from .gt_manager import GTManager

__all__ = ['TextRenderer', 'BackgroundInpainter', 'LayerCompositor', 'ComponentGenerator', 'GTManager']
