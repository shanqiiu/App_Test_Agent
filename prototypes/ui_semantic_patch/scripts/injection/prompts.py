"""
VLM 提示词模板

借鉴 UI-Venus 的提示词结构，适配异常注入决策场景。
"""

# 异常注入决策提示词模板
INJECTION_DECISION_PROMPT = '''
###你是一个异常注入决策器
分析当前界面截图，结合历史步骤，判断此处是否适合注入异常。

你的任务是在一个操作序列中找到最合适的位置注入异常场景，使得：
1. 异常的出现在语义上合理（符合当前界面的业务逻辑）
2. 异常能够有效测试 AI Agent 的异常处理能力
3. 注入位置不宜太早（需要有足够的正常操作上下文）

###用户任务
{task_description}

###可注入的异常类型
{gt_categories_description}

###先前的步骤分析
{previous_steps}

###当前步骤
这是第 {step_index} 步的界面截图（共 {total_steps} 步）。

###输出格式
请严格按以下格式输出：

<think>
分析当前界面内容和语义，判断是否适合注入异常：
1. 当前界面是什么页面？显示了什么内容？
2. 用户正在进行什么操作？
3. 此处注入异常是否语义合理？
4. 如果注入，哪种异常类型最合适？为什么？
</think>
<decision>INJECT 或 SKIP</decision>
<anomaly_type>如果决策为 INJECT，填写选择的异常类型；否则留空</anomaly_type>
<instruction>如果决策为 INJECT，填写异常生成指令（如"在列表区域添加加载超时提示"）；否则留空</instruction>
<conclusion>本步骤的简短总结（一句话）</conclusion>

###注意事项
- 不要在序列的前 2 步就决定注入（需要足够的上下文）
- 优先在用户等待响应的场景注入（如搜索后、点击后、提交后）
- 确保异常类型与当前界面语义匹配
- 如果当前界面不适合注入任何异常，决策为 SKIP
'''

# 界面语义分析提示词（用于生成历史记录）
STEP_SUMMARY_PROMPT = '''
分析这张 App 界面截图，用一句话描述：
1. 这是什么页面
2. 页面的主要内容
3. 用户可能进行的操作

输出格式：
<summary>一句话描述</summary>
'''

# 异常类型描述模板
ANOMALY_CATEGORY_TEMPLATE = '''
{index}. {category_name}
   描述: {description}
   适用场景: {applicable_scenarios}
'''


def build_injection_prompt(
    task_description: str,
    gt_categories_description: str,
    previous_steps: str,
    step_index: int,
    total_steps: int
) -> str:
    """构建异常注入决策提示词"""
    return INJECTION_DECISION_PROMPT.format(
        task_description=task_description,
        gt_categories_description=gt_categories_description,
        previous_steps=previous_steps if previous_steps else "（这是第一步，暂无历史）",
        step_index=step_index,
        total_steps=total_steps
    )


def build_step_summary_prompt() -> str:
    """构建步骤摘要提示词"""
    return STEP_SUMMARY_PROMPT


def format_anomaly_category(
    index: int,
    category_name: str,
    description: str,
    applicable_scenarios: str
) -> str:
    """格式化单个异常类型描述"""
    return ANOMALY_CATEGORY_TEMPLATE.format(
        index=index,
        category_name=category_name,
        description=description,
        applicable_scenarios=applicable_scenarios
    )


# ===== 指令泛化生成提示词 =====

INSTRUCTION_GENERATION_PROMPT = '''
###角色
你是一个移动应用测试专家，擅长构造异常场景的测试指令。

###任务
针对「{scenario_name}」业务场景，为以下故障类型生成多样化的自然语言测试指令。
每条指令描述一个具体的异常注入操作，要求：
1. 指令内容贴合真实业务场景
2. 表述方式多样化（正式、口语、技术化）
3. 包含具体的界面元素或操作步骤

###业务流程步骤
{business_steps}

###可用的异常类型
{anomaly_types}

###思考链（Chain of Thought）
请按以下步骤思考，然后生成指令：

<think>
第一步：梳理业务流程
- 列出用户从开始到完成的完整操作步骤
- 识别每个步骤涉及的关键界面元素（按钮、列表、输入框、图片等）

第二步：故障点映射
- 对每个操作步骤，分析可能出现哪些类型的故障
- 考虑故障的真实性：这种故障在真实场景中是否可能发生？
- 优先选择高频、高影响的故障点

第三步：指令多样化
- 为每个故障点生成至少 3 条不同表述的指令
- 变化维度：动词选择、描述详细度、技术术语程度
- 确保指令可被异常渲染器理解和执行

第四步：质量检查
- 去除重复或过于相似的指令
- 确保覆盖所有异常类型
- 确保覆盖所有关键业务步骤
</think>

###输出格式
请输出 JSON 数组，每个元素格式如下：
```json
[
  {{
    "instruction": "具体的异常注入指令文本",
    "anomaly_mode": "对应的异常模式（dialog/area_loading/content_duplicate/text_overlay/image_broken/network_error/price_anomaly/empty_state）",
    "target_step": "对应的业务步骤名称",
    "category": "异常类别名称",
    "difficulty": "easy/medium/hard",
    "variants": ["指令变体1", "指令变体2"]
  }}
]
```

请生成至少 {count} 条指令，确保异常类型和业务步骤的覆盖面。
'''


def build_instruction_generation_prompt(
    scenario_name: str,
    business_steps: str,
    anomaly_types: str,
    count: int = 20
) -> str:
    """构建指令泛化生成提示词"""
    return INSTRUCTION_GENERATION_PROMPT.format(
        scenario_name=scenario_name,
        business_steps=business_steps,
        anomaly_types=anomaly_types,
        count=count
    )


# ===== 用户意图指令生成提示词 =====

USER_INSTRUCTION_GENERATION_PROMPT = '''
###角色
你是一个移动应用用户行为分析专家，擅长模拟真实用户对 AI Agent 下达的自然语言指令。

###任务
针对「{scenario_name}」业务场景（{app_name}），生成多样化的用户指令文本。
这些指令模拟真实用户对 AI Agent 说的话，要求 Agent 在 App 上完成相应操作。

###业务流程步骤
{business_steps}

###思考链（Chain of Thought）
<think>
第一步：用户画像分析
- 考虑不同类型用户：商务出差者、旅游度假者、学生、家庭用户、老年用户
- 每类用户的表达习惯不同：简洁/详细、正式/口语、有经验/新手

第二步：意图覆盖
- 核心意图：订票、查询、比价、筛选、退改签
- 辅助意图：选座、买保险、用优惠券、查订单、排序
- 边界意图：模糊需求、多步骤组合、信息不完整的指令

第三步：表达多样化
- 同一个意图用不同方式表达（至少 3 种）
- 变化维度：详细程度、口语化程度、参数完整性
- 包含省略主语、使用口语缩写、带有情感色彩等自然表达

第四步：复杂度分层
- simple：单一操作、参数明确（如"用微信支付"）
- medium：需要搜索或筛选、部分参数（如"查最便宜的去北京航班"）
- complex：多步骤组合、约束条件多、信息模糊（如"出差去杭州三天，机票酒店一起订"）
</think>

###输出格式
请输出 JSON 数组，每个元素格式如下：
```json
[
  {{
    "instruction": "用户的自然语言指令",
    "intent": "意图分类（如：单程订票、往返订票、查询比价、筛选条件、退改签等）",
    "complexity": "simple/medium/complex",
    "key_params": {{
      "相关参数名": "参数值或'未指定'"
    }}
  }}
]
```

请生成至少 {count} 条用户指令，确保：
1. 意图类型覆盖全面（订票、查询、筛选、退改签、支付等）
2. 复杂度均衡分布
3. 表达方式贴近真实用户口语
'''


def build_user_instruction_prompt(
    scenario_name: str,
    app_name: str,
    business_steps: str,
    count: int = 30
) -> str:
    """构建用户意图指令生成提示词"""
    return USER_INSTRUCTION_GENERATION_PROMPT.format(
        scenario_name=scenario_name,
        app_name=app_name,
        business_steps=business_steps,
        count=count
    )
