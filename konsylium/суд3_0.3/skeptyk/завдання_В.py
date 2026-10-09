from ngrpy import *
seal("спитати оракула через субагента і лишити впевнені відповіді", ["оракул"])

qs = ["чи світ чорніє?", "чи золото вже близько?", "чи ртуть жива?", "чи сіль тверда?", "чи сірка горить?"]

def ask(q):
    with delegate("провидець", "спитати оракула", ["оракул"]):
        return tool("оракул", q)

conf_ = sift([ask(q) for q in qs], 0.6)
remember("впевнені", conf_)
check(recall("впевнені"), lambda x: len(x) == len(conf_))
print(len(conf_))
