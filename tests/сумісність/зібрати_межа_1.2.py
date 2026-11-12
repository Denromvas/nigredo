#!/usr/bin/env python3
"""Зразки сумісності «межа-1.2»: сліди 1.2, що закінчились межею глибини рекурсії — 2000 викликів.

1.3 піднімає цю межу до 20 000 викликів (`spec/пропозиції/глибина.md`): рекурсивний розбір програми з вкладеністю 1000 бере
понад 2000 викликів, а стек виконавців уже розрахований на 200 000 рівнів. Тож обидві програми в 1.3 доходять до кінця. Обіцянка
§9 («слід 1.x повторює будь-яка новіша 1.x») тримається тим, що повтор бере межу зі сліду (`ліміти.виклики`; без поля — 2000,
як у 1.0–1.2). Ці зразки записали виконавці **1.2** (еталон і Атанор з `main` до злиття 1.3), а `test.py` повторює їх виконавцем 1.x.

Запущено ОДИН раз — 2026-11-12, еталоном і Атанором 1.2 (коміт 954adaf); після цього не перегенеровують.
Запуск: `python3 зібрати_межа_1.2.py ЕТАЛОН_1.2/ngr.py АТАНОР_1.2`
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
OUT = D / 'межа-1.2'
TRACE_KEY = hashlib.sha256('nigredo 1.0 — тестовий ключ сліду набору сумісності'.encode()).hexdigest()
PROGS = {
    'рекурсія': ('🜂 「зразок 1.2: рекурсія на 2500 викликів — у 1.2 межа 2000 викликів, тож зупинка; у 1.3 доходить до кінця」\n'
                 '← глибше λn ¿ ＝ n 0 0 ＋ 1 глибше － n 1\n'
                 '» 「почато」\n'
                 '» глибше 2500\n', []),
    'цикл': ('🜂 「зразок 1.2: рекурсія крізь Σ — 1500 рівнів, по два виклики на рівень: у 1.2 зупинка на 2000 викликів」\n'
             '← глибше λn ¿ ＝ n 0 0 Σ 【1】 0 Λнакоп одиниця ＋ одиниця глибше － n 1\n'
             '» 「почато」\n'
             '» глибше 1500\n', []),
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
                if (head.get('версія') != '1.2' or (head.get('ліміти') or {}).get('облік') != 'робота' or r.returncode != 1
                        or 'виклики' in (head.get('ліміти') or {}) or end.get('подія') != 'помилка'
                        or 'надто глибока рекурсія' not in json.dumps(end, ensure_ascii=False)
                        or not str(head.get('інтерпретатор')).startswith(want_engine)):
                    print(f'✗ {name}{tag}: не слід 1.2, що закінчився межею глибини: код {r.returncode}, {head.get("версія")}, '
                          f'{end}', file=sys.stderr)
                    return 1
                outs.append(r.stdout)
            if outs[0] != outs[1]:
                print(f'✗ {name}: еталон і Атанор 1.2 дали різний вивід', file=sys.stderr)
                return 1
            (work / f'{name}.txt').write_text(outs[0], encoding='utf-8')
        shutil.copytree(work, OUT)
    print(f'✓ {OUT}: {", ".join(sorted(p.name for p in OUT.iterdir()))}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
