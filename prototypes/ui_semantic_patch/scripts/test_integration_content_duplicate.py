#!/usr/bin/env python3
"""
完整集成测试 - 内容重复异常渲染（含 VLM 风格迁移）

测试流程:
1. 使用参考图提取风格参数
2. 分析目标截图组件
3. 生成带风格迁移的底部浮层
4. 合成最终异常图像
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
from PIL import Image

# 加载环境变量
env_path = Path(__file__).parent.parent.parent.parent / '.env'
load_dotenv(env_path)

# 设置路径
sys.path.insert(0, str(Path(__file__).parent))

from content_duplicate_renderer import ContentDuplicateRenderer


def test_full_integration():
    """完整集成测试"""

    print("=" * 60)
    print("内容重复异常渲染 - 完整集成测试（VLM风格迁移）")
    print("=" * 60)

    # 路径配置
    base_dir = Path(__file__).parent.parent
    gt_dir = base_dir / 'data' / 'Agent执行遇到的典型异常UI类型' / 'analysis' / 'gt_templates'
    reference_path = gt_dir / '内容歧义、重复' / '部分信息重复.jpg'

    # 使用调试截图或创建测试图像
    debug_screenshot = Path(__file__).parent / 'debug_dialog_output' / 'debug_1_screenshot_before.png'

    if debug_screenshot.exists():
        screenshot_path = debug_screenshot
        print(f"使用现有截图: {screenshot_path}")
    else:
        # 创建测试图像
        test_img = Image.new('RGB', (1080, 2400), (30, 30, 30))
        test_path = Path(__file__).parent / 'test_output' / 'test_screenshot.png'
        test_path.parent.mkdir(exist_ok=True)
        test_img.save(str(test_path))
        screenshot_path = test_path
        print(f"创建测试截图: {screenshot_path}")

    print(f"参考图: {reference_path}")
    print("-" * 60)

    # API配置
    api_key = os.environ.get('VLM_API_KEY')
    vlm_api_url = os.environ.get('VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions')
    vlm_model = os.environ.get('VLM_MODEL', 'gpt-4o')

    if not api_key:
        print("错误: 未设置 VLM_API_KEY")
        return False

    # 初始化渲染器
    renderer = ContentDuplicateRenderer(
        api_key=api_key,
        vlm_api_url=vlm_api_url,
        vlm_model=vlm_model
    )

    # 模拟 UI-JSON（通常由 Stage 2 生成）
    ui_json = {
        'components': [
            {
                'text': '选集',
                'class': 'android.widget.TextView',
                'bounds': {'x': 50, 'y': 800, 'width': 980, 'height': 60}
            },
            {
                'text': '1',
                'class': 'android.widget.Button',
                'bounds': {'x': 50, 'y': 870, 'width': 150, 'height': 70}
            },
            {
                'text': '2',
                'class': 'android.widget.Button',
                'bounds': {'x': 220, 'y': 870, 'width': 150, 'height': 70}
            }
        ]
    }

    # Meta 特性配置
    meta_features = {
        'anomaly_type': 'ui_duplicate_display',
        'duplicate_mode': 'expanded_view',
        'duplicate_element': '选集',
        'primary_color': '#FF6600',
        'background': '#1A1A1A',
        'overlay_enabled': True,
        'overlay_opacity': 0.5,
        'close_button_position': 'top-right',
        'close_button_style': 'circle_x'
    }

    # 执行渲染
    print("\n正在渲染内容重复异常（带风格迁移）...")
    screenshot_img = Image.open(screenshot_path)

    result_img = renderer.render_content_duplicate(
        screenshot=screenshot_img,
        screenshot_path=str(screenshot_path),
        ui_json=ui_json,
        instruction="选集控件处显示重复列表",
        meta_features=meta_features,
        mode='expanded_view',
        reference_path=str(reference_path)
    )

    if result_img:
        output_path = Path(__file__).parent / 'test_output' / 'integration_test_result.png'
        output_path.parent.mkdir(exist_ok=True)
        result_img.save(str(output_path))
        print(f"\n✓ 渲染成功!")
        print(f"  输出: {output_path}")
        print(f"  尺寸: {result_img.size}")
        return True
    else:
        print("\n✗ 渲染失败")
        return False


def compare_outputs():
    """对比不同配置的输出效果"""

    print("\n" + "=" * 60)
    print("对比测试：默认风格 vs VLM风格迁移")
    print("=" * 60)

    # API配置
    api_key = os.environ.get('VLM_API_KEY')
    vlm_api_url = os.environ.get('VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions')
    vlm_model = os.environ.get('VLM_MODEL', 'gpt-4o')

    # 参考图
    base_dir = Path(__file__).parent.parent
    reference_path = base_dir / 'data' / 'Agent执行遇到的典型异常UI类型' / 'analysis' / 'gt_templates' / '内容歧义、重复' / '部分信息重复.jpg'

    # 初始化渲染器
    renderer = ContentDuplicateRenderer(
        api_key=api_key,
        vlm_api_url=vlm_api_url,
        vlm_model=vlm_model
    )

    # 组件分析（模拟）
    component_analysis = {
        'component_type': 'episode_selector',
        'items': ['1', '2', '3', '4', '5', '6'],
        'title': '玉茗茶骨',
        'total_count': '36集全',
        'style_hints': {}
    }

    meta_features = {
        'primary_color': '#FF6600',
        'background': '#1A1A1A'
    }

    output_dir = Path(__file__).parent / 'test_output'
    output_dir.mkdir(exist_ok=True)

    # 1. 默认风格
    print("\n生成默认风格...")
    default_img = renderer._generate_expanded_content_pil(
        component_analysis=component_analysis,
        meta_features=meta_features,
        target_width=1080,
        target_height=800,
        reference_style=None
    )
    if default_img:
        default_img.save(str(output_dir / 'compare_default.png'))
        print("  ✓ 保存: compare_default.png")

    # 2. VLM风格迁移
    print("\n提取参考图风格...")
    reference_style = renderer._analyze_reference_style(str(reference_path))

    if reference_style:
        print(f"  提取到 {len(reference_style)} 个风格参数")
        styled_img = renderer._generate_expanded_content_pil(
            component_analysis=component_analysis,
            meta_features=meta_features,
            target_width=1080,
            target_height=800,
            reference_style=reference_style
        )
        if styled_img:
            styled_img.save(str(output_dir / 'compare_styled.png'))
            print("  ✓ 保存: compare_styled.png")

        # 保存提取的风格参数
        with open(output_dir / 'extracted_style.json', 'w', encoding='utf-8') as f:
            json.dump(reference_style, f, indent=2, ensure_ascii=False)
        print("  ✓ 保存: extracted_style.json")

    print("\n对比测试完成!")
    print(f"输出目录: {output_dir}")


if __name__ == '__main__':
    success = test_full_integration()
    if success:
        compare_outputs()
