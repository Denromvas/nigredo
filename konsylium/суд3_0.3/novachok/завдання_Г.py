from ngrpy import *
import json
seal("звіт за оплаченими замовленнями по категоріях", ["файл.читати:дані", "файл.писати:звіти"])

orders = json.loads(value(tool("файл.читати", "дані/замовлення.json")))
paid = [o for o in orders if o["оплачено"]]

totals = {}
for o in paid:
    totals[o["категорія"]] = totals.get(o["категорія"], 0) + o["сума"]

lines = [f"{k}: {totals[k]:.2f}" for k in sorted(totals)]
text = "\n".join(lines) + f"\n\nРазом: {sum(o['сума'] for o in paid):.2f}"

tool("файл.писати", "звіти/звіт.txt", text + "\n")
print(text)
