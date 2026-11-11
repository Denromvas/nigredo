#!/usr/bin/env python3
"""Мутанти: парсер на Nigredo проти еталона на зіпсованих програмах. Корпус має сотні хибних програм, але їх писали люди й
судді, тож шляхи помилок у ньому нерівні. Тут правильну програму псують в одному місці — прибирають токен, подвоюють, міняють
сусідні місцями, вставляють гліф, дужку, імʼя, число, рядок чи перенос рядка, обривають текст, зливають рядки — і звіряють
розбір так само, як `звірити.py --парсер`: те саме дерево з тими самими помилками типів або та сама помилка розбору (місце й
слова). Кожен пʼятий мутант — у рядку печатки, прав субагента чи шляху ⊃: квота, пробіли, дужки, вужче й ширше обмеження, інший
інструмент. «Замінити» лишає розбір, а міняє тип: літерал — іншим літералом, гліф — гліфом тієї самої арності.

  python3 самохостинг/мутанти.py [-n 2000] [--зерно 1] [-j 8] [--на-програму 4] [--лишити ТЕКА] [--перелік ПІДСУМОК]
                                 [--виконавець КОМАНДА] [шляхи…]

Насіння — програми до 3000 знаків, які еталон розбирає (без модулів з мережі): з названих тек і файлів, а без них — з усього,
що відстежує git. У програмі з модулями (⊃) псується або вона, або один з її модулів: так перевіряються й помилки «у модулі
«…»: …». Те саме зерно на тих самих програмах дає тих самих мутантів. Вихід: 0 — розбіжностей немає; 1 — є (мутанти з розбіжністю
лишаються в теці, її імʼя друкується); 2 — мутантів немає."""
import argparse
import concurrent.futures as cf
import importlib.util
import os
import pathlib
import random
import shutil
import subprocess
import sys
import tempfile
import threading
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('звірити', HERE / 'звірити.py')
zv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(zv)
nigredo = zv.nigredo

# що вставляти: гліфи всіх арностей, особливі форми, дужки, шаблон, літерали, роздільники
PIECES = ['＋', '×', '¬', 'ρ', '¿', 'Σ', 'μ', 'φ', '↻', '☂', '§', '✎', '»', '☠', '⌂', '∅', '●', 'λ', 'Λ', '←', '∘', '🜔', '🜔час',
          '🜔читати', '🜔нема', '🜂', '🜁', '⊃', '【', '】', '『', '』', '《', '》', '〔т{', '}х〕', '〔т〕', '7', '¯3', '0.50', '007',
          '「х」', '「」', '¦', '\n', '\n      ', '\n  ', 'No', 'файл.читати', 'нема_такого']


def offsets(src, toks):
    """Початок кожного токена в тексті (за рядком і стовпцем лексера)."""
    starts, at = [0], 0
    for line in src.split('\n'):
        at += len(line) + 1
        starts.append(at)
    return [starts[t[2][0] - 1] + t[2][1] - 1 for t in toks]


PERMS = ['час', 'оракул', 'жереб', 'читати:дані', 'писати:тимч', 'список:.', 'бд.читати:дані', 'взяти:api.x', 'послати:api.x≤2',
         'процес:git status', 'процес:./a', 'процес:/bin/ls', 'агент:помічник', 'python:statistics.median', 'python:_x.y',
         'python:statistics', 'нема:х', 'файл.читати:дані/звіти', 'читати писати:тимч', 'читати', '']


def perm_variants(v, rnd):
    """Зіпсований (чи ні) дозвіл: квоти, пробіли, дужки, вужче й ширше обмеження, інший інструмент."""
    tool, sep, scope = v.partition(':')
    return rnd.choice([
        v + '≤3', v + '≤0', v + '≤ 5', v + '≤x', v + '≤3≤4', '≤2' + v, v + '≤007',
        ' ' + v, v + ' ', v.replace(':', ' : ', 1), v.replace(':', ': ', 1), v.replace(' ', '  ', 1) if ' ' in v else v + '  x',
        v + '「', v + '」', v + '/', tool, tool + ':', v + '/..', v + '/підтека', v + '/../..', tool + sep + '..', tool + sep + '/etc',
        tool + sep + '.', tool + sep + './' + scope, v + '//x', tool + sep + '//' + scope, tool + sep + scope + ' -x',
        'читати ' + v, 'час ' + v, tool + ' ' + tool + sep + scope, rnd.choice(PERMS), rnd.choice(PERMS).partition(':')[0] + sep + scope])


def mutate_perm(src, toks, off, rnd):
    """Мутант у рядку печатки, субагента чи ⊃: рядки першої інструкції, шість токенів після 🜁 і рядок після ⊃."""
    first = next((t[2][0] for t in toks if t[0] != 'nl'), 1)
    where = [i for i, t in enumerate(toks[:-1]) if t[0] == 'str' and (
        t[2][0] == first or any(x[0] == 'glyph' and x[1] in '🜁⊃' for x in toks[max(0, i - 6):i]))]
    if not where:
        return None
    i = rnd.choice(where)
    new = perm_variants(toks[i][1], rnd)
    lit = '「' + new.replace('\\', '\\\\').replace('」', '\\」').replace('\n', '\\n').replace('\t', '\\t') + '」'
    return 'у дозволі', src[:off[i]] + lit + ' ' + src[off[i + 1]:] if toks[i + 1][0] != 'nl' else src[:off[i]] + lit + src[off[i + 1]:]


def mutate(src, toks, rnd):
    """Один мутант: (назва мутації, текст)."""
    off = offsets(src, toks)
    if rnd.random() < 0.2:
        m = mutate_perm(src, toks, off, rnd)
        if m:
            return m
    n = len(toks) - 1                       # без eof
    i = rnd.randrange(n)
    a, b = off[i], off[i + 1]
    names = [t[1] for t in toks if t[0] == 'name'] or ['х']
    op = rnd.choice(['прибрати', 'прибрати', 'подвоїти', 'поміняти', 'вставити', 'вставити', 'вставити', 'обірвати', 'злити', 'перенести',
                     'замінити', 'замінити', 'замінити'])
    if op == 'замінити':                    # той самий розбір, інший тип: літерал — іншим літералом, гліф — гліфом тієї ж арності
        kind, val = toks[i][0], toks[i][1]
        piece = None
        if kind in ('num', 'str') or (kind == 'glyph' and val in nigredo.CONSTS):
            piece = rnd.choice(['5', '0', '「а」', '「(」', '●', '∅', '【1 2】', '【「а」】', '『「к」 1』'])
        elif kind == 'glyph' and val in nigredo.GLYPHS and isinstance(nigredo.GLYPHS[val][0], int) and val != '🜁':
            same = [g for g, sp in nigredo.GLYPHS.items() if sp[0] == nigredo.GLYPHS[val][0] and g != val and g != '🜁' and g not in nigredo.CONSTS]
            piece = rnd.choice(same) if same else None
        if piece:
            return op, src[:a] + piece + (' ' if toks[i + 1][0] != 'nl' else '') + src[b:]
        op = 'прибрати'
    if op == 'прибрати':
        return op, src[:a] + src[b:]
    if op == 'подвоїти':
        return op, src[:a] + src[a:b] + ' ' + src[a:]
    if op == 'поміняти' and i + 2 <= n:
        c = off[i + 2]
        return op, src[:a] + src[b:c] + ' ' + src[a:b] + src[c:]
    if op == 'обірвати':
        return op, src[:a].rstrip(' ') if rnd.random() < 0.5 else src[:a]
    if op == 'злити':
        nl = [k for k, ch in enumerate(src) if ch == '\n']
        if nl:
            k = rnd.choice(nl)
            return op, src[:k] + ' ' + src[k + 1:]
    if op == 'перенести':
        return op, src[:a] + rnd.choice(['\n', '\n    ', '\n        ', ' ¦ ']) + src[a:]
    piece = rnd.choice(PIECES + names[:8])
    return 'вставити', src[:a] + piece + ' ' + src[a:]


def seeds(root, paths, rnd, want):
    if paths:
        progs = []
        for p in paths:
            progs += sorted(str(x) for x in pathlib.Path(p).resolve().rglob('*.ngr')) if os.path.isdir(p) else [os.path.abspath(p)]
    else:
        names = subprocess.run(['git', '-C', root, 'ls-files', '-z', '--', '*.ngr'], capture_output=True).stdout.decode('utf-8', 'surrogateescape').split('\0')
        progs = sorted(os.path.join(root, n) for n in names if n and not n.startswith('архів/'))
    rnd.shuffle(progs)
    out = []
    for p in progs:
        try:
            src = open(p, 'rb').read().decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
        except (UnicodeDecodeError, OSError):
            continue
        if not 20 < len(src) <= 3000:
            continue
        try:
            kind, _, toks = zv.want_tree(src, p)
        except (zv.Skip, nigredo.StaticError, RecursionError):
            continue
        if kind == 'дерево' and len(toks) > 4:
            out.append((p, src, toks))
            if len(out) >= want:
                break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-n', type=int, default=2000, help='скільки мутантів')
    ap.add_argument('--зерно', type=int, default=1)
    ap.add_argument('-j', type=int, default=8)
    ap.add_argument('--на-програму', type=int, default=4, dest='per')
    ap.add_argument('--кроки', type=int, default=200000000)
    ap.add_argument('--виконавець', default='')
    ap.add_argument('--корінь', default=str(zv.ROOT))
    ap.add_argument('--лишити', default='', help='тека для мутантів з розбіжністю (типово — тимчасова)')
    ap.add_argument('--перелік', default='', help='надрукувати мутантів з цим підсумком (глибина, «не NFC», «інші перевірки», …)')
    ap.add_argument('шляхи', nargs='*', help='звідки брати насіння (типово — весь корпус)')
    a = ap.parse_args()
    zv.MODE[0] = 'дерево'
    zv.CMD[:] = a.виконавець.split() or zv.CMD
    rnd = random.Random(a.зерно)
    sys.setrecursionlimit(10_000_000)
    threading.stack_size(512 * 1024 * 1024)
    base = pathlib.Path(tempfile.mkdtemp(prefix='мутанти-'))
    (base / 'м').mkdir()
    jobs = []
    for p, src, toks in seeds(a.корінь, a.шляхи, rnd, (a.n + a.per - 1) // a.per):
        for _ in range(a.per):
            if len(jobs) >= a.n:
                break
            d = base / 'м' / f'{len(jobs):05d}'       # кожному мутантові — своя тека: програма й копії її модулів
            d.mkdir()
            mods = set()
            zv.put_modules(toks, os.path.dirname(os.path.realpath(p)), '', d, mods)
            mods = sorted(m for m in mods if (d / m).is_file())
            op, text = None, src
            if mods and rnd.random() < 0.6:           # зіпсувати модуль, а не програму
                mf = d / rnd.choice(mods)
                try:
                    msrc = mf.read_bytes().decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
                    with zv.LEX:
                        mtoks = nigredo.lex(msrc, module=True)
                    if len(mtoks) > 2:
                        op, mtext = mutate(msrc, mtoks, rnd)
                        op = 'у модулі: ' + op
                        mf.write_text(mtext, encoding='utf-8')
                except (UnicodeDecodeError, nigredo.StaticError):
                    pass
            if op is None:
                op, text = mutate(src, toks, rnd)
            f = d / os.path.basename(p)
            f.write_text(text, encoding='utf-8')
            jobs.append((str(f), op, p))
    works = [zv.prepare(str(base)) for _ in range(a.j)]
    free, lock = list(works), threading.Lock()

    def job(j):
        with lock:
            w = free.pop()
        try:
            return j, zv.one(j[0], w, a.кроки)
        finally:
            with lock:
                free.append(w)
    cnt, by_op, bad, typed = Counter(), Counter(), [], 0
    with cf.ThreadPoolExecutor(a.j) as ex:
        for (f, op, p), (_, r, d, _, _) in ex.map(job, jobs):
            if r == 'так з типами':
                r, typed = 'так', typed + 1
            cnt[r] += 1
            by_op[op, r] += 1
            if r == 'різниця':
                bad.append(f)
                print(f'✗ {os.path.basename(os.path.dirname(f))} ({op}; з {os.path.relpath(p, a.корінь)})\n  {d}', flush=True)
            elif r == a.перелік:
                print(f'· {r}: {op}; з {os.path.relpath(p, a.корінь)}{"  — " + d if d else ""}', flush=True)
    print(f'Мутантів: {len(jobs)} (зерно {a.зерно}); те саме дерево {cnt["так"]} (з них {typed} — з тими самими помилками типів), та сама помилка розбору {cnt["та сама помилка"]}, '
          f'розбіжностей {cnt["різниця"]}; парсер не подужав: глибина {cnt["глибина"]}, імена не в NFC {cnt["не NFC"]}; не '
          f'порівнювались: інші перевірки еталона {cnt["інші перевірки"]}, відкинув лексер еталона {cnt["відкинуто"]}, решта '
          f'{sum(v for k, v in cnt.items() if k not in ("так", "та сама помилка", "різниця", "глибина", "не NFC", "інші перевірки", "відкинуто"))}')
    print('За мутацією (та сама помилка / усього): ' + ', '.join(
        f'{op} {by_op[op, "та сама помилка"]}/{sum(v for (o, _), v in by_op.items() if o == op)}' for op in sorted({o for o, _ in by_op})))
    if bad:
        keep = pathlib.Path(a.лишити or tempfile.mkdtemp(prefix='мутанти-розбіжні-'))
        keep.mkdir(parents=True, exist_ok=True)
        for f in bad:
            shutil.copytree(os.path.dirname(f), keep / os.path.basename(os.path.dirname(f)), dirs_exist_ok=True)
        print(f'Мутанти з розбіжністю: {keep}')
    shutil.rmtree(base, ignore_errors=True)
    sys.exit(1 if cnt['різниця'] else 0 if jobs else 2)


if __name__ == '__main__':
    main()
