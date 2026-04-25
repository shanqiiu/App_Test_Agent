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

from app.utils.reference_analyzer import ReferenceAnalyzer, ReferenceStyleApplier


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
    prompt_extend: bool = True,
    reference_image_path: str = None,
    force_model: str = None
) -> Optional[Image.Image]:
    """
    【已废弃】使用 DashScope 云端 API 生成图像
    此函数已被移除，请改用 generate_image_local() 调用本地服务
    
    Args:
        ... (参数同上)
    
    Returns:
        None - 此函数不再提供任何功能
    """
    print("  ⚠️ DashScope 云端 API 已禁用，请使用本地服务 (generate_image_local)")
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

    # 根据 force_model 和 reference_image_path 决定模型和消息格式
    has_ref = reference_image_path and Path(reference_image_path).exists()

    if force_model == 'gen':
        # 强制纯文生图模式，不传参考图给模型
        model = "qwen-image-max"
        messages = [{"role": "user", "content": [{"text": prompt}]}]
        if has_ref:
            print(f"  ℹ 强制文生图模式，忽略参考图 (model={model})")
        else:
            print(f"  ℹ 文生图模式 (model={model})")
    elif force_model == 'edit':
        # 强制图像编辑模式
        if has_ref:
            ref_path = str(Path(reference_image_path).resolve())
            messages = [{"role": "user", "content": [{"image": ref_path}, {"text": prompt}]}]
            model = "qwen-image-edit-max"
            print(f"  ℹ 强制图像编辑模式 (model={model})")
        else:
            # 无参考图时无法使用编辑模型，fallback 到文生图
            model = "qwen-image-max"
            messages = [{"role": "user", "content": [{"text": prompt}]}]
            print(f"  ⚠ 指定 edit 模式但无参考图，回退到文生图 (model={model})")
    else:
        # 自动选择：有参考图用编辑模型，无参考图用文生图
        if has_ref:
            ref_path = str(Path(reference_image_path).resolve())
            messages = [{"role": "user", "content": [{"image": ref_path}, {"text": prompt}]}]
            model = "qwen-image-edit-max"
            print(f"  ℹ 使用参考图直接输入模式 (model={model})")
        else:
            messages = [{"role": "user", "content": [{"text": prompt}]}]
            model = "qwen-image-max"

    # 默认负面提示词（排除非黑色背景、低质量图像、通用品牌相关、关闭按钮）
    # 注意：具体参考图品牌的 negative_prompt 应由调用方通过 negative_prompt 参数传入
    if negative_prompt is None:
        negative_prompt = "低分辨率，低画质，肢体畸形，手指畸形，画面过饱和，蜡像感，人脸无细节，过度光滑，画面具有 AI 感。构图混乱。文字模糊，扭曲。白色背景，灰色背景，渐变背景，彩色背景，white background, gray background, colored background, gradient background, brand logo, brand text, brand name, reference image text, watermark, close button, X button, X icon, 关闭按钮"

    # ====== 调试日志：打印调用信息 ======
    print(f"\n{'='*60}")
    print(f"📝 DashScope API 调用信息:")
    print(f"{'='*60}")
    print(f"  模型：{model}")
    print(f"  API Key（后 8 位）: {api_key[-8:] if api_key else 'None'}")
    print(f"  尺寸：{size}")
    print(f"  Prompt: {prompt[:200]}{'...' if len(prompt) > 200 else ''}")
    if negative_prompt:
        print(f"  Negative Prompt: {negative_prompt[:100]}{'...' if len(negative_prompt) > 100 else ''}")
    if has_ref:
        print(f"  参考图路径：{reference_image_path}")
        print(f"  引用格式：{messages[0]['content'][0].keys()}")
    else:
        print(f"  引用格式：{messages[0]['content'][0].keys()}")
    print(f"{'='*60}\n")
    # ====== 调试日志结束 ======

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
                model=model,
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


def _normalize_dimension(dim: int) -> int:
    """将维度规范化为 16 的倍数（向下取整）"""
    return (dim // 16) * 16


def generate_image_local(
    prompt: str,
    size: str = '1024*1024',
    negative_prompt: str = None,
    reference_image_path: str = None
) -> 'Optional[Image.Image]':
    """
    使用本地文生图服务生成图像 - 支持多种 API 格式

    Args:
        prompt: 图像描述提示词
        size: 图像尺寸，格式 'width*height'
        negative_prompt: 负面提示词（可选）
        reference_image_path: 参考图片路径（可选）

    Returns:
        生成的 PIL Image 对象，失败返回 None
    """
    api_url = os.getenv("LOCAL_IMAGE_API_URL")
    if not api_url:
        print("  未配置 LOCAL_IMAGE_API_URL")
        return None

    steps = os.getenv("LOCAL_IMAGE_API_STEPS", "9")
    timeout = int(os.getenv("LOCAL_IMAGE_API_TIMEOUT", "120"))
    seed = os.getenv("LOCAL_IMAGE_API_SEED", "")

    try:
        w, h = size.split('*')
        width, height = int(w), int(h)
    except ValueError:
        print(f"  无效的尺寸格式：{size}，使用默认 512*512")
        width, height = 512, 512
        size_attr = "512*512"
    else:
        size_attr = size

    # 规范化尺寸为 16 的倍数
    norm_width = _normalize_dimension(width)
    norm_height = _normalize_dimension(height)
    if width != norm_width or height != norm_height:
        print(f"  维度已规范化：{width}x{height} -> {norm_width}x{norm_height} (16 的倍数)")

    headers = {"Content-Type": "application/json"}
    proxies = {"http": None, "https": None}  # 禁用代理，直接访问本地服务

    # 格式 1: width/height 分开
    payload_v1 = {
        "prompt": prompt,
        "width": norm_width,
        "height": norm_height,
        "steps": int(steps),
        "negative_prompt": negative_prompt or ""
    }
    if seed:
        payload_v1["seed"] = int(seed)
    
    # ====== 调试日志：打印调用信息 ======
    print(f"\n{'='*60}")
    print(f"📝 本地服务 API 调用信息 (格式 1):")
    print(f"{'='*60}")
    print(f"  URL: {api_url}")
    print(f"  Prompt: {prompt[:200]}{'...' if len(prompt) > 200 else ''}")
    print(f"  尺寸：width={width}, height={height}")
    print(f"  Steps: {steps}")
    print(f"  Negative Prompt: {negative_prompt or ''}")
    print(f"  Payload: {json.dumps(payload_v1, ensure_ascii=False, indent=4)[:500]}")
    print(f"{'='*60}\n")
    # ====== 调试日志结束 ======
    
    # 尝试格式 1
    try:
        response = requests.post(api_url, json=payload_v1, headers=headers, timeout=timeout, proxies=proxies)
        if response.status_code == 200:
            print(f"  使用格式 1 (width/height) 成功")
            print(f"  响应内容：{json.dumps(response.json(), ensure_ascii=False, indent=2)[:300]}")
            result = response.json()
            img = _process_local_response(result)
            if img:
                return img
        else:
            print(f"  格式 1 失败，状态码：{response.status_code}")
            print(f"  响应内容：{response.text[:500]}")
    except Exception as e:
        print(f"  格式 1 失败：{e}")
        import traceback
        traceback.print_exc()
    
    # 格式 2: size 字符串（使用规范化后的尺寸）
    norm_size_attr = f"{norm_width}*{norm_height}"
    payload_v2 = {
        "prompt": prompt,
        "size": norm_size_attr,
        "steps": int(steps),
        "negative_prompt": negative_prompt or ""
    }
    if seed:
        payload_v2["seed"] = int(seed)

    # ====== 调试日志：格式 2 ======
    print(f"\n{'='*60}")
    print(f"📝 本地服务 API 调用信息 (格式 2):")
    print(f"{'='*60}")
    print(f"  URL: {api_url}")
    print(f"  Prompt: {prompt[:200]}{'...' if len(prompt) > 200 else ''}")
    print(f"  尺寸：{norm_size_attr}")
    print(f"  Steps: {steps}")
    print(f"  Negative Prompt: {negative_prompt or ''}")
    print(f"  Payload: {json.dumps(payload_v2, ensure_ascii=False, indent=4)[:500]}")
    print(f"{'='*60}\n")
    # ====== 调试日志结束 ======
    
    # 尝试格式 2
    try:
        response = requests.post(api_url, json=payload_v2, headers=headers, timeout=timeout, proxies=proxies)
        if response.status_code == 200:
            print(f"  使用格式 2 (size) 成功")
            print(f"  响应内容：{json.dumps(response.json(), ensure_ascii=False, indent=2)[:300]}")
            result = response.json()
            img = _process_local_response(result)
            if img:
                return img
        else:
            print(f"  格式 2 失败，状态码：{response.status_code}")
            print(f"  响应内容：{response.text[:500]}")
    except Exception as e:
        print(f"  格式 2 失败：{e}")
        import traceback
        traceback.print_exc()
    
    print(f"  本地服务请求失败：所有格式都失败")
    return None


def _process_local_response(result: dict) -> 'Optional[Image.Image]':
    """处理本地服务的响应，支持多种返回格式"""
    try:
        # 格式 1: {"path": "http://..."} URL 形式
        if "path" in result and result["path"]:
            image_url = result["path"]
            print(f"  下载图像：{image_url}")
            img_response = requests.get(image_url, timeout=30)
            if img_response.status_code == 200:
                image = Image.open(io.BytesIO(img_response.content)).convert('RGBA')
                print(f"  本地服务图像生成成功 (URL 格式)")
                return image
        
        # 格式 2: {"image": "data:image/..."}
        elif "image" in result and result["image"]:
            image_data = result["image"]
            if image_data.startswith("data:image"):
                image_bytes = base64.b64decode(image_data.split(",", 1)[1])
            else:
                image_bytes = base64.b64decode(image_data)
            image = Image.open(io.BytesIO(image_bytes)).convert('RGBA')
            print(f"  本地服务图像生成成功")
            return image
        
        # 格式 3: {"images": [...]}
        elif "images" in result and result["images"]:
            image_data = result["images"][0]
            if isinstance(image_data, dict) and "url" in image_data:
                # URL 对象格式
                img_response = requests.get(image_data["url"], timeout=30)
                if img_response.status_code == 200:
                    image = Image.open(io.BytesIO(img_response.content)).convert('RGBA')
                    print(f"  本地服务图像生成成功 (images URL 格式)")
                    return image
            elif image_data.startswith("data:image"):
                image_bytes = base64.b64decode(image_data.split(",", 1)[1])
                image = Image.open(io.BytesIO(image_bytes)).convert('RGBA')
                print(f"  本地服务图像生成成功 (images base64 格式)")
                return image
        
        # 格式 4: 直接在顶层返回 URL
        else:
            for key in result:
                if isinstance(result[key], str) and result[key].startswith('http'):
                    print(f"  下载图像：{result[key]}")
                    img_response = requests.get(result[key], timeout=30)
                    if img_response.status_code == 200:
                        image = Image.open(io.BytesIO(img_response.content)).convert('RGBA')
                        print(f"  本地服务图像生成成功 (key={key} URL)")
                        return image
        
        print(f"  本地服务返回空图像：{result}")
        return None
        
    except Exception as e:
        print(f"  处理本地服务响应失败：{e}")
        import traceback
        traceback.print_exc()
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
        reference_path: Optional[str] = None,
        # image_model 已废弃 - 现在全部使用本地服务
        # image_model: Optional[str] = None
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
            图像生成现在使用本地服务 (generate_image_local)，不再需要 API Key
        """
        self.fonts_dir = fonts_dir
        self.api_key = api_key
        self.vlm_api_url = vlm_api_url
        self.vlm_model = vlm_model
        self.font_cache = {}
        # self.image_model = image_model  # 已废弃

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
            'temperature': 0.5,
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
 
