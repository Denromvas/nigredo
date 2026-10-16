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

MODEL = 'gemini-3.6-flash'  # 3.7-flash: 503 перевантаження (суд 6, 2026-10-15)
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
    for attempt in range(9):            # перевантаження (503) — довше чекаємо й переходимо на запасні моделі
        model = (MODEL, 'gemini-3.5-flash', 'gemini-3.7-flash')[min(attempt // 3, 2)]
        req = urllib.request.Request(
            f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
            data=json.dumps(body).encode(), headers={'Content-Type': 'application/json', 'x-goog-api-key': key()})
        try:
            d = json.load(urllib.request.urlopen(req, timeout=600))
            break
        except urllib.error.HTTPError as e:
            if e.code not in (404, 429, 500, 503) or attempt == 8:
                raise
            time.sleep(30 * (attempt % 3 + 1))
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            if attempt == 8:                       # мережа телефона буває нестабільною
                raise
            time.sleep(30)
    return ''.join(p.get('text', '') for p in d['candidates'][0]['content']['parts'] if not p.get('thought'))


def say(history, log, text):
    history.append({'role': 'user', 'parts': [{'text': text}]})
    log.append(f'## → Gemini\n\n{text}\n')
    ans = ask(history)
    history.append({'role': 'model', 'parts': [{'text': ans}]})
    log.append(f'## ← Gemini\n\n{ans}\n')
    return ans


def materials(spec=True):
    parts = [f'# ПРАВИЛА\n{(K / "ПРАВИЛА.md").read_text()}', f'# ЗАВДАННЯ\n{(K / "ЗАВДАННЯ.md").read_text()}',
             f'# ДЛЯ_АГЕНТІВ.md\n{(NGR / "ДЛЯ_АГЕНТІВ.md").read_text()}',
             f'# ПЛАН_1.0.md\n{(NGR / "ПЛАН_1.0.md").read_text()}',
             f'# bench/РЕЗУЛЬТАТИ.md\n{(NGR / "bench" / "РЕЗУЛЬТАТИ.md").read_text()}',
             f'# bench/м2/РЕЗУЛЬТАТИ.md\n{(NGR / "bench" / "м2" / "РЕЗУЛЬТАТИ.md").read_text()}',
             f'# Підсумок суду 6\n{(K.parent / "суд6_0.5" / "protokol" / "ПІДСУМОК.md").read_text()}']
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
    ans = say(history, log, f'{materials()}\n\nВиконай РАУНД 1 сьомого суду. Атак сам запускати не можеш — оцінюй нове (SQLite, процес, ‖, --повторити, --сухо, шлях один раз, ε ∫ λ【a b】, послати) за кодом і специфікацією, чесно позначаючи, що не перевірено. Перша спроба: розвʼяжи задачі К1, К2 і К3 із ЗАВДАННЯ; у відповіді познач їх так: К1 = «Завдання А», К2 = «Завдання Б», К3 = «Завдання В». Дані — у теці `дані/` поруч із програмою. Не відповідай, доки не даси код. {fmt}')
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
    stats = ', '.join(f'{k}: {runs[l]} запусків' for l, k in zip('АБВ', ('К1', 'К2', 'К3')))
    report = say(history, log, f'Підсумок запусків (рахував скрипт): {stats}. Тепер напиши звіт раунду 1 '
                 'строго за шаблоном із ПРАВИЛ (Markdown, без вступу). Роль: «Gemini — незалежний експерт».')
    (HERE / 'звіт_раунд1.md').write_text(report.strip() + '\n', encoding='utf-8')
    (HERE / 'розмова_раунд1.md').write_text('\n'.join(log), encoding='utf-8')


def round2():
    history, log = [], ['# Gemini — розмова, раунд 2\n']
    reports = '\n\n'.join(f'# Звіт: {f.stem}\n{f.read_text()}' for f in sorted((K / 'protokol' / 'раунд1').glob('*.md')))
    ans = say(history, log, f'{materials(spec=False)}\n\n{reports}\n\nЦе РАУНД 2. Вище — звіти першого раунду '
              'всіх учасників (твій теж). Напиши звіт_раунд2.md за правилами раунду 2: з чим згоден, з чим ні й '
              'чому (особливо — найсерйозніші знахідки інших, підкріплені запусками), що змінило думку, остаточний '
              'голос А/Б/В. Ти не можеш сам запускати код, тож не стверджуй як факт те, чого не перевіряв; '
              'твердження інших без запусків зважуй відповідно. Markdown, без вступу.')
    (HERE / 'звіт_раунд2.md').write_text(ans.strip() + '\n', encoding='utf-8')
    (HERE / 'розмова_раунд2.md').write_text('\n'.join(log), encoding='utf-8')


if __name__ == '__main__':
    {'1': round1, '2': round2}[sys.argv[1]]()
