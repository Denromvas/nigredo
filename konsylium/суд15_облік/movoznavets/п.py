#!/usr/bin/env python3
"""п.py [-р 11,А,Е] ПРОГРАМА.ngr [прапорці] [-- аргументи]: кроки, код, зупинка, час і памʼять у кожному виконавці.
11 — норма 1.1 (ngr), А — 1.2 Атанор, Е — 1.2 еталон."""
import json
import os
import pathlib
import subprocess
import sys
import time

K = pathlib.Path(__file__).resolve().parent.parent
RUNS = {'11': ['ngr'], 'А': [str(K / 'ngr15.sh')], 'Е': [str(K / 'нгр15_еталон.sh')]}
args = sys.argv[1:]
which = ['11', 'А', 'Е']
if args and args[0] == '-р':
    which = args[1].split(',')
    args = args[2:]
prog, rest = args[0], args[1:]
if '--' in rest:
    i = rest.index('--')
    flags, pargs = rest[:i], rest[i:]
else:
    flags, pargs = rest, []
for w in which:
    cmd = [*RUNS[w], prog, *flags, '--слід', '-', *pargs]
    t = time.monotonic()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    last = None
    interp = ''
    out_lines = 0
    for line in p.stdout:
        if line.startswith(b'{"\xe2\x84\x96"'):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get('подія') == 'початок':
                interp = d.get('інтерпретатор', '')[:14]
            if 'кроків' in d:
                last = d
        else:
            out_lines += 1
    err = p.stderr.read().decode(errors='replace').strip().splitlines()
    _, status, use = os.wait4(p.pid, 0)
    dt = time.monotonic() - t
    code = os.waitstatus_to_exitcode(status)
    steps = last.get('кроків') if last else None
    ev = last.get('подія') if last else None
    stop = err[-1] if err else ''
    print(f'{w:>2}: код {code}, кроків {steps} ({ev}), {dt:.2f} с, {use.ru_maxrss // 1024} МБ, [{interp}] {stop[:160]}', flush=True)
