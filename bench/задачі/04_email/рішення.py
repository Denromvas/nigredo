import re
t = open('../../дані/листи.txt', encoding='utf-8').read()
for a in re.findall(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+', t):
    print(a)
