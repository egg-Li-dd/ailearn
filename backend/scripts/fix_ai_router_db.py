"""批量修复 ai.py 中访问全局表的接口，改用 get_global_db。"""
file_path = r'C:\creategame\AI学\backend\app\routers\ai.py'
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 需要改为 get_global_db 的行号（访问全局表 ai_channels, ai_call_logs）
global_db_lines = [75, 216, 221, 232, 246, 341, 402, 444, 489, 502, 608]

changed = 0
for i, line in enumerate(lines):
    lineno = i + 1
    if lineno in global_db_lines:
        if 'get_db' in line and 'get_global_db' not in line:
            lines[i] = line.replace('Depends(get_db)', 'Depends(get_global_db)')
            changed += 1
            print(f'  行 {lineno}: {line.strip()[:60]}')

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print(f'\n共修改 {changed} 处')
