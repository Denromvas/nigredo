#!/usr/bin/env python3
"""Проба «час на крок» для кожного гліфа з довгими аргументами (суд 15, Мовознавець: HEAVY — за правилом із пробою).

  python3 athanor/ціна_кроку.py "ВИКОНАВЕЦЬ" [--поріг С_НА_МЛН] [--лише ГЛІФИ]   (виконавець — команда в лапках)

Для кожного гліфа й набору аргументів програма будує великі значення, потім K разів застосовує гліф. Ціна кроку —
(час(K2) − час(K1)) / (кроки(K2) − кроки(K1)). Звичайний цикл — сотні мс на мільйон кроків в еталоні, десятки мс в Атанорі;
усе, що вище порогу, — кандидат у «роботу без плати»."""
import itertools
import json
import os
import subprocess
import sys
import tempfile
import time

args = sys.argv[1:]
thr = 3.0
only = None
if '--поріг' in args:
    i = args.index('--поріг')
    thr = float(args[i + 1])
    del args[i:i + 2]
if '--лише' in args:
    i = args.index('--лише')
    only = args[i + 1]
    del args[i:i + 2]
EXE = args[0].split()

POOL = {
    'Р': '← Р Σ … 1 20 「я」 Λs ж ＋ s s',          # мільйон символів
    'Р2': '← Р2 Σ … 1 20 「я」 Λs ж ＋ s s',        # такий самий, інший обʼєкт
    'П': '← П Σ … 1 20 「 」 Λs ж ＋ s s',          # пробіли
    'Н': '← Н Σ … 1 20 「\\n」 Λs ж ＋ s s',        # переноси
    'С': '← С Σ … 1 16 【1】 Λs ж 【s s】',        # спільне дерево, 196 607
    'С2': '← С2 Σ … 1 16 【1】 Λs ж 【s s】',
    'Ш': '← Ш ⁀ μ … 1 100000 λі 「ab」 「」',      # ASCII рядок 200 тис.
    'Ц': '← Ц Σ … 1 14 3 Λs ж × s s',              # ~26 тис. бітів
    'Ц2': '← Ц2 ＋ Σ … 1 13 5 Λs ж × s s 1',
    'Д': '← Д ✎ 『』 Р 1',
    'Сп': '← Сп μ … 1 100000 λі і',                # плаский список
}
SMALL = ['1', '「а」', '「」', '0', '【1】']
BIG = ['Р', 'П', 'Н', 'С', 'Ш', 'Ц', 'Д', 'Сп']
PAIRS = [('Р', 'Р2'), ('С', 'С2'), ('Ц', 'Ц2'), ('Р', 'Р'), ('Сп', 'Сп'), ('Ш', 'Ш')]

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'interpreter'))
import nigredo as N  # noqa: E402

SKIP = set(N.LAZY_GLYPHS) | set(N.FN_SLOTS) | set('»⌂🜁🜃🜄▶►…')


def combos(g, ar):
    if g == '☠':
        return [[x] for x in BIG]
    if ar == 1:
        return [[x] for x in BIG]
    if ar == 2:
        out = [[x, s] for x in BIG for s in SMALL] + [[s, x] for x in BIG for s in SMALL[:3]] + [list(p) for p in PAIRS]
        return out
    out = []
    for x in BIG:
        for s1, s2 in itertools.product(['「а」', '「я」', '「」', '0', '¯1', '1'], repeat=2):
            out.append([x, s1, s2])
        out.append([x, x, '「」'])
        out.append([x, '「я」', x])
    return out


def run(prog, k):
    with tempfile.TemporaryDirectory() as d:
        home = os.path.join(d, 'h')
        tr = os.path.join(d, 'с.jsonl')
        p = os.path.join(d, 'п.ngr')
        open(p, 'w', encoding='utf-8').write(prog.replace('@K', str(k)))
        t0 = time.perf_counter()
        r = subprocess.run(EXE + ['--слід', tr, p], capture_output=True, env=dict(os.environ, NIGREDO_HOME=home), timeout=600)
        dt = time.perf_counter() - t0
        steps = None
        try:
            for line in open(tr, encoding='utf-8'):
                j = json.loads(line)
                if j.get('подія') == 'кінець':
                    steps = j.get('кроків')
        except OSError:
            pass
        return r.returncode, dt, steps, r.stderr.decode('utf-8', 'replace').strip()[-120:]


for g, v in sorted(N.GLYPHS.items()):
    ar = v[0]
    if ar is None or g in SKIP or (only and g not in only):
        continue
    for a in combos(g, ar):
        names = [x for x in a if x in POOL]
        need = list(dict.fromkeys(names + (['Р'] if 'Д' in names else [])))
        pool = '\n'.join(POOL[n] for n in sorted(need, key=lambda n: n == 'Д'))
        expr = f'{g} {" ".join(a)}'
        if g == '☠':
            expr = f'☂ ☠ {a[0]} λe 0'
        prog = '🜂 「проба」 【】\n' + pool + f'\n∀ … 1 @K λі {expr}\n'
        c1, t1, s1, e1 = run(prog, 1)
        if c1 != 0:
            continue
        k = 21
        c2, t2, s2, e2 = run(prog, k)
        if c2 != 0 or s1 is None or s2 is None:
            print(f'{expr}: K={k} код {c2} {e2}', flush=True)
            continue
        ds, dt = s2 - s1, t2 - t1
        per = dt / max(ds, 1) * 1e6
        flag = '  ⚠' if per > thr and dt > 0.2 else ''
        if flag or os.environ.get('УСЕ'):
            print(f'{expr}: +{ds} кроків, +{dt:.2f} с — {per:.1f} с на мільйон{flag}', flush=True)
print('готово', flush=True)
