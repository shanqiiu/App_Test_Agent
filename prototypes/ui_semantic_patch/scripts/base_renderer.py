#!/usr/bin/env python3
"""
base_renderer.py - 异常渲染器统一接口契约

定义 BaseRenderer 抽象基类和 RenderResult 数据类，
所有异常渲染器必须继承 BaseRenderer 并实现 render() 方法。

渲染器层级：
    BaseRenderer (抽象基类)
    ├── PatchRenderer          (dialog 模式 - meta-driven 弹窗合成)
    ├── AreaLoadingRenderer    (area_loading 模式 - 区域加载图标覆盖)
    ├── ContentDuplicateRenderer (content_duplicate 模式 - 内容重复浮层)
    └── TextOverlayRenderer    (text_overlay 模式 - 局部文字精确编辑)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from PIL import Image


@dataclass
class RenderResult:
    """
    渲染结果统一数据结构

    Attributes:
        image:       最终合成图像（PIL Image 对象）
        output_path: 已写入磁盘的文件路径
        metadata:    渲染过程元数据（耗时、参数、告警等）
    """
    image: Image.Image
    output_path: str
    metadata: dict = field(default_factory=dict)


class BaseRenderer(ABC):
    """
    所有异常渲染器的统一接口契约

    子类必须实现 render() 方法，返回 RenderResult。
    各渲染器原有的内部方法（如 render_area_loading、render_all 等）
    保留不删，render() 作为外层标准入口。

    注意：
    - TextOverlayRenderer 的 render() 通过 kwargs['screenshot_path'] 获取文件路径，
      因其内部 render_all() 接受路径字符串而非 PIL Image 对象。
    - 需要额外参数的渲染器通过 **kwargs 传递（如 gt_category、anomaly_type 等）。
    """

    @abstractmethod
    def render(
        self,
        screenshot: Image.Image,
        ui_json: dict,
        instruction: str,
        output_dir: str,
        **kwargs,
    ) -> RenderResult:
        """
        执行异常渲染，返回统一结果对象。

        Args:
            screenshot:   原始截图（PIL Image）
            ui_json:      Stage 2 输出的 UI-JSON 结构
            instruction:  自然语言异常描述
            output_dir:   输出目录路径
            **kwargs:     各渲染器专有参数（见各子类文档）

        Returns:
            RenderResult 包含最终图像、文件路径和元数据
        """
        ...
