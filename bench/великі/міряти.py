"""Швидкість на великих даних: Nigredo проти Python — процесорний час (з запуском інтерпретатора), найкращий із 3.
Текст — 200 000 слів (детерміновано, зерно 7); арифметика — цикл на 200 000 кроків. Запуск: python3 bench/великі/міряти.py"""
import os
import random
import resource
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
NGR = os.path.join(HERE, '..', '..', 'interpreter', 'ngr.py')


def cpu(cmd, cwd, env):
    best, out = None, None
    for _ in range(3):
        r0 = resource.getrusage(resource.RUSAGE_CHILDREN)
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
        r1 = resource.getrusage(resource.RUSAGE_CHILDREN)
        t = (r1.ru_utime + r1.ru_stime) - (r0.ru_utime + r0.ru_stime)
        best, out = (t if best is None else min(best, t)), (p.stdout, p.stderr, p.returncode)
    return best, out


def main():
    with tempfile.TemporaryDirectory(prefix='ngr-великі-') as d:
        rnd = random.Random(7)
        words = ['сіль', 'сірка', 'ртуть', 'вода', 'олія', 'мед', 'вогонь', 'земля', 'повітря', 'ефір']
        os.mkdir(os.path.join(d, 'дані'))
        with open(os.path.join(d, 'дані', 'текст.txt'), 'w', encoding='utf-8') as f:
            for i in range(20000):
                f.write(' '.join(rnd.choice(words) for _ in range(10)) + '\n')
        home = os.path.join(d, 'власник')
        os.mkdir(home)
        with open(os.path.join(home, 'дозволи.json'), 'w', encoding='utf-8') as f:
            f.write('{"дозволено": ["файл.читати:%s"]}' % os.path.join(d, 'дані'))
        env = dict(os.environ, NIGREDO_HOME=home)
        print('| Задача | Nigredo, с | Python, с | Nigredo/Python | вивід однаковий |')
        print('|---|---|---|---|---|')
        for name in ('слова', 'арифм'):
            prog = os.path.join(d, name + '.ngr')
            with open(os.path.join(HERE, name + '.ngr'), encoding='utf-8') as src, open(prog, 'w', encoding='utf-8') as dst:
                dst.write(src.read())
            tn, (on, en, cn) = cpu([sys.executable, NGR, prog], d, env)
            tp, (op, ep, cp) = cpu([sys.executable, os.path.join(HERE, name + '.py')], d, env)
            same = cn == 0 and cp == 0 and on.split() == op.split()
            print(f'| {name} | {tn:.2f} | {tp:.2f} | {tn / tp:.1f}× | {"так" if same else "НІ: " + (en or ep)[:80]} |')


if __name__ == '__main__':
    main()
