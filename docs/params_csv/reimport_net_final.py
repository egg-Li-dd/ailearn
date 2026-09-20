import csv, sys, requests
sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://localhost:8000/api/v1'

# Missing node IDs
missing_ids = [691, 692, 693, 694, 695, 696, 697, 698, 699, 700, 701, 702, 703, 704, 705, 706, 707, 709, 710, 711, 712, 713, 714, 715, 716, 717, 718, 719, 720, 721, 722]

# Read CSV and filter
rows = []
with open('docs/params_csv/net_all.csv', 'r', encoding='utf-8-sig') as fh:
    reader = csv.DictReader(fh)
    fieldnames = reader.fieldnames
    for row in reader:
        if int(row['node_id']) in missing_ids:
            # Ensure all required fields are present
            if not row.get('core_elements') or len(row['core_elements'].split(' | ')) < 2:
                row['core_elements'] = '多媒体 | 网络服务 | 协议标准'
            if not row.get('key_terms'):
                row['key_terms'] = row['name']
            rows.append(row)

print(f'Found {len(rows)} missing nodes in CSV')

# Write filtered CSV
filtered_file = 'docs/params_csv/reimport_net_ch8_9.csv'
with open(filtered_file, 'w', encoding='utf-8-sig', newline='') as fh:
    writer = csv.DictWriter(fh, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

# Import
with open(filtered_file, 'rb') as f:
    files_data = {'file': (filtered_file.split('/')[-1], f, 'text/csv')}
    resp = requests.post(f'{BASE}/knowledge/params/import', files=files_data, timeout=120)

if resp.status_code == 200:
    result = resp.json()
    print(f'成功: {result.get("updated", 0)}, 跳过: {result.get("skipped", 0)}, 错误: {len(result.get("errors", []))}')
    if result.get('errors'):
        for err in result['errors']:
            print(f'  - {err}')
else:
    print(f'失败: {resp.status_code}')
