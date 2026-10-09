from ngrpy import *
import json
seal("суми оплачених замовлень за категоріями у звіт", ["файл.читати:дані", "файл.писати:звіти"])

orders = json.loads(value(tool("файл.читати", "дані/замовлення.json")).lstrip("﻿"))
paid = [o for o in orders if o["оплачено"]]
sums = {}
for o in paid:
    sums[o["категорія"]] = sums.get(o["категорія"], 0) + o["сума"]
ua = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя"
key = lambda s: [ua.index(ch) if ch in ua else 100 + ord(ch) for ch in s.lower()]
rows = [f"{k}: {v:.2f}" for k, v in sorted(sums.items(), key=lambda kv: key(kv[0]))]
txt = "\n".join(rows) + f"\n\nРазом: {sum(o['сума'] for o in paid):.2f}"
tool("файл.писати", "звіти/звіт.txt", txt)
print(txt)
