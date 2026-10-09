from ngrpy import *
seal("спитати оракула через субагента, лишити впевнені відповіді", ["оракул"])

def ask(q):
    with delegate("провидець", "спитати оракула", ["оракул"]):
        return tool("оракул", q)

qs = ["чи світ чорніє?", "чи золото вже близько?", "чи ртуть жива?", "чи сіль тверда?", "чи сірка горить?"]
confident = sift([ask(q) for q in qs], 0.6)
remember("впевнені", confident)
check(recall("впевнені"), lambda x: len(x) == len(confident))
print(len(confident))
