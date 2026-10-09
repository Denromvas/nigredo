#!/usr/bin/env python3
"""Прогнати examples/*.ngr і порівняти stdout з examples/*.out."""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
NGR = ROOT / 'interpreter' / 'nigredo.py'

failed = 0
for src in sorted((ROOT / 'examples').glob('*.ngr')):
    expected = src.with_suffix('.out')
    if not expected.exists():
        print(f'? {src.name}: немає {expected.name}')
        failed += 1
        continue
    got = subprocess.run([sys.executable, str(NGR), str(src)], capture_output=True, text=True)
    if got.returncode == 0 and got.stdout == expected.read_text(encoding='utf-8'):
        print(f'✓ {src.name}')
    else:
        failed += 1
        print(f'✗ {src.name} (код {got.returncode})\n{got.stderr}')
sys.exit(1 if failed else 0)
