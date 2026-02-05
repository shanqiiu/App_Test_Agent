# UI 异常场景生成流水线 - 脚本文档

完整的 3 阶段 UI 异常场景自动生成流水线。

## 快速开始

```bash
# 基本用法
python run_pipeline.py \
  --screenshot ./screenshot.png \
  --instruction "模拟网络超时弹窗" \
  --output ./output/

# 完整示例（指定所有参数）
python run_pipeline.py \
  --screenshot ./screenshot.png \
  --instruction "库存不足提示" \
  --output ./output/ \
  --api-key sk-xxx \
  --vlm-model gpt-4o \
  --fonts-dir ./fonts/ \
  --omni-device cuda

# GT 模板驱动生成（推荐，精准控制弹窗样式和位置）
# --gt-dir 可省略，自动使用默认路径
python run_pipeline.py \
  --screenshot ./screenshot.png \
  --instruction "显示下拉菜单" \
  --output ./output/ \
  --gt-category "弹窗覆盖原UI" \
  --gt-sample "弹出提示.jpg"
```

## 核心脚本

### 1. `run_pipeline.py` - 主流水线

执行完整的 3 阶段流水线：

**Stage 1: OmniParser 粗检测**
- 使用 YOLO + PaddleOCR + Florence2 检测 UI 组件
- 获得精确的边界框和文本内容
- 输出: `*_stage1_omni_raw_*.json`

**Stage 2: VLM 语义过滤**
- 使用大模型分析截图内容
- 合并属于同一组件的多个检测框
- 删除冗余和错误的检测框
- 输出: `*_stage2_filtered_*.json`

**Stage 3: 异常弹窗生成与合并**
- 直接调用语义弹窗生成器
- 根据页面内容生成上下文相关的异常弹窗
- 支持 GT 模板驱动：通过 `--gt-category` + `--gt-sample` 从 `meta.json` 读取精确的样式和位置参数
- 支持多种弹窗位置类型（见下方 [弹窗位置类型](#弹窗位置类型)）
- 将弹窗合并到原截图上
- 输出: `*_final_*.png`

```bash
python run_pipeline.py -h  # 查看所有参数
```

### 2. `omni_extractor.py` - OmniParser 检测工具

单独运行 OmniParser 进行 UI 结构提取。

```bash
# 基本用法
python omni_extractor.py --image ./screenshot.png

# 保存到指定路径
python omni_extractor.py \
  --image ./screenshot.png \
  --output ./structure.json

# 使用 CPU（默认自动选择）
python omni_extractor.py \
  --image ./screenshot.png \
  --device cpu

# 调整检测阈值
python omni_extractor.py \
  --image ./screenshot.png \
  --box-threshold 0.1 \
  --iou-threshold 0.5
```

输出: UI-JSON 格式的组件列表

### 3. `omni_vlm_fusion.py` - OmniParser + VLM 融合

使用 OmniParser 检测 + VLM 语义过滤进行UI 结构提取。

```bash
# 基本用法
python omni_vlm_fusion.py \
  --image ./screenshot.png \
  --api-key sk-xxx \
  --vlm-model gpt-4o

# 保存到指定路径
python omni_vlm_fusion.py \
  --image ./screenshot.png \
  --api-key sk-xxx \
  --output ./filtered.json
```

输出: 语义正确的 UI-JSON（处理后的组件列表）

### 4. `vlm_patch.py` - VLM 推理生成 JSON Patch

⚠️ **已弃用** - 在简化的 3 阶段流水线中不再使用此脚本。

原用途：根据截图和异常指令生成 UI 修改操作（add/modify/delete）。
现在由 `semantic_dialog_generator.py` 直接生成弹窗代替。

## 辅助工具

### 5. `visualize_omni.py` - 通用可视化工具

将 UI-JSON 的检测结果可视化到截图上。

```bash
# 基本用法
python visualize_omni.py \
  --screenshot ./screenshot.png \
  --ui-json ./structure.json \
  --output ./annotated.png

# 自定义样式
python visualize_omni.py \
  --screenshot ./screenshot.png \
  --ui-json ./structure.json \
  --output ./annotated.png \
  --font-size 12 \
  --border-width 3

# 仅显示边界框，不显示文本
python visualize_omni.py \
  --screenshot ./screenshot.png \
  --ui-json ./structure.json \
  --output ./annotated.png \
  --no-text
```

输出: PNG 图片，显示所有检测到的 UI 组件的边界框和标签

### 6. `visualize_pipeline_stage1.py` - Pipeline 快速可视化

快速可视化 `run_pipeline.py` 的 Stage 1 输出。

```bash
# 运行 pipeline
python run_pipeline.py \
  --screenshot ./test.png \
  --instruction "..." \
  --output ./output/

# 可视化 Stage 1 检测结果
python visualize_pipeline_stage1.py \
  --screenshot ./test.png \
  --stage1-json ./output/test_stage1_omni_raw_*.json
```

输出: PNG 图片，显示 OmniParser 的原始检测结果

### 7. `patch_renderer.py` - 弹窗渲染和合并

处理弹窗图片和原截图的合并逻辑（由 `run_pipeline.py` 调用）。

类关键方法：
- `apply_patch()` - 应用修改操作（仅执行 add 操作）
- `generate_dialog_and_merge()` - 生成异常弹窗并合并到截图
- `save()` - 保存最终结果

### 8. `semantic_dialog_generator.py` - 语义弹窗生成

使用 AI 生成上下文相关的异常弹窗（由 `patch_renderer.py` 调用）。

关键方法：
- `generate()` - 根据页面内容和异常指令生成弹窗

特性：
- 自动背景移除（纯黑色背景）
- 边界平滑（alpha 阈值处理）
- DashScope AI 图像生成

### 9. `img2xml.py` - VLM UI 结构提取（已弃用）

原来的 VLM 方案，已被 OmniParser + VLM 融合替代。

## 工作流示例

### 工作流 1: 完整 Pipeline（推荐）

```bash
# 一条命令完成所有工作
python run_pipeline.py \
  --screenshot ./test.png \
  --instruction "网络超时错误" \
  --output ./output/

# 输出：
# - test_stage1_omni_raw_*.json (OmniParser 原始检测)
# - test_stage2_filtered_*.json (VLM 语义过滤)
# - test_final_*.png (最终异常截图)
# - test_pipeline_meta_*.json (元数据)
```

### 工作流 2: 单独使用 OmniParser

```bash
# 仅提取 UI 结构（不生成异常弹窗）
python omni_extractor.py \
  --image ./test.png \
  --output ./structure.json

# 可视化检测结果
python visualize_omni.py \
  --screenshot ./test.png \
  --ui-json ./structure.json \
  --output ./annotated.png
```

### 工作流 3: GT 模板驱动生成

```bash
# 查看可用的 GT 类别和样本
ls ../data/Agent执行遇到的典型异常UI类型/analysis/gt_templates/

# 使用 GT 模板驱动生成（--gt-dir 自动检测，无需手动指定）
python run_pipeline.py \
  --screenshot ./test.png \
  --instruction "生成下拉菜单弹窗" \
  --output ./output/ \
  --gt-category "弹窗覆盖原UI" \
  --gt-sample "弹出提示.jpg"

# 输出同工作流 1，但弹窗样式和位置精确匹配 GT 样本
# 位置由 meta.json 中的 dialog_position 字段控制
```

### 工作流 4: 调试和验证

```bash
# 第 1 步：运行 pipeline
python run_pipeline.py \
  --screenshot ./test.png \
  --instruction "..." \
  --output ./output/

# 第 2 步：可视化 Stage 1
python visualize_pipeline_stage1.py \
  --screenshot ./test.png \
  --stage1-json ./output/test_stage1_omni_raw_*.json

# 第 3 步：可视化 Stage 2（VLM 过滤后）
python visualize_omni.py \
  --screenshot ./test.png \
  --ui-json ./output/test_stage2_filtered_*.json \
  --output ./output/test_stage2_annotated.png

# 第 4 步：比较两个可视化，验证 VLM 是否正确过滤了检测结果
```

## 环境变量

关键环境变量（可选）：

```bash
# VLM API 密钥（run_pipeline.py 的默认值）
export VLM_API_KEY=sk-xxx

# DashScope API 密钥（用于语义弹窗生成）
export DASHSCOPE_API_KEY=sk-xxx
```

## 弹窗位置类型

Stage 3 支持通过 `meta.json` 中的 `dialog_position` 字段精确控制弹窗放置位置：

| `dialog_position` 值 | 说明 | 典型场景 |
|---|---|---|
| `center` | 屏幕正中央 | 奖励弹窗、权限请求 |
| `bottom-left-inline` | 左下角内联，紧贴触发元素 | 排序下拉菜单 |
| `bottom-center-floating` | 底部居中浮动 | 提示气泡 |
| `bottom-fixed` | 底部固定，贴底 | 优惠券弹窗 |
| `bottom-floating` | 底部浮动，有边距 | 横幅提示 |
| `top` | 顶部 | 顶部通知 |
| `multi-layer` | 多层叠加 | 引导教程 |

## 输出文件说明

| 文件模式 | 说明 | 生成阶段 |
|---------|------|--------|
| `*_stage1_omni_raw_*.json` | OmniParser 原始检测结果 | Stage 1 |
| `*_stage2_filtered_*.json` | VLM 语义过滤后的结果 | Stage 2 |
| `*_final_*.png` | 最终异常场景截图 | Stage 3 |
| `*_pipeline_meta_*.json` | 流水线元数据 | 完成时 |

## 常见参数

### VLM API 参数

```bash
# 更改 VLM 模型（默认 qwen-vl-max）
--structure-model gpt-4o

# 更改 API 端点
--api-url https://api.openai.com/v1/chat/completions

# 使用自定义 API 密钥
--api-key sk-custom-xxx
```

### 生成器参数

```bash
# 指定字体目录
--fonts-dir ./fonts/

# 指定 GT 样本目录（可选，默认自动检测）
--gt-dir ./reference_dialogs/

# GT 模板驱动生成（从 meta.json 读取样式/位置）
--gt-category "弹窗覆盖原UI"
--gt-sample "弹出提示.jpg"

# 异常模式选择
--anomaly-mode dialog         # 全屏弹窗（默认）
--anomaly-mode area_loading   # 区域加载图标

# 为弹窗模型指定不同的 API 端点和模型
--vlm-api-url https://xxx
--vlm-model gpt-4o

# 指定参考弹窗图片（用于样式学习）
--reference ./reference_dialog.png

# 指定参考加载图标（area_loading 模式）
--reference-icon ./loading_icon.png

# 目标组件ID（area_loading 模式）
--target-component 5
```

### 硬件参数

```bash
# 指定 OmniParser 运行设备
--omni-device cuda    # 使用 GPU
--omni-device cpu     # 使用 CPU
```

## 性能指标

| 阶段 | 耗时 | 主要成本 |
|-----|------|--------|
| Stage 1 (OmniParser) | 10-30s | YOLO + OCR 推理 |
| Stage 2 (VLM 过滤) | 30-60s | API 调用 + 网络延迟 |
| Stage 3 (弹窗生成) | 20-40s | AI 图像生成 |
| **总计** | **60-130s** | - |

优化建议：
- 使用 GPU 加速 Stage 1 (通过 `--omni-device cuda`)
- 缓存 Stage 1 结果，避免重复检测
- 批量处理多张图片时，共享 VLM 连接

## 故障排查

### 问题 1: OmniParser 模块导入失败

```
[WARN] OmniParser 导入失败
```

**解决：**
```bash
cd ../OmniParser
pip install -r requirements.txt
```

### 问题 2: VLM API 超时

```
⚠ 网络连接错误: Timeout
```

**解决：**
- 检查网络连接
- 增加 API 超时时间（修改脚本中的 `timeout=180`）
- 使用国内镜像或代理

### 问题 3: CUDA 内存不足

```
RuntimeError: CUDA out of memory
```

**解决：**
```bash
python run_pipeline.py ... --omni-device cpu  # 使用 CPU
```

### 问题 4: 生成的弹窗背景不是纯黑色

**原因：** AI 图像生成模型没有遵循提示

**解决：** 检查 `semantic_dialog_generator.py:1538-1570` 的提示词

## 扩展和定制

### 添加新的组件类型

编辑 `omni_extractor.py:140-188` 的 `map_element_type()` 函数

### 修改可视化颜色

编辑 `visualize_omni.py:15-30` 的 `CLASS_COLORS` 字典

### 自定义异常弹窗内容

编辑 `semantic_dialog_generator.py` 中的提示词和生成逻辑

## 相关文档

- [可视化指南](./VISUALIZATION_GUIDE.md) - 详细的可视化工具使用说明
- [Pipeline 设计](../../docs/) - 技术设计文档

## 文件树

```
scripts/
├── run_pipeline.py                    # 主流水线
├── omni_extractor.py                  # OmniParser 工具
├── omni_vlm_fusion.py                 # OmniParser + VLM
├── vlm_patch.py                       # (已弃用) JSON Patch 生成
├── patch_renderer.py                  # 弹窗渲染
├── area_loading_renderer.py           # 区域加载图标渲染
├── utils/
│   ├── semantic_dialog_generator.py   # 弹窗生成
│   ├── meta_loader.py                 # GT 模板元数据加载
│   ├── gt_manager.py                  # GT 模板管理
│   ├── reference_analyzer.py          # 参考图分析
│   ├── common.py                      # 通用工具函数
│   └── ...
├── visualize_omni.py                  # ✨ 通用可视化
├── visualize_pipeline_stage1.py        # ✨ Pipeline 可视化
├── VISUALIZATION_GUIDE.md             # ✨ 可视化文档
├── README.md                          # 本文件
└── ...
```

---

**最后更新**: 2026-02-05
**Pipeline 版本**: 3.1 (支持 GT 模板驱动 + 多种弹窗位置)
