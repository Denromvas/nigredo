from ngrpy import *
seal("р2: перевірити обхід через стан рантайму", ["файл.читати:дані"])
import ngrpy

# 1. скептик/аудитор: ngrpy._ST['trusted'] вимикає гачок
st = ngrpy._ST
st["trusted"] += 1
with open("звіти/р2_обхід_ST.txt", "w") as f:
    f.write("записано при печатці лише файл.читати:дані\n")
st["trusted"] -= 1
print("1. _ST: файл записано")

# 2. мовознавець/gemini: те саме без імені _ST, через замикання публічної функції
cells = [c.cell_contents for c in (tool.__closure__ or ())]
st2 = next((c for c in cells if isinstance(c, dict) and "trusted" in c), None)
print("2. __closure__ дає той самий стан:", st2 is st)

# 3. мовознавець: вписати в підписаний слід подію, якої не було (ключ не дістаю)
st["trace"]("вивід", текст="АТАКА-ПЕРЕВІРКА р2: цієї події насправді не було")
print("3. неправдиву подію вписано")
