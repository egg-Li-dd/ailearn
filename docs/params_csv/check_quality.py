import csv, sys
sys.stdout.reconfigure(encoding='utf-8')

samples = {
    'DS': ('ds_all.csv', [2, 19, 62, 86, 130]),
    'Math': ('math_all.csv', [161, 189, 231, 293, 306]),
    'Network': ('net_all.csv', [499, 565, 607, 641, 673]),
    'OS': ('os_all.csv', [725, 746, 764, 783, 825]),
    'Org': ('org_all.csv', [314, 356, 414, 459, 491]),
}

for subj, (f, ids) in samples.items():
    print(f'\n=== {subj} ===')
    with open(f'docs/params_csv/{f}', 'r', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if int(row['node_id']) in ids:
                print(f"[{row['node_id']}] {row['name']}")
                print(f"  definition: {row['definition'][:80]}...")
                print(f"  core_elements: {row['core_elements'][:60]}...")
                print(f"  scope_boundary: {row['scope_boundary'][:60]}...")
                print()
