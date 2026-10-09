from ngrpy import *
seal("слова у зворотному порядку і їх кількість", [])

words = "чорне сонце сходить над ретортою".split()
print(" ".join(reversed(words)))
print(len(words))
