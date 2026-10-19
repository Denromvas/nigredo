import xml.etree.ElementTree as ET
from decimal import Decimal
root = ET.parse('дані/накладна.xml').getroot()
print('Накладна', root.get('номер'))
g = {}
for r in root.findall('Рядок'):
    s = int(r.findtext('Кількість')) * Decimal(r.findtext('Ціна'))
    g[r.get('група')] = g.get(r.get('група'), Decimal(0)) + s
for k in sorted(g):
    print(f'{k}: {g[k]:.2f}')
print(f'Всього: {sum(g.values()):.2f}')
