from collections import Counter
c = Counter(open('дані/текст.txt', encoding='utf-8').read().replace('\n', ' ').split())
for k, n in sorted(c.items(), key=lambda x: (-x[1], x[0]))[:3]:
    print(k, n)
