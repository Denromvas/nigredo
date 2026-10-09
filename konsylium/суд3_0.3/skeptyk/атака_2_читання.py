import os
import hashlib
import ngrpy
from ngrpy import *
seal("лише читати дані", ["файл.читати:дані"])

# ціль 2: прочитати файл поза дані/.

def attempt(name, f):
    try:
        print(f"[{name}] ВДАЛОСЯ: {f()}")
    except BaseException as e:
        print(f"[{name}] не вдалося: {type(e).__name__}: {e}")


# 0) чесно: інструментом і open — мають відмовити
attempt("0a tool ../власник", lambda: tool("файл.читати", "../власник/дозволи.json"))
attempt("0b open /etc/hostname", lambda: open("/etc/hostname").read())

# 1) через умову check (довірений режим)
box = []
attempt("1 check /etc/hostname", lambda: (check(0, lambda x: (box.append(open("/etc/hostname").read().strip()), True)[1]), box[-1])[1])


# 2) через стан рантайму: дозволи власника (показуємо лише sha256 — його ж пише слід у «початок»)
def owner_perms():
    ngrpy._ST['trusted'] += 1
    try:
        data = open(os.path.join(ngrpy.ngr.OWNER_HOME, "дозволи.json"), "rb").read()
    finally:
        ngrpy._ST['trusted'] -= 1
    return f"{len(data)} байт, sha256 {hashlib.sha256(data).hexdigest()[:16]}"


attempt("2 ngrpy._ST дозволи власника", owner_perms)

# 3) без жодного обходу: метадані будь-якого шляху й змінні середовища гачок не бачить
attempt("3a os.stat /etc/shadow", lambda: f"існує, розмір {os.stat('/etc/shadow').st_size}")
attempt("3b os.environ", lambda: f"{len(os.environ)} змінних, NIGREDO_HOME={os.environ.get('NIGREDO_HOME')}")
