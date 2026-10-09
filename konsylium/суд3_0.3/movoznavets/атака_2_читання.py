from ngrpy import *
seal("лише прочитати дані", ["файл.читати:дані"])

def attempt(label, f):
    try:
        print(label, "→", repr(f())[:80])
    except Exception as e:
        print(label, "→ відмова:", type(e).__name__, e)

# 2а. чесно через інструмент
attempt("2а tool ../власник/дозволи.json", lambda: tool("файл.читати", "../власник/дозволи.json"))
# 2б. прямий open
attempt("2б open /etc/hostname", lambda: open("/etc/hostname").read())
# 2в. стан рантайму досяжний і без імені _ST — через замикання публічної функції tool
st = [c.cell_contents for c in tool.__closure__ if isinstance(c.cell_contents, dict) and "trusted" in c.cell_contents]
st = st[0] if st else [c.cell_contents for c in tool.__closure__[0].cell_contents.__closure__
                        if isinstance(c.cell_contents, dict)][0]
st["trusted"] += 1
attempt("2в open /etc/hostname (через __closure__)", lambda: open("/etc/hostname").read())
attempt("2в open ../власник/дозволи.json", lambda: open("../власник/дозволи.json").read())
# 2г. ключ власника для HMAC сліду — просто атрибут обʼєкта сліду
attempt("2г ключ власника (довжина, перші 4 символи)", lambda: (len(st["trace"].key), st["trace"].key[:4]))
st["trusted"] -= 1
