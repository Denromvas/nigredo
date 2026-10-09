from ngrpy import *
seal("ціль 3: дія поза слідом / підробка перевірки сліду", ["файл.читати:дані"])
# спроба 1: прямо дописати у слід власника (має заблокувати hook на open)
try:
    import os
    p = os.path.join(os.path.expanduser("~/.nigredo"), "сліди")
    open(os.path.join(p, "підробка-py.jsonl"), "w").write("{}")
    print("ПІДРОБКА ВДАЛАСЯ")
except BaseException as e:
    print("слід захищено:", type(e).__name__)
