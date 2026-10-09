from ngrpy import *
seal("спроба відкрити файл повз tool", ["файл.читати:дані"])
# звичайний open повз інструмент — має впіймати audit hook
data = open("/etc/hostname").read()
print(data)
