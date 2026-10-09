from ngrpy import *
import json
from collections import Counter
from statistics import median

seal("статистика чисел", ["файл.читати:дані"])


class Stats:
    def __init__(self, xs):
        self.xs = sorted(xs)

    def summary(self):
        c = Counter(self.xs)
        return {"мін": self.xs[0], "макс": self.xs[-1], "медіана": median(self.xs),
                "найчастіше": c.most_common(1)[0][0], "унікальних": len(c)}


raw = tool("файл.читати", "дані/числа.json")
s = Stats(json.loads(value(raw))).summary()
for k in sorted(s):
    print(f"{k}: {s[k]}")
