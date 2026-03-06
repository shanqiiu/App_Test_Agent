"""
API 认证测试脚本
诊断 401 Unauthorized 错误原因
"""
import os
import sys
import json
import requests
from pathlib import Path

# 加载 .env
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parents[3] / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✓ 已加载 .env: {env_path}")
    else:
        print(f"✗ .env 文件不存在: {env_path}")
except ImportError:
    print("✗ python-dotenv 未安装")

# 读取配置
API_KEY = os.environ.get('VLM_API_KEY', '')
API_URL = os.environ.get('VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions')
MODEL   = os.environ.get('VLM_MODEL', 'gpt-4o')

print("\n========== 当前配置 ==========")
print(f"API_URL : {API_URL}")
print(f"MODEL   : {MODEL}")
if API_KEY:
    masked = API_KEY[:8] + '...' + API_KEY[-6:] if len(API_KEY) > 14 else API_KEY[:4] + '...'
    print(f"API_KEY : {masked}  (长度={len(API_KEY)})")
else:
    print("API_KEY : ✗ 未设置")

# ─── 测试 1: 最简文本请求 ────────────────────────────────────────────────
print("\n========== 测试 1: 最简文本请求 ==========")
headers = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {API_KEY}'
}
payload = {
    "model": MODEL,
    "messages": [{"role": "user", "content": "说'OK'"}],
    "max_tokens": 10
}
try:
    resp = requests.post(API_URL, headers=headers, json=payload, timeout=30)
    print(f"HTTP 状态码: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        content = data['choices'][0]['message']['content']
        print(f"✓ 成功! 响应: {content}")
    else:
        print(f"✗ 失败")
        print(f"响应体: {resp.text[:500]}")
except Exception as e:
    print(f"✗ 请求异常: {e}")

# ─── 测试 2: 试用备用模型 ────────────────────────────────────────────────
print("\n========== 测试 2: 备用模型 (gpt-4o-mini) ==========")
payload2 = {**payload, "model": "gpt-4o-mini"}
try:
    resp2 = requests.post(API_URL, headers=headers, json=payload2, timeout=30)
    print(f"HTTP 状态码: {resp2.status_code}")
    if resp2.status_code == 200:
        data2 = resp2.json()
        content2 = data2['choices'][0]['message']['content']
        print(f"✓ 成功! 响应: {content2}")
    else:
        print(f"✗ 失败")
        print(f"响应体: {resp2.text[:500]}")
except Exception as e:
    print(f"✗ 请求异常: {e}")

# ─── 测试 3: DashScope 端点（qwen-vl-max）────────────────────────────────
print("\n========== 测试 3: DashScope API (qwen-vl-max) ==========")
DASHSCOPE_KEY = os.environ.get('DASHSCOPE_API_KEY', '')
DASHSCOPE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
if DASHSCOPE_KEY:
    masked_ds = DASHSCOPE_KEY[:8] + '...' + DASHSCOPE_KEY[-4:] if len(DASHSCOPE_KEY) > 12 else '***'
    print(f"DASHSCOPE_API_KEY: {masked_ds}")
    headers_ds = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {DASHSCOPE_KEY}'
    }
    payload_ds = {
        "model": "qwen-vl-max",
        "messages": [{"role": "user", "content": "说'OK'"}],
        "max_tokens": 10
    }
    try:
        resp3 = requests.post(DASHSCOPE_URL, headers=headers_ds, json=payload_ds, timeout=30)
        print(f"HTTP 状态码: {resp3.status_code}")
        if resp3.status_code == 200:
            data3 = resp3.json()
            content3 = data3['choices'][0]['message']['content']
            print(f"✓ 成功! 响应: {content3}")
        else:
            print(f"✗ 失败")
            print(f"响应体: {resp3.text[:500]}")
    except Exception as e:
        print(f"✗ 请求异常: {e}")
else:
    print("跳过（DASHSCOPE_API_KEY 未设置）")

# ─── 测试 4: 检查端点是否可达 ────────────────────────────────────────────
print("\n========== 测试 4: 端点连通性 ==========")
base_url = API_URL.rsplit('/chat', 1)[0]
models_url = base_url + '/models'
try:
    resp4 = requests.get(models_url, headers=headers, timeout=15)
    print(f"GET {models_url}")
    print(f"HTTP 状态码: {resp4.status_code}")
    if resp4.status_code == 200:
        models = resp4.json().get('data', [])
        print(f"✓ 可用模型数: {len(models)}")
        for m in models[:5]:
            print(f"  - {m.get('id', '?')}")
        if len(models) > 5:
            print(f"  ... (共 {len(models)} 个)")
    else:
        print(f"响应体: {resp4.text[:300]}")
except Exception as e:
    print(f"✗ 连通性测试失败: {e}")

print("\n========== 诊断完成 ==========")
