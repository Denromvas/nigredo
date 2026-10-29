#!/usr/bin/env python3
"""Учасник консиліуму — Gemini (незалежна модель іншої компанії).

  python3 gemini_member.py 1   # раунд 1: завдання (код запускає цей скрипт через ngr) + звіт
  python3 gemini_member.py 2   # раунд 2: обговорення звітів ../protokol/раунд1/

Ключ читається з файлу $GEMINI_ENV_FILE щоразу й ніде не зберігається.
Уся розмова пишеться в розмова_раунд<N>.md (без ключа).
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

MODEL = os.environ.get('GEMINI_MODEL', 'gemini-4-argon')  # з 2026-10-16; запасні — 3.6/3.7-flash
MODELS = [MODEL] + [m for m in ('gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.6-flash') if m != MODEL]
USED = []                                                  # які моделі справді відповіли (пишемо у звіт)
ENV = pathlib.Path(os.environ['GEMINI_ENV_FILE'])   # файл .env з рядком GEMINI_API_KEY=…
HERE = pathlib.Path(__file__).resolve().parent
K = HERE.parent
NGR = K.parent.parent
MAX_RUNS = 5

ROLE = """Ти — Gemini, незалежний експерт консиліуму щодо мови програмування Nigredo.
Тебе запросили саме тому, що ти модель іншої компанії, а решту учасників і саму мову
створила модель Claude. Твоя цінність — незалежна думка: не підлаштовуйся під автора
й інших, кажи прямо, спирайся на факти. Відповідай українською."""


def key():
    for line in ENV.read_text().splitlines():
        if line.startswith('GEMINI_API_KEY='):
            return line.split('=', 1)[1].strip().strip('"\'')
    sys.exit('немає GEMINI_API_KEY')


def ask(history):
    body = {'systemInstruction': {'parts': [{'text': ROLE}]}, 'contents': history}
    for attempt in range(30):           # перевантаження (503) буває годинами — колами по всіх моделях, кожні 5 хв
        for model in list(MODELS):
            req = urllib.request.Request(
                f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
                data=json.dumps(body).encode(), headers={'Content-Type': 'application/json', 'x-goog-api-key': key()})
            try:
                d = json.load(urllib.request.urlopen(req, timeout=600))
                USED.append(model)
                return ''.join(p.get('text', '') for p in d['candidates'][0]['content']['parts']
                               if not p.get('thought'))
            except urllib.error.HTTPError as e:
                err = e.read()
                print(f'{model}: {e.code} {err[:300]!r}', file=sys.stderr, flush=True)
                if e.code not in (404, 429, 500, 503):
                    raise
                wait = re.search(rb'"retryDelay": "(\d+)', err)
                if e.code == 429 and wait and int(wait.group(1)) <= 120:   # хвилинна межа — почекати й повторити
                    time.sleep(int(wait.group(1)) + 5)
                elif e.code in (404, 429) and len(MODELS) > 1:   # денну квоту вичерпано чи моделі нема — до кінця
                    MODELS.remove(model)
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
                print(f'{model}: мережа: {e}', file=sys.stderr, flush=True)   # мережа телефона буває нестабільною
        time.sleep(300)
    sys.exit('Gemini не відповів за 30 кіл')


def say(history, log, text):
    history.append({'role': 'user', 'parts': [{'text': text}]})
    log.append(f'## → Gemini\n\n{text}\n')
    ans = ask(history)
    history.append({'role': 'model', 'parts': [{'text': ans}]})
    log.append(f'## ← Gemini ({USED[-1]})\n\n{ans}\n')
    return ans


def materials(spec=True):
    parts = [f'# ПРАВИЛА\n{(K / "ПРАВИЛА.md").read_text()}', f'# ПІДСУМОК суду 10 (що знайдено й виправлено)\n{(K / "ПІДСУМОК_суду10.md").read_text()}',
             f'# ДЛЯ_АГЕНТІВ.md\n{(NGR / "ДЛЯ_АГЕНТІВ.md").read_text()}',
             f'# README.md\n{(NGR / "README.md").read_text()}',
             f'# ПЛАН_1.0.md\n{(NGR / "ПЛАН_1.0.md").read_text()}',
             f'# athanor/README.md\n{(NGR / "athanor" / "README.md").read_text()}',
             f'# bench/РЕЗУЛЬТАТИ.md\n{(NGR / "bench" / "РЕЗУЛЬТАТИ.md").read_text()}',
             f'# bench/великі/РЕЗУЛЬТАТИ.txt\n{(NGR / "bench" / "великі" / "РЕЗУЛЬТАТИ.txt").read_text()}',
             f'# spec/пропозиції/модулі_git.md\n{(NGR / "spec" / "пропозиції" / "модулі_git.md").read_text()}',
             f'# Чужа програма чужа_з_модулем.ngr у твоїй теці\n{(HERE / "чужа_з_модулем.ngr").read_text()}',
             *(f'# Модуль бібліотеки суду {f.relative_to(K / "дзеркало")}\n{f.read_text()}'
               for f in sorted((K / 'дзеркало').rglob('*.ngr')) if 'zvit-' not in str(f) or 'zvit-gemini' in str(f)),
             *(f'# Твій звіт суду 10: {f.name}\n{f.read_text()}' for f in sorted((HERE / 'попередні_звіти').glob('*.md'))),
             f'# Твоя схвалена програма схвалена.ngr\n{(HERE / "схвалена.ngr").read_text()}']
    for f in sorted((HERE / 'дані').iterdir()):
        if f.suffix == '.db':                       # SQLite — двійковий: лише схема
            import sqlite3
            schema = '\n'.join(r[0] for r in sqlite3.connect(f'file:{f}?mode=ro', uri=True).execute(
                'SELECT sql FROM sqlite_master'))
            parts.append(f'# дані/{f.name} у твоїй теці — SQLite, схема:\n{schema}')
        elif f.is_file():
            parts.append(f'# Вміст дані/{f.name} у твоїй теці\n{f.read_text()}')
    if spec:
        parts.append(f'# spec/SPEC.md\n{(NGR / "spec" / "SPEC.md").read_text()}')
        for f in sorted((NGR / 'tests' / 'помилки').glob('*.ngr')):
            parts.append(f'# tests/помилки/{f.name}\n{f.read_text()}')
        for f in sorted((NGR / 'examples').glob('*.ngr')):
            parts.append(f'# examples/{f.name}\n{f.read_text()}\n# вивід {f.stem}.out\n{(f.with_suffix(".out")).read_text()}')
    return '\n\n'.join(parts)


def code_blocks(ans):
    found = {}
    for m in re.finditer(r'Завдання\W{0,3}([АБВГЖ])(?![а-яіїєґʼ])[^\n]*\n+```[^\n]*\n(.*?)```', ans, re.S):
        found[m.group(1).upper()] = m.group(2)
    return found


def run(code, letter):
    path = HERE / f'завдання_{letter}.ngr'
    path.write_text(code, encoding='utf-8')
    p = subprocess.run(['ngr', str(path)], capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout, p.stderr


def round1():
    history, log = [], ['# Gemini — розмова, раунд 1\n']
    fmt = ('Для кожного завдання дай код у форматі:\nЗавдання А\n```ngr\n…\n```\n'
           '(і так само Б, В, Г, Ж). Я запущу код справжнім інтерпретатором і покажу результат.')
    ans = say(history, log, f'{materials()}\n\nЦе ОГЛЯД 10б — коротке підтвердження умови суду 10 (ПІДСУМОК вище: суд 10 дав 7:0 «Б», автор виправив). Ти не можеш сам запускати `ngr --отримати`, `--печатка` чи `--розбір` — я запускаю лише твої програми справжнім ngr з власником суду, а модулі для задач уже у сховищі. Перевір запуском те, що можеш, і чесно познач, чого не перевіряв. Мінімум запусків: «Завдання А» — з модулем 「github.com/nigredo/tekst@b857639070f69dae3ddbda71c10b1ea49710b6c7/slova.ngr#sha256=e5647d12cab5e2dfe2486861a5db7bad42f194e8209b78860169209740804ac2」 надрукуй, скільки разів у `дані/вхід.txt` трапляються слова «агент» і «програма» (контроль: як у суді 10); «Завдання Б» — атака: передай у функцію модуля з мережі λ з дією (🜔 чи »), і окремо λ, що читає ⌂, — яка тепер помилка й чи названо модуль; «Завдання В» — запусти `чужа_з_модулем.ngr` як є (скопіюй текст); «Завдання Г» — з модулем 「github.com/nigredo/hroshi@4be41590b6d22f369abc42e49c11ed34246122ba/suma.ngr#sha256=1c6e78357d195b807853acbef25631f371b5cea37f3210b6790edf17a0808ce5」 надрукуй суму цін із `дані/ціни.json` з двома знаками. Дані — у теці `дані/` поруч із програмою. Не відповідай, доки не даси код. {fmt}')
    runs = {l: 0 for l in 'АБВГЖ'}
    done = set()
    while True:
        blocks = {l: c for l, c in code_blocks(ans).items() if l not in done}
        if not blocks:
            break
        feedback = []
        for l, c in blocks.items():
            if runs[l] >= MAX_RUNS:
                continue
            runs[l] += 1
            rc, out, err = run(c, l)
            feedback.append(f'Завдання {l}, запуск {runs[l]}/{MAX_RUNS}: код виходу {rc}\nstdout:\n{out or "(порожньо)"}\nstderr:\n{err or "(порожньо)"}')
        if not feedback:
            break
        ans = say(history, log, '\n\n'.join(feedback) +
                  '\n\nЯкщо завдання розвʼязане правильно — напиши «Завдання X: ГОТОВО» і не давай його код. '
                  f'Якщо ні — дай виправлений код у тому ж форматі. {fmt}')
        done |= {l for l in 'АБВГЖ' if re.search(rf'Завдання {l}\W+ГОТОВО', ans)}
    stats = ', '.join(f'{k}: {runs[l]} запусків' for l, k in zip('АБВГ', ('А (слова)', 'Б (атака)', 'В (чужа)', 'Г (гроші)')))
    report = say(history, log, f'Підсумок запусків (рахував скрипт): {stats}. Тепер напиши звіт раунду 1 '
                 'строго за шаблоном із ПРАВИЛ (Markdown, без вступу). Роль: «Gemini — незалежний експерт».')
    (HERE / 'звіт_раунд1.md').write_text(f'_Модель: {", ".join(sorted(set(USED)))}_\n\n' + report.strip() + '\n',
                                         encoding='utf-8')
    (HERE / 'розмова_раунд1.md').write_text('\n'.join(log), encoding='utf-8')


def round2():
    history, log = [], ['# Gemini — розмова, раунд 2\n']
    reports = '\n\n'.join(f'# Звіт: {f.stem}\n{f.read_text()}' for f in sorted((K / 'protokol' / 'раунд1').glob('*.md')))
    ans = say(history, log, f'{materials(spec=False)}\n\n{reports}\n\nЦе РАУНД 2. Вище — звіти першого раунду '
              'всіх учасників (твій теж). Напиши звіт_раунд2.md за правилами раунду 2: з чим згоден, з чим ні й '
              'чому (особливо — найсерйозніші знахідки інших, підкріплені запусками), що змінило думку, остаточний '
              'голос А/Б/В. Ти не можеш сам запускати код, тож не стверджуй як факт те, чого не перевіряв; '
              'твердження інших без запусків зважуй відповідно. Markdown, без вступу.')
    (HERE / 'звіт_раунд2.md').write_text(f'_Модель: {", ".join(sorted(set(USED)))}_\n\n' + ans.strip() + '\n',
                                         encoding='utf-8')
    (HERE / 'розмова_раунд2.md').write_text('\n'.join(log), encoding='utf-8')


if __name__ == '__main__':
    {'1': round1, '2': round2}[sys.argv[1]]()
