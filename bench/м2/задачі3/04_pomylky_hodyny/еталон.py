import re
from collections import Counter, defaultdict
hours, mods = defaultdict(list), Counter()
for line in open('дані/app.log', encoding='utf-8'):
    m = re.match(r'\S+ (\d\d):\d\d:\d\d \[(\w+)\] (\w+):', line)
    if m and m.group(2) == 'ERROR':
        hours[m.group(1)].append(m.group(3))
        mods[m.group(3)] += 1
for h in sorted(hours):
    print(f"{h}:00 — {len(hours[h])} ({', '.join(sorted(set(hours[h])))})")
best = sorted(mods.items(), key=lambda kv: (-kv[1], kv[0]))[0]
print(f'Найгірший модуль: {best[0]} ({best[1]})')
