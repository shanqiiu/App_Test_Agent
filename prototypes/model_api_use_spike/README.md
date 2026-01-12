# Model API Use Spike - 云端文生图API验证

基于云端文生图API的异常UI生成验证原型

## 项目定位

这是一个**轻量级API集成验证原型**，用于快速验证云端文生图服务在异常UI生成中的可行性。

### 核心价值

- 与 [z_image_spike](../z_image_spike/README.md)(本地SDXL Turbo方案)形成互补，支持技术路线决策
- 无需GPU资源，快速切换不同模型提供商
- 通过成本追踪支持API vs 本地的成本效益分析
- 为异常测试场景生成提供灵活的云端备选方案

### 在项目中的位置

```
App_Test_Agent 三阶段架构:
正常行为采集 → [程序化异常生成] ← 本spike验证此环节 → 动态场景注入
                      ↓
          ┌───────────┴───────────┐
          │                       │
    z_image_spike          model_api_use_spike
    (本地Diffusion)            (云端API)  ← 本项目
```

### 与 z_image_spike 的对比

| 维度 | z_image_spike | model_api_use_spike |
|------|---------------|---------------------|
| 定位 | 完整的本地生成方案 | 轻量级API验证原型 |
| 模型 | 本地SDXL Turbo | 云端Flux/Qwen |
| GPU | 必需(12GB+) | 不需要 |
| 配置 | YAML(完整参数) | JSON(简洁配置) |
| 核心功能 | 完整pipeline | API验证+成本追踪 |
| 测试场景 | 3个 | 3个(对齐以便对比) |

---

## 快速开始

### 1. 安装依赖

```bash
cd prototypes/model_api_use_spike
pip install -r requirements.txt
```

### 2. 配置API密钥

创建 `.env` 文件：

```bash
# Flux API配置
FLUX_API_KEY=your_flux_api_key_here
FLUX_API_URL=https://api.flux.ai/v1/generate

# Qwen API配置
QWEN_API_KEY=your_qwen_api_key_here
QWEN_API_URL=https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis
```

或者设置环境变量：

```bash
export FLUX_API_KEY="your_api_key"
export QWEN_API_KEY="your_api_key"
```

### 3. 生成测试场景

```bash
# 使用默认API提供商(Flux)生成3个测试场景
python scripts/generate.py

# 指定API提供商
python scripts/generate.py --provider qwen

# 单张自定义生成
python scripts/generate.py --prompt "手机支付APP显示余额不足错误"
```

### 4. 查看结果

```bash
# 查看生成的图像
ls outputs/images/

# 查看成本报告
cat outputs/reports/cost_report_*.json

# 查看元数据
cat outputs/metadata/*.json
```

---

## 目录结构

```
model_api_use_spike/
├── README.md                          # 本文件
├── requirements.txt                   # Python依赖
├── config/
│   ├── api_config.json               # API配置(多提供商)
│   └── test_scenarios.json           # 3个测试场景
├── src/
│   ├── __init__.py
│   ├── utils.py                      # 工具函数
│   ├── config_loader.py              # 配置加载
│   ├── api_client.py                 # 统一API客户端
│   ├── cost_tracker.py               # 成本追踪器
│   └── image_generator.py            # 图像生成器
├── scripts/
│   └── generate.py                   # CLI命令行入口
├── outputs/                           # 生成的输出
│   ├── images/                       # 图像(按API分组)
│   │   ├── flux/
│   │   └── qwen/
│   ├── metadata/                     # 元数据JSON
│   └── reports/                      # 成本报告
└── text2img.py                        # 原始文件(已重构)
```

---

## 配置说明

### API配置 (config/api_config.json)

```json
{
  "active_provider": "flux",
  "providers": {
    "flux": {
      "api_key": "${FLUX_API_KEY}",
      "api_url": "${FLUX_API_URL}",
      "model": "flux_txt_to_image",
      "default_params": {
        "width": 450,
        "height": 807,
        "num_inference_steps": 10,
        "true_cfg_scale": 4.0
      },
      "cost_per_image": 0.02
    },
    "qwen": {
      "api_key": "${QWEN_API_KEY}",
      "api_url": "${QWEN_API_URL}",
      "model": "qwen-image-2512_txt_to_image",
      "default_params": {
        "width": 512,
        "height": 768,
        "steps": 20
      },
      "cost_per_image": 0.03
    }
  }
}
```

**关键字段**:
- `active_provider`: 默认使用的API提供商
- `api_key`: API密钥(支持环境变量`${VAR_NAME}`)
- `default_params`: 生成参数(宽高、步数等)
- `cost_per_image`: 每张图像成本(美元)

### 测试场景 (config/test_scenarios.json)

3个测试场景，覆盖不同异常类型：

1. **test_001 - payment_error** (错误提示异常): 支付失败弹窗
2. **test_002 - network_error** (交互异常): 网络连接失败
3. **test_003 - out_of_stock** (状态异常): 商品缺货

每个场景包含：
```json
{
  "id": "test_001",
  "category": "错误提示异常",
  "app": "支付",
  "title": "支付失败",
  "prompt": "手机支付APP截图,显示支付失败弹窗..."
}
```

---

## 支持的API提供商

### Flux API

**优势**:
- 生成质量高
- 速度快(2-4秒/张)
- 支持多种分辨率

**成本**: ~$0.02/张

**配置示例**:
```json
{
  "api_key": "${FLUX_API_KEY}",
  "api_url": "https://api.flux.ai/v1/generate",
  "model": "flux_txt_to_image"
}
```

### Qwen Image (阿里云)

**优势**:
- 国内访问快
- 中文理解能力强
- 适合生成中文UI

**成本**: ~$0.03/张

**配置示例**:
```json
{
  "api_key": "${QWEN_API_KEY}",
  "api_url": "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis",
  "model": "qwen-image-2512_txt_to_image"
}
```

### 扩展其他API

通过修改 `config/api_config.json` 和 `src/api_client.py` 可轻松添加其他提供商(如DALL-E, Midjourney)。

---

## 成本对比

### API方案成本

| API提供商 | 成本/张 | 100张成本 | 1000张成本 |
|----------|--------|----------|-----------|
| Flux | $0.02 | $2 | $20 |
| Qwen | $0.03 | $3 | $30 |
| DALL-E 3 | $0.04 | $4 | $40 |

### 本地方案成本(z_image_spike)

| 成本项 | 一次性成本 | 运行成本 |
|--------|----------|---------|
| GPU硬件 | $800-1200 (RTX 4080) | - |
| 电费 | - | ~$0.002/张 (0.2kWh × $0.10/kWh) |
| 总成本(100张) | $800-1200 | ~$0.20 |
| 总成本(1000张) | $800-1200 | ~$2.00 |

### 成本对比结论

- **小规模测试(<100张)**: API方案更经济
- **中等规模(100-500张)**: 接近平衡点
- **大规模(>1000张)**: 本地方案更经济(需要有GPU)

---

## 技术决策参考

### 何时选择API方案

✅ **适合场景**:
- 快速验证技术可行性
- 无GPU资源或GPU性能不足
- 需要频繁切换不同模型
- 小规模生成(<100张)
- 团队缺乏GPU运维经验

### 何时选择本地方案

✅ **适合场景**:
- 大规模生成(>1000张)
- 已有GPU资源(RTX 4080+)
- 需要精细控制模型参数
- 需要LoRA微调
- 数据隐私要求高

### 混合方案建议

💡 **推荐策略**:
1. **初期验证**: 使用API方案快速验证3-5个场景
2. **效果评估**: 对比不同API的生成质量
3. **规模决策**: 根据预期生成量决定是否切换到本地
4. **长期运行**: 大规模生成使用本地,临时需求使用API

---

## 使用示例

### 批量生成所有测试场景

```bash
$ python scripts/generate.py

============================================================
Model API Use Spike - API验证
============================================================
Loading configuration...
  Active Provider: flux
  Cost per Image: $0.02

Generating 3 test scenarios...
------------------------------------------------------------
[1/3] test_001 (payment_error)
  ✓ Generated in 2.5s: outputs/images/flux/test_001.png
  Cost: $0.02
[2/3] test_002 (network_error)
  ✓ Generated in 2.3s: outputs/images/flux/test_002.png
  Cost: $0.02
[3/3] test_003 (out_of_stock)
  ✓ Generated in 2.4s: outputs/images/flux/test_003.png
  Cost: $0.02
------------------------------------------------------------

============================================================
Generation Summary
============================================================
✅ 3/3 succeeded
💰 Total Cost: $0.06
📊 Cost Report: outputs/reports/cost_report_20260112_150000.json
============================================================
```

### 切换API提供商

```bash
# 使用Qwen API
python scripts/generate.py --provider qwen

# 使用自定义配置
python scripts/generate.py --config custom_config.json
```

### 单张自定义生成

```bash
python scripts/generate.py --prompt "手机外卖APP显示网络超时,页面中央有灰色断网图标"
```

### 查看成本报告

```json
{
  "timestamp": "2026-01-12T15:00:00",
  "total_cost": 0.06,
  "total_images": 3,
  "avg_cost_per_image": 0.02,
  "provider": "flux",
  "by_scenario": {
    "test_001": {"cost": 0.02, "time_sec": 2.5},
    "test_002": {"cost": 0.02, "time_sec": 2.3},
    "test_003": {"cost": 0.02, "time_sec": 2.4}
  },
  "total_time_sec": 7.2
}
```

---

## 架构设计

### 核心模块

```
ConfigLoader ─→ Config对象
     ↓
APIClient ──→ 调用云端API
     ↓
ImageGenerator ─→ 生成图像
     ↓
CostTracker ──→ 记录成本
     ↓
输出: 图像 + 元数据 + 成本报告
```

### API客户端设计

```python
# 统一接口
class APIClient(ABC):
    @abstractmethod
    def generate_image(self, prompt: str, **params) -> bytes

# 具体实现
class FluxClient(APIClient):
    def generate_image(self, prompt: str, **params) -> bytes:
        # 调用Flux API

class QwenClient(APIClient):
    def generate_image(self, prompt: str, **params) -> bytes:
        # 调用Qwen API

# 工厂方法
def create_client(provider_config: dict) -> APIClient:
    if provider == "flux":
        return FluxClient(config)
    elif provider == "qwen":
        return QwenClient(config)
```

---

## 故障排查

### API密钥未设置

**错误**:
```
ConfigError: Missing API key for provider 'flux'
```

**解决**:
```bash
# 方法1: 设置环境变量
export FLUX_API_KEY="your_key"

# 方法2: 创建.env文件
echo "FLUX_API_KEY=your_key" > .env
```

### API调用失败

**错误**:
```
HTTPError: 401 Unauthorized
```

**解决**:
1. 检查API密钥是否正确
2. 检查API配额是否用尽
3. 检查API URL是否正确

### 网络超时

**错误**:
```
TimeoutError: Request timed out after 30s
```

**解决**:
- 检查网络连接
- 使用国内API提供商(如Qwen)
- 增加超时时间

---

## 验证步骤

### 1. 环境检查

```bash
python -c "import requests; print('requests ok')"
python -c "from PIL import Image; print('Pillow ok')"
```

### 2. 配置检查

```bash
# 验证配置文件
python -c "from src.config_loader import load_api_config; load_api_config('config/api_config.json')"
```

### 3. API连通性测试

```bash
# 单张生成测试
python scripts/generate.py --prompt "test" --provider flux
```

### 4. 批量生成验证

```bash
# 生成所有测试场景
python scripts/generate.py

# 检查输出
ls -lh outputs/images/flux/
```

---

## 后续扩展

### P1 增强功能
- [ ] 批量生成多轮(支持重复运行)
- [ ] 详细的结构化日志
- [ ] 更丰富的CLI参数
- [ ] HTML格式的成本报告

### P2 对比分析
- [ ] API对比工具(compare_apis.py)
- [ ] 生成质量评估(CLIP Score)
- [ ] 技术决策报告生成
- [ ] 可视化对比界面

### Phase 2: 功能增强
- [ ] 支持更多API提供商(DALL-E, Midjourney)
- [ ] 实现图生图能力(基于现有截图修改)
- [ ] 添加质量评估模块
- [ ] 异常场景库管理

---

## 相关文档

### 项目文档
- [项目主README](../../README.md) - 项目概览
- [方案可行性分析](../../docs/research/01_方案可行性分析.md) - 三阶段方案评估
- [程序化异常生成调研](../../docs/research/02_程序化异常生成调研.md) - 异常生成技术路线

### 技术参考
- [z_image_spike README](../z_image_spike/README.md) - 本地方案参考
- [研究路线图](../../docs/planning/研究路线图.md) - 项目整体规划
- [技术栈与工具](../../docs/technical/技术栈与工具.md) - 技术选型

### API文档
- [Flux API文档](https://docs.flux.ai/) - Flux API使用说明
- [Qwen Image文档](https://help.aliyun.com/zh/dashscope/) - 阿里云通义千问

---

## 成功标准

### 必达指标
- ✅ 成功调用至少1个API生成3张图像
- ✅ README清晰说明spike定位
- ✅ 配置文件支持多API提供商
- ✅ 成本追踪正常工作
- ✅ 输出图像到正确目录

### 期望指标
- ✅ 支持2个以上API提供商
- ✅ 生成成本报告(JSON格式)
- ✅ 与z_image_spike形成有效对比
- ✅ 文档清晰完整

---

## License

MIT License - 仅供研究和学习使用

---

**版本**: v1.0.0
**最后更新**: 2026-01-12
**状态**: P0核心功能实现中
**维护者**: App_Test_Agent Team
