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
                if not d.get('candidates'):                # відмова моделі — не обрив: повторювати те саме не можна
                    sys.exit(f'{model}: відповіді немає: {json.dumps(d.get("promptFeedback", d), ensure_ascii=False)[:300]}')
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
    for name in ('spec/пропозиції/вартість.md', 'athanor/src/interp.rs'):
        parts.append(f'# {name}\n{(NGR / name).read_text()}')
    return '\n\n'.join(parts)


def main():
    history, log = [], ['# Gemini — розмова, суд 14\n']
    report = say(history, log, f'{materials()}\n\nЦе СУД 14 про модель вартості: межі кроків і розміру, рецензія коду. Запускати код ти не можеш, тож пиши лише те, що видно з тексту, із посиланням на рядки, і так і позначай: «за читанням». Напиши звіт за шаблоном ПРАВИЛ (Markdown, без вступу). Роль: «Gemini — незалежний експерт».')
    (HERE / 'звіт_раунд1.md').write_text(f'_Модель: {", ".join(sorted(set(USED)))}_\n\n' + report.strip() + '\n', encoding='utf-8')
    (HERE / 'розмова_раунд1.md').write_text('\n'.join(log), encoding='utf-8')


if __name__ == '__main__':
    main()
