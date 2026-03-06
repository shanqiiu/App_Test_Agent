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
