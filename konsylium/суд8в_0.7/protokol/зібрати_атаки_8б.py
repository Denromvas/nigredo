"""Як зібрано audytor/атаки_8б/ і власник/дозволи.json суду 8в: атаки шести суддів суду 8б (без звітів, журналів,
слідів) — у audytor/атаки_8б/<суддя>/, шляхи суду 8б переписано на нові; для кожної теки — свої «для_тек»."""
import json, os, shutil
K = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(os.path.dirname(K), 'суд8б_0.7')
J = ['audytor', 'movoznavets', 'novachok', 'orkestrator', 'praktyk', 'skeptyk']
SKIP = {'CLAUDE.md', 'mcp.json', 'попередні_звіти', 'атаки_минулих_судів', 'сліди', 'gemini_member.py'}
A = f'{K}/audytor'


def rw(t):
    for j in J:
        t = t.replace(f'/konsylium/суд8б_0.7/{j}', f'/konsylium/суд8в_0.7/audytor/атаки_8б/{j}')
    return t.replace('/konsylium/суд8б_0.7/', '/konsylium/суд8в_0.7/')


for j in J:
    for root, dirs, files in os.walk(f'{SRC}/{j}'):
        rel = os.path.relpath(root, f'{SRC}/{j}')
        dirs[:] = [d for d in dirs if not (rel == '.' and d in SKIP)]
        out = os.path.normpath(f'{A}/атаки_8б/{j}/{rel}')
        os.makedirs(out, exist_ok=True)
        for f in files:
            if rel == '.' and (f in SKIP or f.startswith(('звіт_раунд', 'розмова')) or f.endswith('.log')):
                continue
            try:
                open(f'{out}/{f}', 'w', encoding='utf-8').write(rw(open(f'{root}/{f}', encoding='utf-8').read()))
            except UnicodeDecodeError:
                shutil.copy2(f'{root}/{f}', f'{out}/{f}')
P = lambda b: [f'читати:{b}/дані', f'список:{b}/дані', f'писати:{b}/звіти', f'бд.читати:{b}/дані', f'бд.писати:{b}/звіти',
               'взяти:127.0.0.1:28709', 'послати:127.0.0.1:28709', 'процес:echo', 'процес:ls', 'процес:sh -c echo']
per = {A: P(A), **{f'{A}/атаки_8б/{j}': P(f'{A}/атаки_8б/{j}') for j in J}}
json.dump({'дозволено': ['оракул', 'жереб', 'час'], 'для_тек': per},
          open(f'{K}/власник/дозволи.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
