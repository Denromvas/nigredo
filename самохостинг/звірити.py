#!/usr/bin/env python3
"""Звірка лексера й парсера на Nigredo з еталоном: той самий потік токенів (чи те саме дерево розбору, `--парсер`) на програмах
корпусу. Обидва — для правильних програм, тож те, що еталон відкидає, не порівнюється, а лічиться окремо. Модулі (⊃) парсер
розбирає разом з програмою: звірка кладе поруч ті файли, які взяв еталон. Модулі з мережі (сховище за sha256) — «з мережі», окремо;
шлях модуля, що виходить вище теки програми й вертається в неї (тека/../тека/м.ngr), парсер відкидає — «вище теки», окремо.

  python3 самохостинг/звірити.py [--парсер] [-j 3] [--до N] [--від N] [--корінь РЕПО] [--кроки N] [шляхи…]

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
MODE = ['токени']             # або «дерево» (--парсер)
LEX = threading.Lock()         # таблиці еталона вантажаться ліниво й не для кількох потоків


def want(src):
    with LEX:
        return [[kind, val, line, col] for kind, val, (line, col) in nigredo.lex(src)]


class Skip(Exception):
    pass


def canon(n):
    """Дерево еталона (кортежі Parser) → вигляд, який друкує парсер на Nigredo: [вид, рядок, стовпець, …]. Дозволів печатки й
    субагента не порівнюємо: їх читає й перевіряє еталон. Висоту тіла λ порівнюємо: її бере межа роботи."""
    k, (line, col) = n[0], n[1]
    if k == 'lit':
        v = n[2]
        return [('str' if isinstance(v, str) else 'const' if v is None or isinstance(v, bool) else 'num'), line, col, v]
    if k == 'var':
        return ['var', line, col, n[2]]
    if k in ('call', 'op', 'tool'):
        return [k, line, col, n[2], [canon(x) for x in n[3]]]
    if k in ('list', 'dict', 'block'):
        return [k, line, col, [canon(x) for x in n[2]]]
    if k == 'tmpl':
        return [k, line, col, [['hole', x[1][0], x[1][1], canon(x[2])] if x[0] == 'hole' else canon(x) for x in n[2]]]
    if k == 'bind':
        return [k, line, col, n[2], canon(n[3])]
    if k == 'lam':
        return [k, line, col, [p if isinstance(p, str) else ['pat', p[1][0], p[1][1], p[2]] for p in n[2]], canon(n[3]), n[4]]
    if k == 'seal':
        return [k, line, col, n[2]]
    if k == 'deleg':
        return [k, line, col, n[2], n[3], canon(n[5])]
    if k == 'import':           # sha256 і справжній шлях — не будова дерева (парсер на Nigredo хешу не рахує)
        return [k, line, col, n[2], n[3], canon(n[4])]
    raise Skip(f'вузол {k}')


def want_tree(src, prog):
    with LEX:
        toks = nigredo.lex(src)
        for a, b in zip(toks, toks[1:]):
            if a[0] == 'glyph' and a[1] == '⊃' and b[0] == 'str' and (b[1].startswith('github.com/') or '#' in b[1]):
                raise Skip('з мережі')
        base = os.path.dirname(os.path.realpath(prog))
        return canon(nigredo.Parser(toks, base, base).program())


def module_paths(n, out):
    """Шляхи (від теки програми) усіх модулів у дереві, і вкладених теж."""
    if isinstance(n, list):
        if n and n[0] == 'import':
            out.append(n[3])
        for x in n:
            module_paths(x, out)
    return out


def nfc_names(n):
    """Імена в дереві парсера — до NFC, як їх зводить лексер еталона (лексер на Nigredo NFC не робить; звірка токенів це прощає так само)."""
    if not isinstance(n, list):
        return n
    nfc = lambda x: nigredo.unicodedata.normalize('NFC', x) if isinstance(x, str) else x  # noqa: E731
    if n and n[0] in ('var', 'call', 'bind') and len(n) > 3:
        n = n[:3] + [nfc(n[3])] + n[4:]
    elif n and n[0] == 'lam' and len(n) > 3 and isinstance(n[3], list):
        n = n[:3] + [[nfc(p) if isinstance(p, str) else p[:3] + [[nfc(x) for x in p[3]]] for p in n[3]]] + n[4:]
    return [nfc_names(x) for x in n]


def same_tree(a, b, path='дерево'):
    """Те саме дерево: числа — за значенням (і дріб лишається дробом); імена — після NFC (nfc_names)."""
    if isinstance(a, list) and isinstance(b, list):
        if a and a[0] == 'num' and len(a) == 4 and len(b) == 4 and b[0] == 'num' and isinstance(b[3], str):
            ok = a[1:3] == b[1:3] and decimal.Decimal(str(a[3])) == decimal.Decimal(b[3]) and ('.' in b[3]) == isinstance(a[3], decimal.Decimal)
            return '' if ok else f'{path}: еталон {a!r}, парсер {b!r}'
        if len(a) != len(b) or (a and isinstance(a[0], str) and a[0] != b[0]):
            return f'{path}: еталон {json.dumps(a, ensure_ascii=False, default=str)[:240]}, парсер {json.dumps(b, ensure_ascii=False)[:240]}'
        here = f'{path}/{a[0]}@{a[1]}:{a[2]}' if len(a) > 2 and isinstance(a[0], str) and isinstance(a[1], int) else path
        for x, y in zip(a, b):
            d = same_tree(x, y, here)
            if d:
                return d
        return ''
    return '' if a == b and type(a) is type(b) else f'{path}: еталон {a!r}, парсер {b!r}'


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
        a = want(src) if MODE[0] == 'токени' else want_tree(src, prog)
    except Skip as e:          # вузол, якого звірка не знає, — теж розбіжність: його треба навчити
        return prog, 'з мережі' if str(e) == 'з мережі' else 'різниця', str(e), 0, 0
    except nigredo.StaticError:
        return prog, 'відкинуто', '', 0, 0
    except RecursionError:
        return prog, 'відкинуто', '', 0, 0
    tp = time.perf_counter() - t0
    shutil.rmtree(work / 'вхід')
    (work / 'вхід').mkdir()
    if MODE[0] == 'дерево':
        base = os.path.dirname(os.path.realpath(prog))
        for rel in module_paths(a, []):
            (work / 'вхід' / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(os.path.join(base, rel), work / 'вхід' / rel)
    (work / 'вхід' / 'вхід.ngr').write_text(src, encoding='utf-8')
    t0 = time.perf_counter()
    r = subprocess.run([*CMD, '--кроки', str(steps), '--розмір', str(SIZE[0]), '--слід-розмір', str(20 * SIZE[0]), str(work / f'{MODE[0]}.ngr')], capture_output=True, env=dict(os.environ, NIGREDO_HOME=str(work / 'в')),
                       stdin=subprocess.DEVNULL, timeout=600)
    tn = time.perf_counter() - t0
    if r.returncode and MODE[0] == 'дерево' and 'вище теки програми' in r.stderr.decode('utf-8', 'replace'):
        return prog, 'вище теки', '', tp, tn
    if r.returncode:
        return prog, 'різниця', 'код ' + str(r.returncode) + ': ' + r.stderr.decode('utf-8', 'replace')[:300], tp, tn
    try:
        # » показує невидиме як ⟨U+…⟩, а справжній ⟨ — теж кодом: повернути, щоб порівнювати значення, а не вивід
        b = json.loads(re.sub(r'⟨U\+([0-9A-F]{4,6})⟩', lambda m: chr(int(m.group(1), 16)), r.stdout.decode('utf-8')))
    except ValueError as e:
        return prog, 'різниця', f'вивід не JSON: {e}', tp, tn
    d = same(a, b) if MODE[0] == 'токени' else same_tree(a, nfc_names(b))
    return prog, 'різниця' if d else 'так', d, tp, tn


def prepare(base):
    work = pathlib.Path(tempfile.mkdtemp(prefix='лексер-', dir=base))
    (work / 'вхід').mkdir()
    (work / 'в').mkdir()
    for f in ('лексер.ngr', 'токени.ngr', 'парсер.ngr', 'дерево.ngr'):
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
    ap.add_argument('--парсер', action='store_true', help='звіряти дерево розбору (парсер.ngr), а не токени')
    a = ap.parse_args()
    MODE[0] = 'дерево' if a.парсер else 'токени'
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
    print(f'Програм: {len(progs)}; однаково {cnt["так"]}, розбіжностей {cnt["різниця"]}, еталон відкинув {cnt["відкинуто"]}{f", з модулями з мережі {cnt['з мережі']}, модуль вище теки {cnt['вище теки']}" if a.парсер else ""}, завеликі {cnt["завеликий"]}, не utf-8 {cnt["не utf-8"]}')
    print(f'Час: еталон {tp:.1f} с, {"парсер" if a.парсер else "лексер"} на Nigredo {tn:.1f} с')
    sys.exit(2 if not cnt['так'] else 1 if cnt['різниця'] else 0)


main()
