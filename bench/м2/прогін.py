#!/usr/bin/env python3
"""М2: чи пише модель Nigredo з першої спроби не гірше, ніж Python, — на задачах, яких немає ні в памʼятці, ні в
мірилі. Кожна модель пише обидва розвʼязки з того самого завдання в сесії `claude -p` без інструментів, у порожній
теці (не може підглянути еталон). Для Nigredo — лише памʼятка. Друга спроба: модель бачить свій код і вивід.

    python3 bench/м2/прогін.py sonnet haiku        # результати: bench/м2/прогони/, bench/м2/РЕЗУЛЬТАТИ.md
    python3 bench/м2/прогін.py --набір задачі2 sonnet haiku   # складний набір: прогони2/, РЕЗУЛЬТАТИ2.md
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SET = sys.argv[sys.argv.index('--набір') + 1] if '--набір' in sys.argv else 'задачі'
SUFFIX = SET.removeprefix('задачі')                  # '' для першого набору, '2' для другого
TASKS = sorted(p for p in (HERE / SET).iterdir() if p.is_dir())
MEMO = (ROOT / 'ДЛЯ_АГЕНТІВ.md').read_text(encoding='utf-8')
NGR = ROOT / 'interpreter' / 'ngr.py'
OUT = HERE / f'прогони{SUFFIX}'

INTRO = {
    'py': 'Напиши програму на Python 3 (лише стандартна бібліотека), що розвʼязує задачу. Програму запустять із '
          'теки, у якій лежить тека `дані/`. Відповідай лише кодом в одному блоці ```python … ```.\n\n',
    'ngr': 'Напиши програму мовою Nigredo (.ngr), що розвʼязує задачу. Нижче — повна памʼятка мови. Програму '
           'запустять із теки, у якій лежить тека `дані/`; власник дозволив `читати:дані`, `список:дані` і '
           '`бд.читати:дані`. Відповідай лише кодом в одному блоці ``` … ```.\n\n=== ПАМʼЯТКА ===\n' + MEMO +
           '\n=== КІНЕЦЬ ПАМʼЯТКИ ===\n\n',
}


def ask(model, prompt):
    with tempfile.TemporaryDirectory(prefix='м2-') as empty:
        r = subprocess.run(['claude', '-p', '--model', model, '--tools', '', '--no-session-persistence',
                            '--strict-mcp-config'], input=prompt, cwd=empty, capture_output=True, text=True,
                           timeout=900)
    if r.returncode:
        raise RuntimeError(f'claude: код {r.returncode}: {r.stderr[-300:]}')
    m = re.search(r'```[^\n]*\n(.*?)```', r.stdout, re.S)
    return (m.group(1) if m else r.stdout).strip() + '\n', r.stdout


def execute(task, lang, code):
    with tempfile.TemporaryDirectory(prefix='м2-run-') as d:
        d = pathlib.Path(d)
        shutil.copytree(task / 'дані', d / 'дані')
        home = d / '.власник'
        home.mkdir()
        (home / 'дозволи.json').write_text(json.dumps({'дозволено': [
            f'читати:{d}/дані', f'список:{d}/дані', f'бд.читати:{d}/дані']}, ensure_ascii=False), encoding='utf-8')
        src = d / ('рішення.py' if lang == 'py' else 'рішення.ngr')
        src.write_text(code, encoding='utf-8')
        cmd = [sys.executable, str(src)] if lang == 'py' else [sys.executable, str(NGR), str(src)]
        try:
            r = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=60,
                               env=dict(os.environ, NIGREDO_HOME=str(home)))
            return r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            return -1, '', 'тайм-аут 60 с'


def norm(s):
    return '\n'.join(l.rstrip() for l in s.strip().splitlines())


def main(models):
    rows = {}
    for model in models:
        for task in TASKS:
            text = (task / 'завдання.md').read_text(encoding='utf-8')
            want = norm((task / 'очікується.txt').read_text(encoding='utf-8'))
            for lang in ('py', 'ngr'):
                base = OUT / model / f'{task.name}.{lang}'
                done = base.with_suffix(f'.{lang}.json')
                if done.exists():                       # продовжує після обриву
                    rows[(model, task.name, lang)] = json.loads(done.read_text(encoding='utf-8'))
                    continue
                prompt = INTRO[lang] + text
                res = []
                for attempt in (1, 2):
                    try:
                        code, raw = ask(model, prompt)
                    except Exception as e:           # noqa: BLE001
                        res.append({'спроба': attempt, 'помилка_моделі': str(e)})
                        break
                    rc, out, err = execute(task, lang, code)
                    ok = rc == 0 and norm(out) == want
                    res.append({'спроба': attempt, 'гаразд': ok, 'код': code, 'відповідь': raw, 'код_виходу': rc,
                                'вивід': out[-2000:], 'помилки': err[-2000:]})
                    if ok:
                        break
                    prompt = (INTRO[lang] + text + '\n\nТвоя попередня спроба:\n```\n' + code + '```\n'
                              f'Код виходу {rc}. Вивід:\n{out[-1500:]}\nПомилки:\n{err[-1500:]}\n'
                              f'Очікувався вивід:\n{want}\n\nВиправ програму.')
                done.parent.mkdir(parents=True, exist_ok=True)
                done.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
                rows[(model, task.name, lang)] = res
                print(model, task.name, lang, ['✓' if r.get('гаразд') else '✗' for r in res], flush=True)
    report(models, rows)


def report(models, rows):
    L = ['# М2: правильність з першої спроби на задачах поза памʼяткою', '',
         f'Задачі — `bench/м2/{SET}/` ({len(TASKS)}; їх немає ні в памʼятці, ні в мірилі). Модель пише в `claude -p` '
         'без інструментів, у порожній теці; для Nigredo має лише памʼятку. ✓1 — з першої спроби, ✓2 — з другої '
         '(бачила свій код, вивід і очікуваний вивід), ✗ — ні. Повні відповіді моделей (і витягнутий код) — `bench/м2/прогони{SUFFIX}/` (поле «відповідь» — з 2026-10-16; раніше зберігався лише перший блок коду). Python-код моделей виконується без меж (тимчасова тека, права процесу).', '']
    for model in models:
        L += [f'## {model}', '', '| Задача | Python | Nigredo |', '|---|---|---|']
        tot = {'py': [0, 0], 'ngr': [0, 0]}
        for task in TASKS:
            cells = []
            for lang in ('py', 'ngr'):
                res = rows.get((model, task.name, lang), [])
                ok = [r['спроба'] for r in res if r.get('гаразд')]
                cells.append(f'✓{ok[0]}' if ok else ('помилка моделі' if res and 'помилка_моделі' in res[-1] else '✗'))
                if ok:
                    tot[lang][0] += ok[0] == 1
                    tot[lang][1] += 1
            L.append(f'| {task.name} | {cells[0]} | {cells[1]} |')
        n = len(TASKS)
        L += ['', f'**З першої спроби:** Python {tot["py"][0]}/{n}, Nigredo {tot["ngr"][0]}/{n}. '
                  f'**За дві спроби:** Python {tot["py"][1]}/{n}, Nigredo {tot["ngr"][1]}/{n}.', '']
    (HERE / f'РЕЗУЛЬТАТИ{SUFFIX}.md').write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L))


if __name__ == '__main__':
    args = [a for i, a in enumerate(sys.argv[1:]) if a != '--набір' and sys.argv[i] != '--набір']
    main(args or ['sonnet'])
