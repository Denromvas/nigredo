"""Копії атак суду 4 у корінь моєї теки (с4_*.ngr), щоб відносні шляхи «дані/», «звіти/» вели куди треба."""
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = os.path.join(HERE, 'атаки_суду4')
for n in sorted(os.listdir(src)):
    if n.endswith('.ngr'):
        with open(os.path.join(src, n), encoding='utf-8') as f:
            t = f.read()
        with open(os.path.join(HERE, 'с4_' + n), 'w', encoding='utf-8') as f:
            f.write(t)
        print('с4_' + n)
