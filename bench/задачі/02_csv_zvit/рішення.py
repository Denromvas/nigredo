import csv
from collections import Counter
s = Counter()
with open('../../дані/продажі.csv', encoding='utf-8') as f:
    for r in csv.DictReader(f):
        s[r['місто']] += int(r['сума'])
for k, v in s.most_common():
    print(f'{k} — {v}')
