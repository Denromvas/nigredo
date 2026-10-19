import csv
def mins(t):
    h, m = t.split(':')
    return int(h) * 60 + int(m)
rows = list(csv.DictReader(open('дані/зміни.csv', encoding='utf-8')))
tot = {}
for r in rows:
    tot[r['працівник']] = tot.get(r['працівник'], 0) + mins(r['кінець']) - mins(r['початок'])
for p in sorted(tot):
    print(f'{p}: {tot[p] // 60} год {tot[p] % 60:02d} хв')
over = []
for i, a in enumerate(rows):
    for b in rows[i + 1:]:
        if a['працівник'] == b['працівник'] and a['дата'] == b['дата'] and \
                mins(a['початок']) < mins(b['кінець']) and mins(b['початок']) < mins(a['кінець']):
            over.append(f"Перетин: {a['працівник']} {a['дата']} {a['початок']}–{a['кінець']} і {b['початок']}–{b['кінець']}")
print('\n'.join(over) if over else 'Перетинів немає')
