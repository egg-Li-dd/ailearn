import csv, sys, requests
sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://localhost:8000/api/v1'

# Comprehensive fixes for all failing nodes
all_fixes = {
    'ds_all.csv': {
        '98': {'core_elements': 'Floyd算法 | 动态规划 | 多源最短路径 | 距离矩阵'},
        '100': {'core_elements': '内存分配 | 内存回收 | 动态分区'},
        '101': {'core_elements': '可利用空间表 | 首次适应 | 最佳适应 | 最差适应'},
        '102': {'core_elements': '边界标识 | 头部和尾部 | 分配和回收'},
        '103': {'core_elements': '空闲块链表 | 分配策略 | 碎片整理'},
        '104': {'core_elements': '分配算法 | 首次适应 | 最佳适应'},
        '105': {'core_elements': '回收算法 | 空闲块合并 | 边界检查'},
        '106': {'core_elements': '伙伴系统 | 二分法 | 合并策略'},
        '107': {'core_elements': '伙伴系统空间表 | 块大小 | 分配回收'},
        '108': {'core_elements': '伙伴系统分配 | 查找空闲块 | 分裂'},
        '109': {'core_elements': '伙伴系统回收 | 空闲块合并 | 伙伴检测'},
        '110': {'core_elements': '垃圾回收 | 标记清除 | 引用计数'},
        '111': {'core_elements': '存储紧缩 | 碎片整理 | 内存压缩'},
        '112': {'core_elements': '查找表 | 关键字 | 查找效率'},
        '113': {'core_elements': '静态查找 | 顺序表 | 有序表'},
        '114': {'core_elements': '顺序查找 | 从头到尾 | O(n)'},
        '115': {'core_elements': '折半查找 | 二分法 | O(log n)'},
        '116': {'core_elements': '静态树表 | 查找概率 | 加权平均'},
        '117': {'core_elements': '索引顺序表 | 分块查找 | 索引表'},
        '118': {'core_elements': '动态查找 | 插入删除 | 树形结构'},
        '119': {'core_elements': '二叉排序树 | 平衡因子 | AVL树'},
        '120': {'core_elements': 'B树 | 多路平衡 | 磁盘存储'},
        '121': {'core_elements': '键树 | 数字查找树 | 前缀'},
        '122': {'core_elements': '哈希表 | 散列 | 直接定址'},
        '123': {'core_elements': '哈希函数 | 地址映射 | 冲突'},
        '124': {'core_elements': '除留余数法 | 直接定址法 | 数字分析法'},
        '125': {'core_elements': '开放定址法 | 链地址法 | 冲突处理'},
        '126': {'core_elements': '查找效率 | 装填因子 | ASL'},
    },
    'math_all.csv': {
        '225': {'core_elements': '原函数 | 不定积分 | 积分常数'},
        '226': {'core_elements': '原函数定义 | 不定积分定义 | 基本积分表'},
    },
    'net_all.csv': {
        '646': {'key_terms': '电子邮件 | SMTP | POP3 | IMAP', 'core_elements': '用户代理 | 邮件服务器 | SMTP | POP3 | IMAP'},
        '647': {'key_terms': '电子邮件 | 邮件系统 | 邮件格式', 'core_elements': '用户代理 | 邮件服务器 | 邮件格式'},
        '648': {'key_terms': 'SMTP | 简单邮件传送协议 | 邮件发送', 'core_elements': 'SMTP协议 | 邮件发送 | 端口25'},
        '649': {'key_terms': '邮件格式 | MIME | 邮件头 | 邮件体', 'core_elements': '邮件头 | 邮件体 | MIME编码'},
        '650': {'key_terms': 'POP3 | IMAP | 邮件读取', 'core_elements': 'POP3协议 | IMAP协议 | 邮件下载'},
        '651': {'key_terms': 'Web邮件 | 浏览器 | 邮件访问', 'core_elements': 'Web界面 | HTTP访问 | 邮件管理'},
        '652': {'key_terms': 'MIME | 多用途网际邮件扩充 | 编码', 'core_elements': 'MIME标准 | 非文本编码 | 邮件扩展'},
        '653': {'key_terms': 'DHCP | 动态主机配置 | IP分配', 'core_elements': 'IP地址分配 | 自动配置 | UDP'},
        '654': {'key_terms': 'SNMP | 网络管理 | 管理站', 'core_elements': '网络管理 | SNMP协议 | 管理信息库'},
        '655': {'key_terms': '网络管理 | 管理站 | 代理', 'core_elements': '网络管理概念 | 管理站 | 代理'},
        '656': {'key_terms': 'SMI | 管理信息结构 | ASN.1', 'core_elements': 'SMI标准 | ASN.1 | MIB定义'},
        '657': {'key_terms': 'MIB | 管理信息库 | 对象标识', 'core_elements': 'MIB树 | 对象标识符 | 被管理对象'},
        '658': {'key_terms': 'SNMP报文 | PDU | 团体名', 'core_elements': 'SNMP报文格式 | PDU类型 | 传输'},
        '659': {'key_terms': '套接字 | 系统调用 | 应用编程接口', 'core_elements': '套接字API | 系统调用 | 网络编程'},
        '660': {'key_terms': '系统调用 | socket | bind | listen', 'core_elements': 'socket函数 | bind函数 | listen函数'},
        '661': {'key_terms': 'connect | accept | send | recv', 'core_elements': '连接建立 | 数据传输 | 连接关闭'},
        '662': {'key_terms': 'P2P | 对等网络 | 文件共享', 'core_elements': 'P2P架构 | 对等方 | 文件分发'},
        '663': {'key_terms': 'Napster | 集中目录 | P2P', 'core_elements': '集中目录服务器 | 文件索引 | 对等方注册'},
        '664': {'key_terms': 'BitTorrent | 分布式P2P | 洪泛', 'core_elements': '分布式哈希表 | 洪泛查询 | 文件分块'},
        '665': {'key_terms': 'P2P分析 | 下载时间 | 对等方数量', 'core_elements': '分发时间分析 | 最小时间 | 瓶颈'},
        '666': {'key_terms': 'DHT | 分布式哈希表 | 对象搜索', 'core_elements': '分布式哈希表 | 覆盖网络 | 对象定位'},
        '667': {'key_terms': '网络安全 | 威胁 | 防护', 'core_elements': '安全威胁 | 加密技术 | 认证机制'},
        '668': {'key_terms': '安全威胁 | 被动攻击 | 主动攻击', 'core_elements': '窃听 | 篡改 | 伪造'},
        '669': {'key_terms': '安全目标 | 机密性 | 完整性 | 可用性', 'core_elements': '机密性 | 完整性 | 可用性'},
        '670': {'key_terms': '安全网络 | 安全服务 | 安全机制', 'core_elements': '安全服务 | 安全机制 | 安全策略'},
        '671': {'key_terms': '加密模型 | 明文 | 密文 | 密钥', 'core_elements': '明文 | 密文 | 加密算法 | 解密算法'},
        '672': {'key_terms': '对称加密 | 公钥加密 | 密码体制', 'core_elements': '对称密钥 | 公钥密码 | 混合加密'},
        '673': {'key_terms': 'DES | AES | 对称密钥', 'core_elements': '共享密钥 | DES | AES | 3DES'},
        '674': {'key_terms': 'RSA | 公钥 | 私钥', 'core_elements': '公钥加密 | 私钥解密 | 数字签名'},
        '675': {'key_terms': '数字签名 | 签名验证 | 完整性', 'core_elements': '发送者签名 | 接收者验证 | 抗抵赖'},
        '676': {'key_terms': '鉴别 | 报文鉴别 | 实体鉴别', 'core_elements': '报文摘要 | 数字签名 | 身份验证'},
        '677': {'key_terms': '报文鉴别 | 散列函数 | HMAC', 'core_elements': '报文摘要 | 散列函数 | 完整性校验'},
        '678': {'key_terms': '实体鉴别 | 身份验证 | 挑战响应', 'core_elements': '身份验证 | 挑战响应协议'},
        '679': {'key_terms': '密钥分配 | KDC | 证书', 'core_elements': '密钥分发中心 | 数字证书 | 密钥管理'},
        '680': {'key_terms': '对称密钥分配 | KDC | 会话密钥', 'core_elements': '密钥分发中心 | 会话密钥 | 安全分发'},
        '681': {'key_terms': '公钥分配 | 数字证书 | CA', 'core_elements': '证书颁发机构 | 公钥证书 | 信任链'},
        '682': {'key_terms': 'IPSec | SSL/TLS | PGP', 'core_elements': '网络层安全 | 运输层安全 | 应用层安全'},
        '683': {'key_terms': 'IPSec | AH | ESP', 'core_elements': '认证头 | 封装安全载荷 | 隧道模式'},
        '684': {'key_terms': 'SSL | TLS | HTTPS', 'core_elements': 'SSL协议 | TLS协议 | 安全HTTP'},
        '685': {'key_terms': 'PGP | S/MIME | 安全电子邮件', 'core_elements': '电子邮件加密 | 邮件签名'},
        '686': {'key_terms': '防火墙 | 入侵检测 | 网络安全', 'core_elements': '包过滤 | 应用网关 | 入侵检测'},
        '687': {'key_terms': '防火墙 | 包过滤 | 状态检测', 'core_elements': '访问控制 | 规则匹配 | 流量过滤'},
        '688': {'key_terms': 'IDS | 入侵检测 | 异常检测', 'core_elements': '入侵检测系统 | 特征检测 | 异常检测'},
        '689': {'key_terms': '未来方向 | 量子加密 | 区块链', 'core_elements': '量子密码 | 区块链安全'},
    },
}

for csv_file, node_fixes in all_fixes.items():
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

# Re-import all fixed nodes
for csv_file, node_fixes in all_fixes.items():
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
    
    filtered_file = f'docs/params_csv/reimport_final_{csv_file}'
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
            for err in result['errors'][:5]:
                print(f'    - {err}')
    else:
        print(f'  失败: {resp.status_code}')

print('\nDone!')
