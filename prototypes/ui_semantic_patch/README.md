# UI 语义补丁框架

**"逻辑层修改 + 物理层绘制"** 的解耦架构 — 通过 OmniParser 精确检测 + VLM 语义理解 + 程序化渲染，实现异常 UI 场景的自动生成。

---

## 技术架构

```
原始截图 → [Stage 1] OmniParser 粗检测 → [Stage 2] VLM 语义分组 → [Stage 3] 异常渲染 → 异常截图
              YOLO + PaddleOCR + Florence2     合并/过滤/语义分组       4 种模式专用渲染器
```

| 阶段 | 技术 | 输出 |
|------|------|------|
| Stage 1 | OmniParser (YOLO + PaddleOCR + Florence2) | `*_stage1_omni_raw_*.json` |
| Stage 2 | VLM 语义过滤与分组 | `*_stage2_filtered_*.json` |
| Stage 3 | 模式专用渲染器 | `*_final_*.png` |

所有中间结果均保存，便于调试和优化。

---

## 快速上手

### 环境准备

```bash
cp ../../.env.example ../../.env              # 填写 VLM_API_KEY、DASHSCOPE_API_KEY
pip install -r requirements.txt               # 核心依赖
pip install -r third_party/OmniParser/requirements.txt  # OmniParser（需 GPU 推荐）
```

### 四种模式示例

```bash
cd scripts

# 1. dialog — 弹窗覆盖
python run_pipeline.py \
  --screenshot ../data/原图/app首页类-开屏广告弹窗/携程旅行01.jpg \
  --instruction "生成优惠券广告弹窗" \
  --gt-category "弹窗覆盖原UI" --gt-sample "弹出广告.jpg" \
  --output ./output/demo

# 2. area_loading — 区域加载异常
python run_pipeline.py \
  --screenshot ../data/原图/影视剧集类-内容歧义、重复/腾讯视频.jpg \
  --instruction "模拟列表加载超时" \
  --anomaly-mode area_loading \
  --output ./output/demo

# 3. content_duplicate — 内容重复
python run_pipeline.py \
  --screenshot ../data/原图/影视剧集类-内容歧义、重复/腾讯视频.jpg \
  --instruction "模拟底部信息重复显示" \
  --anomaly-mode content_duplicate \
  --gt-category "内容歧义、重复" --gt-sample "部分信息重复.jpg" \
  --output ./output/demo

# 4. text_overlay — 局部文字覆盖
python run_pipeline.py \
  --screenshot ../data/原图/app首页类-开屏广告弹窗/携程旅行01.jpg \
  --instruction "在租车服务卡片中插入优惠信息" \
  --anomaly-mode text_overlay \
  --output ./output/demo
```

### 一键启动

```bash
cd scripts
bash launch.sh              # 交互式菜单
bash launch.sh single       # 单图模式
bash launch.sh batch --run  # 批量模式
bash launch.sh list         # 列出异常类别
```

---

## 模块架构

```
┌─────────────────────────────────────────────────────────────┐
│                      run_pipeline.py                        │
│              batch_pipeline.py (批量入口)                    │
│                        (主控层)                              │
└──────────────────┬──────────────────┬───────────────────────┘
                   │                  │
        ┌──────────▼──────────┐ ┌─────▼─────────────┐
        │     analysis/       │ │    injection/      │
        │ (Stage 1+2 AI感知)  │ │ (注入决策层)       │
        └──────────┬──────────┘ └─────┬─────────────┘
                   │                  │
        ┌──────────▼──────────────────▼───────┐
        │              renderers/              │
        │        (Stage 3 异常渲染层)           │
        └──────────────────┬──────────────────┘
                           │
        ┌──────────────────▼──────────────────┐
        │         utils/ + generators/         │
        │        (工具库 + 元数据生成)          │
        └─────────────────────────────────────┘
```

| 层级 | 模块 | 职责 |
|------|------|------|
| **主控** | `run_pipeline.py` | 三阶段串联，单图入口 |
| | `batch_pipeline.py` | 批量执行（原图 × GT 笛卡尔积） |
| | `injection_pipeline.py` | 注入决策流水线（操作序列分析） |
| **AI 感知** | `analysis/omni_extractor.py` | OmniParser 本地推理 |
| | `analysis/omni_vlm_fusion.py` | VLM 语义分组 |
| | `analysis/gt_bounds.py` | GT 边界框提取 |
| | `analysis/visualize.py` | 检测结果可视化 |
| **异常渲染** | `renderers/patch.py` | dialog 弹窗渲染 |
| | `renderers/area_loading.py` | 区域加载异常 |
| | `renderers/content_duplicate.py` | 内容重复 |
| | `renderers/text_overlay.py` | 文字覆盖 |
| | `renderers/base.py` | 渲染器基类 |
| **注入决策** | `injection/sequence_analyzer.py` | 操作序列语义分析 |
| | `injection/anomaly_recommender.py` | 异常推荐决策 |
| | `injection/sequence_rewriter.py` | 序列改写 |
| **元数据** | `generators/meta.py` | meta.json 自动生成 |
| | `generators/filename_descriptions.py` | 文件名描述生成 |
| **工具库** | `utils/common.py` | 图片编码、JSON 提取 |
| | `utils/meta_loader.py` | GT 元数据加载 |
| | `utils/component_position_resolver.py` | 组件定位 |
| | `utils/semantic_dialog_generator.py` | 弹窗生成器 |

> 详细接口契约与数据流见 [代码手册](../../docs/plans/2026-03-06-code-manual.md)

---

## 目录结构

```
ui_semantic_patch/
├── scripts/
│   ├── run_pipeline.py                # 三阶段主流水线
│   ├── batch_pipeline.py              # 批量生成
│   ├── injection_pipeline.py          # 注入决策流水线
│   ├── launch.sh                      # 一键启动
│   ├── analysis/                      # AI 感知层
│   │   ├── omni_extractor.py          #   OmniParser 推理
│   │   ├── omni_vlm_fusion.py         #   VLM 语义分组
│   │   ├── gt_bounds.py               #   GT 边界框提取
│   │   └── visualize.py               #   检测结果可视化
│   ├── renderers/                     # 异常渲染层
│   │   ├── base.py                    #   渲染器基类
│   │   ├── patch.py                   #   dialog 弹窗
│   │   ├── area_loading.py            #   区域加载
│   │   ├── content_duplicate.py       #   内容重复
│   │   └── text_overlay.py            #   文字覆盖
│   ├── generators/                    # 元数据生成层
│   │   ├── meta.py                    #   meta.json 生成
│   │   └── filename_descriptions.py   #   文件名描述
│   ├── injection/                     # 注入决策层
│   │   ├── sequence_analyzer.py       #   操作序列分析
│   │   ├── anomaly_recommender.py     #   异常推荐
│   │   ├── sequence_rewriter.py       #   序列改写
│   │   └── prompts.py                 #   VLM 提示词
│   ├── utils/                         # 工具库
│   │   ├── common.py
│   │   ├── semantic_dialog_generator.py
│   │   ├── meta_loader.py
│   │   ├── component_position_resolver.py
│   │   ├── gt_manager.py
│   │   ├── reference_analyzer.py
│   │   ├── anomaly_sample_manager.py
│   │   └── history_manager.py
│   └── tests/                         # 测试
├── data/
│   ├── 原图/                          # 原始 APP 截图（4 类 6 张）
│   └── Agent执行遇到的典型异常UI类型/  # GT 模板（3 类 10 个样本）
├── third_party/OmniParser/            # 本地集成
├── examples/                          # 示例文件
├── requirements.txt
└── README.md
```

---

## 命令行参数速查

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--screenshot, -s` | 原始截图路径 | 必需 |
| `--instruction, -i` | 异常指令 | 必需 |
| `--output, -o` | 输出目录 | `./output` |
| `--anomaly-mode` | `dialog` / `area_loading` / `content_duplicate` / `text_overlay` | `dialog` |
| `--gt-category` | GT 模板类别 | - |
| `--gt-sample` | GT 模板样本 | - |
| `--reference, -r` | 参考弹窗图片 | - |
| `--reference-icon` | 参考加载图标 | - |
| `--omni-device` | OmniParser 设备 (`cuda`/`cpu`) | 环境变量 |
| `--api-key` | VLM API 密钥 | 环境变量 |

---

## 输出文件说明

| 文件模式 | 说明 | 生成阶段 |
|---------|------|--------|
| `*_stage1_omni_raw_*.json` | OmniParser 原始检测 | Stage 1 |
| `*_stage1_annotated_*.png` | Stage 1 可视化 | Stage 1 |
| `*_stage2_filtered_*.json` | VLM 语义过滤后 | Stage 2 |
| `*_stage2_annotated_*.png` | Stage 2 可视化 | Stage 2 |
| `*_final_*.png` | 最终异常截图 | Stage 3 |
| `*_pipeline_meta_*.json` | 流水线元数据 | 完成时 |

---

## 实施路线

### Phase 1 - POC ✅
- OmniParser + VLM 融合模式
- 语义感知弹窗生成、参考图风格学习

### Phase 2 - 工具链 ✅
- 四种异常模式（dialog / area_loading / content_duplicate / text_overlay）
- GT 模板驱动、批量生成、一键启动
- 架构重构：analysis / renderers / generators / injection 子包
- 注入决策流水线

### Phase 3 - 待实施
- [ ] ControlNet 精细控制
- [ ] 样式库（Style-Library）
- [ ] 闭环验证与微调

---

## 技术说明

### 为什么不用 Diffusion 重绘全图？

1. **文字清晰度** — 字体引擎渲染无乱码/模糊
2. **可控性** — 局部修改精确可控
3. **效率** — 远快于全图生成
4. **一致性** — 与 Native 原生效果高度一致

### 融合模式解决了什么？

| 问题 | 说明 | 解决方案 |
|------|------|----------|
| 海报内文字 | YOLO 检测海报装饰文字 | VLM 合并为 ImageView |
| 卡片内元素 | 多个元素被分别检测 | VLM 合并为 Card |
| 重复检测 | OCR 和 YOLO 重复 | VLM 去重 |

---

**最后更新**: 2026-03-09
