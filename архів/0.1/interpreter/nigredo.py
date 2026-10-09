#!/usr/bin/env python3
"""Nigredo 0.1 — еталонний інтерпретатор.

Специфікація: spec/SPEC.md. Без залежностей, Python 3.13.
Використання: python3 nigredo.py [--слід] [--розбір] [--зерно N] (ФАЙЛ.ngr | -e КОД)
"""
import datetime
import hashlib
import math
import random
import sys
import threading
import unicodedata

MAX_CALL_DEPTH = 10000
MAX_DELEGATION_DEPTH = 16

# ------------------------------------------------------------------ гліфи

GLOSS = {
    # стек
    '⧉': 'дублювати', '⏚': 'викинути', '⇄': 'обміняти', '⇈': 'підняти другий',
    '⟲': 'обернути трійку',
    # числа
    '⊕': 'додати', '⊖': 'відняти', '⊗': 'помножити', '⨸': 'поділити', '⦼': 'остача',
    '⌊': 'округлити вниз', '⁻': 'змінити знак',
    # порівняння й логіка
    '≡': 'рівні?', '≢': 'не рівні?', '≺': 'менше?', '≻': 'більше?',
    '≼': 'не більше?', '≽': 'не менше?', '⋏': 'і', '⋎': 'або', '⌐': 'не',
    # рядки й списки
    '♯': 'довжина', '⌷': 'елемент за індексом', '⧺': 'зʼєднати', '⊹': 'додати в кінець',
    '⇋': 'обернути', '⋯': 'ряд 0…n−1', '⫽': 'розрізати', '⫻': 'склеїти',
    '⍕': 'у рядок', '⍎': 'у число',
    # керування
    '⍟': 'виконати блок', '⋔': 'якщо-то-інакше', '⟳': 'поки-робити',
    '⧖': 'повторити n разів', '⁘': 'для кожного', '⇶': 'перетворити кожен', '⋐': 'відсіяти',
    '∮': 'згорнути', '☠': 'зупинитися з помилкою', '⛉': 'спробувати, а при помилці',
    # вивід
    '⎙': 'друкувати', '⌸': 'показати стек',
    # константи
    '☉': 'істина', '☽': 'хиба', '∅': 'ніщо',
    # довіра
    '☿': 'призначити впевненість', '⚖': 'впевненість?', '⚗': 'пропустити, якщо впевненість ≥ порогу',
    # агент
    '🜂': 'НАМІР', '🜔': 'ІНСТРУМЕНТ', '🜄': 'ЗАПАМʼЯТАТИ', '🜃': 'ПРИГАДАТИ',
    '🜁': 'ДЕЛЕГУВАТИ', '🜍': 'ПЕРЕВІРИТИ',
}
BINDERS = {'⊸': 'назвати', '⊷': 'назвати локально', '⊶': 'назвати словом'}
OPENERS = {'⌜': '⌟', '⟬': '⟭'}
CLOSERS = {'⌟', '⟭'}
BRACKET_GLOSS = {'⌜': 'блок {', '⌟': '}', '⟬': 'список [', '⟭': ']'}
IGNORED = {'︎', '️'}
COMMENT, STR_OPEN, STR_CLOSE, NEWLINE_GLYPH = '⸸', '⟪', '⟫', '↵'
MINUS, POINTS = '⁻', ('·', '.')


class NgrError(Exception):
    def __init__(self, msg, pos=None):
        super().__init__(msg)
        self.msg, self.pos = msg, pos

    def __str__(self):
        return f'✗ {self.pos[0]}:{self.pos[1]} {self.msg}' if self.pos else f'✗ {self.msg}'


# ------------------------------------------------------------------ лексика

def is_rune(ch):
    o = ord(ch)
    return 0x16A0 <= o <= 0x16EA or 0x16EE <= o <= 0x16F8


def digit(ch):
    return unicodedata.decimal(ch, None)


class Tok:
    __slots__ = ('kind', 'val', 'line', 'col', 'start', 'end')

    def __init__(self, kind, val, line, col, start, end):
        self.kind, self.val, self.line, self.col, self.start, self.end = kind, val, line, col, start, end


def lex(src):
    toks, i, n = [], 0, len(src)
    line, line_start = 1, 0

    def here(at):
        return (line, at - line_start + 1)

    while i < n:
        ch = src[i]
        if ch == '\n':
            i += 1
            line, line_start = line + 1, i
            continue
        if ch.isspace() or ch in IGNORED:
            i += 1
            continue
        start = i
        if ch == COMMENT:
            while i < n and src[i] != '\n':
                i += 1
            continue
        if ch == STR_OPEN:
            depth, i, buf = 1, i + 1, []
            sline, scol = here(start)
            while i < n:
                c = src[i]
                if c == STR_OPEN:
                    depth += 1
                elif c == STR_CLOSE:
                    depth -= 1
                    if depth == 0:
                        break
                elif c == '\n':
                    line, line_start = line + 1, i + 1
                buf.append('\n' if c == NEWLINE_GLYPH else c)
                i += 1
            if i >= n:
                raise NgrError('незакритий рядок ⟪', (sline, scol))
            i += 1
            toks.append(Tok('str', ''.join(buf), sline, scol, start, i))
            continue
        if digit(ch) is not None or (ch == MINUS and i + 1 < n and digit(src[i + 1]) is not None):
            text = []
            if ch == MINUS:
                text.append('-')
                i += 1
            while i < n and digit(src[i]) is not None:
                text.append(str(digit(src[i])))
                i += 1
            is_float = False
            if i + 1 < n and src[i] in POINTS and digit(src[i + 1]) is not None:
                is_float = True
                text.append('.')
                i += 1
                while i < n and digit(src[i]) is not None:
                    text.append(str(digit(src[i])))
                    i += 1
            s = ''.join(text)
            toks.append(Tok('num', float(s) if is_float else int(s), *here(start), start, i))
            continue
        if is_rune(ch):
            while i < n and is_rune(src[i]):
                i += 1
            toks.append(Tok('name', src[start:i], *here(start), start, i))
            continue
        if ch.isascii() and ch.isalpha():
            while i < n and src[i].isascii() and src[i].isalnum():
                i += 1
            raise NgrError(f'людське слово поза рядком: «{src[start:i]}»', here(start))
        i += 1
        if ch in BINDERS:
            toks.append(Tok('bind', ch, *here(start), start, i))
        elif ch in OPENERS:
            toks.append(Tok('open', ch, *here(start), start, i))
        elif ch in CLOSERS:
            toks.append(Tok('close', ch, *here(start), start, i))
        elif ch in GLOSS:
            toks.append(Tok('op', ch, *here(start), start, i))
        else:
            raise NgrError(f'невідомий гліф «{ch}» (U+{ord(ch):04X})', here(start))
    return toks


# ------------------------------------------------------------------ розбір

class Node:
    __slots__ = ('kind', 'val', 'body', 'pos', 'src')

    def __init__(self, kind, val, body, pos, src=None):
        self.kind, self.val, self.body, self.pos, self.src = kind, val, body, pos, src


def parse(toks, src):
    i = 0

    def seq(opener):
        nonlocal i
        out = []
        while i < len(toks):
            t = toks[i]
            pos = (t.line, t.col)
            if t.kind == 'close':
                if opener is None or t.val != OPENERS[opener.val]:
                    raise NgrError(f'зайве «{t.val}»', pos)
                return out, t
            i += 1
            if t.kind == 'open':
                body, end = seq(t)
                i += 1
                kind = 'block' if t.val == '⌜' else 'list'
                out.append(Node(kind, None, body, pos, src[t.start:end.end]))
            elif t.kind == 'bind':
                if i >= len(toks) or toks[i].kind != 'name':
                    raise NgrError(f'після «{t.val}» має йти імʼя з рун', pos)
                out.append(Node('bind', t.val, toks[i].val, pos))
                i += 1
            else:
                out.append(Node(t.kind, t.val, None, pos))
        if opener is not None:
            raise NgrError(f'незакрите «{opener.val}» — бракує «{OPENERS[opener.val]}»',
                           (opener.line, opener.col))
        return out, None

    return seq(None)[0]


# ------------------------------------------------------------------ значення

class V:
    """Значення з впевненістю c ∈ [0, 1]."""
    __slots__ = ('v', 'c')

    def __init__(self, v, c=1.0):
        self.v, self.c = v, c


class Block:
    __slots__ = ('nodes', 'env', 'src')

    def __init__(self, nodes, env, src):
        self.nodes, self.env, self.src = nodes, env, src


class Env:
    __slots__ = ('vars', 'parent', 'barrier')

    def __init__(self, parent=None, barrier=False):
        self.vars, self.parent, self.barrier = {}, parent, barrier

    def lookup(self, name):
        e = self
        while e is not None:
            if name in e.vars:
                return e.vars[name]
            e = e.parent
        return None

    def owner(self, name):
        """Найближчий кадр із цим імʼям, не далі межі делегування."""
        e = self
        while e is not None:
            if name in e.vars:
                return e
            if e.barrier:
                return None
            e = e.parent
        return None


class Agent:
    __slots__ = ('name', 'stack', 'mem', 'depth')

    def __init__(self, name, depth):
        self.name, self.stack, self.mem, self.depth = name, [], {}, depth


def is_num(x):
    return type(x) in (int, float)


def truthy(x):
    return not (x is False or x is None)


def type_name(x):
    if x is None:
        return 'ніщо'
    if x is True or x is False:
        return 'логічне'
    if is_num(x):
        return 'число'
    if isinstance(x, str):
        return 'рядок'
    if isinstance(x, list):
        return 'список'
    if isinstance(x, Block):
        return 'блок'
    return '?'


def fmt(x, inner=False):
    if x is None:
        return '∅'
    if x is True:
        return '☉'
    if x is False:
        return '☽'
    if type(x) is int:
        return str(x)
    if type(x) is float:
        return repr(round(x, 10))
    if isinstance(x, str):
        return f'⟪{x}⟫' if inner else x
    if isinstance(x, list):
        return '⟬' + ' '.join(fmt(e.v, True) for e in x) + '⟭'
    if isinstance(x, Block):
        return x.src
    return '?'


def show(val):
    s = fmt(val.v, True).replace('\n', '↵')
    return s if val.c >= 1 else f'{s}~{round(val.c, 3)}'


def plain(x):
    """Форма для структурного порівняння (логічні ≠ числа)."""
    if x is True or x is False:
        return ('логічне', x)
    if isinstance(x, list):
        return ('список', tuple(plain(e.v) for e in x))
    if isinstance(x, Block):
        return ('блок', id(x))
    return x


def parse_number(s):
    out = []
    for ch in s.strip():
        if ch in POINTS:
            out.append('.')
        elif ch in (MINUS, '-', '−'):
            out.append('-')
        else:
            d = digit(ch)
            if d is None:
                return None
            out.append(str(d))
    t = ''.join(out)
    for conv in (int, float):
        try:
            return conv(t)
        except ValueError:
            pass
    return None


# ------------------------------------------------------------------ інструменти

def tool_oracle(it, arg):
    q = arg.v if isinstance(arg.v, str) else fmt(arg.v)
    h = hashlib.sha256(q.encode('utf-8')).digest()
    return h[0] % 2 == 0, round(0.5 + h[1] / 255 * 0.49, 2)


def tool_words(it, arg):
    return [V(w) for w in it.want(arg, str, 'слова').split()], 1.0


def tool_upper(it, arg):
    return it.want(arg, str, 'верхній').upper(), 1.0


def tool_lot(it, arg):
    n = arg.v
    if type(n) is not int or n < 1:
        raise NgrError('жереб: потрібне ціле число ≥ 1')
    return it.rng.randint(1, n), 1.0


def tool_time(it, arg):
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), 1.0


TOOLS = {
    'луна': lambda it, arg: (arg.v, 1.0),
    'слова': tool_words,
    'верхній': tool_upper,
    'жереб': tool_lot,
    'час': tool_time,
    'оракул': tool_oracle,
}


# ------------------------------------------------------------------ виконання

OPS = {}


def op(glyphs):
    def reg(f):
        for g in glyphs:
            OPS[g] = f
        return f
    return reg


class Interp:
    def __init__(self, trace=False, seed=0, out=None, err=None):
        self.trace = trace
        self.rng = random.Random(seed)
        self.agent = Agent('корінь', 0)
        self.calls = 0
        self.out = out or sys.stdout
        self.err = err or sys.stderr
        self.globals = Env()

    # --- допоміжне

    def log(self, msg):
        if self.trace:
            print('  ' * self.agent.depth + '⟢ ' + msg, file=self.err)

    def take(self, g, n):
        st = self.agent.stack
        if len(st) < n:
            raise NgrError(f'{g}: на стеку замало значень (потрібно {n}, є {len(st)})')
        items = st[-n:]
        del st[-n:]
        return items

    def push(self, v, c=1.0):
        self.agent.stack.append(V(v, c))

    def want(self, val, typ, g):
        x = val.v
        ok = is_num(x) if typ == 'num' else (isinstance(x, typ) and not (typ is int and type(x) is bool))
        if not ok:
            names = {'num': 'число', str: 'рядок', list: 'список', Block: 'блок', int: 'ціле число'}
            raise NgrError(f'{g}: очікувалося {names[typ]}, а не {type_name(x)} {show(val)}')
        return x

    def call(self, blk, barrier=False):
        self.calls += 1
        if self.calls > MAX_CALL_DEPTH:
            raise NgrError(f'надто глибоке занурення (понад {MAX_CALL_DEPTH} викликів)')
        try:
            self.run(blk.nodes, Env(blk.env, barrier))
        finally:
            self.calls -= 1

    def apply(self, g, blk, args):
        """Виконати блок над аргументами й забрати рівно один результат."""
        st = self.agent.stack
        d = len(st)
        st.extend(args)
        self.call(blk)
        if len(st) < d + 1:
            raise NgrError(f'{g}: блок не залишив результату')
        r = st[-1]
        del st[d:]
        return r

    # --- головний цикл

    def run(self, nodes, env):
        for n in nodes:
            try:
                k = n.kind
                if k == 'op':
                    OPS[n.val](self, n.val)
                elif k == 'num' or k == 'str':
                    self.agent.stack.append(V(n.val))
                elif k == 'name':
                    entry = env.lookup(n.val)
                    if entry is None:
                        raise NgrError(f'невідоме імʼя {n.val}')
                    is_word, val = entry
                    if is_word:
                        self.call(val.v)
                    else:
                        self.agent.stack.append(val)
                elif k == 'bind':
                    val, = self.take(n.val, 1)
                    is_word = n.val == '⊶'
                    if is_word and not isinstance(val.v, Block):
                        raise NgrError(f'⊶: словом можна назвати лише блок, а не {type_name(val.v)}')
                    target = env if n.val == '⊷' else (env.owner(n.body) or env)
                    target.vars[n.body] = (is_word, val)
                elif k == 'block':
                    self.agent.stack.append(V(Block(n.body, env, n.src)))
                elif k == 'list':
                    st = self.agent.stack
                    d = len(st)
                    self.run(n.body, env)
                    if len(st) < d:
                        raise NgrError('⟭: вміст списку забрав зі стеку більше, ніж поклав')
                    items = st[d:]
                    del st[d:]
                    st.append(V(items))
            except NgrError as e:
                if e.pos is None:
                    e.pos = n.pos
                raise


# --- константи й стек

@op('☉☽∅')
def _const(it, g):
    it.push({'☉': True, '☽': False, '∅': None}[g])


@op('⧉')
def _dup(it, g):
    a, = it.take(g, 1)
    it.agent.stack += [a, a]


@op('⏚')
def _drop(it, g):
    it.take(g, 1)


@op('⇄')
def _swap(it, g):
    a, b = it.take(g, 2)
    it.agent.stack += [b, a]


@op('⇈')
def _over(it, g):
    a, b = it.take(g, 2)
    it.agent.stack += [a, b, a]


@op('⟲')
def _rot(it, g):
    a, b, c = it.take(g, 3)
    it.agent.stack += [b, c, a]


# --- числа

def _div(a, b):
    if b == 0:
        raise NgrError('⨸: ділення на нуль')
    if type(a) is int and type(b) is int and a % b == 0:
        return a // b
    return a / b


def _mod(a, b):
    if b == 0:
        raise NgrError('⦼: остача від ділення на нуль')
    return a % b


ARITH = {
    '⊕': lambda a, b: a + b,
    '⊖': lambda a, b: a - b,
    '⊗': lambda a, b: a * b,
    '⨸': _div,
    '⦼': _mod,
}


@op(ARITH)
def _arith(it, g):
    a, b = it.take(g, 2)
    it.push(ARITH[g](it.want(a, 'num', g), it.want(b, 'num', g)), a.c * b.c)


@op('⌊')
def _floor(it, g):
    a, = it.take(g, 1)
    it.push(math.floor(it.want(a, 'num', g)), a.c)


@op('⁻')
def _neg(it, g):
    a, = it.take(g, 1)
    it.push(-it.want(a, 'num', g), a.c)


# --- порівняння й логіка

ORDER = {
    '≺': lambda a, b: a < b, '≻': lambda a, b: a > b,
    '≼': lambda a, b: a <= b, '≽': lambda a, b: a >= b,
}


@op('≡≢')
def _eq(it, g):
    a, b = it.take(g, 2)
    same = plain(a.v) == plain(b.v)
    it.push(same if g == '≡' else not same, a.c * b.c)


@op(ORDER)
def _order(it, g):
    a, b = it.take(g, 2)
    if not ((is_num(a.v) and is_num(b.v)) or (isinstance(a.v, str) and isinstance(b.v, str))):
        raise NgrError(f'{g}: порівнювати можна два числа або два рядки, а не {type_name(a.v)} і {type_name(b.v)}')
    it.push(ORDER[g](a.v, b.v), a.c * b.c)


@op('⋏⋎')
def _logic(it, g):
    a, b = it.take(g, 2)
    r = (truthy(a.v) and truthy(b.v)) if g == '⋏' else (truthy(a.v) or truthy(b.v))
    it.push(r, a.c * b.c)


@op('⌐')
def _not(it, g):
    a, = it.take(g, 1)
    it.push(not truthy(a.v), a.c)


# --- рядки й списки

def _seq(it, val, g):
    if not isinstance(val.v, (str, list)):
        raise NgrError(f'{g}: очікувався рядок або список, а не {type_name(val.v)}')
    return val.v


@op('♯')
def _len(it, g):
    a, = it.take(g, 1)
    it.push(len(_seq(it, a, g)), a.c)


@op('⌷')
def _index(it, g):
    s, i = it.take(g, 2)
    seq, idx = _seq(it, s, g), it.want(i, int, g)
    if not -len(seq) <= idx < len(seq):
        raise NgrError(f'⌷: індекс {idx} поза межами (довжина {len(seq)})')
    item = seq[idx]
    if isinstance(seq, str):
        it.push(item, s.c * i.c)
    else:
        it.push(item.v, item.c * s.c * i.c)


@op('⧺')
def _concat(it, g):
    a, b = it.take(g, 2)
    x, y = _seq(it, a, g), _seq(it, b, g)
    if type(x) is not type(y):
        raise NgrError(f'⧺: зʼєднувати можна рядок із рядком або список зі списком')
    it.push(x + y, a.c * b.c)


@op('⊹')
def _append(it, g):
    lst, x = it.take(g, 2)
    it.push(it.want(lst, list, g) + [x], lst.c)


@op('⇋')
def _reverse(it, g):
    a, = it.take(g, 1)
    it.push(_seq(it, a, g)[::-1], a.c)


@op('⋯')
def _range(it, g):
    a, = it.take(g, 1)
    n = it.want(a, int, g)
    it.push([V(k) for k in range(n)], a.c)


@op('⫽')
def _split(it, g):
    s, sep = it.take(g, 2)
    text, by = it.want(s, str, g), it.want(sep, str, g)
    parts = list(text) if by == '' else text.split(by)
    it.push([V(p) for p in parts], s.c * sep.c)


@op('⫻')
def _join(it, g):
    lst, sep = it.take(g, 2)
    items, by = it.want(lst, list, g), it.want(sep, str, g)
    c = lst.c * sep.c
    for e in items:
        c *= e.c
    it.push(by.join(fmt(e.v) for e in items), c)


@op('⍕')
def _tostr(it, g):
    a, = it.take(g, 1)
    it.push(fmt(a.v), a.c)


@op('⍎')
def _tonum(it, g):
    a, = it.take(g, 1)
    n = parse_number(it.want(a, str, g))
    if n is None:
        raise NgrError(f'⍎: «{a.v}» — не число')
    it.push(n, a.c)


# --- керування

@op('⍟')
def _exec(it, g):
    b, = it.take(g, 1)
    it.call(it.want(b, Block, g))


@op('⋔')
def _if(it, g):
    c, t, e = it.take(g, 3)
    t, e = it.want(t, Block, g), it.want(e, Block, g)
    it.call(t if truthy(c.v) else e)


@op('⟳')
def _while(it, g):
    c, body = it.take(g, 2)
    c, body = it.want(c, Block, g), it.want(body, Block, g)
    while True:
        it.call(c)
        r, = it.take(g, 1)
        if not truthy(r.v):
            break
        it.call(body)


@op('⧖')
def _times(it, g):
    n, body = it.take(g, 2)
    n, body = it.want(n, int, g), it.want(body, Block, g)
    for _ in range(n):
        it.call(body)


@op('⁘')
def _each(it, g):
    lst, f = it.take(g, 2)
    items, f = it.want(lst, list, g), it.want(f, Block, g)
    for e in items:
        it.agent.stack.append(V(e.v, e.c * lst.c))
        it.call(f)


@op('⇶')
def _map(it, g):
    lst, f = it.take(g, 2)
    items, f = it.want(lst, list, g), it.want(f, Block, g)
    it.push([it.apply(g, f, [V(e.v, e.c * lst.c)]) for e in items])


@op('⋐')
def _filter(it, g):
    lst, p = it.take(g, 2)
    items, p = it.want(lst, list, g), it.want(p, Block, g)
    it.push([e for e in items if truthy(it.apply(g, p, [V(e.v, e.c * lst.c)]).v)], lst.c)


@op('∮')
def _fold(it, g):
    lst, acc, f = it.take(g, 3)
    items, f = it.want(lst, list, g), it.want(f, Block, g)
    for e in items:
        acc = it.apply(g, f, [acc, V(e.v, e.c * lst.c)])
    it.agent.stack.append(acc)


@op('☠')
def _die(it, g):
    m, = it.take(g, 1)
    raise NgrError(fmt(m.v))


@op('⛉')
def _shield(it, g):
    body, handler = it.take(g, 2)
    body, handler = it.want(body, Block, g), it.want(handler, Block, g)
    agent, calls, d = it.agent, it.calls, len(it.agent.stack)
    try:
        it.call(body)
    except NgrError as e:
        it.agent, it.calls = agent, calls
        del agent.stack[d:]
        it.log(f'щит перехопив помилку: {e.msg}')
        it.push(e.msg)
        it.call(handler)


# --- вивід

@op('⎙')
def _print(it, g):
    a, = it.take(g, 1)
    print(fmt(a.v), file=it.out, flush=True)


@op('⌸')
def _dump(it, g):
    print('стек: ' + ' '.join(show(v) for v in it.agent.stack), file=it.err)


# --- довіра

@op('☿')
def _confide(it, g):
    x, c = it.take(g, 2)
    conf = min(1.0, max(0.0, float(it.want(c, 'num', g))))
    it.log(f'впевненість {show(V(x.v))} := {round(conf, 3)}')
    it.push(x.v, conf)


@op('⚖')
def _weigh(it, g):
    x, = it.take(g, 1)
    it.push(x.c)


@op('⚗')
def _distill(it, g):
    x, t = it.take(g, 2)
    threshold = it.want(t, 'num', g)
    if x.c >= threshold:
        it.log(f'поріг {threshold}: {show(x)} — пропущено')
        it.agent.stack.append(x)
    else:
        it.log(f'поріг {threshold}: {show(x)} — відкинуто')
        it.push(None)


# --- агент

@op('🜂')
def _intent(it, g):
    s, = it.take(g, 1)
    it.log(f'намір: {fmt(s.v)}')


@op('🜔')
def _tool(it, g):
    arg, name = it.take(g, 2)
    tool_name = it.want(name, str, g)
    tool = TOOLS.get(tool_name)
    if tool is None:
        raise NgrError(f'🜔: невідомий інструмент «{tool_name}» (є: {", ".join(TOOLS)})')
    v, c = tool(it, arg)
    res = V(v, c * arg.c)
    it.log(f'інструмент «{tool_name}»: {show(arg)} → {show(res)}')
    it.agent.stack.append(res)


@op('🜄')
def _remember(it, g):
    key, x = it.take(g, 2)
    k = it.want(key, str, g)
    it.agent.mem[k] = x
    it.log(f'памʼять «{k}» ← {show(x)}')


@op('🜃')
def _recall(it, g):
    key, = it.take(g, 1)
    k = it.want(key, str, g)
    x = it.agent.mem.get(k, V(None))
    it.log(f'памʼять «{k}» → {show(x)}')
    it.agent.stack.append(x)


@op('🜁')
def _delegate(it, g):
    b, name = it.take(g, 2)
    blk, who = it.want(b, Block, g), it.want(name, str, g)
    parent = it.agent
    if parent.depth + 1 > MAX_DELEGATION_DEPTH:
        raise NgrError(f'🜁: надто глибоке делегування (понад {MAX_DELEGATION_DEPTH})')
    it.log(f'делегую субагенту «{who}»')
    it.agent = Agent(who, parent.depth + 1)
    try:
        it.call(blk, barrier=True)
        res = it.agent.stack[-1] if it.agent.stack else V(None)
    finally:
        it.agent = parent
    it.log(f'«{who}» повернув {show(res)}')
    parent.stack.append(res)


@op('🜍')
def _verify(it, g):
    x, p = it.take(g, 2)
    r = it.apply(g, it.want(p, Block, g), [x])
    if not truthy(r.v):
        it.log(f'перевірка {show(x)} — НЕ пройдена')
        raise NgrError(f'🜍: перевірку не пройдено для {show(x)}')
    it.log(f'перевірка {show(x)} — пройдена')
    it.agent.stack.append(x)


# ------------------------------------------------------------------ розбір для людини

def explain_lines(src):
    """[(номер, текст рядка, [переклади токенів] або None)] — для людини й для сайту."""
    toks = lex(src)
    by_line = {}
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.kind == 'bind' and i + 1 < len(toks) and toks[i + 1].kind == 'name':
            g = f'{BINDERS[t.val]} {toks[i + 1].val}'
            i += 1
        elif t.kind == 'op':
            g = GLOSS[t.val]
        elif t.kind in ('open', 'close'):
            g = BRACKET_GLOSS[t.val]
        elif t.kind == 'str':
            g = '«' + t.val.replace('\n', '↵') + '»'
        elif t.kind == 'num':
            g = fmt(t.val)
        else:
            g = t.val
        by_line.setdefault(t.line, []).append(g)
        i += 1
    return [(no, text, by_line.get(no)) for no, text in enumerate(src.split('\n'), 1) if text.strip()]


def explain(src, out):
    rows = explain_lines(src)
    width = len(str(rows[-1][0])) if rows else 1
    for no, text, gloss in rows:
        print(f'{no:>{width}}│ {text}', file=out)
        if gloss:
            print(f'{"":>{width}}│   ' + ' · '.join(gloss), file=out)


# ------------------------------------------------------------------ командний рядок

USAGE = """Nigredo 0.1
  nigredo.py ФАЙЛ.ngr | -e КОД
    --слід    | --trace     журнал агентних дій у stderr
    --розбір  | --explain   переклад програми українською, без виконання
    --зерно N | --seed N    зерно для інструмента «жереб» (типово 0)"""


def main(argv):
    trace = explain_only = False
    seed, src, path = 0, None, None
    args = list(argv)
    while args:
        a = args.pop(0)
        if a in ('--слід', '--trace'):
            trace = True
        elif a in ('--розбір', '--explain'):
            explain_only = True
        elif a in ('--зерно', '--seed') and args:
            seed = int(args.pop(0))
        elif a == '-e' and args:
            src, path = args.pop(0), '<-e>'
        elif a in ('-h', '--help', '--допомога'):
            print(USAGE)
            return 0
        elif path is None:
            path = a
        else:
            print(USAGE, file=sys.stderr)
            return 2
    if path is None:
        print(USAGE, file=sys.stderr)
        return 2
    if src is None:
        try:
            with open(path, encoding='utf-8') as f:
                src = f.read()
        except OSError as e:
            print(f'✗ не можу прочитати {path}: {e.strerror}', file=sys.stderr)
            return 2
    try:
        if explain_only:
            explain(src, sys.stdout)
            return 0
        it = Interp(trace=trace, seed=seed)
        it.run(parse(lex(src), src), it.globals)
        return 0
    except NgrError as e:
        sys.stdout.flush()
        print(str(e), file=sys.stderr)
        return 1


def entry():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8')
    sys.setrecursionlimit(60000)
    threading.stack_size(256 * 1024 * 1024)
    result = [1]
    t = threading.Thread(target=lambda: result.__setitem__(0, main(sys.argv[1:])))
    t.start()
    t.join()
    sys.exit(result[0])


if __name__ == '__main__':
    entry()
