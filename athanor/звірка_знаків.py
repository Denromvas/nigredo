#!/usr/bin/env python3
"""Звірка гліфів знаків Атанора (1.4) з unicodedata того Python, яким запускають. ζ (NFC): кожен знак Unicode окремо, а
далі випадкові низки зі знаків, які нормалізація зачіпає (розкладні, з класом поєднання, перші й другі в парах
складання, хангиль). ψ (категорія) і ω (код і назад) — кожен знак.
Запуск: python3 athanor/звірка_знаків.py [БІНАРНИК] [--низок N]. Код 0 — розбіжностей немає."""
import json
import os
import random
import subprocess
import sys
import tempfile
import unicodedata as U

HERE = os.path.dirname(os.path.realpath(__file__))


def binary():
    import glob
    c = sorted(glob.glob(os.path.join(HERE, 'target', '*', 'release', 'athanor')), key=os.path.getmtime)
    return c[-1]


def run(bin_, strings, tmp, body='μ ζ р λз ω з'):
    """ζ над кожним рядком, результат — кодами знаків (ω): друк показує невидимі знаки як ⟨U+…⟩. Програма з самих ASCII
    (рядки — в JSON з \\u), тож Атанор виконує її сам."""
    data = json.dumps(strings, ensure_ascii=True).replace('\\', '\\\\').replace('」', '\\」')
    assert data.isascii()
    path = os.path.join(tmp, 'nfc.ngr')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('🜂 「звірка NFC」 【】\n» Δ μ δ 「' + data + '」 λр ' + body + '\n')
    r = subprocess.run([bin_, path, '--кроки', '2000000000', '--розмір', '200000000'], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f'✗ Атанор: код {r.returncode}: {r.stderr[-400:]}')
    return json.loads(r.stdout)


def main():
    args = sys.argv[1:]
    n = int(args[args.index('--низок') + 1]) if '--низок' in args else 400_000
    bins = [a for a in args if not a.startswith('--') and not a.isdigit()]
    bin_ = bins[0] if bins else binary()
    assert U.unidata_version == '15.1.0', f'Python з Unicode {U.unidata_version}, а мова — за 15.1'
    cps = [c for c in range(0x110000) if not 0xD800 <= c <= 0xDFFF]
    hot = [chr(c) for c in cps if U.combining(chr(c)) or U.normalize('NFD', chr(c)) != chr(c)
           or U.normalize('NFC', chr(c)) != chr(c)]
    firsts = set()
    for ch in hot:
        d = U.normalize('NFD', ch)
        firsts.update(d)
        for i in range(1, len(d)):
            firsts.add(U.normalize('NFC', d[:i]))
    hot = sorted(set(hot) | {x for x in firsts if len(x) == 1} | {chr(c) for c in range(0x1100, 0x1200)}
                 | {chr(0xAC00 + 28 * k) for k in range(0, 399, 7)} | set('aeoAEO '))
    rng = random.Random(16)
    seqs = [''.join(rng.choice(hot) for _ in range(rng.randint(2, 7))) for _ in range(n)]
    bad = total = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, items in (('кожен знак окремо', [chr(c) for c in cps]), ('випадкові низки', seqs)):
            for i in range(0, len(items), 100_000):
                part = items[i:i + 100_000]
                got = [''.join(map(chr, x)) for x in run(bin_, part, tmp)]
                for s, g in zip(part, got):
                    total += 1
                    if g != U.normalize('NFC', s):
                        bad += 1
                        if bad <= 10:
                            print(f'✗ {name}: {[hex(ord(c)) for c in s]} → {[hex(ord(c)) for c in g]}, '
                                  f'а треба {[hex(ord(c)) for c in U.normalize("NFC", s)]}')
            print(f'{name}: {len(items)}')
        for i in range(0, len(cps), 100_000):
            part = [chr(c) for c in cps[i:i + 100_000]]
            got = run(bin_, part, tmp, '【ψ р ω р ω ω ω р】')
            for s, g in zip(part, got):
                total += 1
                if g != [U.category(s), ord(s), ord(s)]:
                    bad += 1
                    if bad <= 10:
                        print(f'✗ ψ ω: {hex(ord(s))} → {g}, а треба {[U.category(s), ord(s), ord(s)]}')
        print(f'ψ і ω кожного знака: {len(cps)}')
    print(f'рядків {total}, знаків для низок {len(hot)}, розбіжностей {bad}')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
