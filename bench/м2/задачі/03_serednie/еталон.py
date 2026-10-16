import csv
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
g = defaultdict(list)
for r in csv.DictReader(open('дані/оцінки.csv', encoding='utf-8')): g[r['студент']].append(int(r['бал']))
avg = {k: (Decimal(sum(v)) / len(v)).quantize(Decimal('0.1'), ROUND_HALF_UP) for k, v in g.items()}
for k in sorted(avg, key=lambda k: (-avg[k], k)): print(k, avg[k])
