import json
from datetime import date, timedelta
t = date(2026, 10, 15)
out = []
for r in json.load(open('дані/рахунки.json', encoding='utf-8')):
    d = (t - (date.fromisoformat(r['дата']) + timedelta(days=r['днів_на_оплату']))).days
    if not r['сплачено'] and d > 0: out.append((-d, r['номер']))
for d, n in sorted(out): print(f'{n}: {-d} днів')
