"""
实际调用 AI，对比优化前后 prompt 的输出内容和 token 消耗
"""
import sys
import os
import json
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.services.ai_gateway import chat_once_with_usage

DEMO_DIR = os.path.dirname(__file__)
PROMPT_DIR = os.path.join(DEMO_DIR, 'prompts')
OUTPUT_DIR = os.path.join(DEMO_DIR, 'outputs')
os.makedirs(OUTPUT_DIR, exist_ok=True)


def read_prompt(name):
    with open(os.path.join(PROMPT_DIR, name), 'r', encoding='utf-8') as f:
        return f.read().strip()


def parse_messages(prompt_text):
    """
    解析 prompt 文件为 messages 列表。
    如果文件包含 [system] / [user] 标记，按标记拆分；
    否则整个内容作为 user message。
    """
    if '[system]' in prompt_text and '[user]' in prompt_text:
        messages = []
        # 按标记拆分
        import re
        parts = re.split(r'\[(system|user)\]', prompt_text)
        # parts: ['', 'system', '...', 'user', '...']
        i = 1
        while i < len(parts):
            role = parts[i]
            content = parts[i + 1].strip() if i + 1 < len(parts) else ''
            if content:
                messages.append({'role': role, 'content': content})
            i += 2
        return messages
    else:
        # 去掉 [只有 user prompt，无 system] 这样的注释行
        lines = prompt_text.split('\n')
        clean_lines = [l for l in lines if not l.strip().startswith('[') or 'prompt' not in l.lower()]
        content = '\n'.join(clean_lines).strip()
        return [{'role': 'user', 'content': content}]


async def run_comparison(scenario_id, before_file, after_file, label):
    print(f"\n{'='*60}")
    print(f"场景: {label}")
    print(f"{'='*60}")

    before_prompt = read_prompt(before_file)
    after_prompt = read_prompt(after_file)

    before_messages = parse_messages(before_prompt)
    after_messages = parse_messages(after_prompt)

    print(f"\n优化前 messages 结构: {[m['role'] for m in before_messages]}")
    print(f"优化后 messages 结构: {[m['role'] for m in after_messages]}")

    # 调用优化前
    print(f"\n[优化前] 正在调用 AI...")
    try:
        before_text, before_usage = await chat_once_with_usage(
            before_messages, temperature=0.4
        )
        print(f"[优化前] 完成. tokens: {before_usage}")
    except Exception as e:
        print(f"[优化前] 失败: {e}")
        before_text = f"调用失败: {e}"
        before_usage = {}

    # 调用优化后
    print(f"\n[优化后] 正在调用 AI...")
    try:
        after_text, after_usage = await chat_once_with_usage(
            after_messages, temperature=0.4
        )
        print(f"[优化后] 完成. tokens: {after_usage}")
    except Exception as e:
        print(f"[优化后] 失败: {e}")
        after_text = f"调用失败: {e}"
        after_usage = {}

    result = {
        'scenario_id': scenario_id,
        'label': label,
        'before': {
            'prompt': before_prompt,
            'messages': before_messages,
            'output': before_text,
            'usage': before_usage,
        },
        'after': {
            'prompt': after_prompt,
            'messages': after_messages,
            'output': after_text,
            'usage': after_usage,
        },
    }

    # 保存
    out_file = os.path.join(OUTPUT_DIR, f'{scenario_id}_comparison.json')
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {out_file}")

    return result


async def main():
    results = []

    # 场景1: 单选题
    r1 = await run_comparison(
        'quiz_single_choice',
        'before_quiz_single_choice.txt',
        'after_quiz_single_choice.txt',
        '出题-单项选择（知识点：队列）'
    )
    results.append(r1)

    # 场景2: 填空题
    r2 = await run_comparison(
        'quiz_fill_cloze',
        'before_quiz_fill_cloze.txt',
        'after_quiz_fill_cloze.txt',
        '出题-填空挖空（知识点：二叉树遍历）'
    )
    results.append(r2)

    # 汇总
    print(f"\n\n{'='*60}")
    print("汇总对比")
    print(f"{'='*60}")
    for r in results:
        bu = r['before']['usage']
        au = r['after']['usage']
        bt = bu.get('total_tokens', bu.get('total_tokens', '?'))
        at = au.get('total_tokens', au.get('total_tokens', '?'))
        print(f"\n{r['label']}")
        print(f"  优化前: total={bt}, prompt={bu.get('prompt_tokens','?')}, completion={bu.get('completion_tokens','?')}")
        print(f"  优化后: total={at}, prompt={au.get('prompt_tokens','?')}, completion={au.get('completion_tokens','?')}")
        if isinstance(bt, (int, float)) and isinstance(at, (int, float)) and bt > 0:
            savings = bt - at
            pct = savings / bt * 100
            print(f"  节省: {savings} tokens ({pct:.1f}%)")

    # 保存汇总
    summary_file = os.path.join(OUTPUT_DIR, 'summary.json')
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n汇总已保存: {summary_file}")


if __name__ == '__main__':
    asyncio.run(main())
