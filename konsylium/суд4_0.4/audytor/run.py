"""Допоміжний: запускає кожен .ngr з аргументів (з теки файлу), друкує вивід і код виходу."""
import os, subprocess, sys

for f in sys.argv[1:]:
    print("===", f, flush=True)
    d = os.path.dirname(os.path.abspath(f))
    try:
        r = subprocess.run(["ngr", os.path.basename(f)], cwd=d, capture_output=True, text=True, timeout=300)
        out = (r.stdout + r.stderr).splitlines()
        print("\n".join(out[:40]) + ("\n…" if len(out) > 40 else ""))
        print("код", r.returncode, flush=True)
    except subprocess.TimeoutExpired:
        print("ТАЙМАУТ 300 с", flush=True)
