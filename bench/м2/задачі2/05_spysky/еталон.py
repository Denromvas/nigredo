def load(f):
    d = {}
    for l in open(f, encoding='utf-8'):
        n = l.strip()
        if n and n.lower() not in d:
            d[n.lower()] = n
    return d
a, b = load('дані/вчора.txt'), load('дані/сьогодні.txt')
lst = lambda xs: ', '.join(sorted(xs, key=str.lower)) or '—'
print('додано: ' + lst(b[k] for k in b if k not in a))
print('зникло: ' + lst(a[k] for k in a if k not in b))
print(f'лишилось: {sum(1 for k in b if k in a)}')
