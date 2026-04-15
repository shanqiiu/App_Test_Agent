"""
异常推荐器

读取 GT 模板库，为 VLM 提供可选异常类型及其描述。
"""

import sys
from pathlib import Path
from typing import List, Dict, Optional

# 添加 utils 目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.meta_loader import MetaLoader
from .prompts import format_anomaly_category


# 异常类型的通用描述（用于 meta.json 未提供详细描述的情况）
DEFAULT_CATEGORY_DESCRIPTIONS = {
    "弹窗覆盖原UI": {
        "description": "全屏或半屏弹窗遮挡原有界面",
        "applicable_scenarios": "广告推广、优惠券领取、系统提示、权限请求、活动推送"
    },
    "内容歧义、重复": {
        "description": "界面内容重复显示或语义冲突",
        "applicable_scenarios": "列表加载异常、数据同步错误、缓存问题"
    },
    "loading_timeout": {
        "description": "加载超时、网络错误等状态",
        "applicable_scenarios": "网络请求等待、数据加载、页面渲染"
    },
    "image_broken": {
        "description": "图片资源加载失败，显示破碎图标或占位符",
        "applicable_scenarios": "航空公司logo无法显示、座位图加载失败、机型图片损坏、广告图裂开"
    },
    "network_error": {
        "description": "网络异常提示覆盖界面，如Toast或错误横幅",
        "applicable_scenarios": "航班搜索网络超时、支付请求失败、数据同步断开、接口返回错误"
    },
    "price_anomaly": {
        "description": "价格或数值显示异常（¥0、负数、乱码、格式错乱）",
        "applicable_scenarios": "机票价格显示错误、折扣计算异常、税费显示乱码、总价不一致"
    },
    "empty_state": {
        "description": "列表或内容区域为空，显示无数据状态",
        "applicable_scenarios": "航班搜索无结果、筛选条件过严、服务器返回空列表、历史订单清空"
    }
}


class AnomalyRecommender:
    """
    异常推荐器

    职责：
    1. 读取 GT 模板库中的可用异常类型
    2. 为 VLM 提供格式化的异常类型描述
    3. 提供异常类型详情查询
    """

    def __init__(self, gt_template_dir: Path = None):
        """
        初始化异常推荐器

        Args:
            gt_template_dir: GT 模板目录路径，默认使用项目标准路径
        """
        if gt_template_dir is None:
            # 使用默认路径
            project_root = Path(__file__).parent.parent.parent
            gt_template_dir = project_root / "data" / "Agent执行遇到的典型异常UI类型" / "analysis" / "gt_templates"

        self.gt_template_dir = Path(gt_template_dir)
        self.meta_loader = MetaLoader(str(self.gt_template_dir))

        # 缓存类别信息
        self._categories_cache: Dict[str, Dict] = {}
        self._load_categories()

    def _load_categories(self) -> None:
        """加载并缓存所有类别信息"""
        for category in self.meta_loader.list_categories():
            category_info = {
                "name": category,
                "samples": self.meta_loader.list_samples(category),
                "description": DEFAULT_CATEGORY_DESCRIPTIONS.get(category, {}).get(
                    "description", "异常场景"
                ),
                "applicable_scenarios": DEFAULT_CATEGORY_DESCRIPTIONS.get(category, {}).get(
                    "applicable_scenarios", "通用场景"
                )
            }

            # 尝试从 meta.json 获取更详细的描述
            samples = category_info["samples"]
            if samples:
                sample_meta = self.meta_loader.load_sample_meta(category, samples[0])
                if sample_meta:
                    if "anomaly_description" in sample_meta:
                        category_info["description"] = sample_meta["anomaly_description"]

            self._categories_cache[category] = category_info

    def get_available_categories(self) -> List[str]:
        """获取所有可用的异常类别"""
        return list(self._categories_cache.keys())

    def get_categories_description(self) -> str:
        """
        生成 VLM 可用的异常类型列表描述

        Returns:
            格式化的异常类型描述文本
        """
        if not self._categories_cache:
            return "（未找到可用的异常类型）"

        descriptions = []
        for i, (category, info) in enumerate(self._categories_cache.items(), 1):
            desc = format_anomaly_category(
                index=i,
                category_name=category,
                description=info["description"],
                applicable_scenarios=info["applicable_scenarios"]
            )
            descriptions.append(desc)

        return "\n".join(descriptions)

    def get_category_details(self, category: str) -> Optional[Dict]:
        """
        获取指定类别的详细信息

        Args:
            category: 类别名称

        Returns:
            类别详情字典，包含 samples、description 等
        """
        return self._categories_cache.get(category)

    def get_sample_details(self, category: str, sample_name: str) -> Optional[Dict]:
        """
        获取指定样本的详细信息

        Args:
            category: 类别名称
            sample_name: 样本名称

        Returns:
            样本 meta 信息
        """
        return self.meta_loader.load_sample_meta(category, sample_name)

    def get_sample_path(self, category: str, sample_name: str) -> Optional[Path]:
        """
        获取样本文件路径

        Args:
            category: 类别名称
            sample_name: 样本名称

        Returns:
            样本文件完整路径
        """
        path = self.meta_loader.get_sample_path(category, sample_name)
        return Path(path) if path else None

    def get_default_sample(self, category: str) -> Optional[str]:
        """
        获取指定类别的默认样本名称

        Args:
            category: 类别名称

        Returns:
            第一个可用的样本名称
        """
        info = self._categories_cache.get(category)
        if info and info["samples"]:
            return info["samples"][0]
        return None

    def validate_category(self, category: str) -> bool:
        """检查类别是否存在"""
        return category in self._categories_cache

    def __repr__(self) -> str:
        return f"AnomalyRecommender(categories={len(self._categories_cache)}, dir={self.gt_template_dir})"


# 便捷函数
def create_recommender(gt_template_dir: Path = None) -> AnomalyRecommender:
    """创建异常推荐器实例"""
    return AnomalyRecommender(gt_template_dir)
