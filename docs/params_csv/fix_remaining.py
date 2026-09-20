import csv, sys, requests
sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://localhost:8000/api/v1'

# Fix remaining issues
fixes = {
    'ds_all.csv': {
        '41': {'core_elements': '逐字符比较 | 回溯 | 位置定位 | 最坏复杂度O(n*m)'},
    },
    'net_all.csv': {
        '628': {'key_terms': '应用层 | DNS | HTTP | SMTP | FTP', 'core_elements': '应用层协议 | DNS | HTTP | SMTP | FTP | 客户服务器'},
        '629': {'key_terms': 'DNS | 域名解析 | 域名服务器', 'core_elements': '域名解析 | 分布式数据库 | 递归查询 | 迭代查询'},
        '630': {'key_terms': '域名 | IP地址 | 映射', 'core_elements': '域名到IP映射 | 分布式数据库 | 层次化查询'},
        '631': {'key_terms': '域名结构 | 顶级域名 | 二级域名', 'core_elements': '层次命名 | 域名标号 | 顶级域名 | 二级域名'},
        '632': {'key_terms': '根域名服务器 | 权威服务器 | 本地服务器', 'core_elements': '根域名服务器 | 权威域名服务器 | 本地域名服务器'},
        '633': {'key_terms': 'FTP | 控制连接 | 数据连接', 'core_elements': '文件传输 | 控制连接 | 数据连接 | 客户服务器'},
        '634': {'key_terms': 'FTP | 主进程 | 子进程', 'core_elements': '文件传输协议 | 交互式 | 控制连接 | 数据连接'},
        '635': {'key_terms': 'FTP工作原理 | 控制连接 | 数据连接', 'core_elements': '主进程 | 子进程 | 控制连接 | 数据连接'},
        '636': {'key_terms': 'TFTP | UDP | 简单文件传输', 'core_elements': '简单文件传输 | UDP | TFTP'},
        '637': {'key_terms': 'TELNET | 远程登录 | NVT', 'core_elements': '远程登录 | 仿真终端 | NVT'},
        '638': {'key_terms': 'WWW | HTTP | URL | 超文本', 'core_elements': '万维网 | 超文本 | HTTP | URL'},
        '639': {'key_terms': '万维网 | 浏览器 | 服务器', 'core_elements': '客户服务器 | 超文本链接 | 浏览器'},
        '640': {'key_terms': 'URL | 协议 | 主机 | 路径', 'core_elements': 'URL格式 | 协议 | 主机 | 路径'},
        '641': {'key_terms': 'HTTP | 请求响应 | 持久连接', 'core_elements': '请求响应 | 非状态 | 持久连接 | 非持久连接'},
        '642': {'key_terms': 'HTML | CSS | JavaScript', 'core_elements': 'HTML | CSS | JavaScript | 静态文档 | 动态文档'},
        '643': {'key_terms': '搜索引擎 | 爬虫 | 索引', 'core_elements': '搜索引擎 | 爬虫 | 索引 | 排名'},
        '644': {'key_terms': '博客 | RSS | 订阅', 'core_elements': '博客 | RSS | 订阅'},
        '645': {'key_terms': '社交网络 | 好友关系 | 信息流', 'core_elements': '社交网络 | 好友关系 | 信息流'},
    },
}

for csv_file, node_fixes in fixes.items():
    filepath = f'docs/params_csv/{csv_file}'
    rows = []
    
    with open(filepath, 'r', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        for row in reader:
            node_id = row['node_id']
            if node_id in node_fixes:
                for key, value in node_fixes[node_id].items():
                    row[key] = value
            rows.append(row)
    
    with open(filepath, 'w', encoding='utf-8-sig', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

# Re-import
for csv_file, node_fixes in fixes.items():
    filepath = f'docs/params_csv/{csv_file}'
    node_ids = [int(nid) for nid in node_fixes.keys()]
    
    print(f'\nRe-importing from {csv_file}...')
    
    filtered_rows = []
    with open(filepath, 'r', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        for row in reader:
            if int(row['node_id']) in node_ids:
                filtered_rows.append(row)
    
    filtered_file = f'docs/params_csv/filtered2_{csv_file}'
    with open(filtered_file, 'w', encoding='utf-8-sig', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(filtered_rows)
    
    with open(filtered_file, 'rb') as f:
        files_data = {'file': (filtered_file.split('/')[-1], f, 'text/csv')}
        resp = requests.post(f'{BASE}/knowledge/params/import', files=files_data, timeout=120)
    
    if resp.status_code == 200:
        result = resp.json()
        print(f'  成功: {result.get("updated", 0)}, 跳过: {result.get("skipped", 0)}, 错误: {len(result.get("errors", []))}')
        if result.get('errors'):
            for err in result['errors']:
                print(f'    - {err}')
    else:
        print(f'  失败: {resp.status_code}')

print('\nDone!')
