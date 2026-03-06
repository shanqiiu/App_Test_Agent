# Claude Code Skills 参考手册

> 当前 Claude Code 安装的所有 Skill 汇总说明
> 最后更新：2026-03-06

---

## 目录

- [Superpowers 核心工作流技能](#superpowers-核心工作流技能)
- [通用开发技能](#通用开发技能)
- [语言与框架专项技能](#语言与框架专项技能)
  - [Python](#python)
  - [Go](#go)
  - [Java / Spring Boot](#java--spring-boot)
  - [Swift / iOS](#swift--ios)
  - [前端 / React / Next.js](#前端--react--nextjs)
  - [数据库](#数据库)
  - [Django](#django)
- [AI / LLM 技能](#ai--llm-技能)
- [测试技能](#测试技能)
- [安全技能](#安全技能)
- [DevOps / 部署技能](#devops--部署技能)
- [内容与文档生成技能](#内容与文档生成技能)
- [项目管理与元技能](#项目管理与元技能)

---

## Superpowers 核心工作流技能

这类技能定义了工作流程和协作模式，是使用其他技能的基础。

| Skill | 触发方式 | 职能说明 |
|-------|----------|----------|
| `superpowers:using-superpowers` | 每次对话开始时 | 基础引导技能，建立如何发现和使用其他技能的规则；要求在任何响应前先检查是否有适用技能 |
| `superpowers:brainstorming` | 创建功能/组件/修改行为之前 | 创意工作前必须使用；引导系统性探索多种方案，避免直接跳入实现 |
| `superpowers:executing-plans` | 执行已有实现计划时 | 在独立会话中带审查节点执行书面计划，确保计划忠实落地 |
| `superpowers:subagent-driven-development` | 在当前会话执行计划时 | 使用子智能体并行执行计划中的独立任务 |
| `superpowers:dispatching-parallel-agents` | 面对 2+ 个独立任务时 | 并行分发多个无状态依赖的任务给子智能体，提升执行效率 |
| `superpowers:requesting-code-review` | 完成功能/合并前 | 引导如何请求代码审查，验证工作是否达到要求 |
| `superpowers:receiving-code-review` | 收到代码审查反馈时 | 在实施建议前，评估反馈是否合理，避免盲目接受技术上不合理的修改 |
| `superpowers:test-driven-development` | 实现任何功能/修复 bug 前 | TDD 工作流，强制先写测试再写实现代码 |
| `superpowers:systematic-debugging` | 遇到 bug/测试失败/异常行为时 | 系统性调试流程，在提出修复方案之前先做根因分析 |
| `superpowers:finishing-a-development-branch` | 实现完成、测试通过、需要集成时 | 引导如何完成开发分支的收尾工作（代码审查、合并决策等） |
| `superpowers:using-git-worktrees` | 开始需要隔离的功能开发前 | 创建 git worktree 提供与当前工作区隔离的开发环境 |

---

## 通用开发技能

| Skill | 触发方式 | 职能说明 |
|-------|----------|----------|
| `simplify` | 代码变更后 | 审查已变更代码的复用性、质量和效率，并修复发现的问题 |
| `everything-claude-code:plan` | 实现复杂功能前 | 重述需求、评估风险、创建分步实现计划；等待用户确认后才触碰代码 |
| `everything-claude-code:search-first` | 编写自定义代码前 | Research-before-coding 工作流：先搜索现有工具/库/模式，再决定是否自行实现 |
| `everything-claude-code:coding-standards` | TypeScript/JavaScript/React/Node.js 开发时 | 通用编码规范和最佳实践 |
| `everything-claude-code:verification-loop` | 提交/发布前 | 综合验证系统：lint、测试、安全扫描、diff 审查的完整闭环 |
| `everything-claude-code:autonomous-loops` | 构建自主 AI 循环时 | 自主 Claude Code 循环的架构模式：从顺序流水线到多智能体 DAG 系统 |
| `everything-claude-code:iterative-retrieval` | 需要渐进式上下文检索时 | 通过渐进精化解决子智能体上下文问题的检索模式 |
| `everything-claude-code:content-hash-cache-pattern` | 需要缓存昂贵文件处理结果时 | 使用 SHA-256 内容哈希缓存文件处理结果，路径无关、自动失效 |
| `everything-claude-code:regex-vs-llm-structured-text` | 解析结构化文本时 | 在 regex 和 LLM 之间做决策的框架：从 regex 开始，仅在低置信度时添加 LLM |

---

## 语言与框架专项技能

### Python

| Skill | 职能说明 |
|-------|----------|
| `everything-claude-code:python-patterns` | Python 惯用写法、PEP 8 规范、类型提示和构建健壮 Python 应用的最佳实践 |
| `everything-claude-code:python-testing` | 使用 pytest 的 Python 测试策略：TDD、fixtures、mock、参数化、覆盖率要求 |
| `everything-claude-code:python-review` | 全面的 Python 代码审查：PEP 8、类型提示、安全性和 Pythonic 惯用法；调用 python-reviewer 智能体 |

### Go

| Skill | 职能说明 |
|-------|----------|
| `everything-claude-code:golang-patterns` | 惯用 Go 模式、最佳实践和构建健壮高效 Go 应用的约定 |
| `everything-claude-code:golang-testing` | Go 测试模式：表驱动测试、子测试、基准测试、模糊测试和测试覆盖率 |
| `everything-claude-code:go-build` | 修复 Go 构建错误、go vet 警告和 linter 问题；调用 go-build-resolver 智能体 |
| `everything-claude-code:go-review` | 全面的 Go 代码审查：惯用模式、并发安全性、错误处理和安全性；调用 go-reviewer 智能体 |
| `everything-claude-code:go-test` | Go TDD 工作流：先写表驱动测试，再实现，用 `go test -cover` 验证 80%+ 覆盖率 |

### Java / Spring Boot

| Skill | 职能说明 |
|-------|----------|
| `everything-claude-code:java-coding-standards` | Java Spring Boot 服务编码规范：命名、不变性、Optional、流、异常、泛型和项目布局 |
| `everything-claude-code:springboot-patterns` | Spring Boot 架构模式：REST API、分层服务、数据访问、缓存、异步处理和日志 |
| `everything-claude-code:springboot-tdd` | Spring Boot TDD：JUnit 5、Mockito、MockMvc、Testcontainers 和 JaCoCo |
| `everything-claude-code:springboot-security` | Spring Security 最佳实践：认证/授权、CSRF、密钥、请求头、限流和依赖安全 |
| `everything-claude-code:springboot-verification` | Spring Boot 项目验证闭环：构建、静态分析、测试覆盖率、安全扫描和 diff 审查 |
| `everything-claude-code:jpa-patterns` | JPA/Hibernate 模式：实体设计、关系映射、查询优化、事务、审计、索引和连接池 |

### Swift / iOS

| Skill | 职能说明 |
|-------|----------|
| `everything-claude-code:swiftui-patterns` | SwiftUI 架构模式、@Observable 状态管理、视图组合、导航和性能优化 |
| `everything-claude-code:swift-concurrency-6-2` | Swift 6.2 并发：单线程默认、@concurrent 显式后台调度、隔离一致性 |
| `everything-claude-code:swift-actor-persistence` | 使用 Actor 实现线程安全数据持久化：内存缓存 + 文件存储，消除数据竞争 |
| `everything-claude-code:swift-protocol-di-testing` | 基于协议的依赖注入：用聚焦协议和 Swift Testing 框架 mock 文件系统/网络/外部 API |
| `everything-claude-code:foundation-models-on-device` | Apple FoundationModels 框架：设备端 LLM 文本生成、@Generable 引导生成、工具调用 |
| `everything-claude-code:liquid-glass-design` | iOS 26 Liquid Glass 设计系统：动态玻璃材质、模糊/反射/交互变形，适用于 SwiftUI/UIKit |

### 前端 / React / Next.js

| Skill | 职能说明 |
|-------|----------|
| `everything-claude-code:frontend-patterns` | React、Next.js、状态管理、性能优化和 UI 最佳实践 |
| `everything-claude-code:backend-patterns` | 后端架构、API 设计、数据库优化：Node.js、Express 和 Next.js API Routes |
| `everything-claude-code:api-design` | REST API 设计模式：资源命名、状态码、分页、过滤、错误响应、版本控制和限流 |

### 数据库

| Skill | 职能说明 |
|-------|----------|
| `everything-claude-code:postgres-patterns` | PostgreSQL 数据库模式：查询优化、Schema 设计、索引和安全性（基于 Supabase 最佳实践） |
| `everything-claude-code:database-migrations` | 数据库迁移最佳实践：Schema 变更、数据迁移、回滚和零停机部署 |
| `everything-claude-code:clickhouse-io` | ClickHouse 数据库模式：查询优化、分析和高性能数据工程最佳实践 |

### Django

| Skill | 职能说明 |
|-------|----------|
| `everything-claude-code:django-patterns` | Django 架构模式：DRF REST API、ORM 最佳实践、缓存、信号、中间件和生产级应用 |
| `everything-claude-code:django-tdd` | Django + pytest-django TDD：factory_boy、mock、覆盖率和测试 DRF API |
| `everything-claude-code:django-security` | Django 安全最佳实践：认证、授权、CSRF、SQL 注入、XSS 防护和安全部署 |
| `everything-claude-code:django-verification` | Django 项目验证闭环：迁移、lint、测试覆盖率、安全扫描和部署就绪检查 |

---

## AI / LLM 技能

| Skill | 触发条件 | 职能说明 |
|-------|----------|----------|
| `claude-api` | 代码导入 `anthropic`/`@anthropic-ai/sdk`/`claude_agent_sdk`，或用户要求使用 Claude API | 使用 Claude API 或 Anthropic SDK 构建应用的完整指南 |
| `everything-claude-code:cost-aware-llm-pipeline` | 构建 LLM API 调用管道时 | LLM API 成本优化：按任务复杂度路由模型、预算跟踪、重试逻辑和 Prompt 缓存 |

---

## 测试技能

| Skill | 职能说明 |
|-------|----------|
| `superpowers:test-driven-development` | 通用 TDD 工作流：实现任何功能/修复 bug 前先写测试 |
| `everything-claude-code:tdd` | TDD 工作流强制执行：先搭骨架、生成测试，再实现最少代码，确保 80%+ 覆盖率 |
| `everything-claude-code:tdd-workflow` | 与 `tdd` 类似，适用于新功能、bug 修复和重构场景 |
| `everything-claude-code:e2e` | 使用 Playwright 生成并运行端到端测试，捕获截图/视频/trace，上传产物 |
| `everything-claude-code:e2e-testing` | Playwright E2E 测试模式：Page Object Model、配置、CI/CD 集成、产物管理和 flaky 测试处理 |
| `everything-claude-code:cpp-testing` | C++ 测试：GoogleTest/CTest 配置、失败测试诊断、覆盖率和 sanitizer |

---

## 安全技能

| Skill | 职能说明 |
|-------|----------|
| `everything-claude-code:security-review` | 添加认证、处理用户输入、使用密钥、创建 API 端点或实现支付时进行安全审查 |
| `everything-claude-code:security-scan` | 扫描 `.claude/` 配置目录中的安全漏洞、错误配置和注入风险 |
| `everything-claude-code:springboot-security` | Spring Boot 安全专项（见上方 Java 部分） |
| `everything-claude-code:django-security` | Django 安全专项（见上方 Django 部分） |

---

## DevOps / 部署技能

| Skill | 职能说明 |
|-------|----------|
| `everything-claude-code:docker-patterns` | Docker 和 Docker Compose 模式：本地开发、容器安全、网络、卷策略和多服务编排 |
| `everything-claude-code:deployment-patterns` | 部署工作流、CI/CD 流水线模式、Docker 容器化、健康检查、回滚策略和生产就绪检查 |
| `everything-claude-code:cpp-coding-standards` | 基于 C++ Core Guidelines 的 C++ 编码规范 |

---

## 内容与文档生成技能

| Skill | 职能说明 |
|-------|----------|
| `ppt-generation` | 创建 PPT 演示文稿、生成汇报幻灯片、工作总结、技术洞察或任何结构化演示内容 |
| `everything-claude-code:frontend-slides` | 从零创建或转换 PowerPoint 为动画丰富的 HTML 演示文稿 |
| `everything-claude-code:article-writing` | 撰写文章、指南、博客、教程、newsletter 和其他长篇内容，保持独特的写作风格 |
| `everything-claude-code:content-engine` | 创建平台原生内容系统：X、LinkedIn、TikTok、YouTube、newsletter 和多平台内容复用 |
| `everything-claude-code:investor-materials` | 创建和更新融资路演材料：pitch deck、一页纸、投资者备忘录、加速器申请、财务模型 |
| `everything-claude-code:investor-outreach` | 起草冷邮件、温介绍、跟进邮件、进度更新和其他融资沟通内容 |
| `everything-claude-code:market-research` | 市场调研、竞争分析、投资者尽职调查和行业情报（含来源引用和决策导向输出） |
| `everything-claude-code:nutrient-document-processing` | 使用 Nutrient DWS API 处理/转换/OCR/提取/脱敏/签署/填写文档（PDF、DOCX、XLSX 等） |
| `everything-claude-code:visa-doc-translate` | 翻译签证申请文件（图片）为英文并创建双语 PDF |

---

## 项目管理与元技能

这类技能用于管理 Claude Code 自身的学习、配置和工作方式。

| Skill | 职能说明 |
|-------|----------|
| `init-project` | 初始化新项目（命令：`/init-project`） |
| `everything-claude-code:configure-ecc` | 交互式安装 Everything Claude Code 技能和规则到用户级或项目级 |
| `everything-claude-code:skill-create` | 分析本地 git 历史，提取编码模式，生成 SKILL.md 文件（本地版 Skill Creator） |
| `everything-claude-code:skill-stocktake` | 审计 Claude 技能和命令质量（快速扫描变更技能 / 全量盘点两种模式） |
| `everything-claude-code:learn-eval` | 从会话中提取可复用模式，自我评估质量后保存（判断 Global vs Project 范围） |
| `everything-claude-code:continuous-learning` | 自动从 Claude Code 会话中提取可复用模式并保存为学习技能 |
| `everything-claude-code:continuous-learning-v2` | 基于 Instinct 的学习系统：通过 hook 观察会话，创建带置信度分数的原子 instinct |
| `everything-claude-code:eval-harness` | 实现评估驱动开发（EDD）原则的正式评估框架 |
| `everything-claude-code:evolve` | 分析 instinct 并建议或生成进化后的结构 |
| `everything-claude-code:instinct-status` | 显示已学习的 instinct（项目级 + 全局级）及置信度 |
| `everything-claude-code:instinct-export` | 将 instinct 从项目/全局范围导出到文件 |
| `everything-claude-code:instinct-import` | 从文件或 URL 导入 instinct 到项目/全局范围 |
| `everything-claude-code:promote` | 将项目范围的 instinct 提升为全局范围 |
| `everything-claude-code:projects` | 列出已知项目及其 instinct 统计信息 |
| `everything-claude-code:plankton-code-quality` | 使用 Plankton 在每次文件编辑时自动格式化、lint 和 Claude 驱动修复（通过 hook 触发） |
| `everything-claude-code:strategic-compact` | 在逻辑节点建议手动上下文压缩，保留任务阶段间的上下文，而非等待自动压缩 |
| `everything-claude-code:claw` | 启动 NanoClaw 智能体 REPL：由 claude CLI 驱动的持久、会话感知 AI 助手 |

---

## 快速选择指南

```
遇到 bug?          → superpowers:systematic-debugging
写新功能?          → superpowers:brainstorming → superpowers:test-driven-development
代码审查?          → superpowers:requesting-code-review
收到审查意见?      → superpowers:receiving-code-review
并行任务?          → superpowers:dispatching-parallel-agents
安全相关代码?      → everything-claude-code:security-review
写 Python?         → everything-claude-code:python-patterns + python-testing
写 Go?             → everything-claude-code:golang-patterns + golang-testing
写 Java?           → everything-claude-code:springboot-patterns + jpa-patterns
写 Swift/iOS?      → everything-claude-code:swiftui-patterns
写 React/Next.js?  → everything-claude-code:frontend-patterns
写数据库?          → everything-claude-code:postgres-patterns
用 Claude API?     → claude-api
生成 PPT?          → ppt-generation
E2E 测试?          → everything-claude-code:e2e
Docker/部署?       → everything-claude-code:docker-patterns + deployment-patterns
```
