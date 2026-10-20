#!/usr/bin/env python3
"""Диференційна проба Атанора на ДАНИХ (суд 9: звірка на програмах репо не бачила класів, де поведінку вирішують
дані, — шаблон регулярки з даних, регістр різними письмами, числа, межі). Генерує програми з випадковими даними,
виконує обома виконавцями (Атанор — без віддачі еталону) і порівнює вивід, stderr і код виходу. Кожна розбіжність —
вада. Запуск: python3 athanor/звірка_даних.py [програм] [виразів у програмі]; SEED=… — інше зерно."""
import json
import os
import random
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
REF = os.environ.get('NIGREDO_PY') or os.path.join(HERE, '..', 'interpreter', 'ngr.py')
BIN = os.environ.get('ATHANOR_BIN') or next((p for p in (os.path.join(HERE, 'target', t, 'release', 'athanor')
                                             for t in ('aarch64-unknown-linux-gnu', 'x86_64-unknown-linux-gnu', ''))
                                            if os.path.exists(p)))
rng = random.Random(int(os.environ.get('SEED', '9')))

# символи, на яких мови й бібліотеки розходяться найчастіше: регістр, сигма, лігатури, турецьке İ, невидимі
TRICKY = list('aAzZiIıİ' 'σςΣΑΒΟΔΥΕ' 'ßẞﬁŉǅǄǆſKkÅå' 'абвгґєіїАБВҐЄІЇ' 'ʼ\'’-_ .,;:!?' '0123456789' '١٢٣४५' '²³½')
TRICKY += ['\r', '\n', '\t', '\u200b', '\u202e', '\u2028', '\u00a0', '\u3000', 'é', 'e\u0301', '😀', '⟨', '」', '\\']
RX_PIECES = ['a', 'b', '.', '\\w', '\\W', '\\d', '\\s', '\\b', '^', '$', '\\Z', '[a-z]', '[^a-z]', '[а-я]', '[ΣσςΑ]',
             '(?i)', '(?s)', '(?m)', '(?a)', '(a)', '(?:ab)', '(?P<x>b)', 'a|b', 'a*', 'a+?', 'b?', 'a{2}', 'a{1,3}',
             'a{4294967294}', 'a{4294967295}', 'a{99999999999999999999}', 'a{2,1}', '\\N{LATIN SMALL LETTER A}',
             'İ', 'ß', 'K', 'ſ', 'σ', 'Σ', '\\u0130', '\\x41', '[', ')', '(?<=a)', '\\1', '(?#c)', '\\²', 'é', '\\.']
REPL_PIECES = ['x', '\\1', '\\g<1>', '\\g<x>', '\\²', '\\n', '\\٣', '\\g<١>', '\\0', '\\\\', '\\q', '']


def lit(s):
    """Рядок Nigredo 「…」 з екрануванням (\\n, \\t, \\r — як є в мові; невидимі — у лапках не можна, тож через δ)."""
    return '「' + s.replace('\\', '\\\\').replace('」', '\\」').replace('\n', '\\n').replace('\t', '\\t') + '」'


def data(s):
    """Будь-який рядок як дані: δ від JSON-рядка (так проходять і невидимі, і \\r)."""
    return 'δ ' + lit(json.dumps(s))


def text(n=None):
    return ''.join(rng.choice(TRICKY) for _ in range(n if n is not None else rng.randint(0, 12)))


def expr():
    k = rng.randrange(12)
    if k == 0:
        pat = ''.join(rng.choice(RX_PIECES) for _ in range(rng.randint(1, 4)))
        return f'⌕ {data(text())} {data(pat)}'
    if k == 1:
        pat = ''.join(rng.choice(RX_PIECES[:30]) for _ in range(rng.randint(1, 3)))
        rep = ''.join(rng.choice(REPL_PIECES) for _ in range(rng.randint(0, 3)))
        return f'≋ {data(text())} {data(pat)} {data(rep)}'
    if k == 2:
        return f'{rng.choice("⇡⇣")} {data(text())}'
    if k == 3:
        num = rng.choice(['1', '-0', '1e5', '1E-7', '0.1', '1e99999999999999999999', '1e-99999999999999999999',
                          '1e30000', '1e30001', ' 12 ', '1_000', '٣', '+5', '.5', '5.', 'NaN', 'Infinity', '1e', 'e1',
                          str(rng.randint(-10 ** 30, 10 ** 30)), f'{rng.random() * 10 ** rng.randint(-20, 20)}'])
        return f'ν {data(num)}'
    if k == 4:
        js = rng.choice(['1e400', '[1e99999999999999999999]', '{"a": 1, "a": 2}', '"\\ud800"', '{"\\ud800": 1}',
                         '[1.5, -0.0, 1E-5]', '"\\u0130"', 'NaN', '[' * 30 + ']' * 30, '{"σ": "Σ"}', '0.1e1'])
        return f'δ {lit(js)}'
    if k == 5:
        return f'⇅ 【{" ".join(data(text(rng.randint(0, 4))) for _ in range(rng.randint(1, 5)))}】 λx x'
    if k == 6:
        d = rng.choice(['2026-02-29', '2024-02-29', '0001-01-01', '9999-12-31T23:59:59', '2026-10-16T10:00:00+03:00',
                        '2026-13-01', '2026-1-1', ' 2026-01-01', '2026-01-01Z'])
        return f'◷ {data(d)} ' + rng.choice([data('2026-01-01'), str(rng.randint(-800000, 800000)), '1.5', '¯3'])
    if k == 7:
        return f'ρ {data(text())}'
    if k == 8:
        return f'σ {data(text())}'
    if k == 9:
        csv = '\n'.join(','.join(rng.choice(['a', '"b,c"', '"d""e"', '', 'ж', ' x ']) for _ in range(rng.randint(1, 3)))
                        for _ in range(rng.randint(1, 4)))
        return f'▦ {data(csv)}'
    if k == 10:
        return f'✂ {data(text())} {data(rng.choice([",", " ", "ß", "Σ", "a"]))}'
    return f'⊢ {data(text())}'


def run(cmd, prog, home):
    env = dict(os.environ, NIGREDO_HOME=home, ATHANOR_NO_FALLBACK='1')
    r = subprocess.run([*cmd, '-e', prog], capture_output=True, text=True, errors='replace', env=env, timeout=120)
    return r.returncode, r.stdout, re.sub(r'слід: \S+\.jsonl', 'слід: …', r.stderr)   # шлях сліду — свій у кожного


def main():
    n_progs = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    n_expr = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    home = tempfile.mkdtemp(prefix='ngr-звірка-даних-')
    native = handed = 0
    bad = []
    for i in range(n_progs):
        lines = [f'» ☂ {expr()} λe e' for _ in range(n_expr)]
        prog = '🜂 「проба даними」\n' + '\n'.join(lines) + '\n'
        a = run([BIN], prog, home)
        if a[0] == 120:                       # Атанор сам не виконує (віддав би еталону) — порівнювати нічого
            handed += 1
            continue
        native += 1
        r = run([sys.executable, REF], prog, home)
        if a != r:
            bad.append((prog, a, r))
            if len(bad) <= int(os.environ.get('SHOW', '5')):
                diff = [(x, y) for x, y in zip((a[1] + a[2]).split('\n'), (r[1] + r[2]).split('\n')) if x != y][:3]
                print(f'✗ розбіжність (програма {i}, код {a[0]}/{r[0]}):', *(f'  А: {x}\n  Е: {y}' for x, y in diff), sep='\n')
    print(f'програм: {n_progs} (по {n_expr} виразів); Атанор виконав сам {native}, віддав би еталону {handed}; '
          f'розбіжностей: {len(bad)}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
