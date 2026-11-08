#!/usr/bin/env python3
"""Зразки сумісності «межа-1.1»: сліди 1.1, що закінчились межею ресурсів, — «сумарно створено» і «ліміт кроків».

1.2 рахує інакше (облік «робота», `spec/пропозиції/облік.md`): μ, що повертає спільне значення, уже не платить увесь його
логічний розмір, а показ значення для сліду (🜄) платить кроки. Тож перша програма в 1.2 доходить до кінця, а друга
зупиняється раніше. Обіцянка §9 («слід 1.x повторює будь-яка новіша 1.x») тримається тим, що повтор бере облік зі сліду
(`ліміти.облік`: «нове» — облік 1.1). Ці зразки записали виконавці **1.1** (еталон і Атанор з `main` до злиття 1.2), а
`test.py` повторює їх виконавцем 1.x.

Запущено ОДИН раз — 2026-11-08, еталоном і Атанором 1.1 (коміт 689b36a); після цього не перегенеровують.
Запуск: `python3 зібрати_межа_1.1.py ЕТАЛОН_1.1/ngr.py АТАНОР_1.1`
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
OUT = D / 'межа-1.1'
TRACE_KEY = hashlib.sha256('nigredo 1.0 — тестовий ключ сліду набору сумісності'.encode()).hexdigest()
PROGS = {
    'створено': ('🜂 「зразок 1.1: μ, що повертає спільне значення, у 1.1 платить увесь його логічний розмір — і впирається в «сумарно створено»」\n'
                 '← спільне Σ … 1 14 【1】 Λs ж 【s s】\n'
                 '» 「почато」\n'
                 '← кінець Σ … 1 400 0 Λа і 《 ← в μ 【спільне спільне】 λx x ¦ » і ¦ ＋ а ρ в 》\n'
                 '» кінець\n', ['--розмір', '300000']),
    'кроки': ('🜂 「зразок 1.1: 🜄 показує спільне значення в сліді — у 1.1 це не коштує кроків, у 1.2 коштує」\n'
              '← спільне Σ … 1 14 【1】 Λs ж 【s s】\n'
              '∀ … 1 300 λі 《 🜄 「к」 спільне ¦ » і 》\n'
              '» 「кінець」\n', ['--кроки', '1000']),
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
                if (head.get('версія') != '1.1' or (head.get('ліміти') or {}).get('облік') != 'нове' or r.returncode != 1
                        or end.get('подія') != 'помилка' or not str(head.get('інтерпретатор')).startswith(want_engine)):
                    print(f'✗ {name}{tag}: не слід 1.1, що закінчився межею: код {r.returncode}, {head.get("версія")}, '
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
