#!/usr/bin/env python3
"""Зразки сумісності «межа-1.1б»: сліди 1.1, що доходять до кінця під межею, але потрапили б на нові ціни 1.2, якби повтор їх
не відгороджував (суд 15, раунд 2, Скептик Н-1): логічний розмір названої функції (1.2: 1 + довжина імені) і плата `✓` з
переліком за показ. Повтор сліду 1.1 мусить рахувати за обліком 1.1 і дійти до того самого кінця; свіжий запуск 1.2 першої
програми зупиняється на `--розмір`.

Запущено ОДИН раз — 2026-11-09, еталоном і Атанором 1.1 (`main`, 689b36a); після цього не перегенеровують.
Запуск: `python3 зібрати_межа_1.1б.py ЕТАЛОН_1.1/ngr.py АТАНОР_1.1`
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
OUT = D / 'межа-1.1б'
TRACE_KEY = hashlib.sha256('nigredo 1.0 — тестовий ключ сліду набору сумісності'.encode()).hexdigest()
PROGS = {
    'функції': ('🜂 「зразок 1.1: таблиця з 5000 посилань на функцію з імʼям у 66 літер — у 1.2 її логічний розмір 335 001」\n'
                '← обробникобробникобробникобробникобробникобробникобробникобробникаб λx ＋ x 1\n'
                '← таблиця μ … 1 5000 λі ∘обробникобробникобробникобробникобробникобробникобробникобробникаб\n'
                '» ρ таблиця\n'
                '» ► § таблиця 0 41\n', ['--розмір', '300000']),
    'перелік': ('🜂 「зразок 1.1: ✓ рядка в 640 символів проти переліку з ним — у 1.2 показ платить кроки, у 1.1 платив результат」\n'
                '← довге ⁀ μ … 1 128 λі 「абвгд」 「」\n'
                '← схема ⁀ 【「рядок:」 довге 「|так」】 「」\n'
                '∀ … 1 2000 λі ✓ довге схема\n'
                '» 「кінець」\n', ['--кроки', '35000']),
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
                if (head.get('версія') != '1.1' or (head.get('ліміти') or {}).get('облік') != 'нове' or r.returncode != 0
                        or end.get('подія') != 'кінець' or not str(head.get('інтерпретатор')).startswith(want_engine)):
                    print(f'✗ {name}{tag}: не слід 1.1, що дійшов до кінця: код {r.returncode}, {head.get("версія")}, '
                          f'{end}', file=sys.stderr)
                    return 1
                outs.append(r.stdout)
            if outs[0] != outs[1]:
                print(f'✗ {name}: еталон і Атанор 1.1 дали різний вивід', file=sys.stderr)
                return 1
            (work / f'{name}.txt').write_text(outs[0], encoding='utf-8')
        shutil.copytree(work, OUT)
    print(f'✓ {OUT}: {", ".join(sorted(p.name for p in OUT.iterdir()))}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
