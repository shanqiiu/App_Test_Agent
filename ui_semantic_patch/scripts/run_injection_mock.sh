#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

MODE="${1:-mock}"  # mock | real
INPUT_DIR="${2:-$PROJECT_ROOT/ui_semantic_patch/examples/injection_demo}"
OUTPUT_DIR="${3:-$PROJECT_ROOT/output/injected_mock}"

if [[ "$MODE" != "mock" && "$MODE" != "real" ]]; then
  echo "用法: bash run_injection_mock.sh [mock|real] [input_dir] [output_dir]"
  echo "  mock: 跳过图像生成（默认）"
  echo "  real: 真实生成链路（调用 run_pipeline.py + 文生图模型）"
  exit 1
fi

echo "============================================================"
echo "Injection Pipeline Launcher"
echo "============================================================"
echo "模式:       $MODE"
echo "输入目录:   $INPUT_DIR"
echo "输出目录:   $OUTPUT_DIR"
echo "============================================================"

if [[ "$MODE" == "mock" ]]; then
  python3 "$SCRIPT_DIR/injection_pipeline.py" \
    --input-dir "$INPUT_DIR" \
    --output-dir "$OUTPUT_DIR" \
    --mock \
    --no-interactive
else
  python3 "$SCRIPT_DIR/injection_pipeline.py" \
    --input-dir "$INPUT_DIR" \
    --output-dir "$OUTPUT_DIR" \
    --no-interactive
fi
