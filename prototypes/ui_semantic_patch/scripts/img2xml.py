#!/usr/bin/env python3
"""
img2xml.py - 从截图提取 UI 结构

使用 VLM 分析截图，生成类似 UIAutomator 的结构化 UI-JSON。
解决无法获取真实 UIAutomator dump 的问题。
"""

import json
import base64
import argparse
import requests
import re
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from PIL import Image


# 系统提示词：引导 VLM 输出结构化 UI 信息
SYSTEM_PROMPT = """你是一个专业的 UI 结构分析专家。你的任务是分析手机 App 截图，识别所有可见的 UI 组件，并输出结构化的 JSON 格式。

## 输出格式

你必须输出一个 JSON 对象，格式如下：

```json
{
  "components": [
    {
      "index": 0,
      "class": "组件类型",
      "bounds": {"x": 左上角x, "y": 左上角y, "width": 宽度, "height": 高度},
      "text": "文本内容（如有）",
      "id": "推测的资源ID（如有）",
      "clickable": true/false,
      "contentDesc": "内容描述（如有）"
    }
  ]
}
```

## 组件类型（class）

请使用以下标准类型名称：
- StatusBar: 状态栏（时间、信号、电池等）
- NavigationBar: 导航栏/标题栏
- TextView: 普通文本
- EditText: 输入框
- Button: 按钮
- ImageView: 图片/图标
- ImageButton: 图片按钮
- RecyclerView: 列表容器
- ListItem: 列表项
- TabBar: 底部/顶部标签栏
- TabItem: 标签项
- SearchBar: 搜索框
- Dialog: 弹窗
- Toast: 轻提示
- Switch: 开关
- Checkbox: 复选框
- RadioButton: 单选按钮
- ProgressBar: 进度条
- Divider: 分割线
- Card: 卡片容器
- Avatar: 头像
- Badge: 角标/徽章

## 边界框估算规则

1. **坐标系**: 左上角为原点 (0, 0)，x 向右增加，y 向下增加
2. **精度**: 尽量精确估算像素坐标，误差控制在 ±20px 以内
3. **完整性**: 边界框应完整包含组件，不要截断

## 识别优先级

1. 先识别大的容器/区域（状态栏、导航栏、内容区、底部栏）
2. 再识别容器内的具体组件
3. 文本组件需要提取具体文字内容
4. 按钮类组件标记 clickable: true
5. 输入框标记其 placeholder 文本

## 注意事项

1. 只输出 JSON，不要任何解释
2. 确保 JSON 格式正确
3. index 从 0 开始递增
4. 所有可见组件都要识别，不要遗漏
5. 组件按从上到下、从左到右的顺序排列
"""


def encode_image(image_path: str) -> str:
    """将图片编码为 base64"""
    with open(image_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')


def get_image_info(image_path: str) -> dict:
    """获取图片信息"""
    with Image.open(image_path) as img:
        return {
            "width": img.width,
            "height": img.height,
            "format": img.format,
            "mode": img.mode
        }


def get_mime_type(image_path: str) -> str:
    """获取图片 MIME 类型"""
    suffix = Path(image_path).suffix.lower()
    mime_map = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp'
    }
    return mime_map.get(suffix, 'image/png')


def build_user_prompt(image_info: dict) -> str:
    """构建用户提示词"""
    return f"""请分析这张手机 App 截图，识别所有可见的 UI 组件。

**截图信息**:
- 分辨率: {image_info['width']} x {image_info['height']} 像素

**任务**:
1. 识别所有可见的 UI 组件
2. 估算每个组件的边界框（bounds）
3. 提取文本内容
4. 判断组件类型
5. 输出结构化 JSON

只输出 JSON，格式如下：
```json
{{
  "components": [...]
}}
```"""


def extract_json(content: str) -> dict:
    """从 VLM 输出中提取 JSON"""
    # 尝试直接解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 块
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试找到 { ... } 块
    brace_match = re.search(r'\{[\s\S]*\}', content)
    if brace_match:
        return json.loads(brace_match.group(0))

    raise ValueError(f"无法从 VLM 输出中提取 JSON: {content[:200]}...")


def call_vlm_api(
    api_key: str,
    api_url: str,
    model: str,
    image_path: str,
    image_info: dict,
    max_retries: int = 10
) -> dict:
    """调用 VLM API 提取 UI 结构（带重试和指数退避）"""
    image_base64 = encode_image(image_path)
    mime_type = get_mime_type(image_path)
    user_prompt = build_user_prompt(image_info)

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }

    payload = {
        'model': model,
        'messages': [
            {
                'role': 'system',
                'content': SYSTEM_PROMPT
            },
            {
                'role': 'user',
                'content': [
                    {
                        'type': 'image_url',
                        'image_url': {
                            'url': f'data:{mime_type};base64,{image_base64}'
                        }
                    },
                    {
                        'type': 'text',
                        'text': user_prompt
                    }
                ]
            }
        ],
        'temperature': 0.1,  # 低温度，确保输出稳定
        'max_tokens': 8192
    }

    base_wait = 5  # 基础等待时间（秒）

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                # 指数退避：5s, 10s, 20s, 40s, ...（最大60秒）
                wait_time = min(base_wait * (2 ** (attempt - 1)), 60)
                print(f"  ⏳ 等待 {wait_time}s 后重试 ({attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
            else:
                print(f"  正在调用 VLM API...")

            response = requests.post(api_url, headers=headers, json=payload, timeout=180)

            # 处理可重试的错误：429 限流 和 5xx 服务器错误
            if response.status_code == 429 or response.status_code >= 500:
                error_type = "API 限流 (429)" if response.status_code == 429 else f"服务器错误 ({response.status_code})"
                print(f"  ⚠ {error_type}，准备重试...")
                continue

            response.raise_for_status()

            result = response.json()
            content = result['choices'][0]['message']['content']

            # 提取 JSON
            ui_structure = extract_json(content)
            return ui_structure

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            print(f"  ⚠ 网络连接错误: {type(e).__name__}")
            if attempt == max_retries - 1:
                # 最后一次也不放弃，额外等待后再试
                print(f"  ⚠ 已达最大重试次数，额外等待 120s 后最后尝试...")
                time.sleep(120)
                try:
                    response = requests.post(api_url, headers=headers, json=payload, timeout=180)
                    response.raise_for_status()
                    result = response.json()
                    content = result['choices'][0]['message']['content']
                    return extract_json(content)
                except Exception as final_e:
                    raise Exception(f"网络持续不稳定，请检查网络连接: {final_e}")
        except requests.exceptions.RequestException as e:
            print(f"  ⚠ API 请求失败: {e}")
            if attempt == max_retries - 1:
                raise
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  ⚠ JSON 解析失败: {e}")
            if attempt == max_retries - 1:
                raise


def validate_and_fix_components(components: list, image_info: dict) -> list:
    """验证并修复组件数据"""
    width, height = image_info['width'], image_info['height']
    fixed_components = []

    for i, comp in enumerate(components):
        # 确保必要字段存在
        if 'bounds' not in comp:
            continue

        bounds = comp['bounds']

        # 修复边界值
        bounds['x'] = max(0, min(bounds.get('x', 0), width - 1))
        bounds['y'] = max(0, min(bounds.get('y', 0), height - 1))
        bounds['width'] = max(1, min(bounds.get('width', 100), width - bounds['x']))
        bounds['height'] = max(1, min(bounds.get('height', 50), height - bounds['y']))

        # 确保 index 存在
        comp['index'] = i

        # 确保 class 存在
        if 'class' not in comp:
            comp['class'] = 'Unknown'

        fixed_components.append(comp)

    return fixed_components


def img_to_ui_json(
    image_path: str,
    api_key: str,
    api_url: str = 'https://api.openai-next.com/v1/chat/completions',
    model: str = 'qwen-vl-max'
) -> dict:
    """
    主函数：从截图提取 UI 结构

    Args:
        image_path: 截图路径
        api_key: API 密钥
        api_url: API 端点
        model: VLM 模型名称

    Returns:
        UI-JSON 字典
    """
    # 获取图片信息
    image_info = get_image_info(image_path)
    print(f"  图片分辨率: {image_info['width']}x{image_info['height']}")

    # 调用 VLM
    ui_structure = call_vlm_api(
        api_key=api_key,
        api_url=api_url,
        model=model,
        image_path=image_path,
        image_info=image_info
    )

    # 验证和修复组件
    components = ui_structure.get('components', [])
    components = validate_and_fix_components(components, image_info)

    # 构建完整的 UI-JSON
    ui_json = {
        "metadata": {
            "source": Path(image_path).name,
            "extractionMethod": "VLM",
            "model": model,
            "timestamp": datetime.now().isoformat(),
            "resolution": {
                "width": image_info['width'],
                "height": image_info['height']
            }
        },
        "components": components,
        "componentCount": len(components)
    }

    return ui_json


def main():
    parser = argparse.ArgumentParser(
        description='从截图提取 UI 结构 (VLM 驱动)'
    )
    parser.add_argument('--image', '-i', required=True,
                        help='截图路径')
    parser.add_argument('--api-key', required=True,
                        help='API 密钥')
    parser.add_argument('--api-url',
                        default='https://api.openai-next.com/v1/chat/completions',
                        help='API 端点')
    parser.add_argument('--model',
                        default='qwen-vl-max',
                        help='VLM 模型名称')
    parser.add_argument('--output', '-o',
                        help='输出 JSON 文件路径')
    parser.add_argument('--pretty', action='store_true',
                        help='格式化输出 JSON')

    args = parser.parse_args()

    print("=" * 50)
    print("从截图提取 UI 结构")
    print("=" * 50)

    # 提取 UI 结构
    ui_json = img_to_ui_json(
        image_path=args.image,
        api_key=args.api_key,
        api_url=args.api_url,
        model=args.model
    )

    # 输出
    if args.output:
        output_path = Path(args.output)
    else:
        image_path = Path(args.image)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = image_path.parent / f"{image_path.stem}_structure_{timestamp}.json"

    indent = 2 if args.pretty else None
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(ui_json, f, ensure_ascii=False, indent=indent)

    print(f"\n✓ UI 结构提取完成: {output_path}")
    print(f"  组件数: {ui_json['componentCount']}")

    # 打印组件摘要
    print("\n组件摘要:")
    for comp in ui_json['components'][:15]:  # 最多显示15个
        text_preview = comp.get('text', '')[:20] + '...' if len(comp.get('text', '')) > 20 else comp.get('text', '')
        bounds = comp.get('bounds', {})
        print(f"  [{comp['index']:2d}] {comp['class']:<15} "
              f"({bounds.get('x', 0):4d},{bounds.get('y', 0):4d}) "
              f"{bounds.get('width', 0):4d}x{bounds.get('height', 0):<4d} "
              f"{text_preview}")

    if ui_json['componentCount'] > 15:
        print(f"  ... 还有 {ui_json['componentCount'] - 15} 个组件")


if __name__ == '__main__':
    main()
