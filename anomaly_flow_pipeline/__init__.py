"""
anomaly_flow_pipeline — 独立异常注入与 Flow 模板转换工具链

基于 utg.json 的操作序列 + LLM 决策：
1. 注入异常（改写 ui_summary）
2. 合并到 Flow 模板（mainFlow.steps）
3. 从 utg.json 数据中抽取页面类型 Spec

使用方式：
    from anomaly_flow_pipeline.core.utg_anomaly_injector import UTGAnomalyInjector
    from anomaly_flow_pipeline.core.flow_converter import FlowConverter
"""
