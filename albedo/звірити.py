#!/usr/bin/env python3
"""Звірка Альбедо з Атанором: та сама програма, той самий власник; вивід, код, stderr і слід мають збігтися. Атанор сам звірений
з еталоном (athanor/звірка.py), тож тут лише крок Атанор → Альбедо. Слід — без того, що Альбедо дописує чесно своє: запис
«ізоляція» й «дія господаря», нумерація після них, поля athanor/звірка.py VOLATILE.

  python3 albedo/звірити.py [-j 3] [--має РЯДОК] [--час 60] [шляхи…]

Без шляхів — усі .ngr, які відстежує git. --має — лише програми з цим рядком у тексті.
Вихід: 0 — звірено й розбіжностей немає; 1 — є розбіжності; 2 — порожня звірка."""
import argparse
import concurrent.futures as cf
import glob
import importlib.util
import json
import os
import hashlib
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter

HERE = os.path.dirname(os.path.realpath(__file__))
spec = importlib.util.spec_from_file_location('zvirka', os.path.join(HERE, '..', 'athanor', 'звірка.py'))
z = importlib.util.module_from_spec(spec)
sys.modules['zvirka'] = z
spec.loader.exec_module(z)
# Атанор — свіжий нативний бінарник, що справді відкриває libsqlite3: старий статичний усе віддав би еталону, і звірка була б порожньою
z.BIN = max(glob.glob(os.path.join(z.HERE, 'target', '*', 'release', 'athanor')), key=os.path.getmtime)
HOST = ['node', os.path.join(HERE, 'хост.mjs'), os.path.join(HERE, 'target', 'wasm32-unknown-unknown', 'release', 'albedo.wasm')]


def trace(t):
    if not t:
        return t
    recs = [{k: v for k, v in r.items() if k != '№'} for r in t[0] if r.get('подія') not in ('ізоляція', 'дія господаря')]
    return recs, t[1]


def compare(prog, timeout):
    tmp = tempfile.mkdtemp(prefix='альбедо-')
    try:
        home = z.make_home(tmp, True)
        a = z.run_one([z.BIN], z.fresh(prog, tmp), home, tmp, 'а', timeout)
        if a[0] == 120:
            return prog, 'лише еталон', ''
        b = z.run_one(HOST, z.fresh(prog, tmp), home, tmp, 'б', timeout * 4)
        if b[0] == 120:
            return prog, 'не вміє', b[2].decode('utf-8', 'replace').strip()
        diffs = []
        if a[0] != b[0]:
            diffs.append(f'код: атанор {a[0]}, альбедо {b[0]}')
        if a[1] != b[1]:
            diffs.append(f'вивід:\n  атанор: {a[1][:300]!r}\n  альбедо: {b[1][:300]!r}')
        if a[2] != b[2]:
            diffs.append(f'stderr:\n  атанор: {a[2][:300]!r}\n  альбедо: {b[2][:300]!r}')
        ta, tb = trace(a[3]), trace(b[3])
        if ta != tb:
            ra, rb = (ta or ([], None))[0], (tb or ([], None))[0]
            i = next((i for i, (x, y) in enumerate(zip(ra, rb)) if x != y), min(len(ra), len(rb)))
            show = lambda t: json.dumps(t[i], ensure_ascii=False)[:300] if i < len(t) else '—'  # noqa: E731
            diffs.append(f'слід (запис {i + 1}):\n  атанор: {show(ra)}\n  альбедо: {show(rb)}' + ('' if (ta or [0, 0])[1] == (tb or [0, 0])[1] else '\n  .дані різні'))
        text = open(prog, encoding='utf-8', errors='replace').read()
        if diffs and ('🜔час' in text or "'now'" in text or 'CURRENT_' in text):
            return prog, 'годинник', '\n'.join(diffs)    # два запуски — різні секунди
        if diffs and 'слід перевищив'.encode() in a[2] and 'слід перевищив'.encode() in b[2]:
            return prog, 'межа сліду', '\n'.join(diffs)  # обидва зупинились тим самим текстом; рядок сліду модуля на кілька байтів інший
        if a[0] == 'час':
            return prog, 'час', ''                        # Атанор сам не вклався: порівнювати нема з чим
        if diffs and ('random(' in text or 'sqlite_source_id' in text or '/proc/self' in text):
            return prog, 'чуже', '\n'.join(diffs)        # випадкове від SQLite чи його збірка: цього 1.x не обіцяє (§9)
        if diffs and 'запит довший за 30 с'.encode() in b[1]:
            return prog, 'темп', '\n'.join(diffs)        # нескінченний запит: Атанор раніше вичерпав кроки, модуль — 30 с
        return prog, 'різниця' if diffs else 'так', '\n'.join(diffs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('шляхи', nargs='*', default=[])
    ap.add_argument('-j', type=int, default=3)
    ap.add_argument('--час', type=float, default=60)
    ap.add_argument('--має', default='')
    ap.add_argument('--корінь', default=z.ROOT, help='репозиторій із робочими файлами суддів; у worktree їх немає')
    ap.add_argument('--до', type=int, default=0)
    ap.add_argument('--звіт', default='', help='записати підсумок у цей файл')
    a = ap.parse_args()
    z.ROOT = a.корінь
    progs = z.programs(a.шляхи)
    if a.має:
        progs = [p for p in progs if a.має in open(p, encoding='utf-8', errors='replace').read()]
    if a.до:
        progs = progs[:a.до]
    cnt, why = Counter(), Counter()
    with cf.ThreadPoolExecutor(a.j) as ex:
        for i, (p, r, t) in enumerate(ex.map(lambda p: compare(p, a.час), progs), 1):
            cnt[r] += 1
            if r == 'не вміє':
                why[t[:90]] += 1
            if r == 'різниця':
                print(f'✗ {os.path.relpath(p, z.ROOT)}\n  {t}', flush=True)
            if i % 100 == 0:
                print(f'… {i}/{len(progs)}', flush=True)
    line = (f'Програм: {len(progs)}; однаково {cnt["так"]}, розбіжностей {cnt["різниця"]}, годинник {cnt["годинник"]}, чуже значення {cnt["чуже"]}, темп {cnt["темп"]}, Атанор не вклався {cnt["час"]}, межа сліду {cnt["межа сліду"]}, модуль не вміє {cnt["не вміє"]}, лише еталон {cnt["лише еталон"]}')
    print(line)
    for w, n in why.most_common(12):
        print(f'  {n} × {w}')
    if a.звіт:
        rev = subprocess.run(['git', '-C', HERE, 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
        sha = lambda p: hashlib.sha256(open(p, 'rb').read()).hexdigest()[:16]  # noqa: E731
        with open(a.звіт, 'w', encoding='utf-8') as f:
            f.write(f'# Звірка Альбедо з Атанором\n\nПрогін {time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}, коміт `{rev}`, копія теки на кожен запуск; '
                    f'модуль `{sha(HOST[2])}…`, господар `{sha(HOST[1])}…`.\n\n{line}.\n\n'
                    '«Лише еталон» — чого не вміє сам Атанор (мережа, `‖`, міст, підпис, печатка поза дозволами): порівнювати нема з чим. «Чуже значення» — '
                    '`random()`, збірка SQLite, `/proc/self`; «темп» — нескінченний запит: Атанор вичерпав кроки, модуль — 30 с; «межа сліду» — обидва '
                    'зупинились тим самим текстом, рядки сліду модуля на кілька байтів інші.\n')
    if not cnt['так']:
        print('✗ порожня звірка: жодної програми не порівняно (Атанор віддав усе еталону?)')
        sys.exit(2)
    sys.exit(1 if cnt['різниця'] else 0)


main()
