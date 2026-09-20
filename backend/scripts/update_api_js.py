file_path = r'C:\creategame\AI学\admin\src\api.js'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 修改 aiChannels 支持参数
old = "  aiChannels: () => request('GET', '/ai/channels'),"
new = "  aiChannels: (params) => request('GET', `/ai/channels?${new URLSearchParams(params || {}).toString()}`),"

if old in content:
    content = content.replace(old, new)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('✓ api.js aiChannels 已支持参数')
else:
    print('✗ 未找到 aiChannels')
