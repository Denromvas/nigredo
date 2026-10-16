import csv
from datetime import date, timedelta
g = {}
for r in csv.DictReader(open('дані/бронювання.csv', encoding='utf-8')):
    g.setdefault(r['кімната'], []).append((date.fromisoformat(r['з']), date.fromisoformat(r['по'])))
for k in sorted(g):
    out = []
    for a, b in sorted(g[k]):
        if out and a <= out[-1][1] + timedelta(days=1):
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    n = sum((b - a).days + 1 for a, b in out)
    print(f'{k}: ' + ', '.join(f'{a}..{b}' for a, b in out) + f' ({n} днів)')
