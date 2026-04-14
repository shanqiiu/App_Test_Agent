# 渲染器模块
# 负责生成各类异常 UI 效果

from .base import BaseRenderer, RenderResult
from .area_loading import AreaLoadingRenderer
from .content_duplicate import ContentDuplicateRenderer
from .patch import PatchRenderer
from .text_overlay import TextOverlayRenderer

__all__ = [
    "BaseRenderer",
    "RenderResult",
    "AreaLoadingRenderer",
    "ContentDuplicateRenderer",
    "PatchRenderer",
    "TextOverlayRenderer",
]
