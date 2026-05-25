"""
异常注入决策模块

该模块实现基于操作序列的异常注入决策功能：
- SequenceAnalyzer: 增量式语义分析器（逐帧 VLM 图像分析）
- UTGLoader: UTG 数据加载器（解析 utg.json）
- UTGDecisionMaker: UTG 文本决策器（全量 ui_summary 文本 LLM 决策）
- UTGAnomalyInjector: UTG 异常注入器（独立模块，决策注入步 + 改写 ui_summary）
- AnomalyRecommender: 异常推荐器
- AnomalyMappingResolver: 异常注入映射解析器（基于配置文件的可靠映射）
- SequenceRewriter: 序列改写器
- QualityVerifier: VLM 质量验证器（生成后验证）
- MockSequenceAnalyzer / MockSequenceRewriter: Mock 模式（不依赖生成模型）
"""

from .sequence_analyzer import SequenceAnalyzer
from .anomaly_recommender import AnomalyRecommender
from .anomaly_mapping_resolver import AnomalyMappingResolver
from .sequence_rewriter import SequenceRewriter
from .quality_verifier import QualityVerifier, VerificationResult
from .utg_loader import UTGLoader, UTGStep, load_utg
from .utg_decision import UTGDecisionMaker, make_utg_decision

# UTGAnomalyInjector 是独立模块，不依赖 injection 包内其他模块。
# 若环境缺少依赖（如 dashscope），不影响本模块导入。
try:
    from .utg_anomaly_injector import (
        UTGAnomalyInjector,
        run_anomaly_inject,
        LLMClient,
    )
except ImportError:
    # 可选依赖缺失时，将导出项设为 None
    UTGAnomalyInjector = None  # type: ignore
    run_anomaly_inject = None  # type: ignore
    LLMClient = None  # type: ignore

__all__ = [
    'SequenceAnalyzer',
    'AnomalyRecommender',
    'AnomalyMappingResolver',
    'SequenceRewriter',
    'QualityVerifier',
    'VerificationResult',
    'UTGLoader',
    'UTGStep',
    'load_utg',
    'UTGDecisionMaker',
    'make_utg_decision',
    'UTGAnomalyInjector',
    'run_anomaly_inject',
    'LLMClient',
]
