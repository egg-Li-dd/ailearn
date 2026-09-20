import csv, sys, re
sys.stdout.reconfigure(encoding='utf-8')

files = [
    ('DS', 'ds_all.csv'),
    ('Math', 'math_all.csv'),
    ('Network', 'net_all.csv'),
]

# Fix mappings for short/prerequisite scope_boundary
fixes = {
    # Data Structures
    '6': '不涉及算法的时间复杂度分析和空间复杂度分析；不涉及具体算法的实现代码',
    '21': '不涉及栈的顺序存储和链式存储的具体实现；不涉及栈的应用场景',
    '41': '从主串的指定位置开始查找子串首次出现的位置，返回位序号或0',
    '80': '不涉及具体存储结构的实现细节；不涉及图的遍历算法',
    '81': '不涉及邻接表和十字链表等其他存储方式；不涉及图的遍历',
    
    # Math
    '166': '不涉及函数极限的性质；不涉及子列收敛性',
    '167': '不涉及多元函数的极限；不涉及左极限和右极限的详细讨论',
    '177': '不涉及一致连续性的判定；不涉及间断点的分类',
    '185': '不涉及介值定理的证明；不涉及函数零点的求解方法',
    '189': '不涉及导数的计算法则；不涉及高阶导数',
    
    # Network - convert prerequisites to proper boundaries
    '504': '不涉及具体网络协议的实现细节；不涉及网络硬件设备',
    '506': '不涉及路由器的具体工作原理；不涉及路由选择算法',
    '508': '不涉及网络协议的具体实现；不涉及网络性能指标的计算',
    '510': '不涉及各类网络的具体协议；不涉及网络设备的选型',
    '511': '不涉及具体协议的性能分析；不涉及网络优化方法',
}

fixed_count = 0

for subj, f in files:
    rows = []
    with open(f'docs/params_csv/{f}', 'r', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        for row in reader:
            node_id = row['node_id']
            
            # Check if this node needs fixing
            scope = row['scope_boundary']
            needs_fix = False
            
            if len(scope) < 10:
                needs_fix = True
            if scope.startswith('需掌握') or scope.startswith('需要'):
                needs_fix = True
            
            if needs_fix:
                if node_id in fixes:
                    row['scope_boundary'] = fixes[node_id]
                    fixed_count += 1
                    print(f'Fixed [{node_id}] {row["name"]}')
                else:
                    # Generate a generic fix based on the name
                    name = row['name']
                    row['scope_boundary'] = f'不涉及{name}的具体实现细节和扩展应用'
                    fixed_count += 1
                    print(f'Auto-fixed [{node_id}] {row["name"]}')
            
            rows.append(row)
    
    # Write back
    with open(f'docs/params_csv/{f}', 'w', encoding='utf-8-sig', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

print(f'\nTotal fixed: {fixed_count}')
