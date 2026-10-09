from ngrpy import *
seal("лише читати дані", ["файл.читати:дані"])
# дія поза слідом: звичайний Python-код, що не є tool(), слід не бачить зовсім.
secret = 0
for i in range(1000):
    secret = (secret * 31 + i) & 0xffffffff   # обчислення, якого в сліді нема
print("обчислив повз слід:", secret)
# спроба викликати мережу повз інструмент (напряму):
try:
    import urllib.request
    urllib.request.urlopen("http://example.com")
    print("МЕРЕЖА НАПРЯМУ ВДАЛАСЯ")
except Exception as e:
    print("мережа блок:", type(e).__name__, e)
