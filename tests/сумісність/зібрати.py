#!/usr/bin/env python3
"""Набір сумісності 1.0 (spec/пропозиції/1.0.md §5): зразки, які кожна 1.x мусить прийняти так само, як 1.0.

Запускається ОДИН раз — при оголошенні 1.0 (кандидата — `1.0-rc`); після оголошення зразки не перегенеровують: інакше
набір перевіряв би сам себе. `--заново` — лише до оголошення 1.0.

- `слід/` — програма, її дані, слід і СЛІД.дані з тестовим ключем сліду `власник/ключ` (ключ лише для тестів, не
  секрет), очікуваний вивід. Кожна 1.x мусить перевірити слід «✓» і повторити його з тим самим виводом — і в іншій
  теці (слід записує теку, де його зроблено, але перевірка й повтор від неї не залежать).
- `підпис/` — програма, підписана ключем «зразок 1.0» (насіння знищено одразу після підпису), відкритий ключ і вивід:
  кожна 1.x мусить сказати «підпис цілий» і з правами ключа дати той самий вивід.
- `печатка/` — програми й стабільні поля `--печатка --json` (тека — `<тека>`, шляхи власника відкинуто): кожна 1.x
  мусить мати ці поля з тими самими значеннями (нові поля — можна).
"""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

D = pathlib.Path(__file__).resolve().parent
ROOT = D.parent.parent
NGR = [sys.executable, str(ROOT / 'interpreter' / 'ngr.py')]
DROP = ('тека', 'програма', 'дозволи_власника')
TRACE_KEY = hashlib.sha256('nigredo 1.0 — тестовий ключ сліду набору сумісності'.encode()).hexdigest()


def norm(v, base):
    """Стабільна форма відповіді: тека програми → «<тека>», поля зі шляхами власника — геть."""
    if isinstance(v, dict):
        return {k: norm(x, base) for k, x in v.items() if k not in DROP}
    if isinstance(v, list):
        return [norm(x, base) for x in v]
    if isinstance(v, str):
        return v.replace(base, '<тека>')
    return v


TEMP = []


def home(perms):
    h = pathlib.Path(tempfile.mkdtemp(prefix='сумісність-'))
    TEMP.append(h)
    (h / 'ключ').write_text(TRACE_KEY + '\n', encoding='utf-8')
    (h / 'дозволи.json').write_text(json.dumps(perms, ensure_ascii=False), encoding='utf-8')
    return h


def run(args, h, cwd):
    env = dict(os.environ, NIGREDO_HOME=str(h))
    env.pop('NIGREDO_TRACE_PATH_FILE', None)
    p = subprocess.run([*NGR, *args], capture_output=True, text=True, env=env, cwd=cwd)
    if p.returncode != 0:
        sys.exit(f'✗ ngr {" ".join(args)}: код {p.returncode}\n{p.stderr}')
    return p.stdout


def main():
    if (D / 'слід' / 'слід.jsonl').exists() and '--заново' not in sys.argv:
        sys.exit('зразки вже є — після оголошення 1.0 їх не перегенеровують (до нього — --заново)')
    for sub in ('слід', 'підпис', 'печатка', 'власник'):
        shutil.rmtree(D / sub, ignore_errors=True)
        (D / sub).mkdir()
    (D / 'власник' / 'ключ').write_text(TRACE_KEY + '\n', encoding='utf-8')

    # слід
    s = D / 'слід'
    (s / 'дані').mkdir()
    (s / 'дані' / 'рядки.txt').write_text('Агент читає програму.\nПечатка каже, що можна.\n', encoding='utf-8')
    (s / 'програма.ngr').write_text(
        '🜂 「зразок сліду 1.0: читання, регулярка, субагент, жереб, памʼять, щит」 【「читати:дані」 「жереб≤3」 「оракул」】\n'
        '🜄 「поріг」 0.6\n'
        '← текст 🜔читати 「дані/рядки.txt」\n'
        '← слова ⌕ ⇣ текст 「\\w+」\n'
        '» ＋ 「слів: 」 σρслова\n'
        '← кістка 🜔жереб 6\n'
        '» ＋ 「кістка: 」 σкістка\n'
        '← спитати λq 🜁 「провидець」 「спитати оракула」 【「оракул」】 🜔оракул q\n'
        '» спитати 「чи світ чорніє?」\n'
        '» ☂ 🜍 「ртуть」 λx ›ρx 10 λe ＋ 「щит: 」 e\n'
        '» ＋ 「поріг: 」 σ🜃「поріг」\n', encoding='utf-8')
    h = home({'дозволено': [f'читати:{s}/дані', 'жереб', 'оракул']})
    out = run(['--зерно', '7', '--слід', str(s / 'слід.jsonl'), str(s / 'програма.ngr')], h, s)
    (s / 'вивід.txt').write_text(out, encoding='utf-8')

    # підпис
    p = D / 'підпис'
    (p / 'дані').mkdir()
    (p / 'дані' / 'а.txt').write_text('підписано 1.0\n', encoding='utf-8')
    prog = p / 'програма.ngr'
    prog.write_text('🜂 「зразок підпису 1.0」 【「читати:дані」】\n» 🜔читати 「дані/а.txt」\n', encoding='utf-8')
    kf = pathlib.Path(tempfile.mkdtemp(prefix='сумісність-ключ-')) / 'зразок.ключ'
    h = home({'дозволено': []})
    pub = run(['--ключ-автора', str(kf)], h, p).split()[0]
    run(['--підписати', str(prog), '--ключ', str(kf)], h, p)
    shutil.rmtree(kf.parent)                         # насіння знищено: підписати ще раз не може ніхто
    (p / 'ключ.txt').write_text(pub + '\n', encoding='utf-8')
    h = home({'дозволено': [], 'для_авторів': {pub: {'імʼя': 'зразок 1.0', 'дозволи': [f'читати:{p}/дані']}}})
    (p / 'вивід.txt').write_text(run([str(prog)], h, p), encoding='utf-8')

    # печатка
    q = D / 'печатка'
    progs = {
        'проста.ngr': '🜂 「проста」 【】\n» ＋ 1 2\n',
        'квоти.ngr': '🜂 「квоти й субагент」 【「читати:.」 「жереб≤2」】\n'
                     '» 🜁 「лічильник」 「кинути раз」 【「жереб≤1」】 🜔жереб 6\n',
        'міст.ngr': '🜂 「міст до Python」 【「python:statistics.median≤2」】\n» 🜔python 「statistics.median」 【【3 1 2】】\n',
    }
    h = home({'дозволено': [f'читати:{q}', 'жереб', 'python:statistics.median']})
    for name, text in progs.items():
        (q / name).write_text(text, encoding='utf-8')
        info = json.loads(run(['--печатка', '--json', str(q / name)], h, q))
        (q / (name[:-4] + '.json')).write_text(json.dumps(norm(info, str(q)), ensure_ascii=False, indent=1) + '\n',
                                               encoding='utf-8')
    for t in TEMP:
        shutil.rmtree(t, ignore_errors=True)
    print(f'зібрано: {D}')


if __name__ == '__main__':
    main()
