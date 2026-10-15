import json
from collections import defaultdict
s = defaultdict(float)
for o in json.load(open('../../дані/замовлення.json', encoding='utf-8')):
    s[o['категорія']] += o['сума']
for k, v in sorted(s.items(), key=lambda kv: -kv[1]):
    print(f'{k}: {v:.2f}')
