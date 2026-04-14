# 文档体系重构设计

**日期**：2026-03-09
**类型**：文档重写
**目标读者**：内部开发者
**状态**：已批准

---

## 1. 设计概述

### 1.1 目标

更新仓库全部 README.md 并完善技术文档，反映最新的模块重构（renderers/、analysis/、generators/、injection/ 四个子包），为内部开发者提供清晰的架构指引。

### 1.2 范围

| 文档 | 操作 | 优先级 |
|------|------|--------|
| 根目录 README.md | 全面重写 | P0 |
| ui_semantic_patch/README.md | 全面重写 | P0 |
| ui_semantic_patch/scripts/README.md | 全面重写 | P0 |
| docs/plans/2026-03-06-code-manual.md | 增量更新 | P0 |
| docs/research/README.md | 简单同步 | P1 |
| docs/technical/README.md | 简单同步 | P1 |
| docs/planning/README.md | 简单同步 | P1 |
| docs/references/README.md | 简单同步 | P1 |

---

## 2. 文档体系结构

### 2.1 三层金字塔

```
┌─────────────────────────────────────────────┐
│              README.md (根目录)               │  ← 第一层：项目入口
│  项目概览 | 快速开始 | 文档导航 | 技术栈概要     │
└──────────────────────┬──────────────────────┘
                       │
    ┌──────────────────┼──────────────────┐
    ▼                  ▼                  ▼
┌────────────┐  ┌─────────────┐  ┌─────────────┐
│ prototypes │  │    docs/    │  │  Claude.md  │  ← 第二层：领域入口（AI 协作，亦作 CLAUDE.md）
│ README.md  │  │  README.md  │  │ (AI 协作)   │
└──────┬─────┘  └──────┬──────┘  └─────────────┘
       │               │
       ▼               ▼
┌─────────────┐  ┌─────────────────────────────┐
│  scripts/   │  │ code-manual.md              │  ← 第三层：深度技术文档
│  README.md  │  │ (模块架构 + 接口契约 + 数据流) │
└─────────────┘  └─────────────────────────────┘
```

### 2.2 核心原则

1. **递进式深度**：从概览 → 使用方法 → 实现细节
2. **单一职责**：每层文档只回答一类问题
3. **交叉引用**：所有深层文档可从上层导航到达

---

## 3. 各文档结构设计

### 3.1 根目录 README.md

```markdown
# App_Test_Agent

## 项目简介（2-3 段）
- 一句话定位
- 核心问题
- 解决方案概述 + 流程图

## 快速开始（3 步）
1. 环境准备（pip install + .env 配置）
2. 运行示例（一行命令 + 预期输出）
3. 探索更多（链接到 ui_semantic_patch/README.md）

## 核心能力（表格）
| 模式 | 说明 | 示例 |
|------|------|------|
| dialog | 弹窗注入 | 优惠券、广告 |
| area_loading | 加载异常 | 超时、网络错误 |
| content_duplicate | 内容重复 | 底部浮层 |
| text_overlay | 文字编辑 | 价格篡改 |

## 项目结构（树形图 + 一句话说明）
- 只展示到第二级目录，关键文件标注说明

## 文档导航（卡片式链接）
- 调研文档 → docs/research/
- 技术文档 → docs/technical/
- 代码手册 → docs/plans/code-manual.md
- 原型代码 → ui_semantic_patch/

## 当前进展（时间线）
- 最新 Milestone + 下一步工作

## 技术栈速览（分类 badges）

## 许可证 / 联系方式
```

**改进点**：
- 删除与 code-manual.md 重复的技术细节
- 强化快速开始：从"了解项目"改为"3 步上手"
- 核心能力前置：用表格直观展示异常模式（含 `modify_text*`）
- 精简项目结构：只到二级目录

---

### 3.2 ui_semantic_patch/README.md

```markdown
# UI 语义补丁框架

## 核心思想（1 段）
"逻辑层修改 + 物理层绘制" 解耦架构

## 技术架构（流程图）
原始截图 → [Stage 1] OmniParser → [Stage 2] VLM 语义分组 → [Stage 3] 异常渲染 → 输出

## 快速上手
### 环境准备
### 基础模式 + 文字编辑示例
### 一键启动

## 模块架构（简化版表格）
| 层级 | 模块 | 职责 |
|------|------|------|
| 主控 | run_pipeline.py | 三阶段串联 |
| 分析 | analysis/ | OmniParser + VLM 融合 |
| 渲染 | renderers/ | 多异常模式渲染（含 `modify_text*`） |
| 注入决策 | injection/ | 操作序列分析 + 异常推荐 |
| 工具 | utils/ | 公共函数 + 元数据加载 |

→ 详细接口见 code-manual.md

## 目录结构（更新后）

## 命令行参数速查表

## 输出文件说明

## 实施路线（Phase 1-3 + 当前状态）
```

**改进点**：
- 模块架构更新：反映四个子包
- 精简重复内容：技术细节引用 code-manual.md
- 新增 injection 模块说明

---

### 3.3 scripts/README.md

```markdown
# 脚本文档

## 快速命令
- 单图生成
- 批量生成
- 一键启动

## 子模块架构

### analysis/ — AI 感知层
| 模块 | 职责 |
|------|------|
| omni_extractor.py | OmniParser 本地推理 |
| omni_vlm_fusion.py | VLM 语义分组 |
| gt_bounds.py | GT 边界框提取 |
| visualize.py | 检测结果可视化 |

### renderers/ — 异常渲染层
| 模块 | 对应模式 |
|------|---------|
| patch.py | dialog |
| area_loading.py | area_loading |
| content_duplicate.py | content_duplicate |
| text_overlay.py | text_overlay |
| base.py | 渲染器基类 |

### generators/ — 元数据生成层
| 模块 | 职责 |
|------|------|
| meta.py | meta.json 自动生成 |
| filename_descriptions.py | 文件名描述生成 |

### injection/ — 注入决策层（新增）
| 模块 | 职责 |
|------|------|
| sequence_analyzer.py | 操作序列语义分析 |
| anomaly_recommender.py | 异常推荐决策 |
| sequence_rewriter.py | 序列改写 |

### utils/ — 工具库
| 模块 | 职责 |
|------|------|
| common.py | 图片编码、JSON 提取 |
| meta_loader.py | GT 元数据加载 |
| component_position_resolver.py | 组件定位 |
| semantic_dialog_generator.py | 弹窗生成器 |

## 完整参数说明（表格）

## 工作流示例

## 性能指标

## 故障排查
```

**改进点**：
- 子模块按包组织：反映重构后的 4 个子包结构
- injection 模块完整覆盖
- 快速命令置顶

---

### 3.4 code-manual.md 更新内容

#### 3.4.1 更新「架构层级总览」表格

| 层级 | 脚本 | 职责摘要 |
|------|------|---------|
| **第一层：主控** | `run_pipeline.py` | 三阶段串联，单图入口 |
| | `batch_pipeline.py` | 批量执行 |
| | `injection_pipeline.py` | 注入决策流水线（新增） |
| **第二层：AI 感知** | `analysis/omni_extractor.py` | OmniParser 推理 |
| | `analysis/omni_vlm_fusion.py` | VLM 语义分组 |
| **第三层：渲染** | `renderers/patch.py` | dialog 模式 |
| | `renderers/area_loading.py` | area_loading 模式 |
| | `renderers/content_duplicate.py` | content_duplicate 模式 |
| | `renderers/text_overlay.py` | text_overlay 模式 |
| **第四层：注入决策（新增）** | `injection/sequence_analyzer.py` | 操作序列分析 |
| | `injection/anomaly_recommender.py` | 异常推荐 |
| | `injection/sequence_rewriter.py` | 序列改写 |
| **第五层：元数据** | `generators/meta.py` | meta.json 生成 |
| **第六层：工具库** | `utils/...` | 公共函数 |

#### 3.4.2 新增「第四层：注入决策层」章节

```markdown
## 4. 第四层：注入决策层（injection/）

### sequence_analyzer.py — 操作序列语义分析器
- 职责：增量式分析用户操作序列，提取语义特征
- 核心接口：`SequenceAnalyzer.analyze(operations: list) -> SemanticContext`
- 与上下游关系：被 `injection_pipeline.py` 调用

### anomaly_recommender.py — 异常推荐器
- 职责：基于语义上下文推荐适合的异常类型和注入点
- 核心接口：`AnomalyRecommender.recommend(context: SemanticContext) -> list[Recommendation]`

### sequence_rewriter.py — 序列改写器
- 职责：将异常推荐转化为修改后的操作序列
- 核心接口：`SequenceRewriter.rewrite(sequence: list, recommendations: list) -> list`
```

#### 3.4.3 更新所有模块路径引用

- `omni_extractor.py` → `analysis/omni_extractor.py`
- `omni_vlm_fusion.py` → `analysis/omni_vlm_fusion.py`
- `patch_renderer.py` → `renderers/patch.py`
- `area_loading_renderer.py` → `renderers/area_loading.py`
- `content_duplicate_renderer.py` → `renderers/content_duplicate.py`
- `text_overlay_renderer.py` → `renderers/text_overlay.py`
- `generate_meta.py` → `generators/meta.py`
- `generate_filename_descriptions.py` → `generators/filename_descriptions.py`

#### 3.4.4 新增架构关系图

```
┌─────────────────────────────────────────────────────────────┐
│                      run_pipeline.py                        │
│                        (主控层)                              │
└──────────────────┬──────────────────┬───────────────────────┘
                   │                  │
        ┌──────────▼──────────┐ ┌─────▼─────┐
        │     analysis/       │ │ injection/│
        │ (Stage 1+2 感知)     │ │ (决策层) │
        └──────────┬──────────┘ └─────┬─────┘
                   │                  │
        ┌──────────▼──────────────────▼───────┐
        │              renderers/              │
        │           (Stage 3 渲染)             │
        └──────────────────┬──────────────────┘
                           │
        ┌──────────────────▼──────────────────┐
        │               utils/                 │
        │            (工具库层)                │
        └─────────────────────────────────────┘
```

---

## 4. 实施步骤

1. 更新 `docs/plans/2026-03-06-code-manual.md`
   - 新增注入决策层章节
   - 更新架构层级表格
   - 更新模块路径引用
   - 新增架构关系图

2. 重写 `ui_semantic_patch/scripts/README.md`
   - 按子包组织模块说明
   - 快速命令置顶

3. 重写 `ui_semantic_patch/README.md`
   - 简化模块架构表格
   - 引用 code-manual.md

4. 重写根目录 `README.md`
   - 核心能力表格
   - 3 步快速开始
   - 精简项目结构

5. 同步更新 docs/ 子目录 README.md
   - 更新文档索引链接

---

## 5. 验收标准

- [ ] 所有 README.md 反映最新的模块结构（renderers/、analysis/、generators/、injection/）
- [ ] code-manual.md 包含完整的注入决策层文档
- [ ] 文档间交叉引用正确无断链
- [ ] 快速开始示例可正常运行

---

*设计批准日期：2026-03-09*

---

**文档同步**: 2026-03-26 — 文档体系与运行示例以仓库根目录 [Claude.md](../../Claude.md) 为权威交叉引用。
