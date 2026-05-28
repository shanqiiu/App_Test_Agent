"""
flow_converter.py — Phase 2: 将改写后的 UTG 数据转换为符合 Schema 的 Flow JSON

设计原则：
  - 场景无关（不假设购物/外卖/社交等具体业务）
  - LLM 驱动内容填充，不硬编码规则（无 SCREEN_KEY_KEYWORDS / 品牌正则等）
  - 字段定义来源：model-schema.json（运行时读取）
  - 结构骨架来源：模板 JSON（mainFlow 外的大部分字段保留）

流程：
  1. 读取 injected UTG → 提取有效步骤 (stepData)
  2. 读取模板 JSON → 作为输出结构的骨架
  3. 读取 model-schema.json → 获取各字段的约束定义
  4. LLM 生成 mainFlow.steps（从 ui_summary 改写为 action 描述）
  5. LLM 提取业务实体（从 steps → topics[].mockInstances）
  6. 合并到模板骨架 + 按模板 step 字段过滤输出
  7. Schema 校验 + 保存
"""

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Any

from .llm_client import LLMClient

logger = logging.getLogger(__name__)

# ── 默认 schema 路径（相对于 anomaly_flow_pipeline/） ───
_DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "model-schema.json"


# ═══════════════════════════════════════════════════════════
# 提示词模板（场景无关，引用 Schema 定义）
# ═══════════════════════════════════════════════════════════

STEPS_GENERATION_PROMPT = """你是一个 APP 操作流程数据生成专家。根据用户操作轨迹数据，生成符合建模规范的操作步骤。

## Action 描述规范
每条 action 应包含三个层次：

1. **用户操作**：用户在[当前页面]上[操作哪个控件/区域]
2. **页面布局**：当前页面的静态 UI 结构（来自 ui_summary，不受用户操作影响的部分，如顶部导航栏、底部Tab、搜索框等）
3. **状态变化**：操作前后的页面空间/内容变化

格式：
```
用户在[页面]上[操作]
页面布局是：[页面静态布局描述]
初始状态是：[操作前页面空间/内容状态]
最终状态是：[操作后页面空间/内容状态]
```

示例:
- ✅ "用户在首页搜索框输入'华为手机'
    页面布局是：顶部搜索栏、底部导航栏、中间商品推荐区域
    初始状态是：搜索框内容为'海尔洗衣机'
    最终状态是：搜索框内容更新为'华为手机'"
- ✅ "用户在搜索结果页点击筛选按钮
    页面布局是：顶部搜索栏、底部导航栏、右侧筛选按钮
    初始状态是：搜索结果页展示全部商品列表
    最终状态是：弹出筛选菜单面板"
- ✅ "用户点击'提交订单'按钮
    页面布局是：订单确认页、收货地址区域、商品清单、底部提交按钮
    初始状态是：订单确认页展示商品信息和¥2999
    最终状态是：页面跳转至支付收银台"

## 输出步骤的字段规范（来自建模 Schema）

{step_schema_text}

## 用户操作轨迹

{step_data_text}

## 要求
1. 每个 stepData 条目对应一个输出步骤，按 order 顺序排列
2. action 必须包含上述三个层次（操作、布局、状态变化）
3. 页面布局来自 ui_summary 中对页面结构的描述，是不受操作影响的静态部分
4. 初始状态和最终状态描述的是受操作影响的空间/内容变化
5. 保留原始轨迹中的异常状态信息（如加载失败、错误提示等异常内容必须保留）
6. 保持步骤之间的因果连贯性：后一步应能从前一步的结果自然推导
7. 严格遵循输出字段规范中的类型约束

## 输出格式
直接输出 JSON 数组，不要 markdown 包裹或额外说明：
[
  {{"order": 1, "action": "..."}},
  ...
]"""


STEPS_COMPRESS_PROMPT = """你是一个 APP 操作流程编辑专家。合并相邻的**同页面**操作步骤，使流程更简洁，同时保留页面布局信息。

## Action 描述规范
每条 action 应包含三个层次：

1. **用户操作**：用户在[当前页面]上依次[操作1]、[操作2]…
2. **页面布局**：当前页面的静态 UI 结构（不受操作影响的部分，如顶部导航栏、底部Tab等）
3. **状态变化**：操作前后的页面空间/内容变化

### 单步格式
```
用户在[页面]上[操作]
页面布局是：[页面静态布局描述]
初始状态是：[操作前页面空间/内容状态]
最终状态是：[操作后页面空间/内容状态]
```

### 合并后格式
```
用户在[页面]上依次[操作1]、[操作2]…
页面布局是：[页面静态布局描述（不受操作影响）]
初始状态是：[合并前第一步的初始页面状态]
最终状态是：[合并后最后一步的最终页面状态]
```

## 合并规则
1. 识别相邻步骤是否发生在**同一个页面**上（根据 action 和原始 ui_summary 语义判断）
2. 如果是，合并为 1 个步骤，按上述"合并后格式"输出
3. **页面布局使用原始 ui_summary 中的页面结构描述，不丢失布局信息**
4. 如果相邻步骤发生在**不同页面**，保持独立，不合并
5. 合并后保留异常状态信息

## 示例

输入:
  Step 1: "用户在首页搜索框输入'华为手机'
    页面布局是：顶部搜索栏、底部导航栏
    初始状态是：搜索框内容为'海尔洗衣机'
    最终状态是：搜索框内容更新为'华为手机'"
  原始 ui_summary: "京东首页，顶部有搜索框，当前内容为"海尔洗衣机"。搜索框右侧有搜索按钮。页面展示多种商品推荐。"
  Step 2: "用户点击搜索按钮
    页面布局是：顶部搜索栏、底部导航栏
    初始状态是：搜索框内容为'华为手机'
    最终状态是：页面跳转至搜索结果页"
  原始 ui_summary: "页面顶部有搜索框，右侧有搜索按钮。页面主体显示商品推荐。底部为导航栏。"
输出:
  [{"order": 1, "action": "用户在首页依次在搜索框输入'华为手机'并点击搜索按钮\n页面布局是：顶部搜索栏、底部导航栏、中间商品推荐区域\n初始状态是：搜索框内容为'海尔洗衣机'\n最终状态是：页面跳转至搜索结果页"}]

## 待处理的步骤
{steps_text}

## 原始轨迹数据（参考页面布局用）
{utg_context}

## 输出
直接输出合并后的 JSON 数组（order 重新编号从 1 开始），不要 markdown 包裹：
[
  {{"order": 1, "action": "..."}},
  ...
]"""


ENTITY_EXTRACTION_PROMPT = """你是一个 APP 数据抽取专家。从操作步骤中提取关键业务实体信息，填充到建模模板的数据主题中。

## 实体的字段规范（来自建模 Schema）

{entity_schema_text}

## 操作步骤

{steps_text}

## 要求
1. 分析所有步骤中提到的具体业务实体（商品、服务、内容、商品等）
2. 从步骤描述中提取实体的具体属性值，严格遵循字段规范中的类型（string / number / price / enum 等）
3. 步骤中未提及的字段设为 null
4. 如果步骤中没有可提取的业务实体，返回空数组 []
5. 不捏造步骤中不存在的数据
6. 严格遵循输出 JSON 结构，不要增减字段

## 输出格式
直接输出 JSON 数组，不要 markdown 包裹：
[
  {{
    "instanceId": "entity_from_steps",
    "imageUrl": null,
    "values": {{ ... }}
  }}
]"""


# ═══════════════════════════════════════════════════════════
# 主类
# ═══════════════════════════════════════════════════════════

class FlowConverter:
    """
    LLM 驱动的 Flow 内容生成器。

    不再依赖硬编码的页面关键词/品牌列表/价格正则等场景特定规则。
    所有内容填充决策由 LLM 根据 Schema 定义 + 实际轨迹数据做出。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        # 步骤生成用低 temperature 确保一致性
        self.llm_steps = LLMClient(
            api_key=api_key,
            api_url=api_url,
            model=model,
            temperature=0.0,
            max_tokens=4096,
        )
        # 实体提取可略高 temperature 鼓励多样性
        self.llm_entity = LLMClient(
            api_key=api_key,
            api_url=api_url,
            model=model,
            temperature=0.1,
            max_tokens=1024,
        )

    # ── 主入口 ─────────────────────────────────────────────

    def convert(
        self,
        utg_path: str,
        template_path: str,
        output_path: str,
        schema_path: Optional[str] = None,
        mode: str = "replace",
        enable_screen_key: bool = True,
        enable_data_binding: bool = True,
        compress_steps: bool = False,
    ) -> Dict[str, Any]:
        """
        LLM 驱动转换：injected UTG + 模板 + Schema → Flow JSON。

        Args:
            utg_path: 注入异常后的 utg_info.json 路径
            template_path: Flow 模板 JSON 路径
            output_path: 输出路径
            schema_path: model-schema.json 路径（默认 schema/model-schema.json）
            mode: 保留参数（兼容旧调用方，实际行为已简化为 replace）
            enable_screen_key: 保留参数（兼容旧调用方）
            enable_data_binding: 保留参数（兼容旧调用方）
            compress_steps: 是否合并相邻同页面步骤（LLM 驱动，按 action 范式凝练）

        Returns:
            {"success": bool, "output_path": str, "step_count": int, "error": str|None}
        """
        result = {
            "success": False,
            "output_path": output_path,
            "step_count": 0,
            "error": None,
        }

        try:
            utg_data = self._load_json(utg_path)
            template = self._load_json(template_path)
            schema = self._load_schema(schema_path)

            # Step 0: 提取有效步骤
            utg_steps = self._get_valid_steps_from_utg(utg_data)
            if not utg_steps:
                result["error"] = "utg_info.json 中没有有效的 ui_summary 步骤"
                return result

            logger.info(f"UTG 有效步骤: {len(utg_steps)}")

            # 构建 merged 骨架（deepcopy 模板保留 events/topics/ui/baselineMapping）
            merged = deepcopy(template)
            self._init_main_flow(merged, utg_data)

            # ── Step 1: LLM 生成 mainFlow.steps ────────────
            logger.info(">>> LLM 生成 steps ...")
            step_schema_text = self._get_step_schema_text(schema)
            new_steps = self._llm_generate_steps(
                utg_steps, step_schema_text, utg_data.get("query", "")
            )
            if not new_steps:
                result["error"] = "LLM 生成 steps 失败"
                return result

            merged["mainFlow"]["steps"] = new_steps
            logger.info(f"  LLM 生成 steps: {len(new_steps)} 步")

            # ── Step 1.5: 可选 — 合并相邻同页面步骤 ─────────
            if compress_steps and len(new_steps) > 1:
                logger.info(">>> 合并相邻同页面步骤 ...")
                compressed = self._llm_compress_steps(new_steps, utg_steps)
                if compressed and len(compressed) < len(new_steps):
                    merged["mainFlow"]["steps"] = compressed
                    logger.info(f"  合并后: {len(new_steps)} → {len(compressed)} 步")
                elif compressed:
                    logger.info(f"  无需合并（仍为 {len(new_steps)} 步）")
                else:
                    logger.info("  合并失败，使用原始步骤")

            # ── Step 2: LLM 提取业务实体 → topics.mockInstances ──
            if enable_data_binding:
                logger.info(">>> LLM 提取业务实体 ...")
                entity_schema_text = self._get_entity_schema_text(schema, template)
                mock_instances = self._llm_extract_entities(
                    new_steps, entity_schema_text, utg_data.get("query", "")
                )
                if mock_instances:
                    self._update_merged_mock_instances(merged, mock_instances)
                    result["bound_mock_id"] = mock_instances[0].get("instanceId")
                    logger.info(f"  提取实体: {len(mock_instances)} 个")
                else:
                    logger.info("  实体提取: 无法提取或无实体信息")

            # ── Step 3: 按模板字段过滤输出 ─────────────────
            step_fields = self._get_template_step_fields(template)
            if step_fields:
                merged["mainFlow"]["steps"] = self._filter_step_fields(
                    merged["mainFlow"].get("steps", []),
                    step_fields,
                )

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

    # ── LLM 步骤生成 ─────────────────────────────────────

    def _llm_generate_steps(
        self, utg_steps: List[Dict], step_schema_text: str, query: str
    ) -> Optional[List[Dict]]:
        """
        LLM 生成 mainFlow.steps。

        输入：UTG stepData（含已注入异常的 ui_summary）
        输出：[{"order": int, "action": str, ...}]
        """
        # 构建步骤文本
        lines = []
        for s in utg_steps:
            summary = (s.get("ui_summary") or "").strip()
            thought = (s.get("thought") or "").strip()
            if summary:
                line = f"Step {s['order']}: {summary[:300]}"
                if thought:
                    line += f"\n   意图: {thought[:100]}"
                lines.append(line)
        if not lines:
            return None

        step_data_text = "\n\n".join(lines)[:4000]

        prompt = STEPS_GENERATION_PROMPT.format(
            step_schema_text=step_schema_text,
            step_data_text=step_data_text,
        )

        try:
            raw = self.llm_steps.chat(prompt)
            logger.debug(f"  LLM raw[:300]: {raw[:300]}")
            parsed = self.llm_steps.extract_json(raw)

            if parsed is None:
                logger.warning("  LLM 返回无法解析的内容")
                return None

            # 兼容两种格式：直接返回数组，或包裹在 {steps: [...]} / {mainFlow: {steps: [...]}}
            if not isinstance(parsed, list):
                steps = parsed.get("steps") or parsed.get("mainFlow", {}).get("steps")
                if isinstance(steps, list):
                    parsed = steps
                else:
                    logger.warning(f"  LLM 返回非数组且无法提取 steps: {type(parsed)}")
                    return None

            if not parsed:
                logger.warning("  LLM 返回空数组")
                return None

            # 确保 order 连续且从 1 开始
            for i, step in enumerate(parsed):
                step["order"] = i + 1
                # 确保 action 非空
                if not isinstance(step, dict) or not step.get("action", "").strip():
                    logger.warning(f"  Step {i+1}: action 无效，跳过")
                    return None

            logger.info(f"  LLM 生成成功: {len(parsed)} 步")
            return parsed

        except Exception as e:
            logger.warning(f"  LLM 生成 steps 失败: {e}")
            return None

    # ── LLM 步骤合并（同页面压缩） ───────────────────────

    def _llm_compress_steps(
        self, steps: List[Dict], utg_steps: Optional[List[Dict]] = None
    ) -> Optional[List[Dict]]:
        """
        合并相邻同页面步骤，保留页面布局信息。

        输入：生成的 steps + 原始 UTG 步骤（含 ui_summary 页面布局描述）
        输出：合并后 steps（order 重新编号），或 None 表示合并失败
        """
        # 构建已生成 steps 的文本
        lines = []
        for s in steps:
            action = (s.get("action") or "").strip()
            if action:
                lines.append(f"  Step {s['order']}: {action[:300]}")
        if not lines:
            return None
        steps_text = "\n".join(lines)

        # 构建原始 UTG 上下文（含 ui_summary 页面布局信息）
        utg_context = ""
        if utg_steps:
            ctx_lines = []
            for s in utg_steps:
                summary = (s.get("ui_summary") or "").strip()
                if summary:
                    ctx_lines.append(
                        f"  Step {s['order']} ui_summary: {summary[:200]}"
                    )
            if ctx_lines:
                utg_context = "\n".join(ctx_lines)

        prompt = STEPS_COMPRESS_PROMPT.format(
            steps_text=steps_text,
            utg_context=utg_context or "（无原始轨迹数据）",
        )

        try:
            raw = self.llm_steps.chat(prompt)
            parsed = self.llm_steps.extract_json(raw)

            if parsed is None:
                return None

            # 兼容两种格式
            if not isinstance(parsed, list):
                steps_data = parsed.get("steps") or parsed.get("mainFlow", {}).get("steps")
                if isinstance(steps_data, list):
                    parsed = steps_data
                else:
                    return None

            if not parsed:
                return None

            # 重新编号
            for i, step in enumerate(parsed):
                step["order"] = i + 1
                if not isinstance(step, dict) or not step.get("action", "").strip():
                    return None

            return parsed

        except Exception as e:
            logger.warning(f"  合并步骤失败: {e}")
            return None

    # ── LLM 实体提取 ─────────────────────────────────────

    def _llm_extract_entities(
        self, steps: List[Dict], entity_schema_text: str, query: str
    ) -> Optional[List[Dict]]:
        """
        LLM 从步骤中提取业务实体 → mockInstances。

        输入：已生成的 steps + 模板 topics/fields 定义
        输出：[{"instanceId": str, "imageUrl": null, "values": {...}}]
        """
        if not entity_schema_text.strip():
            logger.info("  实体提取: 模板无 topics/fields 定义，跳过")
            return None

        # 构建步骤摘要
        lines = []
        for s in steps:
            action = (s.get("action") or "").strip()
            if action:
                lines.append(f"Step {s['order']}: {action[:200]}")
        steps_text = "\n".join(lines)[:3000]

        prompt = ENTITY_EXTRACTION_PROMPT.format(
            entity_schema_text=entity_schema_text,
            steps_text=steps_text,
        )

        try:
            raw = self.llm_entity.chat(prompt)
            parsed = self.llm_entity.extract_json(raw)

            if not isinstance(parsed, list) or not parsed:
                return None

            # 确保每个实例有 instanceId 和 values
            valid = []
            for inst in parsed:
                if not isinstance(inst, dict):
                    continue
                inst.setdefault("instanceId", "entity_from_steps")
                inst.setdefault("imageUrl", None)
                if "values" not in inst:
                    continue
                valid.append(inst)

            return valid if valid else None

        except Exception as e:
            logger.warning(f"  LLM 实体提取失败: {e}")
            return None

    # ── Schema 文本构建 ──────────────────────────────────

    def _get_step_schema_text(self, schema: Dict) -> str:
        """从 schema 中提取 FlowStep 字段定义文本"""
        try:
            flow_step = schema.get("definitions", {}).get("FlowStep", {})
            props = flow_step.get("properties", {})
            required = flow_step.get("required", [])
            lines = []
            for field_name, field_def in props.items():
                is_required = "（必填）" if field_name in required else "（可选）"
                desc = field_def.get("description", "")
                ftype = field_def.get("type", "string")
                lines.append(f"- {field_name} ({ftype}){is_required}: {desc}")
            return "\n".join(lines) if lines else "- order (integer)（必填）: 步骤序号\n- action (string)（必填）: 用户动作或系统行为描述"
        except Exception:
            return "- order (integer)（必填）: 步骤序号\n- action (string)（必填）: 用户动作或系统行为描述"

    def _get_entity_schema_text(self, schema: Dict, template: Dict) -> str:
        """从 schema + 模板中提取 topics/fields 定义文本"""
        try:
            # 从模板获取实际的 topics/fields 结构
            topics = template.get("topics", [])
            if not topics:
                return ""

            lines = []
            for topic in topics:
                topic_name = topic.get("name", "")
                topic_id = topic.get("id", "")
                lines.append(f"\n## 数据主题: {topic_name} ({topic_id})")
                fields = topic.get("fields", [])
                for field in fields:
                    fid = field.get("id", "")
                    fname = field.get("name", "")
                    ftype = field.get("type", "string")
                    required = "（必填）" if field.get("required") else "（可选）"
                    desc = field.get("description", "")
                    enum_vals = field.get("enumValues")
                    unit = field.get("unit", "")
                    extra = f" 单位: {unit}" if unit else ""
                    if enum_vals:
                        extra += f" 枚举值: {', '.join(enum_vals)}"
                    lines.append(
                        f"  - {fid} ({ftype}){required}: {fname}{' - ' + desc if desc else ''}{' | ' + extra if extra else ''}"
                    )
            return "\n".join(lines) if lines else ""

        except Exception as e:
            logger.warning(f"  构建实体 schema 文本失败: {e}")
            return ""

    # ── 辅助方法 ──────────────────────────────────────────

    @staticmethod
    def _load_schema(schema_path: Optional[str]) -> Dict:
        """加载 model-schema.json，失败时返回空 dict"""
        if schema_path:
            p = Path(schema_path)
        else:
            p = _DEFAULT_SCHEMA_PATH
        if p.exists():
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"加载 schema 失败 ({p}): {e}")
        else:
            logger.warning(f"Schema 文件不存在: {p}")
        return {}

    @staticmethod
    def _init_main_flow(merged: Dict, utg_data: Dict):
        """初始化 mainFlow 元数据字段"""
        if "mainFlow" not in merged:
            merged["mainFlow"] = {"id": "flow-from-utg", "steps": []}

        merged["mainFlow"]["id"] = "flow-from-utg"
        merged["mainFlow"]["name"] = utg_data.get("query", "操作流程")
        merged["mainFlow"]["description"] = utg_data.get("query", "")
        merged["mainFlow"]["precondition"] = (
            f"用户已登录，{utg_data.get('appName', 'APP')}首页正常加载"
        )

    @staticmethod
    def _get_valid_steps_from_utg(utg_data: Dict) -> List[Dict]:
        """从 utg_info.json 中提取有效步骤"""
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
                "thought": item.get("thought", ""),
            })
        return valid

    @staticmethod
    def _update_merged_mock_instances(merged: Dict, new_instances: List[Dict]):
        """替换模板中所有 topics/fields 下的 mockInstances"""
        if not new_instances:
            return

        replaced = 0
        for topic in merged.get("topics", []):
            if "mockInstances" in topic:
                topic["mockInstances"] = new_instances
                replaced += 1
            for field in topic.get("fields", []):
                if "mockInstances" in field:
                    field["mockInstances"] = new_instances
                    replaced += 1

        if replaced > 0:
            logger.info(f"  topics mockInstances 已更新（{len(new_instances)} 实例, {replaced} 处）")

    @staticmethod
    def _get_template_step_fields(template: Dict) -> List[str]:
        """获取模板步骤字段列表，用于约束输出字段"""
        steps = template.get("mainFlow", {}).get("steps", [])
        if not steps:
            return ["order", "action"]

        fields = list(steps[0].keys())
        for required in ("order", "action"):
            if required not in fields:
                fields.append(required)
        return fields

    @staticmethod
    def _filter_step_fields(steps: List[Dict], fields: List[str]) -> List[Dict]:
        """仅保留模板声明的步骤字段"""
        return [
            {field: step[field] for field in fields if field in step}
            for step in steps
        ]

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
