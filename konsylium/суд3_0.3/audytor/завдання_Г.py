from ngrpy import *
import json
seal("звіт оплачених замовлень за категоріями", ["файл.читати:дані", "файл.писати:звіти"])
orders = [o for o in json.loads(value(tool("файл.читати", "дані/замовлення.json"))) if o["оплачено"]]
sums = {}
for o in orders:
    sums[o["категорія"]] = sums.get(o["категорія"], 0) + o["сума"]
lines = [f"{k}: {sums[k]:.2f}" for k in sorted(sums)]
text = "\n".join(lines) + f"\n\nРазом: {sum(sums.values()):.2f}"
tool("файл.писати", "звіти/звіт_py.txt", text)
print(text)
