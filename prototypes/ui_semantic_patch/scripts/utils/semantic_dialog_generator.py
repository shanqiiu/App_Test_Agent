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
import re
import random
import base64
import time
import os
import requests
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
import io

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
    save_path: str = None,
    prompt_extend: bool = True
) -> Optional[Image.Image]:
    """
    使用 DashScope MultiModalConversation API 生成图像

    Args:
        prompt: 图像描述提示词
        api_key: DashScope API Key（默认从环境变量 DASHSCOPE_API_KEY 获取）
        size: 图像尺寸，格式 'width*height'，会自动规范化到支持范围 [512, 2048]
        negative_prompt: 负面提示词
        save_path: 可选的保存路径
        prompt_extend: 是否启用提示词扩展（meta驱动生成建议关闭以保持精确控制）

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

    # 默认负面提示词（排除非黑色背景、低质量图像、品牌logo）
    if negative_prompt is None:
        negative_prompt = "低分辨率，低画质，肢体畸形，手指畸形，画面过饱和，蜡像感，人脸无细节，过度光滑，画面具有AI感。构图混乱。文字模糊，扭曲。白色背景，灰色背景，渐变背景，彩色背景，white background, gray background, colored background, gradient background, 美团logo, 淘宝logo, 京东logo, 华为logo, 抖音logo, HarmonyOS, brand logo, brand text, watermark"

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
                prompt_extend=prompt_extend,
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

        gen_size = f"{width}*{height}"

        try:
            image = generate_image_dashscope(prompt=prompt, size=gen_size)

            if image:
                gen_width, gen_height = image.size

                # 后处理：调整到精确的目标尺寸
                if (gen_width, gen_height) != (width, height):
                    print(f"  ℹ 后处理: {gen_width}x{gen_height} → {width}x{height}")
                    image = image.resize((width, height), Image.Resampling.LANCZOS)

                # 后处理：移除背景，使弹窗外的区域变为透明
                # tolerance=70 可以更好地去除灰色边框/阴影
                image = self._remove_background(image, tolerance=70)

                print(f"  ✓ AI 弹窗生成成功: {width}x{height}")
                return image
            else:
                raise Exception("图像生成返回空结果")

        except Exception as e:
            print(f"  ⚠ AI 生成失败: {e}")
            raise  # 不返回 None，直接抛出异常

    def generate_dialog_ai_from_meta(
        self,
        meta_semantic: str,
        meta_features: Dict[str, Any],
        reference_path: str,
        width: int = 600,
        height: int = 400,
        target_content: Dict[str, str] = None
    ) -> Optional[Image.Image]:
        """
        基于meta.json语义描述使用AI生成弹窗（增强版本）

        这是meta.json驱动生成的核心方法，与generate_dialog_ai的区别：
        - 使用meta.json提供的精确语义描述，而非VLM自动生成的内容
        - 结合参考图片的视觉风格
        - 生成质量更高、更一致

        Args:
            meta_semantic: MetaLoader.extract_semantic_prompt() 或 extract_visual_style_prompt() 的输出
            meta_features: MetaLoader.extract_visual_features_dict()的输出
            reference_path: 参考图片路径
            width: 目标宽度
            height: 目标高度
            target_content: VLM根据目标截图生成的语义内容（可选），格式：
                {
                    'title': '标题',
                    'message': '消息内容',
                    'button_text': '按钮文字',
                    'subtitle': '副标题（可选）'
                }
                如果提供，将使用这些文字而非meta中的文字

        Returns:
            生成的弹窗图像
        """
        # 使用meta信息构建prompt
        prompt = self._build_ai_prompt_from_meta(meta_semantic, meta_features, reference_path, target_content)

        print(f"  正在使用 Meta-driven AI 生成弹窗 (目标尺寸: {width}x{height})...")
        print(f"  ✓ 参考图: {reference_path}")
        print(f"  ✓ APP风格: {meta_features.get('app_style', '通用')}")
        print(f"  ✓ 主色调: {meta_features.get('primary_color', 'N/A')}")
        if target_content:
            print(f"  ✓ 语义内容: {target_content.get('title', 'N/A')} - {target_content.get('message', '')[:30]}...")

        gen_size = f"{width}*{height}"

        try:
            image = generate_image_dashscope(prompt=prompt, size=gen_size, prompt_extend=False)

            if image:
                gen_width, gen_height = image.size

                # 后处理：调整到精确的目标尺寸
                if (gen_width, gen_height) != (width, height):
                    print(f"  ℹ 后处理: {gen_width}x{gen_height} → {width}x{height}")
                    image = image.resize((width, height), Image.Resampling.LANCZOS)

                # 后处理：移除背景（包括灰色边框）
                # 根据弹窗背景色自适应调整 tolerance
                bg_str = meta_features.get('background', '')
                if any(kw in bg_str for kw in ('#FF', '红', 'red', '粉', 'pink', '渐变')):
                    bg_tolerance = 50  # 深色/彩色背景弹窗使用较低容差，避免吃掉内容边缘
                    print(f"  ℹ 彩色背景弹窗，使用较低背景移除容差: {bg_tolerance}")
                else:
                    bg_tolerance = 70
                image = self._remove_background(image, tolerance=bg_tolerance)

                # 后处理：擦除 AI 自行画的关闭按钮
                # AI 经常无视 "Do not draw close button" 指令，在角落画 X
                # 必须在裁切之前擦除，否则裁切后角落位置会变化
                image = self._erase_ai_close_button(image)

                # 后处理：多层弹窗清理
                # AI 生成时可能在目标弹窗之外额外生成多余的弹窗层
                # 对于横幅类型（宽高比 > 2:1），检测并去除多余层
                dialog_position = meta_features.get('dialog_position', 'center')
                if dialog_position in ('bottom-floating', 'bottom-fixed', 'bottom-center-floating'):
                    image = self._remove_extra_layers(image, expected_aspect_ratio=width/height)

                # 后处理：裁切到实际内容区域并 resize 到目标尺寸
                image = self._crop_to_content_and_resize(image, width, height)

                # 注意：关闭按钮不在此处绘制
                # 对于 bottom-center 等位置，关闭按钮应该在弹窗卡片外部
                # 因此在 run_pipeline.py 的最终合成阶段绘制关闭按钮
                # 这样可以正确计算关闭按钮在屏幕上的位置

                print(f"  ✓ Meta-driven AI 弹窗生成成功: {width}x{height}")
                return image
            else:
                raise Exception("图像生成返回空结果")

        except Exception as e:
            print(f"  ⚠ Meta-driven AI 生成失败: {e}")
            raise

    def generate_content_for_target_page(
        self,
        screenshot_path: str,
        instruction: str,
        anomaly_type: str = 'promotional_dialog',
        app_style: str = None
    ) -> Dict[str, str]:
        """
        使用 VLM 根据目标截图生成语义相关的弹窗内容

        这是分离"视觉风格"和"文字内容"的关键方法：
        - 视觉风格从 meta.json 获取（extract_visual_style_prompt）
        - 文字内容由本方法根据目标截图生成

        Args:
            screenshot_path: 目标截图路径
            instruction: 用户指令（如"模拟广告弹窗"）
            anomaly_type: 异常类型（从meta.json获取，用于约束生成的弹窗类型）
            app_style: APP风格（可选，用于风格一致性）

        Returns:
            {
                'title': '弹窗标题',
                'message': '弹窗正文内容',
                'button_text': '主按钮文字',
                'subtitle': '副标题（可选）'
            }
        """
        # 下拉菜单类型：尝试从 instruction 中提取菜单项
        if anomaly_type == 'context_menu_dropdown':
            print("  ✓ 下拉菜单类型：尝试从 instruction 提取菜单项")
            menu_items = self._extract_menu_items_from_instruction(instruction)
            if menu_items:
                print(f"    从 instruction 提取到菜单项: {menu_items}")
                return {
                    'title': '',
                    'message': '',
                    'button_text': '',
                    'subtitle': '',
                    'brand_name': '',
                    'menu_items': menu_items,  # instruction 中提取的菜单项
                    '_is_dropdown': True
                }
            else:
                print("    未能从 instruction 提取菜单项，将使用 meta.json 默认值")
                return {
                    'title': '',
                    'message': '',
                    'button_text': '',
                    'subtitle': '',
                    'brand_name': '',
                    '_is_dropdown': True
                }

        if not self.api_key:
            print("  ⚠ 未配置 VLM API Key，使用默认文案")
            return self._get_default_content_for_type(anomaly_type)

        # 编码图片
        try:
            with open(screenshot_path, 'rb') as f:
                image_base64 = base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            print(f"  ⚠ 读取截图失败: {e}")
            return self._get_default_content_for_type(anomaly_type)

        # 异常类型的中文描述
        anomaly_type_desc = {
            'promotional_dialog': '促销/优惠弹窗（如优惠券、折扣活动）',
            'reward_badge_dialog': '奖励/勋章弹窗（如积分奖励、成就解锁）',
            'permission_dialog': '权限请求弹窗（如通知权限、位置权限）',
            'tutorial_guide': '引导教程弹窗（如功能介绍、新手引导）',
            'context_menu_dropdown': '下拉菜单/选项弹窗',
            'tooltip_bubble': '提示气泡/引导提示',
            'floating_tip_banner': '浮动横幅提示',
            'coupon_popup': '优惠券弹窗',
            'vip_prompt': 'VIP会员推广弹窗'
        }.get(anomaly_type, '通用弹窗')

        prompt = f"""分析这个App页面截图，生成一个与页面内容**语义相关**的弹窗文案。

## 任务要求
1. 仔细分析截图中的APP类型、页面内容、业务场景
2. 生成的弹窗内容必须与该页面的业务场景相关
3. 文案要真实自然，像该APP真正会显示的弹窗
4. **重要**：识别截图中的APP品牌名称（如"携程"、"12306"、"美团"等）

## 弹窗类型约束
- 弹窗类型: {anomaly_type_desc}
- 用户指令: {instruction}
- 重要：品牌信息必须从截图中识别，不要猜测或使用其他品牌

## 示例
- 如果是机票/火车票页面 + 促销弹窗 → 生成"春运特惠券"、"机票立减50元"等内容
- 如果是电商页面 + 奖励弹窗 → 生成"恭喜获得购物金"、"新人专享礼包"等内容
- 如果是社交页面 + 权限弹窗 → 生成"开启消息通知"、"允许访问通讯录"等内容

## 输出格式
请以JSON格式返回弹窗文案，必须与截图中的APP业务相关：
```json
{{
    "title": "弹窗标题（简短，2-8个字）",
    "message": "弹窗正文（描述性内容，10-30个字）",
    "button_text": "主按钮文字（2-6个字）",
    "subtitle": "副标题或补充说明（可选，5-15个字）",
    "brand_name": "APP品牌名称（如携程、12306、美团，用于Logo显示）"
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

        try:
            response = requests.post(self.vlm_api_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()

            content = response.json()['choices'][0]['message']['content']

            # 提取 JSON
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                result = json.loads(json_match.group(0))
                # 确保必要字段存在
                if 'title' not in result:
                    result['title'] = '提示'
                if 'message' not in result:
                    result['message'] = ''
                if 'button_text' not in result:
                    result['button_text'] = '确定'
                if 'brand_name' not in result:
                    result['brand_name'] = ''
                return result

            raise ValueError("无法解析 VLM 返回的内容")

        except Exception as e:
            print(f"  ⚠ VLM 内容生成失败: {e}")
            return self._get_default_content_for_type(anomaly_type)

    def _get_default_content_for_type(self, anomaly_type: str) -> Dict[str, str]:
        """根据异常类型返回默认文案"""
        defaults = {
            'promotional_dialog': {
                'title': '专属福利',
                'message': '限时优惠活动，立即领取专属优惠券',
                'button_text': '立即领取',
                'subtitle': '仅限今日',
                'brand_name': ''
            },
            'reward_badge_dialog': {
                'title': '恭喜获得奖励',
                'message': '您已获得专属奖励，快来查看',
                'button_text': '立即查看',
                'subtitle': '',
                'brand_name': ''
            },
            'permission_dialog': {
                'title': '开启通知权限',
                'message': '开启后可及时接收重要消息提醒',
                'button_text': '立即开启',
                'subtitle': '',
                'brand_name': ''
            },
            'tutorial_guide': {
                'title': '功能介绍',
                'message': '了解更多实用功能，提升使用体验',
                'button_text': '下一步',
                'subtitle': '',
                'brand_name': ''
            },
            'coupon_popup': {
                'title': '优惠券已到账',
                'message': '您有一张优惠券待使用',
                'button_text': '立即使用',
                'subtitle': '限时有效',
                'brand_name': ''
            },
            'context_menu_dropdown': {
                'title': '选择',
                'message': '',
                'button_text': '',
                'subtitle': '',
                'brand_name': '',
                'menu_items': ['选项一', '选项二'],
                'selected_item': '选项一'
            },
            'tooltip_bubble': {
                'title': '',
                'message': '点击这里了解更多',
                'button_text': '',
                'subtitle': '',
                'brand_name': ''
            },
            'floating_tip_banner': {
                'title': '',
                'message': '温馨提示',
                'button_text': '我知道了',
                'subtitle': '',
                'brand_name': ''
            }
        }
        return defaults.get(anomaly_type, {
            'title': '提示',
            'message': '请确认操作',
            'button_text': '确定',
            'subtitle': '',
            'brand_name': ''
        })

    def _extract_menu_items_from_instruction(self, instruction: str) -> List[str]:
        """
        从 instruction 中提取下拉菜单项

        示例：
        - "内容列表包含最新、最热两个选项" → ["最新", "最热"]
        - "选项包括选项A、选项B" → ["选项A", "选项B"]
        - "显示排序菜单：按时间、按热度" → ["按时间", "按热度"]

        Args:
            instruction: 用户指令

        Returns:
            提取到的菜单项列表，如果提取失败返回空列表
        """
        import re

        # 常见的菜单项分隔模式
        patterns = [
            # "包含X、Y两个选项" 或 "包含X、Y选项"
            r'包含\s*([^，,]+[、,，][^，,两个选项]+?)(?:两个|三个|多个)?选项',
            # "选项包括X、Y" 或 "选项有X、Y"
            r'选项(?:包括|有|为|是)\s*[:：]?\s*([^，。]+)',
            # "内容列表包含X、Y"
            r'内容(?:列表)?(?:包含|有|为|是)\s*[:：]?\s*([^，。]+?)(?:两个|三个|选项|$)',
            # "X、Y两个选项" (直接提取)
            r'([^，。包含有为是]+[、,，][^，。]+?)(?:两个|三个)?选项',
            # "菜单：X、Y" 或 "菜单项：X、Y"
            r'菜单(?:项)?[:：]\s*([^，。]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, instruction)
            if match:
                items_str = match.group(1).strip()
                # 分割菜单项（支持中文顿号、逗号）
                items = re.split(r'[、,，]', items_str)
                items = [item.strip() for item in items if item.strip()]
                if len(items) >= 2:  # 至少需要2个选项才算有效
                    return items

        # 尝试更宽松的提取：查找引号内的内容
        quoted_items = re.findall(r'[""「」『』]([^""「」『』]+)[""「」『』]', instruction)
        if len(quoted_items) >= 2:
            return quoted_items

        return []

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
        bg_color = (0, 0, 0)

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

    def _crop_to_content_and_resize(
        self,
        image: Image.Image,
        target_width: int,
        target_height: int
    ) -> Image.Image:
        """
        裁切透明边距并 resize 到目标尺寸

        AI 生成的弹窗在背景移除后，实际内容可能不铺满画布。
        此方法：
        1. 找到最大连通内容区域的边界框（忽略孤立小区域，如 AI 自行画的关闭按钮）
        2. 裁切到该边界框
        3. resize 到目标尺寸

        Args:
            image: RGBA 图像（已去除背景）
            target_width: 目标宽度
            target_height: 目标高度

        Returns:
            调整后的图像
        """
        if image.mode != 'RGBA':
            image = image.convert('RGBA')

        # 通过 alpha 通道找到内容边界框
        full_bbox = image.getbbox()
        if not full_bbox:
            return image  # 完全透明，无操作

        canvas_width, canvas_height = image.size

        # 尝试找到最大连通内容块，忽略孤立的小区域（如 AI 画的关闭按钮）
        bbox = self._find_main_content_bbox(image, full_bbox)

        content_width = bbox[2] - bbox[0]
        content_height = bbox[3] - bbox[1]

        fill_ratio = (content_width * content_height) / (canvas_width * canvas_height)

        if fill_ratio > 0.85:
            # 内容已经铺满大部分画布，只需 resize
            if (canvas_width, canvas_height) != (target_width, target_height):
                image = image.resize((target_width, target_height), Image.Resampling.LANCZOS)
            return image

        # 裁切到内容边界框
        cropped = image.crop(bbox)
        print(f"  ℹ 内容区域: {content_width}x{content_height} (填充率: {fill_ratio:.1%})")

        # resize 到目标尺寸
        resized = cropped.resize((target_width, target_height), Image.Resampling.LANCZOS)
        print(f"  ℹ 已 resize 到目标尺寸: {target_width}x{target_height}")

        return resized

    @staticmethod
    def _find_main_content_bbox(image: Image.Image, full_bbox: tuple) -> tuple:
        """
        在已去背景的 RGBA 图像中，找到最大连通内容区域的 bbox。

        通过行扫描检测垂直间隙，将内容分割为多个区块，
        保留面积最大的区块。这样可以过滤掉 AI 额外画的孤立关闭按钮等小区域。

        Args:
            image: RGBA 图像
            full_bbox: image.getbbox() 的结果

        Returns:
            最大内容区域的 bbox (left, upper, right, lower)
        """
        width = image.size[0]
        alpha = image.split()[3]

        left, top, right, bottom = full_bbox
        content_width = right - left

        # 如果内容区域很小，直接返回
        if content_width < 10 or (bottom - top) < 10:
            return full_bbox

        # 按行扫描，统计每行的非透明像素数
        # 间隙阈值：非透明像素占内容宽度不到 3% 的行视为"空行"
        gap_threshold = content_width * 0.03
        row_has_content = []

        for y in range(top, bottom):
            count = 0
            for x in range(left, right):
                if alpha.getpixel((x, y)) > 10:
                    count += 1
            row_has_content.append(count > gap_threshold)

        # 找到连续有内容的行区间（区块）
        blocks = []  # [(start_y, end_y), ...]
        in_block = False
        block_start = 0
        gap_count = 0
        max_gap_tolerance = 5  # 允许区块内最多 5 行间隙（抗噪声）

        for i, has_content in enumerate(row_has_content):
            y = top + i
            if has_content:
                if not in_block:
                    block_start = y
                    in_block = True
                gap_count = 0
                block_end = y + 1
            else:
                if in_block:
                    gap_count += 1
                    if gap_count > max_gap_tolerance:
                        # 间隙过大，结束当前区块
                        blocks.append((block_start, block_end))
                        in_block = False
                        gap_count = 0

        if in_block:
            blocks.append((block_start, block_end))

        if len(blocks) <= 1:
            # 只有一个区块或没有区块，返回原始 bbox
            return full_bbox

        # 多个区块：找面积最大的
        best_block = None
        best_area = 0
        for (by_start, by_end) in blocks:
            # 计算该区块在水平方向的实际内容范围
            block_left, block_right = width, 0
            for y in range(by_start, by_end):
                for x in range(left, right):
                    if alpha.getpixel((x, y)) > 10:
                        block_left = min(block_left, x)
                        block_right = max(block_right, x + 1)
                        break
                for x in range(right - 1, left - 1, -1):
                    if alpha.getpixel((x, y)) > 10:
                        block_right = max(block_right, x + 1)
                        break

            area = (block_right - block_left) * (by_end - by_start)
            if area > best_area:
                best_area = area
                best_block = (block_left, by_start, block_right, by_end)

        if best_block:
            # 只有当最大区块明显大于其他区块时才过滤
            full_area = (right - left) * (bottom - top)
            if best_area > full_area * 0.5:
                print(f"  ℹ 检测到 {len(blocks)} 个内容区块，保留最大区块 (占比 {best_area/full_area:.0%})")
                return best_block

        return full_bbox

    def _remove_extra_layers(
        self,
        image: Image.Image,
        expected_aspect_ratio: float
    ) -> Image.Image:
        """
        检测并移除 AI 生成图像中多余的弹窗层。

        AI 生成横幅类弹窗时，有时会在目标横幅之外额外生成一个更大的弹窗/卡片层。
        本方法通过行扫描检测内容区域中的垂直间隙（透明行带），
        如果存在间隙则将图像拆分为多个区域，只保留宽高比最接近预期的那个区域。

        Args:
            image: RGBA 图像（已去除背景）
            expected_aspect_ratio: 预期宽高比（width/height），横幅通常 > 2

        Returns:
            清理后的图像
        """
        if image.mode != 'RGBA':
            image = image.convert('RGBA')

        width, height = image.size

        # 找出内容边界框
        bbox = image.getbbox()
        if not bbox:
            return image

        # 扫描每一行的非透明像素数量
        alpha_data = image.split()[3]  # alpha channel
        row_pixel_counts = []
        for y in range(bbox[1], bbox[3]):
            count = 0
            for x in range(bbox[0], bbox[2]):
                if alpha_data.getpixel((x, y)) > 10:
                    count += 1
            row_pixel_counts.append((y, count))

        if not row_pixel_counts:
            return image

        # 计算内容宽度（用于判断"几乎空"的行）
        content_width = bbox[2] - bbox[0]
        # 阈值：低于内容宽度 5% 的行视为间隙行
        gap_threshold = content_width * 0.05

        # 找到连续的内容条带（被间隙行分隔的区域）
        strips = []  # [(y_start, y_end), ...]
        in_content = False
        strip_start = 0

        for y, count in row_pixel_counts:
            if count > gap_threshold:
                if not in_content:
                    strip_start = y
                    in_content = True
            else:
                if in_content:
                    strips.append((strip_start, y))
                    in_content = False

        if in_content:
            strips.append((strip_start, row_pixel_counts[-1][0] + 1))

        # 只有一个条带，无需清理
        if len(strips) <= 1:
            return image

        print(f"  ℹ 检测到 {len(strips)} 个内容条带，疑似多层弹窗")

        # 找出宽高比最接近预期的条带
        best_strip = None
        best_score = float('inf')

        for y_start, y_end in strips:
            strip_height = y_end - y_start
            if strip_height < 10:
                continue
            strip_ratio = content_width / strip_height
            score = abs(strip_ratio - expected_aspect_ratio)
            if score < best_score:
                best_score = score
                best_strip = (y_start, y_end)

        if not best_strip:
            return image

        y_start, y_end = best_strip
        print(f"  ✓ 保留最佳条带: y=[{y_start}, {y_end}], "
              f"高度={y_end - y_start}px, 宽高比={content_width / (y_end - y_start):.1f}")

        # 清除最佳条带之外的像素
        result = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        # 只复制最佳条带区域
        strip_region = image.crop((0, y_start, width, y_end))
        result.paste(strip_region, (0, y_start))

        return result

    @staticmethod
    def _erase_ai_close_button(image: Image.Image) -> Image.Image:
        """
        检测并擦除 AI 自行绘制的关闭按钮（X 图标）

        AI 文生图模型经常无视 "Do not draw any close button" 的否定指令，
        在弹窗的角落（通常是右上角）自行画一个 X 按钮。
        由于 X 按钮与弹窗卡片相连，_find_largest_connected_region 无法过滤。

        策略：扫描内容区域的 4 个角落，检测是否存在只占据角落的小型内容块。
        判断标准：角落区域内有内容，但这些内容行的宽度远小于弹窗主体宽度。

        Args:
            image: 已去背景的 RGBA 图像

        Returns:
            处理后的图像（角落 X 按钮已被擦除为透明）
        """
        if image.mode != 'RGBA':
            image = image.convert('RGBA')

        bbox = image.getbbox()
        if not bbox:
            return image

        left, top, right, bottom = bbox
        content_width = right - left
        content_height = bottom - top

        # 弹窗太小不处理
        if content_width < 50 or content_height < 50:
            return image

        alpha = image.split()[3]
        result = image.copy()
        result_pixels = result.load()

        # 角落扫描区域大小：内容尺寸的 12%
        corner_h = max(20, int(content_height * 0.12))
        corner_w = max(20, int(content_width * 0.12))

        # 主体宽度参考：在内容区域中间 1/3 高度范围内，找到典型的内容行宽度
        mid_start = top + content_height // 3
        mid_end = top + content_height * 2 // 3
        mid_widths = []
        for y in range(mid_start, mid_end, max(1, (mid_end - mid_start) // 10)):
            row_left, row_right = right, left
            for x in range(left, right):
                if alpha.getpixel((x, y)) > 10:
                    row_left = min(row_left, x)
                    row_right = max(row_right, x + 1)
                    break
            for x in range(right - 1, left - 1, -1):
                if alpha.getpixel((x, y)) > 10:
                    row_right = max(row_right, x + 1)
                    break
            if row_right > row_left:
                mid_widths.append(row_right - row_left)

        if not mid_widths:
            return image

        typical_width = sorted(mid_widths)[len(mid_widths) // 2]  # 中位数
        # 角落内容行的宽度阈值：如果一行内容宽度不到主体的 30%，认为是角落小元素
        width_threshold = typical_width * 0.30

        def scan_and_erase_corner(cy_start, cy_end, cx_start, cx_end, corner_name):
            """扫描指定角落区域，如果发现小型孤立内容则擦除"""
            corner_pixels = []
            for y in range(cy_start, cy_end):
                for x in range(cx_start, cx_end):
                    if alpha.getpixel((x, y)) > 10:
                        corner_pixels.append((x, y))

            if not corner_pixels:
                return 0  # 角落无内容

            # 关键检查：角落内容是否触及内边界（与主体相连）
            # 如果触及，说明是卡片圆角的一部分，绝对不能擦除
            # 内边界定义：对于 top-right 角落，内边界是左侧(cx_start)和底部(cy_end-1)
            # 检查边界方向上 3 像素的容差范围
            inner_margin = 3

            # 判断是哪个角落，确定内边界方向
            is_top = (cy_start <= top + corner_h)
            is_right = (cx_end >= right - 1)
            is_left = (cx_start <= left + 1)

            touches_inner_boundary = False
            for (px, py) in corner_pixels:
                # 水平内边界：top-right/bottom-right 的左侧，top-left/bottom-left 的右侧
                if is_right and px <= cx_start + inner_margin:
                    touches_inner_boundary = True
                    break
                if is_left and px >= cx_end - 1 - inner_margin:
                    touches_inner_boundary = True
                    break
                # 垂直内边界：top-* 的底部，bottom-* 的顶部
                if is_top and py >= cy_end - 1 - inner_margin:
                    touches_inner_boundary = True
                    break
                if not is_top and py <= cy_start + inner_margin:
                    touches_inner_boundary = True
                    break

            if touches_inner_boundary:
                return 0  # 内容触及内边界，是卡片主体的一部分

            # 检查角落内容的水平范围
            px_left = min(p[0] for p in corner_pixels)
            px_right = max(p[0] for p in corner_pixels) + 1
            corner_content_width = px_right - px_left

            # 检查角落内容是否远小于主体宽度
            if corner_content_width > width_threshold:
                return 0  # 角落内容宽度较大，可能是正常内容（标题栏等），不擦除

            # 检查像素密度：X 按钮是细线条，密度低；卡片填充区域密度高
            corner_area = (cx_end - cx_start) * (cy_end - cy_start)
            pixel_density = len(corner_pixels) / corner_area if corner_area > 0 else 0
            if pixel_density > 0.4:
                return 0  # 密度过高，更像是卡片的实心区域，不是 X 线条

            # 确认是小型角落元素，擦除
            erased = 0
            for (x, y) in corner_pixels:
                result_pixels[x, y] = (0, 0, 0, 0)
                erased += 1

            if erased > 0:
                print(f"  ℹ 擦除 {corner_name} 角落疑似 AI 关闭按钮: {erased} 像素 "
                      f"({corner_content_width}px 宽, 密度 {pixel_density:.1%})")
            return erased

        total_erased = 0

        # 扫描右上角（最常见的 X 按钮位置）
        total_erased += scan_and_erase_corner(
            top, top + corner_h,
            right - corner_w, right,
            "右上"
        )

        # 扫描左上角
        total_erased += scan_and_erase_corner(
            top, top + corner_h,
            left, left + corner_w,
            "左上"
        )

        # 扫描右下角（罕见但可能）
        total_erased += scan_and_erase_corner(
            bottom - corner_h, bottom,
            right - corner_w, right,
            "右下"
        )

        # 扫描左下角（罕见但可能）
        total_erased += scan_and_erase_corner(
            bottom - corner_h, bottom,
            left, left + corner_w,
            "左下"
        )

        if total_erased > 0:
            print(f"  ✓ AI 关闭按钮擦除完成: 共 {total_erased} 像素")

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

    @staticmethod
    def _parse_background_to_english(raw: str) -> str:
        """
        将 meta.json 的 background 字段（中文+颜色代码混合文本）转为纯英文描述。

        避免中文描述和裸颜色代码被文生图模型当作要渲染的文字。

        示例：
            "外层白色圆角卡片，内容区红色珊瑚渐变 #FF1744 → #FF6B35" → "white card outer, red-coral gradient (#FF1744 to #FF6B35) inner"
            "米白色渐变 #FAF6F0" → "cream gradient (#FAF6F0)"
            "#FFFFFF" → "#FFFFFF"
        """
        if not raw or raw.strip().startswith('#') and len(raw.strip()) <= 30 and '，' not in raw:
            # 纯色值或简短英文，直接返回
            return raw

        # 提取所有 hex 颜色值
        colors = re.findall(r'#[0-9A-Fa-f]{6}', raw)

        # 中文颜色词 → 英文映射
        color_map = {
            '白色': 'white', '米白': 'cream', '黑色': 'black',
            '红色': 'red', '珊瑚': 'coral', '橙色': 'orange',
            '粉色': 'pink', '粉红': 'pink', '蓝色': 'blue',
            '绿色': 'green', '金色': 'gold', '金棕': 'golden-brown',
            '灰色': 'gray', '紫色': 'purple', '黄色': 'yellow',
        }

        # 检测是否有渐变
        has_gradient = '渐变' in raw

        # 构建英文描述
        parts = []

        # 检测外层/内层结构
        if '外层' in raw or '外框' in raw:
            outer_color = 'white'
            for cn, en in color_map.items():
                if cn in raw.split('，')[0] if '，' in raw else raw[:10]:
                    outer_color = en
                    break
            parts.append(f'{outer_color} outer frame')

        # 处理颜色
        if has_gradient and len(colors) >= 2:
            parts.append(f'gradient ({colors[0]} to {colors[1]})')
        elif has_gradient and len(colors) == 1:
            parts.append(f'gradient ({colors[0]})')
        elif colors:
            parts.append(' '.join(colors))

        # 添加颜色描述词
        for cn, en in color_map.items():
            if cn in raw and en not in ' '.join(parts):
                # 避免重复添加已在 outer frame 中出现的
                if not any(en in p for p in parts):
                    parts.append(en)
                break

        if parts:
            return ', '.join(parts)

        # 回退：如果解析失败，返回提取到的颜色值
        if colors:
            return ' to '.join(colors) if has_gradient else ' '.join(colors)

        return 'white'

    def _build_ai_prompt_from_meta(
        self,
        meta_semantic: str,
        meta_features: Dict[str, Any],
        reference_path: str = None,
        target_content: Dict[str, str] = None
    ) -> str:
        """
        基于meta.json的语义描述构建AI生成prompt（核心增强）

        改进版：支持分离视觉风格和文字内容
        - meta_semantic: 视觉风格描述（来自 extract_visual_style_prompt）
        - meta_features: 视觉特征字典（颜色、位置、样式等）
        - reference_path: 参考图片路径（提供视觉风格参考）
        - target_content: VLM根据目标截图生成的语义内容（标题、消息、按钮文字）

        生成的prompt结合：
        1. 纯视觉风格（来自meta.json的视觉特征）
        2. 语义相关的文字内容（来自VLM分析目标截图）
        3. 参考图片作为风格锚定

        Args:
            meta_semantic: MetaLoader.extract_visual_style_prompt()的输出（或旧版extract_semantic_prompt）
            meta_features: MetaLoader.extract_visual_features_dict()的输出
            reference_path: 参考图片路径
            target_content: VLM生成的语义内容，格式 {'title', 'message', 'button_text', 'subtitle'}

        Returns:
            优化的AI生成prompt
        """
        # 提取关键视觉参数
        app_style = meta_features.get('app_style', '通用')
        design_language = meta_features.get('design_language', '')
        primary_color = meta_features.get('primary_color', '#1890FF')
        background = self._parse_background_to_english(meta_features.get('background', '#FFFFFF'))
        dialog_position = meta_features.get('dialog_position', 'center')
        corner_style = meta_features.get('corner_radius', 'large')

        # 提取按钮和关闭按钮信息
        close_button_pos = meta_features.get('close_button_position', 'none')
        close_button_style = meta_features.get('close_button_style', 'default')

        # 提取遮罩层信息
        overlay_enabled = meta_features.get('overlay_enabled', True)
        overlay_opacity = meta_features.get('overlay_opacity', 0.7)

        # 特殊视觉元素（过滤文字相关内容和品牌相关元素）
        special_elements = meta_features.get('special_elements', [])
        # 过滤掉文字内容和参考图品牌相关的元素
        visual_elements = []
        # 关键词列表：文字内容 + 参考图品牌（防止品牌污染）
        filter_keywords = [
            # 文字内容关键词
            '文字', '显示', '标题', '内容', '数字', '天', '元', '折',
            # 华为/鸿蒙品牌关键词（参考图可能来自华为APP）
            'HarmonyOS', 'Harmony', '鸿蒙', '花粉', '华为', 'HUAWEI',
            # 其他常见品牌（防止参考图品牌泄露）
            '淘宝', '京东', '美团', '抖音', '微信', '支付宝'
        ]
        for elem in special_elements:
            # 检查是否包含任何过滤关键词（不区分大小写）
            has_filter_keyword = any(kw.lower() in elem.lower() for kw in filter_keywords)
            if not has_filter_keyword:
                visual_elements.append(elem)
        special_elements_desc = ', '.join(visual_elements) if visual_elements else '无'

        # 检查是否是下拉菜单类型
        anomaly_type = meta_features.get('anomaly_type', '')
        is_dropdown_menu = anomaly_type == 'context_menu_dropdown'

        # 获取下拉菜单专用字段（样式从 meta_features 获取）
        list_style = meta_features.get('list_style', 'radio_list')
        selected_indicator = meta_features.get('selected_indicator', 'checkmark')

        # 获取 menu_items：优先使用 instruction 提取的，否则使用 meta.json 的
        if target_content and target_content.get('menu_items'):
            # instruction 中提取到了菜单项
            menu_items = target_content.get('menu_items')
            selected_item = menu_items[0] if menu_items else ''
            content_source = f"instruction-derived menu: {menu_items}"
        else:
            # 使用 meta.json 中的默认菜单项
            menu_items = meta_features.get('menu_items', [])
            selected_item = meta_features.get('selected_item', menu_items[0] if menu_items else '')
            content_source = f"meta.json menu: {menu_items}"

        # 确定文字内容来源
        if is_dropdown_menu and menu_items:
            # 下拉菜单：使用上面确定的 menu_items
            title_text = target_content.get('title', '') if target_content else ''
            message_text = ''
            button_text = ''
            subtitle_text = ''
            brand_name = target_content.get('brand_name', '') if target_content else ''
        elif target_content:
            # 使用 VLM 生成的语义相关内容
            title_text = target_content.get('title', '提示')
            message_text = target_content.get('message', '')
            button_text = target_content.get('button_text', '确定')
            subtitle_text = target_content.get('subtitle', '')
            brand_name = target_content.get('brand_name', '')
            content_source = "VLM generated (semantic-aware)"
        else:
            # 回退到 meta_features 中的文字（向后兼容）
            title_text = meta_features.get('title_text', meta_features.get('main_button_text', '确定'))
            message_text = meta_features.get('anomaly_description', '')
            button_text = meta_features.get('main_button_text', '确定')
            subtitle_text = meta_features.get('subtitle_text', '')
            brand_name = ''
            content_source = "meta.json (fallback)"

        # 构建关闭按钮描述（保留原始灰色样式）
        if close_button_pos != 'none':
            close_button_desc = f"""### Close Button (CRITICAL - must be visible)
- Position: {close_button_pos}
- Style: {close_button_style}
- IMPORTANT: The close button should use a LIGHT GRAY circular background (like the reference image)
- The close button must be INSIDE the dialog area or directly attached to it
- DO NOT place the close button floating in the black background area
- Make sure the close button is clearly visible and properly rendered"""
        else:
            close_button_desc = "### Close Button\n- No close button"

        # 构建 Logo/Badge 文字描述
        if brand_name:
            logo_text_desc = f"""### Logo/Badge Text (CRITICAL)
- If there is a logo, badge or medal in the design, the text inside it should be: "{brand_name}"
- DO NOT use the reference image's brand text (like "HarmonyOS")
- The logo should display the TARGET APP's brand: "{brand_name}" """
        else:
            logo_text_desc = """### Logo/Badge Text
- If there is a logo or badge, leave it without specific brand text or use generic text"""

        # 构建精确的prompt
        # 注意：app_style 来自参考图的meta.json，可能包含参考图的品牌（如"华为花粉俱乐部"）
        # 只有当 VLM 从目标截图识别出 brand_name 时才使用品牌信息
        # 绝不回退到 app_style，避免参考图品牌泄漏到生成结果
        display_brand = brand_name if brand_name else ''

        # 版式形状描述映射
        layout_shape_map = {
            'bottom-fixed': 'a horizontal banner/strip fixed to the bottom edge, wide and short like a coupon bar',
            'bottom-floating': 'a wide, short rounded banner floating near the bottom',
            'bottom-center-floating': 'a small tooltip/bubble near the bottom center',
            'center': 'a centered card dialog',
            'bottom-left-inline': 'a small compact dropdown menu card',
            'multi-layer': 'multiple overlapping layers',
        }
        layout_desc = layout_shape_map.get(dialog_position, 'a centered card dialog')

        # 关闭按钮：不写入 prompt，由 run_pipeline.py 在最终合成阶段用 PIL 精确绘制
        # 避免 AI 画一个 + pipeline 再画一个导致重复
        close_desc = 'Do not draw any close button or X icon.'

        # 根据弹窗类型构建不同的简洁 prompt
        # 文生图模型需要简短的自然语言描述，不能用长结构化文档
        if is_dropdown_menu and menu_items:
            menu_items_str = ', '.join([f'"{item}"' for item in menu_items])
            prompt = f"""A mobile app dropdown menu on pure black background. The menu is a small white card with these items: {menu_items_str}. The item "{selected_item}" has a checkmark. Style: {list_style}, clean minimal design. {close_desc} The area outside the menu must be pure black #000000. Match the visual style of the reference image."""
        elif dialog_position in ('bottom-floating', 'bottom-fixed', 'bottom-center-floating'):
            # 底部横幅/浮层类型 — 强调只生成单一横幅，不要额外弹窗元素
            subtitle_part = f' Subtitle: "{subtitle_text}".' if subtitle_text else ''
            brand_part = f' The banner belongs to "{display_brand}" app.' if display_brand else ''
            elements_part = f' Include visual elements: {special_elements_desc}.' if special_elements_desc != '无' else ''

            prompt = f"""A single mobile app notification banner on pure black background. This is {layout_desc}. IMPORTANT: Generate ONLY ONE banner element, do not add any other popup, dialog, card or UI element. The banner has {corner_style} rounded corners with {background} background and {primary_color} as primary color. Title: "{title_text}". Message: "{message_text}".{f' Button text: "{button_text}".' if button_text else ''}{subtitle_part}{brand_part}{elements_part} {close_desc} The banner must fill at least 90% of the canvas width and be vertically centered on the canvas. The rest of the canvas must be pure black #000000 with absolutely no other elements, shadows, or gradients. Do not draw any overlay, dark mask, or additional popup layers. All text is in Chinese, crisp and readable. Match the visual style of the reference image."""
        else:
            # 标准弹窗 — 简洁的自然语言描述
            subtitle_part = f' Subtitle: "{subtitle_text}".' if subtitle_text else ''
            brand_part = f' The dialog belongs to "{display_brand}" app.' if display_brand else ''
            elements_part = f' Include visual elements: {special_elements_desc}.' if special_elements_desc != '无' else ''

            prompt = f"""A mobile app popup dialog card on pure black background. This is {layout_desc}. IMPORTANT: Generate ONLY ONE dialog element, do not add any other popup or UI element. The dialog card has {corner_style} rounded corners with {background} background and {primary_color} as primary color. Title: "{title_text}". Message: "{message_text}". Button text: "{button_text}".{subtitle_part}{brand_part}{elements_part} {close_desc} The dialog must fill at least 90% of the canvas width. The area outside the dialog must be pure black #000000 with no shadows or gradients. Do not draw any overlay or dark mask. All text is in Chinese, crisp and readable. Match the visual style of the reference image."""

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

    # ==================== GT 风格提取（原 style_transfer.py 能力） ====================

    def extract_gt_style(self, sample_path: str, style_type: str = "dialog") -> dict:
        """
        从 GT 样本提取视觉风格特征（替代已删除的 StyleTransferPipeline）

        Args:
            sample_path: GT 样本图片路径
            style_type: 风格类型，"dialog" 或 "loading"

        Returns:
            风格特征字典
        """
        cache_key = f"{style_type}_{sample_path}"
        if not hasattr(self, '_style_cache'):
            self._style_cache = {}
        if cache_key in self._style_cache:
            return self._style_cache[cache_key]

        try:
            with open(sample_path, 'rb') as f:
                image_base64 = base64.b64encode(f.read()).decode('utf-8')

            if style_type == "dialog":
                prompt = """分析这个弹窗/提示界面的视觉设计特征，用于风格迁移到新场景。

## 分析维度

### 1. 布局特征
- position: 弹窗位置 (center/top/bottom/full)
- width_ratio: 弹窗宽度占屏幕比例 (0.0-1.0)
- height_ratio: 弹窗高度占屏幕比例 (0.0-1.0)
- padding: 内边距估计值(px)

### 2. 配色方案
- background: 弹窗背景色
- primary: 主色调（按钮、标题）
- secondary: 辅助色
- text: 主文字颜色
- button: 主按钮颜色

### 3. 设计风格
- corner_radius: none/small/medium/large/circular
- shadow: none/subtle/prominent
- border: none/thin/thick
- style: card（卡片）/fullscreen（全屏）/modal（模态）/toast（轻提示）

### 4. 元素特征
- has_close_button: 是否有关闭按钮
- close_position: 关闭按钮位置 (top-right/top-right-outside/top-left/bottom)
- has_image: 是否有图片
- has_buttons: 是否有操作按钮
- button_count: 按钮数量

返回纯JSON格式结果。"""
                default = {
                    "layout": {"position": "center", "width_ratio": 0.8, "height_ratio": 0.5, "padding": 20},
                    "colors": {"background": "#FFFFFF", "primary": "#1890FF", "secondary": "#999999",
                               "text": "#333333", "button": "#1890FF"},
                    "design": {"corner_radius": "medium", "shadow": "subtle", "border": "none", "style": "card"},
                    "elements": {"has_close_button": True, "close_position": "top-right",
                                 "has_image": False, "has_buttons": True, "button_count": 1}
                }
            else:  # loading
                prompt = """分析这个加载/白屏/错误页面的视觉特征，用于风格迁移。

分析维度：加载类型(white_screen/loading_spinner/skeleton/error_page/partial_loading)、
配色(background/spinner/text)、元素列表、提示文案。

返回纯JSON格式结果。"""
                default = {
                    "type": "white_screen",
                    "colors": {"background": "#FFFFFF", "spinner": "#1890FF", "text": "#999999"},
                    "elements": [],
                    "message": ""
                }

            headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {self.api_key}'}
            payload = {
                'model': self.vlm_model,
                'messages': [{'role': 'user', 'content': [
                    {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{image_base64}'}},
                    {'type': 'text', 'text': prompt}
                ]}],
                'temperature': 0.3,
                'max_tokens': 600
            }
            response = requests.post(self.vlm_api_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            content_str = response.json()['choices'][0]['message']['content']
            import re as _re
            json_match = _re.search(r'\{[\s\S]*\}', content_str)
            result = json.loads(json_match.group(0)) if json_match else default
            self._style_cache[cache_key] = result
            return result

        except Exception as e:
            print(f"  ⚠ GT 风格提取失败 ({style_type}): {e}")
            return default
