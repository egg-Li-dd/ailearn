"""修复 App.vue 中 sidebar-footer 的 HTML 模板，恢复双引号。"""
file_path = r'C:\creategame\AI学\admin\src\App.vue'

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找到 sidebar-footer 并替换
new_lines = []
i = 0
while i < len(lines):
    if '<div class=sidebar-footer>' in lines[i] or '<div class="sidebar-footer">' in lines[i]:
        # 替换整个 sidebar-footer 块
        new_lines.append('      <div class="sidebar-footer">\n')
        new_lines.append('        <div class="backend-info">\n')
        new_lines.append('          <span class="backend-label">后端</span>\n')
        new_lines.append('          <span class="backend-url" :title="backendUrl">{{ backendUrl.replace(\'http://\', \'\').replace(\'https://\', \'\') }}</span>\n')
        new_lines.append('        </div>\n')
        new_lines.append('        <span class="version">v0.1.0 · 多用户版</span>\n')
        new_lines.append('      </div>\n')
        # 跳过原来的 sidebar-footer 块（直到找到 </div> 后再跳过）
        i += 1
        while i < len(lines) and '</div>' not in lines[i]:
            i += 1
        i += 1  # 跳过 </div>
    else:
        new_lines.append(lines[i])
        i += 1

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print('修复完成')
# 验证
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()
target = 'class="sidebar-footer"'
print(f'包含 class="sidebar-footer": {target in content}')
print(f'包含 后端: {"后端" in content}')
