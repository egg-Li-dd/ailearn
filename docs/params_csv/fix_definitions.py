import csv, sys
sys.stdout.reconfigure(encoding='utf-8')

# Fix short definitions
definition_fixes = {
    # Data Structures
    '41': '从主串S的第pos个字符起查找子串T首次出现的位置，若找到则返回位序号，否则返回0。朴素算法通过逐字符比较实现，最坏时间复杂度为O(n*m)。',
    
    # Math
    '199': '对方程F(x,y)=0两边关于x求导，将y视为x的函数，解出y对x的导数。隐函数求导的关键是正确应用链式法则。',
    '209': '若函数f(x)在闭区间[a,b]上连续，在开区间(a,b)内可导，且f(a)=f(b)，则至少存在一点ξ∈(a,b)使得f\'(ξ)=0。罗尔定理是拉格朗日中值定理的特殊情况。',
    '210': '若函数f(x)在闭区间[a,b]上连续，在开区间(a,b)内可导，则至少存在一点ξ∈(a,b)使得f(b)-f(a)=f\'(ξ)(b-a)。拉格朗日中值定理建立了函数增量与导数之间的联系。',
    '211': '若函数f(x)和g(x)在闭区间[a,b]上连续，在开区间(a,b)内可导，且g\'(x)≠0，则至少存在一点ξ∈(a,b)使得[f(b)-f(a)]/[g(b)-g(a)]=f\'(ξ)/g\'(ξ)。',
    '259': '利用定积分计算平面曲线的弧长。对曲线y=f(x)在[a,b]上的弧长公式为∫√(1+[f\'(x)]²)dx，参数方程形式为∫√([x\'(t)]²+[y\'(t)]²)dt。',
}

for subj, f in [('DS', 'ds_all.csv'), ('Math', 'math_all.csv')]:
    rows = []
    with open(f'docs/params_csv/{f}', 'r', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        for row in reader:
            node_id = row['node_id']
            if node_id in definition_fixes:
                old = row['definition']
                row['definition'] = definition_fixes[node_id]
                print(f'Fixed [{node_id}] {row["name"]}')
                print(f'  Old: {old[:30]}...')
                print(f'  New: {row["definition"][:50]}...')
            rows.append(row)
    
    with open(f'docs/params_csv/{f}', 'w', encoding='utf-8-sig', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

print('\nDone!')
