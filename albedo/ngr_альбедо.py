#!/usr/bin/env python3
"""Альбедо під виглядом `ngr`: запуск програми — у модулі через господаря; дії, що нічого не виконують (печатка, перевірка сліду, розбір), —
еталон. Усе, що виконало б програму повз модуль (`--сухо`, `-e`, `--тека`, `--повторити`, `--repl`), поки відмовляє кодом 120: тихий запуск
еталоном зробив би межу вигаданою. Виняток — ALBEDO_FALLBACK=ФАЙЛ, лише для test.py: там запасний шлях потрібен, щоб порівнювати, і він
веде облік."""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
HOST = os.path.join(HERE, 'хост.mjs')
WASM = os.path.join(HERE, 'target', 'wasm32-unknown-unknown', 'release', 'albedo.wasm')
REF = os.path.join(HERE, '..', 'interpreter', 'ngr.py')
RUN = {'--слід', '--зерно', '--кроки', '--розмір', '--слід-розмір'}           # їх знає й перевірка до запуску
HOST_ONLY = {'--строк', '--памʼять', '--бд-запис'}                            # лише господар
SERVICE = {'--печатка', '--розбір', '--перевірити', '--схвалити', '--формат', '--перевірити-слід', '--перевірити-підпис', '--перевірити-ізоляцію',
           '--отримати', '--ключ-автора', '--відбиток', '--памʼятка', '--памʼятка-коротка', '--help', '-h', '--версія'}


def refuse(what):
    if os.environ.get('ALBEDO_FALLBACK'):
        os.execv(sys.executable, [sys.executable, REF, *sys.argv[1:]])
    print(f'альбедо: цього в модулі ще немає, програму не запущено ({what})', file=sys.stderr)
    sys.exit(120)


def native():
    """Перевірка до запуску: Атанор за 0,03 с, а чого не вміє, сам віддасть еталону з тими самими текстами; без нього — еталон."""
    found = glob.glob(os.path.join(HERE, '..', 'athanor', 'target', '*', 'release', 'athanor'))
    return [max(found, key=os.path.getmtime)] if found else [sys.executable, REF]


def main():
    argv = sys.argv[1:]
    cut = argv.index('--') if '--' in argv else len(argv)
    head, tail = argv[:cut], argv[cut + 1:]
    if not head or any(a in SERVICE for a in head):
        os.execv(sys.executable, [sys.executable, REF, *argv])
    pre, only, prog, i = [], [], None, 0
    while i < len(head):
        if head[i] in RUN:
            pre += head[i:i + 2]
            i += 2
        elif head[i] in HOST_ONLY:
            only += head[i:i + 2]
            i += 2
        elif head[i].startswith('-'):
            refuse(head[i])
        elif prog is not None:
            refuse('зайвий аргумент: аргументи програми — після --')
        else:
            prog = head[i]
            i += 1
    if prog is None:
        os.execv(sys.executable, [sys.executable, REF, *argv])
    # помилки до запуску (розбір, типи, печатка) друкує й записує в слід той самий виконавець, що й завжди: тексти ті самі, а сама програма ще не
    # виконується. Це не межа: що б він тут не сказав, дії перевіряє господар
    chk = subprocess.run([*native(), '--до-запуску', *pre, prog, '--', *tail])
    if chk.returncode:
        sys.exit(chk.returncode)
    cmd = ['node', HOST, *pre, *only, WASM, prog, '--', *tail]
    if not os.environ.get('ALBEDO_FALLBACK'):
        os.execvp('node', cmd)
    # лише для test.py: те, чого модуль не вміє, виконає еталон — так само, як тести йдуть на Атанорі
    run = subprocess.run(cmd, stderr=subprocess.PIPE)
    with open(os.environ['ALBEDO_FALLBACK'], 'a', encoding='utf-8') as log:   # значення змінної — файл обліку: хто що виконав
        log.write(('еталон ' + run.stderr.decode('utf-8', 'replace').strip()[:70] if run.returncode == 120 else 'модуль') + '\n')
    if run.returncode == 120:
        os.execv(sys.executable, [sys.executable, REF, *argv])
    sys.stderr.buffer.write(run.stderr)
    sys.exit(run.returncode)


main()
