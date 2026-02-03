#!/usr/bin/env python3
"""
meta_loader.py - GT模板元数据加载器

功能：
1. 读取异常样本的meta.json文件
2. 提取语义描述和视觉特征
3. 构建用于AI生成的结构化prompt
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class MetaLoader:
    """GT模板元数据加载器"""

    def __init__(self, gt_templates_dir: str):
        """
        初始化加载器

        Args:
            gt_templates_dir: GT模板根目录，如 "./data/Agent执行遇到的典型异常UI类型/analysis/gt_templates"
        """
        self.gt_dir = Path(gt_templates_dir)
        self.categories = self._scan_categories()

    def _scan_categories(self) -> Dict[str, Dict]:
        """扫描所有类别及其meta.json"""
        categories = {}

        if not self.gt_dir.exists():
            print(f"  ⚠ GT模板目录不存在: {self.gt_dir}")
            return categories

        for category_dir in self.gt_dir.iterdir():
            if not category_dir.is_dir():
                continue

            meta_path = category_dir / 'meta.json'
            if meta_path.exists():
                try:
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                    categories[category_dir.name] = {
                        'path': str(category_dir),
                        'meta': meta
                    }
                except Exception as e:
                    print(f"  ⚠ 读取meta.json失败: {meta_path} - {e}")

        return categories

    def list_categories(self) -> List[str]:
        """列出所有可用的异常类别"""
        return list(self.categories.keys())

    def list_samples(self, category: str) -> List[str]:
        """列出指定类别的所有样本"""
        if category not in self.categories:
            return []

        meta = self.categories[category]['meta']
        samples = meta.get('samples', {})
        return list(samples.keys())

    def load_sample_meta(
        self,
        category: str,
        sample_name: str
    ) -> Optional[Dict]:
        """
        加载指定样本的元数据

        Args:
            category: 类别名称，如 "弹窗覆盖原UI"
            sample_name: 样本文件名，如 "弹出广告.jpg"

        Returns:
            {
                "anomaly_type": "promotional_dialog",
                "anomaly_description": "店铺详情页中央弹出红色优惠券领取弹窗",
                "visual_features": {...},
                "generation_template": {...}
            }
        """
        if category not in self.categories:
            print(f"  ⚠ 类别不存在: {category}")
            print(f"  可用类别: {', '.join(self.list_categories())}")
            return None

        meta = self.categories[category]['meta']
        samples = meta.get('samples', {})

        if sample_name not in samples:
            print(f"  ⚠ 样本不存在: {sample_name}")
            print(f"  可用样本: {', '.join(samples.keys())}")
            return None

        return samples[sample_name]

    def get_sample_path(
        self,
        category: str,
        sample_name: str
    ) -> Optional[str]:
        """获取样本文件的完整路径"""
        if category not in self.categories:
            return None

        category_path = Path(self.categories[category]['path'])
        sample_path = category_path / sample_name

        if sample_path.exists():
            return str(sample_path)
        return None

    def extract_semantic_prompt(
        self,
        category: str,
        sample_name: str,
        target_page_context: str = None
    ) -> Optional[str]:
        """
        从meta.json提取语义描述，构建AI生成prompt

        Args:
            category: 类别名称
            sample_name: 样本文件名
            target_page_context: 目标页面的语义上下文（可选）

        Returns:
            结构化的prompt文本
        """
        sample_meta = self.load_sample_meta(category, sample_name)
        if not sample_meta:
            return None

        # 提取核心语义信息
        anomaly_type = sample_meta.get('anomaly_type', 'unknown')
        anomaly_desc = sample_meta.get('anomaly_description', '')
        visual_features = sample_meta.get('visual_features', {})
        gen_template = sample_meta.get('generation_template', {})

        # 构建结构化prompt
        prompt_parts = []

        # 1. 异常类型和描述
        prompt_parts.append("## 异常类型")
        prompt_parts.append(f"- 类型: {anomaly_type}")
        prompt_parts.append(f"- 描述: {anomaly_desc}")
        prompt_parts.append("")

        # 2. 视觉风格要求（从visual_features提取）
        prompt_parts.append("## 视觉风格要求（精确匹配参考图）")

        app_style = visual_features.get('app_style', '通用')
        prompt_parts.append(f"- APP风格: {app_style}")

        if 'primary_color' in visual_features:
            prompt_parts.append(f"- 主色调: {visual_features['primary_color']}")

        if 'background' in visual_features:
            prompt_parts.append(f"- 背景: {visual_features['background']}")

        if 'dialog_position' in visual_features:
            prompt_parts.append(f"- 弹窗位置: {visual_features['dialog_position']}")

        if 'dialog_size_ratio' in visual_features:
            size_ratio = visual_features['dialog_size_ratio']
            if isinstance(size_ratio, dict):
                prompt_parts.append(f"- 弹窗尺寸比例: 宽度={size_ratio.get('width', 0.8)}, 高度={size_ratio.get('height', 0.5)}")

        if 'overlay_enabled' in visual_features:
            overlay = visual_features['overlay_enabled']
            opacity = visual_features.get('overlay_opacity', 0.7)
            if overlay:
                prompt_parts.append(f"- 遮罩层: 启用，不透明度={opacity}")
            else:
                prompt_parts.append("- 遮罩层: 无")

        if 'close_button_position' in visual_features:
            close_pos = visual_features['close_button_position']
            close_style = visual_features.get('close_button_style', 'default')
            prompt_parts.append(f"- 关闭按钮: {close_pos}, 样式={close_style}")

        if 'main_button_text' in visual_features:
            prompt_parts.append(f"- 主按钮文字: \"{visual_features['main_button_text']}\"")

        # 特殊元素
        if 'special_elements' in visual_features:
            elements = visual_features['special_elements']
            prompt_parts.append(f"- 特殊元素: {', '.join(elements)}")

        prompt_parts.append("")

        # 3. 生成要点（从generation_template提取）
        if gen_template:
            instruction = gen_template.get('instruction', '')
            key_points = gen_template.get('key_points', [])

            if instruction:
                prompt_parts.append("## 生成指令")
                prompt_parts.append(instruction)
                prompt_parts.append("")

            if key_points:
                prompt_parts.append("## 设计要点（必须包含）")
                for i, point in enumerate(key_points, 1):
                    prompt_parts.append(f"{i}. {point}")
                prompt_parts.append("")

        # 4. 目标页面上下文（如果提供）
        if target_page_context:
            prompt_parts.append("## 目标页面上下文")
            prompt_parts.append(target_page_context)
            prompt_parts.append("")

        return '\n'.join(prompt_parts)

    def extract_visual_features_dict(
        self,
        category: str,
        sample_name: str
    ) -> Optional[Dict]:
        """
        提取纯视觉特征字典（用于代码渲染）

        Returns:
            {
                "primary_color": "#FF1744",
                "dialog_position": "center",
                "dialog_width_ratio": 0.8,
                "dialog_height_ratio": 0.4,
                ...
            }
        """
        sample_meta = self.load_sample_meta(category, sample_name)
        if not sample_meta:
            return None

        visual_features = sample_meta.get('visual_features', {})

        # 展开嵌套的字典（如dialog_size_ratio）
        flat_features = {}
        for key, value in visual_features.items():
            if key == 'dialog_size_ratio' and isinstance(value, dict):
                flat_features['dialog_width_ratio'] = value.get('width', 0.8)
                flat_features['dialog_height_ratio'] = value.get('height', 0.5)
            else:
                flat_features[key] = value

        return flat_features

    def auto_select_sample(
        self,
        category: str,
        anomaly_keyword: str = None
    ) -> Optional[Tuple[str, Dict]]:
        """
        根据关键词自动选择最匹配的样本

        Args:
            category: 类别名称
            anomaly_keyword: 异常关键词，如"广告"、"权限"、"教程"

        Returns:
            (sample_name, sample_meta) 或 None
        """
        if category not in self.categories:
            return None

        meta = self.categories[category]['meta']
        samples = meta.get('samples', {})

        if not samples:
            return None

        # 如果没有关键词，返回第一个样本
        if not anomaly_keyword:
            first_sample = next(iter(samples.items()))
            return first_sample[0], first_sample[1]

        # 根据关键词匹配
        keyword_lower = anomaly_keyword.lower()
        for sample_name, sample_meta in samples.items():
            anomaly_desc = sample_meta.get('anomaly_description', '').lower()
            anomaly_type = sample_meta.get('anomaly_type', '').lower()

            if keyword_lower in anomaly_desc or keyword_lower in anomaly_type or keyword_lower in sample_name.lower():
                return sample_name, sample_meta

        # 没找到匹配，返回第一个
        first_sample = next(iter(samples.items()))
        return first_sample[0], first_sample[1]


def main():
    """测试用例"""
    import os
    from pathlib import Path

    # 查找GT模板目录
    script_dir = Path(__file__).parent.parent
    gt_dir = script_dir.parent / 'data' / 'Agent执行遇到的典型异常UI类型' / 'analysis' / 'gt_templates'

    if not gt_dir.exists():
        print(f"GT模板目录不存在: {gt_dir}")
        return

    print("=" * 60)
    print("MetaLoader 测试")
    print("=" * 60)

    loader = MetaLoader(str(gt_dir))

    # 1. 列出所有类别
    print("\n可用类别:")
    for cat in loader.list_categories():
        samples = loader.list_samples(cat)
        print(f"  [{cat}] - {len(samples)} 个样本")

    # 2. 加载一个样本的元数据
    print("\n" + "=" * 60)
    print("示例：加载'弹窗覆盖原UI/弹出广告.jpg'")
    print("=" * 60)

    sample_meta = loader.load_sample_meta('弹窗覆盖原UI', '弹出广告.jpg')
    if sample_meta:
        print(f"\n异常类型: {sample_meta.get('anomaly_type')}")
        print(f"异常描述: {sample_meta.get('anomaly_description')}")
        print(f"\n视觉特征:")
        for key, value in sample_meta.get('visual_features', {}).items():
            print(f"  {key}: {value}")

    # 3. 提取语义prompt
    print("\n" + "=" * 60)
    print("生成的语义Prompt:")
    print("=" * 60)

    prompt = loader.extract_semantic_prompt(
        '弹窗覆盖原UI',
        '弹出广告.jpg',
        target_page_context="目标页面: 电商商品详情页"
    )
    if prompt:
        print(prompt)

    # 4. 自动选择样本
    print("\n" + "=" * 60)
    print("自动选择测试:")
    print("=" * 60)

    result = loader.auto_select_sample('弹窗覆盖原UI', '权限')
    if result:
        sample_name, sample_meta = result
        print(f"  关键词='权限' → 匹配到: {sample_name}")
        print(f"  异常类型: {sample_meta.get('anomaly_type')}")


if __name__ == '__main__':
    main()
