import csv
from decimal import Decimal
debt = {}
with open('дані/рахунки.csv', encoding='utf-8') as f:
    for r in csv.DictReader(f):
        debt[r['клієнт']] = debt.get(r['клієнт'], Decimal(0)) + Decimal(r['сума']) - Decimal(r['сплачено'])
pos = sorted(((k, v) for k, v in debt.items() if v > 0), key=lambda kv: (-kv[1], kv[0]))
for k, v in pos:
    print(f'{k}: {v:.2f}')
print(f'Разом: {sum(v for _, v in pos):.2f}')
