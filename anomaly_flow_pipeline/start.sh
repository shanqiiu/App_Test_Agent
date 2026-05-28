#!/usr/bin/env bash

# anomaly_flow_pipeline 一键启动脚本
#
# 参数说明:
#   --utg                 utg_info.json 路径
#   --scenario            单个异常场景描述
#   --scenarios           多个异常场景 JSON 数组字符串，例如 '["异常1", "异常2"]'
#   --template            Flow 模板 JSON 路径
#   --output-dir          输出目录
#   --no-preprocess       跳过 UTG 预处理
#   --no-neighbor-adjust  跳过相邻步骤微调
#   --no-validation       跳过质量验证
#   --model               指定 VLM 模型名
#   --verbose / -v        输出详细日志

python ./scripts/run_pipeline.py \
    --utg ./example_data/utg_info.json \
    --scenario "搜索结果页加载失败，显示网络错误提示" \
    --template ./example_data/shopping-flow-search-and-buy_new.json \
    --output-dir ./outputs/demo
