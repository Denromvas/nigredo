import json
from decimal import Decimal, ROUND_HALF_UP
z = json.load(open('дані/замовлення.json', encoding='utf-8'), parse_float=Decimal)
codes = json.load(open('дані/коди.json', encoding='utf-8'))
s = {}
for o in z:
    d = codes.get(o['код'], 0) if o['код'] is not None else 0
    for p in o['позиції']:
        v = (p['ціна'] * p['кількість'] * (100 - d) / 100).quantize(Decimal('0.01'), ROUND_HALF_UP)
        s[p['категорія']] = s.get(p['категорія'], Decimal(0)) + v
for k in sorted(s, key=lambda k: (-s[k], k)):
    print(f'{k}: {s[k]:.2f}')
