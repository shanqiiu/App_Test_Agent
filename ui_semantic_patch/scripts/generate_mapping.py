#!/usr/bin/env python3
"""
generate_mapping.py — 自动生成异常注入映射配置

输入：query + fault_mode（初步异常指令描述）
输出：config/mapping_{anomaly_mode}.json 中的一条映射条目

三级决策流水线：
  1. fault_mode → anomaly_mode     （规则引擎，确定性关键词匹配）
  2. fault_mode → instruction       （VLM 展开，场景化措辞）
  3. anomaly_mode → GT 模板匹配     （仅 dialog 模式，按 app_name 查找参考图）

用法：
    # 单条生成
    python generate_mapping.py \\
        --query "(去哪儿旅行)购买一张从南京去北京的机票" \\
        --fault-mode "订票按钮置灰" \\
        --app-name "去哪儿旅行"

    # 从文件批量生成（JSON 数组: [{"query": "...", "fault_mode": "...", "app_name": "..."}]）
    python generate_mapping.py --input queries.json

    # 预览模式（不写入文件）
    python generate_mapping.py --query "..." --fault-mode "..." --dry-run
"""

import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

# 确保能导入 app 模块
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 自动加载 .env
try:
    from dotenv import load_dotenv
    for env_path in [
        _project_root.parent / '.env',
        _project_root / '.env',
    ]:
        if env_path.exists():
            load_dotenv(env_path)
            break
except ImportError:
    pass

# UTF-8 输出
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# ============================================================================
# Step 1: fault_mode → anomaly_mode 规则映射
# ============================================================================

FAULT_TO_ANOMALY = {
    # 关键词 → (anomaly_mode, 匹配优先级)
    "置灰":    ("modify_text_ai", 100),
    "无票":    ("modify_text", 90),
    "售罄":    ("modify_text", 90),
    "缺货":    ("modify_text", 80),
    "提示":    ("dialog", 60),   # 低优先级，"无票状态提示"中"提示"不是主意图
    "价格":    ("modify_text", 95),
    "篡改":    ("modify_text_ai", 90),
    "遮挡":    ("text_overlay", 90),
    "浮层":    ("text_overlay", 85),
    "遮盖":    ("text_overlay", 90),
    "弹窗":    ("dialog", 100),
    "广告":    ("dialog", 80),
    "权限":    ("dialog", 80),
    "重复":    ("content_duplicate", 100),
    "歧义":    ("content_duplicate", 90),
    "加载":    ("area_loading", 100),
    "超时":    ("area_loading", 90),
    "卡顿":    ("response_delay", 100),
    "延迟":    ("response_delay", 100),
    "冻结":    ("response_delay", 95),
    "未响应":  ("response_delay", 95),
    "总价":    ("modify_text", 85),
    "票价":    ("modify_text", 85),
    "金额":    ("modify_text", 85),
    "改名":    ("modify_text_ai", 85),
    "改成":    ("modify_text_ai", 90),
    "替换":    ("modify_text_ai", 85),
    "错误":    ("modify_text", 70),
    # content_duplicate 扩展
    "多个":    ("content_duplicate", 90),
    "混乱":    ("content_duplicate", 90),
    "混淆":    ("content_duplicate", 85),
    "标记":    ("content_duplicate", 70),  # "标记为最新" → 低优先级，避免误判
    # text_overlay 扩展
    "无法点击":("modify_text_ai", 85),
    "不可点击":("modify_text_ai", 85),
    "不能点":  ("modify_text_ai", 85),
}

# fallback: 无法匹配时默认使用 modify_text_ai
DEFAULT_ANOMALY_MODE = "modify_text_ai"

# 需要 GT 参考图的模式
GT_REQUIRED_MODES = {"dialog", "area_loading", "content_duplicate"}


def classify_anomaly_mode(fault_mode: str) -> Tuple[str, float]:
    """根据 fault_mode 描述匹配 anomaly_mode。

    Returns:
        (anomaly_mode, confidence)  — confidence 0.0~1.0
    """
    best_mode = DEFAULT_ANOMALY_MODE
    best_priority = 0

    for keyword, (mode, priority) in FAULT_TO_ANOMALY.items():
        if keyword in fault_mode:
            if priority > best_priority:
                best_mode = mode
                best_priority = priority

    confidence = min(1.0, best_priority / 100.0) if best_priority > 0 else 0.3
    return best_mode, confidence


# ============================================================================
# Step 2: VLM instruction 展开
# ============================================================================

VLM_INSTRUCTION_PROMPT = """你是 App 异常 UI 测试场景的设计助手。用户提供了：

**用户查询**：{query}
**异常故障描述**：{fault_mode}
**匹配的异常模式**：{anomaly_mode}
**从查询中提取的关键约束**：{constraints}

请将故障描述展开为一条精确的图像编辑指令（给 AI 图像生成器使用）。

核心要求 — 指令必须精确定位操作目标：
1. **首先从"关键约束"中提取限定条件**，将它们写入指令
   - 时间范围（如"后天18:00-21:00"）→ 指定哪个时间段/哪个航班
   - 航空公司（如"东方航空"）→ 指定哪个航司的按钮
   - 地点（如"南京→北京"）→ 指定哪条路线的元素
   - 价格（如"最便宜"）→ 指定哪个价格档位的元素
2. 然后描述操作动作（置灰、修改、遮挡等）
3. 使用"将...改为...""在...区域...""模拟..."等可执行表述
4. 不要添加"请""建议"等客气话
5. 一句话完成，50 字以内

异常模式参考：{anomaly_mode_desc}

请只输出指令本身，不要 JSON 包装，不要解释。"""

# 各异常模式的说明（注入到 prompt）
ANOMALY_MODE_DESC = {
    "modify_text_ai":   "修改页面文字内容（置灰按钮、替换名称、改价格等）",
    "modify_text":      "修改数字类文字（价格、金额）",
    "text_overlay":     "在页面上覆盖遮挡元素",
    "dialog":           "生成弹窗覆盖界面",
    "content_duplicate":"复制页面元素制造重复",
    "area_loading":     "模拟局部加载超时",
    "response_delay":   "模拟操作无响应",
}


def _extract_constraints(query: str) -> str:
    """从 query 中提取关键约束条件（时间、地点、航司、价格等）。

    Returns:
        约束描述字符串，如 "时间=后天18:00-21:00, 路线=南京→北京, 航司=东方航空"
        无约束时返回 "(无特殊约束)"
    """
    constraints = []

    # 时间约束
    time_patterns = [
        (r'(后天|明天|今天|下周[一二三四五六日]|下个月\d+号)\s*\d{1,2}:\d{2}\s*[-~至到]\s*\d{1,2}:\d{2}', '时间段'),
        (r'(后天|明天|今天|下周[一二三四五六日]|下个月\d+号)', '日期'),
        (r'\d{1,2}:\d{2}\s*[-~至到]\s*\d{1,2}:\d{2}', '时间段'),
    ]
    for pattern, label in time_patterns:
        match = re.search(pattern, query)
        if match:
            constraints.append(f"{label}={match.group(0)}")
            break

    # 地点约束（从 X 到 Y / 从 X 去 Y / X 到 Y 的机票）
    location_patterns = [
        r'从\s*(\S{1,10}?)\s*(?:去|到|出发到)\s*(\S{1,10}?)(?:[的机票火车票航班，,。\s]|$)',
        r'(\S{2,6})\s*到\s*(\S{2,6})(?:的)?(?:机票|火车票|航班)',
    ]
    for pattern in location_patterns:
        match = re.search(pattern, query)
        if match:
            from_place = match.group(1)
            to_place = match.group(2)
            # 清理尾部标点
            to_place = re.sub(r'[，,。\s]+$', '', to_place)
            constraints.append(f"路线={from_place}→{to_place}")
            break

    # 航空公司
    airline_match = re.search(r'(东方航空|南方航空|中国国航|海南航空|春秋航空|吉祥航空|厦门航空|深圳航空|四川航空|山东航空)', query)
    if airline_match:
        constraints.append(f"航司={airline_match.group(1)}")

    # 价格约束
    price_match = re.search(r'(最便宜|最贵|经济舱|商务舱|头等舱)', query)
    if price_match:
        constraints.append(f"价格={price_match.group(1)}")

    # 舱位
    cabin_match = re.search(r'(经济舱|商务舱|头等舱|超级经济舱)', query)
    if cabin_match and '价格' not in str(constraints):
        constraints.append(f"舱位={cabin_match.group(1)}")

    # 特定名称（航班号、车次号）
    name_match = re.search(r'([GDCKZT]\d{1,4})', query)
    if name_match:
        constraints.append(f"车次={name_match.group(1)}")

    # 特定内容名称（剧名、电影名）
    # 匹配模式：动词 + 可选"电视剧/电影" + 实际名称 + 可选后缀
    name_match = re.search(
        r'(?:下载|缓存|看|播放|追|看剧|缓存下)\s*'
        r'(?:电视剧|电影|综艺|动漫|上|下)?\s*'
        r'([\u4e00-\u9fff]{2,8})'
        r'(?:第\d+集|全集|最新一集|大结局|电影版|第\d+季)?',
        query
    )
    if name_match:
        content_name = name_match.group(1)
        # 过滤掉通用词和明显错误匹配
        bad_names = {'电视剧', '电影', '视频', '剧集', '综艺', '动漫',
                     '下', '上', '一集', '全集', '一', '我的', '我没有',
                     '我没有看完', '我没有看完的', '大鹏', '大鹏主演',
                     '主演的', '下载', '缓存', '电影长津湖', '三体最新',
                     '三体最新一集'}
        if content_name not in bad_names and not content_name.endswith('第'):
            constraints.append(f"内容={content_name}")

    if not constraints:
        return "(无特殊约束)"
    return "; ".join(constraints)


def expand_instruction(
    query: str,
    fault_mode: str,
    anomaly_mode: str,
    api_key: str = None,
    api_url: str = None,
    model: str = None,
    dry_run: bool = False,
) -> str:
    """使用 VLM 将 fault_mode 展开为详细的指令。

    如果 VLM 不可用（未配置 API Key 或 dry_run），则使用模板生成。
    """
    if dry_run:
        return _template_instruction(query, fault_mode, anomaly_mode)

    api_key = api_key or os.getenv('VLM_API_KEY', '')
    if not api_key:
        print("  ⚠ VLM_API_KEY 未设置，使用模板生成 instruction")
        return _template_instruction(query, fault_mode, anomaly_mode)

    api_url = api_url or os.getenv('VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions')
    model = model or os.getenv('VLM_MODEL', 'gpt-4o')

    constraints = _extract_constraints(query)
    mode_desc = ANOMALY_MODE_DESC.get(anomaly_mode, "修改页面元素")

    prompt = VLM_INSTRUCTION_PROMPT.format(
        query=query,
        fault_mode=fault_mode,
        anomaly_mode=anomaly_mode,
        constraints=constraints,
        anomaly_mode_desc=mode_desc,
    )

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 200,
    }

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}',
    }

    for attempt in range(3):
        try:
            if attempt > 0:
                wait = min(5 * (2 ** (attempt - 1)), 30)
                print(f"    ⏳ 重试 {attempt + 1}/3 (等待 {wait}s)...")
                time.sleep(wait)

            resp = requests.post(api_url, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            instruction = data['choices'][0]['message']['content'].strip()
            # 清理引号包裹
            instruction = instruction.strip('"').strip("'").strip('"').strip("'")
            return instruction

        except requests.exceptions.RequestException as e:
            print(f"    ⚠ VLM 请求失败: {e}")
            if attempt == 2:
                return _template_instruction(fault_mode, anomaly_mode)

    return _template_instruction(fault_mode, anomaly_mode)


def _template_instruction(query: str, fault_mode: str, anomaly_mode: str) -> str:
    """模板兜底：基于 anomaly_mode + fault_mode + query 约束生成基础 instruction"""
    # 提取 query 中的关键约束作为前缀
    constraints = _extract_constraints(query)
    constraint_prefix = ""
    if constraints and constraints != "(无特殊约束)":
        parts = constraints.split("; ")
        readable = []
        for p in parts[:2]:
            if "=" in p:
                label, value = p.split("=", 1)
                if label == "时间段":
                    readable.append(f"{value}的")
                elif label == "日期":
                    readable.append(f"{value}")
                elif label == "路线":
                    readable.append(f"{value}")
                elif label == "航司":
                    readable.append(f"{value}")
                elif label == "价格":
                    readable.append(f"{value}")
                elif label == "内容":
                    readable.append(f"《{value}》")
        if readable:
            constraint_prefix = "、".join(readable) + "的"

    # 如果 fault_mode 本身已是完整的动作描述，直接加约束前缀即可
    action_verbs = ["置灰", "遮挡", "修改", "改为", "替换", "复制", "重复", "延迟",
                    "卡顿", "超时", "弹窗", "广告", "无法", "不可", "不能", "错误", "异常",
                    "被标记", "被改", "被修改", "被篡改", "比", "便宜", "贵", "错位",
                    "挡住", "覆盖", "挡住", "无响应", "未更新", "关闭", "不可用"]
    has_verb = any(v in fault_mode for v in action_verbs)

    if has_verb:
        # fault_mode 已包含动作动词 → 直接用，不重复添加模式描述
        if anomaly_mode == "dialog" and "弹窗" not in fault_mode:
            return f"{constraint_prefix}模拟{fault_mode}的系统弹窗"
        elif anomaly_mode == "area_loading" and "超时" not in fault_mode and "加载" not in fault_mode:
            return f"模拟{constraint_prefix}{fault_mode}的加载超时"
        elif anomaly_mode == "response_delay" and "延迟" not in fault_mode and "卡顿" not in fault_mode and "无响应" not in fault_mode:
            return f"模拟{constraint_prefix}{fault_mode}导致的无响应"
        else:
            return f"{constraint_prefix}{fault_mode}"

    # fault_mode 无明确动作 → 追加模式描述
    mode_suffix = {
        "modify_text_ai":   f"将{constraint_prefix}{fault_mode}相关按钮/文字修改为异常状态",
        "modify_text":      f"修改{constraint_prefix}{fault_mode}相关的数字信息",
        "text_overlay":     f"在{constraint_prefix}{fault_mode}区域生成遮挡元素",
        "dialog":           f"在页面上模拟{constraint_prefix}{fault_mode}的弹窗",
        "content_duplicate":f"复制{constraint_prefix}{fault_mode}相关条目，制造内容重复",
        "area_loading":     f"模拟{constraint_prefix}{fault_mode}的超时状态",
        "response_delay":   f"模拟{constraint_prefix}{fault_mode}的响应延迟",
    }
    return mode_suffix.get(anomaly_mode, f"{constraint_prefix}{fault_mode}")


# ============================================================================
# Step 3: GT 模板匹配（仅 dialog / area_loading / content_duplicate）
# ============================================================================

def match_gt_template(
    app_name: str,
    anomaly_mode: str,
    gt_template_dir: Path,
) -> Tuple[str, str, str]:
    """为需要 GT 参考图的模式自动匹配模板。

    Returns:
        (gt_category, gt_sample, reference_path) or ("", "", "")
    """
    if anomaly_mode not in GT_REQUIRED_MODES:
        return "", "", ""

    mode_dir = gt_template_dir / anomaly_mode
    if not mode_dir.exists():
        print(f"  ⚠ GT 目录不存在: {mode_dir}")
        return "", "", ""

    # 策略 1: 文件名包含 app_name
    for ext in ('.jpg', '.jpeg', '.png'):
        for f in mode_dir.glob(f'*{app_name}*{ext}'):
            rel_path = f"data/gt-category/{anomaly_mode}/{f.name}"
            return anomaly_mode, f.name, rel_path

    # 策略 2: 取该目录下第一个文件
    for ext in ('.jpg', '.jpeg', '.png'):
        samples = sorted(mode_dir.glob(f'*{ext}'))
        if samples:
            rel_path = f"data/gt-category/{anomaly_mode}/{samples[0].name}"
            return anomaly_mode, samples[0].name, rel_path

    print(f"  ⚠ {anomaly_mode} 目录下未找到 GT 图片: {mode_dir}")
    return "", "", ""


# ============================================================================
# Step 4: 校验 & 写入
# ============================================================================

def build_mapping_entry(
    query: str,
    fault_mode: str,
    app_name: str,
    example_dir: str,
    anomaly_mode: str,
    instruction: str,
    gt_category: str,
    gt_sample: str,
    reference_path: str,
    fault_mode_key: str = "mode_1",
) -> Dict:
    """构建一条 mapping 条目"""
    entry = {
        "query": query,
        "query_id": str(uuid.uuid4()),
        "app_name": app_name,
        "example_dir": example_dir,
        "fault_mode": fault_mode,
        "fault_mode_key": fault_mode_key,
        "injection_config": {
            "anomaly_mode": anomaly_mode,
            "instruction": instruction,
        },
    }

    if anomaly_mode in GT_REQUIRED_MODES and gt_sample:
        entry["injection_config"]["gt_category"] = gt_category
        entry["injection_config"]["gt_sample"] = gt_sample
        entry["injection_config"]["reference_path"] = reference_path

    return entry


def validate_entry(entry: Dict) -> List[str]:
    """校验映射条目，返回问题列表"""
    issues = []

    config = entry.get("injection_config", {})
    anomaly_mode = config.get("anomaly_mode", "")

    # instruction 不能为空
    if not config.get("instruction", "").strip():
        issues.append("instruction 为空")

    # instruction 不能太短
    if len(config.get("instruction", "")) < 5:
        issues.append(f"instruction 过短 ({len(config['instruction'])} 字)")

    # GT 必须的模式需要有 gt_sample
    if anomaly_mode in GT_REQUIRED_MODES:
        if not config.get("gt_sample"):
            issues.append(f"{anomaly_mode} 模式缺少 gt_sample")

    # anomaly_mode 必须在合法值内
    VALID_MODES = {
        "dialog", "area_loading", "content_duplicate",
        "modify_text", "modify_text_ai", "modify_text_ocr",
        "modify_text_e2e", "text_overlay", "response_delay",
    }
    if anomaly_mode not in VALID_MODES:
        issues.append(f"非法的 anomaly_mode: {anomaly_mode}")

    return issues


def load_mapping_file(mapping_path: Path) -> Dict:
    """加载已存在的映射文件（不存在则返回空模板）"""
    if mapping_path.exists():
        with open(mapping_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "version": "3.0",
        "description": "",
        "last_updated": "",
        "anomaly_type": "",
        "total_queries": 0,
        "total_mappings": 0,
        "app_distribution": {},
        "mappings": [],
    }


def write_mapping(entry: Dict, config_dir: Path, anomaly_mode: str) -> Dict:
    """写入映射配置到 config/mapping_{mode}.json，并同步更新聚合 mapping.json

    Returns:
        写入结果 {"success": bool, "file": str, "aggregated_file": str, "issues": [...]}
    """
    issues = validate_entry(entry)
    if issues:
        return {"success": False, "file": "", "aggregated_file": "", "issues": issues}

    # 确定目标文件
    mode_key = anomaly_mode.replace(" ", "_").lower()
    target_file = config_dir / f"mapping_{mode_key}.json"

    # 加载已有数据
    data = load_mapping_file(target_file)

    # 更新元数据
    data["anomaly_type"] = anomaly_mode
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d")

    # 去重：已有相同 query + fault_mode_key 则覆盖
    existing_idx = None
    for i, m in enumerate(data.get("mappings", [])):
        if (m.get("query") == entry["query"]
                and m.get("fault_mode_key") == entry.get("fault_mode_key")):
            existing_idx = i
            break

    if existing_idx is not None:
        data["mappings"][existing_idx] = entry
        action = "覆盖"
    else:
        data["mappings"].append(entry)
        action = "新增"

    # 更新统计
    data["total_mappings"] = len(data["mappings"])
    unique_queries = set(m["query"] for m in data["mappings"])
    data["total_queries"] = len(unique_queries)

    app_dist = {}
    for m in data["mappings"]:
        app = m.get("app_name", "?")
        app_dist[app] = app_dist.get(app, 0) + 1
    data["app_distribution"] = app_dist

    # 写入 per-mode 文件
    target_file.parent.mkdir(parents=True, exist_ok=True)
    with open(target_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    # 同步聚合 mapping.json
    aggregated_file = _sync_aggregated_mapping(entry, config_dir, action)

    return {
        "success": True,
        "file": str(target_file),
        "aggregated_file": str(aggregated_file),
        "action": action,
        "issues": [],
    }


def _sync_aggregated_mapping(entry: Dict, config_dir: Path, action: str) -> Path:
    """同步更新聚合的 mapping.json（batch_injection_with_mapping.py 消费它）"""
    agg_file = config_dir / "mapping.json"

    agg_data = {
        "version": "3.0",
        "description": "Query到异常注入参数的映射配置（自动生成 + 人工审核）",
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
        "changelog": [],
        "statistics": {"total_queries": 0, "total_mappings": 0,
                       "by_anomaly_mode": {}, "app_distribution": {}},
        "mappings": [],
    }

    if agg_file.exists():
        with open(agg_file, 'r', encoding='utf-8') as f:
            agg_data = json.load(f)

    # 保留 changelog
    changelog = agg_data.get("changelog", [])
    if changelog and not any("自动生成" in c for c in changelog[-1:]):
        changelog.append(
            f"auto: {datetime.now().strftime('%Y-%m-%d %H:%M')} "
            f"{action} {entry['fault_mode']} ({entry['app_name']})"
        )
    elif not changelog:
        changelog = [
            f"auto: {datetime.now().strftime('%Y-%m-%d %H:%M')} "
            f"{action} {entry['fault_mode']} ({entry['app_name']})"
        ]

    # 去重替换
    existing_idx = None
    for i, m in enumerate(agg_data.get("mappings", [])):
        if (m.get("query") == entry["query"]
                and m.get("fault_mode_key") == entry.get("fault_mode_key")):
            existing_idx = i
            break

    if existing_idx is not None:
        agg_data["mappings"][existing_idx] = entry
    else:
        agg_data["mappings"].append(entry)

    # 重新计算统计
    mappings = agg_data["mappings"]
    agg_data["total_mappings"] = len(mappings)
    unique_queries = set(m["query"] for m in mappings)
    agg_data["total_queries"] = len(unique_queries)

    mode_dist = {}
    for m in mappings:
        mode = m.get("injection_config", {}).get("anomaly_mode", "?")
        mode_dist[mode] = mode_dist.get(mode, 0) + 1
    agg_data["statistics"]["by_anomaly_mode"] = mode_dist

    app_dist = {}
    for m in mappings:
        app = m.get("app_name", "?")
        app_dist[app] = app_dist.get(app, 0) + 1
    agg_data["statistics"]["app_distribution"] = app_dist

    agg_data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    agg_data["changelog"] = changelog

    with open(agg_file, 'w', encoding='utf-8') as f:
        json.dump(agg_data, f, ensure_ascii=False, indent=2)

    return agg_file


# ============================================================================
# 主流程
# ============================================================================

def generate(
    query: str,
    fault_mode: str,
    app_name: str = "",
    example_dir: str = "",
    gt_template_dir: Optional[Path] = None,
    config_dir: Optional[Path] = None,
    api_key: str = None,
    api_url: str = None,
    model: str = None,
    dry_run: bool = False,
) -> Dict:
    """执行完整的映射生成流程。

    Returns:
        {
            "success": bool,
            "entry": dict,
            "anomaly_mode": str,
            "anomaly_mode_confidence": float,
            "instruction": str,
            "gt": {"category": str, "sample": str, "reference_path": str},
            "write": {...},
        }
    """
    # 确定路径
    if config_dir is None:
        config_dir = _project_root / "config"
    else:
        config_dir = Path(config_dir)

    if gt_template_dir is None:
        gt_template_dir = _project_root.parent / "data" / "gt-category"
    else:
        gt_template_dir = Path(gt_template_dir)

    if not app_name:
        # 尝试从 query 中提取 app_name
        match = re.search(r'[（(]([^）)]+)[）)]', query)
        if match:
            app_name = match.group(1)

    print("=" * 60)
    print("🔧 异常映射配置生成器")
    print("=" * 60)
    print(f"  Query:        {query}")
    print(f"  Fault Mode:   {fault_mode}")
    print(f"  App Name:     {app_name or '(自动提取)'}")
    print(f"  Dry Run:      {dry_run}")

    # ---- Step 1: anomaly_mode 分类 ----
    print("\n--- Step 1: 异常模式分类 ---")
    anomaly_mode, confidence = classify_anomaly_mode(fault_mode)
    print(f"  fault_mode:   {fault_mode}")
    print(f"  anomaly_mode: {anomaly_mode}")
    print(f"  confidence:   {confidence:.0%}")

    # ---- Step 2: instruction 展开 ----
    print("\n--- Step 2: 指令展开 ---")
    instruction = expand_instruction(
        query=query,
        fault_mode=fault_mode,
        anomaly_mode=anomaly_mode,
        api_key=api_key,
        api_url=api_url,
        model=model,
        dry_run=dry_run,
    )
    print(f"  instruction:  {instruction}")

    # ---- Step 3: GT 模板匹配 ----
    print("\n--- Step 3: GT 模板匹配 ---")
    gt_category, gt_sample, reference_path = match_gt_template(
        app_name, anomaly_mode, gt_template_dir
    )
    gt = {"category": gt_category, "sample": gt_sample, "reference_path": reference_path}
    if anomaly_mode in GT_REQUIRED_MODES:
        if gt_sample:
            print(f"  gt_sample:    {gt_sample}")
        else:
            print(f"  ⚠ 未找到匹配的 GT 模板（{anomaly_mode} 模式需要）")
    else:
        print("  (不需要 GT 模板)")

    # ---- 构建条目 ----
    entry = build_mapping_entry(
        query=query,
        fault_mode=fault_mode,
        app_name=app_name,
        example_dir=example_dir,
        anomaly_mode=anomaly_mode,
        instruction=instruction,
        gt_category=gt_category,
        gt_sample=gt_sample,
        reference_path=reference_path,
    )

    # ---- Step 4: 写入 ----
    print("\n--- Step 4: 校验 & 写入 ---")
    if dry_run:
        print("  [预览模式] 不写入文件")
        print(f"  条目: {json.dumps(entry, ensure_ascii=False, indent=2)}")
        write_result = {"success": True, "file": "(dry-run)", "aggregated_file": "(dry-run)", "action": "预览", "issues": []}
    else:
        write_result = write_mapping(entry, config_dir, anomaly_mode)

    if write_result["success"]:
        action = write_result.get("action", "写入")
        print(f"  ✅ {action}: {write_result['file']}")
        if write_result.get("aggregated_file"):
            print(f"  ✅ 聚合: {write_result['aggregated_file']}")
    else:
        print(f"  ❌ 写入失败: {write_result['issues']}")

    return {
        "success": write_result["success"],
        "entry": entry,
        "anomaly_mode": anomaly_mode,
        "anomaly_mode_confidence": confidence,
        "instruction": instruction,
        "gt": gt,
        "write": write_result,
    }


def batch_generate(input_file: str, **kwargs) -> List[Dict]:
    """从 JSON 数组文件批量生成"""
    with open(input_file, 'r', encoding='utf-8') as f:
        queries = json.load(f)

    if not isinstance(queries, list):
        print("❌ 输入文件必须是 JSON 数组")
        return []

    results = []
    for i, item in enumerate(queries):
        print(f"\n\n{'#' * 60}")
        print(f"# [{i + 1}/{len(queries)}]")
        print(f"{'#' * 60}")
        result = generate(
            query=item.get("query", ""),
            fault_mode=item.get("fault_mode", ""),
            app_name=item.get("app_name", ""),
            example_dir=item.get("example_dir", ""),
            gt_template_dir=kwargs.get("gt_template_dir"),
            config_dir=kwargs.get("config_dir"),
            api_key=kwargs.get("api_key"),
            api_url=kwargs.get("api_url"),
            model=kwargs.get("model"),
            dry_run=kwargs.get("dry_run", False),
        )
        results.append(result)

    # 汇总
    success_count = sum(1 for r in results if r["success"])
    print(f"\n\n{'=' * 60}")
    print(f"📊 批量生成完成: {success_count}/{len(results)} 成功")
    print(f"{'=' * 60}")

    return results


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="自动生成异常注入映射配置",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 单条生成
    python generate_mapping.py \\
        --query "(去哪儿旅行)购买一张从南京去北京的机票" \\
        --fault-mode "订票按钮置灰" \\
        --app-name "去哪儿旅行"

    # 预览模式
    python generate_mapping.py --query "..." --fault-mode "..." --dry-run

    # 批量生成
    python generate_mapping.py --input queries.json

    # 自定义 VLM 配置
    python generate_mapping.py \\
        --query "..." --fault-mode "..." \\
        --api-key sk-xxx --api-url https://api.example.com/v1 --model gpt-4o
        """
    )

    parser.add_argument('--query', '-q', type=str, help='用户查询任务描述')
    parser.add_argument('--fault-mode', '-f', type=str, help='异常故障描述')
    parser.add_argument('--app-name', '-a', type=str, default='', help='应用名称')
    parser.add_argument('--example-dir', '-e', type=str, default='', help='示例截图目录名')
    parser.add_argument('--input', '-i', type=str, help='批量输入 JSON 文件')

    parser.add_argument('--config-dir', type=str, default=None, help='config 目录路径')
    parser.add_argument('--gt-template-dir', type=str, default=None, help='GT 模板目录路径')

    parser.add_argument('--api-key', type=str, default=None, help='VLM API Key')
    parser.add_argument('--api-url', type=str, default=None, help='VLM API URL')
    parser.add_argument('--model', type=str, default=None, help='VLM 模型名')

    parser.add_argument('--dry-run', action='store_true', help='预览模式，不写入文件')

    args = parser.parse_args()

    kwargs = {
        "gt_template_dir": Path(args.gt_template_dir) if args.gt_template_dir else None,
        "config_dir": Path(args.config_dir) if args.config_dir else None,
        "api_key": args.api_key,
        "api_url": args.api_url,
        "model": args.model,
        "dry_run": args.dry_run,
    }

    if args.input:
        batch_generate(args.input, **kwargs)
    elif args.query and args.fault_mode:
        generate(
            query=args.query,
            fault_mode=args.fault_mode,
            app_name=args.app_name,
            example_dir=args.example_dir,
            **kwargs,
        )
    else:
        parser.print_help()
        print("\n❌ 请提供 --query + --fault-mode（单条）或 --input（批量）")


if __name__ == '__main__':
    main()
