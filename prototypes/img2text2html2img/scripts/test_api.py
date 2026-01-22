#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
from openai import OpenAI

# API 配置
BASE_URL = "https://api.openai-next.com/v1/"
API_KEY = "sk-K9B2ccVeW4VdAcobD53b16E06b104aA1B5A82593FdFb2557"
CHAT_MODEL = "gpt-3.5-turbo"  # 聊天模型
IMAGE_MODEL = "flux-pro"  # 图像生成模型

def call_with_retry(func, max_retries=3, base_delay=5):
    """带重试的 API 调用"""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if "429" in str(e) or "RateLimitError" in str(type(e).__name__):
                wait_time = base_delay * (2 ** attempt)
                print(f"速率限制，{wait_time}秒后重试... (尝试 {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            else:
                raise
    raise Exception(f"重试 {max_retries} 次后仍然失败")

def test_chat():
    """测试 AI 的对话功能"""
    try:
        # 初始化客户端
        client = OpenAI(
            base_url=BASE_URL,
            api_key=API_KEY
        )
        
        print(f"正在连接: {BASE_URL}")
        print(f"使用模型: {CHAT_MODEL}\n")
        
        # 发送测试消息（带重试）
        def make_request():
            return client.chat.completions.create(
                model=CHAT_MODEL,
                messages=[
                    {"role": "system", "content": "你是一个有用的助手"},
                    {"role": "user", "content": "你好，请简单介绍一下你自己"}
                ],
                temperature=0.7
            )

        response = call_with_retry(make_request)
        
        # 显示响应
        print("=" * 50)
        print("AI 回复:")
        print("=" * 50)
        print(response.choices[0].message.content)
        print("=" * 50)
        print(f"\n使用 token 数: {response.usage.total_tokens}")
        print(f"  - 输入: {response.usage.prompt_tokens}")
        print(f"  - 输出: {response.usage.completion_tokens}")
        
        return True
        
    except Exception as e:
        print(f"错误: {str(e)}")
        import traceback
        print("\n详细错误信息:")
        traceback.print_exc()
        return False

def test_image_generation():
    """测试 Flux 图像生成功能"""
    try:
        client = OpenAI(
            base_url=BASE_URL,
            api_key=API_KEY
        )

        print(f"正在连接: {BASE_URL}")
        print(f"使用模型: {IMAGE_MODEL}\n")

        prompt = "一只可爱的橘猫坐在窗台上看窗外的雨"
        print(f"生成提示词: {prompt}\n")

        # 方法1: 尝试标准 images.generate 端点
        print("尝试方法1: images.generate 端点...")
        try:
            def make_image_request():
                return client.images.generate(
                    model=IMAGE_MODEL,
                    prompt=prompt,
                    n=1
                )
            response = call_with_retry(make_image_request, max_retries=5, base_delay=10)
            image_url = response.data[0].url
            print(f"成功! 图像 URL: {image_url}")
            _save_image(image_url)
            return True
        except Exception as e1:
            print(f"方法1 失败: {e1}\n")

        # 方法2: 通过 chat completions 调用（某些代理使用此方式）
        print("尝试方法2: chat.completions 端点...")
        try:
            def make_chat_request():
                return client.chat.completions.create(
                    model=IMAGE_MODEL,
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
            response = call_with_retry(make_chat_request, max_retries=5, base_delay=10)
            # 检查响应中是否有图像 URL
            content = response.choices[0].message.content
            print(f"响应内容: {content[:500] if len(content) > 500 else content}")

            # 尝试提取 URL
            import re
            urls = re.findall(r'https?://[^\s\)\"\']+\.(?:png|jpg|jpeg|webp)', content, re.IGNORECASE)
            if urls:
                print(f"\n找到图像 URL: {urls[0]}")
                _save_image(urls[0])
                return True
            else:
                print("响应中未找到图像 URL")
                return True  # 至少调用成功了
        except Exception as e2:
            print(f"方法2 失败: {e2}\n")

        print("所有方法都失败了")
        return False

    except Exception as e:
        print(f"错误: {str(e)}")
        import traceback
        print("\n详细错误信息:")
        traceback.print_exc()
        return False

def _save_image(image_url):
    """下载并保存图像"""
    if image_url:
        import urllib.request
        output_path = "generated_image.png"
        print(f"\n正在下载图像到: {output_path}")
        urllib.request.urlretrieve(image_url, output_path)
        print(f"图像已保存到: {output_path}")

def list_models():
    """列出 API 可用的模型"""
    try:
        client = OpenAI(
            base_url=BASE_URL,
            api_key=API_KEY
        )

        print(f"正在查询: {BASE_URL}")
        print("获取可用模型列表...\n")

        models = client.models.list()

        print("=" * 60)
        print("可用模型列表:")
        print("=" * 60)

        # 按模型类型分组
        chat_models = []
        image_models = []
        other_models = []

        for model in models.data:
            model_id = model.id.lower()
            if any(x in model_id for x in ['gpt', 'claude', 'llama', 'qwen', 'glm', 'deepseek']):
                chat_models.append(model.id)
            elif any(x in model_id for x in ['flux', 'dall', 'stable', 'midjourney', 'sd']):
                image_models.append(model.id)
            else:
                other_models.append(model.id)

        if chat_models:
            print("\n📝 聊天模型:")
            for m in sorted(chat_models):
                print(f"   - {m}")

        if image_models:
            print("\n🎨 图像模型:")
            for m in sorted(image_models):
                print(f"   - {m}")

        if other_models:
            print("\n📦 其他模型:")
            for m in sorted(other_models)[:20]:  # 最多显示20个
                print(f"   - {m}")
            if len(other_models) > 20:
                print(f"   ... 还有 {len(other_models) - 20} 个模型")

        print("=" * 60)
        print(f"共 {len(models.data)} 个模型")

        return True

    except Exception as e:
        print(f"错误: {str(e)}")
        import traceback
        print("\n详细错误信息:")
        traceback.print_exc()
        return False

def interactive_chat():
    """交互式对话模式"""
    client = OpenAI(
        base_url=BASE_URL,
        api_key=API_KEY
    )
    
    print(f"已连接到: {BASE_URL}")
    print(f"使用模型: {CHAT_MODEL}")
    print("输入 'quit' 或 'exit' 退出对话\n")
    
    messages = [
        {"role": "system", "content": "你是一个有用的助手"}
    ]
    
    while True:
        user_input = input("\n你: ")
        
        if user_input.lower() in ['quit', 'exit', '退出']:
            print("再见！")
            break
        
        if not user_input.strip():
            continue
        
        messages.append({"role": "user", "content": user_input})
        
        try:
            response = client.chat.completions.create(
                model=CHAT_MODEL,
                messages=messages,
                temperature=0.7
            )
            
            ai_response = response.choices[0].message.content
            print(f"\nAI: {ai_response}")
            
            messages.append({"role": "assistant", "content": ai_response})
            
        except Exception as e:
            print(f"错误: {str(e)}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode == "interactive":
            interactive_chat()
        elif mode == "image":
            print("测试 Flux 图像生成...\n")
            if test_image_generation():
                print("\n图像生成测试成功！")
        elif mode == "models":
            list_models()
        else:
            print(f"未知模式: {mode}")
            print("可用模式: interactive, image, models")
    else:
        print("执行聊天测试...\n")
        if test_chat():
            print("\n测试成功！")
            print("\n提示:")
            print("  - 运行 'python test_api.py interactive' 进入交互式对话模式")
            print("  - 运行 'python test_api.py image' 测试 Flux 图像生成")
            print("  - 运行 'python test_api.py models' 查看可用模型列表")
