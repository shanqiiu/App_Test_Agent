"""
UTG (UI Test Graph) 加载器

解析云端 agent 执行产生的 utg.json，提取每步的 ui_summary 语义理解数据。

utg.json 结构：
{
    "stepData": [
        {"stepId": "home"},                              // 起始标记（无 ui_summary）
        {"stepId": "3", "action_type": "...", "ui_summary": "华为商城首页..."},
        {"stepId": "4", "action_type": "...", "ui_summary": "页面顶部有搜索框..."},
        ...
        {"stepId": "end"}                                // 结束标记（无 ui_summary）
    ]
}

输出：过滤掉 home/end 和无 ui_summary 的步骤，按 step_id 排序。
"""

import json
from pathlib import Path
from typing import List, Dict, Optional


class UTGStep:
    """单个 UTG 步骤"""

    def __init__(self, step_id: str, action_type: str = "",
                 ui_summary: str = "", thought: str = "",
                 cost_time: str = "", step_type: str = ""):
        self.step_id = step_id
        self.action_type = action_type
        self.ui_summary = ui_summary
        self.thought = thought
        self.cost_time = cost_time
        self.step_type = step_type

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "action_type": self.action_type,
            "ui_summary": self.ui_summary,
            "thought": self.thought,
            "cost_time": self.cost_time,
            "step_type": self.step_type,
        }

    @property
    def has_summary(self) -> bool:
        return bool(self.ui_summary.strip())

    def __repr__(self):
        preview = self.ui_summary[:50] + "..." if len(self.ui_summary) > 50 else self.ui_summary
        return f"UTGStep(id={self.step_id}, action={self.action_type[:30]}, ui='{preview}')"


class UTGLoader:
    """UTG 数据加载器"""

    def __init__(self, utg_path: str):
        """
        加载 utg.json

        Args:
            utg_path: utg.json 文件路径
        """
        self.utg_path = Path(utg_path)
        if not self.utg_path.exists():
            raise FileNotFoundError(f"utg.json 不存在: {self.utg_path}")

        with open(self.utg_path, 'r', encoding='utf-8') as f:
            self._raw = json.load(f)

        self.steps: List[UTGStep] = []
        self._parse()
        self._filter_valid_steps()

    def _parse(self):
        """解析 stepData 数组"""
        step_data = self._raw.get("stepData", [])
        for item in step_data:
            sid = str(item.get("stepId", ""))
            if not sid:
                continue

            step = UTGStep(
                step_id=sid,
                action_type=item.get("action_type", ""),
                ui_summary=item.get("ui_summary", ""),
                thought=item.get("thought", ""),
                cost_time=item.get("cost_time", ""),
                step_type=item.get("type", ""),
            )
            self.steps.append(step)

    def _filter_valid_steps(self):
        """过滤掉 home/end 标记和无 ui_summary 的步骤"""
        invalid_ids = {"home", "end", "start"}
        self.valid_steps = [
            s for s in self.steps
            if s.step_id.lower() not in invalid_ids and s.has_summary
        ]

    def get_valid_steps(self) -> List[UTGStep]:
        """获取所有有效步骤（有 ui_summary 的）"""
        return self.valid_steps

    def get_step_by_id(self, step_id: str) -> Optional[UTGStep]:
        """根据 stepId 查找步骤"""
        for s in self.steps:
            if s.step_id == str(step_id):
                return s
        return None

    def get_ui_summaries(self) -> List[str]:
        """获取所有有效步骤的 ui_summary 列表"""
        return [s.ui_summary for s in self.valid_steps]

    def get_summary_text(self) -> str:
        """生成全量 ui_summary 的格式化文本，供 LLM 使用"""
        lines = []
        for i, s in enumerate(self.valid_steps):
            idx = i  # 0-based index，对应截图 step_00.png
            action = s.action_type.replace("<br>", "；").replace("\n", " ")
            # 限制 action 长度
            action_short = action[:80] + "..." if len(action) > 80 else action
            thought_short = s.thought[:60] + "..." if len(s.thought) > 60 else s.thought
            lines.append(
                f"Step {idx} (stepId={s.step_id})"
                f"\n  操作: {action_short}"
                f"\n  思考: {thought_short}" if thought_short else ""
            )
            lines.append(f"  UI状态: {s.ui_summary}")
        return "\n".join(lines)

    def to_dict_list(self) -> List[dict]:
        """输出所有有效步骤的字典列表"""
        return [s.to_dict() for s in self.valid_steps]

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def valid_count(self) -> int:
        return len(self.valid_steps)

    @property
    def task_description(self) -> str:
        """从 raw 数据中推断任务描述（如有）"""
        # utg.json 没有专门的任务描述字段，从首步操作推断
        for s in self.valid_steps:
            if "open(" in s.action_type:
                return f"打开并使用 {s.action_type.split('open(')[-1].rstrip(')')}"
            if "用户回复" in s.action_type:
                # 尝试提取用户原始请求
                parts = s.action_type.split("用户回复(")
                if len(parts) > 1:
                    return parts[1].split(");")[0]
        return "未识别任务描述"

    def __repr__(self):
        return f"UTGLoader(total={self.total_steps}, valid={self.valid_count})"


def load_utg(utg_path: str) -> UTGLoader:
    """便捷函数：加载 UTG 数据"""
    return UTGLoader(utg_path)
