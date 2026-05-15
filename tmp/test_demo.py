import requests
import base64
import os

os.environ["no_proxy"] = "localhost,127.0.0.1,.huawei.com"

headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer sk-eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2NvdW50SWQiOiJqMDA5NTYyNDQiLCJhY2NvdW50TmFtZSI6ImppYW5nYm93ZWkiLCJkZXBhcnRtZW50TmFtZSI6InVua25vd24iLCJ0ZW5hbnRJZCI6ImU0YTQ0NTcxYTlmYzE0MTE1ZmViYmJhNWRhNzZhNmEzIiwia2V5VmVyc2lvbiI6IjIuMCJ9.08kKW8bkq4eU2LabqXb4c51ZJ5EGBQcELhovG_0HVrw'
}

# 文本描述，用于生成图像
prompt = "一个美丽的日落场景，包含山脉和湖泊"

json_data = {
    "model": "flux_txt_to_image",  # 使用文生图模型
    "messages": [
        {
            "role": "user",
            "content": prompt  # 直接使用字符串作为 content
        }
    ],
    "max_tokens": 2048
}

url = 'http://mlops.huawei.com/mlops-service/api/v2/agentService/v1/chat/completions'
response = requests.post(url, headers=headers, json=json_data)

if response.status_code == 200:
    response_data = response.json()
    print(response_data)  # 打印响应数据以检查其结构

    # 提取 Base64 编码的图像数据
    image_data = response_data.get('choices', [{}])[0].get('message', {}).get('content', '')
    if image_data:
        # 将 Base64 编码的图像数据保存为文件
        with open("generated_image.png", "wb") as image_file:
            image_file.write(base64.b64decode(image_data))
        print("图像已保存为 generated_image.png")
    else:
        print("未找到图像数据")
else:
    print(f"请求失败，状态码: {response.status_code}")
    print(response.text)
