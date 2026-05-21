# UI 语义补丁框架

`ui_semantic_patch/` 是仓库的核心实现目录。它不再承担“项目总览”角色，只回答三类问题：

1. 核心代码放在哪里
2. 主要脚本怎么跑
3. 这个子目录里的 legacy 与主链路分别是什么

系统级架构、UTG 决策和 mapping 机制见仓库根目录：

- [../docs/architecture.md](../docs/architecture.md)
- [../docs/utg-architecture.md](../docs/utg-architecture.md)
- [../docs/mapping-generation.md](../docs/mapping-generation.md)

## 入口脚本

推荐入口都在 `scripts/`：

- `run_pipeline.py`
  - 单图异常生成
- `injection_pipeline.py`
  - 视觉序列分析 + 注入 + 序列改写
- `batch_utg_injection.py`
  - 基于 `utg_info.json` 和 `tmp/mapping.json` 的批量注入
- `web_ui/server.py`
  - 本地 Web UI

仍保留但已不是主链路：

- `batch_injection_with_mapping.py`
- `batch_pipeline.py`
- `batch_injection.py`
- `start.sh`

## 目录职责

### `app/core/`

- `config.py`
  - 统一路径和环境配置
- `schemas.py`
  - Stage 输出、渲染结果、编辑操作等数据结构

### `app/stages/`

- `omni_extractor.py`
  - Stage 1，OmniParser 粗检测
- `omni_vlm_fusion.py`
  - Stage 2，VLM 语义分组
- `gt_bounds.py`
  - GT 边界框处理
- `visualize.py`
  - 可视化工具

### `app/renderers/`

- `patch.py`
  - `dialog`
- `area_loading.py`
  - `area_loading`
- `content_duplicate.py`
  - `content_duplicate`
- `text_overlay.py`
  - `text_overlay`、`modify_text*`
- `image_broken.py`
  - `image_broken`

### `app/injection/`

- `page_classifier.py`
  - 页面分类
- `rule_engine.py`
  - 规则匹配
- `sequence_analyzer.py`
  - 视觉序列注入点决策
- `sequence_rewriter.py`
  - 序列改写
- `utg_loader.py`
  - 读取 `utg_info.json`
- `utg_decision.py`
  - 文本 LLM 决策
- `quality_verifier.py`
  - 生成后质量验证

### `config/`

- `query_anomaly_mapping.json`
  - 旧 query 映射配置
- `mapping_*.json`
  - 按异常模式拆分的维护产物

## 模式边界

`run_pipeline.py` 当前支持：

- `dialog`
- `area_loading`
- `content_duplicate`
- `text_overlay`
- `modify_text`
- `modify_text_ai`
- `modify_text_ocr`
- `modify_text_e2e`
- `image_broken`

补充：

- `response_delay` 是序列层异常，不走单图渲染器。
- `dialog` 最依赖 GT 模板。

## 常用命令

### 环境准备

在仓库根目录准备 `.env`，再安装依赖：

```bash
pip install -r ui_semantic_patch/requirements.txt
pip install -r ui_semantic_patch/third_party/OmniParser/requirements.txt
```

最重要的环境变量：

- `VLM_API_KEY`
- `VLM_API_URL`
- `VLM_MODEL`

图像生成相关配置按后端选择：

- `IMAGE_GEN_BACKEND`
- `IMAGE_GEN_API_KEY`
- `IMAGE_GEN_API_URL`
- `IMAGE_GEN_MODEL`

### 单图异常生成

```bash
cd ui_semantic_patch/scripts

python run_pipeline.py \
  --screenshot ../../data/gt-category/dialog/京东到家-外卖页面-优惠券弹窗.jpg \
  --instruction "生成优惠券广告弹窗" \
  --anomaly-mode dialog \
  --output ../../outputs/demo_single
```

### 文字修改

```bash
python run_pipeline.py \
  --screenshot ../../data/gt-category/dialog/铁路12306-首页-通知权限弹窗.jpg \
  --instruction "将按钮文案改为灰色不可点击状态" \
  --anomaly-mode modify_text_ocr \
  --output ../../outputs/demo_text
```

### 视觉序列注入

```bash
python injection_pipeline.py \
  --input-dir ../../data/examples/injection_demo_01 \
  --output-dir ../../outputs/injected_demo \
  --no-interactive
```

### UTG 批量注入

```bash
python batch_utg_injection.py \
  --examples-dir ../../data/examples \
  --mapping-config ../../tmp/mapping.json \
  --output-dir ../../outputs/utg_batch
```

### Web UI

```bash
cd ui_semantic_patch/scripts/web_ui
python server.py
```

默认地址：

- `http://localhost:8767`

## 维护提醒

1. `scripts/start.sh` 只是旧批量流程的快捷封装，不是文档主入口。
2. `config/query_anomaly_mapping.json` 和 `tmp/mapping.json` 面向不同链路，维护时不要混用。
3. 输出文件约定、序列语义和系统边界不要在这里重复维护，统一以下沉文档为准：
   - [../docs/architecture.md](../docs/architecture.md)
   - [../docs/utg-architecture.md](../docs/utg-architecture.md)
   - [../docs/mapping-generation.md](../docs/mapping-generation.md)
