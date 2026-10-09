from ngrpy import *
seal("лише читати дані", ["файл.читати:дані"])
# 1. через інструмент — вихід ../ поза дозволену теку:
try:
    print(value(tool("файл.читати", "../власник/дозволи.json")))
    print("ЧИТАННЯ ../ ЧЕРЕЗ TOOL ВДАЛОСЯ")
except Exception as e:
    print("tool ../ блок:", type(e).__name__, e)
# 2. напряму open поза теку:
try:
    print(open("/etc/hostname").read())
    print("ЧИТАННЯ /etc/hostname НАПРЯМУ ВДАЛОСЯ")
except Exception as e:
    print("open /etc блок:", type(e).__name__, e)
# 3. через дозволену теку, але читаємо стандартну бібліотеку os і далі os.* (audit hook каже «читати stdlib можна»):
try:
    import os as _os
    data = open("/etc/passwd").read()
    print("passwd:", data[:30], "ВДАЛОСЯ")
except Exception as e:
    print("passwd блок:", type(e).__name__, e)
