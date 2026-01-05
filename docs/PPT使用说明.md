# PPT使用说明

## 文件信息

- **文件名**: AI智能体异常测试场景生成_汇报PPT.md
- **文件位置**: [docs/AI智能体异常测试场景生成_汇报PPT.md](./AI智能体异常测试场景生成_汇报PPT.md)
- **格式**: Markdown (Marp格式)
- **页数**: 30+ 页
- **适用场景**: 技术汇报、方案展示、进度汇报

---

## 如何使用

### 方式1: 使用Marp (推荐) ⭐⭐⭐⭐⭐

**Marp** 是专门将Markdown转换为PPT的工具。

#### 安装Marp CLI
```bash
npm install -g @marp-team/marp-cli
```

#### 生成PPT
```bash
# 生成HTML格式（可在浏览器中演示）
marp docs/AI智能体异常测试场景生成_汇报PPT.md -o output.html

# 生成PDF格式
marp docs/AI智能体异常测试场景生成_汇报PPT.md -o output.pdf

# 生成PowerPoint格式
marp docs/AI智能体异常测试场景生成_汇报PPT.md -o output.pptx
```

#### VS Code扩展
- 安装 **Marp for VS Code** 扩展
- 打开Markdown文件
- 点击右上角预览按钮即可实时预览

---

### 方式2: 使用reveal.js

**reveal.js** 是HTML5演示框架。

#### 在线转换
1. 访问 [https://revealjs.com](https://revealjs.com)
2. 将Markdown内容复制到编辑器
3. 调整格式（可能需要微调分隔符）

#### 本地使用
```bash
# 克隆reveal.js
git clone https://github.com/hakimel/reveal.js.git
cd reveal.js

# 将Markdown内容放入
# 访问 http://localhost:8000
npm start
```

---

### 方式3: 直接在IDE中预览

**支持Markdown预览的IDE**:
- VS Code (安装Markdown Preview Enhanced)
- Typora (直接预览)
- Obsidian (使用Slides插件)

**优点**: 快速预览结构和内容
**缺点**: 无法看到真实PPT效果

---

## PPT内容结构

### 第一部分：项目背景与核心问题 (3页)
- 当前AI智能体测试面临的挑战
- 项目目标和预期价值

### 第二部分：技术方案概述 (4页)
- 三阶段技术框架
- 技术可行性评估

### 第三部分：异常界面生成技术路线 (5页)
- 四种技术方案对比
- 推荐方案：LLM + Diffusion
- 业界对比分析

### 第四部分：研究进展与成果 (5页)
- 当前里程碑
- 核心文档产出
- 关键技术突破
- 创新价值

### 第五部分：下一步工作计划 (8页)
- Phase 1-3 详细计划
- 资源需求
- 风险与应对
- 成功标准

### 总结与附录 (5页)
- 核心亮点总结
- 参考资源
- 技术栈说明

---

## 定制建议

### 根据汇报对象调整

#### 技术汇报（工程师、架构师）
- 保留所有技术细节
- 重点强调第三、四部分
- 增加技术实现细节

#### 管理汇报（领导、产品经理）
- 精简技术细节
- 强调第一、二、五部分
- 重点展示价值和计划

#### 学术汇报（研究人员、高校）
- 强调第三、四部分
- 增加学术创新点
- 补充实验数据和对比

---

## 快速修改指南

### 修改主题色
在文件开头修改：
```yaml
backgroundColor: #fff  # 修改背景色
```

### 修改字体大小
在具体页面添加：
```markdown
<!-- _style: "font-size: 1.2em;" -->
```

### 添加图片
```markdown
![width:800px](path/to/image.png)
```

### 添加双栏布局
```markdown
<div class="columns">
<div>

左栏内容

</div>
<div>

右栏内容

</div>
</div>
```

---

## 演示技巧

### 关键页面
- **第3页**: 核心问题 - 引起共鸣
- **第10页**: 推荐方案 - 技术亮点
- **第12页**: 业界对比 - 创新价值
- **第14页**: 研究进展 - 成果展示
- **第24页**: 成功标准 - 可量化目标

### 时间分配（30分钟汇报）
- 背景与问题 (5分钟)
- 技术方案 (8分钟)
- 技术路线 (7分钟)
- 研究进展 (6分钟)
- 工作计划 (4分钟)

---

## 导出建议

### 汇报场景
- **现场演示**: HTML格式 (可交互，链接可点击)
- **文档留存**: PDF格式 (兼容性好)
- **进一步编辑**: PPTX格式 (可用PowerPoint编辑)

### 导出命令
```bash
# 同时导出三种格式
marp docs/AI智能体异常测试场景生成_汇报PPT.md -o output.html
marp docs/AI智能体异常测试场景生成_汇报PPT.md -o output.pdf
marp docs/AI智能体异常测试场景生成_汇报PPT.md -o output.pptx
```

---

## 常见问题

**Q: 为什么使用Markdown格式？**
A:
- ✅ 易于版本控制
- ✅ 内容和样式分离
- ✅ 可自动化生成
- ✅ 易于协作编辑

**Q: 如何添加备注？**
A: 使用HTML注释
```markdown
<!--
这是备注内容，不会在PPT中显示
但可以在演讲者模式中看到
-->
```

**Q: 如何自定义样式？**
A:
1. 创建自定义主题CSS
2. 在文件头部指定：`theme: custom`
3. 参考Marp主题开发文档

---

## 相关资源

- [Marp官方文档](https://marpit.marp.app/)
- [Marp CLI GitHub](https://github.com/marp-team/marp-cli)
- [reveal.js官网](https://revealjs.com/)
- [Markdown PPT最佳实践](https://marp.app/#get-started)

---

**最后更新**: 2026-01-05
**创建者**: Claude Code
**版本**: v1.0
