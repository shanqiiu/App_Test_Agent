# 快速开始指南

## 1. 安装依赖

```bash
cd prototypes/model_api_use_spike
pip install -r requirements.txt
```

## 2. 配置API密钥

### 方法1: 使用.env文件（推荐）

```bash
# 复制示例文件
cp .env.example .env

# 编辑.env文件，填入你的API密钥
# FLUX_API_KEY=your_flux_api_key_here
# QWEN_API_KEY=your_qwen_api_key_here
```

### 方法2: 设置环境变量

```bash
# Linux/Mac
export FLUX_API_KEY="your_api_key"
export FLUX_API_URL="https://api.flux.ai/v1/generate"

# Windows CMD
set FLUX_API_KEY=your_api_key
set FLUX_API_URL=https://api.flux.ai/v1/generate

# Windows PowerShell
$env:FLUX_API_KEY="your_api_key"
$env:FLUX_API_URL="https://api.flux.ai/v1/generate"
```

## 3. 生成测试场景

```bash
# 生成所有3个测试场景（默认使用Flux）
python scripts/generate.py

# 使用Qwen API
python scripts/generate.py --provider qwen

# 单张自定义生成
python scripts/generate.py --prompt "手机支付APP显示余额不足错误"
```

## 4. 查看结果

```bash
# 查看生成的图像
ls outputs/images/flux/

# 查看元数据
cat outputs/metadata/test_001.json

# 查看成本报告
cat outputs/reports/cost_report_*.json
```

## 故障排查

### API密钥未设置

如果出现错误：`ConfigError: Environment variable 'FLUX_API_KEY' not set`

**解决方法**：
1. 检查.env文件是否存在且包含API密钥
2. 或者使用环境变量设置API密钥

### 网络连接失败

如果出现错误：`ConnectionError` 或 `TimeoutError`

**解决方法**：
1. 检查网络连接
2. 使用国内API提供商（如Qwen）
3. 检查API URL是否正确

### API认证失败

如果出现错误：`HTTP 401: Authentication failed`

**解决方法**：
1. 检查API密钥是否正确
2. 检查API密钥是否有效（未过期）
3. 检查API提供商的配额

## 下一步

1. 对比生成结果与[z_image_spike](../z_image_spike/README.md)
2. 查看[README.md](README.md)了解完整文档
3. 查看成本报告，分析API vs 本地方案的成本效益
