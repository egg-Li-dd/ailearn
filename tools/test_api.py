import urllib.request, json

# 测试列表API
req = urllib.request.Request('http://127.0.0.1:8000/api/v1/schedule')
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read())
print(f'列表API返回: {len(data)} 条')
for x in data[:5]:
    wd = x['weekday']
    st = x['start_time']
    et = x['end_time']
    cid = x['course_id']
    act = x['is_active']
    print(f'  weekday={wd} {st}-{et} course_id={cid} active={act}')

# 测试网格API
req2 = urllib.request.Request('http://127.0.0.1:8000/api/v1/schedule/grid')
with urllib.request.urlopen(req2) as resp:
    grid_data = json.loads(resp.read())
print(f'\n网格API time_slots: {grid_data.get("time_slots", [])}')
grid = grid_data.get('grid', {})
print(f'有数据的星期key: {list(grid.keys())}')
for wd, times in grid.items():
    print(f'  周{wd}: {len(times)}个时段')
