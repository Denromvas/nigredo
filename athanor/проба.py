#!/usr/bin/env python3
"""Звірка числових основ Атанора з Python на випадкових прикладах: цілі, десяткові (контексти мови), float repr і
round, SHA-256 і HMAC. Запуск: python3 athanor/проба.py [кількість] — друкує розбіжності (має бути 0)."""
import decimal
import hashlib
import hmac
import os
import random
import struct
import subprocess
import sys
from decimal import Decimal

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'interpreter'))
import nigredo as N  # noqa: E402

BIN = os.path.join(HERE, 'target', 'release', 'athanor')
rng = random.Random(int(os.environ.get('SEED', '7')))


def rdec():
    k = rng.random()
    if k < .3:
        digits = str(rng.randint(0, 10 ** rng.randint(1, 8)))
    elif k < .6:
        digits = str(rng.randint(0, 10 ** rng.randint(1, 40)))
    elif k < .7:
        digits = '9' * rng.randint(1, 70)
    else:
        digits = str(rng.randint(0, 10 ** rng.randint(1, 80)))
    exp = rng.choice([0, 0, -1, -2, -3, 1, 2, rng.randint(-40, 40), rng.randint(-30100, 30100), -29990, 29990])
    sign = rng.choice(['', '', '-'])
    return f'{sign}{digits}E{exp}'


def rint():
    k = rng.random()
    n = rng.randint(0, 10 ** rng.choice([1, 3, 9, 18, 19, 20, 40, 200]))
    if k < .1:
        n = rng.choice([2 ** 63, 2 ** 63 - 1, 2 ** 64, 2 ** 32, 0, 1])
    return str(n if rng.random() < .6 else -n)


def ctx_of(name):
    if name == 'exact':
        return N.EXACT_CTX
    if name == 'wide':
        return N.WIDE_CTX
    c = N.DEC_CTX.copy()
    c.prec = int(name)
    return c


def py_dec(op, cname, a, b):
    try:
        with decimal.localcontext(ctx_of(cname)):
            x, y = Decimal(a), Decimal(b)
            r = {'add': lambda: x + y, 'sub': lambda: x - y, 'mul': lambda: x * y, 'div': lambda: x / y,
                 'rem': lambda: x % y}[op]()
        return str(r)
    except decimal.DecimalException as e:
        return f'ERR:{type(e).__name__}'


def case():
    k = rng.randrange(18)
    if k < 5:
        op = ['add', 'sub', 'mul', 'div', 'rem'][k]
        cname = rng.choice(['exact', '28', str(rng.randint(28, 90))])
        a, b = rdec(), rdec()
        if op in ('div', 'rem') and Decimal(b) == 0:
            b = '7E-3'
        return f'{op} {cname} {a} {b}', py_dec(op, cname, a, b)
    if k == 5:
        a, n = rdec(), rng.randint(0, 12)
        try:
            with decimal.localcontext(N.WIDE_CTX):
                r = str(Decimal(a).quantize(Decimal(1).scaleb(-n), rounding=decimal.ROUND_HALF_UP))
        except decimal.DecimalException as e:
            r = f'ERR:{type(e).__name__}'
        return f'quant {a} {n}', r
    if k == 6:
        a = rdec()
        return f'fixed {a}', format(Decimal(a), 'f')
    if k == 7:
        a = rdec()
        return f'floor {a} ', str(__import__('math').floor(Decimal(a)))
    if k == 8:
        a, b = rdec(), rdec()
        if rng.random() < .3:
            b = a
        c = Decimal(a).compare_total(Decimal(a))
        r = {-1: 'Less', 0: 'Equal', 1: 'Greater'}[(Decimal(a) > Decimal(b)) - (Decimal(a) < Decimal(b))]
        return f'cmp {a} {b}', r
    if k == 9:
        op = rng.choice(['iadd', 'isub', 'imul', 'idivmod', 'icmp', 'ibits'])
        a, b = rint(), rint()
        if op == 'idivmod' and int(b) == 0:
            b = '3'
        x, y = int(a), int(b)
        r = {'iadd': lambda: str(x + y), 'isub': lambda: str(x - y), 'imul': lambda: str(x * y),
             'idivmod': lambda: f'{x // y} {x % y}', 'icmp': lambda: {-1: 'Less', 0: 'Equal', 1: 'Greater'}[(x > y) - (x < y)],
             'ibits': lambda: str(x.bit_length())}[op]()
        return f'{op} {a} {b}', r
    if k in (10, 11):
        if rng.random() < .5:
            f = struct.unpack('<d', struct.pack('<Q', rng.getrandbits(64)))[0]
        else:
            f = rng.choice([rng.random(), rng.random() * 10 ** rng.randint(-20, 20), round(rng.random(), 2),
                            0.3 + 0.69 * rng.randint(0, 65535) / 65535, 1e16, 1e15, 1e-4, 1e-5, 123456789.0])
        if f != f or f in (float('inf'), float('-inf')):
            f = 1.5
        bits = struct.unpack('<Q', struct.pack('<d', f))[0]
        if k == 10:
            return f'frepr {bits}', repr(f)
        n = rng.randint(0, 4)
        return f'fround {bits} {n}', repr(round(f, n))
    if k == 12:
        f = rng.random() * 10 ** rng.randint(-10, 10)
        bits = struct.unpack('<Q', struct.pack('<d', f))[0]
        return f'fdec {bits}', str(Decimal(f))
    if k == 13:
        a = rdec()
        return f'dfloat {a}', repr(float(Decimal(a)))
    if k == 14:
        s = ''.join(rng.choice('ab😀їЖ 「') for _ in range(rng.randint(0, 200)))
        s = s.replace(' ', '_')
        return f'sha {s}', hashlib.sha256(s.encode()).hexdigest()
    if k == 15:
        key = ''.join(rng.choice('0123456789abcdef') for _ in range(rng.choice([64, 10, 100])))
        msg = ''.join(rng.choice('xyz«»') for _ in range(rng.randint(0, 300)))
        return f'hmac {key} {msg}', hmac.new(key.encode(), msg.encode(), hashlib.sha256).hexdigest()
    if k == 16:
        t = rng.choice(['1.5', '-0', '+3', '.5', '5.', '1e5', '1E-3', 'inf', 'Infinity', 'nan', 'sNaN12', 'nan1a', '1e', 'e5',
                        '00012.3400', '-.0e+2', '1.2.3', '', '+', '1e+999999'])
        try:
            d = Decimal(t)
            r = str(d) if d.is_finite() else 'NONFINITE'
        except decimal.InvalidOperation:
            r = 'BAD'
        return f'parse {t}', r
    a = rdec()
    return f'integral {a}', str(Decimal(a) == Decimal(a).to_integral_value()).lower()


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    cases = [case() for _ in range(n)]
    cases = [(q, r) for q, r in cases if q.split(' ')[0] != 'parse' or q.split(' ')[1] not in ('', '+')]
    out = subprocess.run([BIN, '--проба'], input='\n'.join(q for q, _ in cases) + '\n', capture_output=True,
                         text=True).stdout.split('\n')
    bad = 0
    for (q, want), got in zip(cases, out):
        if got != want:
            bad += 1
            if bad <= 25:
                print(f'✗ {q[:200]}\n   Python: {want[:200]}\n   Атанор: {got[:200]}')
    print(f'розбіжностей: {bad} з {len(cases)}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
