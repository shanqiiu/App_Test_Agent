"""
异常注入决策模块

该模块实现基于操作序列的异常注入决策功能：
- SequenceAnalyzer: 增量式语义分析器
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

__all__ = [
    'SequenceAnalyzer',
    'AnomalyRecommender',
    'AnomalyMappingResolver',
    'SequenceRewriter',
    'QualityVerifier',
    'VerificationResult'
]
