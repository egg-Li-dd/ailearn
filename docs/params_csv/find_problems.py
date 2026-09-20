import csv, sys
sys.stdout.reconfigure(encoding='utf-8')

files = [
    ('DS', 'ds_all.csv'),
    ('Math', 'math_all.csv'),
    ('Network', 'net_all.csv'),
    ('OS', 'os_all.csv'),
    ('Org', 'org_all.csv'),
]

problems = []

for subj, f in files:
    with open(f'docs/params_csv/{f}', 'r', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            node_id = row['node_id']
            name = row['name']
            defn = row['definition']
            scope = row['scope_boundary']
            
            issues = []
            
            # Check definition length
            if len(defn) < 20:
                issues.append(f'definition too short ({len(defn)} chars)')
            
            # Check if definition ends abruptly (no punctuation)
            if defn and not defn.endswith(('。', '）', ')', '…', '"', '"')):
                if not defn.endswith(('...', '…')):
                    issues.append(f'definition may be incomplete')
            
            # Check scope_boundary
            if len(scope) < 10:
                issues.append(f'scope_boundary too short ({len(scope)} chars)')
            
            # Check if scope_boundary looks like a formula or incomplete
            if scope and (scope.endswith('dy') or scope.endswith('dx') or 
                         scope.endswith(')...') or scope.endswith('…')):
                issues.append(f'scope_boundary may be incomplete/formula')
            
            # Check if scope_boundary is just a prerequisite
            if scope.startswith('需掌握') or scope.startswith('需要'):
                issues.append(f'scope_boundary is prerequisite, not boundary')
            
            if issues:
                problems.append({
                    'subj': subj,
                    'id': node_id,
                    'name': name,
                    'issues': issues,
                    'defn': defn[:50],
                    'scope': scope[:50],
                })

print(f'Total problems found: {len(problems)}')
print()

# Group by subject
from collections import defaultdict
by_subj = defaultdict(list)
for p in problems:
    by_subj[p['subj']].append(p)

for subj in ['DS', 'Math', 'Network', 'OS', 'Org']:
    probs = by_subj.get(subj, [])
    if probs:
        print(f'\n=== {subj} ({len(probs)} problems) ===')
        for p in probs[:10]:  # Show first 10
            print(f"  [{p['id']}] {p['name']}")
            for issue in p['issues']:
                print(f"    - {issue}")
