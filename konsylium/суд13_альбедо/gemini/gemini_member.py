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


def materials():
    parts = [f'# ПРАВИЛА\n{(K / "ПРАВИЛА.md").read_text()}', f'# ЗАВДАННЯ\n{(K / "ЗАВДАННЯ.md").read_text()}']
    for name in ('spec/пропозиції/альбедо.md', 'albedo/хост.mjs', 'albedo/src/lib.rs', 'albedo/c/база.c', 'albedo/зло/src/lib.rs', 'albedo/перевірити.py',
                 'athanor/src/seal.rs', 'athanor/src/sys.rs', 'ДЛЯ_АГЕНТІВ.md'):
        parts.append(f'# {name}\n{(NGR / name).read_text()}')
    return '\n\n'.join(parts)


def attacks(ans):
    """«Атака А» + блок rust + блок ngr: файли модуля й програми."""
    found = {}
    for m in re.finditer(r'Атака\W{0,3}([АБВГД])(?![а-яіїєґʼ])[^\n]*\n+```rust[^\n]*\n(.*?)```\s*```[^\n]*\n(.*?)```', ans, re.S):
        found[m.group(1).upper()] = (m.group(2), m.group(3))
    return found


def run(code, prog, letter):
    rs, ngr = HERE / f'атака_{letter}.rs', HERE / f'атака_{letter}.ngr'
    rs.write_text(code, encoding='utf-8')
    ngr.write_text(prog, encoding='utf-8')
    p = subprocess.run([str(K / 'зло.sh'), str(rs), str(ngr), '--строк', '20'], capture_output=True, text=True, timeout=180, cwd=HERE)
    return p.returncode, p.stdout, p.stderr


def round1():
    history, log = [], ['# Gemini — розмова, раунд 1\n']
    fmt = ('Для кожної атаки дай у такому вигляді:\nАтака А\n```rust\n…модуль…\n```\n```ngr\n…програма…\n```\n(і так само Б, В, Г, Д, до пʼяти). '
           'Я зберу модуль і запущу під господарем, а результат покажу.')
    ans = say(history, log, f'{materials()}\n\nЦе ТРИНАДЦЯТИЙ СУД — Альбедо. Прочитай код господаря й скажи, де межа слабка. {fmt}')
    runs = {l: 0 for l in 'АБВГД'}
    done = set()
    while True:
        blocks = {l: c for l, c in attacks(ans).items() if l not in done}
        if not blocks:
            break
        feedback = []
        for l, (c, g) in blocks.items():
            if runs[l] >= MAX_RUNS:
                continue
            runs[l] += 1
            rc, out, err = run(c, g, l)
            feedback.append(f'Атака {l}, запуск {runs[l]}/{MAX_RUNS}: код виходу {rc}\nstdout:\n{out[:3000] or "(порожньо)"}\nstderr:\n{err[:3000] or "(порожньо)"}')
        if not feedback:
            break
        ans = say(history, log, '\n\n'.join(feedback) + f'\n\nЯкщо атаку завершено — напиши «Атака X: ГОТОВО». Якщо ні — дай виправлену в тому ж форматі. {fmt}')
        done |= {l for l in 'АБВГД' if re.search(rf'Атака {l}\W+ГОТОВО', ans)}
    report = say(history, log, f'Запусків: {runs}. Тепер напиши звіт раунду 1 строго за шаблоном із ПРАВИЛ (Markdown, без вступу). Роль: «Gemini — незалежний експерт».')
    (HERE / 'звіт_раунд1.md').write_text(f'_Модель: {", ".join(sorted(set(USED)))}_\n\n' + report.strip() + '\n', encoding='utf-8')
    (HERE / 'розмова_раунд1.md').write_text('\n'.join(log), encoding='utf-8')


def round2():
    history, log = [], ['# Gemini — розмова, раунд 2\n']
    reports = '\n\n'.join(f'# Звіт: {f.stem}\n{f.read_text()}' for f in sorted((K / 'protokol' / 'раунд1').glob('*.md')))
    ans = say(history, log, f'{materials()}\n\n{reports}\n\nЦе РАУНД 2. Вище — звіти першого раунду всіх учасників (твій теж). Напиши звіт_раунд2.md за правилами раунду 2: '
              'з чим згоден і чому, що знято, голос А/Б/В. Сам запускати код у цьому раунді ти не можеш, тож не стверджуй як факт те, чого не бачив. Markdown, без вступу.')
    (HERE / 'звіт_раунд2.md').write_text(f'_Модель: {", ".join(sorted(set(USED)))}_\n\n' + ans.strip() + '\n', encoding='utf-8')
    (HERE / 'розмова_раунд2.md').write_text('\n'.join(log), encoding='utf-8')


if __name__ == '__main__':
    {'1': round1, '2': round2}[sys.argv[1]]()
