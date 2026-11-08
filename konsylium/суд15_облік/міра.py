#!/usr/bin/env python3
"""Час і найбільша памʼять однієї програми в трьох запусках: нинішня норма (1.1), 1.2 в Атанорі, 1.2 в еталоні."""
import os
import pathlib
import resource
import subprocess
import sys
import time

K = pathlib.Path(__file__).resolve().parent
RUNS = (('норма 1.1 (ngr)', ['ngr']), ('1.2, Атанор', [str(K / 'ngr15.sh')]), ('1.2, еталон', [str(K / 'нгр15_еталон.sh')]))
for name, cmd in RUNS:
    pid = os.fork()
    if pid == 0:
        with open(os.devnull, 'w') as null:
            os.dup2(null.fileno(), 1)
        os.execvp(cmd[0], [*cmd, *sys.argv[1:]])
    t = time.monotonic()
    _, status, use = os.wait4(pid, 0)
    print(f'{name}: код {os.waitstatus_to_exitcode(status)}, {time.monotonic() - t:.2f} с, памʼять {use.ru_maxrss // 1024} МБ')
