from ngrpy import *
seal("підняти впевненість відповіді оракула без set_conf", ["оракул"])

with delegate("провидець", "спитати", ["оракул"]):
    a = tool("оракул", "чи золото вже близько?")
print("оракул:", a.v, "впевненість", conf(a))

b = U(a.v)                                   # 1) новий U з «сирого» значення
c = value(a)                                 # 2) value() — памʼятка чесно каже, що губить
d = [x for x in (True, False) if x == a.v][0]  # 3) вибір за значенням
print("U(a.v):", conf(b), "| value(a):", conf(c), "| вибір:", conf(d))
print("sift 0.6 лишив:", len(sift([b, c, d], 0.6)))
