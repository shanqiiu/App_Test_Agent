#!/usr/bin/env python3
"""
style_transfer.py - 异常UI风格迁移工具

功能：
1. 从真实异常样本提取视觉风格
2. 将风格迁移到目标截图
3. 支持弹窗、加载图标、白屏等多种异常类型

核心思路：
- 从GT样本学习：视觉风格、布局比例、色彩方案、设计元素
- 将学到的风格应用到新截图上
"""

import json
import os
import base64
import requests
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from PIL import Image

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


class StyleExtractor:
    """从真实样本提取风格特征"""

    def __init__(self, api_key: str = None, api_url: str = None, model: str = None):
        self.api_key = api_key or VLM_API_KEY
        self.api_url = api_url or VLM_API_URL
        self.model = model or VLM_MODEL
        self._cache = {}

    def extract_dialog_style(self, sample_path: str) -> Dict:
        """
        提取弹窗风格特征

        Returns:
            {
                "layout": {
                    "position": "center/top/bottom",
                    "width_ratio": 0.8,
                    "height_ratio": 0.6,
                    "padding": 20
                },
                "colors": {
                    "background": "#FFFFFF",
                    "primary": "#FF6600",
                    "secondary": "#999999",
                    "text": "#333333",
                    "button": "#FF6600"
                },
                "design": {
                    "corner_radius": "large",
                    "shadow": "prominent",
                    "border": "none/thin/thick",
                    "style": "card/fullscreen/modal"
                },
                "elements": {
                    "has_close_button": true,
                    "close_position": "top-right-outside",
                    "has_image": true,
                    "has_buttons": true,
                    "button_count": 2
                }
            }
        """
        cache_key = f"dialog_{sample_path}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            with open(sample_path, 'rb') as f:
                image_base64 = base64.b64encode(f.read()).decode('utf-8')

            prompt = """分析这个弹窗/提示界面的视觉设计特征，用于风格迁移到新场景。

## 分析维度

### 1. 布局特征
- position: 弹窗位置 (center/top/bottom/full)
- width_ratio: 弹窗宽度占屏幕比例 (0.0-1.0)
- height_ratio: 弹窗高度占屏幕比例 (0.0-1.0)
- padding: 内边距估计值(px)

### 2. 配色方案
- background: 弹窗背景色
- primary: 主色调（按钮、标题）
- secondary: 辅助色
- text: 主文字颜色
- button: 主按钮颜色

### 3. 设计风格
- corner_radius: none/small/medium/large/circular
- shadow: none/subtle/prominent
- border: none/thin/thick
- style: card（卡片）/fullscreen（全屏）/modal（模态）/toast（轻提示）

### 4. 元素特征
- has_close_button: 是否有关闭按钮
- close_position: 关闭按钮位置 (top-right/top-right-outside/top-left/bottom)
- has_image: 是否有图片
- has_buttons: 是否有操作按钮
- button_count: 按钮数量

返回纯JSON：
```json
{
    "layout": {
        "position": "center",
        "width_ratio": 0.8,
        "height_ratio": 0.6,
        "padding": 20
    },
    "colors": {
        "background": "#FFFFFF",
        "primary": "#FF6600",
        "secondary": "#999999",
        "text": "#333333",
        "button": "#FF6600"
    },
    "design": {
        "corner_radius": "large",
        "shadow": "prominent",
        "border": "none",
        "style": "card"
    },
    "elements": {
        "has_close_button": true,
        "close_position": "top-right-outside",
        "has_image": true,
        "has_buttons": true,
        "button_count": 2
    }
}
```"""

            result = self._call_vlm(image_base64, prompt)
            if result:
                self._cache[cache_key] = result
            return result

        except Exception as e:
            print(f"  ⚠ 弹窗风格提取失败: {e}")
            return self._get_default_dialog_style()

    def extract_loading_style(self, sample_path: str) -> Dict:
        """
        提取加载/白屏风格特征

        Returns:
            {
                "type": "white_screen/loading_spinner/skeleton/error_page",
                "colors": {"background": "#FFFFFF", "spinner": "#1890FF"},
                "elements": ["loading_text", "spinner", "progress_bar"],
                "message": "加载中..."
            }
        """
        cache_key = f"loading_{sample_path}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            with open(sample_path, 'rb') as f:
                image_base64 = base64.b64encode(f.read()).decode('utf-8')

            prompt = """分析这个加载/白屏/错误页面的视觉特征，用于风格迁移。

## 分析维度

### 1. 加载类型
- white_screen: 纯白屏/空白页
- loading_spinner: 加载转圈
- skeleton: 骨架屏
- error_page: 错误/失败页面
- partial_loading: 部分区域加载

### 2. 配色
- background: 背景色
- spinner: 加载图标颜色
- text: 文字颜色

### 3. 元素
- loading_text: 加载提示文字
- spinner: 旋转图标
- progress_bar: 进度条
- retry_button: 重试按钮
- error_icon: 错误图标

### 4. 提示文案
如果有加载或错误提示文字，提取出来

返回纯JSON：
```json
{
    "type": "loading_spinner",
    "colors": {
        "background": "#F5F5F5",
        "spinner": "#1890FF",
        "text": "#666666"
    },
    "elements": ["spinner", "loading_text"],
    "message": "加载中，请稍候..."
}
```"""

            result = self._call_vlm(image_base64, prompt)
            if result:
                self._cache[cache_key] = result
            return result

        except Exception as e:
            print(f"  ⚠ 加载风格提取失败: {e}")
            return self._get_default_loading_style()

    def _call_vlm(self, image_base64: str, prompt: str) -> Optional[Dict]:
        """调用VLM API"""
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

        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            return json.loads(json_match.group(0))
        return None

    def _get_default_dialog_style(self) -> Dict:
        """默认弹窗风格"""
        return {
            "layout": {
                "position": "center",
                "width_ratio": 0.8,
                "height_ratio": 0.5,
                "padding": 20
            },
            "colors": {
                "background": "#FFFFFF",
                "primary": "#1890FF",
                "secondary": "#999999",
                "text": "#333333",
                "button": "#1890FF"
            },
            "design": {
                "corner_radius": "medium",
                "shadow": "subtle",
                "border": "none",
                "style": "card"
            },
            "elements": {
                "has_close_button": True,
                "close_position": "top-right",
                "has_image": False,
                "has_buttons": True,
                "button_count": 1
            }
        }

    def _get_default_loading_style(self) -> Dict:
        """默认加载风格"""
        return {
            "type": "white_screen",
            "colors": {
                "background": "#FFFFFF",
                "spinner": "#1890FF",
                "text": "#999999"
            },
            "elements": [],
            "message": ""
        }


class StyleTransferPipeline:
    """风格迁移流水线"""

    def __init__(
        self,
        gt_templates_dir: str,
        api_key: str = None,
        api_url: str = None,
        model: str = None
    ):
        """
        初始化风格迁移流水线

        Args:
            gt_templates_dir: GT模板目录（由anomaly_sample_manager.py生成）
            api_key: VLM API密钥
            api_url: VLM API地址
            model: VLM模型
        """
        self.gt_dir = Path(gt_templates_dir)
        self.extractor = StyleExtractor(api_key, api_url, model)

        # 加载GT模板索引
        self.gt_index = self._load_gt_index()

    def _load_gt_index(self) -> Dict:
        """加载GT模板索引"""
        index = {}
        for category_dir in self.gt_dir.iterdir():
            if category_dir.is_dir():
                meta_path = category_dir / 'meta.json'
                if meta_path.exists():
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)

                    # 获取该类别的所有样本
                    samples = list(category_dir.glob('*.jpg')) + list(category_dir.glob('*.png'))
                    index[category_dir.name] = {
                        'meta': meta,
                        'samples': [str(s) for s in samples]
                    }
        return index

    def get_available_categories(self) -> List[str]:
        """获取可用的异常类别"""
        return list(self.gt_index.keys())

    def select_reference_sample(self, category: str, selector: str = 'first') -> Optional[str]:
        """
        选择参考样本

        Args:
            category: 异常类别
            selector: 选择策略 (first/random/all)

        Returns:
            样本路径
        """
        if category not in self.gt_index:
            print(f"  ⚠ 类别不存在: {category}")
            print(f"  可用类别: {', '.join(self.get_available_categories())}")
            return None

        samples = self.gt_index[category]['samples']
        if not samples:
            return None

        if selector == 'first':
            return samples[0]
        elif selector == 'random':
            import random
            return random.choice(samples)
        else:
            return samples[0]

    def transfer_dialog_style(
        self,
        target_screenshot: str,
        source_category: str = 'dialog_ad',
        instruction: str = None
    ) -> Dict:
        """
        将弹窗风格迁移到目标截图

        Args:
            target_screenshot: 目标截图路径
            source_category: 源风格类别
            instruction: 额外指令（如"生成网络错误弹窗"）

        Returns:
            {
                "source_sample": 参考样本路径,
                "source_style": 提取的风格,
                "recommendation": "使用建议"
            }
        """
        # 选择参考样本
        reference_sample = self.select_reference_sample(source_category)
        if not reference_sample:
            return None

        print(f"  参考样本: {Path(reference_sample).name}")

        # 提取风格
        style = self.extractor.extract_dialog_style(reference_sample)
        print(f"  风格: {style.get('design', {}).get('style')} / 圆角: {style.get('design', {}).get('corner_radius')}")

        return {
            'source_sample': reference_sample,
            'source_style': style,
            'recommendation': f"""
使用方式:
1. 作为参考图片: --reference {reference_sample}
2. 风格参数已提取，可传入 PatchRenderer 或 SemanticDialogGenerator
"""
        }

    def transfer_loading_style(
        self,
        target_screenshot: str,
        source_category: str = 'loading_timeout'
    ) -> Dict:
        """
        将加载/白屏风格迁移到目标截图

        Args:
            target_screenshot: 目标截图路径
            source_category: 源风格类别

        Returns:
            迁移结果和建议
        """
        reference_sample = self.select_reference_sample(source_category)
        if not reference_sample:
            return None

        print(f"  参考样本: {Path(reference_sample).name}")

        style = self.extractor.extract_loading_style(reference_sample)
        print(f"  类型: {style.get('type')}")

        return {
            'source_sample': reference_sample,
            'source_style': style,
            'recommendation': f"""
使用方式:
1. 作为参考图标: --reference-icon {reference_sample}
2. 风格参数: 背景色 {style.get('colors', {}).get('background')}, 类型 {style.get('type')}
"""
        }


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='异常UI风格迁移工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:

  # 列出可用的风格类别
  python style_transfer.py \\
    --gt-dir ../data/Agent执行遇到的典型异常UI类型/analysis/gt_templates \\
    --list-categories

  # 提取弹窗风格
  python style_transfer.py \\
    --gt-dir ../data/Agent执行遇到的典型异常UI类型/analysis/gt_templates \\
    --category dialog_ad \\
    --extract-style

  # 迁移风格到新截图
  python style_transfer.py \\
    --gt-dir ../data/Agent执行遇到的典型异常UI类型/analysis/gt_templates \\
    --target-screenshot ./new_page.png \\
    --category dialog_ad
"""
    )

    parser.add_argument('--gt-dir', required=True,
                        help='GT模板目录')
    parser.add_argument('--list-categories', action='store_true',
                        help='列出可用的风格类别')
    parser.add_argument('--category',
                        help='目标风格类别')
    parser.add_argument('--extract-style', action='store_true',
                        help='提取风格特征')
    parser.add_argument('--target-screenshot',
                        help='目标截图路径（风格迁移）')

    args = parser.parse_args()

    # 对于list-categories操作，不需要API密钥
    if not args.list_categories and not VLM_API_KEY:
        print("[ERROR] 需要 VLM_API_KEY 环境变量")
        return

    pipeline = StyleTransferPipeline(gt_templates_dir=args.gt_dir)

    if args.list_categories:
        print("\n可用的风格类别:")
        for cat in pipeline.get_available_categories():
            info = pipeline.gt_index[cat]
            print(f"  [{cat}] {info['meta'].get('description', '')} ({info['meta'].get('count', 0)} 个样本)")
        return

    if args.category and args.extract_style:
        print(f"\n提取风格: {args.category}")
        print("=" * 40)

        sample = pipeline.select_reference_sample(args.category)
        if sample:
            if 'dialog' in args.category:
                style = pipeline.extractor.extract_dialog_style(sample)
            else:
                style = pipeline.extractor.extract_loading_style(sample)

            print(json.dumps(style, ensure_ascii=False, indent=2))
        return

    if args.target_screenshot and args.category:
        print(f"\n风格迁移: {args.category} -> {args.target_screenshot}")
        print("=" * 40)

        if 'dialog' in args.category:
            result = pipeline.transfer_dialog_style(
                target_screenshot=args.target_screenshot,
                source_category=args.category
            )
        else:
            result = pipeline.transfer_loading_style(
                target_screenshot=args.target_screenshot,
                source_category=args.category
            )

        if result:
            print(result['recommendation'])

    print("\n✓ 完成！")


if __name__ == '__main__':
    main()
