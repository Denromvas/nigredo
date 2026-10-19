import re
t = open('дані/текст.txt', encoding='utf-8').read()
sents = [s for s in re.findall(r'[^.!?]+[.!?]', t)]
info = [(i + 1, re.findall(r'[^\W\d_]+', s)) for i, s in enumerate(sents)]
for k, ws in sorted(info, key=lambda p: (-len(p[1]), p[0]))[:3]:
    print(f"№{k} ({len(ws)} слів): {' '.join(ws[:3])}…")
