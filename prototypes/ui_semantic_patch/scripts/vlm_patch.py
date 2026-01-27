#!/usr/bin/env python3
"""
vlm_patch.py - VLM 推理生成 UI-Edit-Action (JSON Patch)

使用多模态大模型分析页面结构和异常指令，输出受控的修改操作。
"""

import json
import base64
import argparse
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional


# 系统提示词：定义 VLM 的角色和输出格式
SYSTEM_PROMPT = """你是一个 UI 异常场景生成专家。你的任务是分析 App 界面，并根据用户的异常指令，输出精确的 UI 修改操作（JSON Patch）。

## 输出格式要求

你必须输出一个 JSON 对象，包含 `actions` 数组，每个 action 是以下三种类型之一：

### 1. modify - 修改现有组件
```json
{
  "type": "modify",
  "target": "组件的 id 或 index",
  "changes": {
    "text": "新文本内容",
    "textColor": "#FF0000",
    "enabled": false,
    "background": "#EEEEEE"
  }
}
```

### 2. add - 新增组件
```json
{
  "type": "add",
  "component": {
    "class": "Dialog | Toast | Loading | TextView | Button",
    "bounds": {"x": 起始x, "y": 起始y, "width": 宽度, "height": 高度},
    "text": "显示内容",
    "style": "error | warning | info | success",
    "children": []
  },
  "zIndex": 100
}
```

### 3. delete - 隐藏/移除组件
```json
{
  "type": "delete",
  "target": "组件的 id 或 index",
  "mode": "hide | blur | placeholder"
}
```

## 注意事项

1. bounds 坐标基于截图的像素坐标系（左上角为原点）
2. 新增弹窗时，需要居中显示，并考虑合适的尺寸
3. 修改文本时，确保新文本与异常场景语义一致
4. 只输出 JSON，不要输出任何解释性文字
5. 确保 JSON 格式正确，可以被直接解析
"""


def encode_image(image_path: str) -> str:
    """将图片编码为 base64"""
    with open(image_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')


def get_image_mime_type(image_path: str) -> str:
    """获取图片的 MIME 类型"""
    suffix = Path(image_path).suffix.lower()
    mime_map = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp'
    }
    return mime_map.get(suffix, 'image/png')


def build_user_prompt(ui_json: dict, instruction: str) -> str:
    """构建用户提示词"""
    resolution = ui_json.get('metadata', {}).get('resolution', {})
    width = resolution.get('width', 1080)
    height = resolution.get('height', 1920)

    # 简化组件列表用于提示
    components_summary = []
    for comp in ui_json.get('components', [])[:50]:  # 限制数量
        summary = f"[{comp.get('index')}] {comp.get('class')}"
        if comp.get('id'):
            summary += f" id={comp['id']}"
        if comp.get('text'):
            summary += f" text=\"{comp['text'][:20]}...\""if len(comp.get('text', '')) > 20 else f" text=\"{comp.get('text', '')}\""
        bounds = comp.get('bounds', {})
        summary += f" bounds=({bounds.get('x')},{bounds.get('y')},{bounds.get('width')},{bounds.get('height')})"
        components_summary.append(summary)

    prompt = f"""## 当前页面信息

**分辨率**: {width} x {height} 像素

**组件列表**:
{chr(10).join(components_summary)}

## 异常指令

{instruction}

## 任务

请分析上述页面截图和组件结构，根据异常指令生成 UI-Edit-Action (JSON Patch)。

只输出 JSON，格式如下：
```json
{{
  "actions": [...]
}}
```"""

    return prompt


def call_vlm_api(
    api_key: str,
    api_url: str,
    model: str,
    screenshot_path: str,
    user_prompt: str,
    max_retries: int = 3
) -> dict:
    """
    调用 VLM API 生成 JSON Patch
    """
    image_base64 = encode_image(screenshot_path)
    mime_type = get_image_mime_type(screenshot_path)

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
        'temperature': 0.2,
        'max_tokens': 4096
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(api_url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()

            result = response.json()
            content = result['choices'][0]['message']['content']

            # 提取 JSON 内容
            patch = extract_json(content)
            return patch

        except requests.exceptions.RequestException as e:
            print(f"API 请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                raise
        except json.JSONDecodeError as e:
            print(f"JSON 解析失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            print(f"原始内容: {content[:500]}...")
            if attempt == max_retries - 1:
                raise


def extract_json(content: str) -> dict:
    """从 VLM 输出中提取 JSON"""
    # 尝试直接解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 块
    import re
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


def generate_patch(
    api_key: str,
    api_url: str,
    model: str,
    screenshot_path: str,
    ui_json_path: str,
    instruction: str
) -> dict:
    """
    主函数：生成 UI-Edit-Action (JSON Patch)

    Args:
        api_key: API 密钥
        api_url: API 端点
        model: VLM 模型名称
        screenshot_path: 截图路径
        ui_json_path: UI-JSON 文件路径
        instruction: 异常指令

    Returns:
        UI-Edit-Action 字典
    """
    # 加载 UI-JSON
    with open(ui_json_path, 'r', encoding='utf-8') as f:
        ui_json = json.load(f)

    # 构建提示词
    user_prompt = build_user_prompt(ui_json, instruction)

    # 调用 VLM
    patch = call_vlm_api(
        api_key=api_key,
        api_url=api_url,
        model=model,
        screenshot_path=screenshot_path,
        user_prompt=user_prompt
    )

    # 添加元数据
    patch['metadata'] = {
        'instruction': instruction,
        'model': model,
        'timestamp': datetime.now().isoformat(),
        'source_ui_json': Path(ui_json_path).name
    }

    return patch


def main():
    parser = argparse.ArgumentParser(
        description='VLM 推理生成 UI-Edit-Action (JSON Patch)'
    )
    parser.add_argument('--api-key', required=True,
                        help='API 密钥')
    parser.add_argument('--api-url',
                        default='https://api.openai-next.com/v1/chat/completions',
                        help='API 端点')
    parser.add_argument('--model',
                        default='qwen-vl-max',
                        help='VLM 模型名称')
    parser.add_argument('--screenshot', '-s', required=True,
                        help='截图路径')
    parser.add_argument('--ui-json', '-u', required=True,
                        help='UI-JSON 文件路径')
    parser.add_argument('--instruction', '-i', required=True,
                        help='异常指令')
    parser.add_argument('--output', '-o',
                        help='输出 JSON 文件路径')

    args = parser.parse_args()

    # 生成 Patch
    patch = generate_patch(
        api_key=args.api_key,
        api_url=args.api_url,
        model=args.model,
        screenshot_path=args.screenshot,
        ui_json_path=args.ui_json,
        instruction=args.instruction
    )

    # 输出
    if args.output:
        output_path = Path(args.output)
    else:
        screenshot_path = Path(args.screenshot)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = screenshot_path.parent / f"{screenshot_path.stem}_patch_{timestamp}.json"

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(patch, f, ensure_ascii=False, indent=2)

    print(f"✓ Patch 生成完成: {output_path}")
    print(f"  操作数: {len(patch.get('actions', []))}")
    for i, action in enumerate(patch.get('actions', [])):
        print(f"  [{i+1}] {action.get('type')}: {action.get('target', action.get('component', {}).get('class', 'N/A'))}")


if __name__ == '__main__':
    main()
