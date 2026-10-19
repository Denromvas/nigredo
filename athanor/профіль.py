#!/usr/bin/env python3
"""Підсумок вибіркового профілю Атанора: python3 athanor/профіль.py ФАЙЛ_АДРЕС [БІНАРНИК] — функції за частками."""
import bisect, collections, os, subprocess, sys
HERE = os.path.dirname(os.path.realpath(__file__))
pcs = [int(x, 16) for x in open(sys.argv[1]).read().split()]
binp = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, 'target/aarch64-unknown-linux-musl/release/athanor')
syms = []
for line in subprocess.run(['nm', '-C', '--defined-only', binp], capture_output=True, text=True).stdout.splitlines():
    p = line.split(' ', 2)
    if len(p) == 3 and p[1] in 'tTwW':
        syms.append((int(p[0], 16), p[2]))
syms.sort()
addrs = [a for a, _ in syms]
c = collections.Counter()
for pc in pcs:
    i = bisect.bisect_right(addrs, pc) - 1
    c[syms[i][1][:110] if i >= 0 else '?'] += 1
tot = sum(c.values())
print(f'вибірок: {tot}')
for name, n in c.most_common(int(os.environ.get('TOP', '40'))):
    print(f'{100 * n / tot:5.1f}%  {name}')
