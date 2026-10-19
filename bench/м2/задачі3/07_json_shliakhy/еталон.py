import json
out = []
def walk(x, path):
    if isinstance(x, dict):
        for k, v in x.items():
            walk(v, path + [k])
    elif isinstance(x, list):
        for i, v in enumerate(x):
            walk(v, path + [str(i)])
    elif isinstance(x, (int, float)) and not isinstance(x, bool) and x > 100:
        out.append(f"{'.'.join(path)} = {x}")
walk(json.load(open('дані/структура.json', encoding='utf-8')), [])
print('\n'.join(out))
print('Знайдено:', len(out))
