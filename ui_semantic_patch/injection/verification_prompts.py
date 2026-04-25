"""
验证 Prompt 模板

用于 VLM 评估异常生成图像的质量。
"""

# 异常生成质量验证 Prompt
QUALITY_VERIFICATION_PROMPT = '''
## 角色
你是一个异常 UI 图像质量评估专家，专注于验证 AI 生成的异常场景是否符合测试标准。

## 待验证图像
[图像1] 原始截图（无异常）
[图像2] 生成的异常截图（期望注入异常）

## 异常信息
- 异常类型: {anomaly_type}
- 生成指令: {instruction}
- 期望的异常场景: {expected_scenario}

## 评估维度（每项 0-10 分）

### 1. 异常存在性 (anomaly_present)
目标异常是否真实存在于生成图像中？例如：
- 弹窗覆盖原UI：是否存在明显的弹窗遮挡？
- 内容歧义/重复：内容是否出现重复或语义冲突？
- loading_timeout：是否显示加载中/超时状态？
- network_error：是否显示网络错误提示？
- image_broken：图片是否显示为破碎或占位符？
- price_anomaly：价格/数值是否有异常显示？
- empty_state：内容区域是否显示为空？

### 2. 语义一致性 (semantic_match)
生成的异常是否与生成指令语义匹配？
- 异常类型是否正确？
- 异常是否出现在合理的位置？
- 异常是否自然融入界面？

### 3. 视觉质量 (visual_quality)
图像是否有明显的视觉瑕疵？
- 是否有拼接痕迹？
- 是否有模糊/伪影？
- 颜色/亮度是否协调？
- 文字是否清晰可读？

### 4. 自然度 (naturalness)
异常是否自然融入原界面？
- 是否符合 UI 设计的合理逻辑？
- 是否有明显的 AI 生成痕迹？
- 异常元素是否与周围内容协调？

## 输出格式（严格 JSON）
请用 <result> 标签包裹 JSON 输出：

<result>
{{
  "passed": true或false,
  "quality_score": 0-10,
  "dimensions": {{
    "anomaly_present": true或false,
    "anomaly_present_score": 0-10,
    "semantic_match": true或false,
    "semantic_match_score": 0-10,
    "visual_quality": 0-10,
    "naturalness": 0-10
  }},
  "issues": ["问题描述1", "问题描述2"],
  "reasoning": "详细的评估理由，解释每个维度的判断依据"
}}
</result>

## 判断标准
- passed = true 当且仅当 anomaly_present = true AND semantic_match = true AND quality_score >= 6
- 无论 passed 为何值，都应完整评估所有维度
'''

# 重试时的增强 Prompt（包含前次评估信息）
QUALITY_VERIFICATION_WITH_HISTORY_PROMPT = '''
## 角色
你是一个异常 UI 图像质量评估专家，这是第 {retry_count} 次评估。

## 上次评估结果
- passed: {prev_passed}
- quality_score: {prev_score}
- issues: {prev_issues}

## 待验证图像
[图像1] 原始截图（无异常）
[图像2] 生成的异常截图（期望注入异常）

## 异常信息
- 异常类型: {anomaly_type}
- 生成指令: {instruction}
- 期望的异常场景: {expected_scenario}

## 评估维度（每项 0-10 分）

### 1. 异常存在性 (anomaly_present)
目标异常是否真实存在于生成图像中？

### 2. 语义一致性 (semantic_match)
生成的异常是否与生成指令语义匹配？

### 3. 视觉质量 (visual_quality)
图像是否有明显的视觉瑕疵？

### 4. 自然度 (naturalness)
异常是否自然融入原界面？

## 输出格式（严格 JSON）
<result>
{{
  "passed": true或false,
  "quality_score": 0-10,
  "dimensions": {{
    "anomaly_present": true或false,
    "anomaly_present_score": 0-10,
    "semantic_match": true或false,
    "semantic_match_score": 0-10,
    "visual_quality": 0-10,
    "naturalness": 0-10
  }},
  "issues": ["问题描述1", "问题描述2"],
  "reasoning": "详细的评估理由"
}}
</result>
'''


# 异常类型到期望场景的映射
ANOMALY_EXPECTED_SCENARIOS = {
    "弹窗覆盖原UI": "全屏或半屏弹窗遮挡原有界面，如广告推广、优惠券领取、系统提示、权限请求等",
    "内容歧义、重复": "界面内容重复显示或语义冲突，如列表加载异常、数据同步错误、缓存问题",
    "loading_timeout": "加载超时、网络错误等状态，如网络请求等待、数据加载、页面渲染超时",
    "image_broken": "图片资源加载失败，显示破碎图标或占位符，如logo无法显示、图片裂开",
    "network_error": "网络异常提示覆盖界面，如Toast或错误横幅，航班搜索网络超时、支付请求失败",
    "price_anomaly": "价格或数值显示异常，如¥0、负数、乱码、格式错乱，如机票价格错误、折扣异常",
    "empty_state": "列表或内容区域为空，显示无数据状态，如无结果、筛选条件过严、历史订单清空"
}


def build_verification_prompt(
    anomaly_type: str,
    instruction: str,
    retry_count: int = 0,
    prev_result: dict = None
) -> str:
    """
    构建验证 Prompt

    Args:
        anomaly_type: 异常类型名称
        instruction: 生成指令
        retry_count: 当前重试次数（第几次评估）
        prev_result: 上次验证结果（用于增强 prompt）

    Returns:
        格式化的验证 prompt
    """
    expected_scenario = ANOMALY_EXPECTED_SCENARIOS.get(
        anomaly_type,
        f"异常类型: {anomaly_type}"
    )

    if retry_count > 0 and prev_result:
        # 使用带历史的增强 prompt
        return QUALITY_VERIFICATION_WITH_HISTORY_PROMPT.format(
            retry_count=retry_count + 1,
            prev_passed=prev_result.get("passed", False),
            prev_score=prev_result.get("quality_score", 0),
            prev_issues=prev_result.get("issues", []),
            anomaly_type=anomaly_type,
            instruction=instruction,
            expected_scenario=expected_scenario
        )

    return QUALITY_VERIFICATION_PROMPT.format(
        anomaly_type=anomaly_type,
        instruction=instruction,
        expected_scenario=expected_scenario
    )


def get_expected_scenario(anomaly_type: str) -> str:
    """获取异常类型的期望场景描述"""
    return ANOMALY_EXPECTED_SCENARIOS.get(
        anomaly_type,
        f"异常类型: {anomaly_type}"
    )
