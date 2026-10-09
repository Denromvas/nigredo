import json
from ngrpy import *
seal("звіт за замовленнями", ["файл.читати:дані", "файл.писати:звіти"])

raw = tool("файл.читати", "дані/замовлення.json")
orders = json.loads(value(raw))

paid = [o for o in orders if o.get("оплачено")]

categories = {}
total = 0
for o in paid:
    cat = o["категорія"]
    s = o["сума"]
    categories[cat] = categories.get(cat, 0) + s
    total += s

sorted_cats = sorted(categories.keys())
lines = [f"{cat}: {categories[cat]}" for cat in sorted_cats]
report = "\n".join(lines) + f"\n\nРазом: {total}"

tool("файл.писати", "звіти/звіт.txt", report)
print(report)
