import re
from collections import Counter
t = open('../../дані/текст.txt', encoding='utf-8').read().lower()
c = Counter(re.findall(r'\w+', t))
for w, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:3]:
    print(w, n)
