# OmniParser 端到端运行解析报告

- 检查时间: 2026-04-18 (UTC)
- 项目路径: `/root/workspace/App_Test_Agent/prototypes/ui_semantic_patch/third_party/OmniParser`
- conda 环境: `omn`
- GPU: `NVIDIA L20` (`torch.cuda.is_available() == True`)

## 1. 结论摘要

`omni_inference.py` 已在当前 Linux + GPU + `omn` 环境跑通，命令如下：

```bash
conda run -n omn python omni_inference.py --image 05.jpg --output results --device cuda
```

本次产物：

- `results/05_result.json`
- `results/05_annotated.png`

运行摘要（成功）：

- 检测元素: 68
- 文本框: 2
- 图标框: 66

## 2. 初始失败与根因定位

### 2.1 首次失败：YOLO 权重与 Ultralytics 版本不兼容

初始报错：

- `AttributeError: Can't get attribute 'C3k2' on ultralytics.nn.modules.block`

对应代码位置：

- 权重加载入口：`util/utils.py:81`
- 调用处：`omni_inference.py:84`

根因：

- 当前 `requirements.txt` 固定为 `ultralytics==8.2.10`（`requirements.txt`）
- 但 `weights/icon_detect/model.pt` 内部包含 `C3k2` / `C2PSA` / `yolo11m.yaml`（从权重字符串可见），属于较新 YOLO11 结构，不兼容 8.2.10

### 2.2 第二次失败：Florence2 依赖缺失

在修复 Ultralytics 后，报错转为：

- `ImportError: ... packages were not found ... flash_attn, einops`

对应代码位置：

- Caption 模型加载：`util/utils.py:55-77`
- 入口调用：`omni_inference.py:88`

根因：

- `einops` 未安装
- `weights/icon_caption_florence/modeling_florence2.py` 使用了 `flash_attn` 导入语句，`transformers` 动态模块检查时会把它识别为硬依赖

## 3. 本次已执行修复

### 3.1 环境依赖修复（在 `omn` 中）

执行：

```bash
conda run -n omn pip install "transformers==4.38.2" "ultralytics>=8.3.0,<8.4"
conda run -n omn pip install einops
```

修复后关键版本：

- `torch 2.2.0+cu121`
- `ultralytics 8.3.253`
- `transformers 4.38.2`
- `einops 0.8.2`

### 3.2 代码兼容补丁

修改文件：`weights/icon_caption_florence/modeling_florence2.py`

修改点：

- `weights/icon_caption_florence/modeling_florence2.py:63-73`
- `weights/icon_caption_florence/modeling_florence2.py:675-689`

说明：

- 将 `flash_attn` 的静态 `from ... import ...` 改为运行时动态导入（`importlib.import_module`）+ `try/except`
- 目的：在 `attn_implementation="eager"` 路径下，不因 `flash_attn` 缺失而被 `transformers` 动态检查提前拦截

## 4. 模型位置核验

### 4.1 `omni_inference.py` 默认模型路径

- YOLO: `weights/icon_detect/model.pt`（见 `omni_inference.py:61`）
- Caption: `weights/icon_caption_florence`（见 `omni_inference.py:62`）

路径通过 `_resolve_path` 解析到项目根目录（`omni_inference.py:96-101`）。

### 4.2 本地模型文件是否在位

- YOLO 权重在位：`weights/icon_detect/model.pt`（约 39MB）
- Florence 权重目录在位：`weights/icon_caption_florence/`
- Florence 核心文件齐全（`OFFLINE_DEPLOYMENT.md` 列出的 10 个文件均存在）

### 4.3 OCR 模型缓存状态

本机 OCR 缓存存在：

- EasyOCR: `/root/.EasyOCR/model/craft_mlt_25k.pth`, `/root/.EasyOCR/model/english_g2.pth`
- PaddleOCR: `/root/.paddleocr/whl/{det,rec,cls}/...`

结论：模型/权重位置本身没有缺失，主要问题是“依赖版本与导入策略”。

## 5. 当前代码层面的已知问题（建议后续修）

1. `--no-semantics` 仍会加载 caption 模型
- 位置：`omni_inference.py:87-92`
- 影响：即使禁用语义，也会触发 `transformers` 与大模型加载，增加失败面与初始化成本

2. `iou_threshold` 传参未用于 YOLO 推理
- 位置：`util/utils.py:431`
- 问题：调用 `predict_yolo(..., iou_threshold=0.1)` 写死，忽略上层传入值

3. `parsed_content_icon` 被 `pop` 后再次遍历
- 位置：`util/utils.py:467-472`
- 问题：先 `pop(0)` 填充 `filtered_boxes_elem`，后续再遍历 `parsed_content_icon` 基本为空；`parsed_content_merged` 的 icon 文本构造逻辑不完整

4. OCR 引擎在模块导入时即初始化
- 位置：`util/utils.py:24-25`
- 影响：导入副作用重，离线/首次环境更容易在 import 阶段失败

5. `requirements.txt` 中 `ultralytics==8.2.10` 与当前 YOLO 权重不匹配
- 建议改为与 YOLO11 权重一致的版本区间

## 6. 复现与验收建议

建议最小验收命令：

```bash
conda run -n omn python omni_inference.py --image 05.jpg --output results --device cuda
```

如果需要离线稳定部署，建议同时设置：

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
```

并保留完整 `weights/icon_caption_florence` 目录。
