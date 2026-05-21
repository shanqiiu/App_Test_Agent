#!/usr/bin/env bash
# ============================================================
# UI 异常场景生成 - 单例快速启动
# 基于 batch_injection_with_mapping.py 的映射配置参数
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# python "$SCRIPT_DIR/run_pipeline.py" \
#   --screenshot "$PROJECT_ROOT/data/examples/injection_demo_01/screenshots/09.jpg" \
#   --instruction "模拟查询结果无票的系统提示弹窗" \
#   --anomaly-mode dialog \
#   --gt-category dialog \
#   --gt-sample 携程旅行-首页-推广弹窗.jpg \
#   --output "$SCRIPT_DIR/outputs/injection_demo_01_mode_2"

python "$SCRIPT_DIR/batch_injection_with_mapping.py" \
  --examples-dir "$PROJECT_ROOT/data/examples" \
  --output-dir "$SCRIPT_DIR/outputs3" \
  --mapping-config "$SCRIPT_DIR/../config/query_anomaly_mapping.json" \
  --gt-template-dir "$PROJECT_ROOT/data/gt-category"

# ============================================================
# UTG 批量异常注入（文本 LLM 决策，推荐）
# 基于 utg_info.json + mapping.json，无需逐帧 VLM 图像分析
# ============================================================

# 完整批量生成（需 mapping.json）
python "$SCRIPT_DIR/batch_utg_injection.py" \
  --examples-dir "$PROJECT_ROOT/data/examples" \
  --mapping-config "$PROJECT_ROOT/tmp/mapping.json" \
  --output-dir "$PROJECT_ROOT/outputs/utg_batch" \
  --gt-template-dir "$PROJECT_ROOT/data/gt-category"

# 自由模式批量生成（无 mapping，LLM 自动决策异常类型和 instruction）
python "$SCRIPT_DIR/batch_utg_injection.py" \
  --examples-dir "$PROJECT_ROOT/data/examples" \
  --output-dir "$PROJECT_ROOT/outputs/utg_batch" \
  --gt-template-dir "$PROJECT_ROOT/data/gt-category"

# Dry-run（仅 LLM 打分预览，不生成图片）
python "$SCRIPT_DIR/batch_utg_injection.py" \
  --examples-dir "$PROJECT_ROOT/data/examples" \
  --dry-run

# 手动指定注入点 + 单 UUID 调试
python "$SCRIPT_DIR/batch_utg_injection.py" \
  --examples-dir "$PROJECT_ROOT/data/examples" \
  --uuid 14a37b63 --injection-point 5