#!/usr/bin/env bash
# ============================================================
# UI 异常场景生成 - 单例快速启动
# 基于 batch_injection_with_mapping.py 的映射配置参数
# ============================================================


# 注入异常
python ./scripts/run_inject.py \
    --utg /data/App_Test_Agent/data/examples/1b1956ef-cf65-45f2-987c-b10f326923ca/utg_info.json \
    --scenario "将百亿补贴按钮的背景色修改为灰色，模拟按钮不可用状态" \
    --output ./outputs/anomaly_injected/utg_info.json

# 合并到 Flow 模板
python ./scripts/run_convert.py \
    --utg  ./outputs/anomaly_injected/utg_info.json \
    --template ./data/config/shopping-flow-search-and-buy.json \
    --output ./outputs/anomaly_injected/shopping-flow-search-and-buy_case.json

