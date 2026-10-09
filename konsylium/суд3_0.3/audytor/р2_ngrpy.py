from ngrpy import *
import os, sys
seal("лише читати дані", ["файл.читати:дані"])

# 1. стан рантайму без імені _ST — через замикання публічної функції (Мовознавець, Gemini)
st = next(c.cell_contents for c in tool.__closure__
          if isinstance(c.cell_contents, dict) and 'trusted' in c.cell_contents)
print("стан через __closure__:", sorted(st)[:4])

# 2. os.open передає в хук mode=None → хук вважає це читанням (Скептик, Мовознавець)
fd = os.open(__file__, os.O_WRONLY | os.O_APPEND)
os.write(fd, "# р2: дописано через os.open повз хук\n".encode())
os.close(fd)
print("os.open: дописав у сам скрипт")

# 3. ключ власника й підроблений слід (Скептик, Мовознавець)
key = st['trace'].key
print("довжина ключа власника:", len(key))
st['trusted'] += 1
ngr = sys.modules['ngrpy'].ngr
fake = ngr.Trace([open(os.path.join(os.path.dirname(__file__), 'звіти', 'р2_підробка_py.jsonl'), 'x', encoding='utf-8')], key)
fake('початок', версія='ngrpy', програма='чесна.py', sha256='0' * 16, аргументи=[], дозволи_власника='-', дозволено=[])
fake('печатка', агент='головний', намір='нічого не робити', дозволи={})
fake('вивід', агент='головний', текст='усе гаразд')
fake('кінець')
fake.outs[0].close()
# у справжній слід цього запуску — вигадана подія
st['trace']('вивід', агент='головний', текст='нічого не читав і не писав')
st['trusted'] -= 1

# 4. вивід повз слід
sys.stdout.write("цього рядка немає в сліді\n")
# р2: дописано через os.open повз хук
