import csv, sys
sys.stdout.reconfigure(encoding='utf-8')

# Fix remaining short definitions
definition_fixes = {
    '273': '形如y\'\'=f(x,y\')的二阶微分方程，不显含未知函数y。可通过令p=y\'将方程降阶为一阶微分方程p\'=f(x,p)求解。',
    '274': '形如y\'\'=f(y,y\')的二阶微分方程，不显含自变量x。可通过令p=y\'并将y视为自变量，利用链式法则将方程降阶求解。',
    '295': '由方程F(x,y,z)=0确定的隐函数z=f(x,y)的偏导数求解公式。利用偏导数公式∂z/∂x=-F_x/F_z，∂z/∂y=-F_y/F_z计算。',
    '296': '由单个方程F(x,y,z)=0确定隐函数z=f(x,y)的情形。需要满足F(x₀,y₀,z₀)=0且F_z≠0的条件。',
}

rows = []
with open('docs/params_csv/math_all.csv', 'r', encoding='utf-8-sig') as fh:
    reader = csv.DictReader(fh)
    fieldnames = reader.fieldnames
    for row in reader:
        node_id = row['node_id']
        if node_id in definition_fixes:
            old = row['definition']
            row['definition'] = definition_fixes[node_id]
            print(f'Fixed [{node_id}] {row["name"]}')
        rows.append(row)

with open('docs/params_csv/math_all.csv', 'w', encoding='utf-8-sig', newline='') as fh:
    writer = csv.DictWriter(fh, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print('Done!')
