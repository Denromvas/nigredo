from ngrpy import *
seal("слова у зворотному порядку і їх кількість", [])

w = "чорне сонце сходить над ретортою".split()
print(" ".join(reversed(w)))
print(len(w))
