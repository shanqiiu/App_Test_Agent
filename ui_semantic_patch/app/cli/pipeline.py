#!/usr/bin/env python3
"""
app/cli/pipeline.py - 异常场景生成流水线 CLI

这是新的命令行入口点，通过调用 app/ 模块提供功能。
保留原有 scripts/ 目录作为向后兼容。

新结构：
    app/
        stages/      - Stage 1/2 AI感知层
        renderers/   - Stage 3 异常渲染层
        injection/   - 注入决策层
        generators/  - 元数据生成层
        utils/       - 工具库
        cli/         - 命令行接口（这个文件）
    scripts/         - 保留，作为向后兼容

使用方式：
    # 新方式（推荐）
    python -m app.cli.pipeline --screenshot ... --instruction ...

    # 兼容方式（仍可用）
    python scripts/run_pipeline.py ...
"""

import sys
import os
from pathlib import Path

# 确保项目根目录在 Python 路径中（使用集中配置）
from app.core.config import config, init_app_paths

# 初始化路径
init_app_paths()

# 代理到 scripts/run_pipeline.py（保持向后兼容）
from scripts.run_pipeline import main as run_pipeline_main

if __name__ == "__main__":
    # 重新设置 argv 以支持 python -m app.cli.pipeline 调用
    sys.argv[0] = "app.cli.pipeline"
    run_pipeline_main()
