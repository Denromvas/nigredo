import json
from collections import Counter
s = json.load(open('дані/склад.json', encoding='utf-8'))
z = Counter()
for o in json.load(open('дані/замовлення.json', encoding='utf-8')): z[o['товар']] += o['кількість']
for t in sorted(z):
    if z[t] > s.get(t, 0): print(f'{t}: бракує {z[t] - s.get(t, 0)}')
