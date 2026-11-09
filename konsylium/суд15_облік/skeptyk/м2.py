#!/usr/bin/env python3
"""Раунд 2: python3 -I м2.py [-р нае] ПРОГРАМА.ngr [прапорці] — для кожного виконавця час, найбільша памʼять, код,
кроки й повідомлення з останнього запису сліду (слід — у сліди2/, вивід — у /dev/null).
н — норма 1.1 (ngr), а — 1.2 Атанор, е — 1.2 еталон."""
import json
import os
import pathlib
import sys
import time

K = pathlib.Path(__file__).resolve().parent
R = {'н': ('норма 1.1', ['ngr']), 'а': ('1.2 Атанор', [str(K.parent / 'ngr15.sh')]),
     'е': ('1.2 еталон', [str(K.parent / 'нгр15_еталон.sh')])}
args = sys.argv[1:]
which = 'нае'
if args[:1] == ['-р']:
    which, args = args[1], args[2:]
prog, rest = args[0], args[1:]
(K / 'сліди2').mkdir(exist_ok=True)
for w in which:
    name, cmd = R[w]
    tr = K / 'сліди2' / f'{pathlib.Path(prog).stem}_{w}.jsonl'
    err = K / 'сліди2' / f'{pathlib.Path(prog).stem}_{w}.err'
    if tr.exists():
        tr.unlink()
    pid = os.fork()
    if pid == 0:
        with open(os.devnull, 'w') as null, open(err, 'w') as e:
            os.dup2(null.fileno(), 1)
            os.dup2(e.fileno(), 2)
        # прапорці програми — після «--»: слід ставимо перед ними
        if '--' in rest:
            i = rest.index('--')
            a = [prog, *rest[:i], '--слід', str(tr), *rest[i:]]
        else:
            a = [prog, *rest, '--слід', str(tr)]
        os.execvp(cmd[0], [*cmd, *a])
    t = time.monotonic()
    _, status, use = os.wait4(pid, 0)
    dt = time.monotonic() - t
    last, interp = {}, ''
    try:
        with open(tr, 'rb') as f:
            first = f.readline()
            try:
                interp = json.loads(first).get('інтерпретатор', '')[:14]
            except Exception:
                pass
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 20000))
            lines = f.read().splitlines()
            for ln in reversed(lines):
                try:
                    last = json.loads(ln)
                    break
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    e = open(err, encoding='utf-8', errors='replace').read().strip().splitlines()
    msg = last.get('повідомлення') or (e[-1] if e else '')
    print(f'{name}: код {os.waitstatus_to_exitcode(status)}, {dt:.2f} с, {use.ru_maxrss // 1024} МБ, '
          f'кроків {last.get("кроків", "?")}, {last.get("подія", "?")} [{interp}] {msg[:150]}', flush=True)
