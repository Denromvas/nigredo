import json
from collections import defaultdict
d = json.load(open('дані/замовлення.json', encoding='utf-8'))
g = defaultdict(int)
for r in d:
    g[r['місто']] += r['кількість'] * r['ціна']
for k in sorted(g):
    print(k, g[k])
