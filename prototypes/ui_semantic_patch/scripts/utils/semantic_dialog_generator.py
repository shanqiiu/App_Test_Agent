#!/usr/bin/env python3
"""
semantic_dialog_generator.py - 语义感知弹窗生成器

根据页面内容和语义理解，生成逼真且符合场景的弹窗。
支持两种渲染模式：
1. PIL 代码生成：使用增强的 PIL 绘制逼真弹窗
2. AI 图像生成：调用大模型直接生成弹窗图像

典型场景：
- 火车票/机票页面 → 余票为0、票价变动、抢票失败
- 电商页面 → 商品推荐、优惠券、限时抢购
- 社交页面 → 好友请求、消息通知、隐私提醒
- 视频/音乐页面 → VIP会员推荐、版权提示
"""

import json
import base64
import time
import os
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import io
import math

import dashscope
from dashscope import MultiModalConversation

from utils.reference_analyzer import ReferenceAnalyzer, ReferenceStyleApplier


# ==================== DashScope 图像生成工具函数 ====================
def _normalize_size_for_dashscope(width: int, height: int) -> Tuple[int, int]:
    """
    将尺寸规范化到 DashScope qwen-image-max 支持的范围，同时尽量保持宽高比

    qwen-image-max 支持的尺寸范围: [512*512, 2048*2048]

    策略：
    1. 保持原始宽高比
    2. 等比缩放到支持范围内
    3. 生成后可通过 resize 调整到精确目标尺寸

    Args:
        width: 原始宽度
        height: 原始高度

    Returns:
        (normalized_width, normalized_height) 规范化后的尺寸
    """
    MIN_SIZE = 512
    MAX_SIZE = 2048

    # 计算宽高比
    aspect_ratio = width / height

    # 先按比例缩放到最小尺寸以上
    if width < MIN_SIZE or height < MIN_SIZE:
        if width < height:
            # 宽度是短边
            new_width = MIN_SIZE
            new_height = int(new_width / aspect_ratio)
        else:
            # 高度是短边
            new_height = MIN_SIZE
            new_width = int(new_height * aspect_ratio)
        width, height = new_width, new_height

    # 再按比例缩放到最大尺寸以下
    if width > MAX_SIZE or height > MAX_SIZE:
        if width > height:
            # 宽度是长边
            new_width = MAX_SIZE
            new_height = int(new_width / aspect_ratio)
        else:
            # 高度是长边
            new_height = MAX_SIZE
            new_width = int(new_height * aspect_ratio)
        width, height = new_width, new_height

    # 最终确保在范围内（处理极端宽高比情况）
    width = max(MIN_SIZE, min(MAX_SIZE, width))
    height = max(MIN_SIZE, min(MAX_SIZE, height))

    return width, height


def generate_image_dashscope(
    prompt: str,
    api_key: str = None,
    size: str = '1024*1024',
    negative_prompt: str = None,
    save_path: str = None
) -> Optional[Image.Image]:
    """
    使用 DashScope MultiModalConversation API 生成图像

    Args:
        prompt: 图像描述提示词
        api_key: DashScope API Key（默认从环境变量 DASHSCOPE_API_KEY 获取）
        size: 图像尺寸，格式 'width*height'，会自动规范化到支持范围 [512, 2048]
        negative_prompt: 负面提示词
        save_path: 可选的保存路径

    Returns:
        生成的 PIL Image 对象，失败返回 None
    """
    # 配置 DashScope
    dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'

    if api_key is None:
        api_key = os.getenv("DASHSCOPE_API_KEY")

    if not api_key:
        print("  ⚠ 未提供 DASHSCOPE_API_KEY")
        return None

    # 解析并规范化尺寸
    try:
        w, h = size.split('*')
        orig_width, orig_height = int(w), int(h)
        norm_width, norm_height = _normalize_size_for_dashscope(orig_width, orig_height)
        if (norm_width, norm_height) != (orig_width, orig_height):
            print(f"  ℹ 尺寸已调整: {orig_width}*{orig_height} → {norm_width}*{norm_height}")
        size = f"{norm_width}*{norm_height}"
    except ValueError:
        print(f"  ⚠ 无效的尺寸格式: {size}，使用默认 1024*1024")
        size = "1024*1024"

    messages = [
        {
            "role": "user",
            "content": [{"text": prompt}]
        }
    ]

    # 默认负面提示词（排除非黑色背景和低质量图像）
    if negative_prompt is None:
        negative_prompt = "低分辨率，低画质，肢体畸形，手指畸形，画面过饱和，蜡像感，人脸无细节，过度光滑，画面具有AI感。构图混乱。文字模糊，扭曲。白色背景，灰色背景，渐变背景，彩色背景，white background, gray background, colored background, gradient background"

    # 重试逻辑
    max_retries = 5
    base_wait = 5
    last_error_code = None

    for attempt in range(max_retries):
        if attempt > 0:
            # 429 限流错误使用更长的等待时间
            if last_error_code == 429:
                wait_time = min(30 * (2 ** (attempt - 1)), 120)  # 30s, 60s, 120s...
            else:
                wait_time = min(base_wait * (2 ** (attempt - 1)), 60)
            print(f"  ⏳ 等待 {wait_time}s 后重试 ({attempt + 1}/{max_retries})...")
            time.sleep(wait_time)

        try:
            response = MultiModalConversation.call(
                api_key=api_key,
                model="qwen-image-max",
                messages=messages,
                result_format='message',
                stream=False,
                watermark=False,
                prompt_extend=True,
                negative_prompt=negative_prompt,
                size=size
            )

            if response.status_code == 200:
                # 提取图片URL
                content = response.output.choices[0].message.content
                for item in content:
                    if "image" in item:
                        image_url = item["image"]
                        print(f"  ✓ 图片生成成功，正在下载...")

                        # 下载图片
                        img_response = requests.get(image_url, timeout=60)
                        if img_response.status_code == 200:
                            image = Image.open(io.BytesIO(img_response.content)).convert('RGBA')

                            # 保存图片（如果指定了路径）
                            if save_path:
                                with open(save_path, "wb") as f:
                                    f.write(img_response.content)
                                print(f"  ✓ 图片已保存至: {save_path}")

                            return image
                        else:
                            print(f"  ⚠ 下载图片失败，状态码: {img_response.status_code}")

                print("  ⚠ 响应中未找到图片URL")
                return None
            else:
                last_error_code = response.status_code
                print(f"  ⚠ API 返回错误: {response.status_code} - {response.message}")
                # 400 错误（如尺寸错误）不重试
                if response.status_code == 400:
                    return None
                if attempt < max_retries - 1:
                    continue
                return None

        except Exception as e:
            print(f"  ⚠ 请求异常: {e}")
            if attempt < max_retries - 1:
                continue
            return None

    return None


class SemanticDialogGenerator:
    """
    语义感知弹窗生成器

    功能：
    1. 分析页面语义，匹配预设的场景弹窗模板
    2. 根据场景生成符合实际的弹窗内容
    3. 支持 PIL 绘制和 AI 生成两种模式
    """

    # ==================== 场景识别规则 ====================
    # 根据页面关键词识别场景类型
    SCENE_PATTERNS = {
        'ticket': {
            'keywords': ['火车票', '机票', '车票', '航班', '余票', '购票', '抢票', '12306', '携程', '去哪儿', '飞猪'],
            'dialog_types': ['no_ticket', 'price_change', 'grab_failed', 'queue_timeout']
        },
        'ecommerce': {
            'keywords': ['购物车', '商品', '价格', '¥', '￥', '加入购物车', '立即购买', '淘宝', '京东', '拼多多', '下单'],
            'dialog_types': ['out_of_stock', 'price_drop', 'coupon_popup', 'flash_sale', 'recommend']
        },
        'social': {
            'keywords': ['好友', '消息', '朋友圈', '动态', '评论', '点赞', '关注', '微信', '微博', 'QQ'],
            'dialog_types': ['friend_request', 'privacy_alert', 'message_notify', 'permission']
        },
        'video': {
            'keywords': ['视频', '播放', 'VIP', '会员', '广告', '观看', '抖音', 'B站', '优酷', '爱奇艺', '腾讯视频'],
            'dialog_types': ['vip_prompt', 'ad_popup', 'copyright_notice', 'download_limit']
        },
        'finance': {
            'keywords': ['余额', '支付', '转账', '银行卡', '提现', '红包', '零钱', '支付宝', '微信支付'],
            'dialog_types': ['payment_failed', 'balance_insufficient', 'security_verify', 'risk_alert']
        },
        'login': {
            'keywords': ['登录', '注册', '密码', '验证码', '账号', '手机号', '用户名'],
            'dialog_types': ['login_expired', 'auth_failed', 'captcha_error', 'account_locked']
        },
        'network': {
            'keywords': ['网络', '加载', '刷新', '连接', '超时'],
            'dialog_types': ['network_error', 'timeout', 'server_error', 'retry']
        }
    }

    # ==================== 弹窗内容模板 ====================
    DIALOG_TEMPLATES = {
        # 火车票/机票场景
        'no_ticket': {
            'title': '余票不足',
            'messages': [
                '非常抱歉，您选择的车次余票已售罄',
                '当前班次已无余票，建议选择其他时间',
                '该航班经济舱已售罄，是否查看其他舱位？'
            ],
            'style': 'warning',
            'buttons': ['查看其他', '取消'],
            'icon': 'warning'
        },
        'price_change': {
            'title': '票价变动提醒',
            'messages': [
                '票价已从 ¥{old_price} 调整为 ¥{new_price}',
                '由于供需变化，当前票价已更新',
                '温馨提示：票价有所浮动，请确认后购买'
            ],
            'style': 'info',
            'buttons': ['确认购买', '取消'],
            'icon': 'info'
        },
        'grab_failed': {
            'title': '抢票失败',
            'messages': [
                '很遗憾，本次抢票未成功',
                '当前购票人数过多，请稍后重试',
                '系统繁忙，抢票失败，请重试'
            ],
            'style': 'error',
            'buttons': ['重新抢票', '放弃'],
            'icon': 'error'
        },
        'queue_timeout': {
            'title': '排队超时',
            'messages': [
                '排队等待超时，请重新提交订单',
                '当前排队人数过多，请稍后再试'
            ],
            'style': 'warning',
            'buttons': ['重试', '取消'],
            'icon': 'timeout'
        },

        # 电商场景
        'out_of_stock': {
            'title': '库存不足',
            'messages': [
                '抱歉，该商品库存不足',
                '您选择的规格已售罄',
                '该商品暂时缺货，建议收藏等待补货'
            ],
            'style': 'warning',
            'buttons': ['收藏商品', '查看相似'],
            'icon': 'stock'
        },
        'coupon_popup': {
            'title': '专属优惠券',
            'messages': [
                '恭喜获得 ¥50 优惠券',
                '限时福利：满100减20',
                '新人专享：首单立减30元'
            ],
            'style': 'success',
            'buttons': ['立即领取', '稍后再说'],
            'icon': 'coupon',
            'is_ad': True
        },
        'flash_sale': {
            'title': '限时抢购',
            'messages': [
                '距离活动结束还有 02:30:00',
                '限时特价，手慢无！',
                '爆款直降，仅剩最后 3 件'
            ],
            'style': 'warning',
            'buttons': ['立即抢购', '提醒我'],
            'icon': 'flash',
            'is_ad': True
        },
        'recommend': {
            'title': '猜你喜欢',
            'messages': [
                '根据您的浏览记录推荐',
                '相似商品推荐',
                '购买此商品的用户还买了'
            ],
            'style': 'info',
            'buttons': ['查看详情', '不感兴趣'],
            'icon': 'recommend',
            'is_ad': True
        },

        # 社交场景
        'friend_request': {
            'title': '好友请求',
            'messages': [
                '用户 {username} 请求添加您为好友',
                '{username} 想要加您为好友',
                '来自 {username} 的好友申请'
            ],
            'style': 'info',
            'buttons': ['同意', '拒绝'],
            'icon': 'friend'
        },
        'privacy_alert': {
            'title': '隐私提醒',
            'messages': [
                '该操作需要访问您的位置信息',
                '是否允许该应用访问您的相册？',
                '该功能需要获取通讯录权限'
            ],
            'style': 'warning',
            'buttons': ['允许', '拒绝'],
            'icon': 'privacy'
        },

        # 视频场景
        'vip_prompt': {
            'title': 'VIP 会员特权',
            'messages': [
                '开通会员，免广告观看',
                '该内容为VIP专享，立即开通？',
                '会员限时特惠：首月仅需 ¥6'
            ],
            'style': 'info',
            'buttons': ['立即开通', '继续等待'],
            'icon': 'vip',
            'is_ad': True
        },
        'ad_popup': {
            'title': '广告',
            'messages': [
                '精选推荐',
                '限时特惠活动',
                '新品发布'
            ],
            'style': 'info',
            'buttons': ['了解更多', '关闭'],
            'icon': 'ad',
            'is_ad': True,
            'show_image': True
        },

        # 金融场景
        'payment_failed': {
            'title': '支付失败',
            'messages': [
                '支付遇到问题，请重试',
                '银行卡余额不足',
                '网络异常，支付未完成'
            ],
            'style': 'error',
            'buttons': ['重试', '更换支付方式'],
            'icon': 'payment'
        },
        'balance_insufficient': {
            'title': '余额不足',
            'messages': [
                '账户余额不足，请充值',
                '当前余额 ¥{balance}，还需 ¥{need}',
                '余额不足以完成本次支付'
            ],
            'style': 'warning',
            'buttons': ['去充值', '取消'],
            'icon': 'balance'
        },
        'security_verify': {
            'title': '安全验证',
            'messages': [
                '检测到异常登录，请完成验证',
                '为保障账户安全，请验证身份',
                '请输入短信验证码完成验证'
            ],
            'style': 'warning',
            'buttons': ['去验证', '取消'],
            'icon': 'security'
        },

        # 登录场景
        'login_expired': {
            'title': '登录已过期',
            'messages': [
                '您的登录状态已过期，请重新登录',
                '长时间未操作，请重新登录',
                '登录信息已失效'
            ],
            'style': 'warning',
            'buttons': ['重新登录', '取消'],
            'icon': 'login'
        },
        'auth_failed': {
            'title': '认证失败',
            'messages': [
                '用户名或密码错误',
                '账号或密码不正确，请重试',
                '登录失败，请检查账号信息'
            ],
            'style': 'error',
            'buttons': ['重试', '找回密码'],
            'icon': 'auth'
        },

        # 网络场景
        'network_error': {
            'title': '网络异常',
            'messages': [
                '网络连接失败，请检查网络设置',
                '当前网络不可用',
                '无法连接到服务器'
            ],
            'style': 'error',
            'buttons': ['重试', '取消'],
            'icon': 'network'
        },
        'timeout': {
            'title': '请求超时',
            'messages': [
                '服务器响应超时，请稍后重试',
                '加载超时，请检查网络',
                '连接超时'
            ],
            'style': 'error',
            'buttons': ['重试', '取消'],
            'icon': 'timeout'
        }
    }

    # ==================== 样式配置 ====================
    STYLE_CONFIG = {
        'error': {
            'title_color': '#FF4D4F',
            'bg_color': '#FFFFFF',
            'border_color': '#FFCCC7',
            'icon_color': '#FF4D4F'
        },
        'warning': {
            'title_color': '#FAAD14',
            'bg_color': '#FFFFFF',
            'border_color': '#FFE58F',
            'icon_color': '#FAAD14'
        },
        'info': {
            'title_color': '#1890FF',
            'bg_color': '#FFFFFF',
            'border_color': '#91D5FF',
            'icon_color': '#1890FF'
        },
        'success': {
            'title_color': '#52C41A',
            'bg_color': '#FFFFFF',
            'border_color': '#B7EB8F',
            'icon_color': '#52C41A'
        }
    }

    def __init__(
        self,
        fonts_dir: Optional[str] = None,
        api_key: Optional[str] = None,
        vlm_api_url: str = 'https://api.openai-next.com/v1/chat/completions',
        vlm_model: str = 'gpt-4o',
        reference_path: Optional[str] = None
    ):
        """
        初始化语义弹窗生成器

        Args:
            fonts_dir: 字体目录
            api_key: VLM API 密钥（用于语义分析）
            vlm_api_url: VLM API 端点（用于语义分析）
            vlm_model: VLM 模型名称
            reference_path: 参考弹窗图片路径（用于风格学习）

        Note:
            图像生成使用 DashScope API，API Key 从环境变量 DASHSCOPE_API_KEY 获取
        """
        self.fonts_dir = fonts_dir
        self.api_key = api_key
        self.vlm_api_url = vlm_api_url
        self.vlm_model = vlm_model
        self.font_cache = {}

        # 参考图片风格分析
        self.reference_style = None
        self.style_applier = None
        if reference_path and Path(reference_path).exists():
            analyzer = ReferenceAnalyzer(
                api_key=api_key,
                vlm_api_url=vlm_api_url,
                vlm_model=vlm_model
            )
            self.reference_style = analyzer.analyze(reference_path)
            self.style_applier = ReferenceStyleApplier(self.reference_style)
            print(f"  ✓ 已加载参考风格: {reference_path}")

    # ==================== 场景识别 ====================
    def detect_scene(self, ui_json: dict, screenshot_path: str = None) -> Tuple[str, List[str]]:
        """
        根据 UI-JSON 和截图识别页面场景

        Returns:
            (scene_type, suggested_dialog_types)
        """
        # 收集页面中的所有文本
        texts = []
        for comp in ui_json.get('components', []):
            if comp.get('text'):
                texts.append(comp['text'])

        all_text = ' '.join(texts).lower()

        # 匹配场景
        best_scene = 'network'  # 默认场景
        best_score = 0

        for scene, config in self.SCENE_PATTERNS.items():
            score = sum(1 for kw in config['keywords'] if kw.lower() in all_text)
            if score > best_score:
                best_score = score
                best_scene = scene

        dialog_types = self.SCENE_PATTERNS.get(best_scene, {}).get('dialog_types', ['network_error'])
        return best_scene, dialog_types

    def generate_semantic_content(
        self,
        ui_json: dict,
        instruction: str,
        screenshot_path: str = None
    ) -> Dict[str, Any]:
        """
        使用 VLM 分析页面并生成符合语义的弹窗内容

        Returns:
            包含弹窗配置的字典
        """
        # 先用规则匹配场景
        scene, suggested_types = self.detect_scene(ui_json, screenshot_path)

        # 如果有 API key，使用 VLM 生成更精确的内容
        if self.api_key and screenshot_path:
            try:
                return self._vlm_generate_content(ui_json, instruction, screenshot_path, scene)
            except Exception as e:
                print(f"  ⚠ VLM 内容生成失败，使用模板: {e}")

        # 回退到模板
        return self._template_generate_content(scene, suggested_types, instruction)

    def _vlm_generate_content(
        self,
        ui_json: dict,
        instruction: str,
        screenshot_path: str,
        scene: str
    ) -> Dict[str, Any]:
        """使用 VLM 生成精确的弹窗内容"""
        # 编码图片
        with open(screenshot_path, 'rb') as f:
            image_base64 = base64.b64encode(f.read()).decode('utf-8')

        prompt = f"""分析这个App页面截图，根据用户指令生成一个逼真的弹窗内容。

用户指令: {instruction}
检测到的场景类型: {scene}

请生成一个符合该页面实际使用场景的弹窗，要求：
1. 弹窗内容要与页面主题相关（如火车票页面应该是余票、票价相关的弹窗）
2. 文案要真实自然，像真实App会显示的内容
3. 如果是广告弹窗，要与页面商品/服务相关

请以JSON格式返回：
```json
{{
    "title": "弹窗标题",
    "message": "弹窗正文内容",
    "style": "error/warning/info/success",
    "buttons": ["按钮1文本", "按钮2文本"],
    "is_ad": false,
    "icon_type": "warning/error/info/success/coupon/vip"
}}
```

只返回JSON，不要其他内容。"""

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }

        payload = {
            'model': self.vlm_model,
            'messages': [
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'image_url',
                            'image_url': {'url': f'data:image/png;base64,{image_base64}'}
                        },
                        {'type': 'text', 'text': prompt}
                    ]
                }
            ],
            'temperature': 0.7,
            'max_tokens': 500
        }

        response = requests.post(self.vlm_api_url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        content = response.json()['choices'][0]['message']['content']

        # 提取 JSON
        import re
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            return json.loads(json_match.group(0))

        raise ValueError("无法解析 VLM 返回的内容")

    def _template_generate_content(
        self,
        scene: str,
        suggested_types: List[str],
        instruction: str
    ) -> Dict[str, Any]:
        """使用模板生成弹窗内容"""
        import random

        # 选择弹窗类型
        dialog_type = suggested_types[0] if suggested_types else 'network_error'

        # 根据指令关键词调整
        instruction_lower = instruction.lower()
        if '广告' in instruction_lower or '推荐' in instruction_lower:
            for dt in suggested_types:
                if self.DIALOG_TEMPLATES.get(dt, {}).get('is_ad'):
                    dialog_type = dt
                    break
        elif '错误' in instruction_lower or '失败' in instruction_lower:
            for dt in suggested_types:
                if self.DIALOG_TEMPLATES.get(dt, {}).get('style') == 'error':
                    dialog_type = dt
                    break
        elif '余票' in instruction_lower or '库存' in instruction_lower or '售罄' in instruction_lower:
            if 'no_ticket' in suggested_types:
                dialog_type = 'no_ticket'
            elif 'out_of_stock' in suggested_types:
                dialog_type = 'out_of_stock'

        template = self.DIALOG_TEMPLATES.get(dialog_type, self.DIALOG_TEMPLATES['network_error'])

        return {
            'title': template['title'],
            'message': random.choice(template['messages']),
            'style': template['style'],
            'buttons': template['buttons'],
            'is_ad': template.get('is_ad', False),
            'icon_type': template.get('icon', 'info')
        }

    # ==================== 方案一：PIL 代码生成 ====================
    def generate_dialog_pil(
        self,
        content: Dict[str, Any],
        width: int = 600,
        height: int = 400,
        screen_width: int = 1080,
        screen_height: int = 1920
    ) -> Image.Image:
        """
        使用 PIL 绘制逼真的弹窗

        增强特性：
        - 圆角矩形
        - 阴影效果
        - 图标绘制
        - 按钮样式
        - 渐变背景
        - 参考风格学习
        """
        title = content.get('title', '提示')
        message = content.get('message', '')
        style = content.get('style', 'info')
        buttons = content.get('buttons', ['确定'])
        is_ad = content.get('is_ad', False)
        icon_type = content.get('icon_type', 'info')

        # 使用参考风格（如果有）
        if self.style_applier:
            ref_colors = self.style_applier.get_colors()
            ref_layout = self.style_applier.get_layout()
            corner_radius = self.style_applier.get_corner_radius()

            style_config = {
                'title_color': ref_colors.get('button_primary', '#FFD700'),
                'bg_color': ref_colors.get('background', '#FFFFFF'),
                'border_color': '#DDDDDD',
                'icon_color': ref_colors.get('button_primary', '#FFD700'),
                'button_color': ref_colors.get('button_primary', '#FFD700')
            }
            # 广告弹窗使用参考风格
            is_ad = True
        else:
            style_config = self.STYLE_CONFIG.get(style, self.STYLE_CONFIG['info'])
            corner_radius = 16

        # 创建带阴影的画布
        shadow_offset = 12
        canvas_width = width + shadow_offset * 2
        canvas_height = height + shadow_offset * 2

        canvas = Image.new('RGBA', (canvas_width, canvas_height), (0, 0, 0, 0))

        # 绘制阴影（参考风格通常有更明显的阴影）
        shadow_blur = 12 if self.style_applier else 8
        shadow = self._create_rounded_rect(
            width, height, corner_radius,
            fill_color=(0, 0, 0, 60 if self.style_applier else 50)
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_blur))
        canvas.paste(shadow, (shadow_offset + 6, shadow_offset + 6), shadow)

        # 绘制主体
        dialog_bg = self._create_rounded_rect(
            width, height, corner_radius,
            fill_color=self._parse_color(style_config['bg_color'])
        )
        canvas.paste(dialog_bg, (shadow_offset, shadow_offset), dialog_bg)

        draw = ImageDraw.Draw(canvas)
        base_x = shadow_offset
        base_y = shadow_offset

        # 绘制顶部装饰条（广告弹窗 - 参考风格不需要顶部装饰条）
        if is_ad and not self.style_applier:
            self._draw_rounded_rect(
                draw,
                (base_x, base_y, base_x + width, base_y + 8),
                radius=corner_radius,
                fill=self._parse_color(style_config['title_color']),
                corners=['top_left', 'top_right']
            )

        # 绘制图标
        icon_size = 48
        icon_x = base_x + 30
        icon_y = base_y + 40
        self._draw_icon(draw, icon_type, (icon_x, icon_y), icon_size, style_config['icon_color'])

        # 绘制标题
        title_font = self._get_font(20, bold=True)
        title_x = icon_x + icon_size + 15
        title_y = icon_y + (icon_size - 24) // 2
        draw.text(
            (title_x, title_y),
            title,
            font=title_font,
            fill=self._parse_color(style_config['title_color'])
        )

        # 绘制消息内容
        msg_font = self._get_font(16)
        msg_x = base_x + 30
        msg_y = icon_y + icon_size + 20

        # 自动换行
        lines = self._wrap_text(message, width - 60, msg_font)
        for line in lines:
            draw.text((msg_x, msg_y), line, font=msg_font, fill='#666666')
            msg_y += 24

        # 绘制按钮
        btn_height = 48 if self.style_applier else 44
        btn_y = base_y + height - btn_height - 25
        btn_spacing = 15

        # 获取按钮颜色
        btn_color = style_config.get('button_color', style_config['title_color'])

        if len(buttons) == 1:
            # 单按钮居中（参考风格的按钮更宽）
            btn_width = width - 50 if self.style_applier else width - 60
            btn_x = base_x + (width - btn_width) // 2
            self._draw_button(
                draw, canvas,
                (btn_x, btn_y, btn_x + btn_width, btn_y + btn_height),
                buttons[0],
                primary=True,
                color=btn_color,
                rounded=24 if self.style_applier else 8
            )
        else:
            # 双按钮
            btn_width = (width - 75) // 2
            btn_x1 = base_x + 30
            btn_x2 = btn_x1 + btn_width + 15

            self._draw_button(
                draw, canvas,
                (btn_x1, btn_y, btn_x1 + btn_width, btn_y + btn_height),
                buttons[1] if len(buttons) > 1 else '取消',
                primary=False,
                rounded=24 if self.style_applier else 8
            )
            self._draw_button(
                draw, canvas,
                (btn_x2, btn_y, btn_x2 + btn_width, btn_y + btn_height),
                buttons[0],
                primary=True,
                color=btn_color,
                rounded=24 if self.style_applier else 8
            )

        # 如果是广告弹窗，添加关闭按钮
        if is_ad:
            if self.style_applier:
                # 参考风格的关闭按钮在右上角外侧
                close_config = self.style_applier.get_close_button_config()
                close_size = close_config.get('size', 28)
                close_x = base_x + width - close_size // 2
                close_y = base_y - close_size // 2
                self._draw_close_button_styled(
                    canvas, draw, (close_x, close_y), close_size,
                    bg_color=close_config.get('background', '#FFFFFF'),
                    icon_color=close_config.get('icon_color', '#666666')
                )
            else:
                close_size = 24
                close_x = base_x + width - close_size - 12
                close_y = base_y + 12
                self._draw_close_button(draw, (close_x, close_y), close_size)

        return canvas

    def _create_rounded_rect(
        self,
        width: int,
        height: int,
        radius: int,
        fill_color: Tuple[int, int, int, int]
    ) -> Image.Image:
        """创建圆角矩形图像"""
        # 使用更大的尺寸绘制，然后缩小以获得抗锯齿效果
        scale = 2
        img = Image.new('RGBA', (width * scale, height * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        r = radius * scale
        draw.rounded_rectangle(
            [0, 0, width * scale - 1, height * scale - 1],
            radius=r,
            fill=fill_color
        )

        return img.resize((width, height), Image.Resampling.LANCZOS)

    def _draw_rounded_rect(
        self,
        draw: ImageDraw.ImageDraw,
        bbox: Tuple[int, int, int, int],
        radius: int,
        fill: Tuple[int, int, int, int],
        corners: List[str] = None
    ):
        """绘制圆角矩形（支持指定圆角）"""
        x1, y1, x2, y2 = bbox
        draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill)

    def _draw_icon(
        self,
        draw: ImageDraw.ImageDraw,
        icon_type: str,
        position: Tuple[int, int],
        size: int,
        color: str
    ):
        """绘制图标"""
        x, y = position
        color_rgba = self._parse_color(color)

        # 绘制圆形背景
        bg_color = (*color_rgba[:3], 30)  # 淡色背景
        draw.ellipse([x, y, x + size, y + size], fill=bg_color)

        # 绘制图标符号
        center_x = x + size // 2
        center_y = y + size // 2

        if icon_type in ['error', 'warning']:
            # 三角形警告图标
            points = [
                (center_x, y + 10),
                (x + 10, y + size - 10),
                (x + size - 10, y + size - 10)
            ]
            draw.polygon(points, outline=color_rgba, width=2)
            # 感叹号
            draw.text((center_x - 3, center_y - 8), '!', fill=color_rgba, font=self._get_font(16, bold=True))
        elif icon_type == 'info':
            # 圆形信息图标
            draw.ellipse([x + 8, y + 8, x + size - 8, y + size - 8], outline=color_rgba, width=2)
            draw.text((center_x - 3, center_y - 8), 'i', fill=color_rgba, font=self._get_font(16, bold=True))
        elif icon_type == 'success':
            # 对勾图标
            draw.ellipse([x + 8, y + 8, x + size - 8, y + size - 8], outline=color_rgba, width=2)
            # 简化的对勾
            draw.line([(center_x - 8, center_y), (center_x - 2, center_y + 6), (center_x + 8, center_y - 6)],
                     fill=color_rgba, width=2)
        elif icon_type in ['coupon', 'vip', 'flash']:
            # 礼物/优惠图标（简化为星形）
            draw.ellipse([x + 4, y + 4, x + size - 4, y + size - 4], fill=color_rgba)
            draw.text((center_x - 6, center_y - 10), '★', fill='#FFFFFF', font=self._get_font(20))

    def _draw_button(
        self,
        draw: ImageDraw.ImageDraw,
        canvas: Image.Image,
        bbox: Tuple[int, int, int, int],
        text: str,
        primary: bool = True,
        color: str = '#1890FF',
        rounded: int = 8
    ):
        """绘制按钮"""
        x1, y1, x2, y2 = bbox
        width = x2 - x1
        height = y2 - y1

        if primary:
            fill_color = self._parse_color(color)
            text_color = '#333333' if self._is_light_color(fill_color) else '#FFFFFF'
        else:
            fill_color = (245, 245, 245, 255)
            text_color = '#666666'

        # 绘制圆角按钮
        btn_img = self._create_rounded_rect(width, height, rounded, fill_color)
        canvas.paste(btn_img, (x1, y1), btn_img)

        # 绘制按钮文字
        font = self._get_font(16 if self.style_applier else 15)
        bbox_text = draw.textbbox((0, 0), text, font=font)
        text_width = bbox_text[2] - bbox_text[0]
        text_height = bbox_text[3] - bbox_text[1]

        text_x = x1 + (width - text_width) // 2
        text_y = y1 + (height - text_height) // 2
        draw.text((text_x, text_y), text, font=font, fill=text_color)

    def _is_light_color(self, rgba: Tuple[int, int, int, int]) -> bool:
        """判断颜色是否为浅色（用于决定文字颜色）"""
        r, g, b = rgba[:3]
        # 计算亮度
        brightness = (r * 299 + g * 587 + b * 114) / 1000
        return brightness > 186

    def _draw_close_button(
        self,
        draw: ImageDraw.ImageDraw,
        position: Tuple[int, int],
        size: int
    ):
        """绘制关闭按钮（基础样式）"""
        x, y = position
        # 圆形背景
        draw.ellipse([x, y, x + size, y + size], fill=(0, 0, 0, 50))
        # X 符号
        padding = 6
        draw.line([(x + padding, y + padding), (x + size - padding, y + size - padding)],
                 fill='#FFFFFF', width=2)
        draw.line([(x + size - padding, y + padding), (x + padding, y + size - padding)],
                 fill='#FFFFFF', width=2)

    def _draw_close_button_styled(
        self,
        canvas: Image.Image,
        draw: ImageDraw.ImageDraw,
        position: Tuple[int, int],
        size: int,
        bg_color: str = '#FFFFFF',
        icon_color: str = '#666666'
    ):
        """绘制关闭按钮（参考风格样式 - 带阴影的白色圆形）"""
        x, y = position

        # 创建带阴影的关闭按钮
        btn_size = size + 8  # 增加阴影空间
        btn_canvas = Image.new('RGBA', (btn_size, btn_size), (0, 0, 0, 0))
        btn_draw = ImageDraw.Draw(btn_canvas)

        # 绘制阴影
        shadow_offset = 2
        btn_draw.ellipse(
            [shadow_offset + 2, shadow_offset + 2, btn_size - 2, btn_size - 2],
            fill=(0, 0, 0, 40)
        )
        btn_canvas = btn_canvas.filter(ImageFilter.GaussianBlur(3))
        btn_draw = ImageDraw.Draw(btn_canvas)

        # 绘制白色圆形背景
        padding = 4
        btn_draw.ellipse(
            [padding, padding, btn_size - padding, btn_size - padding],
            fill=self._parse_color(bg_color)
        )

        # 绘制 X 符号
        icon_padding = 10
        icon_color_rgba = self._parse_color(icon_color)
        center = btn_size // 2
        line_len = (btn_size - icon_padding * 2) // 2

        btn_draw.line(
            [(center - line_len, center - line_len), (center + line_len, center + line_len)],
            fill=icon_color_rgba, width=3
        )
        btn_draw.line(
            [(center + line_len, center - line_len), (center - line_len, center + line_len)],
            fill=icon_color_rgba, width=3
        )

        # 粘贴到主画布
        canvas.paste(btn_canvas, (x - 4, y - 4), btn_canvas)

    def _get_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        """获取字体"""
        cache_key = (size, bold)
        if cache_key in self.font_cache:
            return self.font_cache[cache_key]

        font_paths = [
            'C:/Windows/Fonts/msyh.ttc',
            'C:/Windows/Fonts/simhei.ttf',
            '/System/Library/Fonts/PingFang.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ]

        if self.fonts_dir:
            font_dir = Path(self.fonts_dir)
            for f in font_dir.glob('*.ttf'):
                font_paths.insert(0, str(f))
            for f in font_dir.glob('*.ttc'):
                font_paths.insert(0, str(f))

        for path in font_paths:
            if Path(path).exists():
                try:
                    font = ImageFont.truetype(path, size)
                    self.font_cache[cache_key] = font
                    return font
                except:
                    continue

        font = ImageFont.load_default()
        self.font_cache[cache_key] = font
        return font

    def _wrap_text(self, text: str, max_width: int, font: ImageFont.FreeTypeFont) -> List[str]:
        """文本自动换行"""
        lines = []
        current_line = ""

        # 创建临时 draw 对象用于测量
        temp_img = Image.new('RGBA', (1, 1))
        temp_draw = ImageDraw.Draw(temp_img)

        for char in text:
            test_line = current_line + char
            bbox = temp_draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = char

        if current_line:
            lines.append(current_line)

        return lines

    def _parse_color(self, color: str) -> Tuple[int, int, int, int]:
        """解析颜色字符串"""
        if color.startswith('#'):
            color = color[1:]
            if len(color) == 3:
                color = ''.join(c * 2 for c in color)
            if len(color) == 6:
                r = int(color[0:2], 16)
                g = int(color[2:4], 16)
                b = int(color[4:6], 16)
                return (r, g, b, 255)
            elif len(color) == 8:
                r = int(color[0:2], 16)
                g = int(color[2:4], 16)
                b = int(color[4:6], 16)
                a = int(color[6:8], 16)
                return (r, g, b, a)
        return (0, 0, 0, 255)

    # ==================== 方案二：AI 图像直接生成 ====================
    def generate_dialog_ai(
        self,
        content: Dict[str, Any],
        width: int = 600,
        height: int = 400,
        screenshot_path: str = None,
        app_style: str = 'wechat'
    ) -> Optional[Image.Image]:
        """
        使用 DashScope qwen-image-max 模型生成弹窗图像

        Args:
            content: 弹窗内容配置
            width: 目标宽度
            height: 目标高度
            screenshot_path: 原始截图（用于风格参考）
            app_style: App 风格参考

        Returns:
            生成的弹窗图像
        """
        title = content.get('title', '提示')
        message = content.get('message', '')
        style = content.get('style', 'info')
        buttons = content.get('buttons', ['确定'])
        is_ad = content.get('is_ad', False)

        # 构建详细的提示词
        prompt = self._build_ai_prompt(title, message, style, buttons, is_ad, app_style)

        print(f"  正在使用 DashScope AI 生成弹窗 (目标尺寸: {width}x{height})...")

        # 计算生成尺寸（qwen-image-max 支持的尺寸）
        gen_size = f"{width}*{height}"

        # 创建调试输出目录
        debug_dir = Path("debug_dialog_output")
        debug_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        try:
            image = generate_image_dashscope(
                prompt=prompt,
                size=gen_size
            )

            if image:
                gen_width, gen_height = image.size

                # [调试] 保存原始 AI 生成的图像
                raw_path = debug_dir / f"1_raw_ai_{timestamp}.png"
                image.save(raw_path)
                print(f"  [调试] 原始AI图像已保存: {raw_path}")

                # 后处理：调整到精确的目标尺寸
                if (gen_width, gen_height) != (width, height):
                    print(f"  ℹ 后处理: {gen_width}x{gen_height} → {width}x{height}")
                    image = image.resize((width, height), Image.Resampling.LANCZOS)

                # 后处理：移除背景，使弹窗外的区域变为透明
                print(f"  正在移除背景...")
                image = self._remove_background(image, tolerance=30)

                # [调试] 保存移除背景后的图像
                transparent_path = debug_dir / f"2_transparent_{timestamp}.png"
                image.save(transparent_path)
                print(f"  [调试] 透明背景图像已保存: {transparent_path}")

                print(f"  ✓ AI 弹窗生成成功: {width}x{height}")
                return image
            else:
                raise Exception("图像生成返回空结果")

        except Exception as e:
            print(f"  ⚠ AI 生成失败: {e}")
            raise  # 不返回 None，直接抛出异常

    def _remove_background(self, image: Image.Image, tolerance: int = 30) -> Image.Image:
        """
        移除 AI 生成图像的背景，使用从边缘扩散的洪水填充算法

        只移除与边缘背景色相连的像素，避免误删弹窗内部的相似颜色像素。

        Args:
            image: 输入图像（RGBA）
            tolerance: 颜色容差，越大则移除更多相似颜色的像素

        Returns:
            处理后的透明背景图像
        """
        if image.mode != 'RGBA':
            image = image.convert('RGBA')

        width, height = image.size
        pixels = image.load()

        # 直接使用纯黑色作为背景色（AI 生成时已要求纯黑背景）
        # 不再从角落采样，因为背景应该是固定的黑色
        bg_color = (0, 0, 0)
        print(f"  ℹ 目标背景色: RGB(0, 0, 0) 纯黑色")

        # 使用洪水填充从边缘开始标记背景像素
        # 创建访问标记数组
        to_remove = set()
        visited = set()

        def is_background_color(x: int, y: int) -> bool:
            """检查像素是否接近背景色"""
            r, g, b, a = pixels[x, y]
            diff = abs(r - bg_color[0]) + abs(g - bg_color[1]) + abs(b - bg_color[2])
            return diff <= tolerance * 3

        def flood_fill_from_edges():
            """从图像边缘开始洪水填充，标记所有连通的背景像素"""
            # 初始化队列：添加所有边缘像素
            queue = []

            # 上边缘和下边缘
            for x in range(width):
                if is_background_color(x, 0):
                    queue.append((x, 0))
                if is_background_color(x, height - 1):
                    queue.append((x, height - 1))

            # 左边缘和右边缘
            for y in range(height):
                if is_background_color(0, y):
                    queue.append((0, y))
                if is_background_color(width - 1, y):
                    queue.append((width - 1, y))

            # BFS 洪水填充
            while queue:
                x, y = queue.pop(0)

                if (x, y) in visited:
                    continue

                if x < 0 or x >= width or y < 0 or y >= height:
                    continue

                if not is_background_color(x, y):
                    continue

                visited.add((x, y))
                to_remove.add((x, y))

                # 添加相邻的4个像素（4连通）
                queue.append((x + 1, y))
                queue.append((x - 1, y))
                queue.append((x, y + 1))
                queue.append((x, y - 1))

        # 执行洪水填充
        flood_fill_from_edges()

        # 找出保留的像素（非背景像素）
        retained_pixels = set()
        for y in range(height):
            for x in range(width):
                if (x, y) not in to_remove:
                    retained_pixels.add((x, y))

        # 孤岛过滤：只保留与主要内容区域相连的像素
        # 找到最大的连通区域（弹窗主体），移除孤立的小区域
        main_content = self._find_largest_connected_region(retained_pixels, width, height)

        # 创建结果图像
        result = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        result_pixels = result.load()

        # 复制像素，只保留主要内容区域
        for y in range(height):
            for x in range(width):
                if (x, y) in main_content:
                    result_pixels[x, y] = pixels[x, y]
                else:
                    result_pixels[x, y] = (0, 0, 0, 0)

        # 对边缘进行额外处理（渐变透明，使边缘更平滑）
        # 注意：只对弹窗边缘做轻微平滑，不影响已经透明的区域
        result = self._smooth_edges_safe(result, blur_radius=0.8)

        # 关键修复：对 alpha 通道进行阈值处理，消除半透明边缘导致的灰色条纹
        # 半透明像素（alpha 在 1-254 之间）与底图合成时会产生灰白色条纹
        # 通过阈值处理，将 alpha < 128 的像素变为完全透明，alpha >= 128 的变为完全不透明
        result = self._threshold_alpha(result, threshold=128)

        removed_percent = (1 - len(main_content) / (width * height)) * 100
        isolated_removed = len(retained_pixels) - len(main_content)
        print(f"  ✓ 背景移除完成: 移除了 {removed_percent:.1f}% 的像素（含 {isolated_removed} 个孤立像素）")

        return result

    def _find_largest_connected_region(
        self,
        pixels_set: set,
        width: int,
        height: int
    ) -> set:
        """
        找到最大的连通区域（8连通）

        Args:
            pixels_set: 需要分析的像素坐标集合
            width: 图像宽度
            height: 图像高度

        Returns:
            最大连通区域的像素坐标集合
        """
        if not pixels_set:
            return set()

        visited = set()
        largest_region = set()

        def bfs_find_region(start_x: int, start_y: int) -> set:
            """BFS 查找与起点相连的所有像素（8连通）"""
            region = set()
            queue = [(start_x, start_y)]

            while queue:
                x, y = queue.pop(0)

                if (x, y) in visited:
                    continue
                if (x, y) not in pixels_set:
                    continue

                visited.add((x, y))
                region.add((x, y))

                # 8连通：检查周围8个像素
                for dx in [-1, 0, 1]:
                    for dy in [-1, 0, 1]:
                        if dx == 0 and dy == 0:
                            continue
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < width and 0 <= ny < height:
                            if (nx, ny) not in visited and (nx, ny) in pixels_set:
                                queue.append((nx, ny))

            return region

        # 遍历所有像素，找到所有连通区域
        for (x, y) in pixels_set:
            if (x, y) not in visited:
                region = bfs_find_region(x, y)
                if len(region) > len(largest_region):
                    largest_region = region

        return largest_region

    def _smooth_edges(self, image: Image.Image, blur_radius: float = 0.5) -> Image.Image:
        """
        平滑处理透明边缘，减少锯齿

        Args:
            image: RGBA 图像
            blur_radius: 模糊半径，用于平滑边缘

        Returns:
            边缘平滑后的图像
        """
        if image.mode != 'RGBA':
            return image

        # 提取 alpha 通道
        r, g, b, alpha = image.split()

        # 对 alpha 通道进行轻微模糊以平滑边缘
        alpha_blurred = alpha.filter(ImageFilter.GaussianBlur(radius=blur_radius))

        # 重新合并通道
        result = Image.merge('RGBA', (r, g, b, alpha_blurred))

        return result

    def _smooth_edges_safe(self, image: Image.Image, blur_radius: float = 0.5) -> Image.Image:
        """
        安全的边缘平滑处理 - 只平滑边缘，不影响已经完全透明的区域

        问题：普通的 _smooth_edges 会把 alpha=0 的像素变成 alpha>0，
        导致透明背景区域在合成时显示出 RGB 值（灰色）。

        解决：只在原本有内容（alpha>0）的区域附近进行平滑，
        完全透明的区域保持 alpha=0。

        Args:
            image: RGBA 图像
            blur_radius: 模糊半径

        Returns:
            边缘平滑后的图像
        """
        if image.mode != 'RGBA':
            return image

        r, g, b, alpha = image.split()

        # 对 alpha 通道进行模糊
        alpha_blurred = alpha.filter(ImageFilter.GaussianBlur(radius=blur_radius))

        # 关键：使用原始 alpha 作为遮罩
        # 原本完全透明的像素（alpha=0）保持透明，不使用模糊后的值
        # 使用 ImageChops 实现：result = min(original, blurred)
        # 这样原本 alpha=0 的区域不会变成 alpha>0
        from PIL import ImageChops
        alpha_result = ImageChops.darker(alpha, alpha_blurred)

        result = Image.merge('RGBA', (r, g, b, alpha_result))

        return result

    def _threshold_alpha(self, image: Image.Image, threshold: int = 128) -> Image.Image:
        """
        对 alpha 通道进行阈值处理，消除半透明边缘

        将 alpha 值低于阈值的像素设为完全透明，高于阈值的设为完全不透明。
        这样可以避免合成时半透明像素与底图混合产生黑边。

        Args:
            image: RGBA 图像
            threshold: alpha 阈值 (0-255)，低于此值的像素变为透明

        Returns:
            处理后的图像
        """
        if image.mode != 'RGBA':
            return image

        # 提取各通道
        r, g, b, alpha = image.split()

        # 对 alpha 通道进行阈值处理：低于阈值变0，高于阈值变255
        alpha_threshold = alpha.point(lambda x: 255 if x >= threshold else 0)

        # 重新合并通道
        result = Image.merge('RGBA', (r, g, b, alpha_threshold))

        return result

    def _build_ai_prompt(
        self,
        title: str,
        message: str,
        style: str,
        buttons: List[str],
        is_ad: bool,
        app_style: str
    ) -> str:
        """构建 AI 图像生成的提示词"""
        # 如果有参考风格，使用参考风格的提示词
        if self.style_applier:
            return self.style_applier.get_ai_prompt(title, message)

        style_desc = {
            'error': 'red accent color, error/warning theme',
            'warning': 'orange/yellow accent color, caution theme',
            'info': 'blue accent color, informational theme',
            'success': 'green accent color, success/confirmation theme'
        }.get(style, 'blue accent color')

        buttons_desc = ' and '.join([f'"{b}" button' for b in buttons])

        # 要求纯黑色背景，便于后续处理时移除
        black_bg = """CRITICAL BACKGROUND REQUIREMENT:
- The background MUST be pure solid BLACK (#000000, RGB 0,0,0)
- Only render the dialog card itself with its white rounded rectangle
- The area OUTSIDE the dialog card must be 100% pure black - no gradients, no other colors
- This black background will be removed in post-processing
- DO NOT use any other background color - ONLY pure black"""

        if is_ad:
            prompt = f"""A mobile app promotional popup dialog in {app_style} style:
- Clean white rounded rectangle card with subtle drop shadow
- Colorful header banner at top
- Title: "{title}" in bold
- Message: "{message}"
- {buttons_desc} at bottom
- Small close (X) button in top-right corner
- Modern minimalist design like WeChat/iOS
- High resolution, crisp Chinese text
- {style_desc}

{black_bg}"""
        else:
            prompt = f"""A mobile app alert dialog popup in {app_style} style:
- Clean white rounded rectangle card with subtle drop shadow
- Icon matching the alert type on left side
- Title: "{title}" in bold, {style_desc}
- Message: "{message}" in gray
- {buttons_desc} at bottom
- Modern minimalist flat design like WeChat or iOS alert
- High resolution, crisp Chinese text rendering
- Professional mobile app quality

{black_bg}"""

        return prompt

    # ==================== 统一接口 ====================
    def get_dialog_bounds_from_reference(
        self,
        screen_width: int,
        screen_height: int
    ) -> Optional[Dict[str, int]]:
        """
        根据参考风格获取弹窗的位置和尺寸

        Args:
            screen_width: 目标屏幕宽度
            screen_height: 目标屏幕高度

        Returns:
            弹窗坐标字典 {'x', 'y', 'width', 'height'}，如果没有参考风格则返回 None
        """
        if self.style_applier:
            return self.style_applier.get_bounds_for_screen(screen_width, screen_height)
        return None

    def generate(
        self,
        ui_json: dict,
        instruction: str,
        screenshot_path: str,
        width: int = 600,
        height: int = 400,
        mode: str = 'pil',
        screen_width: int = 1080,
        screen_height: int = 1920
    ) -> Tuple[Image.Image, Dict[str, Any]]:
        """
        统一的弹窗生成接口

        Args:
            ui_json: UI 结构
            instruction: 异常指令
            screenshot_path: 截图路径
            width: 弹窗宽度（如果有参考风格会被覆盖）
            height: 弹窗高度（如果有参考风格会被覆盖）
            mode: 渲染模式 ('pil' 或 'ai')
            screen_width: 目标屏幕宽度
            screen_height: 目标屏幕高度

        Returns:
            (弹窗图像, 内容配置)
        """
        # 如果有参考风格，使用参考风格的尺寸
        if self.style_applier:
            bounds = self.style_applier.get_bounds_for_screen(screen_width, screen_height)
            width = bounds['width']
            height = bounds['height']
            print(f"  ✓ 使用参考风格尺寸: {width}x{height}")

        # 生成语义内容
        content = self.generate_semantic_content(ui_json, instruction, screenshot_path)
        msg_preview = content.get('message', '')[:30]
        print(f"  ✓ 语义内容: {content.get('title')} - {msg_preview}...")

        # 根据模式生成弹窗
        if mode == 'ai':
            # AI 模式：坚持使用 AI 生成，不回退到 PIL
            dialog = self.generate_dialog_ai(content, width, height, screenshot_path)
        else:
            dialog = self.generate_dialog_pil(content, width, height, screen_width, screen_height)

        return dialog, content
