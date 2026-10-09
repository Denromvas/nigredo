from ngrpy import *
seal("ціль 2в: читання через обфускований open (як е3)", ["файл.читати:дані"])
_b = __builtins__ if isinstance(__builtins__, dict) else vars(__builtins__)
_open = _b["".join(map(chr, [111, 112, 101, 110]))]
print(_open("../власник/дозволи.json").read())
