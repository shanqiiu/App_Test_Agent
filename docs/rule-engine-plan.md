# VLM 分类 + 规则引擎 — 实施计划

## 1. 概述

### 现状问题

| 方案 | 问题 |
|------|------|
| 旧 VLM 自由决策 | VLM 三维开放决策（注入与否 + 注入类型 + 注入点），输出不稳定 |
| 当前 `len//2` 硬编码 | 无视截图语义，所有故障模式固定中间位置 |

### 方案核心

**将 VLM 的任务从"开放决策"降级为"封闭分类"**：

```
旧: VLM 回答 "是否注入？注入什么？在哪注入？"  → 不稳定
新: VLM 回答 "这是什么页面？有什么关键元素？"  → 封闭分类，高准确率
    规则引擎根据分类结果确定 "注入什么 + 在哪注入"  → 确定性强
```

## 2. 架构设计

```
┌──────────────────────────────────────────────────────────┐
│                      SequenceAnalyzer                    │
│  (改造)                                                  │
│  ┌────────────────────────────────────────────────────┐  │
│  │ Step 1: VLM 分类器                                  │  │
│  │   输入: screenshot                                  │  │
│  │   输出: {page_type, key_elements, user_waiting}    │  │
│  └──────────────┬─────────────────────────────────────┘  │
│                 ▼                                        │
│  ┌────────────────────────────────────────────────────┐  │
│  │ Step 2: RuleMatcher 规则匹配                       │  │
│  │   输入: page_type + key_elements                   │  │
│  │   输出: {anomaly_mode, instruction, priority}      │  │
│  │   匹配: page_type → anomaly_mode 映射表             │  │
│  │   增强: 关键元素匹配 → 更精准的 instruction          │  │
│  └──────────────┬─────────────────────────────────────┘  │
│                 ▼                                        │
│  ┌────────────────────────────────────────────────────┐  │
│  │ Step 3: TimingValidator 时序验证                   │  │
│  │   检查: min_steps_before_inject                    │  │
│  │   检查: 同类页面优先级                              │  │
│  │   检查: 用户等待状态优先                             │  │
│  └──────────────┬─────────────────────────────────────┘  │
│                 ▼                                        │
│  ┌────────────────────────────────────────────────────┐  │
│  │ Step 4: 输出 injection_point + anomaly_config      │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
         │
         ▼ (失败/不匹配)
┌───────────────────────┐
│ Fallback: len//2 +    │
│ dialog (不弱于当前)    │
└───────────────────────┘
```

## 3. 规则表设计

### 3.1 页面类型定义

```json
{
  "page_types": {
    "splash":      {"name": "启动页/开屏页",     "keywords": ["启动", "开屏", "广告", "splash"]},
    "home":        {"name": "首页/主页面",       "keywords": ["首页", "主界面", "home", "tab"]},
    "search":      {"name": "搜索/筛选页",       "keywords": ["搜索", "筛选", "查询", "search"]},
    "list_result": {"name": "列表/结果页",       "keywords": ["列表", "结果", "商品", "列表"]},
    "detail":      {"name": "详情展示页",        "keywords": ["详情", "介绍", "detail", "详情"]},
    "form":        {"name": "表单填写页",        "keywords": ["表单", "填写", "输入", "form", "填写"]},
    "payment":     {"name": "支付/确认页",       "keywords": ["支付", "确认", "付款", "下单"]},
    "profile":     {"name": "个人中心/设置页",   "keywords": ["个人", "设置", "我的", "profile"]},
    "loading_wait":{"name": "加载/等待页面",     "keywords": ["加载", "等待", "loading", "进度"]},
    "other":       {"name": "其他/未知页面",     "keywords": []}
  }
}
```

### 3.2 异常模式 → 页面映射规则

```json
{
  "rules": [
    {
      "id": "splash_dialog_ad",
      "page_types": ["splash", "home"],
      "anomaly_mode": "dialog",
      "fault_mode": "开屏广告弹窗",
      "instruction_template": "在首页生成广告弹窗遮挡功能入口",
      "priority": 80,
      "gt_category": "dialog",
      "gt_sample": "自动匹配（取dialog分类第一个可用样本）"
    },
    {
      "id": "home_dialog_coupon",
      "page_types": ["home"],
      "anomaly_mode": "dialog",
      "fault_mode": "优惠券弹窗",
      "instruction_template": "在页面生成优惠券领取弹窗",
      "priority": 70,
      "gt_category": "dialog"
    },
    {
      "id": "home_dialog_permission",
      "page_types": ["home", "splash"],
      "anomaly_mode": "dialog",
      "fault_mode": "权限请求弹窗",
      "instruction_template": "模拟定位权限请求弹窗",
      "priority": 60,
      "gt_category": "dialog"
    },
    {
      "id": "search_result_empty",
      "page_types": ["list_result", "search"],
      "anomaly_mode": "modify_text",
      "fault_mode": "无结果状态提示",
      "instruction_template": "将查询结果修改为「未找到相关结果」状态",
      "priority": 90,
      "requires_elements": ["列表", "结果"]
    },
    {
      "id": "search_button_disabled",
      "page_types": ["search", "form"],
      "anomaly_mode": "modify_text_ocr",
      "fault_mode": "按钮置灰不可用",
      "instruction_template": "将查询按钮置灰，显示为不可点击状态",
      "priority": 70,
      "requires_elements": ["查询", "搜索", "按钮"]
    },
    {
      "id": "list_loading_timeout",
      "page_types": ["list_result", "loading_wait"],
      "anomaly_mode": "area_loading",
      "fault_mode": "列表加载超时",
      "instruction_template": "模拟列表加载超时，显示加载失败提示",
      "priority": 85,
      "user_waiting": true
    },
    {
      "id": "detail_dialog_prompt",
      "page_types": ["detail"],
      "anomaly_mode": "dialog",
      "fault_mode": "系统提示弹窗",
      "instruction_template": "模拟系统提示弹窗（与商品相关）",
      "priority": 60,
      "gt_category": "dialog"
    },
    {
      "id": "payment_network_error",
      "page_types": ["payment"],
      "anomaly_mode": "dialog",
      "fault_mode": "支付超时弹窗",
      "instruction_template": "模拟支付超时的系统提示弹窗",
      "priority": 90,
      "user_waiting": true,
      "gt_category": "dialog"
    },
    {
      "id": "profile_login_prompt",
      "page_types": ["profile"],
      "anomaly_mode": "dialog",
      "fault_mode": "登录提示弹窗",
      "instruction_template": "模拟需要登录的权限弹窗",
      "priority": 65,
      "gt_category": "dialog"
    },
    {
      "id": "list_content_duplicate",
      "page_types": ["list_result", "home"],
      "anomaly_mode": "content_duplicate",
      "fault_mode": "内容重复展示",
      "instruction_template": "将列表第一个元素复制，制造内容重复异常",
      "priority": 50,
      "requires_elements": ["列表"]
    }
  ]
}
```

### 3.3 优先级与 fallback 策略

```
匹配到多条规则时 → 按 priority 降序选择
                  → 同优先级时随机选择
无匹配规则       → fallback: len(screenshots)//2 + dialog
```

## 4. VLM 分类 Prompt

封闭式分类 Prompt，输出结构化 JSON：

```python
VLM_CLASSIFICATION_PROMPT = '''
分析这张 App 界面截图，回答以下问题。

### 页面类型（单选，必须选最接近的）：
{splash_info}    A. 启动页/开屏页 — 应用启动画面、品牌展示、开屏广告
{home_info}      B. 首页/主页面 — 应用主界面、tab导航页
{search_info}    C. 搜索/筛选页 — 搜索框、筛选条件、日期选择
{list_info}      D. 列表/结果页 — 商品列表、搜索结果、信息流
{detail_info}    E. 详情展示页 — 商品详情、信息详情
{form_info}      F. 表单填写页 — 输入框、表单填写、信息录入
{payment_info}   G. 支付/确认页 — 支付确认、订单确认
{profile_info}   H. 个人中心/设置 — 我的页面、设置页
{loading_info}   I. 加载/等待页 — 加载动画、等待状态
                 J. 其他

### 关键元素
当前页面上有哪些可交互的关键元素？
（列出按钮、输入框、列表等，如：查询按钮、出发日期选择、搜索框）

### 用户等待状态
用户当前是否在等待某个操作的结果？
（如：等待搜索完成、等待支付结果、等待页面加载）
回答 true 或 false。

### 输出格式（仅返回 JSON，不要其他内容）
{
  "page_type": "A/B/C/D/E/F/G/H/I/J",
  "page_type_name": "页面类型名称",
  "key_elements": ["元素1", "元素2"],
  "user_waiting": true/false,
  "reasoning": "简要判断理由"
}
'''
```

## 5. 文件清单与改动范围

### 5.1 新增文件

| 文件 | 用途 | 预估行数 |
|------|------|---------|
| `app/injection/rule_engine.py` | 规则引擎：加载规则表 + 匹配 + 优先级排序 | ~120 |
| `app/injection/page_classifier.py` | VLM 页面分类器：调用 VLM + 解析分类结果 | ~100 |
| `app/injection/rules.json` | 规则表配置文件（解耦，无需改代码即可增删规则） | ~80 |
| `docs/rule-engine-plan.md` | 本实施计划 | — |

### 5.2 修改文件

| 文件 | 改动 | 预估改动量 |
|------|------|-----------|
| `app/injection/sequence_analyzer.py` | 核心改造：替换 VLM 决策逻辑为 分类+规则引擎 流程 | 重写 `analyze_step()` |
| `app/injection/prompts.py` | 新增 VLM_CLASSIFICATION_PROMPT，保留旧 prompt 作为参考 | +30 行 |
| `scripts/batch_injection_with_mapping.py` | 集成新的 SequenceAnalyzer，替代 `len//2` | ~50 行 |

### 5.3 不改动的文件

| 文件 | 原因 |
|------|------|
| `app/renderers/*` | 渲染逻辑无需改动，只改变决策 |
| `app/injection/sequence_rewriter.py` | 仅执行改写，不对决策逻辑耦合 |
| `app/injection/quality_verifier.py` | 独立的质量验证模块，不改 |
| `config/query_anomaly_mapping.json` | 保留作为应用级映射兜底，与规则引擎共存 |

## 6. 实施步骤

### Phase 1：基础结构（0.5 天）

```
Step 1.1  — 创建 app/injection/rules.json
             定义页面类型、规则表（第 3 节内容）
             新增 8 种页面类型 × 10 条规则

Step 1.2  — 创建 app/injection/page_classifier.py
             PageClassifier 类
             - classify(screenshot_path) → {page_type, key_elements, user_waiting}
             - 调用 VLM API（复用 _call_vlm 逻辑）
             - 解析 JSON 格式响应
             - cache 机制（同一截图不重复调用）

Step 1.3  — 创建 app/injection/rule_engine.py
             RuleEngine 类
             - load_rules(path) → 加载 rules.json
             - match(page_type, elements, user_waiting) → [matched_rules]
             - select_best(matched_rules) → 按优先级选最优
             - get_anomaly_config(rule) → {anomaly_mode, instruction, ...}
```

### Phase 2：核心改造（0.5 天）

```
Step 2.1  — 改造 sequence_analyzer.py
             保留 run() 框架（逐帧遍历 + 停止条件）
             重写 analyze_step() 为：
               1. VLM 分类页面 → page_type
               2. 规则引擎匹配 → anomaly_config
               3. 时序验证 → injection_point
               4. 输出结果
             删除旧 VLM 自由决策逻辑

Step 2.2  — 更新 prompts.py
             添加 VLM_CLASSIFICATION_PROMPT
             保留旧 INJECTION_DECISION_PROMPT 作为参考（不删除）
```

### Phase 3：集成与调试（0.5 天）

```
Step 3.1  — 改造 batch_injection_with_mapping.py
             替换 len(screenshots)//2 为 SequenceAnalyzer.run()
             保留 fallback（无匹配时回退到中间位置 + dialog）

Step 3.2  — 集成测试
             对 3 个 demo 示例各运行一次
             验证：注入点是否语义合理、anomaly_mode 是否匹配页面类型
```

### Phase 4：验证与优化（0.5 天）

```
Step 4.1  — 人工验证输出质量
             - 检查注入点是否语义合理
             - 检查异常类型是否匹配页面
             - 对比旧方案（VLM/len//2）的效果提升

Step 4.2  — 规则表调优
             根据测试结果调整 priority、增删规则
             补充遗漏的页面类型映射
```

**总计工期：2 人天**

## 7. 关键实现细节

### 7.1 分类 + 匹配流程伪代码

```python
# sequence_analyzer.py (改造后)
class SequenceAnalyzer:
    def __init__(self, ...):
        self.classifier = PageClassifier(api_key, api_url, model)
        self.rule_engine = RuleEngine(rules_path)
        
    def analyze_step(self, screenshot_path, step_index, total_steps):
        # Step 1: 前置约束
        if step_index < self.min_steps_before_inject:
            return {"decision": "SKIP"}
        
        # Step 2: VLM 分类
        page_info = self.classifier.classify(screenshot_path)
        
        # Step 3: 规则匹配
        matched = self.rule_engine.match(
            page_type=page_info["page_type"],
            elements=page_info["key_elements"],
            user_waiting=page_info["user_waiting"]
        )
        
        if not matched:
            return {"decision": "SKIP"}
        
        # Step 4: 选最优规则
        best = self.rule_engine.select_best(matched)
        config = self.rule_engine.get_anomaly_config(best)
        
        return {
            "decision": "INJECT",
            "anomaly_mode": config["anomaly_mode"],
            "instruction": config["instruction"],
            "gt_category": config.get("gt_category", ""),
            "gt_sample": config.get("gt_sample", ""),
            "page_type": page_info["page_type_name"]
        }
```

### 7.2 rules.json 与 query_anomaly_mapping.json 的关系

| 维度 | `rules.json`（新增） | `query_anomaly_mapping.json`（已有） |
|------|--------------------|-----------------------------------|
| 匹配依据 | 页面类型（VLM 分类结果） | 用户 query 文本 + app_name |
| 粒度 | 页面维度 | 应用+query 维度 |
| 覆盖范围 | 通用（不依赖具体应用） | 应用定制（需手动配置） |
| 定位 | 通用兜底规则引擎 | 应用级精细映射 |

两者**共存**：`rules.json` 作为通用匹配，`query_anomaly_mapping.json` 作为应用级精细覆盖。

### 7.3 异常配置输出格式

```python
# get_anomaly_config() 输出
{
    "anomaly_mode": "dialog",
    "instruction": "在首页生成广告弹窗遮挡功能入口",
    "gt_category": "dialog",
    "gt_sample": "",  # 空 = 取该分类第一个可用样本
    "fault_mode": "开屏广告弹窗",  # 仅用于日志/元数据
    "priority": 80,
    "matched_rule_id": "splash_dialog_ad"  # 用于追踪
}
```

## 8. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| VLM 页面分类不准 | 中 | 规则匹配错误 | 封闭分类（8 类）+JSON 格式约束，准确率高于开放决策；有 fallback 兜底 |
| 规则表不完备 | 中 | 部分页面无匹配 | fallback 策略（中间点+dialog）不弱于当前方案 |
| VLM 调用成本 | 低 | 每张截图需 1 次 API 调用 | 500tokens/次，含缓存机制，同一截图不重复调用 |
| 规则表膨胀 | 低 | 维护困难 | JSON 文件独立管理，改规则无需改代码；设计时预留分类字段 |

## 9. 验收标准

```
✅ 对 3 个 injection_demo 运行后：
   - 注入点不再固定为 len//2
   - 注入点语义合理（如：搜索页 → 注入搜索相关异常）
   - anomaly_mode 与页面类型匹配（如：首页 → dialog、列表页 → area_loading）
   - 无规则匹配时正确 fallback（不报错，能跑完）
   - 每张截图只调用 1 次 VLM
```

---

*版本: 1.0*
*最后更新: 2026-04-30*
