#!/usr/bin/env python3
"""Зразки сумісності «межа-1.0-1.1»: сліди 1.0 і 1.1, що закінчились межею глибини рекурсії — 2000 викликів.

Набір «межа-1.2» має такі сліди лише від 1.2, а §9 обіцяє повтор слідів 1.0–1.2 (суд 16, Аудитор). Ці зразки записали еталони
**1.0** (коміт 08b759a) і **1.1** (коміт 35b1064): рекурсія на 2500 викликів і рекурсія крізь Σ на 1500 рівнів — у 1.0–1.2
зупинка на 2000 викликів, у 1.3 обидві доходять до кінця. Повтор у 1.3 бере межу зі сліду (без `ліміти.виклики` — 2000) і
дає тодішній текст зупинки. Атанора 1.0 й 1.1 тут немає: повтор однаково веде еталон.

Запущено ОДИН раз — 2026-11-13; після цього не перегенеровують.
Запуск: `python3 зібрати_межа_1.0_1.1.py ЕТАЛОН_1.0/ngr.py ЕТАЛОН_1.1/ngr.py`
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
OUT = D / 'межа-1.0-1.1'
TRACE_KEY = hashlib.sha256('nigredo 1.0 — тестовий ключ сліду набору сумісності'.encode()).hexdigest()
PROGS = {
    'рекурсія': ('🜂 「зразок 1.0–1.1: рекурсія на 2500 викликів — межа 2000 викликів, тож зупинка; у 1.3 доходить до кінця」\n'
                 '← глибше λn ¿ ＝ n 0 0 ＋ 1 глибше － n 1\n'
                 '» 「почато」\n'
                 '» глибше 2500\n'),
    'цикл': ('🜂 「зразок 1.0–1.1: рекурсія крізь Σ — 1500 рівнів, по два виклики на рівень: зупинка на 2000 викликів」\n'
             '← глибше λn ¿ ＝ n 0 0 Σ 【1】 0 Λнакоп одиниця ＋ одиниця глибше － n 1\n'
             '» 「почато」\n'
             '» глибше 1500\n'),
}


def main():
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    refs = (('1.0', sys.argv[1]), ('1.1', sys.argv[2]))
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
        for name, src in PROGS.items():
            (work / f'{name}.ngr').write_text(src, encoding='utf-8')
            outs = []
            for ver, ref in refs:
                tr = work / f'{name}_{ver}.jsonl'
                r = subprocess.run([sys.executable, ref, '--слід', str(tr), str(work / f'{name}.ngr')], env=env, cwd=work,
                                   capture_output=True, text=True, timeout=600)
                lines = [x for x in tr.read_text(encoding='utf-8').split('\n') if x]
                head, end = json.loads(lines[0]), json.loads(lines[-1])
                if (head.get('версія') != ver or r.returncode != 1 or 'виклики' in (head.get('ліміти') or {})
                        or end.get('подія') != 'помилка' or not json.dumps(end, ensure_ascii=False).count('надто глибока рекурсія"')):
                    print(f'✗ {name}, {ver}: не слід {ver}, що закінчився межею глибини: код {r.returncode}, {head.get("версія")}, '
                          f'{end}', file=sys.stderr)
                    return 1
                outs.append(r.stdout)
            if outs[0] != outs[1]:
                print(f'✗ {name}: еталони 1.0 і 1.1 дали різний вивід', file=sys.stderr)
                return 1
            (work / f'{name}.txt').write_text(outs[0], encoding='utf-8')
        shutil.copytree(work, OUT)
    print(f'✓ {OUT}: {", ".join(sorted(p.name for p in OUT.iterdir()))}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
