"""
页面类型分类器（v2 — 两级分类）

使用 VLM 将截图分类为 (APP类别, 页面类型) 两级封闭式分类。

VLM 职责：app_category + page_type + 关键元素提取
规则引擎：基于 (app_category, page_type) 双维度确定性匹配
"""

import json
import re
import os
import time
import base64
import requests
from pathlib import Path
from typing import Optional


# VLM 两级分类提示词（v2）
VLM_CLASSIFICATION_PROMPT = """
分析这张 App 界面截图，进行两级分类。

## 第一级：APP 类别（单选）
1. travel   — 出行预订：机票、火车票、酒店、打车（如 12306、携程、去哪儿）
2. video    — 长视频：电视剧、电影、综艺、动漫（如 腾讯视频、爱奇艺）
3. music    — 音乐音频：歌曲、歌单、播放器、歌词（如 QQ音乐、网易云）
4. sports   — 体育直播：赛事、比分、直播、数据统计（如 直播吧、懂球帝）
5. social   — 内容社区：笔记、图文、UGC、商城（如 小红书、抖音）
6. delivery — 即时配送：外卖、生鲜、跑腿（如 美团、饿了么）

## 第二级：页面类型（从所选类别中单选）

### travel（出行预订）
- travel_home: 出行首页（搜索入口、功能icon、活动banner）
- travel_search: 搜索筛选页（城市选择、日期日历、舱位座型）
- travel_route_list: 路线结果页（航班/车次卡片、价格、余票）
- travel_detail: 班次详情页（经停信息、舱位详情、退改规则）
- travel_booking: 预订下单页（乘客信息、保险、增值服务）
- travel_payment: 支付确认页（支付方式、金额汇总、倒计时）
- travel_order: 订单管理页（订单列表、出票状态）
- travel_member: 会员/个人页（里程、优惠券、常用乘客）
- travel_loading: 加载等待（搜索等待、提交等待）

### video（长视频）
- video_home: 视频首页（推荐流、分类tab、热播banner）
- video_search: 搜索页（搜索框、历史、分类标签）
- video_content_detail: 内容详情页（封面、简介、演职员、推荐）
- video_episode_select: 选集面板（剧集列表、勾选框、清晰度）
- video_download: 下载管理页（下载列表、缓存进度）
- video_player: 播放器（播放画面、进度条、弹幕）
- video_profile: 个人中心（观看历史、收藏、会员）
- video_loading: 加载等待（视频缓冲、列表加载）

### music（音乐音频）
- music_home: 音乐首页（推荐、歌单、新歌速递）
- music_search: 搜索页（搜索框、热搜、分类）
- music_album_detail: 专辑/歌单详情（封面、曲目列表、收藏）
- music_player: 播放器（专辑封面、歌词、进度条）
- music_lyrics: 歌词页（全屏歌词、逐行高亮）
- music_download: 下载管理（已下载列表、音质选择）
- music_profile: 个人中心（我喜欢、最近播放、歌单）
- music_loading: 加载等待（歌曲缓冲、列表加载）

### sports（体育直播）
- sports_home: 赛事首页（今日赛事、热门联赛、比分速览）
- sports_schedule: 赛事日程（按日期/联赛的赛事列表）
- sports_live: 直播页面（视频流、实时比分、事件时间轴）
- sports_data: 数据统计（技术统计、阵容、交锋记录）
- sports_community: 社区讨论（帖子列表、评论区）
- sports_profile: 个人中心（关注球队、预约、设置）
- sports_loading: 加载等待（直播加载、数据刷新）

### social（内容社区）
- social_feed: 内容流（双列/单列笔记、推荐/关注）
- social_note_detail: 笔记详情（图文/视频、标签、评论区）
- social_post_create: 发布编辑（图片选择、文字编辑、话题）
- social_search: 搜索发现（搜索框、热门话题）
- social_shop: 商城（商品列表、详情、购物车）
- social_message: 消息/聊天（私信列表、对话）
- social_profile: 个人主页（头像、笔记列表、收藏）
- social_loading: 加载等待（内容刷新、图片加载）

### delivery（即时配送）
- delivery_home: 配送首页（推荐商家、分类入口、banner）
- delivery_shop_list: 商家列表（评分/距离排序的商家卡片）
- delivery_menu: 菜单/商品页（分类tab、商品列表、价格）
- delivery_item_config: 规格配置（温度/甜度/配料/份量）
- delivery_cart: 下单确认（已选商品、优惠券、合计）
- delivery_payment: 支付确认（支付方式、倒计时）
- delivery_tracking: 配送跟踪（实时地图、骑手位置、预计送达）
- delivery_profile: 个人中心（地址管理、收藏、订单）
- delivery_loading: 加载等待（商家加载、支付等待）

## 关键元素
列出当前页面上可交互的关键元素（按钮、输入框、列表等）。

## 用户等待状态
用户当前是否在等待某个操作结果？回答 true/false。

## 页面内容特征（对以下每项回答 yes/no）
- has_price: 页面上是否有可见的具体价格/金额数字（如 ¥328、99元）？
- has_button: 页面上是否有可操作的按钮（预订、购买、下载、提交等）？
- has_list_items: 页面是否包含多项可选的列表条目（如航班卡片、商品卡片、剧集列表）？
- has_form_input: 页面是否有需要用户填写的输入框/选择器（日期、乘客、规格等）？
- has_text_content: 页面是否有明显的文字标题/名称内容（如电影名、航班号、商品名）？

## 输出格式（仅返回 JSON，不要其他内容）
{
  "app_category": "travel",
  "page_type": "travel_route_list",
  "key_elements": ["航班卡片", "价格标签", "筛选按钮"],
  "user_waiting": false,
  "reasoning": "展示航班搜索结果列表，含价格和余票信息",
  "content_features": {
    "has_price": true,
    "has_button": true,
    "has_list_items": true,
    "has_form_input": false,
    "has_text_content": true
  }
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

    def classify(self, screenshot_path: str, use_cache: bool = True,
                 prev_page_info: dict = None, step_context: str = "") -> dict:
        """
        对截图进行页面类型分类（支持序列上下文）

        Args:
            screenshot_path: 截图文件路径
            use_cache: 是否使用缓存（有上下文时不缓存，因为同一帧在不同上下文可能判断不同）
            prev_page_info: 前一帧的分类结果，用于序列上下文感知
            step_context: 序列位置描述，如 "第3/8步"

        Returns:
            {
                "app_category": "travel/video/music/sports/social/delivery",
                "page_type": "travel_route_list/...",
                "key_elements": [...],
                "user_waiting": bool,
                "reasoning": "str",
                "content_features": {...},
                "raw_response": "str"
            }
                "raw_response": "str"    # VLM 原始响应（调试用）
            }
        """
        screenshot_path = str(Path(screenshot_path).resolve())

        # 有上下文时不使用缓存（同一帧在不同序列位置可能判断不同）
        has_context = bool(prev_page_info or step_context)
        if use_cache and not has_context and screenshot_path in self._cache:
            cached = self._cache[screenshot_path]
            print(f"  [分类器] 缓存命中: {Path(screenshot_path).name} → {cached.get('app_category', '?')}/{cached.get('page_type', '?')}")
            return cached

        context_label = f" [{step_context}]" if step_context else ""
        print(f"  [分类器] 分析页面: {Path(screenshot_path).name}{context_label}")

        # 调用 VLM（注入序列上下文）
        raw_response = self._call_vlm(screenshot_path, prev_page_info, step_context)

        # 解析
        result = self._parse_response(raw_response)
        result["raw_response"] = raw_response

        print(f"  [分类器] 分类结果: {result.get('app_category', '?')}/{result.get('page_type', '?')} "
              f"(等待={result.get('user_waiting', '?')})")

        # 缓存
        if use_cache:
            self._cache[screenshot_path] = result

        return result

    def _call_vlm(self, image_path: str, prev_page_info: dict = None,
                   step_context: str = "", max_retries: int = 3) -> str:
        """调用 VLM API（支持序列上下文注入）"""
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

        # 构建带序列上下文的 prompt
        prompt_text = VLM_CLASSIFICATION_PROMPT
        if prev_page_info or step_context:
            context_lines = ["\n## 序列上下文（当前截图在操作序列中的位置）"]
            if step_context:
                context_lines.append(f"- 当前是序列的第 {step_context}")
            if prev_page_info:
                prev_cat = prev_page_info.get("app_category", "?")
                prev_page = prev_page_info.get("page_type", "?")
                prev_reason = prev_page_info.get("reasoning", "")
                context_lines.append(f"- 上一帧页面类型: {prev_cat}/{prev_page}")
                if prev_reason:
                    context_lines.append(f"- 上一帧分析: {prev_reason}")
            context_lines.append("- 请结合序列位置判断当前页面的实际类型（刚切换过来的新页面 vs 停留在原页面）")
            prompt_text += "\n" + "\n".join(context_lines)

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
                            "text": prompt_text
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
        """解析 VLM 的 JSON 响应（v2 两级分类）"""
        # 有效值集合
        VALID_CATEGORIES = {"travel", "video", "music", "sports", "social", "delivery"}
        VALID_PAGE_TYPES = {
            "travel":   {"travel_home","travel_search","travel_route_list","travel_detail","travel_booking","travel_payment","travel_order","travel_member","travel_loading"},
            "video":    {"video_home","video_search","video_content_detail","video_episode_select","video_download","video_player","video_profile","video_loading"},
            "music":    {"music_home","music_search","music_album_detail","music_player","music_lyrics","music_download","music_profile","music_loading"},
            "sports":   {"sports_home","sports_schedule","sports_live","sports_data","sports_community","sports_profile","sports_loading"},
            "social":   {"social_feed","social_note_detail","social_post_create","social_search","social_shop","social_message","social_profile","social_loading"},
            "delivery": {"delivery_home","delivery_shop_list","delivery_menu","delivery_item_config","delivery_cart","delivery_payment","delivery_tracking","delivery_profile","delivery_loading"},
        }

        default = {
            "app_category": "travel",
            "page_type": "travel_loading",
            "key_elements": [],
            "user_waiting": False,
            "reasoning": "解析失败，使用默认值",
            "content_features": {}
        }

        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                return default

            data = json.loads(json_match.group(0))

            # 校验 app_category
            app_category = data.get("app_category", "").strip().lower()
            if app_category not in VALID_CATEGORIES:
                app_category = "travel"

            # 校验 page_type（必须在对应 category 的有效集合中）
            page_type = data.get("page_type", "").strip().lower()
            valid_types = VALID_PAGE_TYPES.get(app_category, set())
            if page_type not in valid_types:
                page_type = next(iter(valid_types), "travel_loading")

            return {
                "app_category": app_category,
                "page_type": page_type,
                "key_elements": data.get("key_elements", []),
                "user_waiting": bool(data.get("user_waiting", False)),
                "reasoning": data.get("reasoning", ""),
                "content_features": data.get("content_features", {}),
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
