cfg = {}
for fn in ('дані/base.ini', 'дані/local.ini'):
    sec = None
    for line in open(fn, encoding='utf-8'):
        line = line.strip()
        if not line or line[0] in '#;':
            continue
        if line.startswith('['):
            sec = line[1:-1]
            cfg.setdefault(sec, {})
        else:
            k, v = line.split('=', 1)
            cfg[sec][k.strip()] = v.strip()
for s in sorted(cfg):
    print(f'[{s}]')
    for k in sorted(cfg[s]):
        print(f'{k}={cfg[s][k]}')
