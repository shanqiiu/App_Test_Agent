# ui_semantic_patch 重构设计文档

**项目**：ui_semantic_patch — 异常测试场景自动生成原型
**重构策略**：BaseRenderer 抽象基类（Strategy A）
**日期**：2026-03-06
**读者**：技术负责人 / 实施工程师

---

## 重构目标

基于工程代码说明书（`docs/plans/2026-03-06-code-manual.md`）梳理的技术债，按以下顺序推进三阶段重构：

```
Phase 1：接口统一  →  Phase 2：重叠合并  →  Phase 3：健壮性修复
```

**不在本次范围内**：
- `omni_extractor.py` / `omni_vlm_fusion.py`（AI 感知层稳定，不动）
- `batch_pipeline.py`（调用 `run_pipeline`，主入口接口不变则无需改）
- 离线工具脚本（`generate_meta`、`extract_gt_bounds`、`anomaly_sample_manager` 等）

---

## Phase 1：接口统一

### 问题

四个渲染器（`patch_renderer`、`area_loading_renderer`、`content_duplicate_renderer`、`text_overlay_renderer`）各自暴露不同的方法名和返回值格式，`run_pipeline` 用 if-elif 分支分别处理，新增渲染模式需修改主控逻辑。

### 方案

#### 新增 `scripts/base_renderer.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from PIL import Image

@dataclass
class RenderResult:
    image: Image.Image          # 最终合成图像
    output_path: str            # 写入磁盘的文件路径
    metadata: dict = field(default_factory=dict)  # 渲染过程元数据（耗时、参数等）

class BaseRenderer(ABC):
    """所有异常渲染器的统一接口契约"""

    @abstractmethod
    def render(
        self,
        screenshot: Image.Image,
        ui_json: dict,
        instruction: str,
        output_dir: str,
        **kwargs,
    ) -> RenderResult:
        """执行异常渲染，返回统一结果对象"""
        ...
```

#### 四个渲染器改动方式

各渲染器继承 `BaseRenderer`，新增 `render()` 作为标准接口的外层包装，原有方法（如 `render_area_loading`）**保留不删**，不破坏现有逻辑。

以 `AreaLoadingRenderer` 为例：

```python
class AreaLoadingRenderer(BaseRenderer):
    def render(
        self,
        screenshot: Image.Image,
        ui_json: dict,
        instruction: str,
        output_dir: str,
        **kwargs,
    ) -> RenderResult:
        component = self._resolve_component(ui_json, instruction)
        anomaly_type = kwargs.get("anomaly_type", "loading")
        image = self.render_area_loading(screenshot, component, anomaly_type)
        path = self._save(image, output_dir)
        return RenderResult(image=image, output_path=path, metadata={"anomaly_type": anomaly_type})
```

#### `run_pipeline.py` 改为策略模式路由

```python
# 改动前：if-elif 分支，各自不同调用方式
if anomaly_mode == "dialog":
    renderer = PatchRenderer(...)
    result = renderer.generate_dialog_and_merge(...)
    result.save(output_path)
elif anomaly_mode == "area_loading":
    ...

# 改动后：统一路由表
RENDERER_MAP = {
    "dialog":            PatchRenderer,
    "area_loading":      AreaLoadingRenderer,
    "content_duplicate": ContentDuplicateRenderer,
    "text_overlay":      TextOverlayRenderer,
}

renderer_cls = RENDERER_MAP[anomaly_mode]
renderer = renderer_cls(api_key=api_key, ...)
result = renderer.render(screenshot, ui_json, instruction, output_dir, **extra_kwargs)
# 统一访问：result.output_path / result.image / result.metadata
```

### 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `scripts/base_renderer.py` | **新增** | 定义 `BaseRenderer` + `RenderResult` |
| `scripts/patch_renderer.py` | 修改 | 继承 `BaseRenderer`，新增 `render()` 包装 |
| `scripts/area_loading_renderer.py` | 修改 | 继承 `BaseRenderer`，新增 `render()` 包装 |
| `scripts/content_duplicate_renderer.py` | 修改 | 继承 `BaseRenderer`，新增 `render()` 包装 |
| `scripts/text_overlay_renderer.py` | 修改 | 继承 `BaseRenderer`，新增 `render()` 包装 |
| `scripts/run_pipeline.py` | 修改 | 改为策略模式路由，读取 `RenderResult` |

---

## Phase 2：重叠合并

### 问题

风格提取逻辑分散在三处：
- `style_transfer.py`：`StyleExtractor` 独立存在，与主流水线完全解耦
- `reference_analyzer.py`：`ReferenceAnalyzer` 分析参考图颜色/布局
- `semantic_dialog_generator.py`：内部自有风格分析逻辑

### 方案

**`style_transfer.py` → 删除**，将有价值的方法迁移进 `semantic_dialog_generator`：

```python
# 新增于 semantic_dialog_generator.py
def extract_gt_style(self, sample_path: str, style_type: str = "dialog") -> dict:
    """从 GT 样本提取视觉风格（原 StyleTransferPipeline 能力）"""
    ...
```

**`reference_analyzer.py` → 保留，职责明确化**

`semantic_dialog_generator` 改为显式 import `ReferenceAnalyzer`，不再自行实现颜色提取：

```python
# semantic_dialog_generator.py 顶部
from utils.reference_analyzer import ReferenceAnalyzer, ReferenceStyleApplier

# 内部统一调用
analyzer = ReferenceAnalyzer()
style_info = analyzer.analyze(reference_path)
```

**合并后模块职责边界：**

```
reference_analyzer.py         ← 纯视觉分析（颜色、布局、特征提取）
        ↓ import
semantic_dialog_generator.py  ← 弹窗生成主体（文案 + 风格应用 + AI/PIL 渲染 + GT风格提取）

style_transfer.py             ← 删除
```

### 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `scripts/style_transfer.py` | **删除** | 功能并入 `semantic_dialog_generator` |
| `scripts/utils/semantic_dialog_generator.py` | 修改 | 新增 `extract_gt_style()`，显式 import `reference_analyzer` |
| `scripts/utils/reference_analyzer.py` | 无改动 | 职责明确为纯视觉分析工具 |

---

## Phase 3：健壮性修复

### 修复一：`gt_manager.py` — index.json 自动重建

**问题**：新增 GT 样本需手动更新 `index.json`，否则 `get_template` 命中不到。

**修复**：启动时扫描目录自动重建索引，`index.json` 降级为可选缓存。

```python
def _build_index(self) -> dict:
    """扫描 gt_templates/ 目录自动重建索引，无需手动维护 index.json"""
    index = {}
    for component_type_dir in self.gt_root.iterdir():
        if not component_type_dir.is_dir():
            continue
        for sample in component_type_dir.glob("*.png"):
            index[sample.stem] = {
                "path": str(sample),
                "component_type": component_type_dir.name,
            }
    return index
```

---

### 修复二：`component_position_resolver.py` — 回退告警

**问题**：关键词匹配失败时静默回退到屏幕中心，调用方无感知，定位错误难以排查。

**修复**：回退时记录告警，结果中标记 `_fallback=True`。

```python
import logging
logger = logging.getLogger(__name__)

def resolve_position(self, instruction: str, ...) -> dict:
    keyword = self.extract_target_keyword(instruction)
    component = self.find_component_by_text(keyword)
    if not component:
        logger.warning(
            f"[ComponentPositionResolver] 未找到关键词 '{keyword}' 对应的组件，"
            f"已回退到屏幕中心。指令：'{instruction}'"
        )
        result = self._default_center_position()
        result["_fallback"] = True   # 供 run_pipeline 检测并写入 pipeline_meta
        return result
    ...
```

`run_pipeline` 检测到 `_fallback=True` 时，在 `pipeline_meta.json` 中记录告警。

---

### 修复三：`omni_vlm_fusion.py` — VLM 解析失败标记

**问题**：Stage 2 VLM 解析异常时静默 fallback 到 Stage 1 原始结果，`pipeline_meta.json` 中无记录。

**修复**：返回值中增加 `_stage2_status` 字段，失败时明确标记。

```python
def omni_vlm_fusion(...) -> dict:
    try:
        groups = extract_json(vlm_response)
        ui_json = apply_grouping(groups, omni_components)
        ui_json["_stage2_status"] = "success"
    except Exception as e:
        logger.warning(
            f"[Stage 2] VLM 分组解析失败，使用 Stage 1 原始结果。原因：{e}"
        )
        ui_json = {
            "components": omni_components,
            "_stage2_status": "fallback",
            "_stage2_error": str(e),
        }
    return ui_json
```

---

### 修复汇总

| 修复点 | 文件 | 改动规模 | 影响范围 |
|--------|------|---------|---------|
| index.json 自动重建 | `gt_manager.py` | 新增 `_build_index()`，约 20 行 | 仅内部，对外接口不变 |
| 位置回退告警 | `component_position_resolver.py` | 新增 logging + `_fallback` 标记，约 10 行 | `run_pipeline` 需读取 `_fallback` |
| VLM 失败标记 | `omni_vlm_fusion.py` | 新增 `_stage2_status` 字段，约 15 行 | `run_pipeline` 需读取 `_stage2_status` |

---

## 完整改动文件汇总

| 文件 | Phase | 改动类型 |
|------|-------|---------|
| `scripts/base_renderer.py` | 1 | 新增 |
| `scripts/patch_renderer.py` | 1 | 修改（继承 + 新增 render()） |
| `scripts/area_loading_renderer.py` | 1 | 修改（继承 + 新增 render()） |
| `scripts/content_duplicate_renderer.py` | 1 | 修改（继承 + 新增 render()） |
| `scripts/text_overlay_renderer.py` | 1 | 修改（继承 + 新增 render()） |
| `scripts/run_pipeline.py` | 1 + 3 | 修改（策略模式 + 读取告警标记） |
| `scripts/style_transfer.py` | 2 | 删除 |
| `scripts/utils/semantic_dialog_generator.py` | 2 | 修改（新增 extract_gt_style + 显式 import） |
| `scripts/utils/gt_manager.py` | 3 | 修改（新增 _build_index） |
| `scripts/utils/component_position_resolver.py` | 3 | 修改（新增 logging + _fallback 标记） |
| `scripts/omni_vlm_fusion.py` | 3 | 修改（新增 _stage2_status 标记） |

**净变化**：新增 1 文件，删除 1 文件，修改 9 文件。

---

*设计时间：2026-03-06*
*参考文档：`docs/plans/2026-03-06-code-manual.md`*
