from ngrpy import *
seal("перевірка: чи пише код в умові check() повз печатку", ["файл.читати:дані"])

def умова(v):
    with open("звіти/р2_check.txt", "w") as f:
        f.write("записано з умови check()\n")
    return True

check(1, умова)
print("check пройдено")
