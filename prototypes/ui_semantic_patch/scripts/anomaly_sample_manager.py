#!/usr/bin/env python3
"""
anomaly_sample_manager.py - 异常样本管理与聚类工具

功能：
1. 自动分析异常样本并根据根因聚类
2. 提取样本的视觉风格特征（作为GT模板或参考）
3. 支持风格迁移到新场景
"""

import json
import os
import base64
import requests
import re
from pathlib import Path
from typing import Dict, List, Optional
from PIL import Image

# 从环境变量读取API配置
VLM_API_KEY = os.environ.get('VLM_API_KEY')
VLM_API_URL = os.environ.get('VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions')
VLM_MODEL = os.environ.get('VLM_MODEL', 'gpt-4o')


class AnomalySampleManager:
    """异常样本管理器 - 聚类、分析、风格迁移"""

    # 异常类型映射（根据文件名关键词识别）
    ANOMALY_CATEGORIES = {
        'dialog_ad': {
            'keywords': ['广告', '弹出', 'ad', '推广'],
            'description': '广告弹窗',
            'en_name': 'Advertisement Dialog'
        },
        'dialog_tip': {
            'keywords': ['提示', '教程', 'tip', 'tutorial', 'guide'],
            'description': '提示/教程弹窗',
            'en_name': 'Tip Dialog'
        },
        'dialog_system': {
            'keywords': ['权限', '设置', 'permission', 'setting'],
            'description': '系统/权限弹窗',
            'en_name': 'System Dialog'
        },
        'loading_timeout': {
            'keywords': ['加载', '超时', 'loading', 'timeout', '白屏'],
            'description': '加载超时/白屏',
            'en_name': 'Loading Timeout'
        },
        'content_error': {
            'keywords': ['重复', '遮挡', '错误', 'error', 'duplicate', 'overlap'],
            'description': '内容错误/重复',
            'en_name': 'Content Error'
        },
        'ui_interference': {
            'keywords': ['干扰', '按钮', 'interference', 'button'],
            'description': 'UI干扰元素',
            'en_name': 'UI Interference'
        },
        'normal': {
            'keywords': ['正常', 'normal'],
            'description': '正常界面',
            'en_name': 'Normal'
        }
    }

    def __init__(self, samples_dir: str, output_dir: str = None):
        """
        初始化样本管理器

        Args:
            samples_dir: 异常样本目录
            output_dir: 输出目录（分类结果、特征库等）
        """
        self.samples_dir = Path(samples_dir)
        self.output_dir = Path(output_dir) if output_dir else self.samples_dir / 'analysis'
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.api_key = VLM_API_KEY
        self.api_url = VLM_API_URL
        self.model = VLM_MODEL

    def scan_samples(self) -> List[Dict]:
        """
        扫描样本目录，返回样本列表

        Returns:
            [
                {
                    'path': 文件路径,
                    'filename': 文件名,
                    'category': 自动分类,
                    'size': 文件大小
                },
                ...
            ]
        """
        samples = []
        for ext in ['*.jpg', '*.png', '*.jpeg']:
            for file_path in self.samples_dir.glob(ext):
                # 根据文件名自动分类
                category = self._classify_by_filename(file_path.stem)

                samples.append({
                    'path': str(file_path),
                    'filename': file_path.name,
                    'category': category,
                    'size': file_path.stat().st_size
                })

        return samples

    def _classify_by_filename(self, filename: str) -> str:
        """根据文件名关键词自动分类"""
        filename_lower = filename.lower()

        # 优先级排序（避免误分类）
        priority_categories = [
            'normal',
            'dialog_ad',
            'dialog_tip',
            'dialog_system',
            'loading_timeout',
            'content_error',
            'ui_interference'
        ]

        for category in priority_categories:
            keywords = self.ANOMALY_CATEGORIES[category]['keywords']
            if any(keyword in filename_lower for keyword in keywords):
                return category

        return 'unknown'

    def analyze_sample_with_vlm(self, image_path: str) -> Dict:
        """
        使用VLM深度分析样本

        提取：
        - 异常类型细分
        - 视觉风格特征
        - 关键UI元素
        - 根因分析

        Args:
            image_path: 样本图片路径

        Returns:
            {
                "anomaly_type": "dialog_ad / dialog_tip / loading_error / ...",
                "root_cause": "根因描述",
                "visual_style": {
                    "dialog_style": "淘宝风格/微信风格/通用",
                    "primary_color": "#FF6600",
                    "corner_radius": "large",
                    "shadow": "strong"
                },
                "key_elements": ["广告图片", "关闭按钮", "立即查看按钮"],
                "agent_impact": "阻塞等级 (low/medium/high)",
                "recommended_action": "建议的处理方式"
            }
        """
        try:
            with open(image_path, 'rb') as f:
                image_base64 = base64.b64encode(f.read()).decode('utf-8')

            prompt = """分析这个Agent执行时遇到的UI异常样本，提取关键信息用于样本聚类和风格迁移。

## 分析维度

### 1. 异常类型识别
- **dialog_ad**: 广告弹窗（推广、活动、红包）
- **dialog_tip**: 提示/教程弹窗（使用说明、新功能引导）
- **dialog_system**: 系统弹窗（权限申请、设置确认）
- **loading_timeout**: 加载超时（白屏、转圈、无响应）
- **content_error**: 内容错误（信息重复、显示异常）
- **ui_interference**: UI干扰元素（浮层、悬浮按钮遮挡）
- **network_error**: 网络异常（断网提示、请求失败）

### 2. 根因分析
简要说明导致Agent执行阻塞的原因。

### 3. 视觉风格特征（用于风格迁移）
- APP风格识别（淘宝/京东/微信/抖音/通用）
- 主色调
- 圆角风格（small/medium/large/circular）
- 阴影效果（none/subtle/prominent）

### 4. 关键UI元素
列出图中关键元素（如：广告图片、关闭按钮、"立即查看"按钮）

### 5. 对Agent影响
- **high**: 完全阻塞，必须处理
- **medium**: 部分阻塞，建议处理
- **low**: 轻微影响

### 6. 建议处理方式
- 点击关闭按钮
- 点击返回键
- 等待自动消失
- 重新加载页面

返回纯JSON：
```json
{
    "anomaly_type": "dialog_ad",
    "root_cause": "电商APP启动时弹出新人红包广告",
    "visual_style": {
        "app_style": "淘宝",
        "primary_color": "#FF6600",
        "corner_radius": "large",
        "shadow": "prominent"
    },
    "key_elements": ["红包图片", "右上角关闭按钮", "立即领取按钮"],
    "agent_impact": "high",
    "recommended_action": "点击右上角关闭按钮或点击返回键"
}
```"""

            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }

            payload = {
                'model': self.model,
                'messages': [{
                    'role': 'user',
                    'content': [
                        {
                            'type': 'image_url',
                            'image_url': {'url': f'data:image/png;base64,{image_base64}'}
                        },
                        {'type': 'text', 'text': prompt}
                    ]
                }],
                'temperature': 0.3,
                'max_tokens': 600
            }

            response = requests.post(self.api_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()

            content = response.json()['choices'][0]['message']['content']

            # 提取 JSON
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                analysis = json.loads(json_match.group(0))
                return analysis

            raise ValueError("无法解析VLM返回的分析结果")

        except Exception as e:
            print(f"  ⚠ VLM分析失败: {e}")
            return None

    def cluster_samples(self, deep_analysis: bool = False) -> Dict:
        """
        聚类分析所有样本

        Args:
            deep_analysis: 是否使用VLM深度分析（慢但准确）

        Returns:
            {
                "summary": {
                    "total": 10,
                    "by_category": {"dialog_ad": 2, "dialog_tip": 3, ...}
                },
                "samples": [样本列表],
                "feature_library": {特征库，用于风格迁移}
            }
        """
        print("=" * 60)
        print("异常样本聚类分析")
        print("=" * 60)

        samples = self.scan_samples()
        print(f"  扫描到 {len(samples)} 个样本")

        # 统计分类
        category_counts = {}
        for sample in samples:
            category = sample['category']
            category_counts[category] = category_counts.get(category, 0) + 1

        # VLM深度分析（可选）
        if deep_analysis and self.api_key:
            print("\n  开始VLM深度分析...")
            for i, sample in enumerate(samples, 1):
                print(f"    [{i}/{len(samples)}] 分析: {sample['filename']}")
                analysis = self.analyze_sample_with_vlm(sample['path'])
                if analysis:
                    sample['vlm_analysis'] = analysis
                    # 使用VLM分析结果更新分类
                    sample['category'] = analysis.get('anomaly_type', sample['category'])

        # 构建特征库（按类别组织）
        feature_library = {}
        for category, info in self.ANOMALY_CATEGORIES.items():
            category_samples = [s for s in samples if s['category'] == category]
            if category_samples:
                feature_library[category] = {
                    'description': info['description'],
                    'count': len(category_samples),
                    'samples': [
                        {
                            'path': s['path'],
                            'filename': s['filename']
                        } for s in category_samples
                    ]
                }

        result = {
            'summary': {
                'total': len(samples),
                'by_category': category_counts
            },
            'samples': samples,
            'feature_library': feature_library
        }

        # 保存结果
        output_path = self.output_dir / 'sample_clustering.json'
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"\n  ✓ 聚类结果已保存: {output_path}")

        # 打印汇总
        print("\n" + "=" * 60)
        print("聚类汇总")
        print("=" * 60)
        for category, count in category_counts.items():
            desc = self.ANOMALY_CATEGORIES.get(category, {}).get('description', '未分类')
            print(f"  [{category:20s}] {count:2d} 个样本 - {desc}")

        return result

    def export_gt_templates(self, clustering_result: Dict, category: str = None):
        """
        导出GT模板（用于PatchRenderer）

        Args:
            clustering_result: 聚类结果
            category: 指定类别（不指定则导出全部）
        """
        gt_dir = self.output_dir / 'gt_templates'
        gt_dir.mkdir(exist_ok=True)

        feature_lib = clustering_result.get('feature_library', {})

        categories_to_export = [category] if category else feature_lib.keys()

        for cat in categories_to_export:
            if cat not in feature_lib:
                continue

            cat_info = feature_lib[cat]
            cat_dir = gt_dir / cat
            cat_dir.mkdir(exist_ok=True)

            # 复制样本到GT目录
            for sample in cat_info['samples']:
                src = Path(sample['path'])
                dst = cat_dir / src.name
                if src.exists():
                    import shutil
                    shutil.copy(src, dst)

            # 创建元数据
            meta = {
                'category': cat,
                'description': cat_info['description'],
                'count': cat_info['count'],
                'usage': f'--gt-dir {gt_dir} 或 --reference-icon {cat_dir}/xxx.jpg'
            }

            with open(cat_dir / 'meta.json', 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)

        print(f"\n  ✓ GT模板已导出: {gt_dir}")
        print(f"  使用方法: --gt-dir {gt_dir} 或 --reference-icon {gt_dir}/category/sample.jpg")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='异常样本管理与聚类工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:

  # 快速聚类（仅基于文件名）
  python anomaly_sample_manager.py --samples-dir ./data/Agent执行遇到的典型异常UI类型

  # 深度分析（使用VLM）
  python anomaly_sample_manager.py \\
    --samples-dir ./data/Agent执行遇到的典型异常UI类型 \\
    --deep-analysis

  # 导出GT模板
  python anomaly_sample_manager.py \\
    --samples-dir ./data/Agent执行遇到的典型异常UI类型 \\
    --export-gt
"""
    )

    parser.add_argument('--samples-dir', required=True,
                        help='异常样本目录')
    parser.add_argument('--output-dir',
                        help='输出目录（默认为samples-dir/analysis）')
    parser.add_argument('--deep-analysis', action='store_true',
                        help='使用VLM深度分析（需要API密钥）')
    parser.add_argument('--export-gt', action='store_true',
                        help='导出GT模板供PatchRenderer使用')

    args = parser.parse_args()

    # 检查API密钥
    if args.deep_analysis and not VLM_API_KEY:
        print("[ERROR] 深度分析需要VLM_API_KEY环境变量")
        return

    manager = AnomalySampleManager(
        samples_dir=args.samples_dir,
        output_dir=args.output_dir
    )

    # 执行聚类
    result = manager.cluster_samples(deep_analysis=args.deep_analysis)

    # 导出GT模板
    if args.export_gt:
        manager.export_gt_templates(result)

    print("\n✓ 完成！")


if __name__ == '__main__':
    main()
