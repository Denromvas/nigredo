import json
from collections import Counter
c = Counter(u['email'].strip().lower() for u in json.load(open('дані/користувачі.json', encoding='utf-8')))
for a in sorted(c):
    if c[a] > 1: print(a, c[a])
