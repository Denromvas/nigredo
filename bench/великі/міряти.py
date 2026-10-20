"""Швидкість на великих даних: Nigredo проти Python — процесорний час (з запуском інтерпретатора), найкращий із кількох
запусків (Атанор і Python — по черзі, щоб навантаження телефона діяло на обох однаково). Текст — 200 000 слів
(детерміновано, зерно 7); арифметика — цикл на 200 000 кроків; JSON — 25 000 замовлень, виручка за містами; функція —
той самий цикл через іменовану функцію (Σ; тіло — дерево цілих, Атанор рахує його швидкою доріжкою); умова — функція з
¿ у тілі; дроби — точні дроби (у Python — Decimal); рядки — σ, ＋, ρ у тілі; стан — цикл ↻ зі станом-списком (повільна
форма).
Запуск: python3 bench/великі/міряти.py"""
import os
import json
import random
import resource
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
NGR = os.path.join(HERE, '..', '..', 'interpreter', 'ngr.py')
ATHANOR = next((p for p in (os.path.join(HERE, '..', '..', 'athanor', 'target', t, 'release', 'athanor') for t in ('aarch64-unknown-linux-gnu', 'x86_64-unknown-linux-gnu', '', 'aarch64-unknown-linux-musl')) if os.path.exists(p)), '')   # нативний виконавець (якщо зібрано)


def cpu(cmd, cwd, env, runs=3):
    best, out = None, None
    for _ in range(runs):
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
        cities = ['Київ', 'Львів', 'Одеса', 'Харків', 'Дніпро', 'Вінниця', 'Полтава', 'Ужгород']
        rnd = random.Random(7)
        orders = [{'id': i, 'місто': rnd.choice(cities), 'кількість': rnd.randint(1, 100), 'ціна': rnd.randint(1, 1000)}
                  for i in range(25000)]
        with open(os.path.join(d, 'дані', 'замовлення.json'), 'w', encoding='utf-8') as f:
            json.dump(orders, f, ensure_ascii=False)
        home = os.path.join(d, 'власник')
        os.mkdir(home)
        with open(os.path.join(home, 'дозволи.json'), 'w', encoding='utf-8') as f:
            f.write('{"дозволено": ["файл.читати:%s"]}' % os.path.join(d, 'дані'))
        env = dict(os.environ, NIGREDO_HOME=home)
        nat = bool(ATHANOR)
        print('| Задача | Nigredo, с | Python, с | Nigredo/Python | вивід однаковий |' + (' Атанор, с | Атанор/Python | вивід Атанора той самий |' if nat else ''))
        print('|---|---|---|---|---|' + ('---|---|---|' if nat else ''))
        for name in ('слова', 'арифм', 'жсон', 'функція', 'умова', 'дроби', 'рядки', 'стан'):
            prog = os.path.join(d, name + '.ngr')
            with open(os.path.join(HERE, name + '.ngr'), encoding='utf-8') as src, open(prog, 'w', encoding='utf-8') as dst:
                dst.write(src.read())
            tn, (on, en, cn) = cpu([sys.executable, NGR, prog], d, env)
            tp, ta, outs = None, None, {}
            for _ in range(11 if nat else 3):     # по черзі: Python, Атанор
                t1, outs['p'] = cpu([sys.executable, os.path.join(HERE, name + '.py')], d, env, 1)
                tp = t1 if tp is None else min(tp, t1)
                if nat:
                    t2, outs['a'] = cpu([ATHANOR, prog], d, dict(env, ATHANOR_NO_FALLBACK='1'), 1)
                    ta = t2 if ta is None else min(ta, t2)
            op, ep, cp = outs['p']
            same = cn == 0 and cp == 0 and on.split() == op.split()
            row = f'| {name} | {tn:.2f} | {tp:.3f} | {tn / tp:.1f}× | {"так" if same else "НІ: " + (en or ep)[:80]} |'
            if nat:
                oa, ea, ca = outs['a']
                row += f' {ta:.3f} | {ta / tp:.2f}× | {"так" if ca == 0 and oa == on else "НІ: " + ea[:80]} |'
            print(row)


if __name__ == '__main__':
    main()
