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
#   --gt-sample 华为花粉俱乐部-首页-勋章奖励弹窗.jpg \
#   --output "$SCRIPT_DIR/outputs/injection_demo_01_mode_2"

python "$SCRIPT_DIR/batch_injection_with_mapping.py" \
  --examples-dir "$PROJECT_ROOT/data/examples" \
  --output-dir "$SCRIPT_DIR/outputs" \
  --mapping-config "$SCRIPT_DIR/../config/query_anomaly_mapping.json" \
  --gt-template-dir "$PROJECT_ROOT/data/gt-category"