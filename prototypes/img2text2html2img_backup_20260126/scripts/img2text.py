"""
Image to Text - UI截图描述工具
将UI截图转换为描述性文本，供LLM生成HTML
"""

import base64
import requests
import os
import argparse
import json
from typing import Dict, Optional, Tuple
from pathlib import Path
from datetime import datetime
try:
    from PIL import Image
except ImportError:
    Image = None


class ImageMetadata:
    """提取图片元信息"""

    def __init__(self, image_path: str):
        self.path = image_path
        self.width: int = 0
        self.height: int = 0
        self.dpi: Tuple[int, int] = (72, 72)
        self.format: str = ""
        self._extract()

    def _extract(self):
        if Image is None:
            return
        try:
            with Image.open(self.path) as img:
                self.width, self.height = img.size
                self.format = img.format or Path(self.path).suffix.upper().replace(".", "")
                if "dpi" in img.info:
                    self.dpi = img.info["dpi"]
        except Exception as e:
            print(f"[WARN] {e}")

    def to_dict(self) -> Dict:
        return {"width": self.width, "height": self.height, "format": self.format}


def get_prompt(metadata: ImageMetadata) -> str:
    """生成描述性文本的提示词 - 增强视觉细节版"""
    w, h = metadata.width, metadata.height

    return f"""精确分析这张App截图（{w}×{h}px），生成可用于HTML复刻的详细描述。

## 1. 组件识别与描述

按从上到下顺序，识别每个UI组件并详细描述：

### 格式规范
```
[组件名] 布局:___ 高度:___px 背景:___
  ├─ 子元素1: 类型 | 尺寸 | 样式 | 内容
  ├─ 子元素2: ...
  └─ 子元素3: ...
```

### 组件类型识别

**A. 功能按钮网格**（如：酒店、机票、外卖等入口）
```
[功能区] 布局:grid_列数x行数 高度:___px 间距:___px
  ├─ 按钮1: btn | 宽x高px | bg:#___ radius:___px | 内含icon:___ | 「文字」
  ├─ 按钮2: btn | 宽x高px | bg:#___ radius:___px | 内含img:风景照 | 「文字」
  ...
```
注意：按钮可能是纯色背景+图标，也可能是图片背景，需区分！

**B. 搜索框**
```
[搜索框] 布局:horizontal 高度:___px 背景:#___ radius:___px
  ├─ (L) icon:___ 颜色:#___
  ├─ (C) placeholder:「搜索文字」
  └─ (R) icon:___ | 「标签文字」
```

**C. 横向标签/分类**
```
[分类栏] 布局:horizontal_scroll 高度:___px
  ├─ 「标签1」active | 「标签2」| 「标签3」| ...
```

**D. 卡片区域**
```
[卡片区] 布局:horizontal_2col 或 vertical 高度:___px
  ├─ 卡片1: 宽x高px | 左图(宽x高)+右文 或 上图下文
  │    ├─ img: 类型(照片/插画/纯色) 尺寸 圆角
  │    ├─ 标题:「___」字号 颜色
  │    ├─ 副标题:「___」
  │    └─ 按钮:「___」bg:#___
  ├─ 卡片2: ...
```

**E. 列表项**（聊天、订单等）
```
[列表] 布局:vertical 单项高度:___px
  ├─ 项1: [img:头像_50px圆角8] + [名称+副文字] + [时间+标记]
  ...
```

## 2. 精确测量（关键！）

**测量方法**：观察每个组件在屏幕中占据的**视觉比例**，然后计算像素值。
- 如果组件占屏幕高度的10%，则高度 = {h} × 0.10 = {int(h*0.10)}px
- 禁止使用"其他空白"这种模糊描述！每个可见区域都必须精确测量。

```yaml
画布: {w} x {h} px

固定区域（通常占比很小）:
  状态栏: 高度约{int(h*0.018)}px（约1.8%）
  导航栏: 高度约{int(h*0.025)}px（约2.5%）
  底部栏: 高度约{int(h*0.030)}px（约3%，无则填0）

内容区（必须填满剩余空间！）:
  可用高度: 约{int(h*0.93)}px

各组件高度（按视觉比例估算）:
  - [功能区]: 占屏幕约__%, 高度约___px
  - [搜索框]: 占屏幕约__%, 高度约___px
  - [分类栏]: 占屏幕约__%, 高度约___px
  - [卡片区]: 占屏幕约__%, 高度约___px（这通常是最大的区域！）
  - [推荐区]: 占屏幕约__%, 高度约___px
  ...

总计校验: 所有组件高度之和 ≈ {h}px
```

**重要提示**：
- 卡片区通常占据屏幕30-50%的高度
- 不要遗漏任何可见内容区域
- 禁止用"空白"填充，必须识别所有UI组件

## 3. 样式记录

```yaml
颜色:
  页面背景: #___
  主色调: #___
  主文字: #___
  辅助文字: #___
  分割线: #___

圆角:
  按钮: __px
  卡片: __px
  头像: __px
  搜索框: __px

间距:
  组件间距: __px
  内边距: __px
```

## 4. 布局特征

用1-2句话总结：页面类型、主要布局模式、视觉风格。

---
**输出检查清单**：
✓ 功能按钮的背景类型已区分（纯色/图片）
✓ 搜索框形状和内部结构已描述
✓ 卡片布局方向已标注（左右分栏/上下结构）
✓ 所有图片/图标的尺寸和圆角已记录
✓ 高度测量值相加≈{h}px"""


class ImageAnalyzer:
    def __init__(self, api_key: str, api_url: str, model: str = "qwen3-vl-30b"):
        self.api_key, self.api_url, self.model = api_key, api_url, model
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def encode_image(self, path: str) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')

    def analyze(self, image_path: str) -> Dict:
        metadata = ImageMetadata(image_path)
        if not metadata.width:
            raise ValueError("Cannot read image")

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{self.encode_image(image_path)}"}},
                {"type": "text", "text": get_prompt(metadata)}
            ]}],
            "max_tokens": 4096,
            "temperature": 0.3
        }

        # 重试机制
        import time
        max_retries = 5
        retry_delays = [5, 10, 20, 30, 60]

        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    self.api_url,
                    headers=self.headers,
                    verify=False,
                    timeout=600,
                    json=payload
                )
                resp.raise_for_status()
                break
            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response else 0
                if status_code in [524, 502, 503, 504, 500] and attempt < max_retries - 1:
                    delay = retry_delays[min(attempt, len(retry_delays)-1)]
                    print(f"  [RETRY {attempt+1}/{max_retries}] 服务器错误 {status_code}，{delay}秒后重试...")
                    time.sleep(delay)
                else:
                    raise
            except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt < max_retries - 1:
                    delay = retry_delays[min(attempt, len(retry_delays)-1)]
                    print(f"  [RETRY {attempt+1}/{max_retries}] 网络错误，{delay}秒后重试...")
                    time.sleep(delay)
                else:
                    raise

        return {
            "description": resp.json()["choices"][0]["message"]["content"],
            "metadata": metadata.to_dict(),
            "model": self.model,
            "timestamp": datetime.now().isoformat()
        }

    def save(self, result: Dict, name: str, output_dir: str) -> str:
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 保存描述文本
        txt_file = path / f"{name}_{ts}.txt"
        content = f"""# UI Description
# Resolution: {result['metadata']['width']} x {result['metadata']['height']}
# Model: {result['model']}
# Time: {result['timestamp']}

{result['description']}
"""
        txt_file.write_text(content, encoding="utf-8")
        print(f"[OK] {txt_file}")

        # 保存元信息JSON
        json_file = path / f"{name}_{ts}.json"
        json_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        return str(txt_file)


def main():
    parser = argparse.ArgumentParser(description="UI Screenshot to Description")
    parser.add_argument("--api-url", default="https://api.openai-next.com/v1/chat/completions")
    parser.add_argument("--api-key", default="sk-K9B2ccVeW4VdAcobD53b16E06b104aA1B5A82593FdFb2557")
    parser.add_argument("--model", default="qwen-vl-max")
    parser.add_argument("--image-path", help="Single image file")
    parser.add_argument("--images-dir", default="./images", help="Directory of images")
    parser.add_argument("--output-dir", default="./outputs")
    args = parser.parse_args()

    analyzer = ImageAnalyzer(args.api_key, args.api_url, args.model)
    print(f"=== img2text | Model: {args.model} ===\n")

    if args.image_path:
        images = [Path(args.image_path)]
    else:
        images = [f for f in sorted(Path(args.images_dir).iterdir())
                  if f.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}]

    if not images:
        print(f"[WARN] No images found")
        return

    for i, img in enumerate(images, 1):
        print(f"[{i}/{len(images)}] {img.name}")
        try:
            result = analyzer.analyze(str(img))
            analyzer.save(result, img.stem, args.output_dir)
        except Exception as e:
            print(f"[FAIL] {e}")
        print()


if __name__ == "__main__":
    main()
