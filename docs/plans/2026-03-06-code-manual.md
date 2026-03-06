# 工程代码说明书

**项目**：ui_semantic_patch — 异常测试场景自动生成原型
**路径**：`prototypes/ui_semantic_patch/scripts/`
**版本**：2026-03-06
**读者**：技术负责人

---

## 1. 系统概览

### 一句话定位

输入「原始截图 + 异常模式 + 文本指令（+ 可选 GT 参考模板）」，输出「合成的异常场景截图」。

### 全局数据流

```
用户输入
  ├─ 原始截图 (PNG/JPG)
  ├─ 异常模式 (dialog / area_loading / content_duplicate / text_overlay)
  ├─ 文本指令 (自然语言描述)
  └─ GT 参考模板 (可选, meta.json + 样本图)
         │
         ▼
┌─────────────────────────────────────────────────┐
│              run_pipeline.py  (主控)             │
│                                                 │
│  Stage 1      Stage 2         Stage 3           │
│  OmniParser → VLM 语义分组 → 异常渲染           │
│  (检测组件)   (合并/过滤)    (叠加异常)          │
└─────────────────────────────────────────────────┘
         │
         ▼
输出文件 (output_dir/)
  ├─ stage1_omni_raw_*.json      (Stage 1 原始检测)
  ├─ stage2_filtered_*.json      (Stage 2 UI-JSON)
  ├─ final_*.png                 (最终异常截图)
  └─ pipeline_meta_*.json        (流水线元数据)
```

### 架构层级总览

| 层级 | 脚本 | 职责摘要 |
|------|------|---------|
| **第一层：主控** | `run_pipeline.py` | 三阶段串联，单图入口 |
| | `batch_pipeline.py` | 批量执行，遍历原图 × GT |
| **第二层：AI 感知** | `omni_extractor.py` | OmniParser 本地推理，输出原始组件列表 |
| | `omni_vlm_fusion.py` | VLM 语义分组，输出合并后 UI-JSON |
| **第三层：渲染** | `patch_renderer.py` | dialog 模式弹窗合成 |
| | `area_loading_renderer.py` | 区域加载/超时图标覆盖 |
| | `content_duplicate_renderer.py` | 内容重复浮层生成 |
| | `text_overlay_renderer.py` | 局部文字精确编辑 |
| **第四层：元数据** | `generate_meta.py` | VLM 自动生成 meta.json |
| | `extract_gt_bounds.py` | 从 GT 图精确提取弹窗像素边界 |
| | `anomaly_sample_manager.py` | 异常样本扫描、聚类、导出 GT |
| | `generate_filename_descriptions.py` | 按文件名生成异常描述 |
| | `style_transfer.py` | GT 风格提取与迁移 |
| **第五层：工具库** | `utils/common.py` | 图片编码、JSON 提取通用函数 |
| | `utils/gt_manager.py` | GT 模板裁剪、检索、few-shot 构建 |
| | `utils/meta_loader.py` | meta.json 读取与语义提示词提取 |
| | `utils/component_position_resolver.py` | 指令关键词 → UI 组件坐标 |
| | `utils/reference_analyzer.py` | 参考图风格分析（颜色、布局） |
| | `utils/semantic_dialog_generator.py` | 弹窗内容生成（AI 模式 / PIL 模式） |
| **辅助** | `visualize_omni.py` | 检测结果可视化，调试用 |

---

## 2. 第一层：主控流水线

### run_pipeline.py — 三阶段流水线主入口

**层级职责**：唯一的单图执行入口，串联 Stage 1→2→3，根据 `--anomaly-mode` 路由到对应渲染器。

**关键输入**：

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `--screenshot` / `-s` | 路径 | ✅ | 原始截图 |
| `--instruction` / `-i` | 字符串 | ✅ | 自然语言异常描述 |
| `--anomaly-mode` | 枚举 | ✅ | `dialog` / `area_loading` / `content_duplicate` / `text_overlay` |
| `--gt-category` | 字符串 | dialog 模式必需 | GT 类别名，如 `弹窗覆盖原UI` |
| `--gt-sample` | 字符串 | dialog 模式必需 | GT 样本文件名，如 `弹出广告.jpg` |
| `--output` / `-o` | 路径 | 否 | 输出目录（默认 `./output`） |
| `--omni-device` | 字符串 | 否 | `cuda` / `cpu`（默认 `cuda`） |

**关键输出**：

| 文件 | 说明 |
|------|------|
| `stage1_omni_raw_*.json` | Stage 1 原始 OmniParser 结果 |
| `stage2_filtered_*.json` | Stage 2 VLM 分组后的 UI-JSON |
| `final_*.png` | 最终合成异常截图 |
| `pipeline_meta_*.json` | 运行元数据（时间戳、参数、耗时） |

**核心接口**：

```python
def run_pipeline(
    screenshot_path: str,
    instruction: str,
    output_dir: str,
    anomaly_mode: str = "dialog",
    gt_category: str = None,
    gt_sample: str = None,
    omni_device: str = "cuda",
    ...
) -> dict   # 返回输出文件路径字典
```

**与上下游的关系**：
- 上游依赖：用户命令行调用；`launch.sh` 封装调用
- 下游产出：调用 `omni_extractor`、`omni_vlm_fusion`，再路由到对应渲染器

**注意事项**：dialog 模式下若未提供 `--gt-category` 和 `--gt-sample`，流水线会报错退出。`--omni-device cuda` 需要 GPU 环境，CPU 模式速度显著变慢。

---

### batch_pipeline.py — 批量异常场景生成

**层级职责**：对「原图目录 × GT 样本」做笛卡尔积批量调用 `run_pipeline`，生成汇总报告。

**关键输入**：

| 参数 | 说明 |
|------|------|
| `--input-dir` / `-i` | 原图目录（自动扫描 jpg/png） |
| `--gt-category` / `-c` | 异常类别名（必需） |
| `--output` / `-o` | 输出根目录 |
| `--run` | 加此标志才实际执行，否则为 dry-run |
| `--list-categories` | 列出所有可用 GT 类别，不执行生成 |

**关键输出**：

| 文件 | 说明 |
|------|------|
| `batch_<category>_<timestamp>/` | 批次输出根目录 |
| `<原图名>_<样本名>/` | 每对组合的子目录（结构同 run_pipeline 输出） |
| `batch_report.json` | 汇总：成功/失败数、耗时、各子任务路径 |

**核心接口**：

```python
def run_batch(
    input_dir: str,
    gt_category: str,
    output_dir: str,
    gt_dir: str = None,
    dry_run: bool = True,
) -> dict   # 返回 batch_report 字典
```

**与上下游的关系**：
- 上游：用户命令行或 `launch.sh batch` 调用
- 下游：循环调用 `run_pipeline.run_pipeline()`

**注意事项**：默认为 dry-run，必须加 `--run` 才写磁盘。`batch_report.json` 记录失败任务详情，可用于断点续跑排查。

---

## 3. 第二层：AI 感知层

### omni_extractor.py — OmniParser UI 结构提取

**层级职责**：Stage 1。本地运行 OmniParser（YOLO + PaddleOCR + Florence2），将截图转为原始组件列表，不依赖外部 API。

**关键输入**：截图路径（必需）；可选 `box_threshold`（0.05）、`iou_threshold`（0.7）、`device`

**关键输出**：UI-JSON（见第 8 节数据契约）

**核心接口**：

```python
def omni_to_ui_json(
    image_path: str,
    box_threshold: float = 0.05,
    iou_threshold: float = 0.7,
    device: str = "cuda",
    return_annotated: bool = False,
) -> dict   # 返回 UI-JSON
```

**与上下游的关系**：
- 上游：`run_pipeline` Stage 1 调用
- 下游：输出 UI-JSON 传给 `omni_vlm_fusion`（Stage 2）
- 模型依赖：`third_party/OmniParser/`，首次调用有模型加载开销（懒加载）

**注意事项**：OmniParser 模型为懒加载单例，同进程多次调用不重复加载。`box_threshold` 调低会检测更多噪点组件，调高会漏检小控件——当前默认值 0.05 偏低，Stage 2 VLM 做二次过滤。

---

### omni_vlm_fusion.py — VLM 语义分组融合

**层级职责**：Stage 2。接收 OmniParser 原始检测结果，发起单次 VLM 调用，对组件做语义分组与合并，输出干净的 UI-JSON。

**关键输入**：截图路径 + Stage 1 UI-JSON + VLM API Key

**关键输出**：合并后的 UI-JSON（组件数从 N 压缩到 M，M < N）

**核心接口**：

```python
def omni_vlm_fusion(
    image_path: str,
    api_key: str,
    api_url: str,
    vlm_model: str,
    omni_components: list,   # Stage 1 输出的 components 列表
    output_dir: str = None,
) -> dict   # 返回合并后 UI-JSON
```

**与上下游的关系**：
- 上游：`run_pipeline` Stage 2 调用，接收 `omni_extractor` 的输出
- 下游：输出 UI-JSON 传给 Stage 3 渲染器（用于组件定位）
- 外部依赖：VLM API（OpenAI 兼容接口），由 `VLM_API_KEY` 环境变量提供

**注意事项**：内部有带指数退避的重试逻辑（`_call_vlm_with_retry`）。VLM 输出 JSON 通过 `utils/common.py::extract_json` 解析，若 VLM 返回格式异常会 fallback 到原始 Stage 1 结果。

---

## 4. 第三层：异常渲染层

四个渲染器对应四种 `--anomaly-mode`，均接收「原始截图 + Stage 2 UI-JSON + 指令」作为基础输入，输出合成后的 PNG。

---

### patch_renderer.py — dialog 模式弹窗渲染引擎

**层级职责**：Stage 3（dialog 模式）。驱动 `semantic_dialog_generator` 生成弹窗内容，将弹窗图像合成到原截图指定位置。

**关键输入**：原截图、UI-JSON、GT 目录（含 meta.json）、文本指令

**关键输出**：合成弹窗后的截图（PNG）

**核心接口**：

```python
class PatchRenderer:
    def __init__(self, screenshot_path, ui_json_path, fonts_dir, render_mode, api_key, gt_dir)
    def generate_dialog_and_merge(self, screenshot_path: str, instruction: str) -> Image
    def save(self, output_path: str)
```

**与上下游的关系**：
- 上游：`run_pipeline` Stage 3（dialog 模式）调用
- 下游依赖：`utils/semantic_dialog_generator`（弹窗内容生成）、`utils/component_position_resolver`（定位）、`utils/meta_loader`（读取 meta.json）

**注意事项**：仅支持 `add` 操作（叠加弹窗），不支持删除/修改现有 UI 元素。弹窗位置由 meta.json 中的 `dialog_position` + 指令关键词联合决定。

---

### area_loading_renderer.py — 区域加载异常渲染器

**层级职责**：Stage 3（area_loading 模式）。在目标 UI 组件区域中心覆盖加载/超时图标，支持风格自适应生成。

**关键输入**：截图、UI-JSON 中的目标组件、异常类型、可选参考图标路径

**关键输出**：合成加载图标后的截图（PNG）

**核心接口**：

```python
class AreaLoadingRenderer:
    def render_area_loading(
        self,
        screenshot: Image,
        component: dict,      # UI-JSON 中的目标组件
        anomaly_type: str,    # timeout/network_error/loading/image_broken/empty_data
    ) -> Image
```

**与上下游的关系**：
- 上游：`run_pipeline` Stage 3（area_loading 模式）调用
- 外部依赖：DashScope API（`DASHSCOPE_API_KEY`）用于生成风格匹配图标；若无密钥则 fallback 到内置图标

**注意事项**：图标尺寸由 `calculate_icon_size` 根据组件区域大小纯算法计算，不依赖 AI。AI 仅用于生成"风格匹配"的图标外观，可选降级。

---

### content_duplicate_renderer.py — 内容重复异常渲染器

**层级职责**：Stage 3（content_duplicate 模式）。在截图底部叠加半透明浮层，显示已有 UI 组件的重复/扩展内容，模拟"内容重复渲染"异常。

**关键输入**：截图、UI-JSON、文本指令、可选 meta_features（视觉特征）

**关键输出**：合成重复内容浮层后的截图（PNG）

**核心接口**：

```python
class ContentDuplicateRenderer:
    def render_content_duplicate(
        self,
        screenshot: Image,
        screenshot_path: str,
        ui_json: dict,
        instruction: str,
        meta_features: dict = None,
        mode: str = "simple_crop",   # simple_crop / expanded_view
    ) -> Image
```

**与上下游的关系**：
- 上游：`run_pipeline` Stage 3（content_duplicate 模式）调用
- 内部：通过指令关键词（选集/列表/筛选/标签等）匹配目标组件，执行裁剪复制

**注意事项**：`simple_crop` 模式直接复制组件区域像素，`expanded_view` 模式通过 VLM 生成扩展内容再绘制。`simple_crop` 速度快、无 API 依赖，是默认优先模式。

---

### text_overlay_renderer.py — 局部文字精确编辑渲染器

**层级职责**：Stage 3（text_overlay 模式）。由 VLM 规划编辑方案，PIL 执行精确文字叠加/替换，输出带 diff 可视化的结果。

**关键输入**：截图路径、UI-JSON、文本指令

**关键输出**：

| 文件 | 说明 |
|------|------|
| `final_*.png` | 编辑后截图 |
| `diff_*.png` | 原图/编辑对比可视化 |
| `edit_plan_*.json` | VLM 输出的编辑操作计划 |

**核心接口**：

```python
class TextOverlayRenderer:
    def render_all(
        self,
        screenshot_path: str,
        ui_json: dict,
        instruction: str,
    ) -> dict   # 返回输出文件路径字典
```

**支持操作**：`insert_text` / `replace_region` / `modify_text` / `add_badge` / `expand_card`

**与上下游的关系**：
- 上游：`run_pipeline` Stage 3（text_overlay 模式）调用
- 外部依赖：VLM API（规划编辑内容），PIL（执行绘制）

**注意事项**：渲染精度依赖 VLM 输出的坐标准确性，若 VLM 坐标偏差大，可通过 `ui_json` 中的组件 bounds 做校正。字体路径由 `--fonts-dir` 指定，中文渲染需要 CJK 字体文件。

---

## 5. 第四层：元数据与数据管理层

这一层脚本均为**离线工具**，不在主流水线执行路径上，用于维护和扩充 GT 模板库。

---

### generate_meta.py — GT 模板 meta.json 自动生成

**层级职责**：离线工具。VLM 分析异常截图，自动生成符合规范的 `meta.json`，驱动 dialog 模式弹窗生成。

**关键输入**：GT 模板目录路径；类别 ID（`dialog_blocking` / `content_duplicate` / `loading_timeout`）

**关键输出**：`meta.json`（写入 GT 目录，见第 8 节数据契约）

**核心接口**：

```python
def generate_meta_for_directory(
    target_dir: str,
    category_id: str,
    force: bool = False,   # 是否覆盖已有 meta.json
    dry_run: bool = True,
) -> dict
```

**与上下游的关系**：
- 下游被消费：`utils/meta_loader` 读取，`patch_renderer` / `semantic_dialog_generator` 使用
- 外部依赖：VLM API

**注意事项**：默认 dry-run，加 `--run` 才写文件。加 `--scan-all` 可批量处理所有子目录。生成后建议人工验证 `dialog_bounds_px` 字段精度（可用 `extract_gt_bounds.py` 精化）。

---

### extract_gt_bounds.py — GT 弹窗边界框精确提取

**层级职责**：离线工具。对 GT 参考图运行 OmniParser，结合 IoU 匹配精确提取弹窗像素边界框，回写到 `meta.json` 的 `dialog_bounds_px` 字段。

**关键输入**：GT 模板目录；类别名；可选指定样本名

**关键输出**：更新 `meta.json` 中各样本的 `dialog_bounds_px` 字段

**核心接口**：

```python
def extract_bounds_for_sample(
    image_path: str,
    sample_meta: dict,
    category: str,
    dry_run: bool = True,
) -> dict   # 返回提取到的 bounds
```

**策略**：OmniParser 检测全部组件 → VLM 过滤出弹窗组件 → IoU 匹配预期区域

**注意事项**：依赖 OmniParser 本地模型（GPU 推荐）。当 GT 图中弹窗与背景对比度低时，检测精度下降，需人工核查。

---

### anomaly_sample_manager.py — 异常样本管理与聚类

**层级职责**：离线工具。扫描异常样本目录，通过 VLM 深度分析 + 聚类算法，将样本归类并导出结构化 GT 模板。

**关键输入**：异常样本根目录

**关键输出**：`sample_clustering.json`（聚类结果）；GT 模板目录（含按类别整理的样本）

**核心接口**：

```python
class AnomalySampleManager:
    def scan_samples(self) -> list
    def cluster_samples(self, deep_analysis: bool = False) -> dict
    def export_gt_templates(self, clustering_result: dict, category: str) -> str
```

**异常类别**：`dialog_ad` / `dialog_tip` / `dialog_system` / `loading_timeout` / `content_error` / `ui_interference`

**注意事项**：`deep_analysis=True` 会对每张图调用 VLM，成本较高。通常先 `deep_analysis=False` 做快速分类，再对边界样本做深度分析。

---

### generate_filename_descriptions.py — 文件名描述生成

**层级职责**：离线工具。根据异常样本文件名，调用 VLM 生成结构化异常描述，用于标注和检索。

**关键输入**：异常样本目录；可选图片路径（提供视觉上下文）

**关键输出**：JSON 数组，每条含 `anomaly_description`、`root_cause`、`agent_impact`、`blocking_level`、`recommended_handling`

**注意事项**：纯语言模型调用，无本地模型依赖。`blocking_level` 字段（high/medium/low）可用于测试用例优先级排序。

---

### style_transfer.py — GT 风格提取与迁移

**层级职责**：实验性工具。从 GT 样本提取视觉风格（颜色、布局），迁移到目标截图，用于增强弹窗与 APP 风格的一致性。

**关键输入**：GT 样本路径（源风格）；目标截图路径

**关键输出**：风格特征字典；迁移后的视觉建议

**核心接口**：

```python
class StyleTransferPipeline:
    def transfer_dialog_style(self, target_screenshot: str, source_category: str) -> dict
    def transfer_loading_style(self, target_screenshot: str, source_category: str) -> dict
```

**注意事项**：当前作为独立工具存在，尚未集成到主流水线。`semantic_dialog_generator` 已内置风格提取逻辑，两者存在功能重叠，后续可考虑合并。

---

## 6. 第五层：工具库（utils/）

工具库所有模块由主流水线脚本和渲染器直接 import，不作为命令行脚本独立运行。

---

### utils/common.py — 公共基础函数

**职能**：提供跨模块复用的基础工具函数。

| 函数 | 说明 |
|------|------|
| `encode_image(image_path)` | 图片 → Base64 字符串，用于 VLM 多模态调用 |
| `get_mime_type(image_path)` | 返回图片 MIME 类型（`image/jpeg` 等） |
| `extract_json(content)` | 从 VLM 文本输出中提取 JSON，支持纯 JSON、```json 代码块、裸 `{` 块三种格式 |

**注意事项**：`extract_json` 是全系统 VLM JSON 解析的统一入口，其健壮性直接影响所有依赖 VLM 输出的模块。

---

### utils/gt_manager.py — GT 模板管理器

**职能**：管理 GT 模板库的读取、裁剪、检索、few-shot 构建。

**核心接口**：

```python
class GTManager:
    def extract_component_from_gt(self, gt_image_path, bounds, component_type, style, name) -> Image
    def get_template(self, component_type, style, target_size) -> Image
    def build_fewshot_prompt(self, component_type, instruction) -> str
```

**目录结构约定**：`gt_templates/dialogs/` / `loadings/` / `toasts/` + `index.json`

**注意事项**：`index.json` 是模板检索的索引文件，新增 GT 样本后需同步更新，否则 `get_template` 无法命中新样本。

---

### utils/meta_loader.py — GT 元数据加载器

**职能**：读取 `meta.json`，提供按类别/样本粒度的元数据访问接口，并生成供 VLM 使用的语义提示词。

**核心接口**：

```python
class MetaLoader:
    def list_categories(self) -> list[str]
    def list_samples(self, category: str) -> list[str]
    def load_sample_meta(self, category: str, sample_name: str) -> dict
    def extract_semantic_prompt(self, category: str, sample_name: str) -> str
    def extract_visual_style_prompt(self, category: str, sample_name: str) -> str
```

**注意事项**：是 dialog 模式的核心依赖，`patch_renderer` 和 `semantic_dialog_generator` 均通过它获取 meta 数据。meta.json 字段变更需同步更新此类的提取逻辑。

---

### utils/component_position_resolver.py — UI 组件精确定位解析器

**职能**：将自然语言指令（如"在租车服务卡片中"）解析为 UI-JSON 中对应组件的像素坐标，计算弹窗/图标的绝对位置。

**核心接口**：

```python
class ComponentPositionResolver:
    def resolve_position(
        self,
        instruction: str,
        dialog_position: str,   # "center" / "below_left" / "above_center" 等
        dialog_size_ratio: dict,
    ) -> dict   # 返回 {x, y, width, height}

# 便捷函数（含回退逻辑）
def resolve_popup_position(ui_json, instruction, ...) -> dict
```

**匹配优先级**：精确全匹配 > 前缀匹配 > 包含匹配 > 组件类型匹配

**注意事项**：当关键词匹配失败时回退到屏幕中心位置。指令中的关键词提取依赖规则（`extract_target_keyword`），对高度口语化指令可能失效。

---

### utils/reference_analyzer.py — 参考图风格分析器

**职能**：分析参考弹窗图片，提取颜色（主色调、按钮色、文字色）和布局特征，供 `semantic_dialog_generator` 生成风格一致的弹窗。

**核心接口**：

```python
class ReferenceAnalyzer:
    def analyze(self, reference_path: str) -> dict   # 返回风格信息字典
    def apply_style_to_bounds(self, style_info, target_width, target_height) -> dict

class ReferenceStyleApplier:
    def get_colors(self) -> dict
    def get_ai_prompt(self, title: str, message: str) -> str
```

**输出结构**：包含 `layout`（位置、尺寸比）、`colors`（颜色字典）、`features`（圆角、阴影等）、`vlm_analysis`（VLM 自然语言描述）

**注意事项**：颜色提取基于 PIL 像素统计（K-means 聚类），对渐变色提取效果较好，对复杂背景可能不准确。

---

### utils/semantic_dialog_generator.py — 语义感知弹窗生成器

**职能**：系统中最核心的工具类。负责弹窗内容生成（VLM 生成文案 + AI 图像生成/PIL 绘制）和弹窗与截图的合成。

**两种渲染模式**：

| 模式 | 触发条件 | 依赖 | 质量 |
|------|---------|------|------|
| AI 模式 | `DASHSCOPE_API_KEY` 可用 | DashScope qwen-image-max | 高（真实感强） |
| PIL 模式 | API 不可用时降级 | 本地 PIL + TrueType 字体 | 中（程序化绘制） |

**核心接口**：

```python
class SemanticDialogGenerator:
    def generate_dialog_ai_from_meta(
        self,
        meta_semantic: str,
        meta_features: dict,
        instruction: str,
        screenshot_path: str,
        width: int,
        height: int,
    ) -> Image   # 返回弹窗 PIL Image

    def generate_content_for_target_page(
        self,
        screenshot_path: str,
        instruction: str,
        meta_features: dict,
    ) -> dict   # 返回弹窗文案内容字典
```

**注意事项**：文件体积最大（约 103KB），逻辑最复杂。AI 模式生成时间约 10-30s；PIL 模式约 1s 但视觉质量明显偏低。中文渲染必须指定 CJK 字体，否则文字显示为方块。

---

## 7. 辅助脚本

### visualize_omni.py — OmniParser 检测结果可视化

**层级职责**：调试工具。将 UI-JSON 中的组件边界框、标签、中心点叠加到原始截图，便于人工核查 Stage 1/Stage 2 检测质量。

**关键输入**：

| 参数 | 说明 |
|------|------|
| `--screenshot` / `-s` | 原始截图（必需） |
| `--ui-json` / `-j` | UI-JSON 文件路径（必需） |
| `--output` / `-o` | 输出图片路径 |

**关键输出**：带彩色边界框标注的 PNG（每个组件显示 index + class + text 标签）

**典型用法**：

```bash
python visualize_omni.py \
  -s ../data/原图/app首页类-开屏广告弹窗/携程旅行01.jpg \
  -j ./output/demo/stage1_omni_raw_xxx.json \
  -o ./debug_vis.png
```

---

## 8. 数据契约（关键 JSON 格式）

### UI-JSON（Stage 1 / Stage 2 输出）

```json
{
  "metadata": {
    "image_path": "xxx.jpg",
    "image_size": {"width": 1080, "height": 1920},
    "timestamp": "2026-03-06T10:00:00"
  },
  "components": [
    {
      "index": 0,
      "class": "text | button | image | container | ...",
      "bounds": {"x": 100, "y": 200, "width": 300, "height": 60},
      "text": "文字内容（如有）",
      "clickable": true,
      "source": "omni | vlm_merged"
    }
  ],
  "componentCount": 42
}
```

**字段说明**：
- `bounds`：像素绝对坐标，原点在截图左上角
- `source`：`omni` 表示 OmniParser 直接检测，`vlm_merged` 表示 VLM 合并后的组件
- Stage 2 输出中 `componentCount` 通常显著小于 Stage 1

---

### meta.json（GT 模板元数据）

```json
{
  "category": "dialog_blocking",
  "description": "弹窗覆盖原UI类异常，共N个样本",
  "count": 8,
  "samples": {
    "弹出广告.jpg": {
      "anomaly_type": "promotional_dialog",
      "anomaly_description": "全屏促销弹窗覆盖主界面",
      "visual_features": {
        "app_style": "电商类APP",
        "primary_color": "#FF6600",
        "dialog_position": "center",
        "dialog_size_ratio": {"width": 0.8, "height": 0.5},
        "overlay_enabled": true,
        "overlay_opacity": 0.7,
        "dialog_bounds_px": {
          "x": 100, "y": 400, "width": 860, "height": 960
        }
      },
      "generation_template": {
        "instruction": "生成优惠券弹窗",
        "key_points": ["大标题", "优惠金额", "立即使用按钮", "关闭按钮"]
      }
    }
  }
}
```

**字段说明**：
- `dialog_bounds_px`：由 `extract_gt_bounds.py` 精确提取的像素坐标，是 dialog 模式定位的依据
- `dialog_size_ratio`：相对于截图宽高的比例，用于跨屏幕尺寸适配
- `generation_template.key_points`：引导 VLM 生成符合 GT 视觉特征的弹窗内容

---

*文档生成时间：2026-03-06*
*基于代码版本：commit 813149e*
