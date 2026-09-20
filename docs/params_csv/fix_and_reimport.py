import csv, sys, requests
sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://localhost:8000/api/v1'

# Nodes that failed due to core_elements < 2
failed_nodes = {
    'ds_all.csv': [41, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97],
    'math_all.csv': [199, 209, 210, 211, 259, 273, 274, 295, 296, 300],
    'net_all.csv': [557, 560, 628, 629, 630, 631, 632, 633, 634, 635, 636, 637, 638, 639, 640, 641, 642, 643, 644, 645],
    'org_all.csv': [344],
}

# Additional core_elements for these nodes
core_elements_fixes = {
    # Data Structures - Graph chapter
    '79': '顶点和边 | 有向图和无向图 | 完全图 | 权',
    '80': '邻接矩阵 | 邻接表 | 十字链表 | 邻接多重表',
    '81': '二维数组 | 空间复杂度O(n²) | 适合稠密图',
    '82': '链表结构 | 空间复杂度O(n+e) | 适合稀疏图',
    '83': '有向图优化 | 弧链表 | 入度出度',
    '84': '无向图优化 | 边链表 | 边节点',
    '85': '深度优先和广度优先 | 访问标记 | 时间复杂度',
    '86': '递归栈 | 邻接顶点 | 回溯 | 访问标记',
    '87': '队列 | 邻接顶点 | 逐层访问',
    '88': '连通分量 | 生成树 | 最小生成树',
    '89': '生成树 | 连通分量 | DFS或BFS',
    '90': '强连通分量 | 有向图 | 缩点',
    '91': 'Prim算法 | Kruskal算法 | 贪心策略',
    '92': '割点 | 桥 | 连通度',
    '93': '有向无环图 | 拓扑排序 | 关键路径',
    '94': '入度为零 | 删除入度为零的顶点 | 检测环',
    '95': 'AOE网 | 关键路径 | 最长路径',
    '96': 'Dijkstra算法 | Floyd算法 | 贪心',
    '97': 'Dijkstra算法 | 单源最短路径 | 贪心',
    '98': 'Floyd算法 | 动态规划 | 多源最短路径',
    
    # Math
    '199': '隐函数求导 | 链式法则 | 方程两边求导',
    '209': '闭区间连续 | 开区间可导 | 端点值相等',
    '210': '闭区间连续 | 开区间可导 | 拉格朗日中值',
    '211': '两个函数 | 柯西中值 | 导数之比',
    '259': '弧长公式 | 参数方程 | 微分元素',
    '273': '不显含y | 降阶法 | 令p=y\'',
    '274': '不显含x | 降阶法 | 链式法则',
    '295': '隐函数求导 | 偏导数公式 | F_z≠0',
    '296': '单个方程 | 隐函数存在条件 | 偏导数',
    '300': '条件极值 | 拉格朗日乘数法 | 辅助函数',
    
    # Network
    '557': '100Mbps | 快速以太网 | 802.3u',
    '560': '以太网接入 | PPPoE | HFC',
    '628': '应用层协议 | DNS | HTTP | SMTP | FTP',
    '629': '域名解析 | 分布式数据库 | 递归查询 | 迭代查询',
    '630': '域名到IP映射 | 分布式数据库 | 层次化查询',
    '631': '层次命名 | 域名标号 | 顶级域名 | 二级域名',
    '632': '根域名服务器 | 权威域名服务器 | 本地域名服务器',
    '633': '文件传输 | 控制连接 | 数据连接 | 客户服务器',
    '634': '文件传输协议 | 交互式 | 控制连接 | 数据连接',
    '635': '主进程 | 子进程 | 控制连接 | 数据连接',
    '636': '简单文件传输 | UDP | TFTP',
    '637': '远程登录 | 仿真终端 | NVT',
    '638': '万维网 | 超文本 | HTTP | URL',
    '639': '客户服务器 | 超文本链接 | 浏览器',
    '640': 'URL格式 | 协议 | 主机 | 路径',
    '641': '请求响应 | 非状态 | 持久连接 | 非持久连接',
    '642': 'HTML | CSS | JavaScript | 静态文档 | 动态文档',
    '643': '搜索引擎 | 爬虫 | 索引 | 排名',
    '644': '博客 | RSS | 订阅',
    '645': '社交网络 | 好友关系 | 信息流',
    
    # Organization
    '344': '电气特性 | 机械特性 | 功能特性 | 时间特性',
}

fixed_count = 0

for csv_file, node_ids in failed_nodes.items():
    filepath = f'docs/params_csv/{csv_file}'
    rows = []
    
    with open(filepath, 'r', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        for row in reader:
            node_id = row['node_id']
            if int(node_id) in node_ids:
                # Fix core_elements
                if node_id in core_elements_fixes:
                    row['core_elements'] = core_elements_fixes[node_id]
                    fixed_count += 1
            rows.append(row)
    
    with open(filepath, 'w', encoding='utf-8-sig', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

print(f'Fixed {fixed_count} nodes')

# Re-import failed nodes
for csv_file, node_ids in failed_nodes.items():
    filepath = f'docs/params_csv/{csv_file}'
    print(f'\nRe-importing from {csv_file}...')
    
    # Filter rows to only include failed nodes
    filtered_rows = []
    with open(filepath, 'r', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        for row in reader:
            if int(row['node_id']) in node_ids:
                filtered_rows.append(row)
    
    # Write filtered CSV
    filtered_file = f'docs/params_csv/filtered_{csv_file}'
    with open(filtered_file, 'w', encoding='utf-8-sig', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(filtered_rows)
    
    # Import
    with open(filtered_file, 'rb') as f:
        files_data = {'file': (filtered_file.split('/')[-1], f, 'text/csv')}
        resp = requests.post(f'{BASE}/knowledge/params/import', files=files_data, timeout=120)
    
    if resp.status_code == 200:
        result = resp.json()
        print(f'  成功: {result.get("updated", 0)}, 跳过: {result.get("skipped", 0)}, 错误: {len(result.get("errors", []))}')
        if result.get('errors'):
            for err in result['errors'][:3]:
                print(f'    - {err}')
    else:
        print(f'  失败: {resp.status_code}')

print('\nDone!')
