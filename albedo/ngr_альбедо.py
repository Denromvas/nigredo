#!/usr/bin/env python3
"""Альбедо під виглядом `ngr`: запуск програми — у модулі через господаря, службові дії (печатка, перевірка сліду, розбір) — еталон,
бо вони нічого не виконують. Для `ngr --альбедо` і test.py (NGR_TEST_BIN). Запасного шляху для запуску немає: чого модуль не вміє,
він відмовляє кодом 120, а не віддає еталону, інакше межа була б вигаданою. Виняток — ALBEDO_FALLBACK=1, лише для тестів."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
HOST = os.path.join(HERE, 'хост.mjs')
WASM = os.path.join(HERE, 'target', 'wasm32-unknown-unknown', 'release', 'albedo.wasm')
REF = os.path.join(HERE, '..', 'interpreter', 'ngr.py')
RUN = {'--слід', '--зерно', '--кроки', '--розмір', '--слід-розмір'}


def main():
    argv = sys.argv[1:]
    cut = argv.index('--') if '--' in argv else len(argv)
    head, tail = argv[:cut], argv[cut + 1:]
    opts, prog, i = [], None, 0
    while i < len(head):
        if head[i] in RUN:
            opts += head[i:i + 2]
            i += 2
        elif head[i].startswith('-') or prog is not None:
            os.execv(sys.executable, [sys.executable, REF, *argv])
        else:
            prog = head[i]
            i += 1
    if prog is None:
        os.execv(sys.executable, [sys.executable, REF, *argv])
    # помилки до запуску (розбір, типи, печатка) друкує й записує в слід еталон: тексти ті самі, а сама програма ще не виконується.
    # Це не межа: що б він тут не сказав, дії перевіряє господар
    pre = subprocess.run([sys.executable, REF, '--до-запуску', *opts, prog, '--', *tail])
    if pre.returncode:
        sys.exit(pre.returncode)
    cmd = ['node', HOST, *opts, WASM, prog, '--', *tail]
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
