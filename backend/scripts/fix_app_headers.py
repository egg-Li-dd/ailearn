file_path = r'C:\ailearn\app\lib\core\api.dart'
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找到 _headers 的起始行
start_idx = None
for i, line in enumerate(lines):
    if 'Map<String, String> get _headers' in line:
        start_idx = i
        break

if start_idx is None:
    print('未找到 _headers')
else:
    print(f'找到 _headers 在第 {start_idx+1} 行')
    # 找到结束行（包含 '};'）
    end_idx = start_idx
    for i in range(start_idx, len(lines)):
        if '};' in lines[i]:
            end_idx = i
            break
    print(f'结束行: {end_idx+1}')
    print(f'原内容（{start_idx+1}-{end_idx+1}行）:')
    for i in range(start_idx, end_idx+1):
        print(f'  {i+1}: {lines[i].rstrip()}')
    
    # 替换内容
    new_lines = [
        '  Map<String, String> get _headers {\n',
        '    final headers = <String, String>{\n',
        "      'Content-Type': 'application/json',\n",
        '    };\n',
        '    // Bearer token 优先（用户登录态），其次 Basic Auth（管理台认证）\n',
        '    if (token != null && token!.isNotEmpty) {\n',
        "      headers['Authorization'] = 'Bearer $token';\n",
        '    } else if (ApiConfig.basicAuth.isNotEmpty) {\n',
        "      headers['Authorization'] = 'Basic ${ApiConfig.basicAuth}';\n",
        '    }\n',
        '    return headers;\n',
        '  }\n',
    ]
    
    # 替换
    lines[start_idx:end_idx+1] = new_lines
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    
    print()
    print('替换成功！新内容:')
    for i in range(start_idx, start_idx+len(new_lines)):
        print(f'  {i+1}: {lines[i].rstrip()}')
