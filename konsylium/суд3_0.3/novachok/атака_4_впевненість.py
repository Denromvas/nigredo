from ngrpy import *
seal("підняти впевненість без set_conf", ["оракул"])
v = tool("оракул", "чи світ чорніє?")
print(conf(v))
# спроба 1: зняти U і загорнути заново — це публічний API з памʼятки
v2 = U(value(v), 1.0)
print(conf(v2))
# спроба 2: просто value() — впевненість губиться, conf звичайного значення
print(conf(value(v)))
