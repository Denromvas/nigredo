#!/usr/bin/env python3
"""Підсумок вибіркового профілю Атанора: python3 athanor/профіль.py ФАЙЛ_АДРЕС… [--bin БІНАРНИК] — функції за частками.
Кожен файл (ATHANOR_SAMPLE) починається рядком «start АДРЕСА» — де в процесі sampler::start (PIE: зсув завантаження)."""
import bisect, collections, os, subprocess, sys
HERE = os.path.dirname(os.path.realpath(__file__))
args = sys.argv[1:]
binp = os.path.join(HERE, 'target/aarch64-unknown-linux-gnu/release/athanor')
if '--bin' in args:
    i = args.index('--bin')
    binp = args[i + 1]
    del args[i:i + 2]
syms = []
for line in subprocess.run(['nm', '-C', '--defined-only', binp], capture_output=True, text=True).stdout.splitlines():
    p = line.split(' ', 2)
    if len(p) == 3 and p[1] in 'tTwW':
        syms.append((int(p[0], 16), p[2]))
syms.sort()
start = next((a for a, n in syms if n.endswith('sampler::start')), 0)
pcs, libpcs, libsyms = [], collections.Counter(), {}


def lib_symbols(path):
    if path not in libsyms:
        out = []
        for line in subprocess.run(['nm', '-D', '--defined-only', path], capture_output=True, text=True).stdout.splitlines():
            p = line.split()
            if len(p) == 3 and p[1] in 'tTwWiI':
                out.append((int(p[0], 16), p[2]))
        out.sort()
        libsyms[path] = out
    return libsyms[path]


for path in args:
    delta, libs = 0, []
    for x in open(path).read().split('\n'):
        if x.startswith('start '):
            delta = int(x.split()[1], 16) - start
        elif x.startswith('lib '):
            _, a, b, off, lp = x.split(' ', 4)
            libs.append((int(a, 16), int(b, 16), int(off, 16), lp))
        elif x:
            pc = int(x, 16)
            lib = next((l for l in libs if l[0] <= pc < l[1]), None)
            if lib and 'athanor' not in os.path.basename(lib[3]):    # у proot бінарник видно як .l2s.athanor-…
                rel = pc - lib[0] + lib[2]
                ss = lib_symbols(lib[3])
                i = bisect.bisect_right([q for q, _ in ss], rel) - 1
                libpcs[f'{os.path.basename(lib[3])}:{ss[i][1] if i >= 0 else "?"}'] += 1
            else:
                pcs.append(pc - delta)
addrs = [a for a, _ in syms]
c = collections.Counter()
for pc in pcs:
    i = bisect.bisect_right(addrs, pc) - 1
    c[syms[i][1][:110] if i >= 0 else '?'] += 1
c.update(libpcs)
tot = sum(c.values())
print(f'вибірок: {tot}')
for name, n in c.most_common(int(os.environ.get('TOP', '40'))):
    print(f'{100 * n / tot:5.1f}%  {name}')
