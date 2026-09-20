"""批量为所有 AI 调用点添加 function_type 标记（简化版）。"""
import os

files_to_modify = [
    # (文件路径, 替换规则列表: (旧文本, 新文本, function_type))
    (
        r'C:\creategame\AI学\backend\app\services\cloze_service.py',
        [
            ('from .ai_gateway import chat_stream',
             'from .ai_gateway import chat_stream\nfrom .call_logger import set_function_type'),
            # generate_cloze - quiz
            ('    parts: list[str] = []\n    try:\n        async for text in chat_stream(messages):',
             '    parts: list[str] = []\n    set_function_type("quiz")\n    try:\n        async for text in chat_stream(messages):'),
            # grade_cloze - quiz_answer (第二个出现的)
            ('    parts: list[str] = []\n    try:\n        async for text in chat_stream(messages):',
             '    parts: list[str] = []\n    set_function_type("quiz_answer")\n    try:\n        async for text in chat_stream(messages):'),
        ]
    ),
]

# 由于 cloze_service 有两个相同的模式，需要特殊处理
# 让我逐个文件精确修改

print("=== 修改 cloze_service.py ===")
file_path = r'C:\creategame\AI学\backend\app\services\cloze_service.py'
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 添加导入
for i, line in enumerate(lines):
    if 'from .ai_gateway import chat_stream' in line and 'set_function_type' not in lines[i+1]:
        lines.insert(i+1, 'from .call_logger import set_function_type\n')
        print(f"  行 {i+1}: 添加导入")
        break

# 找到所有 chat_stream 调用行，根据所在函数设置 function_type
current_func = None
for i, line in enumerate(lines):
    if 'async def generate_cloze' in line:
        current_func = 'quiz'
    elif 'async def grade_cloze' in line:
        current_func = 'quiz_answer'
    elif 'async def generate_cloze_batch' in line:
        current_func = 'quiz'
    elif 'async def grade_cloze_batch' in line:
        current_func = 'quiz_answer'
    elif 'async for text in chat_stream(' in line and current_func:
        # 在上一行（parts = [] 或 try:）之前插入 set_function_type
        # 找到 try: 行
        for j in range(i, max(i-5, 0), -1):
            if 'try:' in lines[j]:
                indent = lines[j][:len(lines[j]) - len(lines[j].lstrip())]
                lines.insert(j, f'{indent}set_function_type("{current_func}")\n')
                print(f"  行 {j+1}: 添加 set_function_type({current_func})")
                break
        current_func = None  # 重置，避免重复

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)
print("  ✓ cloze_service.py 完成")

print()
print("=== 修改 routers/classroom.py (detailed-explanation) ===")
file_path = r'C:\creategame\AI学\backend\app\routers\classroom.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 添加导入
if 'set_function_type' not in content:
    content = content.replace(
        'from ..services.ai_gateway import chat_stream, AiGatewayError',
        'from ..services.ai_gateway import chat_stream, AiGatewayError\nfrom ..services.call_logger import set_function_type'
    )

# 在 detailed-explanation 的 chat_stream 前添加
content = content.replace(
    '    parts = []\n    try:\n        async for text in chat_stream(messages):',
    '    parts = []\n    set_function_type("quiz_answer")\n    try:\n        async for text in chat_stream(messages):'
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("  ✓ classroom.py (router) 完成")

print()
print("=== 修改 services/classroom.py ===")
file_path = r'C:\creategame\AI学\backend\app\services\classroom.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

if 'set_function_type' not in content:
    content = content.replace(
        'from .ai_gateway import chat_stream',
        'from .ai_gateway import chat_stream\nfrom .call_logger import set_function_type'
    )

# classroom 互动的 chat_stream
content = content.replace(
    'async for text in chat_stream(messages, info_collector=info_collector):',
    'set_function_type("classroom")\n        async for text in chat_stream(messages, info_collector=info_collector):'
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("  ✓ classroom.py (service) 完成")

print()
print("=== 修改 routers/knowledge.py ===")
file_path = r'C:\creategame\AI学\backend\app\routers\knowledge.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

if 'set_function_type' not in content:
    content = content.replace(
        'from ..services.ai_gateway import chat_stream',
        'from ..services.ai_gateway import chat_stream\nfrom ..services.call_logger import set_function_type'
    )

# 两个 knowledge 调用
content = content.replace(
    'async for text in chat_stream(messages):',
    'set_function_type("knowledge")\n        async for text in chat_stream(messages):'
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("  ✓ knowledge.py 完成")

print()
print("✅ 批量添加 function_type 完成！")
