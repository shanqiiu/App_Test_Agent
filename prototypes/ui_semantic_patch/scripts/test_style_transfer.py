#!/usr/bin/env python3
"""
测试 VLM 风格迁移功能

验证 _analyze_reference_style() 是否能从参考图提取正确的风格参数
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量
env_path = Path(__file__).parent.parent.parent.parent / '.env'
load_dotenv(env_path)

# 设置路径
sys.path.insert(0, str(Path(__file__).parent))

from content_duplicate_renderer import ContentDuplicateRenderer

def test_style_extraction():
    """测试从参考图提取风格参数"""

    # 参考图路径
    reference_path = Path(__file__).parent.parent / 'data' / 'Agent执行遇到的典型异常UI类型' / 'analysis' / 'gt_templates' / '内容歧义、重复' / '部分信息重复.jpg'

    if not reference_path.exists():
        print(f"错误: 参考图不存在 {reference_path}")
        return

    print(f"参考图: {reference_path}")
    print("=" * 60)

    # API配置
    api_key = os.environ.get('VLM_API_KEY')
    vlm_api_url = os.environ.get('VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions')
    vlm_model = os.environ.get('VLM_MODEL', 'gpt-4o')

    if not api_key:
        print("错误: 未设置 VLM_API_KEY 环境变量")
        return

    print(f"API URL: {vlm_api_url}")
    print(f"Model: {vlm_model}")
    print("=" * 60)

    # 初始化渲染器
    renderer = ContentDuplicateRenderer(
        api_key=api_key,
        vlm_api_url=vlm_api_url,
        vlm_model=vlm_model
    )

    # 测试风格提取
    print("\n正在分析参考图风格...")
    style = renderer._analyze_reference_style(str(reference_path))

    if style:
        print("\n✓ 风格提取成功!")
        print("-" * 40)
        for key, value in style.items():
            print(f"  {key}: {value}")
        print("-" * 40)

        # 验证关键参数
        expected_keys = [
            'background_color',
            'primary_color',
            'grid_columns',
            'has_vip_badge',
            'overlay_opacity'
        ]

        missing = [k for k in expected_keys if k not in style]
        if missing:
            print(f"\n⚠ 缺少的参数: {missing}")
        else:
            print("\n✓ 所有关键参数都已提取")
    else:
        print("\n✗ 风格提取失败")


def test_pil_rendering_with_style():
    """测试使用提取的风格参数进行 PIL 渲染"""
    from PIL import Image

    print("\n" + "=" * 60)
    print("测试 PIL 渲染（带风格参数）")
    print("=" * 60)

    # API配置
    api_key = os.environ.get('VLM_API_KEY')
    vlm_api_url = os.environ.get('VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions')
    vlm_model = os.environ.get('VLM_MODEL', 'gpt-4o')

    # 参考图路径
    reference_path = Path(__file__).parent.parent / 'data' / 'Agent执行遇到的典型异常UI类型' / 'analysis' / 'gt_templates' / '内容歧义、重复' / '部分信息重复.jpg'

    # 初始化渲染器
    renderer = ContentDuplicateRenderer(
        api_key=api_key,
        vlm_api_url=vlm_api_url,
        vlm_model=vlm_model
    )

    # 提取风格
    print("提取参考图风格...")
    reference_style = renderer._analyze_reference_style(str(reference_path))

    if not reference_style:
        print("使用默认风格")
        reference_style = {}

    # 模拟组件分析结果
    component_analysis = {
        'component_type': 'episode_selector',
        'items': ['1', '2', '3', '4', '5', '6'],
        'title': '玉茗茶骨',
        'total_count': '36集全',
        'style_hints': reference_style
    }

    meta_features = {
        'primary_color': '#FF6600',
        'background': '#1A1A1A'
    }

    # 生成内容
    print("生成底部浮层内容...")
    content_img = renderer._generate_expanded_content_pil(
        component_analysis=component_analysis,
        meta_features=meta_features,
        target_width=1080,
        target_height=800,
        reference_style=reference_style
    )

    if content_img:
        output_path = Path(__file__).parent / 'test_output' / 'style_transfer_test.png'
        output_path.parent.mkdir(exist_ok=True)
        content_img.save(str(output_path))
        print(f"\n✓ 渲染结果保存至: {output_path}")
    else:
        print("\n✗ PIL渲染失败")


if __name__ == '__main__':
    test_style_extraction()
    test_pil_rendering_with_style()
