import pathlib
p = pathlib.Path('../../тимч/лічильник.txt')
n = int(p.read_text()) + 1 if p.exists() else 1
p.parent.mkdir(exist_ok=True)
p.write_text(str(n))
print(n)
