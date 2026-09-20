"""
提示词优化前后 Token 消耗对比分析
Token 估算：中文字符 × 1.3 + 英文单词 × 1.0 + 其他字符 × 0.3
（适用于 DeepSeek / GPT-4 / Qwen 等主流分词器的大致比例）
"""
import re
import json
import os

PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")

def estimate_tokens(text):
    """估算 token 数"""
    chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
    english_words = len(re.findall(r'[a-zA-Z]+', text))
    other = len(text) - chinese - sum(len(w) for w in re.findall(r'[a-zA-Z]+', text))
    tokens = chinese * 1.3 + english_words * 1.0 + other * 0.3
    return {
        'total_chars': len(text),
        'chinese_chars': chinese,
        'english_words': english_words,
        'other_chars': other,
        'estimated_tokens': round(tokens, 1)
    }

def read_prompt(name):
    path = os.path.join(PROMPT_DIR, name)
    with open(path, 'r', encoding='utf-8') as f:
        return f.read().strip()

# 分析所有对比组
comparisons = [
    {
        'id': 'classroom_system',
        'name': '课堂系统提示词',
        'scenario': '每次课堂交互必发，高频',
        'before_file': 'before_classroom_system.txt',
        'after_file': 'after_classroom_system.txt',
        'optimization': '结构化分区（角色/规则/上下文），压缩冗长要求描述',
    },
    {
        'id': 'quiz_single_choice',
        'name': '出题-单项选择',
        'scenario': '每题一次，中等频率',
        'before_file': 'before_quiz_single_choice.txt',
        'after_file': 'after_quiz_single_choice.txt',
        'optimization': '引入 system prompt（字段定义表），user 只传参数；JSON 完整示例改为字段定义',
    },
    {
        'id': 'quiz_fill_cloze',
        'name': '出题-填空（挖空）',
        'scenario': '每题一次，高消耗场景',
        'before_file': 'before_quiz_fill_cloze.txt',
        'after_file': 'after_quiz_fill_cloze.txt',
        'optimization': '引入 system prompt，7条要求合并为规则段，JSON 示例改为字段定义',
    },
]

results = []
total_before = 0
total_after = 0

for comp in comparisons:
    before_text = read_prompt(comp['before_file'])
    after_text = read_prompt(comp['after_file'])
    before_stats = estimate_tokens(before_text)
    after_stats = estimate_tokens(after_text)
    savings = before_stats['estimated_tokens'] - after_stats['estimated_tokens']
    savings_pct = round(savings / before_stats['estimated_tokens'] * 100, 1) if before_stats['estimated_tokens'] > 0 else 0

    result = {
        'id': comp['id'],
        'name': comp['name'],
        'scenario': comp['scenario'],
        'optimization': comp['optimization'],
        'before': before_stats,
        'after': after_stats,
        'savings_tokens': round(savings, 1),
        'savings_pct': savings_pct,
    }
    results.append(result)
    total_before += before_stats['estimated_tokens']
    total_after += after_stats['estimated_tokens']

total_savings = total_before - total_after
total_savings_pct = round(total_savings / total_before * 100, 1) if total_before > 0 else 0

summary = {
    'total_before_tokens': round(total_before, 1),
    'total_after_tokens': round(total_after, 1),
    'total_savings_tokens': round(total_savings, 1),
    'total_savings_pct': total_savings_pct,
    'comparisons': results,
}

# 输出 JSON
output_path = os.path.join(os.path.dirname(__file__), 'analysis', 'token_comparison.json')
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)

# 打印报告
print("=" * 70)
print("提示词优化 Token 消耗对比报告")
print("=" * 70)
print()
for r in results:
    print(f"【{r['name']}】({r['scenario']})")
    print(f"  优化前: {r['before']['estimated_tokens']} tokens ({r['before']['total_chars']} 字符)")
    print(f"  优化后: {r['after']['estimated_tokens']} tokens ({r['after']['total_chars']} 字符)")
    print(f"  节省:   {r['savings_tokens']} tokens ({r['savings_pct']}%)")
    print(f"  优化手段: {r['optimization']}")
    print()

print("=" * 70)
print(f"合计: {summary['total_before_tokens']} → {summary['total_after_tokens']} tokens")
print(f"总节省: {summary['total_savings_tokens']} tokens ({summary['total_savings_pct']}%)")
print("=" * 70)
print()
print("注：token 数为估算值（中文×1.3 + 英文词×1.0 + 其他×0.3），")
print("实际值取决于具体模型的分词器，但比例关系具有参考意义。")
print(f"详细数据已保存至: {output_path}")
