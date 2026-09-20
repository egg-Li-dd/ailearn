import csv, sys, sqlite3, requests
sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://localhost:8000/api/v1'

conn = sqlite3.connect('backend/data/ailearn.db')
cur = conn.cursor()

# Get all node IDs with notes
cur.execute("SELECT id FROM knowledge_nodes WHERE notes IS NOT NULL AND notes != ''")
imported = set(row[0] for row in cur.fetchall())

# Check each CSV and re-import missing nodes
files = [
    ('DS', 'ds_all.csv'),
    ('Math', 'math_all.csv'),
    ('Network', 'net_all.csv'),
]

for subj, f in files:
    csv_ids = set()
    all_rows = {}
    with open(f'docs/params_csv/{f}', 'r', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        for row in reader:
            nid = int(row['node_id'])
            csv_ids.add(nid)
            all_rows[nid] = row
    
    not_imported = csv_ids - imported
    print(f'{subj}: {len(not_imported)} nodes in CSV but not imported')
    
    if not_imported:
        # Filter rows
        filtered_rows = [all_rows[nid] for nid in not_imported if nid in all_rows]
        
        # Write filtered CSV
        filtered_file = f'docs/params_csv/reimport_{f}'
        with open(filtered_file, 'w', encoding='utf-8-sig', newline='') as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(filtered_rows)
        
        # Import
        with open(filtered_file, 'rb') as fp:
            files_data = {'file': (filtered_file.split('/')[-1], fp, 'text/csv')}
            resp = requests.post(f'{BASE}/knowledge/params/import', files=files_data, timeout=120)
        
        if resp.status_code == 200:
            result = resp.json()
            print(f'  成功: {result.get("updated", 0)}, 跳过: {result.get("skipped", 0)}, 错误: {len(result.get("errors", []))}')
            if result.get('errors'):
                for err in result['errors'][:5]:
                    print(f'    - {err}')
        else:
            print(f'  失败: {resp.status_code}')

conn.close()
print('\nDone!')
