#!/usr/bin/env python3
"""Збирає interpreter/літери.tsv — літери, яких UTS #39 не радить для імен (Identifier_Status = Restricted:
технічні, застарілі, рідковживані …), з двох файлів Unicode Security Mechanisms:

    python3 interpreter/зібрати_літери.py IdentifierStatus.txt IdentifierType.txt > interpreter/літери.tsv

Файли — https://www.unicode.org/Public/security/latest/. Беруться лише літери письм, дозволених в іменах (NAME_SCRIPTS),
які NFKC не змінює: решту ловлять правила «письмо», «символи сумісності» й «заповнювач» (суд 9д: ƻ ≈ 2, ꜫ ≈ 3,
ꜭ ≈ 4 — ручна таблиця двійників цифр клас не закривала)."""
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import nigredo as N  # noqa: E402


def load(path):
    """Код → значення з файлу UTS #39 («A..B ; значення # …») і рядки Version/Date заголовка."""
    out, head = {}, {}
    for line in open(path, encoding='utf-8'):
        m = re.match(r'# (Version|Date): (.*)', line)
        if m:
            head[m[1]] = m[2].strip()
        line = line.split('#')[0].strip()
        if line:
            r, v = (x.strip() for x in line.split(';'))
            a, _, b = r.partition('..')
            for cp in range(int(a, 16), int(b or a, 16) + 1):
                out[cp] = v
    return out, head


def main():
    status, head = load(sys.argv[1])
    types, _ = load(sys.argv[2])
    runs = []
    for cp in range(0x110000):
        ch = chr(cp)
        if (status.get(cp, 'Restricted') != 'Allowed' and N.is_name_start(ch) and ch != '_'
                and N.script_of(ch) in N.NAME_SCRIPTS and unicodedata.normalize('NFKC', ch) == ch):
            t = types.get(cp, 'Not_Characters')
            if runs and runs[-1][1] == cp - 1 and runs[-1][2] == t:
                runs[-1][1] = cp
            else:
                runs.append([cp, cp, t])
    print('# Літери, яких UTS #39 (Unicode Security Mechanisms) не радить для імен: Identifier_Status = Restricted.')
    print(f'# Джерело: https://www.unicode.org/Public/security/latest/IdentifierStatus.txt і IdentifierType.txt '
          f'(Version: {head.get("Version")}, Date: {head.get("Date")}); Unicode Terms of Use')
    print('# Лише літери письм, дозволених в іменах, які NFKC не змінює. Збирає interpreter/зібрати_літери.py.')
    print('# Формат: перший<TAB>останній<TAB>тип за IdentifierType (коди hex).')
    for a, b, t in runs:
        print(f'{a:04X}\t{b:04X}\t{t}')


if __name__ == '__main__':
    main()
