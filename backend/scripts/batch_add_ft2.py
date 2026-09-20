"""批量为剩余功能添加 function_type。"""
import re

def add_ft_before_call(file_path, call_pattern, function_type, import_from='.call_logger'):
    """在指定调用前添加 set_function_type。"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 添加导入
    if 'set_function_type' not in content:
        # 找到 ai_gateway 导入行
        if 'from .ai_gateway import' in content:
            content = content.replace(
                'from .ai_gateway import',
                f'from {import_from} import set_function_type\nfrom .ai_gateway import',
                1
            )
        elif 'from ..services.ai_gateway import' in content:
            content = content.replace(
                'from ..services.ai_gateway import',
                f'from ..services.call_logger import set_function_type\nfrom ..services.ai_gateway import',
                1
            )

    # 在调用前添加 set_function_type
    # 匹配 "    xxx = await chat_once(" 或 "    async for text in chat_stream("
    old = call_pattern
    # 获取缩进
    indent = ' ' * (len(call_pattern) - len(call_pattern.lstrip()))
    new = f'{indent}set_function_type("{function_type}")\n{call_pattern}'
    content = content.replace(old, new, 1)  # 只替换第一个

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  ✓ {file_path.split(chr(92))[-1]}: {function_type}")

# ========== handwrite_grading.py ==========
print("=== handwrite_grading.py ===")
add_ft_before_call(
    r'C:\creategame\AI学\backend\app\services\handwrite_grading.py',
    '        raw = await chat_once(',
    'handwrite'
)

# ========== planner.py ==========
print("=== planner.py ===")
add_ft_before_call(
    r'C:\creategame\AI学\backend\app\services\planner.py',
    '        raw = await chat_once(messages, temperature=0.5)',
    'planner'
)

# ========== stats.py ==========
print("=== stats.py ===")
add_ft_before_call(
    r'C:\creategame\AI学\backend\app\routers\stats.py',
    '            reply = await chat_once(',
    'stats',
    import_from='..services.call_logger'
)

# ========== quiz.py ==========
print("=== quiz.py ===")
file_path = r'C:\creategame\AI学\backend\app\services\quiz.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

if 'set_function_type' not in content:
    content = content.replace(
        'from .ai_gateway import',
        'from .call_logger import set_function_type\nfrom .ai_gateway import',
        1
    )

# quiz.py 有多个调用，需要根据函数区分
# 188行: 出题 → quiz
content = content.replace(
    '        raw = await chat_once(messages, temperature=0.4)',
    '        set_function_type("quiz")\n        raw = await chat_once(messages, temperature=0.4)',
    1
)
# 876, 909, 996行: 判卷/解析 → quiz_answer
# 这些是单独的 prompt 调用，都属于判卷
content = content.replace(
    '            raw = await chat_once([{"role": "user", "content": prompt}], temperature=0.1)',
    '            set_function_type("quiz_answer")\n            raw = await chat_once([{"role": "user", "content": prompt}], temperature=0.1)'
)
content = content.replace(
    '        raw = await chat_once([{"role": "user", "content": prompt}], temperature=0.2)',
    '        set_function_type("quiz_answer")\n        raw = await chat_once([{"role": "user", "content": prompt}], temperature=0.2)'
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("  ✓ quiz.py: quiz + quiz_answer")

# ========== knowledge_enhancer.py ==========
print("=== knowledge_enhancer.py ===")
file_path = r'C:\creategame\AI学\backend\app\services\knowledge_enhancer.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

if 'set_function_type' not in content:
    content = content.replace(
        'from .ai_gateway import',
        'from .call_logger import set_function_type\nfrom .ai_gateway import',
        1
    )

# 两个 chat_with_tools 调用都属于 knowledge
content = content.replace(
    '        result = await chat_with_tools(',
    '        set_function_type("knowledge")\n        result = await chat_with_tools('
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("  ✓ knowledge_enhancer.py: knowledge")

# ========== knowledge_refine.py ==========
print("=== knowledge_refine.py ===")
file_path = r'C:\creategame\AI学\backend\app\services\knowledge_refine.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

if 'set_function_type' not in content:
    content = content.replace(
        'from .ai_gateway import',
        'from .call_logger import set_function_type\nfrom .ai_gateway import',
        1
    )

content = content.replace(
    '        result = await chat_with_tools(',
    '        set_function_type("knowledge")\n        result = await chat_with_tools('
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("  ✓ knowledge_refine.py: knowledge")

# ========== routers/knowledge.py (chat_once 调用) ==========
print("=== routers/knowledge.py (chat_once) ===")
file_path = r'C:\creategame\AI学\backend\app\routers\knowledge.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 已有 set_function_type 导入，直接在 chat_once 前添加
content = content.replace(
    '        reply = await chat_once(',
    '        set_function_type("knowledge")\n        reply = await chat_once('
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("  ✓ knowledge.py router: knowledge")

print()
print("✅ 剩余功能 function_type 添加完成！")
