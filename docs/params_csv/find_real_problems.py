import csv, sys
sys.stdout.reconfigure(encoding='utf-8')

files = [
    ('DS', 'ds_all.csv'),
    ('Math', 'math_all.csv'),
    ('Network', 'net_all.csv'),
    ('OS', 'os_all.csv'),
    ('Org', 'org_all.csv'),
]

real_problems = []

for subj, f in files:
    with open(f'docs/params_csv/{f}', 'r', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            node_id = row['node_id']
            name = row['name']
            defn = row['definition']
            scope = row['scope_boundary']
            
            issues = []
            
            # Real issue: scope_boundary too short (< 10 chars)
            if len(scope) < 10:
                issues.append(f'scope_boundary too short ({len(scope)} chars): "{scope}"')
            
            # Real issue: scope_boundary is prerequisite
            if scope.startswith('需掌握') or scope.startswith('需要'):
                issues.append(f'scope_boundary is prerequisite: "{scope}"')
            
            # Real issue: definition too short (< 15 chars)
            if len(defn) < 15:
                issues.append(f'definition too short ({len(defn)} chars): "{defn}"')
            
            if issues:
                real_problems.append({
                    'subj': subj,
                    'id': node_id,
                    'name': name,
                    'issues': issues,
                })

print(f'Real problems found: {len(real_problems)}')
print()

# Group by subject
from collections import defaultdict
by_subj = defaultdict(list)
for p in real_problems:
    by_subj[p['subj']].append(p)

for subj in ['DS', 'Math', 'Network', 'OS', 'Org']:
    probs = by_subj.get(subj, [])
    print(f'{subj}: {len(probs)} problems')
    for p in probs[:5]:
        print(f"  [{p['id']}] {p['name']}")
        for issue in p['issues']:
            print(f"    - {issue}")
