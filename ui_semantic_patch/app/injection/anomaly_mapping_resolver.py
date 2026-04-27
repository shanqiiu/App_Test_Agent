"""
异常注入映射解析器

基于任务描述（query）和app_name，从配置文件中查找对应的异常注入参数，
替代VLM的不稳定判定，保证注入参数的可靠性和透明性。
"""

import json
import re
from pathlib import Path
from typing import Dict, Optional, List


class AnomalyMappingResolver:
    """
    异常注入映射解析器

    根据 query 和 app_name 从映射配置中查找对应的异常注入参数。
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化映射解析器

        Args:
            config_path: 映射配置文件路径，默认使用项目内置配置
        """
        if config_path is None:
            # 默认配置路径
            config_path = Path(__file__).parent.parent.parent / "config" / "query_anomaly_mapping.json"

        self.config_path = Path(config_path)
        self.mappings: List[Dict] = []
        self.fallback_config: Dict = {}

        self._load_config()

    def _load_config(self) -> None:
        """加载映射配置文件"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"映射配置文件不存在: {self.config_path}")

        with open(self.config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        self.mappings = config.get('mappings', [])
        self.fallback_config = config.get('fallback_config', {})

        print(f"✓ 加载映射配置: {len(self.mappings)} 条规则")

    def resolve(
        self,
        query: str,
        app_name: Optional[str] = None
    ) -> Optional[Dict]:
        """
        解析异常注入参数

        Args:
            query: 任务描述（如"在瑞幸咖啡App点一杯生椰拿铁"）
            app_name: 应用名称（如"瑞幸咖啡"），优先级高于query匹配

        Returns:
            {
                "anomaly_mode": str,
                "gt_category": str,
                "gt_sample": str,
                "reference_path": str,
                "instruction": str,
                "matched_by": str  # "app_name" or "query_pattern" or "fallback"
            }
            如果没有匹配则返回 None
        """
        # 优先使用 app_name 匹配
        if app_name:
            for mapping in self.mappings:
                if mapping.get('app_name') == app_name:
                    result = self._build_result(mapping, "app_name")
                    print(f"✓ 通过 app_name 匹配: {app_name}")
                    return result

        # 其次使用 query_pattern 匹配
        for mapping in self.mappings:
            pattern = mapping.get('query_pattern', '')
            if pattern and pattern in query:
                result = self._build_result(mapping, "query_pattern")
                print(f"✓ 通过 query_pattern 匹配: {pattern}")
                return result

        # 尝试模糊匹配（使用正则表达式）
        for mapping in self.mappings:
            pattern = mapping.get('query_pattern', '')
            if pattern and re.search(pattern, query, re.IGNORECASE):
                result = self._build_result(mapping, "query_pattern_fuzzy")
                print(f"✓ 通过 query_pattern 模糊匹配: {pattern}")
                return result

        # 使用fallback配置
        if self.fallback_config:
            result = self._build_result(self.fallback_config, "fallback")
            print(f"⚠ 使用 fallback 配置")
            return result

        print(f"✗ 未找到匹配的映射配置")
        return None

    def _build_result(self, mapping: Dict, matched_by: str) -> Dict:
        """
        构建返回结果

        Args:
            mapping: 映射配置项
            matched_by: 匹配方式

        Returns:
            标准化的返回结果
        """
        injection_config = mapping.get('injection_config', {})

        return {
            "anomaly_mode": injection_config.get('anomaly_mode'),
            "gt_category": injection_config.get('gt_category'),
            "gt_sample": injection_config.get('gt_sample'),
            "reference_path": injection_config.get('reference_path'),
            "instruction": injection_config.get('instruction'),
            "matched_by": matched_by,
            "priority": mapping.get('priority', 0)
        }

    def get_available_apps(self) -> List[str]:
        """获取所有支持的应用名称"""
        return list(set(m.get('app_name') for m in self.mappings if m.get('app_name')))

    def get_available_patterns(self) -> List[str]:
        """获取所有支持的query模式"""
        return [m.get('query_pattern') for m in self.mappings if m.get('query_pattern')]

    def get_mapping_by_app(self, app_name: str) -> Optional[Dict]:
        """
        根据应用名称获取映射配置

        Args:
            app_name: 应用名称

        Returns:
            映射配置，如果不存在则返回 None
        """
        for mapping in self.mappings:
            if mapping.get('app_name') == app_name:
                return mapping
        return None

    def reload(self) -> None:
        """重新加载配置文件"""
        self._load_config()
