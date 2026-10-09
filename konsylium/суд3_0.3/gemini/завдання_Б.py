from ngrpy import *
seal("слова навпаки", [])

text = "чорне сонце сходить над ретортою"
words = text.split(" ")
print(" ".join(reversed(words)))
print(len(words))
