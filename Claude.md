# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

本项目专注于AI智能体测试技术研究，特别是**异常场景测试的自动化生成**。
---

## 项目定位

- **项目类型**: 技术研究
- **当前阶段**: 原型开发与优化（Phase 2）
- **核心目标**: 构建异常测试场景自动生成平台

---

## 环境配置

```bash
# 1. 复制并填写 API 密钥
cp .env.example .env

# 2. 安装 ui_semantic_patch 核心依赖
pip install -r prototypes/ui_semantic_patch/requirements.txt

# 3. 安装 OmniParser 依赖（需要 GPU/CUDA 推荐）
pip install -r prototypes/ui_semantic_patch/third_party/OmniParser/requirements.txt
```

`.env` 必需变量：
- `VLM_API_KEY` — OpenAI 兼容接口密钥（UI 分析/语义理解）
- `DASHSCOPE_API_KEY` — 阿里云 DashScope 密钥（AI 图像生成，可选）

---

## 运行原型代码

所有脚本从 `prototypes/ui_semantic_patch/scripts/` 目录执行。

### 一键启动（推荐）

```bash
cd prototypes/ui_semantic_patch/scripts
bash launch.sh              # 交互式菜单
bash launch.sh single       # 单图模式（使用脚本内默认配置）
bash launch.sh batch --run  # 批量模式
bash launch.sh list         # 列出所有可用异常类别
```

### 直接调用流水线

```bash
cd prototypes/ui_semantic_patch/scripts

# 弹窗模式（meta-driven，推荐）
python run_pipeline.py \
  --screenshot ../data/原图/app首页类-开屏广告弹窗/携程旅行01.jpg \
  --instruction "生成优惠券广告弹窗" \
  --gt-category "弹窗覆盖原UI" \
  --gt-sample "弹出广告.jpg" \
  --output ./output/demo

# 区域加载模式
python run_pipeline.py \
  --screenshot ../data/原图/影视剧集类-内容歧义、重复/腾讯视频.jpg \
  --instruction "模拟列表加载超时" \
  --anomaly-mode area_loading \
  --output ./output/demo

# 内容重复模式
python run_pipeline.py \
  --screenshot ../data/原图/影视剧集类-内容歧义、重复/腾讯视频.jpg \
  --instruction "模拟底部信息重复显示" \
  --anomaly-mode content_duplicate \
  --gt-category "内容歧义、重复" \
  --gt-sample "部分信息重复.jpg" \
  --output ./output/demo

# 局部文字覆盖模式
python run_pipeline.py \
  --screenshot ../data/原图/app首页类-开屏广告弹窗/携程旅行01.jpg \
  --instruction "在租车服务卡片中插入优惠信息" \
  --anomaly-mode text_overlay \
  --output ./output/demo
```

### 批量生成

```bash
cd prototypes/ui_semantic_patch/scripts
python batch_pipeline.py \
  --input-dir ../data/原图/app首页类-开屏广告弹窗 \
  --gt-category "弹窗覆盖原UI" \
  --output ./batch_output
  # 加 --run 实际执行，否则为 dry-run
```

---

## 核心架构

### `ui_semantic_patch` 流水线（三阶段）

```
截图输入 → Stage 1: OmniParser → Stage 2: VLM 语义分组 → Stage 3: 异常渲染 → 输出图像
```

**关键模块（均位于 `scripts/`）**:

| 模块 | 职责 |
|------|------|
| `run_pipeline.py` | 主流水线入口，三阶段串联执行 |
| `omni_extractor.py` | 调用 OmniParser（YOLO + PaddleOCR + Florence2）检测 UI 组件 |
| `omni_vlm_fusion.py` | 将 OmniParser 检测结果传给 VLM 做语义分组，产出结构化 UI-JSON |
| `patch_renderer.py` | `dialog` 模式弹窗渲染（现被 `semantic_dialog_generator` 驱动） |
| `area_loading_renderer.py` | `area_loading` 模式：在目标组件中心覆盖加载图标 |
| `content_duplicate_renderer.py` | `content_duplicate` 模式：底部浮层复制组件 |
| `batch_pipeline.py` | 批量执行，遍历原图目录 × GT 类别 |
| `generate_meta.py` | 用 VLM 自动生成 `meta.json`（描述 GT 模板的视觉特征） |
| `extract_gt_bounds.py` | 精确提取 GT 模板中弹窗的像素边界框 |
| `utils/semantic_dialog_generator.py` | meta-driven 弹窗生成：读取 meta.json 风格 + VLM 生成文案 + DashScope AI 图像生成 |
| `utils/meta_loader.py` | 读取 `meta.json`，提供视觉特征和位置信息 |
| `utils/component_position_resolver.py` | 根据指令关键词匹配 UI-JSON 组件，精确定位弹窗位置 |
| `utils/reference_analyzer.py` | 分析参考图片风格（颜色、布局） |

**数据流关键数据结构**:
- Stage 1 输出：`{components: [{index, bounds, text, class}...], componentCount}`
- Stage 2 输出（UI-JSON）：同上但经过语义过滤和分组合并
- `meta.json`：每个 GT 模板目录下的视觉特征描述，驱动 dialog 模式生成

**GT 模板数据**（`data/Agent执行遇到的典型异常UI类型/analysis/gt_templates/`）:
- `弹窗覆盖原UI/` — 8 个弹窗样本（含 `meta.json`）
- `内容歧义、重复/` — 1 个样本
- `loading_timeout/` — 1 个样本

**原图数据**（`data/原图/`）:
- `app首页类-开屏广告弹窗/` — 携程旅行 01、02
- `个人主页类-控件点击弹窗/` — 抖音原图 01、02
- `影视剧集类-内容歧义、重复/` — 腾讯视频

---

## 文档结构

```
docs/
├── research/        # 调研文档（命名：NN_描述.md）
├── technical/       # 技术栈与工具.md、术语表.md
├── references/      # 学术研究.md、开源项目.md
├── planning/        # 研究路线图.md、待研究问题.md
└── setup/           # 环境搭建指南.md
```

**文档管理规则**:
- 新调研文档 → `docs/research/NN_描述.md`，更新 `docs/research/README.md`
- 新工具/术语 → 对应技术文档，不重复创建
- 优先级标记：🔥 高 / ⭐ 中 / 💡 探索

---

## 提交规范

- `docs:` — 文档更新
- `feat:` — 新功能原型
- `refactor:` — 代码或文档重构
- `experiment:` — 实验性代码
- `chore:` — 配置、依赖等

---

## 核心术语

| 术语 | 英文 | 说明 |
|------|------|------|
| 智能体 | AI Agent | 能够感知、决策、执行的AI系统 |
| 异常场景 | Anomaly Scenario | 偏离正常行为的测试场景 |
| GT 模板 | Ground Truth Template | 真实异常截图，作为生成参考 |
| UI-JSON | - | Stage 2 输出的结构化界面表示 |
| meta-driven | - | 由 meta.json 驱动的精准生成模式 |
| RAG | Retrieval-Augmented Generation | 检索增强生成 |

---

**配置版本**: v4.0
**最后更新**: 2026-03-04
