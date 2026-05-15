#!/usr/bin/env python3
"""
convert_queries_to_demo.py - 将 queries 目录数据转换为 injection_demo 格式

功能：
1. 扫描 queries 目录下的所有查询任务
2. 提取截图序列（home + catchDataTurnId1-N）
3. 生成 task.json（可选使用 VLM 生成任务描述）
4. 输出到 examples 目录

用法：
    # 转换指定数量的查询
    python convert_queries_to_demo.py --count 3

    # 转换所有查询
    python convert_queries_to_demo.py --all

    # 使用 VLM 生成任务描述
    python convert_queries_to_demo.py --count 3 --use-vlm
"""

import os
import sys
import json
import shutil
import argparse
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

# 确保能导入 app 模块
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 设置 UTF-8 编码输出（Windows 兼容）
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# 自动加载项目根目录的 .env 文件
try:
    from dotenv import load_dotenv
    env_paths = [
        _project_root / '.env',
        _project_root.parent / '.env',
        Path.cwd() / '.env',
    ]
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            break
except ImportError:
    pass

# 延迟导入 VLMClient（仅在需要时导入）
VLMClient = None
try:
    from app.utils.vlm_client import VLMClient
except ImportError:
    pass


def extract_app_name(query_name: str) -> str:
    """从查询名称中提取应用名称"""
    # 匹配括号中的应用名称，如 (去哪儿旅行)、(支付宝)、华为(视频)
    import re
    patterns = [
        r'\(([^)]+)\)',  # (应用名)
        r'([^()]+)\(视频\)',  # 华为(视频) -> 华为
    ]
    for pattern in patterns:
        match = re.search(pattern, query_name)
        if match:
            return match.group(1).strip()
    return "未知应用"


def generate_expected_steps(query_name: str) -> List[str]:
    """根据查询名称生成预期步骤"""
    app_name = extract_app_name(query_name)
    query_lower = query_name.lower()

    # 根据关键词生成步骤
    if '购买' in query_name or '订' in query_name or '买' in query_name:
        if '机票' in query_name:
            return [
                f"打开{app_name}App首页",
                "点击机票入口",
                "选择出发地和目的地",
                "选择出发日期",
                "搜索航班",
                "选择合适的航班",
                "填写乘机人信息",
                "确认订单并支付"
            ]
        elif '火车票' in query_name:
            return [
                f"打开{app_name}App首页",
                "点击火车票入口",
                "选择出发地和目的地",
                "选择出发日期",
                "搜索车次",
                "选择合适的车次",
                "填写乘客信息",
                "确认订单并支付"
            ]
        else:
            return [
                f"打开{app_name}App首页",
                "浏览或搜索商品",
                "选择商品",
                "查看商品详情",
                "加入购物车",
                "确认订单",
                "完成支付"
            ]

    elif '查询' in query_name or '查看' in query_name or '找' in query_name:
        if '违法' in query_name or '违章' in query_name:
            return [
                f"打开{app_name}App首页",
                "搜索或找到车辆违法查询入口",
                "进入车辆违法查询页面",
                "查看违法记录"
            ]
        elif '乘机证明' in query_name:
            return [
                f"打开{app_name}App首页",
                "搜索或找到乘机证明入口",
                "进入乘机证明页面",
                "查看或下载乘机证明"
            ]
        else:
            return [
                f"打开{app_name}App首页",
                "搜索或找到查询入口",
                "输入查询条件",
                "查看查询结果"
            ]

    elif '下载' in query_name or '缓存' in query_name:
        return [
            f"打开{app_name}App首页",
            "搜索或浏览找到目标内容",
            "点击内容详情",
            "点击下载或缓存按钮",
            "选择下载质量",
            "开始下载"
        ]

    elif '申请' in query_name or '办理' in query_name or '领取' in query_name:
        if '乘机证明' in query_name:
            return [
                f"打开{app_name}App首页",
                "搜索或找到乘机证明入口",
                "进入乘机证明申请页面",
                "填写必要信息",
                "提交申请"
            ]
        else:
            return [
                f"打开{app_name}App首页",
                "找到申请入口",
                "填写申请信息",
                "提交申请"
            ]

    elif '添加' in query_name:
        return [
            f"打开{app_name}App首页",
            "找到添加入口",
            "输入或选择要添加的内容",
            "确认添加"
        ]

    # 默认步骤
    return [
        f"打开{app_name}App首页",
        "浏览或搜索目标功能",
        "执行相关操作",
        "完成任务"
    ]


def analyze_with_vlm(vlm_client: VLMClient, screenshots: List[Path]) -> str:
    """使用 VLM 分析截图序列，生成任务描述"""
    if not screenshots:
        return "未指定任务描述"

    # 只分析前3张截图，避免token过多
    sample_screenshots = screenshots[:3]

    prompt = """分析这些 App 界面截图，用一句话描述用户正在执行的任务。

要求：
1. 描述要简洁明了
2. 包含应用名称和主要操作
3. 格式：在[应用名]中[操作内容]

例如：
- 在瑞幸咖啡App点一杯生椰拿铁
- 在支付宝查询车辆违法记录
- 在华为视频下载电影金陵十三钗

请直接输出任务描述，不要包含其他解释。"""

    try:
        # 编码图片
        images_data = []
        for img_path in sample_screenshots:
            with open(img_path, 'rb') as f:
                import base64
                images_data.append(base64.b64encode(f.read()).decode('utf-8'))

        # 构建消息
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt}
                ]
            }
        ]

        # 添加图片
        for img_data in images_data:
            messages[0]["content"].append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_data}"}
            })

        # 调用 VLM
        response = vlm_client.chat(messages, temperature=0.3)

        # 提取任务描述
        task_desc = response.strip()
        # 移除可能的引号
        task_desc = task_desc.strip('"').strip("'").strip()

        return task_desc if task_desc else "未指定任务描述"

    except Exception as e:
        print(f"  ⚠ VLM 分析失败: {e}")
        return "未指定任务描述"


def convert_query_to_demo(
    query_dir: Path,
    output_dir: Path,
    vlm_client: Optional[VLMClient] = None,
    demo_index: int = 0
) -> Optional[Dict]:
    """
    将单个查询目录转换为 injection_demo 格式

    Args:
        query_dir: 查询目录路径
        output_dir: 输出目录
        vlm_client: VLM 客户端（可选）
        demo_index: demo 序号

    Returns:
        转换结果字典
    """
    query_name = query_dir.name

    print(f"\n处理: {query_name}")

    # 收集截图
    screenshots = []

    # 1. home 目录
    home_dir = query_dir / "home"
    if home_dir.exists():
        for img_file in home_dir.glob("temp_image-screenshot-origin.*"):
            screenshots.append(img_file)

    # 2. catchDataTurnId1-N 目录
    turn_dirs = sorted(
        [d for d in query_dir.glob("catchDataTurnId*") if d.is_dir()],
        key=lambda x: int(x.name.replace("catchDataTurnId", ""))
    )

    for turn_dir in turn_dirs:
        for img_file in turn_dir.glob("temp_image-screenshot-origin.*"):
            screenshots.append(img_file)

    if not screenshots:
        print(f"  ⚠ 未找到截图，跳过")
        return None

    print(f"  找到 {len(screenshots)} 张截图")

    # 创建输出目录
    demo_name = f"injection_demo_{demo_index:02d}"
    demo_dir = output_dir / demo_name
    screenshots_dir = demo_dir / "screenshots"

    if demo_dir.exists():
        shutil.rmtree(demo_dir)

    screenshots_dir.mkdir(parents=True)

    # 复制截图
    for i, img_path in enumerate(screenshots):
        dst_path = screenshots_dir / f"step_{i:02d}.jpg"
        shutil.copy2(img_path, dst_path)

    print(f"  已复制 {len(screenshots)} 张截图到 {demo_name}/screenshots/")

    # 生成 task.json
    app_name = extract_app_name(query_name)

    # 使用 VLM 生成任务描述
    if vlm_client:
        print(f"  使用 VLM 分析任务...")
        task_description = analyze_with_vlm(vlm_client, screenshots)
    else:
        task_description = query_name

    expected_steps = generate_expected_steps(query_name)

    task_json = {
        "description": task_description,
        "app_name": app_name,
        "expected_steps": expected_steps,
        "notes": f"从 queries 目录转换而来，原始查询: {query_name}"
    }

    task_json_path = demo_dir / "task.json"
    with open(task_json_path, 'w', encoding='utf-8') as f:
        json.dump(task_json, f, ensure_ascii=False, indent=2)

    print(f"  已生成 task.json")
    print(f"  任务描述: {task_description}")
    print(f"  应用名称: {app_name}")
    print(f"  预期步骤: {len(expected_steps)} 步")

    return {
        "query_name": query_name,
        "demo_name": demo_name,
        "screenshots_count": len(screenshots),
        "task_description": task_description,
        "app_name": app_name
    }


def main():
    parser = argparse.ArgumentParser(
        description="将 queries 目录数据转换为 injection_demo 格式",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "--queries-dir",
        type=str,
        default=None,
        help="queries 目录路径（默认: data/Agent执行遇到的典型异常UI类型/queries）"
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="输出目录（默认: data/examples）"
    )

    parser.add_argument(
        "--count",
        type=int,
        default=3,
        help="转换的查询数量（默认: 3）"
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="转换所有查询"
    )

    parser.add_argument(
        "--use-vlm",
        action="store_true",
        help="使用 VLM 生成任务描述"
    )

    parser.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="起始 demo 序号（默认: 1）"
    )

    args = parser.parse_args()

    # 确定路径
    if args.queries_dir:
        queries_dir = Path(args.queries_dir)
    else:
        queries_dir = _project_root / "data" / "Agent执行遇到的典型异常UI类型" / "queries"

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = _project_root / "data" / "examples"

    if not queries_dir.exists():
        print(f"❌ queries 目录不存在: {queries_dir}")
        sys.exit(1)

    # 初始化 VLM 客户端
    vlm_client = None
    if args.use_vlm:
        if VLMClient is None:
            print("⚠ VLMClient 模块未找到，将使用查询名称作为任务描述")
        else:
            try:
                vlm_client = VLMClient()
                print("✓ VLM 客户端初始化成功")
            except Exception as e:
                print(f"⚠ VLM 客户端初始化失败: {e}")
                print("  将使用查询名称作为任务描述")

    # 扫描查询目录
    query_dirs = sorted([d for d in queries_dir.iterdir() if d.is_dir()])

    if not query_dirs:
        print(f"❌ 未找到查询目录: {queries_dir}")
        sys.exit(1)

    print(f"\n找到 {len(query_dirs)} 个查询任务")

    # 确定要转换的数量
    if args.all:
        count = len(query_dirs)
    else:
        count = min(args.count, len(query_dirs))

    print(f"将转换 {count} 个查询任务\n")

    # 转换查询
    results = []
    for i in range(count):
        query_dir = query_dirs[i]
        demo_index = args.start_index + i

        result = convert_query_to_demo(
            query_dir=query_dir,
            output_dir=output_dir,
            vlm_client=vlm_client,
            demo_index=demo_index
        )

        if result:
            results.append(result)

    # 输出总结
    print("\n" + "="*60)
    print("✅ 转换完成")
    print("="*60)
    print(f"成功转换: {len(results)} 个")
    print(f"输出目录: {output_dir}")

    if results:
        print("\n转换列表:")
        for r in results:
            print(f"  • {r['demo_name']}: {r['query_name']}")
            print(f"    任务: {r['task_description']}")
            print(f"    截图: {r['screenshots_count']} 张")


if __name__ == "__main__":
    main()
