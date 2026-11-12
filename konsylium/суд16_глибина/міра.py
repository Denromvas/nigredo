#!/usr/bin/env python3
"""Код, час і найбільша памʼять однієї програми в чотирьох запусках: нинішня норма (1.2) і три виконавці 1.3."""
import os
import pathlib
import sys
import time

K = pathlib.Path(__file__).resolve().parent
RUNS = (('норма 1.2 (ngr)', ['ngr']), ('1.3, Атанор', [str(K / 'ngr16.sh')]), ('1.3, еталон', [str(K / 'нгр16_еталон.sh')]),
        ('1.3, Альбедо', [str(K / 'нгр16_альбедо.sh')]))
for name, cmd in RUNS:
    pid = os.fork()
    if pid == 0:
        with open(os.devnull, 'w') as null:
            os.dup2(null.fileno(), 1)
        os.execvp(cmd[0], [*cmd, *sys.argv[1:]])
    t = time.monotonic()
    _, status, use = os.wait4(pid, 0)
    print(f'{name}: код {os.waitstatus_to_exitcode(status)}, {time.monotonic() - t:.2f} с, памʼять {use.ru_maxrss // 1024} МБ', flush=True)
