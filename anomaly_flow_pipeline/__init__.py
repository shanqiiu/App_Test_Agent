"""
anomaly_flow_pipeline — 独立异常注入与 Flow 模板转换工具链

5 Phase 管道:
  Phase 0: UTG 预处理器 — 去重合并 + 动作驱动重写 + 数据对齐 + 页面补齐
  Phase 1: 异常注入器 — 上下文感知改写 + 相邻步联动 + 多步注入
  Phase 2: Flow 转换器 — targetPage 映射 + mockInstances 数据绑定
  Phase 3: 质量验证器 — Schema 校验 + 连贯性 + 可读性 + 5维评分
  Phase 4: 报告输出 — 各环节质量指标

使用方式:
    from anomaly_flow_pipeline.core.utg_preprocessor import UTGPreprocessor
    from anomaly_flow_pipeline.core.utg_anomaly_injector import UTGAnomalyInjector
    from anomaly_flow_pipeline.core.flow_converter import FlowConverter
    from anomaly_flow_pipeline.core.quality_validator import QualityValidator
"""

from .core.utg_preprocessor import UTGPreprocessor
from .core.utg_anomaly_injector import UTGAnomalyInjector
from .core.flow_converter import FlowConverter
from .core.quality_validator import QualityValidator

__all__ = [
    "UTGPreprocessor",
    "UTGAnomalyInjector",
    "FlowConverter",
    "QualityValidator",
]
