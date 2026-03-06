# ui_semantic_patch 重构实施计划

**基于设计文档**：`docs/plans/2026-03-06-refactor-design.md`
**日期**：2026-03-06
**所有路径前缀**：`prototypes/ui_semantic_patch/scripts/`

---

## 一、需求重述

### Phase 1：接口统一
- 新增 `base_renderer.py`，定义 `BaseRenderer` 抽象基类和 `RenderResult` 数据类
- 四个渲染器各自继承 `BaseRenderer`，新增 `render()` 包装方法，原有方法保留不删
- `run_pipeline.py` 改为 `RENDERER_MAP` 字典路由 + 统一读取 `RenderResult`

### Phase 2：重叠合并
- 将 `style_transfer.py` 中 `StyleExtractor.extract_dialog_style()` 和 `extract_loading_style()` 迁移到 `utils/semantic_dialog_generator.py`，新方法名为 `extract_gt_style()`
- `semantic_dialog_generator.py` 改为显式 import `ReferenceAnalyzer`（**已完成**，见关键发现 #4）
- 删除 `style_transfer.py`

### Phase 3：健壮性修复
- `utils/gt_manager.py`：新增 `_build_index()` 自动扫描目录，`index.json` 降级为可选缓存
- `utils/component_position_resolver.py`：回退时 `logging.warning` + 结果添加 `_fallback=True`
- `omni_vlm_fusion.py`：返回值增加 `_stage2_status` 字段
- `run_pipeline.py`：读取上述标记字段，写入 `pipeline_meta.json`

---

## 二、关键发现（与设计文档的偏差）

### 发现 #1：`PatchRenderer` 在 dialog 模式中未被调用

`run_pipeline.py` 的 dialog 分支（第 486-684 行）**完全绕过** `PatchRenderer`。它直接实例化 `SemanticDialogGenerator`（第 544 行），调用 `generate_dialog_ai_from_meta()`（第 566 行），然后在 `run_pipeline.py` 内部完成遮罩叠加、关闭按钮绘制、位置计算等约 180 行逻辑。`PatchRenderer` 的 `generate_dialog_and_merge()` 和 `apply_patch()` 方法在主流水线中从未被调用。

**影响**：`PatchRenderer.render()` 包装方法不能简单地委托给 `generate_dialog_and_merge()`，必须将 `run_pipeline.py` 第 502-683 行的 meta-driven 逻辑迁入。这是 Phase 1 最高风险步骤。

### 发现 #2：`TextOverlayRenderer.render_all()` 接受 `screenshot_path: str`，非 `Image.Image`

`BaseRenderer.render()` 签名传入 `screenshot: Image.Image`，但 `TextOverlayRenderer.render_all()`（第 1239 行）接受 `screenshot_path: str` 并在内部自行打开文件（第 1258 行）。`render()` 包装必须通过 `**kwargs` 传递 `screenshot_path`。

### 发现 #3：`PatchRenderer.__init__` 要求 `ui_json_path: str`（文件路径）

`PatchRenderer.__init__`（第 26 行）要求 `screenshot_path` 和 `ui_json_path` 两个文件路径参数，在构造函数内打开文件。但 `BaseRenderer.render()` 签名传入的是内存中的 `screenshot: Image.Image` 和 `ui_json: dict`。`render()` 包装需要绕过构造函数的文件加载逻辑。

### 发现 #4：`semantic_dialog_generator.py` 已经 import `ReferenceAnalyzer`

第 32 行已有 `from utils.reference_analyzer import ReferenceAnalyzer, ReferenceStyleApplier`。设计文档中"改为显式 import"这一条已经满足，Phase 2 步骤 2.2 仅需验证，无需改代码。

### 发现 #5：`component_position_resolver.py` 已有 `used_fallback: True`

`resolve_popup_position()` 回退分支（第 328-335 行）返回 `'used_fallback': True`。新增 `_fallback: True` 是**补充字段**，用于 `run_pipeline.py` 明确检测。

### 发现 #6：`style_transfer.py` 全局零引用

在整个 `scripts/` 目录中，没有任何文件 import `style_transfer`。可以安全删除。

---

## 三、风险评估

| 风险 | 等级 | 来源 | 缓解措施 |
|------|------|------|----------|
| `PatchRenderer.render()` 需要封装 ~180 行 meta-driven 逻辑 | **高** | 发现 #1 | 提取为 `_render_dialog_meta_driven()` 私有方法；首次迁移后保留 `run_pipeline.py` 旧代码注释备用 |
| `TextOverlayRenderer` 接口不匹配，`render_all` 需要文件路径 | **中** | 发现 #2 | `render()` 强制要求 `kwargs['screenshot_path']`；文档注释说明 |
| `PatchRenderer.__init__` 要求文件路径，与 `BaseRenderer.render()` 内存对象冲突 | **中** | 发现 #3 | 为 `PatchRenderer` 新增不读取文件的轻量构造函数（或将文件加载延迟到 `render()` 内部） |
| `RENDERER_MAP` 统一路由后某模式静默失败 | **中** | Step 1.6 | 改动后逐模式跑 `run_pipeline.py` 端到端测试 |
| `_build_index()` 扫描性能比 `index.json` 慢 | **低** | Step 3.1 | GT 目录通常 < 20 个文件，扫描可忽略 |
| 删除 `style_transfer.py` 后外部工具链报错 | **低** | 发现 #6 | 已确认零引用 |

---

## 四、实施步骤（19 步）

### Phase 1：接口统一（7 步）

#### Step 1.1：创建 `base_renderer.py`

- **文件**：`scripts/base_renderer.py`（新增）
- **改动内容**：
  - 定义 `RenderResult` dataclass：字段 `image: Image.Image`、`output_path: str`、`metadata: dict`
  - 定义 `BaseRenderer` ABC：抽象方法 `render(self, screenshot, ui_json, instruction, output_dir, **kwargs) -> RenderResult`
- **验证方式**：
  ```bash
  python -c "from base_renderer import BaseRenderer, RenderResult; print('OK')"
  ```
- **依赖**：无
- **风险**：低

---

#### Step 1.2：`AreaLoadingRenderer` 继承 `BaseRenderer`

- **文件**：`scripts/area_loading_renderer.py`
- **改动内容**：
  1. 文件头新增 `from base_renderer import BaseRenderer, RenderResult`
  2. 类声明改为 `class AreaLoadingRenderer(BaseRenderer):`
  3. 新增 `render()` 方法：从 `kwargs` 获取 `screenshot_path`、`anomaly_type`，调用已有 `render_area_loading()`，返回 `RenderResult`
  4. **保留** `render_area_loading()` 方法不变
- **验证方式**：
  ```bash
  python -c "from area_loading_renderer import AreaLoadingRenderer; from base_renderer import BaseRenderer; assert issubclass(AreaLoadingRenderer, BaseRenderer); print('OK')"
  ```
- **依赖**：Step 1.1
- **风险**：中（需从 `run_pipeline.py` 迁移组件选择辅助逻辑）

---

#### Step 1.3：`ContentDuplicateRenderer` 继承 `BaseRenderer`

- **文件**：`scripts/content_duplicate_renderer.py`
- **改动内容**：
  1. 文件头新增 `from base_renderer import BaseRenderer, RenderResult`
  2. 类声明改为 `class ContentDuplicateRenderer(BaseRenderer):`
  3. 新增 `render()` 方法：从 `kwargs` 获取 `screenshot_path`、`meta_features`（默认 `{}`）、`mode`（默认 `'expanded_view'`），调用已有 `render_content_duplicate()`，返回 `RenderResult`
  4. **保留** `render_content_duplicate()` 方法不变
- **验证方式**：同 Step 1.2 模式
- **依赖**：Step 1.1
- **风险**：低（参数对齐度高）

---

#### Step 1.4：`TextOverlayRenderer` 继承 `BaseRenderer`

- **文件**：`scripts/text_overlay_renderer.py`
- **改动内容**：
  1. 文件头新增 `from base_renderer import BaseRenderer, RenderResult`
  2. 类声明改为 `class TextOverlayRenderer(BaseRenderer):`
  3. 新增 `render()` 方法：
     - **必须**从 `kwargs['screenshot_path']` 获取文件路径（因 `render_all` 接受路径而非 PIL 对象，见发现 #2）
     - 调用 `self.render_all(screenshot_path, ui_json, instruction)`
     - 返回 `RenderResult`，metadata 包含 `edit_count`、`diff_path`、`edit_plan_path`
  4. **保留** `render_all()` 方法不变
  5. 在方法文档中注明：`render()` 的 `screenshot` 参数不被使用，路径通过 `kwargs['screenshot_path']` 传递
- **验证方式**：同 Step 1.2 模式
- **依赖**：Step 1.1
- **风险**：中（接口不匹配需文档说明）

---

#### Step 1.5：`PatchRenderer` 继承 `BaseRenderer`

- **文件**：`scripts/patch_renderer.py`
- **改动内容**：
  1. 文件头新增 `from base_renderer import BaseRenderer, RenderResult`
  2. 类声明改为 `class PatchRenderer(BaseRenderer):`
  3. **修改构造函数**：`screenshot_path` 和 `ui_json_path` 改为可选（默认 `None`），延迟文件加载
  4. 新增 `_render_dialog_meta_driven()` 私有方法，封装 `run_pipeline.py` 第 502-683 行的完整逻辑：
     - `MetaLoader` 加载 meta.json
     - 计算弹窗尺寸（`dialog_bounds_px` 优先，回退到比例）
     - `SemanticDialogGenerator` 生成弹窗图像
     - `ComponentPositionResolver` 计算弹窗位置
     - 遮罩层叠加 + 关闭按钮绘制
  5. 新增 `render()` 方法调用 `_render_dialog_meta_driven()`，返回 `RenderResult`
  6. **保留** `generate_dialog_and_merge()`、`apply_patch()`、`apply_add()` 等原有方法不变
- **验证方式**：dialog 模式端到端运行（见 Step 1.6）
- **依赖**：Step 1.1
- **风险**：**高**（需迁移 ~180 行逻辑，见发现 #1 和 #3）

---

#### Step 1.6：`run_pipeline.py` 改为 `RENDERER_MAP` 路由

- **文件**：`scripts/run_pipeline.py`
- **改动内容**：
  1. 顶部新增 import 四个渲染器和 `RenderResult`
  2. 定义模块级 `RENDERER_MAP` 字典：
     ```python
     RENDERER_MAP = {
         "dialog": PatchRenderer,
         "area_loading": AreaLoadingRenderer,
         "content_duplicate": ContentDuplicateRenderer,
         "text_overlay": TextOverlayRenderer,
     }
     ```
  3. 替换 Stage 3 的 if-elif 分支（第 278-684 行）为统一路由：查表 → 实例化 → `renderer.render()` → 读取 `RenderResult`
  4. **首次迁移建议**：将旧的 if-elif 代码注释保留，待所有模式验证通过后再清理
- **验证方式**：依次运行四种模式端到端测试：
  ```bash
  # dialog 模式
  python run_pipeline.py -s ../data/原图/app首页类-开屏广告弹窗/携程旅行01.jpg \
    -i "生成优惠券广告弹窗" --gt-category "弹窗覆盖原UI" --gt-sample "弹出广告.jpg" \
    -o ./test_output/dialog

  # area_loading 模式
  python run_pipeline.py -s ../data/原图/影视剧集类-内容歧义、重复/腾讯视频.jpg \
    -i "模拟列表加载超时" --anomaly-mode area_loading -o ./test_output/area_loading

  # content_duplicate 模式
  python run_pipeline.py -s ../data/原图/影视剧集类-内容歧义、重复/腾讯视频.jpg \
    -i "模拟底部信息重复显示" --anomaly-mode content_duplicate \
    --gt-category "内容歧义、重复" --gt-sample "部分信息重复.jpg" -o ./test_output/dup

  # text_overlay 模式
  python run_pipeline.py -s ../data/原图/app首页类-开屏广告弹窗/携程旅行01.jpg \
    -i "在租车服务卡片中插入优惠信息" --anomaly-mode text_overlay -o ./test_output/overlay
  ```
- **依赖**：Steps 1.2, 1.3, 1.4, 1.5
- **风险**：**高**（中心集成点）

---

#### Step 1.7：Phase 1 集成验证

- **文件**：无改动
- **改动内容**：运行 `batch_pipeline.py` dry-run 验证向后兼容
  ```bash
  python batch_pipeline.py --input-dir ../data/原图/app首页类-开屏广告弹窗 \
    --gt-category "弹窗覆盖原UI" --output ./test_batch
  ```
- **验证方式**：dry-run 无 ImportError，输出命令行参数格式与旧版一致
- **依赖**：Step 1.6
- **风险**：低

---

### Phase 2：重叠合并（4 步）

> Phase 2 与 Phase 1 **可完全并行执行**（无依赖关系）。

#### Step 2.1：在 `SemanticDialogGenerator` 中新增 `extract_gt_style()`

- **文件**：`scripts/utils/semantic_dialog_generator.py`
- **改动内容**：
  1. 新增方法 `extract_gt_style(self, sample_path: str, style_type: str = "dialog") -> dict`
  2. 从 `style_transfer.py` 迁移：
     - `style_type == "dialog"` → 迁移 `StyleExtractor.extract_dialog_style()`（第 48-159 行）的 VLM prompt 和返回格式
     - `style_type == "loading"` → 迁移 `StyleExtractor.extract_loading_style()`（第 161-228 行）
  3. 复用 `self.api_key`、`self.vlm_api_url`、`self.vlm_model`
  4. 迁移 fallback 默认值（`_get_default_dialog_style()`、`_get_default_loading_style()`）
  5. 在 `__init__` 中初始化 `self._style_cache = {}` 缓存结果
- **验证方式**：
  ```bash
  python -c "from utils.semantic_dialog_generator import SemanticDialogGenerator; g = SemanticDialogGenerator(api_key='test'); assert hasattr(g, 'extract_gt_style'); print('OK')"
  ```
- **依赖**：无
- **风险**：低（纯新增方法）

---

#### Step 2.2：验证 `ReferenceAnalyzer` import 已完成

- **文件**：`scripts/utils/semantic_dialog_generator.py`（只读核查）
- **改动内容**：无代码改动。确认第 32 行已有正确 import，并检查内部是否有与 `ReferenceAnalyzer.analyze()` 功能重叠的颜色提取代码：
  ```bash
  grep -n "dominant_color\|extract_color\|getpixel\|color_histogram" utils/semantic_dialog_generator.py
  ```
  若有重叠，替换为调用 `ReferenceAnalyzer`。
- **验证方式**：上述 grep 无独立颜色提取代码
- **依赖**：Step 2.1
- **风险**：低

---

#### Step 2.3：确认 `style_transfer.py` 零引用

- **文件**：`scripts/` 全目录（只读核查）
- **改动内容**：无代码改动。最终确认：
  ```bash
  grep -r "style_transfer" prototypes/ui_semantic_patch/
  ```
  结果应仅有文件自身（已确认：零外部引用）。
- **验证方式**：grep 排除文件自身后零匹配
- **依赖**：Steps 2.1, 2.2
- **风险**：低

---

#### Step 2.4：删除 `style_transfer.py`

- **文件**：`scripts/style_transfer.py`（删除）
- **改动内容**：
  ```bash
  git rm prototypes/ui_semantic_patch/scripts/style_transfer.py
  ```
- **验证方式**：所有四种流水线模式正常运行，无 `ImportError`
- **依赖**：Step 2.3
- **风险**：低

---

### Phase 3：健壮性修复（8 步）

> Phase 3 与 Phase 1、Phase 2 **可完全并行执行**。
> Phase 3 内部：Steps 3.1-3.2、Step 3.3、Step 3.4 三组互不依赖，可并行推进。

#### Step 3.1：在 `GTManager` 中新增 `_build_index()`

- **文件**：`scripts/utils/gt_manager.py`
- **改动内容**：新增方法 `_build_index(self) -> dict`：
  - 扫描 `dialogs/`、`toasts/`、`loadings/` 三个子目录
  - 遍历每个子目录下的 `*.png` 文件，构建索引条目（`name`、`style`、`path`、`size`）
  - 若存在同名 `.json` 元数据文件，读取其中的 `style` 和 `size` 覆盖默认值
  - 返回格式与 `index.json` 一致：`{"dialogs": [...], "toasts": [...], "loadings": [...]}`
- **验证方式**：手动调用 `_build_index()` 并与现有 `index.json` 内容对比
- **依赖**：无
- **风险**：低

---

#### Step 3.2：修改 `_load_index()` 优先使用 `_build_index()`

- **文件**：`scripts/utils/gt_manager.py`
- **改动内容**：修改 `_load_index()`（第 58-63 行）：
  ```python
  def _load_index(self) -> dict:
      # 主路径：扫描目录自动重建
      index = self._build_index()
      if any(index.get(k) for k in ("dialogs", "toasts", "loadings")):
          return index
      # 回退：读取 index.json 缓存
      if self.index_path.exists():
          with open(self.index_path, 'r', encoding='utf-8') as f:
              return json.load(f)
      return {"dialogs": [], "toasts": [], "loadings": []}
  ```
- **验证方式**：删除 `index.json`（备份后），实例化 `GTManager`，调用 `get_template('dialog')`，应正常返回模板
- **依赖**：Step 3.1
- **风险**：低

---

#### Step 3.3：`component_position_resolver.py` 添加回退告警和 `_fallback` 标记

- **文件**：`scripts/utils/component_position_resolver.py`
- **改动内容**：
  1. 文件顶部新增 `import logging` 和 `logger = logging.getLogger(__name__)`
  2. 在 `resolve_popup_position()` 回退分支新增日志：
     ```python
     logger.warning(
         "[ComponentPositionResolver] keyword match failed for instruction '%s', "
         "falling back to percentage-based positioning (dialog_position='%s')",
         instruction, dialog_position
     )
     ```
  3. 回退返回字典中新增 `'_fallback': True` 字段（补充现有的 `used_fallback: True`）
- **验证方式**：传入不匹配任何组件的 instruction，检查返回 dict 包含 `_fallback: True`，且 warning 日志已输出
- **依赖**：无
- **风险**：低

---

#### Step 3.4：`omni_vlm_fusion.py` 返回值增加 `_stage2_status`

- **文件**：`scripts/omni_vlm_fusion.py`
- **改动内容**：修改 try-except 块，在成功/失败路径分别设置状态变量：
  - 成功路径：`_stage2_status = "success"`
  - 异常路径：`_stage2_status = "fallback"`，`_stage2_error = str(e)`
  在最终 `ui_json` 字典中新增 `_stage2_status` 字段，失败时额外添加 `_stage2_error`
- **验证方式**：用无效 API key 调用，检查返回 dict 包含 `_stage2_status: "fallback"` 和 `_stage2_error`
- **依赖**：无
- **风险**：低

---

#### Step 3.5：`run_pipeline.py` 读取 `_fallback` 写入 `pipeline_meta.json`

- **文件**：`scripts/run_pipeline.py`
- **改动内容**：在位置解析结果后新增检测逻辑：
  ```python
  if position_result.get('_fallback'):
      results.setdefault('warnings', []).append({
          'type': 'position_fallback',
          'instruction': instruction,
          'message': 'Component keyword match failed, used percentage-based positioning'
      })
  ```
  （若 Phase 1 已完成，此逻辑写在 `PatchRenderer._render_dialog_meta_driven()` 内部，通过 `RenderResult.metadata` 传递）
- **验证方式**：运行 dialog 模式并使用不匹配组件的 instruction，检查 `pipeline_meta.json` 包含 `warnings` 数组
- **依赖**：Step 3.3
- **风险**：低

---

#### Step 3.6：`run_pipeline.py` 读取 `_stage2_status` 写入 `pipeline_meta.json`

- **文件**：`scripts/run_pipeline.py`
- **改动内容**：在 Stage 2 结果保存后新增检测逻辑：
  ```python
  stage2_status = ui_json.get('_stage2_status', 'unknown')
  results['stage2_status'] = stage2_status
  if stage2_status == 'fallback':
      results.setdefault('warnings', []).append({
          'type': 'stage2_fallback',
          'error': ui_json.get('_stage2_error', ''),
          'message': 'VLM semantic grouping failed, using raw OmniParser results'
      })
      print(f"  [WARN] Stage 2 fell back to raw results: {ui_json.get('_stage2_error', '')}")
  ```
- **验证方式**：强制 VLM 失败（无效 key），检查 `pipeline_meta.json` 包含 `stage2_status: "fallback"` 和 `warnings`
- **依赖**：Step 3.4
- **风险**：低

---

#### Step 3.7：确认 `warnings` 字段自动写入 `pipeline_meta.json`

- **文件**：`scripts/run_pipeline.py`（只读核查）
- **改动内容**：无代码改动。确认 `json.dump(results, ...)` 调用处会自动序列化 `results['warnings']` 和 `results['stage2_status']` 字段。
- **验证方式**：检查输出的 `pipeline_meta.json` 文件包含新字段
- **依赖**：Steps 3.5, 3.6
- **风险**：低

---

#### Step 3.8：Phase 3 集成验证

- **文件**：无改动
- **改动内容**：三种场景端到端测试：
  1. **正常配置**：`pipeline_meta.json` 中 `stage2_status = "success"`，无 `warnings`
  2. **无效 VLM key**：`pipeline_meta.json` 中 `stage2_status = "fallback"`，`warnings` 包含 `stage2_fallback`
  3. **不匹配的 instruction**：`pipeline_meta.json` 中 `warnings` 包含 `position_fallback`
- **验证方式**：逐场景检查 `pipeline_meta.json` 内容
- **依赖**：Step 3.7
- **风险**：低

---

## 五、并行执行说明

```
时间线 →

Phase 1:  1.1 ─→ 1.2 ┐
                  1.3 ├──→ 1.6 ──→ 1.7
                  1.4 │
                  1.5 ┘

Phase 2:  2.1 ──→ 2.2 ──→ 2.3 ──→ 2.4         ← 与 Phase 1 完全并行

Phase 3:  3.1 ──→ 3.2 ┐
          3.3 ─────────┼──→ 3.5 ┐
          3.4 ─────────┼──→ 3.6 ├──→ 3.7 ──→ 3.8
                       └────────┘
                                                ← 与 Phase 1/2 完全并行
```

**关键依赖链**：
- Phase 1 内部：Steps 1.2-1.5 互相并行，但都依赖 1.1；Step 1.6 依赖 1.2-1.5 全部完成
- Phase 2 内部：严格顺序（2.1 → 2.2 → 2.3 → 2.4）
- Phase 3 内部：Steps 3.1-3.2、3.3、3.4 三组并行；Steps 3.5/3.6 分别依赖 3.3/3.4
- **三个 Phase 之间无依赖**，可同时推进

---

## 六、验收标准

- [ ] 四种异常模式（dialog、area_loading、content_duplicate、text_overlay）通过 `RENDERER_MAP` 统一路由产出正确结果
- [ ] `batch_pipeline.py` dry-run 无 ImportError（接口向后兼容）
- [ ] `style_transfer.py` 已删除；`SemanticDialogGenerator.extract_gt_style()` 可用
- [ ] 删除 `index.json` 后 `GTManager.get_template()` 仍能通过目录扫描找到模板
- [ ] 位置回退时 `pipeline_meta.json` 包含 `warnings[type=position_fallback]`
- [ ] VLM Stage 2 失败时 `pipeline_meta.json` 包含 `stage2_status: "fallback"` 和对应 warning
- [ ] 所有已有端到端流水线输出质量无回归

---

## 七、完整改动文件汇总

| 文件 | Phase | 改动类型 |
|------|-------|---------|
| `scripts/base_renderer.py` | 1 | **新增** |
| `scripts/patch_renderer.py` | 1 | 修改（继承 + 新增 `render()` + 构造函数可选参数） |
| `scripts/area_loading_renderer.py` | 1 | 修改（继承 + 新增 `render()` 包装） |
| `scripts/content_duplicate_renderer.py` | 1 | 修改（继承 + 新增 `render()` 包装） |
| `scripts/text_overlay_renderer.py` | 1 | 修改（继承 + 新增 `render()` 包装，注明 kwargs） |
| `scripts/run_pipeline.py` | 1 + 3 | 修改（策略模式路由 + 告警标记读取） |
| `scripts/style_transfer.py` | 2 | **删除** |
| `scripts/utils/semantic_dialog_generator.py` | 2 | 修改（新增 `extract_gt_style()`） |
| `scripts/utils/gt_manager.py` | 3 | 修改（新增 `_build_index()`，修改 `_load_index()`） |
| `scripts/utils/component_position_resolver.py` | 3 | 修改（新增 logging + `_fallback` 标记） |
| `scripts/omni_vlm_fusion.py` | 3 | 修改（新增 `_stage2_status` 字段） |

**净变化**：新增 1 文件，删除 1 文件，修改 9 文件。

---

*实施计划生成时间：2026-03-06*
*基于设计文档：`docs/plans/2026-03-06-refactor-design.md`*
*代码审查版本：commit 5572033*
