import re
from collections import Counter
c = Counter()
for l in open('дані/запити.log', encoding='utf-8'):
    m = re.search(r'https?://([^/\s:]+)', l)
    if m:
        d = m.group(1).lower()
        c[d[4:] if d.startswith('www.') else d] += 1
for d, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:3]:
    print(d, n)
