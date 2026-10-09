#!/usr/bin/env python3
"""Зібрати сайт: site/src/* + справжні приклади, вивід, слід і переклад → site/index.html.

Результат — один самодостатній файл (CSS і JS вбудовані): так він відкривається
з памʼяті телефона, де відносні посилання на сусідні файли часто ламаються.
Поруч кладеться копія SPEC.md. Якщо існує PHONE_DIR — туди теж копіюється.

    python3 site/build.py            зібрати й скопіювати на телефон
    python3 site/build.py --local    лише зібрати
"""
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / 'site'
SRC = SITE / 'src'
INTERP = ROOT / 'interpreter' / 'nigredo.py'
PHONE_DIR = pathlib.Path('/storage/emulated/0/with_termux/nigredo-site')

sys.path.insert(0, str(INTERP.parent))
import nigredo  # noqa: E402

EXAMPLES = [
    ('poklyk', 'Заклик', 'друк, список, цикл'),
    ('chysla', 'Числа', 'рекурсія, відсів, згортка'),
    ('ahent', 'Агент', 'намір, делегування, довіра, перевірка'),
]

# Групи алфавіту; кожен гліф інтерпретатора має потрапити рівно в одну.
GROUPS = [
    ('Стек', '⧉⏚⇄⇈⟲'),
    ('Числа', '⊕⊖⊗⨸⦼⌊⁻'),
    ('Порівняння й логіка', '≡≢≺≻≼≽⋏⋎⌐'),
    ('Рядки й списки', '♯⌷⧺⊹⇋⋯⫽⫻⍕⍎'),
    ('Керування', '⍟⋔⟳⧖⁘⇶⋐∮☠⛉'),
    ('Вивід', '⎙⌸'),
    ('Константи', '☉☽∅'),
    ('Довіра', '☿⚖⚗'),
    ('Агент', '🜂🜔🜄🜃🜁🜍'),
]
STRUCTURE = [
    ('⌜ ⌟', 'блок — код як значення'),
    ('⟬ ⟭', 'список'),
    ('⟪ ⟫', 'рядок'),
    ('⸸', 'коментар до кінця рядка'),
    ('⊸ ⊷ ⊶', 'назвати: значення · локально · словом'),
    ('０…９', 'цифри'),
    ('ᚠ…ᛪ', 'імена — лише руни'),
]


def run(*args):
    r = subprocess.run([sys.executable, str(INTERP), *args], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f'інтерпретатор упав на {args}:\n{r.stderr}')
    return r.stdout, r.stderr


def collect():
    grouped = ''.join(g for _, gs in GROUPS for g in gs)
    missing = set(nigredo.GLOSS) - set(grouped)
    extra = set(grouped) - set(nigredo.GLOSS)
    if missing or extra or len(grouped) != len(set(grouped)):
        sys.exit(f'алфавіт розійшовся з інтерпретатором: бракує {missing}, зайві {extra}')

    examples = []
    for stem, title, about in EXAMPLES:
        path = ROOT / 'examples' / f'{stem}.ngr'
        code = path.read_text(encoding='utf-8')
        out, _ = run(str(path))
        expected = path.with_suffix('.out').read_text(encoding='utf-8')
        if out != expected:
            sys.exit(f'{path.name}: вивід не збігається з {path.stem}.out — спершу interpreter/test.py')
        _, trace = run('--слід', str(path))
        examples.append({
            'file': path.name, 'title': title, 'about': about,
            'code': code.rstrip('\n'), 'out': out.rstrip('\n'), 'trace': trace.rstrip('\n'),
            'lines': [{'no': no, 'text': text, 'gloss': gloss}
                      for no, text, gloss in nigredo.explain_lines(code)],
        })
    return {
        'examples': examples,
        'groups': [{'name': n, 'glyphs': [{'g': g, 'm': nigredo.GLOSS[g]} for g in gs]}
                   for n, gs in GROUPS],
        'structure': [{'g': g, 'm': m} for g, m in STRUCTURE],
        'spec': (ROOT / 'spec' / 'SPEC.md').read_text(encoding='utf-8'),
    }


def main():
    data = json.dumps(collect(), ensure_ascii=False).replace('</', '<\\/')
    html = (SRC / 'index.html').read_text(encoding='utf-8')
    css = (SRC / 'style.css').read_text(encoding='utf-8')
    js = (SRC / 'app.js').read_text(encoding='utf-8')
    for marker, value in (('/*@CSS*/', css), ('/*@DATA*/', f'const NGR = {data};'), ('/*@JS*/', js)):
        if marker not in html:
            sys.exit(f'у src/index.html немає мітки {marker}')
        html = html.replace(marker, value)
    (SITE / 'index.html').write_text(html, encoding='utf-8')
    shutil.copy(ROOT / 'spec' / 'SPEC.md', SITE / 'SPEC.md')
    print(f'зібрано: {SITE / "index.html"} ({len(html.encode()) // 1024} КБ)')
    if '--local' not in sys.argv and PHONE_DIR.parent.exists():
        PHONE_DIR.mkdir(exist_ok=True)
        for name in ('index.html', 'SPEC.md'):
            shutil.copy(SITE / name, PHONE_DIR / name)
        print(f'скопійовано: {PHONE_DIR}')


if __name__ == '__main__':
    main()
