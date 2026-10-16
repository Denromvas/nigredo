import json
c = json.load(open('дані/конфіги.json', encoding='utf-8'))
def resolve(n, seen=()):
    if n in seen:
        return None
    p = c[n]['успадковує']
    base = {} if p is None else resolve(p, seen + (n,))
    if base is None:
        return None
    return {**base, **c[n]['значення']}
def show(v):
    return v if isinstance(v, str) else json.dumps(v)
for n in sorted(c):
    r = resolve(n)
    print(f'{n}: цикл' if r is None else f'{n}: ' + ', '.join(f'{k}={show(r[k])}' for k in sorted(r)))
