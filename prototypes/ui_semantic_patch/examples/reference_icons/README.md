# 参考加载图标示例库

本目录用于存放真实APP的加载图标样本，用于指导AI生成更真实的加载效果。

## 使用方法

### 1. 收集参考图标

从真实APP截取加载图标并保存到本目录，推荐按APP分类：

```
reference_icons/
├── taobao_loading.png       # 淘宝加载图标
├── wechat_loading.png       # 微信加载图标
├── douyin_loading.png       # 抖音加载图标
├── alipay_loading.png       # 支付宝加载图标
└── ...
```

### 2. 使用参考图标

```bash
python scripts/run_pipeline.py \
  --screenshot ./page.png \
  --instruction "模拟列表加载超时" \
  --anomaly-mode area_loading \
  --reference-icon ./examples/reference_icons/taobao_loading.png \
  --output ./output/
```

### 3. 参考图标特征

VLM会自动提取以下特征：
- **加载形状**：circular（圆形）/ linear（线性）/ dots（点阵）
- **图标类型**：spinner（旋转）/ progress（进度）/ pulse（脉冲）/ orbit（轨道）
- **配色方案**：monochrome（单色）/ colorful（多色）
- **动画风格**：smooth（平滑）/ discrete（离散）
- **设计复杂度**：simple（简单）/ complex（复杂）

## 建议的参考图标

| APP类型 | 推荐图标特点 |
|---------|-------------|
| 电商（淘宝/京东） | 橙色/红色圆形旋转，简洁设计 |
| 社交（微信/QQ） | 绿色/蓝色圆环，流畅动画 |
| 视频（抖音/B站） | 彩色渐变，动感设计 |
| 金融（支付宝/银行） | 蓝色进度条，稳重专业 |
| 新闻资讯 | 简单圆圈，快速切换 |

## 注意事项

1. **图标质量**：建议使用高清截图，至少 200×200 像素
2. **背景纯净**：最好是纯色背景或已抠图的透明背景
3. **典型性**：选择该APP最常见的加载样式
4. **版权**：仅用于学习研究，不做商业用途

## 效果对比

| 方式 | 生成效果 | 说明 |
|------|---------|------|
| 无参考图标 | ★★☆☆☆ | AI凭空生成，可能与APP风格不符 |
| 有参考图标 | ★★★★★ | 学习真实样式，生成效果高度逼真 |

**建议**：每个常用APP准备1-2个参考图标样本，可复用。
