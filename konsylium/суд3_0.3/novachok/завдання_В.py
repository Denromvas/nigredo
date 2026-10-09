from ngrpy import *
seal("спитати оракула через субагента і лишити впевнені відповіді", ["оракул"])

questions = ["чи світ чорніє?", "чи золото вже близько?", "чи ртуть жива?",
             "чи сіль тверда?", "чи сірка горить?"]

def ask(q):
    with delegate("провидець", "спитати оракула", ["оракул"]):
        return tool("оракул", q)

answers = [ask(q) for q in questions]
confident = sift(answers, 0.6)
remember("впевнені", confident)
check(recall("впевнені"), lambda x: len(x) == len(confident))
print(len(confident))
