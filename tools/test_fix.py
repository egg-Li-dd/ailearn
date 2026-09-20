import urllib.request, json

# 测试 archived=all
try:
    req = urllib.request.Request('http://127.0.0.1:8000/api/v1/courses?archived=all')
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
        print(f'archived=all → 成功，返回 {len(data)} 门课程:')
        for c in data:
            print(f'  id={c["id"]} {c["name"]}')
except urllib.error.HTTPError as e:
    print(f'archived=all → 失败: {e.code} {e.reason}')
    print(e.read().decode())

# 测试 schedule
try:
    req2 = urllib.request.Request('http://127.0.0.1:8000/api/v1/schedule')
    with urllib.request.urlopen(req2) as resp:
        data2 = json.loads(resp.read())
        print(f'\nschedule → 成功，返回 {len(data2)} 条课表')
except urllib.error.HTTPError as e:
    print(f'\nschedule → 失败: {e.code} {e.reason}')
