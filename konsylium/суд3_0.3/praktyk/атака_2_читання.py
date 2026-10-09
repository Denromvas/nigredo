from ngrpy import *
seal("спроба читання поза дані", ["файл.читати:дані"])
print(value(tool("файл.читати", "/etc/hostname")))
