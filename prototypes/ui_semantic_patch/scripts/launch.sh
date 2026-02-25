#!/bin/bash
# launch.sh - UI 异常场景生成一键启动脚本
#
# 用法:
#   bash launch.sh                    # 交互式选择模式
#   bash launch.sh single             # 单图模式（使用下方默认配置）
#   bash launch.sh batch              # 批量模式（dry-run 预览）
#   bash launch.sh batch --run        # 批量模式（实际执行）
#   bash launch.sh list               # 列出所有异常类别

set -e

# ============================================================
# 路径配置（相对于本脚本所在目录）
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
DATA_DIR="$SCRIPT_DIR/../data"
GT_DIR="$DATA_DIR/Agent执行遇到的典型异常UI类型/analysis/gt_templates"
ORIG_DIR="$DATA_DIR/原图"

# ============================================================
# 默认参数（按需修改）
# ============================================================

# --- 单图模式默认值 ---
SCREENSHOT="$ORIG_DIR/app首页类-开屏广告弹窗/携程旅行01.jpg"
INSTRUCTION="生成优惠券广告弹窗"
ANOMALY_MODE="dialog"
GT_CATEGORY="弹窗覆盖原UI"
GT_SAMPLE="弹出广告.jpg"
OUTPUT_DIR="$SCRIPT_DIR/output/生成优惠券广告弹窗"

# --- 批量模式默认值 ---
BATCH_INPUT_DIR="$ORIG_DIR/app首页类-开屏广告弹窗"
BATCH_GT_CATEGORY="弹窗覆盖原UI"
BATCH_OUTPUT_DIR="$SCRIPT_DIR/batch_output"
BATCH_PATTERN="*.jpg"

# ============================================================
# 预置场景（快速切换）
# ============================================================
# 取消注释下方某组配置即可切换场景

# --- 场景 A: 弹窗广告 (dialog) ---
# SCREENSHOT="$ORIG_DIR/app首页类-开屏广告弹窗/携程旅行01.jpg"
# INSTRUCTION="生成优惠券广告弹窗"
# ANOMALY_MODE="dialog"
# GT_CATEGORY="弹窗覆盖原UI"
# GT_SAMPLE="弹出广告.jpg"
# OUTPUT_DIR="$SCRIPT_DIR/output/demo_dialog"

# --- 场景 B: 关闭按钮干扰 (dialog) ---
# SCREENSHOT="$ORIG_DIR/个人主页类-控件点击弹窗/抖音原图01.jpg"
# INSTRUCTION="生成权限请求弹窗"
# ANOMALY_MODE="dialog"
# GT_CATEGORY="弹窗覆盖原UI"
# GT_SAMPLE="关闭按钮干扰.jpg"
# OUTPUT_DIR="$SCRIPT_DIR/output/demo_close_button"

# --- 场景 C: 内容重复 (content_duplicate) ---
# SCREENSHOT="$ORIG_DIR/影视剧集类-内容歧义、重复/腾讯视频.jpg"
# INSTRUCTION="模拟底部信息重复显示"
# ANOMALY_MODE="content_duplicate"
# GT_CATEGORY="内容歧义、重复"
# GT_SAMPLE="部分信息重复.jpg"
# OUTPUT_DIR="$SCRIPT_DIR/output/demo_duplicate"

# --- 场景 D: 加载超时 (area_loading) ---
# SCREENSHOT="$ORIG_DIR/影视剧集类-内容歧义、重复/腾讯视频.jpg"
# INSTRUCTION="模拟列表加载超时"
# ANOMALY_MODE="area_loading"
# GT_CATEGORY=""
# GT_SAMPLE=""
# OUTPUT_DIR="$SCRIPT_DIR/output/demo_loading"

# --- 场景 E: 普通弹窗（无Meta回退） ---
# SCREENSHOT="$ORIG_DIR/app首页类-开屏广告弹窗/携程旅行02.jpg"
# INSTRUCTION="模拟网络超时弹窗"
# ANOMALY_MODE="dialog"
# GT_CATEGORY=""
# GT_SAMPLE=""
# OUTPUT_DIR="$SCRIPT_DIR/output/demo_simple"

# ============================================================
# 环境检查
# ============================================================
check_env() {
    echo "============================================================"
    echo "环境检查"
    echo "============================================================"

    # 加载 .env
    if [ -f "$PROJECT_ROOT/.env" ]; then
        set -a
        source "$PROJECT_ROOT/.env"
        set +a
        echo "  [OK] 已加载 .env: $PROJECT_ROOT/.env"
    else
        echo "  [WARN] 未找到 .env 文件: $PROJECT_ROOT/.env"
        echo "         请复制 .env.example 并填入 API Key:"
        echo "         cp $PROJECT_ROOT/.env.example $PROJECT_ROOT/.env"
    fi

    # 检查 API Key
    if [ -z "$VLM_API_KEY" ]; then
        echo "  [ERROR] VLM_API_KEY 未设置，请在 .env 中配置"
        exit 1
    else
        echo "  [OK] VLM_API_KEY 已设置 (${VLM_API_KEY:0:8}...)"
    fi

    # 检查 Python
    if command -v python &> /dev/null; then
        echo "  [OK] Python: $(python --version 2>&1)"
    else
        echo "  [ERROR] Python 未找到"
        exit 1
    fi

    # 检查数据目录
    if [ -d "$ORIG_DIR" ]; then
        local count=$(find "$ORIG_DIR" -name "*.jpg" -o -name "*.png" | wc -l)
        echo "  [OK] 原图目录: $ORIG_DIR ($count 张)"
    else
        echo "  [ERROR] 原图目录不存在: $ORIG_DIR"
        exit 1
    fi

    if [ -d "$GT_DIR" ]; then
        echo "  [OK] GT模板目录: $GT_DIR"
    else
        echo "  [ERROR] GT模板目录不存在: $GT_DIR"
        exit 1
    fi

    echo ""
}

# ============================================================
# 单图模式
# ============================================================
run_single() {
    echo "============================================================"
    echo "单图异常生成"
    echo "============================================================"
    echo "  截图:       $SCREENSHOT"
    echo "  指令:       $INSTRUCTION"
    echo "  异常模式:   $ANOMALY_MODE"
    echo "  GT类别:     ${GT_CATEGORY:-（未指定，使用普通模式）}"
    echo "  GT样本:     ${GT_SAMPLE:-（未指定）}"
    echo "  输出目录:   $OUTPUT_DIR"
    echo "============================================================"
    echo ""

    # 检查截图文件
    if [ ! -f "$SCREENSHOT" ]; then
        echo "[ERROR] 截图文件不存在: $SCREENSHOT"
        exit 1
    fi

    # 构建命令
    CMD="python \"$SCRIPT_DIR/run_pipeline.py\""
    CMD="$CMD --screenshot \"$SCREENSHOT\""
    CMD="$CMD --instruction \"$INSTRUCTION\""
    CMD="$CMD --anomaly-mode $ANOMALY_MODE"
    CMD="$CMD --output \"$OUTPUT_DIR\""

    if [ -n "$GT_CATEGORY" ] && [ -n "$GT_SAMPLE" ]; then
        CMD="$CMD --gt-category \"$GT_CATEGORY\""
        CMD="$CMD --gt-sample \"$GT_SAMPLE\""
        CMD="$CMD --gt-dir \"$GT_DIR\""
    fi

    echo "[CMD] $CMD"
    echo ""
    eval $CMD
}

# ============================================================
# 批量模式
# ============================================================
run_batch() {
    local extra_args="$*"

    echo "============================================================"
    echo "批量异常生成"
    echo "============================================================"
    echo "  原图目录:   $BATCH_INPUT_DIR"
    echo "  GT类别:     $BATCH_GT_CATEGORY"
    echo "  文件匹配:   $BATCH_PATTERN"
    echo "  输出目录:   $BATCH_OUTPUT_DIR"
    echo "  额外参数:   ${extra_args:-（无）}"
    echo "============================================================"
    echo ""

    CMD="python \"$SCRIPT_DIR/batch_pipeline.py\""
    CMD="$CMD --input-dir \"$BATCH_INPUT_DIR\""
    CMD="$CMD --gt-category \"$BATCH_GT_CATEGORY\""
    CMD="$CMD --pattern \"$BATCH_PATTERN\""
    CMD="$CMD --output \"$BATCH_OUTPUT_DIR\""
    CMD="$CMD $extra_args"

    echo "[CMD] $CMD"
    echo ""
    eval $CMD
}

# ============================================================
# 列出类别
# ============================================================
run_list() {
    python "$SCRIPT_DIR/batch_pipeline.py" --list-categories --gt-dir "$GT_DIR"
}

# ============================================================
# 交互式菜单
# ============================================================
run_interactive() {
    echo ""
    echo "============================================================"
    echo "  UI 异常场景生成 - 一键启动"
    echo "============================================================"
    echo ""
    echo "  可用原图:"
    echo "    [1] app首页类-开屏广告弹窗/  (携程旅行01, 携程旅行02)"
    echo "    [2] 个人主页类-控件点击弹窗/  (抖音原图01, 抖音原图02)"
    echo "    [3] 影视剧集类-内容歧义、重复/ (腾讯视频)"
    echo ""
    echo "  可用异常类别:"
    echo "    [A] 弹窗覆盖原UI       (7个样本, dialog 模式)"
    echo "    [B] 内容歧义、重复      (1个样本, content_duplicate 模式)"
    echo "    [C] loading_timeout    (1个样本, area_loading 模式)"
    echo ""
    echo "  请选择运行模式:"
    echo "    1) 单图 - 弹窗广告 (携程旅行01 × 弹出广告)"
    echo "    2) 单图 - 关闭按钮干扰 (抖音原图01 × 关闭按钮干扰)"
    echo "    3) 单图 - 内容重复 (腾讯视频 × 部分信息重复)"
    echo "    4) 单图 - 加载超时 (腾讯视频)"
    echo "    5) 批量 - 预览计划 (dry-run)"
    echo "    6) 批量 - 实际执行"
    echo "    7) 列出所有异常类别"
    echo "    q) 退出"
    echo ""
    read -p "  请输入选项 [1-7/q]: " choice

    case $choice in
        1)
            SCREENSHOT="$ORIG_DIR/app首页类-开屏广告弹窗/携程旅行01.jpg"
            INSTRUCTION="生成优惠券广告弹窗"
            ANOMALY_MODE="dialog"
            GT_CATEGORY="弹窗覆盖原UI"
            GT_SAMPLE="弹出广告.jpg"
            OUTPUT_DIR="$SCRIPT_DIR/output/demo_dialog"
            run_single
            ;;
        2)
            SCREENSHOT="$ORIG_DIR/个人主页类-控件点击弹窗/抖音原图01.jpg"
            INSTRUCTION="生成权限请求弹窗"
            ANOMALY_MODE="dialog"
            GT_CATEGORY="弹窗覆盖原UI"
            GT_SAMPLE="关闭按钮干扰.jpg"
            OUTPUT_DIR="$SCRIPT_DIR/output/demo_close_button"
            run_single
            ;;
        3)
            SCREENSHOT="$ORIG_DIR/影视剧集类-内容歧义、重复/腾讯视频.jpg"
            INSTRUCTION="模拟底部信息重复显示"
            ANOMALY_MODE="content_duplicate"
            GT_CATEGORY="内容歧义、重复"
            GT_SAMPLE="部分信息重复.jpg"
            OUTPUT_DIR="$SCRIPT_DIR/output/demo_duplicate"
            run_single
            ;;
        4)
            SCREENSHOT="$ORIG_DIR/影视剧集类-内容歧义、重复/腾讯视频.jpg"
            INSTRUCTION="模拟列表加载超时"
            ANOMALY_MODE="area_loading"
            GT_CATEGORY=""
            GT_SAMPLE=""
            OUTPUT_DIR="$SCRIPT_DIR/output/demo_loading"
            run_single
            ;;
        5)
            run_batch
            ;;
        6)
            run_batch --run
            ;;
        7)
            run_list
            ;;
        q|Q)
            echo "退出"
            exit 0
            ;;
        *)
            echo "[ERROR] 无效选项: $choice"
            exit 1
            ;;
    esac
}

# ============================================================
# 主入口
# ============================================================
cd "$SCRIPT_DIR"
check_env

case "${1:-}" in
    single)
        run_single
        ;;
    batch)
        shift
        run_batch "$@"
        ;;
    list)
        run_list
        ;;
    "")
        run_interactive
        ;;
    *)
        echo "用法: bash launch.sh [single|batch|list]"
        echo ""
        echo "  single          单图模式（使用脚本内默认配置）"
        echo "  batch            批量模式（默认 dry-run）"
        echo "  batch --run      批量模式（实际执行）"
        echo "  list             列出所有异常类别"
        echo "  （无参数）        交互式菜单"
        exit 1
        ;;
esac
