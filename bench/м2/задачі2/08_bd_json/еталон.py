import json, sqlite3
cl = json.load(open('дані/клієнти.json', encoding='utf-8'))
reg, names = {}, {}
for cid, s in sqlite3.connect('дані/база.db').execute("SELECT клієнт_id, сума FROM оплати WHERE статус = 'ок'"):
    c = cl.get(str(cid))
    if c:
        reg[c['регіон']] = reg.get(c['регіон'], 0) + s
        names.setdefault(c['регіон'], set()).add(c['імʼя'])
for r in sorted(reg, key=lambda r: (-reg[r], r)):
    print(f'{r}: {reg[r]} ({", ".join(sorted(names[r]))})')
