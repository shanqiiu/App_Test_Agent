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

    # 从文件批量生成（每行 JSON: {"query": "...", "fault_mode": "...", "app_name": "..."}）
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
    "缺货":    ("modify_text", 90),
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
    "替换":    ("modify_text_ai", 85),
    "错误":    ("modify_text", 70),
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

请将用户的故障描述展开为一条精确的图像编辑指令（给 AI 图像生成器使用）。

要求：
1. 指令必须明确描述"对哪个 UI 元素做什么操作"
2. 使用"将...改为...""在...区域...""模拟..."等可执行的表述
3. 不要添加"请""建议"等客气话，直接给出操作指令
4. 一句话完成，50 字以内

异常模式参考：
- modify_text_ai: 修改页面文字内容（置灰按钮、替换名称、改价格等）
- modify_text: 修改数字类文字（价格、金额）
- text_overlay: 在页面上覆盖遮挡元素
- dialog: 生成弹窗覆盖界面
- content_duplicate: 复制页面元素制造重复
- area_loading: 模拟局部加载超时
- response_delay: 模拟操作无响应

请只输出指令本身，不要 JSON 包装，不要解释。"""


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
        return _template_instruction(fault_mode, anomaly_mode)

    api_key = api_key or os.getenv('VLM_API_KEY', '')
    if not api_key:
        print("  ⚠ VLM_API_KEY 未设置，使用模板生成 instruction")
        return _template_instruction(fault_mode, anomaly_mode)

    api_url = api_url or os.getenv('VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions')
    model = model or os.getenv('VLM_MODEL', 'gpt-4o')

    prompt = VLM_INSTRUCTION_PROMPT.format(
        query=query,
        fault_mode=fault_mode,
        anomaly_mode=anomaly_mode,
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


def _template_instruction(fault_mode: str, anomaly_mode: str) -> str:
    """模板兜底：基于 anomaly_mode + fault_mode 生成基础 instruction"""
    mode_templates = {
        "modify_text_ai": f"将{fault_mode}",
        "modify_text": f"修改{fault_mode}相关的数字",
        "text_overlay": f"在{fault_mode}相关区域生成遮挡",
        "dialog": f"模拟{fault_mode}的系统弹窗",
        "content_duplicate": f"复制{fault_mode}相关元素",
        "area_loading": f"模拟{fault_mode}的加载状态",
        "response_delay": f"模拟{fault_mode}",
    }
    return mode_templates.get(anomaly_mode, fault_mode)


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
    """写入映射配置到对应的 config/mapping_{mode}.json

    Returns:
        写入结果 {"success": bool, "file": str, "issues": [...]}
    """
    issues = validate_entry(entry)
    if issues:
        return {"success": False, "file": "", "issues": issues}

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

    # 写入
    target_file.parent.mkdir(parents=True, exist_ok=True)
    with open(target_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    return {
        "success": True,
        "file": str(target_file),
        "action": action,
        "issues": [],
    }


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
        write_result = {"success": True, "file": "(dry-run)", "action": "预览", "issues": []}
    else:
        write_result = write_mapping(entry, config_dir, anomaly_mode)

    if write_result["success"]:
        action = write_result.get("action", "写入")
        print(f"  ✅ {action}: {write_result['file']}")
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
    """从 JSON 文件批量生成"""
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
