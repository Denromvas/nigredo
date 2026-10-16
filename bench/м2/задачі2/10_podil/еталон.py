import json
from decimal import Decimal, ROUND_FLOOR
p = json.load(open('дані/поділ.json', encoding='utf-8'))
total, w = Decimal(p['сума']), p['ваги']
W = sum(w.values())
exact = {k: total * v / W for k, v in w.items()}
part = {k: e.quantize(Decimal('0.01'), ROUND_FLOOR) for k, e in exact.items()}
left = int((total - sum(part.values())) * 100)
for k in sorted(w, key=lambda k: (-(exact[k] - part[k]), k))[:left]:
    part[k] += Decimal('0.01')
for k in sorted(part):
    print(f'{k}: {part[k]:.2f}')
