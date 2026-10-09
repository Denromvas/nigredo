from ngrpy import *
seal("підняти впевненість оракула без set_conf", ["оракул"])
ans = tool("оракул", "чи ртуть жива?")
print("було:", conf(ans))
# 1. сконструювати нове U з тим самим значенням і впевненістю 0.99 — set_conf не викликається, сліду нема:
faked = U(value(ans), 0.99)
print("після U(value,0.99):", conf(faked), "— сліду про це НЕМА")
# 2. через value() і назад:
laundered = U(value(ans))  # типово 1.0
print("після value()+U():", conf(laundered))
