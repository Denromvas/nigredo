#!/usr/bin/env python3
"""Звірка лексера й парсера на Nigredo з еталоном: той самий потік токенів (чи те саме дерево розбору, `--парсер`) на програмах
корпусу. Лексер — для правильних програм: те, що відкидає лексер еталона, не порівнюється, а лічиться окремо. Парсер (`--парсер`)
звіряється й на хибних: помилку розбору, яку він перевіряє сам (OWN — будова, імена, печатка зі змістом дозволів), має дати в
тому самому місці й тими самими словами; решту перевірок Parser еталона (двійники імен функцій і субагентів, невидимі символи в
намірі й дозволах, файли модулів) він не робить — такі програми лічаться окремо («інші перевірки»), і там парсер мусить лише не
зламатися. Двійників імен
(check_twins) і типи (§5а) звірка не запускає зовсім: порівнюється саме розбір. Модулі (⊃) парсер розбирає разом з програмою:
звірка кладе поруч файли, на які вказують ⊃. Окремо лічаться: модулі з мережі (сховище за sha256); шлях модуля, що виходить вище
теки програми й вертається в неї (тека/../тека/м.ngr), — парсер його відкидає («вище теки»); програми, яких парсер не подужав
через межі самої мови («глибина»: показ значення до 2000 рівнів — замало для дерева програми з ~1000 рівнів; до 1.3 ще й 2000
викликів) і через імена не в NFC (лексер еталона зводить їх до NFC, мова цього не вміє). Невидиме в тексті помилки (ключ словника, шлях) еталон показує
сам (↵, ⟨U+…⟩), а парсер лишає як є — показ робить виконавець, тож тексти порівнюються після того самого показу.

  python3 самохостинг/звірити.py [--парсер] [-j 3] [--до N] [--від N] [--корінь РЕПО] [--кроки N] [--перелік ПІДСУМОК] [шляхи…]

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


# Помилки розбору, які парсер на Nigredo перевіряє сам: початок тексту (після «у модулі «…»: ✗ р:с », якщо помилка — в модулі)
OWN = [re.compile(x) for x in (
    r'рядок закінчився, а виразові бракує аргументу', r'програма має починатися з печатки', r'незакрите «', r'зайва «',
    r'вираз уже завершено, а в рядку ще щось є', r'вираз вкладено глибше за', r'імʼя з крапкою «', r'«.*» ще обчислюється',
    r'невідоме імʼя «', r'у словнику 『』 має бути парна кількість', r'у словнику 『』 ключ «', r'шаблон обірвався',
    r'у \{…\} шаблону — рівно один вираз', r'«.*» тут не очікувалося', r'бракує аргументу: вираз обірвався', r'бракує «',
    r'після [λΛ←∘] очікувалося імʼя', r'[λΛ]【…】: розбір', r'однакові імена параметрів',
    r'⊃ — лише на початку інструкції верхнього рівня', r'⊃: шлях до модуля — буквальний рядок',
    r'⊃: імена — непорожній буквальний список рядків', r'⊃: модуль — відносний шлях до файлу \.ngr', r'⊃: циклічний імпорт «',
    r'у модулі «.*» немає «', r'«.*» уже назване тут', r'модуль на верхньому рівні лише називає функції',
    r'печатка 🜂 — лише одна', r'печатка: 🜂 「намір」', r'дозволи (печатки|субагента) мають бути буквальним списком рядків',
    r'після 🜔 очікувалася назва інструмента', r'невідомий інструмент «', r'інструмента «.*» немає в печатці',
    r'← називає лише на початку інструкції', r'∘ бере функцію, названу ←', r'🜁: імʼя \(і, за бажанням, намір\) субагента',
    # печатка: зміст дозволів
    r'(намір печатки|дозвіл печатки|дозвіл субагента|імʼя субагента|намір субагента|шлях модуля): пробіли поспіль чи по краях',
    r'(намір печатки|дозвіл печатки|дозвіл субагента|імʼя субагента|намір субагента|шлях модуля): символи 「」',
    r'дозвіл «.*»: квота — «≤N» у кінці', r'дозвіл «.*»: одна квота ≤N', r'дозвіл «.*»: квота ≤0', r'дві квоти на «',
    r'невідомий інструмент у дозволах: «', r'«.*» потребує обмеження: «', r'«.*»: команда — імʼя з PATH',
    r'«.*»: функція — повна назва', r'субагент «.*» просить «.*», якого немає в батька', r'субагент «.*» просить «.*» — у батька',
    r'модуль «.*» просить «.*», якого немає в печатці програми', r'модуль «.*» просить «.*» — ширше, ніж у печатці програми')]
IN_MODULE = re.compile(r'у модулі «.*?»: ✗ (?:\d+:\d+ )?')
# що парсер каже, коли справа не в будові програми: цього з еталоном не звірити
NOT_HERE = ('⊃: модулі з мережі цей парсер не розбирає', 'не прочитати: ', 'невідомий символ')


def own(msg):
    """Чи це помилка, яку парсер на Nigredo перевіряє сам (і в модулі, і в модулі модуля)."""
    while (m := IN_MODULE.match(msg)):
        msg = msg[m.end():]
    return any(r.match(msg) for r in OWN)


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


def after_import(toks):
    """Рядки одразу після ⊃ (перенос рядка між ними — теж): шляхи модулів, як їх шукає `шляхи_модулів` парсера."""
    out = []
    for i, a in enumerate(toks):
        if a[0] == 'glyph' and a[1] == '⊃':
            j = i + 1
            while toks[j][0] == 'nl':
                j += 1
            if toks[j][0] == 'str':
                out.append(toks[j][1])
    return out


def want_tree(src, prog):
    """Дерево еталона з помилками типів (§5а) або його помилка розбору: ('дерево', (дерево, [[рядок, стовпець, текст]…]), токени)
    чи ('помилка', 'рядок:стовпець текст', токени). Як у справжньому запуску, файл програми — у стеку модулів: модуль, що бере
    саму програму, — коло."""
    with LEX:
        toks = nigredo.lex(src)                 # помилка лексера — StaticError: «відкинуто»
        if any(p.startswith('github.com/') or '#' in p for p in after_import(toks)):
            raise Skip('з мережі')
        base = os.path.dirname(os.path.realpath(prog))
        try:
            tree = nigredo.Parser(toks, base, base, stack=(os.path.realpath(prog),)).program()
            return 'дерево', (canon(tree), [[e.pos[0], e.pos[1], e.msg] for e in nigredo.type_errors(tree)]), toks
        except nigredo.StaticError as e:
            return 'помилка', f'{e.pos[0]}:{e.pos[1]} {e.msg}', toks


def put_modules(toks, base, here, dest, seen):
    """Покласти в dest файли, на які вказують ⊃ програми та її модулів (що читатиме дерево.ngr): лише .ngr у теці програми."""
    for rel in after_import(toks):
        if not rel.endswith('.ngr') or rel.startswith('/') or '://' in rel or '#' in rel:
            continue
        path = os.path.normpath(os.path.join(here, rel))
        if path.startswith('..') or os.path.isabs(path) or path in seen:
            continue
        seen.add(path)
        real = os.path.join(base, path)
        if not os.path.isfile(real) or os.path.getsize(real) > 400000:
            continue
        (dest / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(real, dest / path)
        try:
            with LEX:
                sub = nigredo.lex(open(real, 'rb').read().decode('utf-8'), module=True)
        except (nigredo.StaticError, UnicodeDecodeError, RecursionError):
            continue
        put_modules(sub, base, os.path.dirname(path), dest, seen)


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
    kind, err, toks = 'дерево', '', None
    try:
        if MODE[0] == 'токени':
            a = want(src)
        else:
            kind, a, toks = want_tree(src, prog)
            if kind == 'помилка':
                a, err = None, a
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
        put_modules(toks, os.path.dirname(os.path.realpath(prog)), '', work / 'вхід', set())
    # парсерові — під власним імʼям: модуль, що бере саму програму, — коло (лексер читає вхід.ngr)
    name = os.path.basename(prog) if MODE[0] == 'дерево' else 'вхід.ngr'
    (work / 'вхід' / name).write_text(src, encoding='utf-8')
    t0 = time.perf_counter()
    r = subprocess.run([*CMD, '--кроки', str(steps), '--розмір', str(SIZE[0]), '--слід-розмір', str(20 * SIZE[0]), str(work / f'{MODE[0]}.ngr'),
                        *(['--', name] if MODE[0] == 'дерево' else [])], capture_output=True, env=dict(os.environ, NIGREDO_HOME=str(work / 'в')),
                       stdin=subprocess.DEVNULL, timeout=600)
    tn = time.perf_counter() - t0
    if r.returncode and MODE[0] == 'дерево' and any(x in r.stderr.decode('utf-8', 'replace') for x in ('надто глибока рекурсія', 'Δ: значення вкладене надто глибоко')):
        # межі самої мови: значення глибше за 2000 рівнів не показати (дерево програми з ~1000 рівнів — це ~2000 рівнів
        # списків); до 1.3 — ще й 2000 викликів, менше, ніж треба парсерові на 1000 рівнів дужок
        return prog, 'глибина', r.stderr.decode('utf-8', 'replace').strip()[:120], tp, tn
    if r.returncode:
        return prog, 'різниця', 'код ' + str(r.returncode) + ': ' + r.stderr.decode('utf-8', 'replace')[:300], tp, tn
    try:
        # » показує невидиме як ⟨U+…⟩, а справжній ⟨ — теж кодом: повернути, щоб порівнювати значення, а не вивід
        b = json.loads(re.sub(r'⟨U\+([0-9A-F]{4,6})⟩', lambda m: chr(int(m.group(1), 16)), r.stdout.decode('utf-8')))
    except ValueError as e:
        return prog, 'різниця', f'вивід не JSON: {e}', tp, tn
    if MODE[0] == 'токени':
        d = same(a, b)
        return prog, 'різниця' if d else 'так', d, tp, tn
    mine = b.get('помилка') if isinstance(b, dict) else None
    if mine is not None and 'вище теки програми' in mine and not (err and own(err.split(' ', 1)[1])):
        return prog, 'вище теки', '', tp, tn
    if err and not own(err.split(' ', 1)[1]):
        # перевірка, якої парсер не робить: він мусить дати дерево чи свою помилку розбору, а не зламатися всередині
        text = mine.split(' ', 1)[-1] if mine is not None else ''
        broke = mine is not None and not own(text) and not IN_MODULE.match(text) and not any(x in text for x in NOT_HERE)
        return prog, 'різниця' if broke else 'інші перевірки', f'еталон: {err[:200]}; парсер зламався: {mine[:300]}' if broke else '', tp, tn
    nfc = lambda x: nigredo.unicodedata.normalize('NFC', x)  # noqa: E731
    # лексер еталона зводить імена до NFC; мова цього не вміє: імʼя в тексті помилки порівнюємо після NFC (як імена в дереві),
    # а коли через це імʼя «не знайдено» — лічимо окремо
    lost = mine is not None and 'невідоме імʼя «' in mine and nfc(src) != src
    if err:
        ok = mine is not None and nigredo.safe(nfc(mine)) == nigredo.safe(nfc(err))
        if not ok and lost:
            return prog, 'не NFC', '', tp, tn
        return prog, 'та сама помилка' if ok else 'різниця', '' if ok else f'еталон: {err[:400]}\n  парсер: {(mine if mine is not None else "дерево")[:400]}', tp, tn
    if lost:
        return prog, 'не NFC', '', tp, tn
    if mine is not None:
        return prog, 'різниця', f'еталон розібрав, парсер: {mine[:400]}', tp, tn
    tree, types = a
    d = same_tree(tree, nfc_names(b['дерево']))
    if not d:                  # ті самі помилки типів у тому самому порядку: місце й слова
        got = [[x[0], x[1], nigredo.safe(nfc(x[2]))] for x in b['типи']]
        want_t = [[x[0], x[1], nigredo.safe(nfc(x[2]))] for x in types]
        if got != want_t:
            k = next((i for i, (x, y) in enumerate(zip(want_t, got)) if x != y), min(len(want_t), len(got)))
            d = (f'помилки типів: еталон {len(want_t)}, парсер {len(got)}; перша різниця №{k + 1}: еталон '
                 f'{want_t[k] if k < len(want_t) else "—"}, парсер {got[k] if k < len(got) else "—"}')[:900]
    return prog, 'різниця' if d else 'так з типами' if types else 'так', d, tp, tn


def prepare(base):
    work = pathlib.Path(tempfile.mkdtemp(prefix='лексер-', dir=base))
    (work / 'вхід').mkdir()
    (work / 'в').mkdir()
    for f in ('лексер.ngr', 'токени.ngr', 'парсер.ngr', 'типи.ngr', 'дерево.ngr'):
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
    ap.add_argument('--перелік', default='', help='надрукувати програми з цим підсумком (глибина, «не NFC», «інші перевірки», …)')
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
    sys.setrecursionlimit(10_000_000)          # як entry() еталона: вкладеність до MAX_NEST розбирає він, а не межа Python
    threading.stack_size(512 * 1024 * 1024)
    base = tempfile.mkdtemp(prefix='лексер-звірка-')
    works = [prepare(base) for _ in range(a.j)]
    free = list(works)
    cnt, tp, tn = Counter(), 0.0, 0.0
    typed = [0]
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
                if r == 'так з типами':            # дерево те саме, і помилки типів (вони є) — ті самі
                    r, typed[0] = 'так', typed[0] + 1
                cnt[r] += 1
                tp += x
                tn += y
                if r == 'різниця':
                    print(f'✗ {os.path.relpath(p, a.корінь)}\n  {d}', flush=True)
                elif r == a.перелік:
                    print(f'· {r}: {os.path.relpath(p, a.корінь)}{"  — " + d if d else ""}', flush=True)
                if i % 200 == 0:
                    print(f'… {i}/{len(progs)}', flush=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    if a.парсер:
        print(f'Програм: {len(progs)}; те саме дерево {cnt["так"]} (з них {typed[0]} — з тими самими помилками типів), та сама помилка розбору {cnt["та сама помилка"]}, розбіжностей '
              f'{cnt["різниця"]}; парсер не подужав: глибина {cnt["глибина"]}, імена не в NFC {cnt["не NFC"]}; не '
              f'порівнювались: інші перевірки еталона {cnt["інші перевірки"]}, відкинув лексер еталона {cnt["відкинуто"]}, з '
              f'модулями з мережі {cnt["з мережі"]}, модуль вище теки {cnt["вище теки"]}, завеликі {cnt["завеликий"]}, не utf-8 '
              f'{cnt["не utf-8"]}')
    else:
        print(f'Програм: {len(progs)}; однаково {cnt["так"]}, розбіжностей {cnt["різниця"]}, еталон відкинув {cnt["відкинуто"]}, '
              f'завеликі {cnt["завеликий"]}, не utf-8 {cnt["не utf-8"]}')
    print(f'Час: еталон {tp:.1f} с, {"парсер" if a.парсер else "лексер"} на Nigredo {tn:.1f} с')
    sys.exit(2 if not cnt['так'] else 1 if cnt['різниця'] else 0)


if __name__ == '__main__':
    main()
