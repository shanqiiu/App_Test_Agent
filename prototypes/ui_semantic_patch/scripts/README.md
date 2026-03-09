# 脚本文档

UI 异常场景生成流水线的完整脚本参考。

---

## 快速命令

```bash
# 单图生成（弹窗模式）
python run_pipeline.py \
  --screenshot ../data/原图/app首页类-开屏广告弹窗/携程旅行01.jpg \
  --instruction "生成优惠券广告弹窗" \
  --gt-category "弹窗覆盖原UI" --gt-sample "弹出广告.jpg" \
  --output ./output/demo

# 批量生成
python batch_pipeline.py \
  --input-dir ../data/原图/app首页类-开屏广告弹窗 \
  --gt-category "弹窗覆盖原UI" --output ./batch_output --run

# 注入决策流水线
python injection_pipeline.py \
  --input-dir examples/injection_demo \
  --output-dir output/injected --interactive

# 一键启动
bash launch.sh              # 交互式菜单
bash launch.sh single       # 单图模式
bash launch.sh list         # 列出异常类别
```

---

## 子模块架构

### analysis/ — AI 感知层

| 模块 | 职责 |
|------|------|
| `omni_extractor.py` | OmniParser 本地推理（YOLO + PaddleOCR + Florence2） |
| `omni_vlm_fusion.py` | VLM 语义分组：合并/过滤/去重 |
| `gt_bounds.py` | GT 模板精确边界框提取 |
| `visualize.py` | 检测结果可视化（边界框标注） |

### renderers/ — 异常渲染层

| 模块 | 对应模式 | 机制 |
|------|---------|------|
| `base.py` | - | 渲染器统一基类 |
| `patch.py` | `dialog` | VLM 语义分析 + PIL/AI 弹窗合成叠加 |
| `area_loading.py` | `area_loading` | VLM 推荐目标区域 + Loading 图标覆盖 |
| `content_duplicate.py` | `content_duplicate` | 组件裁剪 + 底部浮层扩展渲染 |
| `text_overlay.py` | `text_overlay` | VLM 编辑规划 + PIL 局部文字精确绘制 |

### generators/ — 元数据生成层

| 模块 | 职责 |
|------|------|
| `meta.py` | VLM 驱动 meta.json 自动生成（GT 模板视觉特征描述） |
| `filename_descriptions.py` | 基于文件名的异常描述生成 |

### injection/ — 注入决策层

| 模块 | 职责 |
|------|------|
| `sequence_analyzer.py` | 增量式操作序列语义分析 |
| `anomaly_recommender.py` | 基于语义上下文的异常推荐决策 |
| `sequence_rewriter.py` | 将推荐转化为修改后的操作序列 |
| `prompts.py` | VLM 提示词模板 |

### utils/ — 工具库

| 模块 | 职责 |
|------|------|
| `common.py` | 图片编码（base64）、JSON 提取、颜色解析 |
| `semantic_dialog_generator.py` | 语义感知弹窗生成（DashScope AI + PIL） |
| `meta_loader.py` | GT 元数据加载与管理 |
| `gt_manager.py` | GT 模板提取、风格分析、Few-shot 参考 |
| `component_position_resolver.py` | UI-JSON 精确组件定位（多级匹配 + 百分比回退） |
| `reference_analyzer.py` | 参考图片风格分析 |
| `anomaly_sample_manager.py` | 异常样本聚类与导出 |
| `history_manager.py` | 注入历史记录管理 |

---

## 完整参数说明

### run_pipeline.py

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--screenshot, -s` | 原始截图路径 | 必需 |
| `--instruction, -i` | 异常指令 | 必需 |
| `--output, -o` | 输出目录 | `./output` |
| `--anomaly-mode` | `dialog` / `area_loading` / `content_duplicate` / `text_overlay` | `dialog` |
| `--gt-category` | GT 模板类别名 | - |
| `--gt-sample` | GT 模板样本文件名 | - |
| `--gt-dir` | GT 样本目录（可选，默认自动检测） | - |
| `--reference, -r` | 参考弹窗图片（dialog 模式） | - |
| `--reference-icon` | 参考加载图标（area_loading 模式） | - |
| `--target-component` | 目标组件 ID（area_loading 模式） | 自动推荐 |
| `--api-key` | VLM API 密钥 | `VLM_API_KEY` 环境变量 |
| `--api-url` | VLM API 端点 | `VLM_API_URL` 环境变量 |
| `--structure-model` | 结构提取模型 | `STRUCTURE_MODEL` 环境变量 |
| `--vlm-model` | VLM 模型名称 | `VLM_MODEL` 环境变量 |
| `--omni-device` | OmniParser 设备 (`cuda`/`cpu`) | `OMNIPARSER_DEVICE` 环境变量 |
| `--no-visualize` | 禁用检测结果可视化 | False |

### injection_pipeline.py

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--input-dir` | 输入目录（含 task.json + screenshots/） | 必需 |
| `--output-dir` | 输出目录 | 必需 |
| `--interactive` | 启用用户确认流程 | False |

### batch_pipeline.py

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--input-dir` | 原图目录 | 必需 |
| `--gt-category` | GT 模板类别 | 必需 |
| `--output` | 输出目录 | `./batch_output` |
| `--run` | 实际执行（默认 dry-run） | False |

---

## 工作流示例

### 工作流 1: 完整 Pipeline

```bash
python run_pipeline.py \
  --screenshot ./test.png \
  --instruction "网络超时错误" \
  --output ./output/

# 输出：
# - test_stage1_omni_raw_*.json      (OmniParser 检测)
# - test_stage2_filtered_*.json      (VLM 过滤)
# - test_final_*.png                 (最终异常截图)
# - test_pipeline_meta_*.json        (元数据)
```

### 工作流 2: GT 模板驱动生成

```bash
python run_pipeline.py \
  --screenshot ./test.png \
  --instruction "生成下拉菜单弹窗" \
  --gt-category "弹窗覆盖原UI" \
  --gt-sample "弹出提示.jpg" \
  --output ./output/

# 弹窗样式和位置精确匹配 GT 样本
```

### 工作流 3: 注入决策

```bash
# 准备输入目录
# input/
# ├── task.json           # {"description": "购物流程"}
# └── screenshots/
#     ├── step_00.png
#     ├── step_01.png
#     └── ...

python injection_pipeline.py \
  --input-dir ./input \
  --output-dir ./output/injected \
  --interactive
```

### 工作流 4: 调试和验证

```bash
# 运行 pipeline
python run_pipeline.py --screenshot ./test.png --instruction "..." --output ./output/

# 对比 Stage 1 和 Stage 2 可视化结果，验证 VLM 过滤效果
# 查看 output/ 目录下的 *_stage1_annotated_*.png 和 *_stage2_annotated_*.png
```

---

## 性能指标

| 阶段 | 耗时 | 主要成本 |
|-----|------|--------|
| Stage 1 (OmniParser) | 10-30s | YOLO + OCR 推理 |
| Stage 2 (VLM 过滤) | 30-60s | API 调用 |
| Stage 3 (弹窗生成) | 20-40s | AI 图像生成 |
| Stage 3 (内容重复) | 10-30s | 组件裁剪 + 浮层合成 |
| **总计** | **60-130s** | - |

优化建议：
- 使用 GPU 加速 Stage 1（`--omni-device cuda`）
- 缓存 Stage 1 结果，避免重复检测
- 批量处理时共享 VLM 连接

---

## 故障排查

| 问题 | 解决方案 |
|------|----------|
| OmniParser 导入失败 | `cd ../third_party/OmniParser && pip install -r requirements.txt` |
| VLM API 超时 | 检查网络连接，增加脚本中的 `timeout=180` |
| CUDA 内存不足 | 使用 `--omni-device cpu` |
| 弹窗背景不是纯黑色 | 检查 `utils/semantic_dialog_generator.py` 提示词 |

---

## 环境变量

```bash
VLM_API_KEY=sk-xxx           # VLM API 密钥（必需）
VLM_API_URL=https://...      # VLM API 端点
VLM_MODEL=gpt-4o             # VLM 模型名称
STRUCTURE_MODEL=qwen-vl-max  # 结构提取模型
DASHSCOPE_API_KEY=sk-xxx     # DashScope（可选，用于 AI 图像生成）
OMNIPARSER_DEVICE=cuda       # OmniParser 设备
```

---

**最后更新**: 2026-03-09
