from ngrpy import *
import json
seal("суми оплачених замовлень за категоріями у звіт", ["файл.читати:дані", "файл.писати:звіти"])

orders = json.loads(value(tool("файл.читати", "дані/замовлення.json")))
sums = {}
for o in orders:
    if o["оплачено"]:
        sums[o["категорія"]] = sums.get(o["категорія"], 0) + o["сума"]
rows = [f"{k}: {sums[k]:.2f}" for k in sorted(sums)]
txt = "\n".join(rows) + f"\n\nРазом: {sum(sums.values()):.2f}"
tool("файл.писати", "звіти/звіт.txt", txt)
print(txt)
