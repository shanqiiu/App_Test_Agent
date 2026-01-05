# 参考资源索引

本目录收录AI智能体测试相关的学术研究和开源项目资源。

---

## 目录结构

### [学术研究](./学术研究.md)
**内容**: 相关学术论文和研究文献

**主要分类**:
- AI测试技术综述
- 上下文感知异常检测
- 对抗性测试
- 移动应用测试
- 异常生成技术

**文献数量**: 15篇

---

### [开源项目](./开源项目.md)
**内容**: 相关开源工具、框架和代码库

**主要分类**:
- UI自动化测试框架
- 异常生成工具
- 对抗性测试框架
- AI/ML框架
- 数据处理工具

**项目数量**: 12个

---

## 快速导航

### 按研究方向

#### 异常生成
- 📚 学术研究：
  - [Synthetic Data Generation](./学术研究.md#synthetic-data-generation-for-ai-agent-testing)
  - [Template-based Feature Aggregation](./学术研究.md#template-based-feature-aggregation-network-for-anomaly-detection)
- 💻 开源项目：
  - [Awesome-Anomaly-Generation](./开源项目.md#awesome-anomaly-generation)
  - [Stable Diffusion](./开源项目.md#stable-diffusion)

#### 上下文感知
- 📚 学术研究：
  - [Context-Aware Trajectory Anomaly Detection](./学术研究.md#context-aware-trajectory-anomaly-detection)
  - [Deep Context-Aware Feature Extraction](./学术研究.md#deep-context-aware-feature-extraction-for-anomaly-detection)
- 💻 实现参考：多模态融合、图结构建模

#### 对抗性测试
- 📚 学术研究：
  - [RedTeamCUA](./学术研究.md#redteamcua-realistic-adversarial-testing-of-computer-use-ai-agents)
  - [Shadow Injection](./学术研究.md#shadow-injection-and-adversarial-testing-in-tool-augmented-agents)
- 💻 开源项目：
  - [Intel Labs Adversarial Image Injection](./开源项目.md#intel-labs-adversarial-image-injection-framework)
  - [gMiniWoB](./开源项目.md#gminiwob)

#### UI自动化
- 📚 学术研究：
  - [Automated Visual Testing](./学术研究.md#automated-visual-testing-for-mobile-apps-in-an-industrial-setting)
  - [Mobile App Testing Best Practices](./学术研究.md#mobile-app-testing-test-types-best-practices-and-tools)
- 💻 开源项目：
  - [Appium](./开源项目.md#appium)
  - [Espresso](./开源项目.md#espresso)
  - [Detox](./开源项目.md#detox)

---

### 按优先级

#### 🔥 高优先级
**立即阅读/使用的资源**

学术研究：
1. [RedTeamCUA](./学术研究.md#redteamcua-realistic-adversarial-testing-of-computer-use-ai-agents) - 直接相关的对抗性UI测试
2. [Context-Aware Anomaly Detection](./学术研究.md#context-aware-trajectory-anomaly-detection) - 核心方法论
3. [Shadow Injection](./学术研究.md#shadow-injection-and-adversarial-testing-in-tool-augmented-agents) - 动态注入技术参考

开源项目：
1. [Appium](./开源项目.md#appium) - 正常行为采集工具
2. [Awesome-Anomaly-Generation](./开源项目.md#awesome-anomaly-generation) - 异常生成资源汇总
3. [OpenCV](./开源项目.md#opencv) - 图像处理基础

#### ⭐ 中优先级
**需要调研和评估的资源**

学术研究：
1. [Synthetic Data Generation](./学术研究.md#synthetic-data-generation-for-ai-agent-testing)
2. [Automated Visual Testing](./学术研究.md#automated-visual-testing-for-mobile-apps-in-an-industrial-setting)

开源项目：
1. [Intel Labs Adversarial Framework](./开源项目.md#intel-labs-adversarial-image-injection-framework)
2. [gMiniWoB](./开源项目.md#gminiwob)
3. [PyTorch](./开源项目.md#pytorch)

#### 💡 探索性
**长期规划和创新方向**

学术研究：
1. [Generative AI for Testing](./学术研究.md#generative-ai-for-testing-of-autonomous-driving-systems)
2. [Adversarial Prompting](./学术研究.md#adversarial-prompting-in-llms)

开源项目：
1. [Stable Diffusion](./开源项目.md#stable-diffusion)
2. [Hugging Face Transformers](./开源项目.md#hugging-face-transformers)

---

## 使用指南

### 文献调研流程
1. **确定研究问题** → 参考 [研究路线图](../planning/研究路线图.md)
2. **查找相关文献** → 浏览 [学术研究](./学术研究.md) 对应分类
3. **深入阅读** → 按优先级选择重点文献
4. **整理笔记** → 记录核心思想和可复用方法
5. **寻找实现** → 在 [开源项目](./开源项目.md) 查找参考代码

### 技术选型流程
1. **明确需求** → 参考 [调研文档](../research/)
2. **评估工具** → 查阅 [开源项目](./开源项目.md) 和 [技术栈](../technical/技术栈与工具.md)
3. **对比方案** → 结合学术研究的方法论
4. **原型验证** → 实现POC并评估效果

### 跟踪前沿动态
- 定期查看 [Awesome-Anomaly-Generation](./开源项目.md#awesome-anomaly-generation) 更新
- 关注相关会议：ICSE, ASE, ISSTA（软件测试）；NeurIPS, ICML（AI/ML）
- 跟踪相关研究者和实验室

---

## 资源统计

| 类别 | 数量 | 完整度 |
|------|------|--------|
| 学术论文 | 15篇 | ⭐⭐⭐⭐ |
| 开源项目 | 12个 | ⭐⭐⭐⭐ |
| 技术报告 | 待补充 | - |
| 行业案例 | 待补充 | - |

---

## 待补充资源

### 学术研究
- [ ] UI测试领域顶会论文（ICSE, ASE）
- [ ] 生成式AI最新进展（2024-2025）
- [ ] 异常检测benchmark论文

### 开源项目
- [ ] UI差分测试工具
- [ ] 移动应用性能测试工具
- [ ] 测试数据生成工具

### 行业实践
- [ ] 大厂测试技术分享
- [ ] 实际案例研究
- [ ] 技术博客和教程

---

## 贡献资源

欢迎补充新的学术研究或开源项目：

### 学术研究提交格式
参考 [学术研究.md](./学术研究.md) 中的格式

### 开源项目提交格式
参考 [开源项目.md](./开源项目.md) 中的格式

---

## 相关文档

- [调研文档](../research/) - 基于这些资源的调研分析
- [技术文档](../technical/) - 技术栈和术语说明
- [研究规划](../planning/) - 整体研究计划

---

**最后更新**: 2024-12-30
**总资源数**: 27+
