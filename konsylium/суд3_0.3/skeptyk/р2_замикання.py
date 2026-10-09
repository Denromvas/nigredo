from ngrpy import *
seal("раунд 2: чи досяжний стан ngrpy без імені _ST", ["файл.читати:дані"])

# перевірка заяв мовознавця й Gemini: стан рантайму — через __closure__ публічної функції
st = None
for cell in (tool.__closure__ or ()):
    v = cell.cell_contents
    if isinstance(v, dict) and "trusted" in v:
        st = v
print("стан знайдено через tool.__closure__:", st is not None)
if st is not None:
    st["trusted"] += 1
    with open("/etc/hostname") as f:
        print("/etc/hostname прочитано, довжина:", len(f.read()))
    st["trusted"] -= 1
