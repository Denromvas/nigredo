#!/usr/bin/env python3
"""Звірка Атанора з еталоном: кожну програму .ngr з репозиторію запускає обидва виконавці з тією самою тимчасовою
текою власника (ключ, дозволи: читати й список — по репозиторію, писати — ніде) і порівнює код виходу, вивід, stderr
і слід (без часу, номера запуску, хешів ланцюжка й поля «інтерпретатор»). Програми, які Атанор віддає еталону,
лічаться окремо (з причиною).

  python3 athanor/звірка.py [-j 4] [--до N] [--зразок K] [шляхи…]

Друкує розбіжності й підсумок; пише athanor/ЗВІРКА.md."""
import argparse
import concurrent.futures as cf
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
BIN = next((p for p in (os.path.join(HERE, 'target', t, 'release', 'athanor') for t in ('aarch64-unknown-linux-gnu', 'x86_64-unknown-linux-gnu', '', 'aarch64-unknown-linux-musl')) if os.path.exists(p)))
REF = os.path.join(ROOT, 'interpreter', 'ngr.py')
SKIP_DIRS = ('архів', 'target', '.git', 'site/пісочниця/вихід')
VOLATILE = {'час', 'запуск', 'інтерпретатор', 'хеш', 'попередній'}


def programs(paths):
    out = []
    for base in paths:
        if os.path.isfile(base):
            out.append(os.path.abspath(base))
            continue
        for d, dirs, files in os.walk(base):
            rel = os.path.relpath(d, ROOT)
            if any(rel == s or rel.startswith(s + '/') for s in SKIP_DIRS):
                dirs[:] = []
                continue
            out += [os.path.abspath(os.path.join(d, f)) for f in files if f.endswith('.ngr')]
    return sorted(out)


def make_home(tmp):
    home = os.path.join(tmp, 'власник')
    os.makedirs(home, mode=0o700)
    with open(os.path.join(home, 'ключ'), 'w') as f:
        f.write('0123456789abcdef' * 4)
    with open(os.path.join(home, 'дозволи.json'), 'w', encoding='utf-8') as f:
        json.dump({'дозволено': ['оракул', 'жереб', 'час', f'файл.читати:{ROOT}', f'файл.список:{ROOT}']}, f,
                  ensure_ascii=False)
    return home


def norm_trace(path, timed=False):
    if not path or not os.path.exists(path):
        return None
    recs, clock = [], set()
    for line in open(path, encoding='utf-8'):
        r = json.loads(line)
        if r.get('назва') == 'час' and 'результат' in r:      # годинник: два запуски — різні секунди
            clock.add(r.get('значення'))
            r = {k: v for k, v in r.items() if k not in ('результат', 'значення')}
        if timed and r.get('подія') == 'кінець':     # SQLite списує кроки й за часом роботи запиту
            r.pop('кроків', None)
        recs.append({k: v for k, v in r.items() if k not in VOLATILE})
    store = path + '.дані'
    data = None
    if os.path.exists(store):
        data = [x for x in open(store, encoding='utf-8').read().split('\n') if x and json.loads(x)['sha256'] not in clock]
    return recs, data


EXTRA = []


def run_one(cmd, prog, home, tmp, tag, timeout):
    tpf = os.path.join(tmp, f'{tag}.шлях')
    env = dict(os.environ, NIGREDO_HOME=home, NIGREDO_TRACE_PATH_FILE=tpf, PYTHONHASHSEED='0')
    if tag == 'а':
        env['ATHANOR_NO_FALLBACK'] = '1'
    if os.path.exists(tpf):
        os.remove(tpf)
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd + EXTRA + [prog], capture_output=True, timeout=timeout, env=env, cwd=os.path.dirname(prog),
                           stdin=subprocess.DEVNULL)
        code, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        code, out, err = 'час', b'', b''
    dt = time.perf_counter() - t0
    tpath = open(tpf, encoding='utf-8').read() if os.path.exists(tpf) else None
    timed = 'бд.' in open(prog, encoding='utf-8', errors='replace').read()
    return code, out, err, norm_trace(tpath, timed), dt


def compare(prog, timeout):
    tmp = tempfile.mkdtemp(prefix='звірка-')
    try:
        home = make_home(tmp)
        a = run_one([BIN], prog, home, tmp, 'а', timeout)
        if a[0] == 120:
            why = a[2].decode('utf-8', 'replace').strip().removeprefix('атанор: не виконую сам (').removesuffix(')')
            return prog, 'еталон', why, None
        p = run_one(['python3', REF], prog, home, tmp, 'п', timeout)
        if p[0] == 'час' and a[0] != 'час':        # еталон у рази повільніший — дати йому більше часу, а не рахувати різницею
            p = run_one(['python3', REF], prog, home, tmp, 'п', timeout * 8)
        diffs = []
        if a[0] != p[0]:
            diffs.append(f'код: атанор {a[0]}, еталон {p[0]}')
        if a[1] != p[1]:
            diffs.append(f'вивід:\n  атанор: {a[1][:300]!r}\n  еталон: {p[1][:300]!r}')
        if a[2] != p[2]:
            diffs.append(f'stderr:\n  атанор: {a[2][:300]!r}\n  еталон: {p[2][:300]!r}')
        if a[3] != p[3]:
            ta, tp = a[3] or ([], None), p[3] or ([], None)
            first = next((i for i, (x, y) in enumerate(zip(ta[0], tp[0])) if x != y), min(len(ta[0]), len(tp[0])))
            show = lambda t: json.dumps(t[0][first], ensure_ascii=False)[:400] if first < len(t[0]) else '—'  # noqa: E731
            diffs.append(f'слід (запис {first + 1}):\n  атанор: {show(ta)}\n  еталон: {show(tp)}'
                         + ('' if ta[1] == tp[1] else '\n  сховище .дані різне'))
        if diffs and '🜔час' in open(prog, encoding='utf-8', errors='replace').read():
            return prog, 'годинник', '\n'.join(diffs), (a[4], p[4])   # поведінка залежить від секунд — не порівнюється
        return prog, 'різниця' if diffs else 'так', '\n'.join(diffs), (a[4], p[4])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('шляхи', nargs='*', default=[ROOT])
    ap.add_argument('-j', type=int, default=3)
    ap.add_argument('--до', type=int, default=0)
    ap.add_argument('--зразок', type=int, default=0)
    ap.add_argument('--час', type=float, default=60)
    ap.add_argument('--звіт', default=os.path.join(HERE, 'ЗВІРКА.md'))
    ap.add_argument('--прапорці', default='', help='додаткові прапорці обом виконавцям, напр. «--кроки 500»')
    a = ap.parse_args()
    EXTRA[:] = a.прапорці.split()
    progs = programs(a.шляхи)
    if a.зразок:
        progs = progs[::max(1, len(progs) // a.зразок)]
    if a.до:
        progs = progs[:a.до]
    res = []
    with cf.ThreadPoolExecutor(a.j) as ex:
        for i, r in enumerate(ex.map(lambda p: compare(p, a.час), progs), 1):
            res.append(r)
            if r[1] == 'різниця':
                print(f'✗ {os.path.relpath(r[0], ROOT)}\n  {r[2]}', flush=True)
            if i % 100 == 0:
                print(f'… {i}/{len(progs)}', flush=True)
    cnt = Counter(r[1] for r in res)
    whys = Counter(r[2] for r in res if r[1] == 'еталон')
    sa = sum(r[3][0] for r in res if r[3])
    sp = sum(r[3][1] for r in res if r[3])
    lines = [f'# Звірка Атанора з еталоном', '',
             f'Програм: {len(res)}. Атанор виконав сам: {cnt["так"] + cnt["різниця"] + cnt["годинник"]} — однаково '
             f'{cnt["так"]}, розбіжностей {cnt["різниця"]}, залежних від годинника (не порівнюються) {cnt["годинник"]}. '
             f'Віддав еталону: {cnt["еталон"]}.',
             f'Час (лише виконані Атанором): Атанор {sa:.1f} с, еталон {sp:.1f} с.', '',
             '## Чому віддано еталону', ''] + [f'- {n} — {w}' for w, n in whys.most_common(40)]
    if cnt['різниця']:
        lines += ['', '## Розбіжності', ''] + [f'- `{os.path.relpath(r[0], ROOT)}`' for r in res if r[1] == 'різниця']
    open(a.звіт, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print('\n'.join(lines[:4]))
    return 1 if cnt['різниця'] else 0


if __name__ == '__main__':
    sys.exit(main())
