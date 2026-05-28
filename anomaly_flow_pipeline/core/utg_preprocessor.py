"""
utg_preprocessor.py — UTG 数据预处理器（Phase 0）

在异常注入之前，把原始 utg_info.json 的质量问题修复到可接受水平。

三阶段流程：
  1. 去重合并（Rule-based）: 连续相同页面指纹的步骤合并
  2. 动作驱动重写（LLM）: 页面状态快照 → "用户动作→系统响应" 格式
  3. 数据对齐（LLM）: 商品名、价格跨步骤一致性修正
  4. 页面补齐（Rule + LLM）: 补充 ProductDetail、OrderDetail 等关键缺失页面

独立模块，仅依赖 llm_client 和 utg_loader。
"""

import json
import logging
import re
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from .llm_client import LLMClient
from .utg_loader import UTGLoader, UTGStep

logger = logging.getLogger(__name__)

# ── Prompt 模板 ──────────────────────────────────────────

ACTION_REWRITE_PROMPT = """你是一个 App 操作步骤描述优化专家。你的任务是将"页面状态快照"改写为"用户动作 → 系统响应"格式的动作驱动描述。

## 原始输入
- 当前页面描述: {ui_summary}
- 用户操作意图: {thought}
- 操作类型: {action_type}

## 改写要求
1. 格式: "用户[做了什么操作]，系统[如何响应]，当前页面展示[关键UI信息]"
2. 语言自然口语化，模拟真实用户的视角
3. 聚焦页面核心功能信息，省略次要装饰性描述
4. 保留所有重要的数据（价格、商品名、数量等）
5. 每步一句或两句，不超过80字
6. 不要使用开发/测试术语（exception, error, null, undefined等）
7. 不要假设用户看不到的信息

## 示例
原始: "京东首页，顶部有搜索框，当前内容为'海尔洗衣机'。搜索框右侧有搜索按钮。页面展示多种商品推荐..."
改写: "用户在首页搜索框输入'海尔洗衣机'，系统跳转到搜索结果页，展示华为手机相关商品推荐列表"

原始: "页面展示筛选选项，包含服务/折扣、价格区间、配送至、品牌及全部分类。价格区间包含最低价、最高价和价格选项..."
改写: "用户打开筛选面板设置价格上限为3000元，系统展示服务/折扣、品牌等筛选选项，底部有确定按钮显示'1400+件商品'"

## 输出
只输出改写后的文本，不要包含其他内容，不要加引号包裹。"""

DATA_ALIGN_PROMPT = """你是一个 App 测试数据一致性专家。检查以下操作序列中所有步骤的 UI 描述，找出数据不一致问题并修正。

## 用户原始查询
{query}

## 操作序列步骤
{steps_text}

## 检查要点
1. 搜索的商品名称在各步骤中是否一致
2. 同一商品的价格在各步骤中是否一致
3. 购物车数量等数据是否逻辑自洽
4. 描述与实际语义是否匹配

## 输出格式（只输出 JSON）
{{
  "issues": [
    {{
      "step_index": <int>,
      "field": "商品名称|价格|数量|其他",
      "original": "<当前不一致的值>",
      "corrected": "<修正后的值>",
      "reason": "<修正原因>"
    }}
  ],
  "consistency_summary": "<整体一致性评估，一句话>"
}}

如果没有发现问题，返回 {{"issues": [], "consistency_summary": "数据一致"}}"""

PAGE_COMPLETE_PROMPT = """你是一个 App 操作流程专家。分析以下操作序列，判断是否需要补充关键页面。

## 操作序列步骤
{steps_text}

## 预期购物流程页面拓扑
{expected_topology}

## 要求
1. 对照预期拓扑，找出缺失的关键页面
2. 如果需要补充，为每个缺失页面生成一段动作驱动描述
3. 补充步骤应插入到最合理的相邻位置

## 输出格式（只输出 JSON）
{{
  "missing_pages": [
    {{
      "page_name": "<缺失页面名称>",
      "insert_after_step": <int, 在此步骤后插入>,
      "action_description": "<动作驱动描述，格式: 用户[动作]，系统[响应]，页面展示[关键信息]>"
    }}
  ]
}}

如果无缺失，返回 {{"missing_pages": []}}"""


def _compute_page_fingerprint(ui_summary: str, n_chars: int = 50) -> str:
    """计算页面指纹：取 ui_summary 前 n_chars 个字符，去除非中文字符和空白"""
    if not ui_summary:
        return ""
    # 取前 n_chars 并清理
    raw = ui_summary.strip()[:n_chars]
    # 提取关键内容（去掉标点符号和空白）
    key = re.sub(r'[\s,，。！？、；：""''【】《》（）\!\?\.\,\;\:\'\"\(\)\[\]\{\}]', '', raw)
    return key[:30]


def _get_action_type_label(action_type: str) -> str:
    """从 action_type 推断用户操作类型"""
    if not action_type:
        return "点击"
    at = action_type.lower()
    if "set_text" in at or "input" in at:
        return "输入"
    if "click" in at:
        return "点击"
    if "back" in at:
        return "返回"
    if "swipe" in at or "scroll" in at:
        return "滑动"
    if "clarify" in at:
        return "确认"
    return "点击"


class UTGPreprocessor:
    """UTG 数据预处理器（Phase 0）"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.llm = LLMClient(
            api_key=api_key,
            api_url=api_url,
            model=model,
            temperature=0.1,
            max_tokens=1024,
        )
        self.llm_align = LLMClient(
            api_key=api_key,
            api_url=api_url,
            model=model,
            temperature=0.1,
            max_tokens=2048,
        )

    # ── Phase 0-1: 去重合并（Rule-based） ────────────────

    def deduplicate(self, loader: UTGLoader) -> Tuple[List[UTGStep], Dict]:
        """
        基于页面指纹合并连续重复步骤。

        Returns:
            (去重后的有效步骤列表, 去重统计信息)
        """
        valid = loader.get_valid_steps()
        if not valid:
            return [], {"removed": 0, "total_before": 0, "total_after": 0}

        stat = {"total_before": len(valid), "removed": 0, "merged_groups": []}

        deduped = []
        last_fingerprint = None
        current_group = []

        for step in valid:
            fp = _compute_page_fingerprint(step.ui_summary)
            if fp and fp == last_fingerprint:
                current_group.append(step)
                stat["removed"] += 1
            else:
                if current_group:
                    # 保留组内第一条
                    deduped.append(current_group[0])
                    if len(current_group) > 1:
                        stat["merged_groups"].append(
                            f"Step{current_group[0].step_id}~Step{current_group[-1].step_id}"
                        )
                current_group = [step]
                last_fingerprint = fp

        # 处理最后一组
        if current_group:
            deduped.append(current_group[0])
            if len(current_group) > 1:
                stat["merged_groups"].append(
                    f"Step{current_group[0].step_id}~Step{current_group[-1].step_id}"
                )

        stat["total_after"] = len(deduped)
        logger.info(
            f"  去重: {stat['total_before']} → {stat['total_after']} "
            f"(移除 {stat['removed']} 步)"
        )
        if stat["merged_groups"]:
            logger.info(f"  合并组: {', '.join(stat['merged_groups'])}")

        return deduped, stat

    # ── Phase 0-2: 动作驱动重写（LLM） ────────────────────

    def rewrite_to_action_driven(
        self, steps: List[UTGStep], batch_size: int = 5
    ) -> Tuple[List[str], Dict]:
        """
        将每步的 ui_summary 重写为动作驱动描述。

        Returns:
            (重写后的 ui_summary 列表, 重写统计)
        """
        stat = {"total": len(steps), "success": 0, "failed": 0, "skipped": 0}
        rewritten = []

        for i, step in enumerate(steps):
            ui_summary = step.ui_summary.strip()
            if not ui_summary:
                rewritten.append(ui_summary)
                stat["skipped"] += 1
                continue

            action_label = _get_action_type_label(step.action_type)
            thought = step.thought.strip() if step.thought else action_label

            prompt = ACTION_REWRITE_PROMPT.format(
                ui_summary=ui_summary[:800],
                thought=thought[:200],
                action_type=action_label,
            )

            try:
                result = self.llm.chat(prompt).strip()
                # 清理可能的引号包裹
                result = result.strip('"\'')
                if result:
                    rewritten.append(result)
                    stat["success"] += 1
                    logger.debug(f"  Step {step.step_id}: ✓ 重写成功 ({len(result)} chars)")
                else:
                    rewritten.append(ui_summary)
                    stat["skipped"] += 1
            except Exception as e:
                logger.warning(f"  Step {step.step_id}: LLM 重写失败: {e}")
                rewritten.append(ui_summary)
                stat["failed"] += 1

        logger.info(
            f"  重写: {stat['success']} 成功, {stat['failed']} 失败, "
            f"{stat['skipped']} 跳过"
        )
        return rewritten, stat

    # ── Phase 0-3: 数据对齐（LLM） ────────────────────────

    def align_data(
        self, loader: UTGLoader, steps: List[UTGStep], rewritten: List[str]
    ) -> Tuple[List[str], Dict]:
        """
        跨步骤数据一致性检查和修正。

        Args:
            loader: UTG 数据加载器
            steps: 当前有效步骤列表（去重后）
            rewritten: 当前重写后的 ui_summary 列表

        Returns:
            (修正后的 ui_summary 列表, 修正详情)
        """
        result = {"issues_found": 0, "fixes": []}

        query = loader._raw.get("query", "")

        # 构建步骤文本供 LLM 分析
        steps_text = ""
        for i, (step, rw) in enumerate(zip(steps, rewritten)):
            steps_text += f"Step {i} (stepId={step.step_id}): {rw[:300]}\n\n"

        prompt = DATA_ALIGN_PROMPT.format(
            query=query[:300], steps_text=steps_text
        )

        try:
            raw = self.llm_align.chat(prompt)
            parsed = self.llm_align.extract_json(raw)
            issues = parsed.get("issues", [])
            result["issues_found"] = len(issues)
            result["consistency_summary"] = parsed.get("consistency_summary", "")

            if not issues:
                logger.info("  数据对齐: 未发现问题")
                return rewritten, result

            # 应用修正
            for issue in issues:
                step_idx = issue.get("step_index")
                original = issue.get("original", "")
                corrected = issue.get("corrected", "")

                if step_idx is None or step_idx >= len(rewritten):
                    continue
                if not original or not corrected:
                    continue

                old_text = rewritten[step_idx]
                # 只替换第一次出现的 original
                if original in old_text:
                    new_text = old_text.replace(original, corrected, 1)
                    rewritten[step_idx] = new_text
                    result["fixes"].append({
                        "step_index": step_idx,
                        "field": issue.get("field", ""),
                        "original": original,
                        "corrected": corrected,
                    })
                    logger.info(
                        f"  Step {step_idx}: {issue.get('field', '')} "
                        f"'{original}' → '{corrected}'"
                    )
                else:
                    logger.debug(
                        f"  Step {step_idx}: 未找到 '{original}'，跳过修正"
                    )

        except Exception as e:
            logger.warning(f"  数据对齐 LLM 调用失败: {e}")

        return rewritten, result

    # ── Phase 0-4: 页面补齐 ──────────────────────────────

    def complete_pages(
        self,
        loader: UTGLoader,
        steps: List[UTGStep],
        rewritten: List[str],
        template_path: Optional[str] = None,
    ) -> Tuple[List[str], Dict]:
        """
        检查并补充缺失的关键页面（如 ProductDetail、OrderDetail）。

        Args:
            loader: UTG 数据加载器
            steps: 去重后的步骤列表
            rewritten: 当前 ui_summary 列表
            template_path: 模板文件路径（用于获取预期页面拓扑）

        Returns:
            (补充后的 ui_summary 列表, 补充详情)
        """
        result = {"inserted": [], "total_before": len(rewritten)}

        # 构建预期页面拓扑
        expected_topology = self._get_expected_topology(template_path)

        # 构建当前步骤文本
        steps_text = ""
        for i, rw in enumerate(rewritten):
            steps_text += f"Step {i}: {rw[:200]}\n"

        prompt = PAGE_COMPLETE_PROMPT.format(
            steps_text=steps_text,
            expected_topology=json.dumps(expected_topology, ensure_ascii=False),
        )

        try:
            raw = self.llm_align.chat(prompt)
            parsed = self.llm_align.extract_json(raw)
            missing = parsed.get("missing_pages", [])

            if not missing:
                logger.info("  页面补齐: 无缺失页面")
                return rewritten, result

            # 从后往前插入，避免索引偏移
            missing.sort(key=lambda x: x.get("insert_after_step", 0), reverse=True)

            for page in missing:
                insert_after = page.get("insert_after_step", 0)
                action_desc = page.get("action_description", "")
                page_name = page.get("page_name", "")

                if insert_after < 0:
                    insert_after = 0
                if insert_after >= len(rewritten):
                    rewritten.append(action_desc)
                else:
                    rewritten.insert(insert_after + 1, action_desc)

                result["inserted"].append({
                    "page_name": page_name,
                    "insert_after_step": insert_after,
                    "action_description": action_desc,
                })
                logger.info(f"  + 在 Step {insert_after} 后插入 '{page_name}'")

        except Exception as e:
            logger.warning(f"  页面补齐 LLM 调用失败: {e}")

        result["total_after"] = len(rewritten)
        return rewritten, result

    def _get_expected_topology(self, template_path: Optional[str] = None) -> List[str]:
        """从模板获取预期的页面拓扑"""
        default_topology = [
            "home", "search", "searchResult", "productDetail",
            "cart", "checkout", "payment", "orderDetail"
        ]
        if not template_path:
            return default_topology

        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                template = json.load(f)
            return template.get("baselineMapping", {}).get(
                "screenKeys", default_topology
            )
        except Exception:
            return default_topology

    # ── 全流程（Phase 0） ─────────────────────────────────

    def run(
        self,
        utg_path: str,
        template_path: Optional[str] = None,
        output_path: Optional[str] = None,
        skip_dedup: bool = False,
        skip_rewrite: bool = False,
        skip_align: bool = False,
        skip_complete: bool = False,
    ) -> Dict[str, Any]:
        """
        执行完整的预处理流程。

        Args:
            utg_path: utg_info.json 路径
            template_path: 模板 JSON 路径（可选，用于补齐参考）
            output_path: 输出路径（可选）
            skip_dedup: 跳过去重
            skip_rewrite: 跳过动作重写
            skip_align: 跳过数据对齐
            skip_complete: 跳过页面补齐

        Returns:
            {
                "success": bool,
                "modified_utg": dict,
                "phases": {
                    "dedup": {...},
                    "rewrite": {...},
                    "align": {...},
                    "complete": {...},
                },
                "steps_before": int,
                "steps_after": int,
                "output_path": str|None,
            }
        """
        result = {
            "success": False,
            "modified_utg": None,
            "phases": {},
            "steps_before": 0,
            "steps_after": 0,
            "error": None,
        }

        try:
            loader = UTGLoader(utg_path)
            result["steps_before"] = loader.valid_count
            logger.info(f"Phase 0 开始: {loader.valid_count} 有效步骤")

            # Phase 0-1: 去重
            if not skip_dedup:
                deduped_steps, dedup_stat = self.deduplicate(loader)
                result["phases"]["dedup"] = dedup_stat
            else:
                deduped_steps = loader.get_valid_steps()
                result["phases"]["dedup"] = {
                    "skipped": True,
                    "total_before": len(deduped_steps),
                    "total_after": len(deduped_steps),
                }

            # 初始 rewritten 来自各步的 ui_summary
            rewritten = [s.ui_summary for s in deduped_steps]

            # Phase 0-2: 动作驱动重写
            if not skip_rewrite:
                rewritten, rewrite_stat = self.rewrite_to_action_driven(deduped_steps)
                result["phases"]["rewrite"] = rewrite_stat
            else:
                result["phases"]["rewrite"] = {"skipped": True}

            # Phase 0-3: 数据对齐
            if not skip_align:
                rewritten, align_stat = self.align_data(
                    loader, deduped_steps, rewritten
                )
                result["phases"]["align"] = align_stat
            else:
                result["phases"]["align"] = {"skipped": True}

            # Phase 0-4: 页面补齐
            if not skip_complete:
                rewritten, complete_stat = self.complete_pages(
                    loader, deduped_steps, rewritten, template_path
                )
                result["phases"]["complete"] = complete_stat
            else:
                result["phases"]["complete"] = {"skipped": True}

            # 组装修改后 utg
            modified_utg = self._build_modified_utg(
                loader, deduped_steps, rewritten
            )
            result["modified_utg"] = modified_utg
            result["steps_after"] = len(rewritten)
            result["success"] = True

            if output_path:
                self.save(modified_utg, output_path)
                result["output_path"] = output_path
                logger.info(f"  ✓ 已保存: {output_path}")

            logger.info(
                f"Phase 0 完成: {result['steps_before']} → {result['steps_after']} 步"
            )
            return result

        except Exception as e:
            logger.exception("Phase 0 预处理失败")
            result["error"] = str(e)
            return result

    def _build_modified_utg(
        self,
        loader: UTGLoader,
        valid_steps: List[UTGStep],
        rewritten: List[str],
    ) -> Dict:
        """组装修改后的 utg_info.json"""
        modified = deepcopy(loader._raw)

        # 清空原始 stepData，重新构建
        new_step_data = []

        for i, step in enumerate(valid_steps):
            ui_summary = rewritten[i] if i < len(rewritten) else step.ui_summary
            new_step_data.append({
                "stepId": step.step_id,
                "action_type": step.action_type,
                "thought": step.thought,
                "ui_summary": ui_summary,
                "cost_time": step.cost_time,
                "type": step.step_type,
                "imageId": step.image_id,
            })

        # 添加被去重跳过的步骤不展示在最终数据中
        # 保留全量 stepData 但标记去重的步骤
        # 更好的方式：保留所有 step，但将去重的步骤 ui_summary 设为 "（已合并）"
        # 考虑到 downstream 只需要有 ui_summary 的步骤，这里直接替换有效步骤的 ui_summary
        # 非有效步骤（home/end/start）保持不变

        # 更简单的做法：只替换有效的 step 的 ui_summary
        step_data_map = {}
        for item in modified.get("stepData", []):
            sid = str(item.get("stepId", ""))
            step_data_map[sid] = item

        # 用重写后的内容更新
        for i, step in enumerate(valid_steps):
            ui_summary = rewritten[i] if i < len(rewritten) else step.ui_summary
            if step.step_id in step_data_map:
                step_data_map[step.step_id]["ui_summary"] = ui_summary

        # 对于被去重合并掉的步骤（不在 valid_steps 但在原始 stepData 中），保留但标记
        valid_ids = {s.step_id for s in valid_steps}
        for item in modified.get("stepData", []):
            sid = str(item.get("stepId", ""))
            if sid not in valid_ids and item.get("ui_summary", "").strip():
                item["ui_summary"] = "（已合并到上一步）"

        return modified

    @staticmethod
    def save(modified_utg: Dict, output_path: str) -> str:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(modified_utg, f, ensure_ascii=False, indent=2)
        return str(path)
