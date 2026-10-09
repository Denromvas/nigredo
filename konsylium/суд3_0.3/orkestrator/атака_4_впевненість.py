from ngrpy import *
seal("ціль 4: підняти впевненість оракула без set_conf", ["оракул"])
a = tool("оракул", "чи золото вже близько?")
print("оракул:", conf(a))
# спроба: зняти U через value() і перезагорнути з впевненістю 1.0
laundered = U(value(a), 1.0)
print("відмито:", conf(laundered))
