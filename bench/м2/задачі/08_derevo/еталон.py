import json
t = json.load(open('дані/дерево.json', encoding='utf-8'))
size = lambda n: n['розмір'] + sum(size(c) for c in n['діти'])
depth = lambda n: 1 + max((depth(c) for c in n['діти']), default=0)
print(f'разом: {size(t)}'); print(f'глибина: {depth(t)}')
