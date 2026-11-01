#!/usr/bin/env python3
"""Звірка лексера на Nigredo з еталоном: той самий потік токенів на програмах корпусу. Лексер — для правильних програм, тож те, що еталон
відкидає, не порівнюється, а лічиться окремо.

  python3 самохостинг/звірити.py [-j 3] [--до N] [--від N] [--корінь РЕПО] [--кроки N] [шляхи…]

Вихід: 0 — порівняно й розбіжностей немає; 1 — є розбіжності; 2 — порожня звірка."""
import argparse
import concurrent.futures as cf
import decimal
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'interpreter'))
import nigredo  # noqa: E402

NGR = next((str(p) for p in sorted((ROOT / 'athanor' / 'target').glob('*/release/athanor'), key=os.path.getmtime, reverse=True)), 'ngr')


SIZE = [50000000]
CMD = [NGR]
LEX = threading.Lock()         # таблиці еталона вантажаться ліниво й не для кількох потоків


def want(src):
    with LEX:
        return [[kind, val, line, col] for kind, val, (line, col) in nigredo.lex(src)]


def same(a, b):
    if len(a) != len(b):
        return f'токенів: еталон {len(a)}, лексер {len(b)}'
    for x, y in zip(a, b):
        ok = x[0] == y[0] and x[2:] == y[2:]
        if ok and x[0] == 'num':
            ok = decimal.Decimal(str(x[1])) == decimal.Decimal(y[1]) and ('.' in y[1]) == isinstance(x[1], decimal.Decimal)
        elif ok:
            ok = x[1] == y[1] or (x[0] == 'name' and nigredo.unicodedata.normalize('NFC', y[1]) == x[1])
        if not ok:
            return f'еталон {x!r}, лексер {y!r}'
    return ''


def one(prog, work, steps):
    raw = open(prog, 'rb').read()
    try:
        src = raw.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
    except UnicodeDecodeError:
        return prog, 'не utf-8', '', 0, 0
    if len(src) > 400000:
        return prog, 'завеликий', '', 0, 0
    t0 = time.perf_counter()
    try:
        a = want(src)
    except nigredo.StaticError:
        return prog, 'відкинуто', '', 0, 0
    except RecursionError:
        return prog, 'відкинуто', '', 0, 0
    tp = time.perf_counter() - t0
    (work / 'вхід' / 'вхід.ngr').write_text(src, encoding='utf-8')
    t0 = time.perf_counter()
    r = subprocess.run([*CMD, '--кроки', str(steps), '--розмір', str(SIZE[0]), '--слід-розмір', str(20 * SIZE[0]), str(work / 'токени.ngr')], capture_output=True, env=dict(os.environ, NIGREDO_HOME=str(work / 'в')),
                       stdin=subprocess.DEVNULL, timeout=600)
    tn = time.perf_counter() - t0
    if r.returncode:
        return prog, 'різниця', 'код ' + str(r.returncode) + ': ' + r.stderr.decode('utf-8', 'replace')[:300], tp, tn
    try:
        # » показує невидиме як ⟨U+…⟩, а справжній ⟨ — теж кодом: повернути, щоб порівнювати значення, а не вивід
        b = json.loads(re.sub(r'⟨U\+([0-9A-F]{4,6})⟩', lambda m: chr(int(m.group(1), 16)), r.stdout.decode('utf-8')))
    except ValueError as e:
        return prog, 'різниця', f'вивід не JSON: {e}', tp, tn
    d = same(a, b)
    return prog, 'різниця' if d else 'так', d, tp, tn


def prepare(base):
    work = pathlib.Path(tempfile.mkdtemp(prefix='лексер-', dir=base))
    (work / 'вхід').mkdir()
    (work / 'в').mkdir()
    for f in ('лексер.ngr', 'токени.ngr'):
        shutil.copy(HERE / f, work / f)
    (work / 'в' / 'дозволи.json').write_text(json.dumps({'дозволено': [f'файл.читати:{work}/вхід']}, ensure_ascii=False), encoding='utf-8')
    return work


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('шляхи', nargs='*')
    ap.add_argument('-j', type=int, default=3)
    ap.add_argument('--до', type=int, default=0)
    ap.add_argument('--від', type=int, default=0)
    ap.add_argument('--кроки', type=int, default=200000000)
    ap.add_argument('--виконавець', default='', help='команда запуску замість Атанора, через пробіл')
    ap.add_argument('--розмір', type=int, default=50000000, help='межа «сумарно створено» — 20 × це')
    ap.add_argument('--корінь', default=str(ROOT))
    a = ap.parse_args()
    SIZE[0] = a.розмір
    CMD[:] = a.виконавець.split() or CMD
    if a.шляхи:
        progs = []
        for p in a.шляхи:
            progs += sorted(str(x) for x in pathlib.Path(p).resolve().rglob('*.ngr')) if os.path.isdir(p) else [os.path.abspath(p)]
    else:
        names = subprocess.run(['git', '-C', a.корінь, 'ls-files', '-z', '--', '*.ngr'], capture_output=True).stdout.decode('utf-8', 'surrogateescape').split('\0')
        progs = sorted(os.path.join(a.корінь, n) for n in names if n and not n.startswith('архів/'))
    progs = (progs[:a.до] if a.до else progs)[a.від:]
    base = tempfile.mkdtemp(prefix='лексер-звірка-')
    works = [prepare(base) for _ in range(a.j)]
    free = list(works)
    cnt, tp, tn = Counter(), 0.0, 0.0
    lock = threading.Lock()

    def job(p):
        with lock:
            w = free.pop()
        try:
            return one(p, w, a.кроки)
        finally:
            with lock:
                free.append(w)
    try:
        with cf.ThreadPoolExecutor(a.j) as ex:
            for i, (p, r, d, x, y) in enumerate(ex.map(job, progs), 1):
                cnt[r] += 1
                tp += x
                tn += y
                if r == 'різниця':
                    print(f'✗ {os.path.relpath(p, a.корінь)}\n  {d}', flush=True)
                if i % 200 == 0:
                    print(f'… {i}/{len(progs)}', flush=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print(f'Програм: {len(progs)}; однаково {cnt["так"]}, розбіжностей {cnt["різниця"]}, еталон відкинув {cnt["відкинуто"]}, завеликі {cnt["завеликий"]}, не utf-8 {cnt["не utf-8"]}')
    print(f'Час: еталон {tp:.1f} с, лексер на Nigredo {tn:.1f} с')
    sys.exit(2 if not cnt['так'] else 1 if cnt['різниця'] else 0)


main()
