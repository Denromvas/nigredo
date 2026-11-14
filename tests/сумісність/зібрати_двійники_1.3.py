#!/usr/bin/env python3
"""Зразки сумісності «двійники-1.3»: програми 1.3 з функціями, чиї імена на вигляд схожі на грецькі літери.

1.4 додає перші гліфи після 1.0. Перша спроба (η, γ; суд 17, раунд 1) зламала обіцянку §9: таблиця двійників гліфів
будується з усіх гліфів, скелет γ за UTS #39 — латинська y, скелет η — той самий, що в ŋ, тож функції `y`, `у`, `ү`, `ɣ`,
`ყ`, `ŋ` (і з цифрою, повтором, у `∘імʼя`) 1.4 відкидала до запуску, а слід 1.3 такої програми не повторювався. Знайшли
п'ятеро суддів. Гліфи замінено на `ζ ψ` (і `ω`), а до правила «Нові гліфи в 1.x» дописано умову про скелет. Ці зразки
записали виконавці **1.3** (еталон і Атанор з `main` до злиття 1.4), а `test.py` запускає й повторює їх виконавцем 1.x.

Запущено ОДИН раз — 2026-11-14, еталоном і Атанором 1.3 (коміт 9afb430); після цього не перегенеровують.
Запуск: `python3 зібрати_двійники_1.3.py ЕТАЛОН_1.3/ngr.py АТАНОР_1.3`
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
OUT = D / 'двійники-1.3'
TRACE_KEY = hashlib.sha256('nigredo 1.0 — тестовий ключ сліду набору сумісності'.encode()).hexdigest()
NAMES = {'латинська_y': 'y', 'кирилична_у': 'у', 'кирилична_ү': 'ү', 'латинська_ɣ': 'ɣ', 'грузинська_ყ': 'ყ', 'латинська_ŋ': 'ŋ'}
PROGS = {k: (f'🜂 「зразок 1.3: функції {n}, {n}{n}, {n}5 і ∘{n} — імена, схожі на грецькі літери, яких 1.3 гліфами не має」\n'
             f'← {n} λчисло ＋ число 1\n← {n}{n} λчисло × число 2\n← {n}5 λчисло － число 1\n'
             f'» {n} 41\n» {n}{n} 4\n» {n}5 4\n» μ 【1 2 3】 ∘{n}\n', []) for k, n in NAMES.items()}


def main():
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    ref, ath = sys.argv[1], sys.argv[2]
    if OUT.exists():
        print(f'✗ {OUT} уже є: зразки записано один раз, не перегенеровують', file=sys.stderr)
        return 1
    if (D / 'власник' / 'ключ').read_text(encoding='utf-8').strip() != TRACE_KEY:
        print('✗ власник/ключ — не тестовий ключ набору', file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        home = pathlib.Path(tmp) / 'власник'
        home.mkdir()
        shutil.copy(D / 'власник' / 'ключ', home / 'ключ')
        (home / 'дозволи.json').write_text('{"дозволено": []}', encoding='utf-8')
        env = dict(os.environ, NIGREDO_HOME=str(home))
        work = pathlib.Path(tmp) / 'двійники'
        work.mkdir()
        for name, (src, flags) in PROGS.items():
            (work / f'{name}.ngr').write_text(src, encoding='utf-8')
            outs = []
            for tag, cmd in (('', [sys.executable, ref]), ('_атанор', [ath])):
                tr = work / f'{name}{tag}.jsonl'
                r = subprocess.run(cmd + flags + ['--слід', str(tr), str(work / f'{name}.ngr')], env=env, cwd=work,
                                   capture_output=True, text=True, timeout=600)
                head = json.loads(tr.read_text(encoding='utf-8').split('\n')[0])
                end = json.loads([x for x in tr.read_text(encoding='utf-8').split('\n') if x][-1])
                want_engine = 'атанор:' if tag else ''
                if (head.get('версія') != '1.3' or r.returncode != 0 or end.get('подія') != 'кінець'
                        or not str(head.get('інтерпретатор')).startswith(want_engine)):
                    print(f'✗ {name}{tag}: не слід 1.3, що дійшов до кінця: код {r.returncode}, {head.get("версія")}, {end}, '
                          f'{r.stderr[-300:]}', file=sys.stderr)
                    return 1
                outs.append(r.stdout)
            if outs[0] != outs[1]:
                print(f'✗ {name}: еталон і Атанор 1.3 дали різний вивід', file=sys.stderr)
                return 1
            (work / f'{name}.txt').write_text(outs[0], encoding='utf-8')
        shutil.copytree(work, OUT)
    print(f'✓ {OUT}: {", ".join(sorted(p.name for p in OUT.iterdir()))}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
