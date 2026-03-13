# 分析模块
# 负责 UI 组件检测、VLM 融合、GT 边界提取等

from .omni_extractor import omni_to_ui_json, img_to_ui_json, get_omni_parser
from .omni_vlm_fusion import omni_vlm_fusion, call_vlm_for_grouping
from .gt_bounds import extract_bounds_for_sample, extract_all_bounds
from .visualize import visualize_components

__all__ = [
    "omni_to_ui_json",
    "img_to_ui_json",
    "get_omni_parser",
    "omni_vlm_fusion",
    "call_vlm_for_grouping",
    "extract_bounds_for_sample",
    "extract_all_bounds",
    "visualize_components",
]
