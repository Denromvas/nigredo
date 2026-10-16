import re
recs = []
for line in open('дані/журнал.txt', encoding='utf-8').read().splitlines():
    if line[:1] == ' ' and recs:
        recs[-1][1].append(line)
    elif line.strip():
        recs.append((line[:19], []))
st = {}
for t, cont in recs:
    types = [m.group(1) for l in cont if (m := re.match(r'^\s+(\w+): ', l))]
    if types:
        ty = types[-1]
        n, f, last = st.get(ty, (0, t, t))
        st[ty] = (n + 1, f, t)
for ty in sorted(st, key=lambda k: (-st[k][0], k)):
    n, f, l = st[ty]
    print(f'{ty}: {n} (перший {f}, останній {l})')
