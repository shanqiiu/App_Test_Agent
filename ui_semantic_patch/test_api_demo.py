import requests
import json

url = "http://10.85.177.2:8042/generate"

data = {
    "prompt": "青山，美丽的日出， 30岁中国女子，皮肤毛孔和轻微皱纹。穿着衣服、裤子、鞋，朝镜头摆 POSE，全身照随手拍，无摄影技巧",
    "height": 1440,
    "width": 1920,
    "steps": 9,
    "seed": 42
}

response = requests.post(url, json=data, proxies={"http": None, "https": None})


print(response.json())

print(f"状态码：{response.status_code}")
if response.status_code == 200:
    result = response.json()
    print("请求成功！")
    print(json.dumps(result, indent=2))
    print(f"图片访问 URL: {result['path']}")
else:
    print(f"请求失败，状态码：{response.status_code}")
    print(response.text)
