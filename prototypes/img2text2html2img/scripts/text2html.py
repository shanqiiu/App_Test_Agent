"""
Text to HTML - 将UI描述文本转换为HTML/CSS
接收img2text.py生成的描述性文本，通过LLM生成可渲染的HTML
"""

import argparse
import os
import re
import json
import requests
from typing import Dict, Tuple
from pathlib import Path
from datetime import datetime


def extract_resolution(content: str) -> Tuple[int, int]:
    """从描述文本中提取分辨率"""
    patterns = [
        r'画布[:\s]*(\d+)\s*[x×]\s*(\d+)',  # 新格式：画布: 1279 x 2774 px
        r'分辨率[:\s]*(\d+)\s*[x×]\s*(\d+)',
        r'Resolution[:\s]*(\d+)\s*[x×]\s*(\d+)',
        r'(\d+)\s*[x×]\s*(\d+)\s*(?:px|像素)',
        r'width[:\s]*(\d+).*?height[:\s]*(\d+)',
    ]
    for p in patterns:
        m = re.search(p, content, re.IGNORECASE)
        if m:
            return int(m.group(1)), int(m.group(2))
    return 375, 667


def get_system_prompt() -> str:
    """系统提示词 - 增强布局版"""
    return """你是UI还原专家。根据结构化描述生成精确的HTML/CSS。

## 核心原则

### 1. 高度必须精确（最重要！）
```
html, body { height: 画布高度px; overflow: hidden; }
每个组件 { height: 描述中指定的高度px; }
```
- 所有组件高度之和必须等于画布高度
- 禁止使用 height:auto 或省略高度
- 使用 flex-shrink:0 防止组件被压缩

### 2. 文字原样使用
描述中的「文字」必须原样出现在HTML中，禁止编造。

### 3. 元素类型处理
- 「文字」→ 直接显示文本
- img:照片/风景 → 渐变色块: `background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);`
- img:头像 → 灰色圆角块: `background:#3A3A3A; border-radius:8px;`
- icon:描述 → Font Awesome图标

### 4. 布局模式
- `grid_5x2` → `display:grid; grid-template-columns:repeat(5,1fr);`
- `horizontal` → `display:flex; justify-content:space-between;`
- `horizontal_scroll` → `display:flex; overflow-x:auto; gap:12px;`
- `horizontal_2col` → `display:flex; gap:12px;` 两个flex:1子元素
- `vertical` → `display:flex; flex-direction:column;`

## HTML结构模板（必须遵循）

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
  <style>
    * { margin:0; padding:0; box-sizing:border-box; }
    html, body {
      width: [画布宽度]px;
      height: [画布高度]px;
      overflow: hidden;
      font-family: -apple-system, sans-serif;
    }
    .container {
      display: flex;
      flex-direction: column;
      height: 100%;
    }
    .status-bar { height: [高度]px; flex-shrink: 0; }
    .nav-bar { height: [高度]px; flex-shrink: 0; }
    .bottom-bar { height: [高度]px; flex-shrink: 0; }

    /* 内容区必须填满中间所有空间 */
    .content {
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    /* 内容区内的组件：使用flex比例分配高度 */
    .func-grid { flex: 2; }      /* 功能区占2份 */
    .search-section { flex: 1; } /* 搜索区占1份 */
    .tag-bar { flex: 1; }        /* 标签栏占1份 */
    .card-section { flex: 6; }   /* 卡片区占6份（最大） */
    .recommend { flex: 3; }      /* 推荐区占3份 */
  </style>
</head>
<body>
  <div class="container">
    <div class="status-bar">...</div>
    <div class="nav-bar">...</div>
    <div class="content">
      <!-- 所有内容组件，使用flex比例自动填满 -->
    </div>
    <div class="bottom-bar">...</div>
  </div>
</body>
</html>
```

**关键点**：
- 固定区域（状态栏、导航栏、底部栏）使用固定height + flex-shrink:0
- 内容区使用 flex:1 填满剩余空间
- 内容区内的子组件使用 flex:N 按比例分配高度（N越大占比越多）
- 卡片区通常是最大的，给它最大的flex值

## CSS组件参考

### 功能按钮网格
```css
.func-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 8px;
  padding: 8px 16px;
  height: [指定高度]px;
}
```

### 搜索框
```css
.search-bar {
  display: flex;
  align-items: center;
  height: [指定高度]px;
  background: #F5F5F5;
  border-radius: 20px;
  margin: 8px 16px;
  padding: 0 16px;
}
```

### 双列卡片
```css
.card-row {
  display: flex;
  gap: 12px;
  padding: 8px 16px;
  height: [指定高度]px;
}
.card { flex: 1; border-radius: 12px; overflow: hidden; }
```

## 输出要求
1. 直接以 <!DOCTYPE html> 开头
2. 不要markdown包裹，不要解释
3. 每个组件必须有明确的height值"""


def generate_prompt(content: str, resolution: Tuple[int, int]) -> str:
    """生成用户提示词"""
    w, h = resolution

    return f"""画布尺寸: {w}px × {h}px（必须严格遵守！）

{content}

## 关键实现要求

1. **尺寸锁定**：
   - `html, body {{ width:{w}px; height:{h}px; overflow:hidden; }}`
   - 禁止滚动，所有内容必须在画布内

2. **高度分配**：
   - 读取描述中每个组件的「高度:___px」
   - 为每个组件设置 `height: Xpx; flex-shrink: 0;`
   - 内容区使用 `flex:1` 填充剩余空间

3. **布局结构**：
   ```
   container (flex column, height:100%)
   ├── status-bar (height: 描述中的值)
   ├── nav-bar (height: 描述中的值)
   ├── content (flex:1, flex column)
   │   ├── 组件1 (height: 描述中的值)
   │   ├── 组件2 (height: 描述中的值)
   │   └── ...
   └── bottom-bar (height: 描述中的值)
   ```

4. **Font Awesome**: `https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css`

直接输出HTML，以<!DOCTYPE html>开头："""


class HTMLGenerator:
    def __init__(self, api_key: str, api_url: str, model: str = "qwen3-235b"):
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
        self.headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def generate(self, content: str) -> Dict:
        """调用LLM生成HTML"""
        resolution = extract_resolution(content)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": get_system_prompt()},
                {"role": "user", "content": generate_prompt(content, resolution)}
            ],
            "temperature": 0.2,
            "max_tokens": 8192
        }

        # 重试机制（增强版：处理超时和服务器错误）
        import time
        max_retries = 5
        retry_delays = [5, 10, 20, 30, 60]  # 递增延迟

        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    self.api_url,
                    headers=self.headers,
                    verify=False,
                    timeout=900,  # 增加超时到15分钟
                    json=payload
                )
                resp.raise_for_status()
                break
            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response is not None else 0
                # 524: Cloudflare超时, 502/503/504: 网关错误
                if status_code in [524, 502, 503, 504, 500] and attempt < max_retries - 1:
                    delay = retry_delays[min(attempt, len(retry_delays)-1)]
                    print(f"  [RETRY {attempt+1}/{max_retries}] 服务器错误 {status_code}，{delay}秒后重试...")
                    time.sleep(delay)
                else:
                    raise
            except requests.exceptions.RequestException as e:
                # 捕获所有其他请求异常（包括连接错误、超时等）
                if attempt < max_retries - 1:
                    delay = retry_delays[min(attempt, len(retry_delays)-1)]
                    error_msg = str(e)[:100]
                    print(f"  [RETRY {attempt+1}/{max_retries}] 请求异常: {error_msg}，{delay}秒后重试...")
                    time.sleep(delay)
                else:
                    raise
            except Exception as e:
                # 最后的兜底处理
                if attempt < max_retries - 1:
                    delay = retry_delays[min(attempt, len(retry_delays)-1)]
                    print(f"  [RETRY {attempt+1}/{max_retries}] 未知错误: {type(e).__name__}，{delay}秒后重试...")
                    time.sleep(delay)
                else:
                    raise

        html = resp.json()["choices"][0]["message"]["content"].strip()
        # 移除可能的markdown代码块包裹
        html = re.sub(r'^```html?\n?|```\n?$', '', html, flags=re.MULTILINE).strip()

        # 提取纯HTML（去除LLM思考过程）
        doctype_match = re.search(r'<!DOCTYPE\s+html[^>]*>', html, re.IGNORECASE)
        if doctype_match:
            html = html[doctype_match.start():]
        elif '<html' in html.lower():
            html_match = re.search(r'<html[^>]*>', html, re.IGNORECASE)
            if html_match:
                html = html[html_match.start():]

        return {
            "html": html,
            "model": self.model,
            "timestamp": datetime.now().isoformat(),
            "resolution": {"width": resolution[0], "height": resolution[1]}
        }

    def save(self, result: Dict, output_dir: str, name: str) -> str:
        """保存生成的HTML"""
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_file = path / f"{name}_{ts}.html"
        html_file.write_text(result["html"], encoding="utf-8")

        # 保存元信息JSON（供html2img使用）
        json_file = path / f"{name}_{ts}.json"
        meta = {
            "model": result["model"],
            "timestamp": result["timestamp"],
            "resolution": result["resolution"]
        }
        json_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"[OK] {html_file}")
        print(f"     Resolution: {result['resolution']['width']}x{result['resolution']['height']}px")
        return str(html_file)


def main():
    parser = argparse.ArgumentParser(description="UI Description to HTML")
    parser.add_argument("--api-url", default=os.environ.get("API_URL", "https://api.openai-next.com/v1/chat/completions"))
    parser.add_argument("--api-key", default=os.environ.get("API_KEY"), help="API密钥（或设置环境变量 API_KEY）")
    parser.add_argument("--model", default="qwen3-235b-a22b")
    parser.add_argument("--input-file", help="单个输入文件(.txt)")
    parser.add_argument("--input-dir", help="输入目录，处理所有.txt文件")
    parser.add_argument("--output-dir", default="./dist_html")
    args = parser.parse_args()

    if not args.api_key:
        print("[ERROR] 未设置 API 密钥。请设置环境变量 API_KEY 或使用 --api-key 参数")
        return

    generator = HTMLGenerator(args.api_key, args.api_url, args.model)
    print(f"=== text2html | Model: {args.model} ===\n")

    # 确定输入文件列表
    if args.input_file:
        if not os.path.exists(args.input_file):
            print(f"[ERROR] Not found: {args.input_file}")
            return
        files = [Path(args.input_file)]
    elif args.input_dir:
        files = sorted(Path(args.input_dir).glob("*.txt"))
    else:
        print("[ERROR] 请指定 --input-file 或 --input-dir")
        return

    if not files:
        print("[WARN] No .txt files found")
        return

    for i, f in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {f.name}")
        try:
            content = f.read_text(encoding='utf-8')
            result = generator.generate(content)
            generator.save(result, args.output_dir, f.stem)
        except Exception as e:
            print(f"[FAIL] {e}")
        print()


if __name__ == "__main__":
    main()
