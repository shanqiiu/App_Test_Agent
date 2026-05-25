"""
flow_converter.py — 将修改后的 utg_info.json 合并到 Flow 模板

严格遵循模板 mainFlow.steps 格式（只保留 order + action 字段），
不添加额外字段，不修改模板其他部分。
"""

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


def get_valid_steps_from_utg(utg_data: Dict) -> List[Dict]:
    """从 utg_info.json 中提取有效步骤（有 ui_summary 的）"""
    step_data = utg_data.get("stepData", [])
    valid = []
    invalid_ids = {"home", "end", "start"}
    for item in step_data:
        sid = str(item.get("stepId", ""))
        if sid.lower() in invalid_ids:
            continue
        ui_summary = (item.get("ui_summary") or "").strip()
        if not ui_summary:
            continue
        valid.append({
            "order": len(valid) + 1,
            "stepId": sid,
            "ui_summary": ui_summary,
        })
    return valid


class FlowConverter:
    """
    Flow 模板转换器

    将修改后的 utg_info.json（含改写后的 ui_summary）合并到 Flow 模板的 mainFlow.steps。
    严格遵循模板现有的 step 字段格式（仅 order + action）。
    """

    def __init__(self):
        pass

    def convert(
        self,
        utg_path: str,
        template_path: str,
        output_path: str,
        mode: str = "replace",
    ) -> Dict[str, Any]:
        """
        合并转换

        Args:
            utg_path: 修改后的 utg_info.json 路径
            template_path: Flow 模板 JSON 路径
            output_path: 输出路径
            mode: "replace" - 完全替换, "fill" - 按顺序填充
        """
        result = {"success": False, "output_path": output_path, "step_count": 0, "error": None}

        try:
            utg_data = self._load_json(utg_path)
            template = self._load_json(template_path)

            utg_steps = get_valid_steps_from_utg(utg_data)
            if not utg_steps:
                result["error"] = "utg_info.json 中没有有效的 ui_summary 步骤"
                return result

            logger.info(f"UTG 有效步骤: {len(utg_steps)}")
            merged = deepcopy(template)

            if "mainFlow" not in merged:
                merged["mainFlow"] = {
                    "id": "flow-from-utg",
                    "name": utg_data.get("query", "操作流程"),
                    "description": utg_data.get("query", ""),
                    "precondition": f"用户已登录，{utg_data.get('appName', 'APP')}首页正常加载",
                    "steps": [],
                }

            # 构建新步骤 — 严格遵循模板格式: 只保留 order + action
            new_steps = [
                {"order": s["order"], "action": s["ui_summary"]}
                for s in utg_steps
            ]

            if mode == "replace":
                merged["mainFlow"]["steps"] = new_steps
            elif mode == "fill":
                template_steps = merged["mainFlow"].get("steps", [])
                for i, ns in enumerate(new_steps):
                    if i < len(template_steps):
                        template_steps[i] = {
                            "order": template_steps[i].get("order", i + 1),
                            "action": ns["action"],
                        }
                    else:
                        template_steps.append(ns)
                merged["mainFlow"]["steps"] = template_steps
            else:
                result["error"] = f"未知的合并模式: {mode}"
                return result

            self._save_json(merged, output_path)
            step_count = len(merged["mainFlow"]["steps"])
            logger.info(f"输出步骤数: {step_count}")
            logger.info(f"已保存: {output_path}")

            result["success"] = True
            result["step_count"] = step_count
            return result

        except Exception as e:
            logger.exception("转换失败")
            result["error"] = str(e)
            return result

    @staticmethod
    def _load_json(path: str) -> Dict:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def _save_json(data: Dict, path: str):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
