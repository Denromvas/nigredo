#!/usr/bin/env python3
"""Учасник консиліуму — Gemini (незалежна модель іншої компанії).

  python3 gemini_member.py     # один раунд: рецензія пропозиції й змін за текстом + звіт

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
    for name in ('spec/пропозиції/знаки.md',):
        parts.append(f'# {name}\n{(NGR / name).read_text()}')
    parts.append(f'# зміни проти 1.3 (git diff)\n{(K / "зміни.diff").read_text()}')
    return '\n\n'.join(parts)


def main():
    history, log = [], ['# Gemini — розмова, суд 17\n']
    report = say(history, log, f'{materials()}\n\nЦе СУД 17 про три нові гліфи мови Nigredo (1.4): η — нормальна форма NFC, ω — код знака й знак '
                 'за кодом, γ — категорія знака; наявне не змінюється. Запускати код ти не можеш: це рецензія '
                 'пропозиції, норми й змін за текстом (git diff вище). Чого не видно з тексту — так і пиши («за читанням», «не '
                 'перевірено запуском»). Напиши звіт за шаблоном ПРАВИЛ (Markdown, без вступу) з голосом. Роль: «Gemini — '
                 'незалежний експерт».')
    (HERE / 'звіт_раунд1.md').write_text(f'_Модель: {", ".join(sorted(set(USED)))}_\n\n' + report.strip() + '\n', encoding='utf-8')
    (HERE / 'розмова_раунд1.md').write_text('\n'.join(log), encoding='utf-8')


def main2():
    """Раунд 2: звіти раунду 1 й підсумок виправлень — остаточний голос."""
    history, log = [], ['# Gemini — розмова, суд 17, раунд 2\n']
    r1 = '\n\n'.join(f'# звіт раунду 1: {f.stem}\n{f.read_text()}' for f in sorted((K / 'protokol' / 'раунд1').glob('*.md')))
    text = (f'{materials()}\n\n{r1}\n\n# protokol/ПІДСУМОК.md\n{(K / "protokol" / "ПІДСУМОК.md").read_text()}\n\n'
            'Це РАУНД 2 суду 17. Прочитай звіти раунду 1 й підсумок виправлень; версія заморожена наново (ПРАВИЛА, «Раунд 2»). '
            'Запускати код ти не можеш: звір за текстом змін (git diff вище), чи виправлення справді закривають знахідки й чи не '
            'відкрили нових, позначай «за читанням». Напиши звіт раунду 2 за шаблоном ПРАВИЛ (Markdown, без вступу) з '
            'остаточним голосом. Роль: «Gemini — незалежний експерт».')
    report = say(history, log, text)
    (HERE / 'звіт_раунд2.md').write_text(f'_Модель: {", ".join(sorted(set(USED)))}_\n\n' + report.strip() + '\n', encoding='utf-8')
    (HERE / 'розмова_раунд2.md').write_text('\n'.join(log), encoding='utf-8')


if __name__ == '__main__':
    main2() if sys.argv[1:] == ['2'] else main()
