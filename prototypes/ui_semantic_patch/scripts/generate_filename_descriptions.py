#!/usr/bin/env python3
"""
generate_filename_descriptions.py - 基于文件名生成异常描述

功能：
1. 读取异常样本的文件名
2. 使用VLM根据文件名生成详细的异常描述
3. 输出供用户验证
"""

import json
import os
import base64
import requests
import re
from pathlib import Path
from typing import Dict, List

# 自动加载.env文件
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parents[3] / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

# 环境变量
VLM_API_KEY = os.environ.get('VLM_API_KEY')
VLM_API_URL = os.environ.get('VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions')
VLM_MODEL = os.environ.get('VLM_MODEL', 'gpt-4o')


class FilenameDescriptionGenerator:
    """基于文件名生成异常描述"""

    def __init__(self, api_key: str = None, api_url: str = None, model: str = None):
        self.api_key = api_key or VLM_API_KEY
        self.api_url = api_url or VLM_API_URL
        self.model = model or VLM_MODEL

    def generate_description(self, filename: str, image_path: str = None) -> Dict:
        """
        基于文件名生成异常描述

        Args:
            filename: 文件名（如 "弹出广告.jpg"）
            image_path: 图片路径（可选，用于视觉验证）

        Returns:
            {
                "filename": "弹出广告.jpg",
                "anomaly_description": "广告弹窗异常",
                "detailed_explanation": "详细说明...",
                "root_cause": "根因分析",
                "agent_impact": "对Agent的影响",
                "blocking_level": "high/medium/low",
                "recommended_handling": "建议处理方式"
            }
        """
        try:
            # 如果提供了图片路径，同时发送图片
            if image_path and Path(image_path).exists():
                with open(image_path, 'rb') as f:
                    image_base64 = base64.b64encode(f.read()).decode('utf-8')
                has_image = True
            else:
                has_image = False

            # 构建prompt
            prompt = f"""请基于文件名「{filename}」分析这是什么类型的UI异常场景。

## 分析要求

### 1. 异常描述（anomaly_description）
用一句简洁的话（10-15字）概括这个异常的本质特征。
例如："广告弹窗遮挡操作区域"、"加载超时白屏无响应"

### 2. 详细说明（detailed_explanation）
解释这个异常的具体表现：
- 用户看到了什么UI现象
- 界面的异常状态是什么样的
- 有什么视觉特征（弹窗、白屏、重复内容等）

### 3. 根因分析（root_cause）
从技术角度分析导致这个异常的可能原因：
- APP层面：代码bug、逻辑问题、第三方SDK
- 网络层面：网络超时、请求失败
- 系统层面：权限问题、资源不足
- 业务层面：数据异常、状态错误

### 4. 对Agent的影响（agent_impact）
说明这个异常如何影响AI Agent的执行流程：
- 阻塞目标操作（无法点击、无法输入）
- 误导理解（内容重复、信息错误）
- 干扰判断（遮挡关键信息）
- 导致超时（等待加载）

### 5. 阻塞等级（blocking_level）
- **high**: 完全阻塞Agent执行，必须处理才能继续
- **medium**: 部分影响Agent执行，建议处理
- **low**: 轻微影响，可选处理

### 6. 建议处理方式（recommended_handling）
提供处理这个异常的具体操作建议：
- 点击关闭按钮
- 点击返回键
- 等待自动消失
- 重新加载页面
- 跳过该区域

{"注意：请结合图片内容与文件名综合判断，如果文件名与图片不符，以图片实际内容为准。" if has_image else ""}

返回纯JSON：
```json
{{
    "filename": "{filename}",
    "anomaly_description": "简洁描述（10-15字）",
    "detailed_explanation": "详细说明这个异常的具体表现...",
    "root_cause": "技术角度的根因分析...",
    "agent_impact": "对Agent执行的影响...",
    "blocking_level": "high",
    "recommended_handling": "具体的处理建议..."
}}
```"""

            # 构建消息
            if has_image:
                content = [
                    {
                        'type': 'image_url',
                        'image_url': {'url': f'data:image/png;base64,{image_base64}'}
                    },
                    {'type': 'text', 'text': prompt}
                ]
            else:
                content = prompt

            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }

            payload = {
                'model': self.model,
                'messages': [{
                    'role': 'user',
                    'content': content
                }],
                'temperature': 0.3,
                'max_tokens': 800
            }

            response = requests.post(self.api_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()

            content_text = response.json()['choices'][0]['message']['content']

            # 提取 JSON
            json_match = re.search(r'\{[\s\S]*\}', content_text)
            if json_match:
                result = json.loads(json_match.group(0))
                return result

            raise ValueError("无法解析VLM返回的结果")

        except Exception as e:
            print(f"  ⚠ 生成描述失败: {e}")
            return {
                'filename': filename,
                'error': str(e),
                'anomaly_description': '生成失败',
                'detailed_explanation': '',
                'root_cause': '',
                'agent_impact': '',
                'blocking_level': 'unknown',
                'recommended_handling': ''
            }


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='基于文件名生成异常描述工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:

  # 为指定目录的所有样本生成描述
  python generate_filename_descriptions.py \\
    --samples-dir ./data/Agent执行遇到的典型异常UI类型

  # 仅基于文件名生成（不读取图片）
  python generate_filename_descriptions.py \\
    --samples-dir ./data/Agent执行遇到的典型异常UI类型 \\
    --filename-only

  # 指定输出文件
  python generate_filename_descriptions.py \\
    --samples-dir ./data/Agent执行遇到的典型异常UI类型 \\
    --output ./descriptions.json
"""
    )

    parser.add_argument('--samples-dir', required=True,
                        help='异常样本目录')
    parser.add_argument('--filename-only', action='store_true',
                        help='仅基于文件名生成描述（不读取图片内容）')
    parser.add_argument('--output',
                        help='输出JSON文件路径（默认为samples-dir/filename_descriptions.json）')

    args = parser.parse_args()

    # 检查API密钥
    if not VLM_API_KEY:
        print("[ERROR] 需要VLM_API_KEY环境变量")
        print("请配置 .env 文件或设置环境变量")
        return

    samples_dir = Path(args.samples_dir)
    if not samples_dir.exists():
        print(f"[ERROR] 样本目录不存在: {samples_dir}")
        return

    # 扫描样本文件
    samples = []
    for ext in ['*.jpg', '*.png', '*.jpeg']:
        samples.extend(samples_dir.glob(ext))

    if not samples:
        print(f"[WARN] 未找到图片文件: {samples_dir}")
        return

    print("=" * 70)
    print("基于文件名生成异常描述")
    print("=" * 70)
    print(f"  样本目录: {samples_dir}")
    print(f"  样本数量: {len(samples)}")
    print(f"  分析模式: {'仅文件名' if args.filename_only else '文件名+图片内容'}")
    print("=" * 70)

    generator = FilenameDescriptionGenerator()

    results = []
    for i, sample_path in enumerate(samples, 1):
        filename = sample_path.name
        print(f"\n[{i}/{len(samples)}] 分析: {filename}")
        print("-" * 70)

        if args.filename_only:
            description = generator.generate_description(filename, image_path=None)
        else:
            description = generator.generate_description(filename, image_path=str(sample_path))

        if 'error' not in description:
            print(f"  异常描述: {description.get('anomaly_description', 'N/A')}")
            print(f"  阻塞等级: {description.get('blocking_level', 'N/A')}")
            print(f"  根因: {description.get('root_cause', 'N/A')[:60]}...")
            print(f"  建议: {description.get('recommended_handling', 'N/A')[:60]}...")
        else:
            print(f"  ⚠ 生成失败: {description.get('error')}")

        results.append(description)

    # 保存结果
    output_path = Path(args.output) if args.output else samples_dir / 'filename_descriptions.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 70)
    print("汇总统计")
    print("=" * 70)

    # 统计阻塞等级
    blocking_counts = {'high': 0, 'medium': 0, 'low': 0, 'unknown': 0}
    for result in results:
        level = result.get('blocking_level', 'unknown')
        blocking_counts[level] = blocking_counts.get(level, 0) + 1

    print(f"  总样本数: {len(results)}")
    print(f"  高阻塞 (high): {blocking_counts['high']}")
    print(f"  中阻塞 (medium): {blocking_counts['medium']}")
    print(f"  低阻塞 (low): {blocking_counts['low']}")
    print(f"  未知: {blocking_counts['unknown']}")

    print(f"\n  ✓ 描述已保存: {output_path}")
    print("\n请检查生成的描述是否准确。")
    print("如需修改，可直接编辑JSON文件或提供反馈。")


if __name__ == '__main__':
    main()
