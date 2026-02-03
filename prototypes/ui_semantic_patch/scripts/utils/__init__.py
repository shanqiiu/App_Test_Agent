"""
utils - UI Semantic Patch 工具模块

包含：
- common: 公共工具函数
- gt_manager: Ground Truth 模板管理
- semantic_dialog_generator: 语义弹窗生成器
"""

from .gt_manager import GTManager
from .semantic_dialog_generator import SemanticDialogGenerator

__all__ = ['GTManager', 'SemanticDialogGenerator']
