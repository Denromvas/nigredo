from collections import Counter
c = Counter(l.split()[0][11:13] for l in open('дані/лог.txt', encoding='utf-8') if l.split()[1:2] == ['ERROR'])
for h in sorted(c): print(f'{h}: {c[h]}')
