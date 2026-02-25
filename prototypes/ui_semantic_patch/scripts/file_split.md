**原图地址：**
D:\my_git_projects\App_Test_Agent\prototypes\ui_semantic_patch\data\原图

**异常类型参考基准图片地址：**
D:\my_git_projects\App_Test_Agent\prototypes\ui_semantic_patch\data\Agent执行遇到的典型异常UI类型\analysis\gt_templates

---

## 目录结构

```
prototypes/ui_semantic_patch/
├── data/
│   ├── 原图/                                    # 待注入异常的原始截图
│   │   ├── app首页类-开屏广告弹窗/
│   │   ├── 个人主页类-控件点击弹窗/
│   │   └── 影视剧集类-内容歧义、重复/
│   └── Agent执行遇到的典型异常UI类型/
│       └── analysis/gt_templates/               # GT模板（异常参考样本）
│           ├── 弹窗覆盖原UI/        (7个样本)    # category=dialog_blocking
│           │   ├── meta.json
│           │   ├── 弹出广告.jpg
│           │   ├── 弹出提示.jpg
│           │   ├── 关闭按钮干扰.jpg
│           │   └── ...
│           ├── 内容歧义、重复/       (1个样本)    # category=content_duplicate
│           │   ├── meta.json
│           │   └── 部分信息重复.jpg
│           └── loading_timeout/     (1个样本)    # category=loading_timeout
│               ├── meta.json
│               └── 白屏无内容.jpg
└── scripts/
    ├── run_pipeline.py              # 单张图片异常生成（核心流水线）
    ├── batch_pipeline.py            # 批量异常生成（封装 run_pipeline）
    └── utils/
        ├── meta_loader.py           # GT模板 meta.json 加载器
        ├── semantic_dialog_generator.py
        ├── component_position_resolver.py
        └── ...
```

---

## 流水线架构

### run_pipeline.py — 单图处理流水线（3阶段）

```
输入: 原始截图 + 异常指令 + (可选)GT模板
         │
         ▼
┌─────────────────────────────────┐
│ Stage 1: OmniParser 粗检测       │  YOLO + PaddleOCR + Florence2
│   输出: stage1_omni_raw_*.json  │  检测所有 UI 组件
│   输出: stage1_annotated_*.png  │  可视化标注图
└──────────┬──────────────────────┘
           ▼
┌─────────────────────────────────┐
│ Stage 2: VLM 语义过滤            │  qwen-vl-max (默认)
│   输出: stage2_filtered_*.json  │  合并海报/卡片内文字，清理噪声
│   输出: stage2_annotated_*.png  │  过滤后可视化
└──────────┬──────────────────────┘
           ▼
┌─────────────────────────────────┐
│ Stage 3: 异常渲染（三种模式）     │
│   dialog         → 全屏弹窗覆盖  │  DashScope AI 图像生成
│   area_loading   → 区域加载图标  │  Pillow 图标叠加
│   content_duplicate → 内容重复   │  组件复制+浮层
│   输出: *_final_*.png           │  最终异常截图
└─────────────────────────────────┘
```

### batch_pipeline.py — 批量封装

```
batch_pipeline.py
  │
  ├── 扫描原图目录 → 得到 N 张截图
  ├── 加载GT类别 → 得到 M 个样本
  ├── 生成 N × M 个任务
  └── 逐个调用 run_pipeline() → 输出到子目录
       └── 生成 batch_report.json 汇总报告
```

---

## 参数配置

### 环境变量（.env 文件，项目根目录）

| 变量 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `VLM_API_KEY` | **是** | — | VLM API 密钥（Stage 2 语义过滤 + Stage 3 弹窗生成） |
| `VLM_API_URL` | 否 | `https://api.openai-next.com/v1/chat/completions` | VLM API 端点 |
| `VLM_MODEL` | 否 | `gpt-4o` | VLM 模型名 |
| `STRUCTURE_MODEL` | 否 | `qwen-vl-max` | Stage 2 结构提取/语义过滤模型 |
| `DASHSCOPE_API_KEY` | 否 | — | DashScope API 密钥（dialog 模式 AI 图像生成） |
| `OMNIPARSER_DEVICE` | 否 | `auto` | OmniParser 运行设备（`cuda` / `cpu`） |

### run_pipeline.py 参数

| 参数 | 简写 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--screenshot` | `-s` | **是** | — | 原始截图路径 |
| `--instruction` | `-i` | **是** | — | 异常生成指令 |
| `--output` | `-o` | 否 | `./output` | 输出目录 |
| `--anomaly-mode` | — | 否 | `dialog` | 异常模式: `dialog` / `area_loading` / `content_duplicate` |
| `--gt-category` | — | 否 | — | GT类别名（启用 meta 驱动生成） |
| `--gt-sample` | — | 否 | — | GT样本文件名（与 `--gt-category` 配合） |
| `--gt-dir` | — | 否 | 自动检测 | GT模板根目录 |
| `--reference` | `-r` | 否 | — | 参考弹窗图片路径 |
| `--reference-icon` | — | 否 | — | 参考加载图标路径（area_loading 模式） |
| `--target-component` | — | 否 | — | 目标组件ID（area_loading 模式） |
| `--api-key` | — | 否 | `$VLM_API_KEY` | VLM API 密钥 |
| `--api-url` | — | 否 | `$VLM_API_URL` | VLM API 端点 |
| `--structure-model` | — | 否 | `$STRUCTURE_MODEL` | 语义过滤模型 |
| `--vlm-api-url` | — | 否 | `$VLM_API_URL` | 弹窗生成 VLM 端点 |
| `--vlm-model` | — | 否 | `$VLM_MODEL` | 弹窗生成 VLM 模型 |
| `--omni-device` | — | 否 | `auto` | OmniParser 设备 |
| `--no-visualize` | — | 否 | `false` | 禁用中间结果可视化 |
| `--fonts-dir` | — | 否 | 系统默认 | 自定义字体目录 |

### batch_pipeline.py 参数

| 参数 | 简写 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--input-dir` | `-i` | **是** | — | 原图目录 |
| `--gt-category` | `-c` | **是** | — | 异常类别名 |
| `--output` | `-o` | 否 | `./batch_output` | 输出根目录 |
| `--gt-dir` | — | 否 | 自动检测 | GT模板根目录 |
| `--pattern` | — | 否 | `*.jpg` | 文件匹配模式 |
| `--list-categories` | — | 否 | — | 列出所有异常类别 |
| `--dry-run` | — | 否 | — | 只打印计划 |
| `--run` | — | 否 | — | 实际执行（默认为 dry-run） |
| `--no-visualize` | — | 否 | — | 禁用可视化 |
| API 相关参数 | — | — | — | 同 run_pipeline.py |

---

## 运行示例

### 前置准备

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 VLM_API_KEY

# 2. 进入脚本目录
cd prototypes/ui_semantic_patch/scripts
```

### 示例 1：查看可用异常类别

```bash
python batch_pipeline.py --list-categories
```

输出示例：
```
可用异常类别 (3 个):
============================================================

  [弹窗覆盖原UI]
    描述: 各种弹窗、浮层遮挡原始UI的异常场景
    异常模式: dialog
    样本数: 7
      - 弹出广告.jpg
      - 弹出提示.jpg
      - 关闭按钮干扰.jpg
      ...

  [内容歧义、重复]
    描述: 界面内容重复显示的异常场景
    异常模式: content_duplicate
    样本数: 1
      - 部分信息重复.jpg

  [loading_timeout]
    描述: 加载超时/白屏异常
    异常模式: area_loading
    样本数: 1
      - 白屏无内容.jpg
```

### 示例 2：单图 — 弹窗异常（Meta驱动，推荐）

```bash
python run_pipeline.py \
  --screenshot "../data/原图/app首页类-开屏广告弹窗/某app首页.jpg" \
  --instruction "生成优惠券广告弹窗" \
  --gt-category "弹窗覆盖原UI" \
  --gt-sample "弹出广告.jpg" \
  --output ./output/demo_dialog
```

流程：Stage1 检测组件 → Stage2 语义过滤 → Stage3 从 meta.json 读取弹窗风格，VLM 生成语义文案，AI 渲染弹窗并合成。

### 示例 3：单图 — 区域加载异常

```bash
python run_pipeline.py \
  --screenshot "../data/原图/影视剧集类-内容歧义、重复/某视频页.jpg" \
  --instruction "模拟列表加载超时" \
  --anomaly-mode area_loading \
  --output ./output/demo_loading
```

### 示例 4：单图 — 内容重复异常

```bash
python run_pipeline.py \
  --screenshot "../data/原图/影视剧集类-内容歧义、重复/某视频页.jpg" \
  --instruction "模拟底部信息重复显示" \
  --anomaly-mode content_duplicate \
  --gt-category "内容歧义、重复" \
  --gt-sample "部分信息重复.jpg" \
  --output ./output/demo_duplicate
```

### 示例 5：单图 — 普通弹窗（无Meta，回退模式）

```bash
python run_pipeline.py \
  --screenshot "../data/原图/app首页类-开屏广告弹窗/某app首页.jpg" \
  --instruction "模拟网络超时弹窗" \
  --output ./output/demo_simple
```

不指定 `--gt-category`/`--gt-sample` 时，使用 PatchRenderer 的 `semantic_ai` 模式直接生成。

### 示例 6：批量 — 预览执行计划（dry-run）

```bash
python batch_pipeline.py \
  --input-dir "../data/原图/app首页类-开屏广告弹窗" \
  --gt-category "弹窗覆盖原UI" \
  --output ./batch_output
```

默认为 dry-run，输出任务计划但不执行。显示 `N张原图 × M个样本 = 总任务数`。

### 示例 7：批量 — 实际执行

```bash
python batch_pipeline.py \
  --input-dir "../data/原图/app首页类-开屏广告弹窗" \
  --gt-category "弹窗覆盖原UI" \
  --output ./batch_output \
  --run
```

对目录下每张原图 × "弹窗覆盖原UI" 下的 7 个 GT 样本，生成 7N 个异常截图。

### 示例 8：批量 — 过滤特定格式 + 禁用可视化

```bash
python batch_pipeline.py \
  --input-dir "../data/原图" \
  --gt-category "内容歧义、重复" \
  --pattern "*.png" \
  --no-visualize \
  --output ./batch_output \
  --run
```

---

## 输出目录结构

### run_pipeline.py 单次输出

```
output/demo_dialog/
├── 某app首页_stage1_omni_raw_20260210_143000.json     # Stage1 OmniParser检测
├── 某app首页_stage1_annotated_20260210_143000.png      # Stage1 可视化
├── 某app首页_stage2_filtered_20260210_143000.json      # Stage2 VLM过滤
├── 某app首页_stage2_annotated_20260210_143000.png      # Stage2 可视化
├── 某app首页_final_20260210_143000.png                 # ★ 最终异常截图
└── 某app首页_pipeline_meta_20260210_143000.json        # 流水线元数据
```

### batch_pipeline.py 批量输出

```
batch_output/
└── batch_弹窗覆盖原UI_20260210_143000/
    ├── 某app首页__弹出广告/          # 原图名__样本名
    │   ├── *_stage1_*.json
    │   ├── *_stage2_*.json
    │   ├── *_final_*.png            # ★ 最终异常截图
    │   └── *_pipeline_meta_*.json
    ├── 某app首页__弹出提示/
    │   └── ...
    ├── 某app首页__关闭按钮干扰/
    │   └── ...
    └── batch_report.json             # ★ 批量处理汇总报告
```

### batch_report.json 结构

```json
{
  "timestamp": "20260210_143000",
  "input_dir": "../data/原图/app首页类-开屏广告弹窗",
  "gt_category": "弹窗覆盖原UI",
  "anomaly_mode": "dialog",
  "total_tasks": 7,
  "success": 5,
  "failed": 2,
  "results": [
    {
      "screenshot": "...某app首页.jpg",
      "gt_sample": "弹出广告.jpg",
      "gt_category": "弹窗覆盖原UI",
      "instruction": "生成优惠券促销弹窗...",
      "anomaly_mode": "dialog",
      "status": "success",
      "final_image": "...某app首页_final_*.png"
    }
  ]
}
```

---

## anomaly_mode 与 GT 类别映射

| GT 类别 | meta.json category | 自动映射 anomaly_mode | Stage 3 渲染器 |
|---------|--------------------|-----------------------|----------------|
| 弹窗覆盖原UI | `dialog_blocking` | `dialog` | SemanticDialogGenerator / PatchRenderer |
| 内容歧义、重复 | `content_duplicate` | `content_duplicate` | ContentDuplicateRenderer |
| loading_timeout | `loading_timeout` | `area_loading` | AreaLoadingRenderer |

batch_pipeline.py 会从 meta.json 的 `category` 字段自动推断 `anomaly_mode`，无需手动指定。
