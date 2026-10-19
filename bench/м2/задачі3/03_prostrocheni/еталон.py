import json
from datetime import date
today = date(2026, 10, 20)
t = json.load(open('дані/задачі.json', encoding='utf-8'))
late = [(x, (today - date.fromisoformat(x['термін'])).days) for x in t if not x['виконано']]
late = sorted([p for p in late if p[1] > 0], key=lambda p: (-p[1], p[0]['задача']))
for x, d in late:
    print(f"{x['задача']} ({x['відповідальний']}): {d} дн.")
print('Прострочено:', len(late))
