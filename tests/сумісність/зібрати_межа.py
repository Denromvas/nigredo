#!/usr/bin/env python3
"""Зразки сумісності «межа» (суд 14): сліди 1.0, що закінчились межею ресурсів, — «сумарно створено» і «ліміт кроків».

1.1 рахує створене й кроки інакше (облік «нові дані», `spec/пропозиції/вартість.md`): ті самі програми з тими самими
межами в 1.1 доходять далі. Обіцянка §9 («слід 1.0 перевіряє й повторює будь-яка 1.x») тримається тим, що повтор бере облік
зі сліду (`ліміти.облік`; без поля — облік 1.0). Ці зразки це перевіряють: їх записали виконавці **1.0** (еталон і Атанор з
`main` до злиття 1.1), а `test.py` повторює їх виконавцем 1.x.

Запущено ОДИН раз — 2026-11-07, еталоном і Атанором 1.0 (коміт 6165c72); після цього не перегенеровують.
Запуск: `python3 зібрати_межа.py ЕТАЛОН_1.0/ngr.py АТАНОР_1.0`
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
OUT = D / 'межа'
TRACE_KEY = hashlib.sha256('nigredo 1.0 — тестовий ключ сліду набору сумісності'.encode()).hexdigest()
PROGS = {
    'створено': ('🜂 「зразок 1.0: цикл зі станом, де великий список не міняється, упирається в «сумарно створено»」\n'
                 '← великий … 1 50000\n'
                 '» 「почато」\n'
                 '← кінець ↻ 『「дані」 великий 「н」 0』 λс ‹ § с 「н」 100 λс ✎ с 「н」 ＋ § с 「н」 1\n'
                 '» § кінець 「н」\n', ['--розмір', '300000']),
    'кроки': ('🜂 「зразок 1.0: та сама межа кроків — у 1.0 менше роботи, ніж у 1.1」\n'
              '← великий … 1 20000\n'
              '∀ … 1 300 λі 《 ← п 【і великий】 ¦ » § п 0 》\n'
              '» 「кінець」\n', ['--кроки', '30000']),
}


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
        work = pathlib.Path(tmp) / 'межа'
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
                if (head.get('версія') != '1.0' or 'облік' in (head.get('ліміти') or {}) or r.returncode != 1
                        or end.get('подія') != 'помилка' or not str(head.get('інтерпретатор')).startswith(want_engine)):
                    print(f'✗ {name}{tag}: не слід 1.0, що закінчився межею: код {r.returncode}, {head.get("версія")}, '
                          f'{end}', file=sys.stderr)
                    return 1
                outs.append(r.stdout)
            if outs[0] != outs[1]:
                print(f'✗ {name}: еталон і Атанор 1.0 дали різний вивід', file=sys.stderr)
                return 1
            (work / f'{name}.txt').write_text(outs[0], encoding='utf-8')
        shutil.copytree(work, OUT)
    print(f'✓ {OUT}: {", ".join(sorted(p.name for p in OUT.iterdir()))}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
