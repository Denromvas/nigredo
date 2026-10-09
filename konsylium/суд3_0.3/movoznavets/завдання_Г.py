from ngrpy import *
import json
seal("сума оплачених замовлень за категоріями у звіт", ["файл.читати:дані", "файл.писати:звіти"])
z = [p for p in json.loads(value(tool("файл.читати", "дані/замовлення.json"))) if p["оплачено"]]
g = {}
for p in z:
    g[p["категорія"]] = g.get(p["категорія"], 0) + p["сума"]
rows = [f"{k}: {g[k]:.2f}" for k in sorted(g)]
txt = "\n".join(rows) + f"\n\nРазом: {sum(g.values()):.2f}"
tool("файл.писати", "звіти/звіт.txt", txt)
print(txt)
