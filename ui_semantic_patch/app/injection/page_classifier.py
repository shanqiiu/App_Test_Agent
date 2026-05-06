"""
页面类型分类器

使用 VLM 将截图分类为预定义的页面类型（封闭式分类），
替代旧方案中 VLM 做开放决策的不稳定方式。

VLM 仅负责：页面类型分类 + 关键元素提取
规则引擎负责：基于分类结果做确定性匹配
"""

import json
import re
import os
import time
import base64
import requests
from pathlib import Path
from typing import Optional


# VLM 页面分类提示词
VLM_CLASSIFICATION_PROMPT = """
分析这张 App 界面截图，回答以下问题。

### 页面类型（单选，必须选最接近的）：
A. 启动页/开屏页 — 应用启动画面、品牌展示、开屏广告
B. 首页/主页面 — 应用主界面、tab导航页、功能入口页
C. 搜索/筛选页 — 搜索框、筛选条件、日期选择、参数输入
D. 列表/结果页 — 商品列表、搜索结果、订单列表、信息流
E. 详情展示页 — 商品详情、信息详情、图片展示
F. 表单填写页 — 输入框、表单填写、信息录入、文本编辑
G. 支付/确认页 — 支付确认、订单确认、提交订单
H. 个人中心/设置 — 我的页面、设置页、个人资料
I. 加载/等待页 — 加载动画、进度条、等待状态
J. 其他 — 不属于以上任何类型

### 关键元素
当前页面上有哪些可交互的关键元素？
列出按钮、输入框、列表等，如：查询按钮、出发日期选择、搜索框

### 用户等待状态
用户当前是否在等待某个操作的结果？
（如：等待搜索完成、等待支付结果、等待页面加载）
回答 true 或 false。

### 输出格式（仅返回 JSON，不要其他内容）
{
  "page_type": "A",  // A/B/C/D/E/F/G/H/I/J
  "page_type_name": "首页/主页面",
  "key_elements": ["元素1", "元素2"],
  "user_waiting": false,
  "reasoning": "简要判断理由（一句话）"
}
"""


class PageClassifier:
    """
    页面类型分类器

    职责：
    1. 调用 VLM 分析截图
    2. 将截图分类为预定义的页面类型（封闭式分类）
    3. 提取关键 UI 元素
    4. 缓存结果避免重复调用
    """

    def __init__(
        self,
        api_key: str = None,
        api_url: str = None,
        model: str = None,
        temperature: float = 0.0,
    ):
        """
        初始化分类器

        Args:
            api_key: VLM API 密钥，默认从 VLM_API_KEY 环境变量读取
            api_url: VLM API URL
            model: VLM 模型名称
            temperature: 生成温度（0 表示确定性输出）
        """
        self.api_key = api_key or os.getenv('VLM_API_KEY')
        self.api_url = api_url or os.getenv('VLM_API_URL', 'https://api.openai-next.com/v1/chat/completions')
        self.model = model or os.getenv('VLM_MODEL', 'gpt-4o')
        self.temperature = temperature

        if not self.api_key:
            raise ValueError("VLM_API_KEY 环境变量未设置，无法初始化 PageClassifier")

        self._cache = {}  # 缓存分类结果 key=screenshot_path

    def classify(self, screenshot_path: str, use_cache: bool = True) -> dict:
        """
        对截图进行页面类型分类

        Args:
            screenshot_path: 截图文件路径
            use_cache: 是否使用缓存（同一截图不重复调用 VLM）

        Returns:
            {
                "page_type": "A-J",     # 页面类型代号
                "page_type_name": "str", # 页面类型中文名
                "key_elements": [...],   # 关键元素列表
                "user_waiting": bool,    # 用户是否在等待
                "reasoning": "str",      # 判断理由
                "raw_response": "str"    # VLM 原始响应（调试用）
            }
        """
        screenshot_path = str(Path(screenshot_path).resolve())

        # 缓存命中
        if use_cache and screenshot_path in self._cache:
            cached = self._cache[screenshot_path]
            print(f"  [分类器] 缓存命中: {Path(screenshot_path).name} → {cached.get('page_type_name', '?')}")
            return cached

        print(f"  [分类器] 分析页面: {Path(screenshot_path).name}")

        # 调用 VLM
        raw_response = self._call_vlm(screenshot_path)

        # 解析
        result = self._parse_response(raw_response)
        result["raw_response"] = raw_response

        print(f"  [分类器] 分类结果: {result.get('page_type_name', '?')} "
              f"(等待={result.get('user_waiting', '?')})")

        # 缓存
        if use_cache:
            self._cache[screenshot_path] = result

        return result

    def _call_vlm(self, image_path: str, max_retries: int = 3) -> str:
        """调用 VLM API"""
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }

        # 编码图片
        with open(image_path, 'rb') as f:
            image_base64 = base64.b64encode(f.read()).decode('utf-8')

        # 判断图片格式
        ext = Path(image_path).suffix.lower()
        mime_map = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}
        mime_type = mime_map.get(ext, 'image/png')

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_base64}"
                            }
                        },
                        {
                            "type": "text",
                            "text": VLM_CLASSIFICATION_PROMPT
                        }
                    ]
                }
            ],
            "temperature": self.temperature,
            "max_tokens": 512
        }

        base_wait = 5
        last_error = None

        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    wait_time = min(base_wait * (2 ** (attempt - 1)), 60)
                    print(f"    ⏳ 等待 {wait_time}s 后重试 ({attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)

                response = requests.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=180
                )

                if response.status_code == 429:
                    print(f"    ⚠ API 限流 (429)，准备重试...")
                    last_error = "API 限流 (429)"
                    continue
                elif response.status_code >= 500:
                    print(f"    ⚠ 服务器错误 ({response.status_code})，准备重试...")
                    last_error = f"服务器错误 ({response.status_code})"
                    continue

                response.raise_for_status()
                result = response.json()
                return result['choices'][0]['message']['content']

            except requests.exceptions.RequestException as e:
                print(f"    ⚠ API 请求失败: {e}")
                last_error = str(e)
                if attempt == max_retries - 1:
                    raise

        raise Exception(f"VLM 调用失败，已重试 {max_retries} 次。最后错误: {last_error}")

    def _parse_response(self, response: str) -> dict:
        """
        解析 VLM 的 JSON 响应

        Args:
            response: VLM 原始响应文本

        Returns:
            结构化的分类结果
        """
        # 默认值
        default = {
            "page_type": "J",
            "page_type_name": "其他/未知页面",
            "key_elements": [],
            "user_waiting": False,
            "reasoning": "解析失败，使用默认值"
        }

        try:
            # 提取 JSON（处理 VLM 可能返回 markdown 包裹的情况）
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                return default

            data = json.loads(json_match.group(0))

            # 校验 page_type
            page_type = data.get("page_type", "J").strip().upper()
            if page_type not in "ABCDEFGHIJ":
                page_type = "J"

            # page_type 代号 → 中文名
            type_names = {
                "A": "启动页/开屏页", "B": "首页/主页面",
                "C": "搜索/筛选页", "D": "列表/结果页",
                "E": "详情展示页", "F": "表单填写页",
                "G": "支付/确认页", "H": "个人中心/设置",
                "I": "加载/等待页", "J": "其他/未知页面"
            }

            return {
                "page_type": page_type,
                "page_type_name": type_names.get(page_type, "其他/未知页面"),
                "key_elements": data.get("key_elements", []),
                "user_waiting": bool(data.get("user_waiting", False)),
                "reasoning": data.get("reasoning", "")
            }

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"    ⚠ VLM 响应解析失败: {e}")
            return default

    def clear_cache(self):
        """清空分类缓存"""
        self._cache.clear()
        print("  [分类器] 缓存已清空")

    @property
    def cache_size(self) -> int:
        """缓存大小"""
        return len(self._cache)
