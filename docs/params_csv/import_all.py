import requests
import sys
sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://localhost:8000/api/v1'

files = [
    ('数据结构', 'docs/params_csv/ds_all.csv'),
    ('高数二', 'docs/params_csv/math_all.csv'),
    ('计算机网络', 'docs/params_csv/net_all.csv'),
    ('操作系统', 'docs/params_csv/os_all.csv'),
    ('计算机组成原理', 'docs/params_csv/org_all.csv'),
]

for subj_name, filepath in files:
    print(f'\n=== 导入 {subj_name} ===')
    try:
        with open(filepath, 'rb') as f:
            files_data = {'file': (filepath.split('/')[-1], f, 'text/csv')}
            resp = requests.post(f'{BASE}/knowledge/params/import', files=files_data, timeout=120)
        
        if resp.status_code == 200:
            result = resp.json()
            print(f'  成功: {result.get("updated", 0)} 个')
            print(f'  跳过: {result.get("skipped", 0)} 个')
            if result.get('errors'):
                print(f'  错误: {len(result["errors"])} 个')
                for err in result['errors'][:3]:
                    print(f'    - {err}')
        else:
            print(f'  失败: {resp.status_code} - {resp.text[:100]}')
    except Exception as e:
        print(f'  异常: {e}')

print('\n=== 导入完成 ===')
