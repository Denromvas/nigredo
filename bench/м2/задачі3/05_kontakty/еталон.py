import csv
groups = {}
with open('дані/контакти.csv', encoding='utf-8') as f:
    for r in csv.DictReader(f):
        groups.setdefault(r['email'].strip().lower(), []).append(r['імʼя'])
for e, names in groups.items():
    if len(names) > 1:
        print(f'{e}: {len(names)}')
        for n in names:
            print('  ' + n)
print('Унікальних:', len(groups))
