# 文档索引

`docs/` 现在只保留当前实现仍然有效的文档，历史实施计划、重复总结和过期分析已经清理。

## 当前保留

- [architecture.md](./architecture.md)
  - 当前项目总架构、主入口、模块职责、异常模式、序列语义。
- [utg-architecture.md](./utg-architecture.md)
  - `utg_info.json` 文本决策链路、UTG 批量注入流程。
- [mapping-generation.md](./mapping-generation.md)
  - mapping 自动生成、fault mode 分类、指令扩写、关键词定位机制。
- [技术难题业界与项目方案对照.md](./技术难题业界与项目方案对照.md)
  - 技术挑战、业界路线和当前项目落点的对照。

## 清理原则

以下类型的文档已删除：

- 和代码现状重复但内容更旧的总结文档
- 只描述“计划做什么”的实施方案文档
- 明显是一次性问题记录或人工 review 备注的文档
- 已经被总架构文档吸收的局部说明文档

如果后续需要新增文档，优先补充到现有主题文档中，避免再次把 `docs/` 拆成大量阶段性草稿。
