"""
utg_loader.py — UTG (UI Test Graph) 数据加载器

解析 utg.json / utg_info.json，提取每步的 ui_summary 语义描述数据。
纯 Python 实现，无外部依赖。
"""

import json
from pathlib import Path
from typing import List, Optional


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
        self.image_id = ""

    @property
    def has_summary(self) -> bool:
        return bool(self.ui_summary.strip())


class UTGLoader:
    """UTG 数据加载器"""

    def __init__(self, utg_path: str):
        self.utg_path = Path(utg_path)
        if not self.utg_path.exists():
            raise FileNotFoundError(f"utg.json 不存在: {self.utg_path}")

        with open(self.utg_path, 'r', encoding='utf-8') as f:
            self._raw = json.load(f)

        self.steps: List[UTGStep] = []
        self.valid_steps: List[UTGStep] = []
        self._parse()

    def _parse(self):
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
            step.image_id = item.get("imageId", "")
            self.steps.append(step)

        invalid_ids = {"home", "end", "start"}
        self.valid_steps = [
            s for s in self.steps
            if s.step_id.lower() not in invalid_ids and s.has_summary
        ]

    def get_valid_steps(self) -> List[UTGStep]:
        return self.valid_steps

    def get_summary_text(self) -> str:
        """生成全量 stepData 的格式化文本，供 LLM 评分"""
        lines = []
        for i, s in enumerate(self.valid_steps):
            img_tag = f" [截图: {s.image_id}]" if s.image_id else ""
            thought = s.thought.strip() if s.thought else ""
            lines.append(f"Step {i}{img_tag}")
            if thought:
                lines.append(f"  意图: {thought}")
            lines.append(f"  UI: {s.ui_summary}")
            lines.append("")
        return "\n".join(lines)

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def valid_count(self) -> int:
        return len(self.valid_steps)

    @property
    def task_description(self) -> str:
        query = self._raw.get("query", "")
        if query:
            return query
        for s in self.valid_steps:
            if "open(" in s.action_type:
                return f"打开并使用 {s.action_type.split('open(')[-1].rstrip(')')}"
        return "未识别任务描述"
