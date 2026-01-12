"""
原始文件 - 已重构

此文件是最初的简单实现，已被重构为更完整的系统。

新的实现位于：
- src/api_client.py - 统一的API客户端接口
- src/image_generator.py - 增强的图像生成器
- scripts/generate.py - CLI命令行入口

请使用新的实现：
    python scripts/generate.py

此文件保留作为参考。
"""

import base64
import requests
import os
from typing import Optional


class ImageGenerator:
    def __init__(self, api_key: str, api_url: str):
        self.headers = {
            "Authorization": f"Bearer {api_key}"
        }
        self.api_url = api_url

    def generate_image(self, prompt: str, width: int = 450, height: int = 807,
                       num_inference_steps: int = 10, true_cfg_scale: float = 4.0,
                       seed: Optional[int] = None  ) -> bytes:   #seed=42,
        json_data = {
            "model": "flux_txt_to_image", # 请填写模型名称，例如: qwen-image-2512_txt_to_image flux_txt_to_image
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "negative_prompt": "",
            "width": width,
            "height": height,
            "num_inference_steps": num_inference_steps,
            "true_cfg_scale": true_cfg_scale,
            "seed": seed
        }

        response = requests.post(self.api_url, headers=self.headers, json=json_data, verify=False)
        response.raise_for_status()  # 确保请求成功

        base64_data = response.json()["choices"][0]["message"]["content"]
        image_data = base64.b64decode(base64_data)

        return image_data

    def save_image(self, image_data: bytes, file_path: str = "output.png") -> None:
        with open(file_path, "wb") as f:
            f.write(image_data)
        print(f"图片已保存为 {file_path}")


# 使用示例
if __name__ == "__main__":
    API_KEY = ""
    API_URL = ""

    generator = ImageGenerator(api_key=API_KEY, api_url=API_URL)
    image_data = generator.generate_image(
        prompt="手机票务APP UI截图，显示严重数据异常。热门演唱会页面顶部大红幅显示“已售罄”。但下方票档区域信息矛盾：“VIP区”灰显，而“A区看台”旁边竟有绿色标签显示“剩余：5张”，且旁边的“立即抢票”按钮是亮红色的可点状态。底部有一个故障感的系统提示小浮窗：“系统警告：库存数据同步异常”。现代中国票务APP风格")

    # 创建保存目录
    model_name = "flux_txt_to_image"  # 从json_data中获取模型名称
    save_dir = f"../../img_demo/{model_name}"
    os.makedirs(save_dir, exist_ok=True)

    # 生成时间戳作为文件名
    import datetime

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = f"{save_dir}/{timestamp}.png"

    generator.save_image(image_data, file_path)