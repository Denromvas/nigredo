#!/usr/bin/env python3
"""Звірка двох читань програми: господар Альбедо (друга, мала граматика в хост.mjs) і мова (`ngr --печатка --json`).

Господар вирішує, які права дати, читаючи текст сам, тож будь-яка розбіжність із мовою — вада межі. На кожній програмі, яку мова
приймає, тут порівнюються: інструменти й теки печатки, квоти, безпосередні імпорти. Програма, яку господар відмовився читати, — не
помилка межі (він лише вужчий), але рахується окремо: це запуск, якого нема. Звірка нічого не виконує.

  python3 albedo/читання.py [--до N] [шляхи…]     Без шляхів — усі .ngr, які відстежує git.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
from collections import Counter

D = pathlib.Path(__file__).resolve().parent
ROOT = D.parent
HOST = D / 'хост.mjs'
sys.path.insert(0, str(ROOT / 'interpreter'))
import nigredo                     # noqa: E402


def scope_key(tool, scope, base):
    if not scope:
        return (tool, '')
    if tool.startswith(('файл.', 'бд.')):
        return (tool, os.path.realpath(os.path.join(base, scope)))
    return (tool, scope)


def language(path):
    """Читання мови: еталон, уже імпортований у цьому процесі; fork на файл дешевий і не лишає стану між програмами."""
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(r)
        null = os.open(os.devnull, os.O_WRONLY)
        os.dup2(w, 1)
        os.dup2(null, 2)
        sys.argv = ['ngr', '--печатка', '--json', path]
        try:
            nigredo.entry()
        except BaseException:
            pass
        finally:
            sys.stdout.flush()
            os._exit(0)
    os.close(w)
    with os.fdopen(r, 'rb') as f:
        out = f.read()
    os.waitpid(pid, 0)
    try:
        return json.loads(out)
    except ValueError:
        return {'помилка_розбору': out[:120].decode('utf-8', 'replace')}


def compare(path, mine):
    lang = language(path)
    if 'помилка_розбору' in lang or 'дозволи' not in lang:
        return 'мова не читає', ''
    if 'відмова' in mine:
        return 'господар вужчий', mine['відмова']
    if mine['печатка'] is None:
        return 'господар вужчий', 'не бачить печатки'
    base = lang.get('тека') or os.path.dirname(os.path.abspath(path))
    a = {scope_key(g['tool'], g['scope'], base) for g in mine['печатка']}
    b = {scope_key(t, s, base) for t, ss in lang['дозволи'].items() for s in (ss or [''])}
    if a != b:
        return 'РОЗБІЖНІСТЬ', f'печатка: господар без мови {sorted(a - b)}, мова без господаря {sorted(b - a)}'
    q1 = sorted((g['tool'], scope_key(g['tool'], g['scope'], base)[1], g['quota']) for g in mine['печатка'] if g['quota'] is not None)
    q2 = sorted((q['інструмент'], scope_key(q['інструмент'], q.get('обмеження') or '', base)[1], q['не_більше']) for q in lang.get('квоти', []))
    if q1 != q2:
        return 'РОЗБІЖНІСТЬ', f'квоти: {q1} / {q2}'
    # порівнюємо файли, а не написання: мова пише «./а.ngr» як «а.ngr» і той самий імпорт перелічує раз
    i1 = sorted({os.path.realpath(os.path.join(base, x)) for x in mine['імпорти']})
    i2 = sorted({os.path.realpath(m.get('файл') or os.path.join(base, m['шлях'])) for m in lang.get('модулі', []) if 'програма' in m.get('бере_його', [])})
    if i1 != i2:
        return 'РОЗБІЖНІСТЬ', f'імпорти: {i1} / {i2}'
    return 'збіглося', ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--до', type=int)
    ap.add_argument('шляхи', nargs='*')
    a = ap.parse_args()
    paths = a.шляхи or [str(ROOT / f) for f in subprocess.run(['git', '-c', 'core.quotepath=off', 'ls-files', '*.ngr'], cwd=ROOT, capture_output=True,
                                                              text=True, check=True).stdout.splitlines()]
    paths = [p for p in paths if os.path.isfile(p)][:a.до]
    r = subprocess.run(['node', str(HOST), '--читання'], input='\n'.join(paths) + '\n', capture_output=True, text=True, check=True)
    mine = [json.loads(x) for x in r.stdout.splitlines()]
    assert len(mine) == len(paths), 'господар прочитав не всі файли'
    count, notes = Counter(), []
    for n, (p, m) in enumerate(zip(paths, mine), 1):
        kind, why = compare(p, m)
        count[kind] += 1
        if kind not in ('збіглося', 'мова не читає'):
            notes.append(f'{kind}: {os.path.relpath(p, ROOT)}: {why}')
        if n % 2000 == 0:
            print(f'… {n}/{len(paths)}', file=sys.stderr, flush=True)
    for x in notes[:60]:
        print(x)
    print(dict(count))
    if not count['збіглося']:
        print('✗ порожня звірка: жодна програма не порівнялася')
        return 2
    return 1 if count['РОЗБІЖНІСТЬ'] else 0


if __name__ == '__main__':
    sys.exit(main())
