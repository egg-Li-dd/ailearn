# 提示词结构优化方案 - 独立演示项目

## 项目概述

本项目独立于主业务代码，用于展示 AI 提示词（Prompt）的结构优化方案及 Token 消耗对比成果。

**核心思路**：从"内容精简（删字）"升级为"结构重构"，在不影响输出效果的前提下，通过四项结构性改造降低 Token 消耗量。

## 优化策略

| 优化维度 | 优化前 | 优化后 |
|---------|--------|--------|
| 消息架构 | 只有 user，静态规则和动态参数混在一起 | system（静态规则）+ user（动态参数） |
| System 结构 | 纯文本拼接，无分区 | 【角色】【规则】【上下文】分区结构化 |
| JSON 格式 | 完整示例（含占位符，180-300字） | 字段定义表（字段名+类型+约束，60-120字） |
| 要求描述 | 逐条完整句子展开 | 合并为精简规则段 |

## 优化成果

| 场景 | 优化前 | 优化后 | 节省 |
|------|--------|--------|------|
| 课堂系统提示词 | 491.6 tokens | 172.6 tokens | **64.9%** |
| 出题-单项选择 | 168.4 tokens | 99.5 tokens | **40.9%** |
| 出题-填空（挖空） | 346.6 tokens | 176.4 tokens | **49.1%** |
| **合计** | **1006.6** | **448.5** | **55.4%** |

## 项目结构

```
prompt-optimization-demo/
├── index.html                    # 主展示页面（可视化对比）
├── 启动演示.bat                   # 一键启动本地服务器查看演示
├── analyze_tokens.py             # Token 消耗分析脚本
├── prompts/                      # 优化前后的提示词文件
│   ├── before_classroom_system.txt
│   ├── after_classroom_system.txt
│   ├── before_quiz_single_choice.txt
│   ├── after_quiz_single_choice.txt
│   ├── before_quiz_fill_cloze.txt
│   └── after_quiz_fill_cloze.txt
└── analysis/
    └── token_comparison.json     # 分析结果数据
```

## 查看演示

### 方式一：一键启动（推荐）
双击 `启动演示.bat`，自动打开浏览器访问 `http://localhost:8765`

### 方式二：手动启动
```bash
cd prompt-optimization-demo
python -m http.server 8765
# 浏览器访问 http://localhost:8765
```

### 方式三：直接打开
直接用浏览器打开 `index.html`（部分浏览器可能因安全策略无法加载本地 prompt 文件，建议用方式一/二）

## 重新运行分析

```bash
python analyze_tokens.py
```

输出各场景的 Token 消耗对比，并更新 `analysis/token_comparison.json`。

## Token 估算说明

Token 数为估算值，计算公式：
- 中文字符 × 1.3
- 英文单词 × 1.0
- 其他字符 × 0.3

适用于 DeepSeek / GPT-4 / Qwen 等主流分词器的大致比例。实际值取决于具体模型的分词器，但节省比例关系具有参考意义。

## 后续可扩展方向

1. **消息历史优化**：历史消息截断、条数缩减、内部字段去除
2. **全场景覆盖**：planner、sediment、knowledge_refine、handwrite_grading 等
3. **数据结构瘦身**：AI 交互格式去除内部跟踪字段，响应只保留渲染必需字段
4. **实际 A/B 测试**：在真实业务中对比优化前后的输出质量和 Token 消耗
