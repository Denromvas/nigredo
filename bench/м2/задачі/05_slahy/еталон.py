import re
for l in open('дані/заголовки.txt', encoding='utf-8'):
    if l.strip(): print(re.sub(r'[^a-z0-9]+', '-', l.lower()).strip('-'))
