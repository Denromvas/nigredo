import csv
from decimal import Decimal
g = {}
for r in csv.DictReader(open('дані/виміри.csv', encoding='utf-8')):
    g.setdefault(r['датчик'], [])
    if r['значення'].strip():
        g[r['датчик']].append(Decimal(r['значення']))
def fmt(d):
    s = format(d.normalize(), 'f')
    return s
for k in sorted(g):
    v = sorted(g[k])
    if not v:
        print(f'{k}: —'); continue
    n = len(v)
    m = v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
    print(f'{k}: {fmt(m)}')
