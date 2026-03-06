# 实现计划：异常注入决策模块

**创建日期**: 2026-03-06
**状态**: ✅ 已完成
**设计文档**: [2026-03-06-anomaly-injection-decision-design.md](./2026-03-06-anomaly-injection-decision-design.md)

---

## 实现阶段

### Phase 1: 基础设施与工具函数 ✅

- [x] 1.1 `scripts/injection/__init__.py` - 模块初始化
- [x] 1.2 `scripts/injection/prompts.py` - VLM 提示词模板
- [x] 1.3 `scripts/utils/history_manager.py` - 历史记录管理器
- [x] 1.4 `examples/injection_demo/` - 示例输入数据

### Phase 2: 异常推荐器 ✅

- [x] 2.1 `scripts/injection/anomaly_recommender.py` - 主类
- [x] 2.2 集成 `utils/meta_loader.py`
- [x] 2.3 实现 `get_categories_description()`

### Phase 3: 增量式语义分析器 ✅

- [x] 3.1 `scripts/injection/sequence_analyzer.py` - 主类
- [x] 3.2 实现 `analyze_step()`
- [x] 3.3 实现 `_build_vlm_prompt()`
- [x] 3.4 实现 `_parse_vlm_response()`
- [x] 3.5 实现 `run()`

### Phase 4: 序列改写器 ✅

- [x] 4.1 `scripts/injection/sequence_rewriter.py` - 主类
- [x] 4.2 实现 `_call_generator()`
- [x] 4.3 实现 `rewrite()`
- [x] 4.4 保存 metadata 和 decision_log

### Phase 5: 主入口与交互 ✅

- [x] 5.1 `scripts/injection_pipeline.py` - 主入口
- [x] 5.2 实现参数解析
- [x] 5.3 实现用户确认流程
- [x] 5.4 实现完整流水线串联

### Phase 6: 测试与文档 ⏳

- [x] 6.1 示例数据目录结构已创建
- [ ] 6.2 端到端测试（需要实际截图数据）
- [ ] 6.3 更新 README

---

## 已创建文件清单

```
prototypes/ui_semantic_patch/
├── scripts/
│   ├── injection/
│   │   ├── __init__.py              ✅ 模块初始化
│   │   ├── prompts.py               ✅ VLM 提示词模板
│   │   ├── anomaly_recommender.py   ✅ 异常推荐器
│   │   ├── sequence_analyzer.py     ✅ 增量式语义分析器
│   │   └── sequence_rewriter.py     ✅ 序列改写器
│   ├── injection_pipeline.py        ✅ 主入口脚本
│   └── utils/
│       └── history_manager.py       ✅ 历史记录管理器
└── examples/
    └── injection_demo/
        └── task.json                ✅ 示例任务配置
```

---

## 使用方法

```bash
cd prototypes/ui_semantic_patch/scripts

# 交互式模式
python injection_pipeline.py \
  --input-dir examples/injection_demo \
  --output-dir output/injected

# 非交互式模式
python injection_pipeline.py \
  --input-dir examples/injection_demo \
  --output-dir output/injected \
  --no-interactive
```

---

## 进度追踪

| 日期 | 完成项 | 备注 |
|------|--------|------|
| 2026-03-06 | 计划创建 | - |
| 2026-03-06 | Phase 1-5 完成 | 核心功能实现完成 |

---

## 后续工作

1. 准备实际测试截图数据
2. 端到端测试验证
3. 更新项目 README
4. 根据测试结果调优 VLM 提示词

