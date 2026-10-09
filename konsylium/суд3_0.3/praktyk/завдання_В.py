from ngrpy import *
seal("спитати оракула через субагента і лишити впевнені відповіді", ["оракул"])

def ask(q):
    with delegate("провидець", "спитати оракула", ["оракул"]):
        return tool("оракул", q)

qs = ["чи світ чорніє?", "чи золото вже близько?", "чи ртуть жива?", "чи сіль тверда?", "чи сірка горить?"]
ok = sift([ask(q) for q in qs], 0.6)
remember("впевнені", ok)
check(recall("впевнені"), lambda x: len(x) == len(ok))
print(len(ok))
