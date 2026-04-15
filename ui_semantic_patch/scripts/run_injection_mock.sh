#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

INPUT_DIR="${1:-$PROJECT_ROOT/ui_semantic_patch/examples/injection_demo}"
OUTPUT_DIR="${2:-$PROJECT_ROOT/output/injected_mock}"

python3 "$SCRIPT_DIR/injection_pipeline.py" \
  --input-dir "$INPUT_DIR" \
  --output-dir "$OUTPUT_DIR" \
  --mock \
  --no-interactive
