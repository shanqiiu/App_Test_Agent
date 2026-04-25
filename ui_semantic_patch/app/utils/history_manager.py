"""
历史记录管理器

借鉴 UI-Venus 的 _build_query() 机制，实现增量式历史记录管理。
"""

from typing import List, Optional
from pathlib import Path
import json

from app.core.schemas import StepRecord


class HistoryManager:
    """
    历史记录管理器

    借鉴 UI-Venus 的设计：
    - 累积每步的分析结果
    - 支持窗口限制（max_history_steps）
    - 生成格式化的历史文本供 VLM 使用
    """

    def __init__(self, max_history_steps: int = 10):
        """
        初始化历史管理器

        Args:
            max_history_steps: 最大历史步数，超过则只保留最近 N 步
        """
        self.max_history_steps = max_history_steps
        self.records: List[StepRecord] = []

    def add_record(self, record: StepRecord) -> None:
        """添加一条步骤记录"""
        self.records.append(record)

    def get_recent_records(self) -> List[StepRecord]:
        """获取最近的记录（受窗口限制）"""
        if self.max_history_steps <= 0:
            return self.records
        return self.records[-self.max_history_steps:]

    def build_history_text(self) -> str:
        """
        构建历史文本（用于 VLM 提示词）

        借鉴 UI-Venus 的 _build_query() 方法：
        将历史记录格式化为文本，供 VLM 理解上下文
        """
        recent = self.get_recent_records()
        if not recent:
            return ""

        entries = [record.to_history_entry() for record in recent]
        return "\n".join(entries)

    def get_injection_record(self) -> Optional[StepRecord]:
        """获取决策为 INJECT 的记录（如果有）"""
        for record in self.records:
            if record.decision == "INJECT":
                return record
        return None

    def has_injection_decision(self) -> bool:
        """检查是否已有注入决策"""
        return self.get_injection_record() is not None

    def reset(self) -> None:
        """重置历史记录"""
        self.records = []

    def to_json(self) -> str:
        """导出为 JSON 字符串"""
        return json.dumps(
            [r.to_dict() for r in self.records],
            ensure_ascii=False,
            indent=2
        )

    def save(self, output_path: Path) -> None:
        """保存历史记录到文件"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self.to_json(), encoding='utf-8')

    def __len__(self) -> int:
        return len(self.records)

    def __repr__(self) -> str:
        return f"HistoryManager(records={len(self.records)}, max={self.max_history_steps})"
