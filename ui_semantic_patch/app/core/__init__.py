"""
core/__init__.py - 核心数据类型定义
"""

from .schemas import (
    # UI组件
    UIComponent,
    UIComponentGroup,
    Stage1Output,
    Stage2Output,
    # GT模板
    GTMeta,
    AnomalySample,
    GTCategory,
    # 渲染器
    TextStyle,
    EditOp,
    RenderResult,
    RenderConfig,
    # 注入决策
    InjectionDecision,
    InjectionContext,
    StepRecord,
    # Schema验证
    validate_stage1_output,
    validate_stage2_output,
    validate_gt_meta,
    load_json_with_schema,
    convert_legacy_format,
)

__all__ = [
    'UIComponent',
    'UIComponentGroup',
    'Stage1Output',
    'Stage2Output',
    'GTMeta',
    'AnomalySample',
    'GTCategory',
    'TextStyle',
    'EditOp',
    'RenderResult',
    'RenderConfig',
    'InjectionDecision',
    'InjectionContext',
    'StepRecord',
    'validate_stage1_output',
    'validate_stage2_output',
    'validate_gt_meta',
    'load_json_with_schema',
    'convert_legacy_format',
]
