import re
t = open('дані/контакти.txt', encoding='utf-8').read()
out = set()
for m in re.finditer(r'\+?[\d()][\d\s()-]*\d', t):
    d = re.sub(r'\D', '', m.group())
    if len(d) == 10 and d[0] == '0': out.add('+38' + d)
    elif len(d) == 12 and d.startswith('380'): out.add('+' + d)
for x in sorted(out): print(x)
