#!/usr/bin/env python3
"""
schemas.py - Pydantic数据模型定义

定义项目核心数据结构，提供类型安全和数据验证能力。

使用方式:
    from app.core import UIComponent, Stage1Output, validate_stage1_output

数据流:
    OmniParser → Stage1Output → Stage2Output → RenderResult
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field, field_validator, model_validator


# ==================== 枚举定义 ====================

class ComponentType(str, Enum):
    """UI组件类型枚举"""
    STATUS_BAR = "StatusBar"
    NAVIGATION_BAR = "NavigationBar"
    TEXT_VIEW = "TextView"
    BUTTON = "Button"
    IMAGE_VIEW = "ImageView"
    IMAGE_BUTTON = "ImageButton"
    CARD = "Card"
    TAB_BAR = "TabBar"
    TAB_ITEM = "TabItem"
    SEARCH_BAR = "SearchBar"
    DIALOG = "Dialog"
    AVATAR = "Avatar"
    LIST_ITEM = "ListItem"
    INPUT_FIELD = "InputField"
    UNKNOWN = "Unknown"


class AnomalyMode(str, Enum):
    """异常模式枚举"""
    DIALOG = "dialog"
    AREA_LOADING = "area_loading"
    CONTENT_DUPPLICATE = "content_duplicate"
    TEXT_OVERLAY = "text_overlay"
    MODIFY_TEXT = "modify_text"
    MODIFY_TEXT_AI = "modify_text_ai"
    MODIFY_TEXT_OCR = "modify_text_ocr"
    MODIFY_TEXT_E2E = "modify_text_e2e"


class GTMetaCategory(str, Enum):
    """GT模板类别枚举"""
    DIALOG_BLOCKING = "dialog_blocking"
    CONTENT_DUPLICATE = "content_duplicate"
    LOADING_TIMEOUT = "loading_timeout"
    IMAGE_BROKEN = "image_broken"
    NETWORK_ERROR = "network_error"
    PRICE_ANOMALY = "price_anomaly"
    EMPTY_STATE = "empty_state"


class ImageModel(str, Enum):
    """图像生成模型枚举"""
    AUTO = "auto"
    GEN = "gen"      # qwen-image-max 纯文生图
    EDIT = "edit"    # qwen-image-edit-max 图像编辑


# ==================== UI组件相关Schema ====================

class BoundingBox(BaseModel):
    """边界框坐标"""
    x1: int = Field(..., ge=0, description="左上角X坐标")
    y1: int = Field(..., ge=0, description="左上角Y坐标")
    x2: int = Field(..., gt=0, description="右下角X坐标")
    y2: int = Field(..., gt=0, description="右下角Y坐标")

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def center(self) -> Tuple[int, int]:
        return (self.x1 + self.width // 2, self.y1 + self.height // 2)

    @property
    def area(self) -> int:
        return self.width * self.height

    def to_list(self) -> List[int]:
        return [self.x1, self.y1, self.x2, self.y2]

    @classmethod
    def from_list(cls, values: List[int]) -> "BoundingBox":
        if len(values) != 4:
            raise ValueError(f"Expected 4 values, got {len(values)}")
        return cls(x1=values[0], y1=values[1], x2=values[2], y2=values[3])


class UIComponent(BaseModel):
    """
    单个UI组件

    属性:
        id: 组件唯一标识符（OmniParser输出中可能不存在，自动生成）
        index: 检测顺序索引
        component_type: 组件类型（OmniParser用'class'字段）
        bounds: 边界框坐标 [x1, y1, x2, y2]（OmniParser用'bbox'字段）
        text: 识别到的文本内容（可选）
        confidence: 检测置信度（0-1）
        ocr_text: OCR识别文本（可选）
        ocr_confidence: OCR置信度（可选）
    """
    # id可选，OmniParser不提供，自动生成
    id: Optional[str] = Field(default=None, description="组件唯一标识符")
    index: int = Field(..., ge=0, description="检测顺序索引")
    # 支持 class (OmniParser格式) 和 component_type (Schema标准)
    component_type: str = Field(default="Unknown", alias="class")
    bounds: Union[List[int], Dict[str, int], BoundingBox] = Field(
        default_factory=list,
        alias="bbox",
        description="边界框坐标 [x1, y1, x2, y2]"
    )
    # 兼容 OmniParser 的 contentDesc 字段
    text: Optional[str] = Field(default=None, description="组件文本内容")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="检测置信度")
    ocr_text: Optional[str] = Field(default=None, alias="contentDesc", description="OCR识别文本")
    ocr_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    model_config = {"populate_by_name": True}

    @field_validator("bounds", mode="before")
    @classmethod
    def parse_bounds(cls, v: Any) -> List[int]:
        if v is None:
            return [0, 0, 0, 0]
        if isinstance(v, dict):
            # OmniParser format: {x, y, width, height}
            if "width" in v and "height" in v:
                x = v.get("x", 0)
                y = v.get("y", 0)
                return [x, y, x + v["width"], y + v["height"]]
            # Alternative format: {x1, y1, x2, y2}
            return [v.get("x1", 0), v.get("y1", 0), v.get("x2", 0), v.get("y2", 0)]
        if isinstance(v, BoundingBox):
            return v.to_list()
        if isinstance(v, list):
            return v
        return [0, 0, 0, 0]

    @field_validator("component_type", mode="before")
    @classmethod
    def parse_component_type(cls, v: Any) -> str:
        if v is None:
            return "Unknown"
        return str(v)

    @model_validator(mode="after")
    def ensure_id(self) -> "UIComponent":
        """自动生成ID如果未提供"""
        if self.id is None or self.id == "":
            self.id = f"comp_{self.index}"
        return self

    @field_validator("ocr_text", mode="before")
    @classmethod
    def parse_ocr_text(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        return str(v) if v else None

    @property
    def bbox(self) -> List[int]:
        """返回边界框列表 [x1, y1, x2, y2] - 兼容OmniParser"""
        if isinstance(self.bounds, list):
            return self.bounds
        return [0, 0, 0, 0]

    @property
    def width(self) -> int:
        return self.bbox[2] - self.bbox[0] if len(self.bbox) == 4 else 0

    @property
    def height(self) -> int:
        return self.bbox[3] - self.bbox[1] if len(self.bbox) == 4 else 0


class UIComponentGroup(BaseModel):
    """
    UI组件分组

    属性:
        id: 分组唯一标识符（可选，自动生成）
        name: 分组名称（语义描述）
        indices: 包含的组件索引列表
        component_type: 分组类型（VLM用'class'字段）
        text: 合并后的语义描述
        bounds: 合并后的边界框
    """
    # id可选，VLM输出可能不提供
    id: Optional[str] = Field(default=None, description="分组唯一标识符")
    name: str = Field(..., description="分组名称（语义描述）")
    indices: List[int] = Field(default_factory=list, description="包含的组件索引")
    # 支持 class (VLM格式)
    component_type: str = Field(default="Unknown", alias="class")
    text: Optional[str] = Field(default=None, description="合并后的语义描述")

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def ensure_id(self) -> "UIComponentGroup":
        """自动生成ID如果未提供"""
        if self.id is None or self.id == "":
            self.id = f"group_{self.name[:10]}"
        return self

    def compute_bounds(self, components: List[UIComponent]) -> List[int]:
        """根据包含的组件计算合并后的边界框"""
        if not self.indices or not components:
            return [0, 0, 0, 0]

        valid_bounds = []
        for idx in self.indices:
            if idx < len(components):
                bounds = components[idx].bbox
                if bounds and len(bounds) == 4:
                    valid_bounds.append(bounds)

        if not valid_bounds:
            return [0, 0, 0, 0]

        x1 = min(b[0] for b in valid_bounds)
        y1 = min(b[1] for b in valid_bounds)
        x2 = max(b[2] for b in valid_bounds)
        y2 = max(b[3] for b in valid_bounds)

        return [x1, y1, x2, y2]


class Stage1Output(BaseModel):
    """
    Stage 1输出（OmniParser检测结果）

    属性:
        screenshot_path: 原始截图路径（OmniParser在metadata.source中）
        timestamp: 检测时间戳
        components: 检测到的UI组件列表
        total_count: 组件总数（OmniParser用componentCount）
        device_info: 设备信息（分辨率等）
        metadata: OmniParser附加信息
        componentCount: OmniParser的组件计数（兼容字段）
    """
    # screenshot_path在OmniParser中可能在metadata.source
    screenshot_path: Optional[str] = Field(default=None, description="原始截图路径")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    components: List[UIComponent] = Field(default_factory=list, description="检测到的UI组件")
    total_count: int = Field(default=0, alias="componentCount", description="组件总数")
    device_info: Optional[Dict[str, Any]] = Field(default=None, description="设备信息")
    model_version: Optional[str] = Field(default=None, description="模型版本")
    # 保留OmniParser的metadata字段
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="OmniParser附加信息")
    annotated_image: Optional[Any] = Field(default=None, description="可视化图片( PIL.Image)")

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def compute_total_count(self) -> "Stage1Output":
        """自动计算total_count"""
        if self.total_count == 0:
            self.total_count = len(self.components)
        return self

    @field_validator("screenshot_path", mode="before")
    @classmethod
    def extract_screenshot_path(cls, v: Optional[str], info) -> Optional[str]:
        if v is not None:
            return v
        # 从metadata.source提取
        metadata = info.data.get("metadata", {})
        if isinstance(metadata, dict):
            return metadata.get("source", None)
        return None

    @model_validator(mode="before")
    @classmethod
    def extract_screenshot_from_metadata(cls, data: Any) -> Any:
        """从metadata.source提取screenshot_path"""
        if isinstance(data, dict) and "metadata" in data:
            metadata = data["metadata"]
            if isinstance(metadata, dict) and "source" in metadata:
                if "screenshot_path" not in data:
                    data["screenshot_path"] = metadata["source"]
        return data

    def get_component_by_index(self, index: int) -> Optional[UIComponent]:
        """根据索引获取组件"""
        for comp in self.components:
            if comp.index == index:
                return comp
        return None

    def get_components_by_type(self, comp_type: str) -> List[UIComponent]:
        """根据类型获取组件列表"""
        return [c for c in self.components if c.component_type == comp_type]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（兼容原有JSON格式）"""
        return {
            "screenshot_path": self.screenshot_path,
            "timestamp": self.timestamp,
            "components": [
                {
                    "id": c.id,
                    "index": c.index,
                    "class": c.component_type,
                    "bounds": c.bbox,
                    "text": c.text,
                    "confidence": c.confidence,
                }
                for c in self.components
            ],
            "total_count": self.total_count,
        }


class Stage2Output(BaseModel):
    """
    Stage 2输出（VLM语义分组结果）

    属性:
        screenshot_path: 原始截图路径（可选）
        timestamp: 处理时间戳
        groups: 语义分组列表
        groups_count: 分组总数
        raw_output: VLM原始输出（用于调试）
    """
    screenshot_path: Optional[str] = Field(default=None, description="原始截图路径")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    groups: List[UIComponentGroup] = Field(default_factory=list, description="语义分组列表")
    groups_count: int = Field(default=0, description="分组总数")
    raw_output: Optional[str] = Field(default=None, description="VLM原始输出（调试用）")
    vlm_model: Optional[str] = Field(default=None, description="VLM模型名称")
    processing_time: Optional[float] = Field(default=None, ge=0, description="处理耗时(秒)")

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def compute_groups_count(self) -> "Stage2Output":
        """自动计算groups_count"""
        if self.groups_count == 0:
            self.groups_count = len(self.groups)
        return self

    def get_group_by_id(self, group_id: str) -> Optional[UIComponentGroup]:
        """根据ID获取分组"""
        for group in self.groups:
            if group.id == group_id:
                return group
        return None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（兼容原有JSON格式）"""
        return {
            "screenshot_path": self.screenshot_path,
            "timestamp": self.timestamp,
            "groups": [
                {
                    "id": g.id,
                    "name": g.name,
                    "indices": g.indices,
                    "class": g.component_type,
                    "text": g.text,
                }
                for g in self.groups
            ],
            "groups_count": self.groups_count,
        }

    @classmethod
    def from_vlm_response(cls, screenshot_path: str, vlm_output: Dict[str, Any]) -> "Stage2Output":
        """从VLM响应创建Stage2Output"""
        groups = []
        for i, g_data in enumerate(vlm_output.get("groups", [])):
            group = UIComponentGroup(
                id=g_data.get("id", f"group_{i}"),
                name=g_data.get("name", ""),
                indices=g_data.get("indices", []),
                component_type=g_data.get("class", "Unknown"),
                text=g_data.get("text"),
            )
            groups.append(group)

        return cls(
            screenshot_path=screenshot_path,
            groups=groups,
            raw_output=json.dumps(vlm_output) if isinstance(vlm_output, dict) else str(vlm_output),
        )


# ==================== GT模板相关Schema ====================

class AnomalySample(BaseModel):
    """
    异常样本定义

    属性:
        filename: 样本文件名
        description: 样本描述
        visual_features: 视觉特征描述
        applicable_scenarios: 适用场景列表
    """
    filename: str = Field(..., description="样本文件名")
    description: Optional[str] = Field(default=None, description="样本描述")
    visual_features: Optional[Dict[str, Any]] = Field(default=None, description="视觉特征")
    applicable_scenarios: List[str] = Field(default_factory=list, description="适用场景")

    @property
    def full_path(self, base_dir: Optional[Path] = None) -> Optional[Path]:
        """获取样本完整路径"""
        if base_dir:
            return base_dir / self.filename
        return Path(self.filename)


class GTCategory(BaseModel):
    """
    GT模板类别定义

    属性:
        category_id: 类别ID（如dialog_blocking）
        category_name: 类别名称（中文）
        description: 类别描述
        anomaly_mode: 对应的异常模式
        samples: 样本列表
    """
    category_id: str = Field(..., description="类别ID")
    category_name: str = Field(..., description="类别名称（中文）")
    description: Optional[str] = Field(default=None, description="类别描述")
    anomaly_mode: str = Field(..., description="对应的异常模式")
    samples: List[AnomalySample] = Field(default_factory=list, description="样本列表")

    model_config = {"populate_by_name": True}

    def get_sample(self, filename: str) -> Optional[AnomalySample]:
        """根据文件名获取样本"""
        for sample in self.samples:
            if sample.filename == filename:
                return sample
        return None


class GTMeta(BaseModel):
    """
    GT模板元数据

    属性:
        version: 元数据版本
        created_at: 创建时间
        updated_at: 更新时间
        categories: 类别列表
    """
    version: str = Field(default="1.0", description="元数据版本")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    categories: List[GTCategory] = Field(default_factory=list, description="类别列表")

    def get_category(self, category_id: str) -> Optional[GTCategory]:
        """根据ID获取类别"""
        for cat in self.categories:
            if cat.category_id == category_id:
                return cat
        return None

    def get_category_by_name(self, name: str) -> Optional[GTCategory]:
        """根据名称获取类别（支持模糊匹配）"""
        for cat in self.categories:
            if name in cat.category_name or cat.category_id == name:
                return cat
        return None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "categories": [
                {
                    "category": cat.category_id,
                    "name": cat.category_name,
                    "description": cat.description,
                    "anomaly_mode": cat.anomaly_mode,
                    "samples": [
                        {
                            "filename": s.filename,
                            "description": s.description,
                            "visual_features": s.visual_features,
                            "applicable_scenarios": s.applicable_scenarios,
                        }
                        for s in cat.samples
                    ],
                }
                for cat in self.categories
            ],
        }


# ==================== 渲染器相关Schema ====================

class TextStyle(BaseModel):
    """文字视觉风格"""
    font_size: int = Field(default=28, ge=1, description="字体大小(像素)")
    font_color: Tuple[int, int, int] = Field(default=(51, 51, 51), description="字体颜色RGB")
    font_weight: str = Field(default="regular", description="字重: regular/bold")
    bg_color: Tuple[int, int, int] = Field(default=(255, 255, 255), description="背景颜色RGB")
    line_height: int = Field(default=40, ge=1, description="行高(像素)")
    font_path: Optional[str] = Field(default=None, description="字体文件路径")


class EditOp(BaseModel):
    """单次编辑操作
    
    属性:
        action: 操作类型 (insert_text/replace_region/modify_text/add_badge/expand_card)
        region: 编辑区域坐标 {"x": int, "y": int, "width": int, "height": int}
        content: 文字内容
        target_component: 目标组件索引(UI-JSON)
        style_hint: VLM建议的风格参数
        reference_component: 用于风格采样的参考组件索引
    """
    action: str = Field(..., description="操作类型")
    region: Dict[str, int] = Field(default_factory=dict, description="编辑区域坐标")
    content: str = Field(default="", description="文字内容")
    target_component: Optional[int] = Field(default=None, description="目标组件索引")
    style_hint: Dict[str, Any] = Field(default_factory=dict, description="风格参数")
    reference_component: Optional[int] = Field(default=None, description="参考组件索引")


class RenderConfig(BaseModel):
    """
    渲染配置

    属性:
        mode: 渲染模式
        instruction: 渲染指令
        gt_category: GT类别（可选）
        gt_sample: GT样本（可选）
        reference_path: 参考图片路径（可选）
        fonts_dir: 字体目录（可选）
        image_model: 图像生成模型
    """
    mode: str = Field(default="dialog", description="渲染模式")
    instruction: str = Field(..., description="渲染指令")
    gt_category: Optional[str] = Field(default=None, description="GT类别")
    gt_sample: Optional[str] = Field(default=None, description="GT样本")
    reference_path: Optional[str] = Field(default=None, description="参考图片路径")
    fonts_dir: Optional[str] = Field(default=None, description="字体目录")
    image_model: str = Field(default="auto", description="图像生成模型")
    target_component: Optional[str] = Field(default=None, description="目标组件ID")
    edit_plan_path: Optional[str] = Field(default=None, description="编辑计划JSON路径")
    e2e_full_image: bool = Field(default=False, description="E2E整图编辑")


class PipelineResult(BaseModel):
    """
    流水线执行结果

    属性:
        success: 是否成功
        output_path: 输出文件路径
        stage1_output: Stage 1输出
        stage2_output: Stage 2输出
        final_image: 最终图像路径
        error: 错误信息（如果失败）
        timing: 各阶段耗时
    """
    success: bool = Field(..., description="是否成功")
    output_path: Optional[str] = Field(default=None, description="输出文件路径")
    stage1_output: Optional[Stage1Output] = Field(default=None, description="Stage 1输出")
    stage2_output: Optional[Stage2Output] = Field(default=None, description="Stage 2输出")
    final_image: Optional[str] = Field(default=None, description="最终图像路径")
    error: Optional[str] = Field(default=None, description="错误信息")
    timing: Dict[str, float] = Field(default_factory=dict, description="各阶段耗时(秒)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="其他元数据")


# ==================== 渲染结果Schema ====================

class RenderResult(BaseModel):
    """
    渲染结果统一数据结构
    
    属性:
        annotated_image_path: 渲染后的图片路径(存储路径而非PIL对象)
        output_path: 已写入磁盘的文件路径
        metadata: 渲染过程元数据(耗时、参数、告警等)
    """
    annotated_image_path: Optional[str] = Field(default=None, description="渲染后的图片路径")
    output_path: Optional[str] = Field(default=None, description="最终输出文件路径")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="渲染元数据")


# ==================== 注入决策相关Schema ====================

class InjectionDecision(str, Enum):
    """注入决策枚举"""
    CONTINUE = "CONTINUE"      # 继续分析
    INJECT = "INJECT"          # 注入异常
    SKIP = "SKIP"              # 跳过
    ERROR = "ERROR"            # 错误


class StepRecord(BaseModel):
    """
    步骤记录

    属性:
        step_index: 步骤索引
        screenshot_path: 截图路径
        think: 分析思考过程
        decision: 决策结果
        anomaly_type: 异常类型（如果决定注入）
        instruction: 指令内容
        conclusion: 结论
        timestamp: 时间戳
        action: 执行的动作
        context: 上下文信息
        confidence: 决策置信度
    """
    step_index: int = Field(..., ge=0, description="步骤索引")
    screenshot_path: str = Field(..., description="截图路径")
    think: str = Field(default="", description="分析思考过程")
    decision: str = Field(default="CONTINUE", description="决策结果: CONTINUE/INJECT/SKIP/ERROR")
    anomaly_type: Optional[str] = Field(default=None, description="异常类型")
    instruction: Optional[str] = Field(default=None, description="指令内容")
    conclusion: str = Field(default="", description="结论")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    action: Optional[str] = Field(default=None, description="执行的动作")
    context: Dict[str, Any] = Field(default_factory=dict, description="上下文信息")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="决策置信度")

    def to_history_entry(self) -> str:
        """转换为历史记录条目（用于 VLM 提示词）"""
        entry = f"Step {self.step_index}: <think>{self.think}</think>"
        entry += f"<decision>{self.decision}</decision>"
        if self.conclusion:
            entry += f"<conclusion>{self.conclusion}</conclusion>"
        return entry

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 JSON 序列化）"""
        return self.model_dump()


class InjectionContext(BaseModel):
    """
    注入上下文

    属性:
        task_description: 任务描述
        total_steps: 总步数
        current_step: 当前步数
        history: 历史步骤记录
        anomaly_types: 可用异常类型列表
    """
    task_description: str = Field(..., description="任务描述")
    total_steps: int = Field(default=0, ge=0, description="总步数")
    current_step: int = Field(default=0, ge=0, description="当前步数")
    history: List[StepRecord] = Field(default_factory=list, description="历史步骤记录")
    anomaly_types: List[str] = Field(default_factory=list, description="可用异常类型")
    max_history: int = Field(default=10, ge=1, description="最大历史步数")

    def add_step(self, step: StepRecord) -> None:
        """添加步骤记录"""
        self.history.append(step)
        self.current_step = step.step_index
        # 保持历史记录在限制内
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

    @property
    def recent_history(self) -> List[StepRecord]:
        """获取最近的步骤记录"""
        return self.history[-self.max_history:]


# ==================== Schema验证工具 ====================

def validate_stage1_output(data: Dict[str, Any]) -> Stage1Output:
    """
    验证并解析Stage 1输出

    Args:
        data: 原始数据字典

    Returns:
        Stage1Output实例

    Raises:
        ValidationError: 数据验证失败
    """
    return Stage1Output(**data)


def validate_stage2_output(data: Dict[str, Any]) -> Stage2Output:
    """
    验证并解析Stage 2输出

    Args:
        data: 原始数据字典

    Returns:
        Stage2Output实例

    Raises:
        ValidationError: 数据验证失败
    """
    return Stage2Output(**data)


def validate_gt_meta(data: Dict[str, Any]) -> GTMeta:
    """
    验证并解析GT元数据

    Args:
        data: 原始数据字典

    Returns:
        GTMeta实例

    Raises:
        ValidationError: 数据验证失败
    """
    return GTMeta(**data)


def load_json_with_schema(
    file_path: Union[str, Path],
    schema_class: type,
    strict: bool = False,
) -> Any:
    """
    加载JSON文件并验证Schema

    Args:
        file_path: JSON文件路径
        schema_class: Pydantic模型类
        strict: 是否严格验证

    Returns:
        验证后的模型实例

    Raises:
        FileNotFoundError: 文件不存在
        ValidationError: 数据验证失败
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return schema_class(**data)


def save_json_with_schema(
    instance: BaseModel,
    file_path: Union[str, Path],
    indent: int = 2,
) -> None:
    """
    保存实例为JSON文件

    Args:
        instance: Pydantic模型实例
        file_path: 输出文件路径
        indent: 缩进空格数
    """
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(instance.model_dump() if hasattr(instance, "model_dump") else instance.dict(), f, ensure_ascii=False, indent=indent)


# ==================== 兼容性辅助函数 ====================

def convert_legacy_format(data: Dict[str, Any], stage: int = 1) -> Union[Stage1Output, Stage2Output]:
    """
    将旧格式转换为新Schema

    兼容原有代码中的JSON格式：
    - components: [{"id": "...", "index": ..., "class": "...", "bounds": [...]}]
    - groups: [{"id": "...", "name": "...", "indices": [...], "class": "...", "text": "..."}]

    Args:
        data: 原始数据
        stage: 阶段（1或2）

    Returns:
        对应的Schema实例
    """
    if stage == 1:
        # 转换components字段
        if "components" in data:
            components = []
            for i, comp in enumerate(data["components"]):
                if isinstance(comp, dict):
                    # 处理不同的字段名
                    comp_dict = {
                        "id": comp.get("id", f"comp_{i}"),
                        "index": comp.get("index", comp.get("idx", i)),
                        "component_type": comp.get("class", comp.get("type", "Unknown")),
                        "bounds": comp.get("bounds", []),
                        "text": comp.get("text"),
                        "confidence": comp.get("confidence", 1.0),
                    }
                    components.append(UIComponent(**comp_dict))
            data["components"] = components

        # 确保必需字段有默认值
        if "screenshot_path" not in data:
            data["screenshot_path"] = "unknown"

        return Stage1Output(**data)

    elif stage == 2:
        # 转换groups字段
        if "groups" in data:
            groups = []
            for i, group in enumerate(data["groups"]):
                if isinstance(group, dict):
                    group_dict = {
                        "id": group.get("id", f"group_{i}"),
                        "name": group.get("name", ""),
                        "indices": group.get("indices", []),
                        "component_type": group.get("class", "Unknown"),
                        "text": group.get("text"),
                    }
                    groups.append(UIComponentGroup(**group_dict))
            data["groups"] = groups

        # 确保必需字段有默认值
        if "screenshot_path" not in data:
            data["screenshot_path"] = "unknown"

        return Stage2Output(**data)

    raise ValueError(f"Unknown stage: {stage}")
