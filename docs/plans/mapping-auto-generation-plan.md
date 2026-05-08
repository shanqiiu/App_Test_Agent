# mapping.json 自动化生成方案（修正版）

## 1. 现状分析

### 1.1 当前数据流

```
examples2数据（服务端） → 手动/半自动脚本 → mapping.json（42条，7种异常类型）
     ↑                                                ↓
  task.json + screenshots/              batch_injection_with_mapping.py（运行时消费）
```

### 1.2 现有可复用能力

| 能力 | 成熟度 | 位置 | 说明 |
|------|--------|------|------|
| 页面类型分类（VLM） | ✅ 已实现 | `page_classifier.py` | 封闭式分类A-J，当前仅处理单张截图 |
| 规则引擎（页面→异常模式） | ✅ 已实现 | `rules.json` + `rule_engine.py` | 10条规则，含fault_mode/instruction_template |
| 预定义 fault_mode 名 | ✅ 已存在 | `rules.json` 10个 + 可按APP扩展 | **选择而非生成** |
| GT 模板匹配 | ⚠️ 部分 | `data/gt-category/*/` | 按 app_name 模糊匹配，覆盖率不足 |
| anomaly_mode 自动决策 | ⚠️ 已实现但仅用于注入点 | `batch_injection_with_mapping.py` | 规则引擎返回的 anomaly_mode 当前刻意忽略 |

### 1.3 关键制约

1. **examples2 数据不在本地**：`mapping.json` 引用了 25 个 `injection_demo_XX` 目录，本地 `data/examples/` 仅 3 个
2. **PageClassifier 无序列感知**：当前 `classify()` 仅处理单张截图（`page_classifier.py` L94），VLM prompt 无 query 上下文注入
3. **GT 模板覆盖率不足**：仅有 10 张 dialog、1 张 area_loading、0 张 content_duplicate，覆盖 3 个 APP
4. **fault_mode 集需扩展**：`rules.json` 预定义了 10 个通用 fault_mode，但实际 mapping 中有 APP 专属名称（如"下载按钮遮挡"、"选集置灰"等）不在其中

---

## 2. 分阶段方案

### Phase 1：半自动化生成（推荐立即实施）

**目标**：脚本生成 mapping.json 初稿，人工审核后发布

**输入**：
- `examples/{injection_demo_XX}/task.json`（query 描述 + app_name）
- `examples/{injection_demo_XX}/screenshots/`（截图序列）
- `config/rules.json`（预定义 fault_mode 命名 + 规则）
- `config/fault_mode_templates.json`（新增：APP 专属 fault_mode 扩展）
- `data/gt-category/*/`（GT 模板库）

**流程**：

```
Step 1: 扫描 examples 目录，遍历每个 demo
          ↓
Step 2: 读取 task.json → query, app_name
          ↓
Step 3: 序列级页面分类
        ┌─ 将 full screenshot sequence + query 上下文送入 VLM
        │  识别：整体流程类型（购票/下载视频/点餐…）
        │  定位：最适合注入异常的页面（step index + page_type）
        └─ 输出：injection_page_type, key_elements, user_waiting
          ↓
Step 4: RuleEngine 匹配
        ┌─ 根据 page_type + key_elements + user_waiting 匹配 rules.json
        │  获取：anomaly_mode, fault_mode（预定义名）, instruction_template
        └─ 若规则无匹配 → 使用 fallback，标记 confidence=low
          ↓
Step 5: 按 app_name 匹配 GT 模板
        ┌─ 精确匹配：app_name 完全一致
        │  模糊匹配：app 类别一致（如"视频"类 → 华为花粉俱乐部）
        └─ 兜底：使用同 category 下第一个可用模板
          ↓
Step 6: fault_mode 选择 + instruction 细化
        ┌─ fault_mode: 从预定义集中选择（rules.json + APP 专属模板）
        │  不在预定义集中的 → 标记为 needs_review
        └─ instruction: 用模板 + query 占位符填充，VLM 润色措辞
          ↓
Step 7: 生成 1 个或多个 fault_mode 条目（不强制 2 个）
        ┌─ 若规则匹配到多条（如 page_type=home 同时命中 splash_dialog_ad
        │  和 home_dialog_coupon）→ 取 top-N 条
        │  若仅有 1 条 → 生成 mode_1 即可
        └─ 多条需确保 fault_mode 语义不重复
          ↓
Step 8: 输出 mapping_auto.json → 人工审核
```

**fault_mode 选择机制**（非 VLM 生成）：

```
优先级 1: rules.json 预定义名（10 个）→ 确定性匹配，confidence=high
  例：page_type=home → "开屏广告弹窗" / "优惠券弹窗" / "权限请求弹窗"

优先级 2: APP 专属模板 → 按 app_name + page_type 查表，confidence=medium
  例：app=视频 + page=detail → ["下载按钮遮挡", "选集置灰", "内容名篡改"]

优先级 3: VLM 建议 + 人工确认 → confidence=low, needs_review=true
  仅当前两级无匹配时使用，且标记为必须审核
```

**页面分类改进**（序列级，非单帧）：

```
当前实现（有问题）：
  PageClassifier.classify(single_screenshot) → page_type
  问题：单张截图无上下文，可能误分类（如搜索结果页 vs 详情页外观接近）

改进方案：
  1. 将全序列 + query 描述编码为 VLM prompt：
     "任务：{query}。以下是该任务执行过程中的 {N} 张截图序列。
      请分析整个流程，确定最合理注入异常的页面是第几张截图，
      以及该页面的类型（A-J）。"
  2. VLM 返回：injection_step_index, page_type, key_elements, reasoning
  3. 之后再对目标帧做细粒度分类确认
```

---

### Phase 2：规则驱动 + 人工标注

**目标**：建立标注规范，将人工判断固化为规则

**新增能力**：

1. **`config/fault_mode_templates.json`** — APP 专属 fault_mode 扩展表
   ```json
   {
     "视频": {
       "home":       ["弹窗广告"],
       "detail":     ["内容名篡改", "选集置灰", "下载按钮遮挡"],
       "list_result":["选集信息重复", "内容重复展示"]
     },
     "去哪儿旅行": {
       "home":       ["弹窗广告", "权限请求弹窗"],
       "search":     ["价格逻辑错误", "商务舱比经济舱更便宜"],
       "list_result":["增值服务总价异常", "价格计算错误"]
     },
     "铁路12306": {
       "home":       ["系统提示弹窗"],
       "list_result":["加载超时"]
     }
   }
   ```

2. **`config/instruction_templates.json`** — 预定义 instruction 模板
   ```json
   {
     "弹窗广告": "在首页生成广告弹窗遮挡功能入口",
     "下载按钮遮挡": "在下载按钮区域生成遮挡元素，阻止用户点击下载",
     "内容名篡改": "将页面中的「{content_name}」替换为「{fake_name}」，模拟内容名称篡改异常",
     "选集置灰": "将选集列表中从第{start_ep}集开始的勾选框置灰，模拟选集权限限制异常",
     "价格逻辑错误": "修改搜索结果中的{price_field}数字，制造价格逻辑矛盾"
   }
   ```

3. **GT 匹配策略升级**：APP 名精确 → APP 类别模糊 → 同 anomaly_mode 兜底

---

### Phase 3：完全自动化（长期目标，不推荐短期追求）

**前置条件**（均不满足）：
- PageClassifier 序列级分类准确率 > 95%
- fault_mode 预定义集覆盖 90%+ 场景
- GT 模板库覆盖所有目标 APP
- 有 labeled 数据做回归测试

**当前评估**：异常类测试数据质量 > 数量，人工审核不可省略。

---

## 3. Phase 1 具体实现计划

### 3.1 新建脚本：`scripts/generate_mapping.py`

```python
def generate_mapping(examples_dir, gt_dir, rules_path,
                     fault_mode_templates_path, output_path):
    """
    扫描 examples 目录，为每个 demo 生成 mapping 条目

    Args:
        examples_dir: examples2 数据目录
        gt_dir: GT 模板目录
        rules_path: rules.json 路径
        fault_mode_templates_path: APP 专属 fault_mode 模板路径
        output_path: 输出 JSON 路径

    Returns:
        {
            "auto_generated": int,    # 自动生成的条目数
            "needs_review": int,      # 需人工审核的条目数
            "confidence_high": [...], # 高置信度条目
            "confidence_low": [...],  # 低置信度条目（含原因）
            "unmatched_gt": [...],    # GT 无匹配的条目
            "mappings": [...]         # 完整映射列表
        }
    """
```

### 3.2 实现步骤

| 步骤 | 函数 | 依赖 | 估时 |
|------|------|------|------|
| 1. 扫描目录 | `scan_examples()` | 文件系统 | 0.5h |
| 2. 序列级分类 | `classify_sequence()` | VLM + 全序列截图 | 2h |
| 3. 规则匹配 | `match_rule()` | RuleEngine | 0.5h |
| 4. GT 匹配 | `match_gt()` | GT 文件系统 | 1h |
| 5. fault_mode 选择 | `select_fault_mode()` | rules.json + templates | 1h |
| 6. instruction 填充 | `fill_instruction()` | 模板引擎 | 0.5h |
| 7. 条目组装 | `build_mapping_entry()` | 以上全部 | 0.5h |
| 8. 主流程 + CLI | `main()` | argparse | 1h |
| 9. 对比验证 | `validate_against_manual()` | 现有 mapping.json | 1h |

**总估时**：约 8-10 小时

### 3.3 输出格式

```json
{
  "version": "auto-1.0",
  "generated_at": "2026-05-08T...",
  "source": "examples2",
  "auto_generated": 35,
  "needs_review": 7,
  "confidence_low": [
    {
      "query_id": "xxx",
      "reason": "fault_mode不在预定义集中，VLM建议'搜索结果置灰异常'",
      "suggested_action": "人工确认fault_mode名，或将其添加到fault_mode_templates.json"
    }
  ],
  "unmatched_gt": [
    {
      "query_id": "xxx",
      "app_name": "视频",
      "anomaly_mode": "content_duplicate",
      "reason": "content_duplicate目录为空，无可用GT模板"
    }
  ],
  "mappings": [...]
}
```

### 3.4 置信度标记

| 置信度 | 条件 | 建议 |
|--------|------|------|
| high | rules.json 精确匹配 + GT 精确匹配 + fault_mode 在预定义集中 | 抽查 |
| medium | 规则匹配但 GT 模糊匹配，或 fault_mode 来自 APP 专属模板 | 人工审核 |
| low | 规则无匹配用 fallback，fault_mode 不在预定义集中 | **必须人工改写** |

---

## 4. 风险与限制

1. **序列级 VLM 分类成本高**：全序列多图 prompt token 消耗大 → 可先用首帧+末帧做轻量分类，失败时回退全序列
2. **fault_mode 预定义集需持续维护**：新增 APP/场景时需同步更新 `fault_mode_templates.json`
3. **GT 模板覆盖率不足**：当前 content_duplicate 目录为空 → 需扩充 GT 库或允许该模式不指定 gt_sample
4. **examples 数据依赖**：需从服务端同步 → 前置条件
5. **回退策略**：始终保留 manual `mapping.json` 作为 fallback，自动版本标记为 `mapping_auto.json`

---

## 5. 建议

- **立即启动 Phase 1**：投入产出比最高，8-10h 可将 70% 映射工作自动化
- **Phase 1 同步创建 `fault_mode_templates.json`**：作为 Phase 2 的种子数据，从现有 mapping.json 反推出 APP 专属命名
- **暂不追求 Phase 3**：GT 模板库不足 + VLM 准确率未验证前，完全自动化不可靠
- **保留人工审核作为必需环节**：`confidence=low` 的条目强制人工确认后方可入库
