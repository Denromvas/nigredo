import subprocess, sys, os
cases = [l.rstrip("\n") for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
d = os.path.dirname(os.path.abspath(sys.argv[1]))
for c in cases:
    p = os.path.join(d, "т.ngr")
    with open(p, "w", encoding="utf-8") as f:
        f.write("🜂 「т」 【】\n" + c.replace("¶", "\n") + "\n")
    r = subprocess.run(["ngr", p], capture_output=True, text=True, timeout=60)
    out = (r.stdout + r.stderr).strip().replace("\n", " ⏎ ")
    print(f"{c}  →  [{r.returncode}] {out}")
