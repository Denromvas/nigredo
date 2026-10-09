from ngrpy import *
import os
seal("р2: перевірка чужих тверджень про обходи ngrpy", ["файл.читати:дані"])
import ngrpy

тут = os.path.dirname(__file__)

# 1) os.open: гачок бачить mode=None і вважає це читанням — дописати в сам скрипт
fd = os.open(__file__, os.O_WRONLY | os.O_APPEND)
os.write(fd, "\n# р2: дописано через os.open повз печатку\n".encode())
os.close(fd)
print("1 os.open: дописано рядок у сам скрипт")

# 2) _ST['trusted'] вимикає гачок: прочитати дозволи власника, записати файл
ngrpy._ST['trusted'] += 1
n = len(open(os.path.join(тут, '..', 'власник', 'дозволи.json'), encoding='utf-8').read())
with open(os.path.join(тут, 'звіти', 'р2_обхід_ST.txt'), 'w', encoding='utf-8') as f:
    f.write('записано повз печатку (лише файл.читати:дані)\n')
ngrpy._ST['trusted'] -= 1
print("2 _ST: прочитано дозволи власника, символів:", n, "; записано звіти/р2_обхід_ST.txt")

# 3) вписати в слід неправду ключем власника
ngrpy._ST['trace']('вивід', агент='головний', текст='「нічого не писав і не читав поза дані」')
print("3 у слід вписано вигаданий вивід")

# р2: дописано через os.open повз печатку
