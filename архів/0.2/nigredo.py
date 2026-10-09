#!/usr/bin/env python3
"""Nigredo 0.2 — еталонний інтерпретатор.

Специфікація: spec/SPEC.md. Без залежностей, Python ≥ 3.10.
Таблиці GLYPHS і TOOLS нижче — єдине джерело правди: з них генеруються
памʼятка (`--памʼятка`) і переклад (`--розбір`).
"""
import fnmatch
import hashlib
import json
import os
import random
import subprocess
import sys
import threading
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone

VERSION = '0.2'
MAX_DEPTH = 2000
DEFAULT_STEPS = 10_000_000
ALLOWLIST = os.path.expanduser('~/.nigredo/дозволи.json')
DEFAULT_ALLOWED = ['оракул', 'жереб', 'час']
AGENTS_REGISTRY = os.environ.get('NIGREDO_AGENTS', '/root/ai-agents/launcher/agents.json')


class NgrError(Exception):
    """Помилка програми: її можна перехопити ☂."""

    def __init__(self, msg, pos=None):
        super().__init__(msg)
        self.msg, self.pos = msg, pos

    def __str__(self):
        return f'✗ {self.pos[0]}:{self.pos[1]} {self.msg}' if self.pos else f'✗ {self.msg}'


class StaticError(NgrError):
    """Помилка до запуску: розбір, імена, печатка."""


class Refused(NgrError):
    """Печатка просить більше, ніж дозволив власник."""


class Fatal(NgrError):
    """Межі виконання (кроки, глибина): ☂ їх не перехоплює."""


# ------------------------------------------------------------------ гліфи
# гліф: (арність, сигнатура, що робить, шаблон розбору, група)
# Шаблон: {0} {1} … — перекладені аргументи. Арність None — особлива форма.

GLYPHS = {
    # звʼязування й функції
    '←': (None, '← імʼя вираз', 'назвати значення (назавжди: перепризначити не можна)', '{name} ← {0}', 'імена'),
    'λ': (None, 'λ x тіло', 'функція одного аргументу', 'функція ({p}) ↦ {0}', 'імена'),
    'Λ': (None, 'Λ a b тіло', 'функція двох аргументів', 'функція ({p}) ↦ {0}', 'імена'),
    '►': (2, '► f x', 'викликати функцію-значення з одним аргументом', '{0}({1})', 'імена'),
    '▶': (3, '▶ f a b', 'викликати функцію-значення з двома аргументами', '{0}({1}, {2})', 'імена'),
    # числа
    '＋': (2, '＋ a b', 'додати числа; зʼєднати рядки або списки', '({0} + {1})', 'числа'),
    '－': (2, '－ a b', 'відняти', '({0} − {1})', 'числа'),
    '×': (2, '× a b', 'помножити', '({0} × {1})', 'числа'),
    '÷': (2, '÷ a b', 'поділити (націло — ціле, інакше дріб)', '({0} ÷ {1})', 'числа'),
    '‰': (2, '‰ a b', 'остача від ділення a на b', '({0} остача {1})', 'числа'),
    '⌊': (1, '⌊ a', 'округлити вниз', 'вниз({0})', 'числа'),
    # порівняння й логіка
    '＝': (2, '＝ a b', 'рівні? (глибоко, для будь-яких значень)', '({0} = {1})', 'порівняння'),
    '≠': (2, '≠ a b', 'не рівні?', '({0} ≠ {1})', 'порівняння'),
    '‹': (2, '‹ a b', 'a менше за b?', '({0} < {1})', 'порівняння'),
    '›': (2, '› a b', 'a більше за b?', '({0} > {1})', 'порівняння'),
    '≤': (2, '≤ a b', 'a не більше b?', '({0} ≤ {1})', 'порівняння'),
    '≥': (2, '≥ a b', 'a не менше b?', '({0} ≥ {1})', 'порівняння'),
    '∧': (2, '∧ p q', 'і (обидва — ● або ○)', '({0} і {1})', 'порівняння'),
    '∨': (2, '∨ p q', 'або', '({0} або {1})', 'порівняння'),
    '¬': (1, '¬ p', 'не', 'не {0}', 'порівняння'),
    # керування
    '¿': (3, '¿ умова то інакше', 'якщо умова ● — «то», інакше «інакше» (обчислюється лише одна гілка)',
          'якщо {0} то {1} інакше {2}', 'керування'),
    '∀': (2, '∀ список λx тіло', 'для кожного елемента виконати функцію; дає ∅', 'для кожного з {0}: {1}', 'керування'),
    'μ': (2, 'μ список λx тіло', 'перетворити кожен елемент (map)', 'кожен з {0} перетворити: {1}', 'керування'),
    'φ': (2, 'φ список λx умова', 'лишити елементи, для яких умова ● (filter)', 'з {0} лишити ті, де {1}', 'керування'),
    'Σ': (3, 'Σ список початок Λa x тіло', 'згорнути (reduce): a ← тіло для кожного x', 'згорнути {0} від {1}: {2}', 'керування'),
    '↻': (3, '↻ стан λs умова λs крок', 'поки умова(стан) ● — стан ← крок(стан); дає останній стан',
          'починаючи з {0}, поки {1}, повторювати {2}', 'керування'),
    '☂': (2, '☂ вираз λe обробник', 'обчислити вираз; якщо помилка — обробник(текст помилки)',
          'спробувати {0}; при помилці — {1}', 'керування'),
    '☠': (1, '☠ повідомлення', 'зупинитися з помилкою', 'ПОМИЛКА {0}', 'керування'),
    # рядки, списки, словники
    '…': (2, '… a b', 'ряд цілих від a до b включно', 'ряд {0}…{1}', 'дані'),
    'ρ': (1, 'ρ x', 'довжина рядка, списку чи словника', 'довжина({0})', 'дані'),
    '§': (2, '§ x i', 'елемент списку/рядка за індексом (з 0; відʼємний — з кінця) або словника за ключем',
          '{0}[{1}]', 'дані'),
    '✎': (3, '✎ словник ключ значення', 'новий словник із доданим/заміненим ключем', '{0} з [{1}] = {2}', 'дані'),
    'κ': (1, 'κ словник', 'список ключів', 'ключі({0})', 'дані'),
    '↺': (1, '↺ x', 'обернути рядок або список', 'навпаки({0})', 'дані'),
    '↑': (1, '↑ список', 'відсортувати за зростанням', 'відсортувати({0})', 'дані'),
    '✂': (2, '✂ рядок роздільник', 'розрізати рядок на список', 'розрізати {0} по {1}', 'дані'),
    '⁀': (2, '⁀ список роздільник', 'склеїти список у рядок', 'склеїти {0} через {1}', 'дані'),
    'σ': (1, 'σ x', 'у рядок', 'рядок({0})', 'дані'),
    'ν': (1, 'ν рядок', 'у число', 'число({0})', 'дані'),
    'δ': (1, 'δ рядок', 'розібрати JSON', 'з JSON({0})', 'дані'),
    'Δ': (1, 'Δ x', 'записати як JSON', 'у JSON({0})', 'дані'),
    '»': (1, '» x', 'надрукувати', 'надрукувати {0}', 'дані'),
    # довіра
    '≈': (2, '≈ x c', 'призначити впевненість c ∈ [0, 1] (записується в слід)', '{0} з впевненістю {1}', 'довіра'),
    '±': (1, '± x', 'впевненість значення', 'впевненість({0})', 'довіра'),
    '⚗': (2, '⚗ список поріг', 'лишити елементи з впевненістю ≥ порогу (кожне рішення — у слід)',
          'з {0} лишити впевнені щонайменше на {1}', 'довіра'),
    # агент
    '🜂': (None, '🜂 「намір」 【「дозвіл」 …】', 'ПЕЧАТКА: намір і повний перелік дозволів; перший рядок програми',
          'ПЕЧАТКА', 'агент'),
    '🜔': (None, '🜔інструмент аргументи…', 'викликати інструмент (лише з печатки)', 'інструмент {name}({args})', 'агент'),
    '🜁': (4, '🜁 「імʼя」 「намір」 【「дозвіл」 …】 вираз', 'делегувати вираз субагенту з підмножиною дозволів',
          'субагент «{0}» (намір {1}; дозволи {2}) виконує: {3}', 'агент'),
    '🜄': (2, '🜄 ключ значення', 'запамʼятати (памʼять агента)', 'запамʼятати [{0}] = {1}', 'агент'),
    '🜃': (1, '🜃 ключ', 'пригадати (∅, якщо нема)', 'пригадати [{0}]', 'агент'),
    '🜍': (2, '🜍 значення λx умова', 'перевірити: умова(значення) має бути ●; дає значення',
          'перевірити {0}: {1}', 'агент'),
}
CONSTS = {'●': True, '○': False, '∅': None}
OPEN = {'【': '】', '『': '』', '《': '》'}
CLOSE = set(OPEN.values())
STR_OPEN, STR_CLOSE, COMMENT, SEP, NEG = '「', '」', '※', '¦', '¯'
GREEK = range(0x0370, 0x0400)
ASCII_HINTS = {
    '+': '＋', '-': '－ (або ¯ перед числом)', '*': '×', '/': '÷', '=': '＝', '<': '‹', '>': '›',
    '%': '‰', '!': '¬', '&': '∧', '|': '∨', '(': '《 … 》', ')': '《 … 》', '[': '【 … 】', ']': '【 … 】',
    '{': '『 … 』', '}': '『 … 』', '"': '「 … 」', "'": '「 … 」', '#': '※', ';': '¦', ':': '←',
}

# ------------------------------------------------------------------ значення


class V:
    """Значення з впевненістю c ∈ [0, 1]."""
    __slots__ = ('v', 'c')

    def __init__(self, v, c=1.0):
        self.v, self.c = v, c


class Fn:
    __slots__ = ('params', 'body', 'env', 'name')

    def __init__(self, params, body, env, name=None):
        self.params, self.body, self.env, self.name = params, body, env, name


def kind(x):
    v = x.v
    if v is None:
        return 'ніщо'
    if isinstance(v, bool):
        return 'істинність'
    if isinstance(v, (int, float)):
        return 'число'
    if isinstance(v, str):
        return 'рядок'
    if isinstance(v, list):
        return 'список'
    if isinstance(v, dict):
        return 'словник'
    return 'функція'


def fmt_num(n):
    if isinstance(n, float):
        if n.is_integer() and abs(n) < 1e15:
            return str(int(n))
        return f'{n:.12g}'
    return str(n)


def show(x, top=True):
    """Друкована форма. Рядок верхнього рівня — як є."""
    v = x.v
    if isinstance(v, str):
        return v if top else '「' + v.replace('\\', '\\\\').replace('」', '\\」').replace('\n', '\\n') + '」'
    if v is None:
        return '∅'
    if isinstance(v, bool):
        return '●' if v else '○'
    if isinstance(v, (int, float)):
        return fmt_num(v)
    if isinstance(v, list):
        return '【' + ' '.join(show(e, False) for e in v) + '】'
    if isinstance(v, dict):
        return '『' + ' '.join(f'{show(V(k), False)} {show(e, False)}' for k, e in v.items()) + '』'
    return f'λ{v.name or ""}'


def plain(x):
    """У Python-значення (для JSON і сліду)."""
    v = x.v
    if isinstance(v, list):
        return [plain(e) for e in v]
    if isinstance(v, dict):
        return {k: plain(e) for k, e in v.items()}
    if isinstance(v, Fn):
        return 'λ'
    return v


def wrap(p):
    if isinstance(p, list):
        return V([wrap(e) for e in p])
    if isinstance(p, dict):
        return V({str(k): wrap(e) for k, e in p.items()})
    return V(p)


def deep_eq(a, b):
    va, vb = a.v, b.v
    if isinstance(va, bool) or isinstance(vb, bool):
        return type(va) is type(vb) and va == vb
    if isinstance(va, list) and isinstance(vb, list):
        return len(va) == len(vb) and all(deep_eq(x, y) for x, y in zip(va, vb))
    if isinstance(va, dict) and isinstance(vb, dict):
        return va.keys() == vb.keys() and all(deep_eq(va[k], vb[k]) for k in va)
    return va == vb


def brief(x, n=120):
    s = show(x, False)
    return s if len(s) <= n else s[:n] + '…'


# ------------------------------------------------------------------ лексика


def is_name_start(ch):
    return unicodedata.category(ch).startswith('L') and ord(ch) not in GREEK or ch == '_'


def is_name_char(ch):
    return is_name_start(ch) or unicodedata.category(ch) in ('Nd', 'Mn', 'Mc') or ch in 'ʼ\''


def digit(ch):
    return unicodedata.decimal(ch, None)


def lex(src):
    toks, i, line, col = [], 0, 1, 1
    n = len(src)

    def adv(k=1):
        nonlocal i, line, col
        for _ in range(k):
            if src[i] == '\n':
                line, col = line + 1, 1
            else:
                col += 1
            i += 1

    while i < n:
        ch, pos = src[i], (line, col)
        if ch == '\n':
            toks.append(('nl', None, pos))
            adv()
        elif ch in '\ufe0e\ufe0f' or ch.isspace():
            adv()
        elif ch == COMMENT:
            while i < n and src[i] != '\n':
                adv()
        elif ch == STR_OPEN:
            adv()
            buf = []
            while True:
                if i >= n:
                    raise StaticError('незакритий рядок «「» — бракує «」»', pos)
                c = src[i]
                if c == STR_CLOSE:
                    adv()
                    break
                if c == '\\' and i + 1 < n:
                    e = src[i + 1]
                    buf.append({'n': '\n', 't': '\t', '」': '」', '\\': '\\'}.get(e, '\\' + e))
                    adv(2)
                    continue
                buf.append(c)
                adv()
            toks.append(('str', ''.join(buf), pos))
        elif digit(ch) is not None or (ch == NEG and i + 1 < n and digit(src[i + 1]) is not None):
            neg = ch == NEG
            if neg:
                adv()
            num = ''
            while i < n and digit(src[i]) is not None:
                num += str(digit(src[i]))
                adv()
            if i + 1 < n and src[i] in '.·' and digit(src[i + 1]) is not None:
                num += '.'
                adv()
                while i < n and digit(src[i]) is not None:
                    num += str(digit(src[i]))
                    adv()
            val = float(num) if '.' in num else int(num)
            toks.append(('num', -val if neg else val, pos))
        elif is_name_start(ch):
            buf = ''
            while i < n and (is_name_char(src[i]) or (src[i] == '.' and i + 1 < n and is_name_start(src[i + 1]))):
                buf += src[i]
                adv()
            toks.append(('name', unicodedata.normalize('NFC', buf), pos))
        elif ch in GLYPHS or ch in CONSTS:
            toks.append(('glyph', ch, pos))
            adv()
        elif ch in OPEN:
            toks.append(('open', ch, pos))
            adv()
        elif ch in CLOSE:
            toks.append(('close', ch, pos))
            adv()
        elif ch == SEP:
            toks.append(('nl', None, pos))
            adv()
        else:
            hint = ASCII_HINTS.get(ch)
            if ord(ch) in GREEK:
                raise StaticError(f'невідомий гліф «{ch}» (грецькі літери — це гліфи, не імена)', pos)
            raise StaticError(f'невідомий символ «{ch}»' + (f' — може, {hint}?' if hint else ''), pos)
    toks.append(('eof', None, (line, col)))
    return toks


# ------------------------------------------------------------------ розбір
# Вузол: (вид, позиція, ...). Види: lit var call op bind lam list dict block seal tool deleg


class Parser:
    def __init__(self, toks):
        self.t, self.i = toks, 0
        self.scopes = [{}]          # імʼя → арність функції або 0 для значення
        self.cap_stack = []         # дозволи найближчої печатки / субагента: {інструмент: [обмеження]}

    def peek(self):
        return self.t[self.i]

    def next(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def skip_nl(self):
        while self.peek()[0] == 'nl':
            self.i += 1

    def lookup(self, name):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        return None

    def program(self):
        self.skip_nl()
        tok = self.peek()
        if tok[0] != 'glyph' or tok[1] != '🜂':
            raise StaticError('програма має починатися з печатки: 🜂 「намір」 【дозволи】', tok[2])
        stmts = self.statements(end=None)
        return ('block', (1, 1), stmts)

    def statements(self, end):
        stmts = []
        while True:
            self.skip_nl()
            tok = self.peek()
            if tok[0] == 'eof':
                if end:
                    raise StaticError(f'незакрите «{end[0]}» — бракує «{OPEN[end[0]]}»', end[1])
                return stmts
            if tok[0] == 'close':
                if end and tok[1] == OPEN[end[0]]:
                    self.next()
                    return stmts
                raise StaticError(f'зайва «{tok[1]}»', tok[2])
            stmts.append(self.expr())
            after = self.peek()
            if after[0] not in ('nl', 'eof', 'close'):
                raise StaticError('вираз уже завершено, а в рядку ще щось є — зайве чи бракує аргументу раніше? '
                                  '(кілька виразів в одному рядку розділяйте ¦)', after[2])

    def expr(self):
        self.skip_nl()
        kind_, val, pos = self.next()
        if kind_ == 'num' or kind_ == 'str':
            return ('lit', pos, val)
        if kind_ == 'glyph' and val in CONSTS:
            return ('lit', pos, CONSTS[val])
        if kind_ == 'name':
            if '.' in val:
                raise StaticError(f'імʼя з крапкою «{val}» буває лише після 🜔', pos)
            ar = self.lookup(val)
            if ar is None:
                if any(val in sc for sc in self.scopes):
                    raise StaticError(f'«{val}» ще обчислюється: значення не може посилатися на себе '
                                      f'(і не може перекривати однойменне зовнішнє імʼя у власному виразі)', pos)
                raise StaticError(f'невідоме імʼя «{val}» (імена треба спершу назвати ←)', pos)
            if ar:
                return ('call', pos, val, [self.expr() for _ in range(ar)])
            return ('var', pos, val)
        if kind_ == 'open':
            if val == '【':
                return ('list', pos, self.items('】'))
            if val == '『':
                items = self.items('』')
                if len(items) % 2:
                    raise StaticError('у словнику 『』 має бути парна кількість: ключ значення …', pos)
                return ('dict', pos, items)
            self.scopes.append({})
            stmts = self.statements(end=(val, pos))
            self.scopes.pop()
            return ('block', pos, stmts)
        if kind_ == 'close':
            raise StaticError(f'«{val}» тут не очікувалося — бракує аргументу', pos)
        if kind_ == 'eof' or kind_ == 'nl':
            raise StaticError('бракує аргументу: вираз обірвався', pos)
        return self.glyph(val, pos)

    def items(self, close):
        out = []
        while True:
            self.skip_nl()
            tok = self.peek()
            if tok[0] == 'close' and tok[1] == close:
                self.next()
                return out
            if tok[0] == 'eof':
                raise StaticError(f'бракує «{close}»', tok[2])
            out.append(self.expr())

    def name_tok(self, what):
        self.skip_nl()
        kind_, val, pos = self.next()
        if kind_ != 'name' or '.' in val:
            raise StaticError(f'після {what} очікувалося імʼя', pos)
        return val, pos

    def lam(self, n, pos):
        params = [self.name_tok('λ' if n == 1 else 'Λ')[0] for _ in range(n)]
        if len(set(params)) != n:
            raise StaticError('однакові імена параметрів', pos)
        self.scopes.append({p: 0 for p in params})
        body = self.expr()
        self.scopes.pop()
        return ('lam', pos, params, body)

    def caps_literal(self, what, pos):
        node = self.expr()
        if node[0] != 'list' or any(e[0] != 'lit' or not isinstance(e[2], str) for e in node[2]):
            raise StaticError(f'дозволи {what} мають бути буквальним списком рядків 【「…」 …】', pos)
        caps = {}
        for e in node[2]:
            name, _, scope = e[2].partition(':')
            name = name.strip()
            if name not in TOOLS:
                raise StaticError(f'невідомий інструмент у дозволах: «{name}»', e[1])
            if TOOLS[name][3] and not scope.strip():
                raise StaticError(f'«{name}» потребує обмеження: «{name}:{TOOLS[name][4]}»', e[1])
            caps.setdefault(name, []).extend([s.strip()] if (s := scope.strip()) else [])
        return node, caps

    def glyph(self, g, pos):
        if g == '🜂':
            if self.cap_stack:
                raise StaticError('печатка 🜂 — лише одна й лише першим рядком програми', pos)
            intent = self.expr()
            if intent[0] != 'lit' or not isinstance(intent[2], str) or not intent[2].strip():
                raise StaticError('намір печатки має бути непорожнім буквальним рядком 「…」', pos)
            _, caps = self.caps_literal('печатки', pos)
            self.cap_stack.append(caps)
            return ('seal', pos, intent[2], caps)
        if g == '🜔':
            kind_, name, npos = self.next()
            if kind_ != 'name':
                raise StaticError('після 🜔 очікувалася назва інструмента: 🜔файл.читати …', npos)
            if name not in TOOLS:
                raise StaticError(f'невідомий інструмент «{name}»; є: {", ".join(TOOLS)}', npos)
            if name not in self.cap_stack[-1]:
                raise StaticError(f'інструмента «{name}» немає в печатці (дозволах) цього агента', npos)
            return ('tool', pos, name, [self.expr() for _ in range(TOOLS[name][0])])
        if g == '←':
            name, npos = self.name_tok('←')
            if name in self.scopes[-1]:
                raise StaticError(f'«{name}» уже назване тут — значення в Nigredo не перепризначаються', npos)
            self.skip_nl()
            nxt = self.peek()
            if nxt[0] == 'glyph' and nxt[1] in 'λΛ':
                self.scopes[-1][name] = 1 if nxt[1] == 'λ' else 2   # рекурсія: імʼя видно в тілі
            else:
                self.scopes[-1][name] = None                        # поки обчислюється — ще не видно
            value = self.expr()
            if self.scopes[-1][name] is None:
                self.scopes[-1][name] = 0
            return ('bind', pos, name, value)
        if g in 'λΛ':
            return self.lam(1 if g == 'λ' else 2, pos)
        if g == '🜁':
            name = self.expr()
            intent = self.expr()
            if name[0] != 'lit' or not isinstance(name[2], str) or intent[0] != 'lit' or not isinstance(intent[2], str):
                raise StaticError('🜁: імʼя і намір субагента мають бути буквальними рядками', pos)
            _, caps = self.caps_literal('субагента', pos)
            parent = self.cap_stack[-1]
            for t, scopes in caps.items():
                if t not in parent:
                    raise StaticError(f'субагент «{name[2]}» просить «{t}», якого немає в батька', pos)
                for s in scopes:
                    if s not in parent[t]:
                        raise StaticError(f'субагент «{name[2]}» просить «{t}:{s}» — у батька лише {parent[t]}', pos)
                if not scopes:
                    caps[t] = list(parent[t])
            self.cap_stack.append(caps)
            self.scopes.append({})          # імена субагента не просочуються до батька
            body = self.expr()
            self.scopes.pop()
            self.cap_stack.pop()
            return ('deleg', pos, name[2], intent[2], caps, body)
        ar = GLYPHS[g][0]
        return ('op', pos, g, [self.expr() for _ in range(ar)])


def parse(src):
    p = Parser(lex(src))
    return p.program()


# ------------------------------------------------------------------ слід


class Trace:
    """Слід веде інтерпретатор, а не програма. JSONL, кожен запис містить хеш попереднього."""

    def __init__(self, out=None):
        self.out, self.prev, self.n = out, '0' * 16, 0
        self.depth = 0

    def __call__(self, event, **data):
        self.n += 1
        rec = {'№': self.n, 'подія': event, 'глибина': self.depth, **data, 'попередній': self.prev}
        body = json.dumps(rec, ensure_ascii=False, sort_keys=True)
        h = hashlib.sha256(body.encode()).hexdigest()[:16]
        rec['хеш'] = h
        self.prev = h
        if self.out:
            self.out.write(json.dumps(rec, ensure_ascii=False) + '\n')
            self.out.flush()


def verify_trace(path):
    prev, n = '0' * 16, 0
    for lineno, line in enumerate(open(path, encoding='utf-8'), 1):
        rec = json.loads(line)
        h = rec.pop('хеш', None)
        body = json.dumps(rec, ensure_ascii=False, sort_keys=True)
        if rec.get('попередній') != prev or hashlib.sha256(body.encode()).hexdigest()[:16] != h:
            return f'✗ слід пошкоджено або змінено в рядку {lineno}'
        prev, n = h, n + 1
    return f'✓ слід цілий: {n} записів, останній хеш {prev}'


# ------------------------------------------------------------------ інструменти


def _path_ok(it, tool, p, pos, write=False):
    if not isinstance(p, str):
        raise NgrError(f'{tool}: шлях має бути рядком', pos)
    real = os.path.realpath(os.path.join(it.cwd, p))
    check = os.path.dirname(real) if write else real
    for base in it.caps[tool]:
        b = os.path.realpath(os.path.join(it.cwd, base))
        if check == b or check.startswith(b + os.sep) or (not write and real == b):
            return real
    raise NgrError(f'{tool}: «{p}» поза дозволеним ({", ".join(it.caps[tool])})', pos)


def t_oracle(it, pos, q):
    h = hashlib.sha256(show(q).encode()).digest()
    return V(bool(h[0] & 1), round(0.3 + 0.69 * int.from_bytes(h[1:3], 'big') / 65535, 2))


def t_dice(it, pos, n):
    if not isinstance(n.v, int) or isinstance(n.v, bool) or n.v < 1:
        raise NgrError('жереб: потрібне ціле ≥ 1', pos)
    return V(it.rng.randint(1, n.v))


def t_time(it, pos):
    return V(datetime.now(timezone.utc).isoformat(timespec='seconds'))


def t_read(it, pos, p):
    real = _path_ok(it, 'файл.читати', p.v, pos)
    try:
        with open(real, encoding='utf-8') as f:
            return V(f.read(2_000_000))
    except OSError as e:
        raise NgrError(f'файл.читати: {e.strerror}: {p.v}', pos)


def t_write(it, pos, p, text):
    real = _path_ok(it, 'файл.писати', p.v, pos, write=True)
    if not isinstance(text.v, str):
        raise NgrError('файл.писати: вміст має бути рядком (для даних — Δ)', pos)
    try:
        with open(real, 'w', encoding='utf-8') as f:
            f.write(text.v)
    except OSError as e:
        raise NgrError(f'файл.писати: {e.strerror}: {p.v}', pos)
    return V(None)


def t_list(it, pos, p):
    real = _path_ok(it, 'файл.список', p.v, pos)
    try:
        return V([V(x) for x in sorted(os.listdir(real))])
    except OSError as e:
        raise NgrError(f'файл.список: {e.strerror}: {p.v}', pos)


def t_fetch(it, pos, url):
    u = url.v
    host = urllib.parse.urlsplit(u).hostname if isinstance(u, str) else None
    if not u or urllib.parse.urlsplit(u).scheme not in ('http', 'https') or host not in it.caps['мережа.взяти']:
        raise NgrError(f'мережа.взяти: «{u}» поза дозволеними хостами ({", ".join(it.caps["мережа.взяти"])})', pos)
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'nigredo/0.2'}), timeout=30) as r:
            return V(r.read(1_000_000).decode('utf-8', 'replace'))
    except Exception as e:
        raise NgrError(f'мережа.взяти: {e}', pos)


def t_agent(it, pos, name, prompt):
    if name.v not in it.caps['агент']:
        raise NgrError(f'агент: «{name.v}» поза дозволеними ({", ".join(it.caps["агент"])})', pos)
    try:
        reg = {a['name']: a['path'] for a in json.load(open(AGENTS_REGISTRY, encoding='utf-8'))['agents']}
    except OSError:
        raise NgrError('агент: немає реєстру агентів', pos)
    if name.v not in reg:
        raise NgrError(f'агент: «{name.v}» немає в реєстрі', pos)
    try:
        r = subprocess.run(['claude', '-p', show(prompt)], cwd=reg[name.v], capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise NgrError(f'агент: {e}', pos)
    if r.returncode:
        raise NgrError(f'агент «{name.v}» завершився з кодом {r.returncode}', pos)
    return V(r.stdout.strip())


# імʼя: (арність, сигнатура, що робить, потрібне обмеження?, приклад обмеження, реалізація)
TOOLS = {
    'оракул': (1, '🜔оракул питання → ●/○', 'ІМІТАЦІЯ ненадійного джерела: відповідь і впевненість (0.3–0.99) '
               'з SHA-256 питання; нічого не знає', False, '', t_oracle),
    'жереб': (1, '🜔жереб n → 1…n', 'випадкове ціле (зерно --зерно, типово 0)', False, '', t_dice),
    'час': (0, '🜔час → рядок', 'поточний час UTC, ISO 8601', False, '', t_time),
    'файл.читати': (1, '🜔файл.читати шлях → рядок', 'прочитати текстовий файл', True, 'тека', t_read),
    'файл.писати': (2, '🜔файл.писати шлях текст → ∅', 'записати (перезаписати) текстовий файл', True, 'тека', t_write),
    'файл.список': (1, '🜔файл.список тека → список', 'імена в теці', True, 'тека', t_list),
    'мережа.взяти': (1, '🜔мережа.взяти url → рядок', 'HTTP GET (до 1 МБ, 30 с)', True, 'хост', t_fetch),
    'агент': (2, '🜔агент 「імʼя」 「запит」 → рядок', 'спитати справжнього агента з реєстру лаунчера '
              '(claude -p у його теці; він діє з власними правами)', True, 'імʼя', t_agent),
}


def load_allowlist(path):
    if path is None:
        path = ALLOWLIST
        if not os.path.exists(path):
            return DEFAULT_ALLOWED, '(типові: лише іграшкові інструменти)'
    try:
        data = json.load(open(path, encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise Refused(f'не вдалося прочитати дозволи власника {path}: {e}')
    digest = hashlib.sha256(open(path, 'rb').read()).hexdigest()[:16]
    return data.get('дозволено', []), f'{path} (sha256 {digest})'


def check_allowlist(caps, allowed, cwd):
    """Печатка ⊆ дозволи власника. Теки — вкладеність, хости й агенти — точний збіг."""
    granted = {}
    for a in allowed:
        name, _, scope = a.partition(':')
        granted.setdefault(name.strip(), []).append(scope.strip())
    missing = []
    for tool, scopes in caps.items():
        if tool not in granted:
            missing.append(tool)
            continue
        for s in scopes:
            ok = False
            for g in granted[tool]:
                if not g:
                    continue
                if TOOLS[tool][4] == 'тека':
                    if not os.path.isabs(os.path.expanduser(g)):
                        continue                      # у дозволах власника — лише абсолютні теки
                    rs, rg = os.path.realpath(os.path.join(cwd, s)), os.path.realpath(os.path.expanduser(g))
                    ok = ok or rs == rg or rs.startswith(rg + os.sep)
                else:
                    ok = ok or s == g
            if not ok:
                missing.append(f'{tool}:{s}')
    return missing


# ------------------------------------------------------------------ виконання


class Interp:
    def __init__(self, trace, seed=0, steps=DEFAULT_STEPS, cwd='.', out=None):
        self.trace, self.rng = trace, random.Random(seed)
        self.steps_left, self.cwd = steps, os.path.abspath(cwd)
        self.out = out or sys.stdout
        self.memory, self.agent, self.caps = {}, 'головний', {}
        self.depth = 0

    def step(self, pos):
        self.steps_left -= 1
        if self.steps_left < 0:
            raise Fatal('перевищено ліміт кроків (--кроки)', pos)

    def run(self, prog):
        return self.eval(prog, {})

    def lookup(self, env, name, pos):
        e = env
        while e is not None:
            if name in e:
                return e[name]
            e = e.get('\0parent')
        raise NgrError(f'невідоме імʼя «{name}»', pos)

    def call(self, fn, args, pos):
        if not isinstance(fn.v, Fn):
            raise NgrError(f'очікувалася функція, а не {kind(fn)}', pos)
        f = fn.v
        if len(f.params) != len(args):
            raise NgrError(f'функція чекає {len(f.params)} аргумент(и), а дано {len(args)}', pos)
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise Fatal('надто глибока рекурсія', pos)
        try:
            env = dict(zip(f.params, args))
            env['\0parent'] = f.env
            return self.eval(f.body, env)
        finally:
            self.depth -= 1

    def need(self, x, k, g, pos):
        if kind(x) != k:
            raise NgrError(f'{g}: очікувалося {k}, а не {kind(x)} {brief(x, 40)}', pos)
        return x.v

    def num(self, x, g, pos):
        if isinstance(x.v, bool) or not isinstance(x.v, (int, float)):
            raise NgrError(f'{g}: очікувалося число, а не {kind(x)} {brief(x, 40)}', pos)
        return x.v

    def boolean(self, x, g, pos):
        if not isinstance(x.v, bool):
            raise NgrError(f'{g}: умова має бути ● або ○, а не {kind(x)} {brief(x, 40)}', pos)
        return x.v

    def eval(self, node, env):
        k, pos = node[0], node[1]
        self.step(pos)
        if k == 'lit':
            return V(node[2])
        if k == 'var':
            return self.lookup(env, node[2], pos)
        if k == 'list':
            return V([self.eval(e, env) for e in node[2]])
        if k == 'dict':
            d = {}
            items = node[2]
            for i in range(0, len(items), 2):
                key = self.eval(items[i], env)
                if not isinstance(key.v, str):
                    raise NgrError('ключ словника має бути рядком', items[i][1])
                d[key.v] = self.eval(items[i + 1], env)
            return V(d)
        if k == 'block':
            inner = {'\0parent': env}
            result = V(None)
            for s in node[2]:
                result = self.eval(s, inner)
            return result
        if k == 'bind':
            if node[3][0] == 'lam':
                fn = V(Fn(node[3][2], node[3][3], env, node[2]))
                env[node[2]] = fn
                return fn
            val = self.eval(node[3], env)
            env[node[2]] = val
            return val
        if k == 'lam':
            return V(Fn(node[2], node[3], env))
        if k == 'call':
            fn = self.lookup(env, node[2], pos)
            return self.call(fn, [self.eval(a, env) for a in node[3]], pos)
        if k == 'seal':
            self.caps = node[3]
            self.trace('печатка', агент=self.agent, намір=node[2], дозволи=node[3])
            return V(None)
        if k == 'tool':
            args = [self.eval(a, env) for a in node[3]]
            name = node[2]
            try:
                res = TOOLS[name][5](self, pos, *args)
            except NgrError as e:
                self.trace('інструмент', агент=self.agent, назва=name, аргументи=[brief(a) for a in args], помилка=e.msg)
                raise
            c = min([res.c] + [a.c for a in args])
            res = V(res.v, c)
            self.trace('інструмент', агент=self.agent, назва=name, аргументи=[brief(a) for a in args],
                       результат=brief(res), впевненість=c)
            return res
        if k == 'deleg':
            return self.delegate(node, env)
        return self.op(node[2], node[3], env, pos)

    def delegate(self, node, env):
        _, pos, name, intent, caps, body = node
        saved = (self.memory, self.agent, self.caps)
        self.trace('делегування', агент=self.agent, субагент=name, намір=intent, дозволи=caps)
        self.memory, self.agent, self.caps = {}, f'{self.agent}/{name}', caps
        self.trace.depth += 1
        try:
            res = self.eval(body, {'\0parent': env})
        except Fatal:
            raise
        except NgrError as e:
            self.trace('субагент впав', агент=self.agent, помилка=e.msg)
            raise NgrError(f'у субагенті «{name}»: {e.msg}', e.pos or pos)
        finally:
            self.trace.depth -= 1
            self.memory, self.agent, self.caps = saved
        self.trace('субагент повернув', агент=self.agent, субагент=name, результат=brief(res), впевненість=res.c)
        return res

    def op(self, g, argn, env, pos):
        E = lambda i: self.eval(argn[i], env)   # noqa: E731
        if g == '¿':
            c = E(0)
            branch = E(1) if self.boolean(c, g, pos) else E(2)
            return V(branch.v, min(c.c, branch.c))
        if g == '☂':
            try:
                return E(0)
            except Fatal:
                raise
            except NgrError as e:
                self.trace('помилку перехоплено', агент=self.agent, помилка=e.msg)
                return self.call(E(1), [V(e.msg)], pos)
        if g in '∀μφ':
            lst = E(0)
            items = self.seq(lst, g, pos)
            fn = E(1)
            if g == '∀':
                for x in items:
                    self.call(fn, [x], pos)
                return V(None)
            if g == 'μ':
                return V([self.call(fn, [x], pos) for x in items], lst.c)
            return V([x for x in items if self.boolean(self.call(fn, [x], pos), g, pos)], lst.c)
        if g == 'Σ':
            lst, acc, fn = E(0), E(1), E(2)
            for x in self.seq(lst, g, pos):
                acc = self.call(fn, [acc, x], pos)
            return acc
        if g == '↻':
            s, cond, stepf = E(0), E(1), E(2)
            while self.boolean(self.call(cond, [s], pos), g, pos):
                s = self.call(stepf, [s], pos)
            return s
        args = [E(i) for i in range(len(argn))]
        res = self.prim(g, args, pos)
        if g not in ('≈', '±', '⚗', '►', '▶', '🜃', '🜍', '§'):
            res.c = min([res.c] + [a.c for a in args])
        return res

    def seq(self, x, g, pos):
        if isinstance(x.v, list):
            return x.v
        if isinstance(x.v, str):
            return [V(ch, x.c) for ch in x.v]
        raise NgrError(f'{g}: очікувався список або рядок, а не {kind(x)}', pos)

    def prim(self, g, a, pos):
        n = lambda i: self.num(a[i], g, pos)      # noqa: E731
        b = lambda i: self.boolean(a[i], g, pos)  # noqa: E731
        if g == '＋':
            x, y = a[0].v, a[1].v
            if isinstance(x, str) and isinstance(y, str) or isinstance(x, list) and isinstance(y, list):
                return V(x + y)
            if isinstance(x, str) or isinstance(y, str):
                raise NgrError(f'＋: рядок можна зʼєднати лише з рядком (для числа — σ): {brief(a[0], 30)} ＋ {brief(a[1], 30)}', pos)
            return V(n(0) + n(1))
        if g == '－':
            return V(n(0) - n(1))
        if g == '×':
            return V(n(0) * n(1))
        if g in '÷‰':
            x, y = n(0), n(1)
            if y == 0:
                raise NgrError(f'{g}: ділення на нуль', pos)
            if g == '‰':
                return V(x % y)
            return V(x // y if isinstance(x, int) and isinstance(y, int) and x % y == 0 else x / y)
        if g == '⌊':
            return V(int(n(0) // 1))
        if g == '＝':
            return V(deep_eq(a[0], a[1]))
        if g == '≠':
            return V(not deep_eq(a[0], a[1]))
        if g in '‹›≤≥':
            x, y = a[0].v, a[1].v
            if not (isinstance(x, str) and isinstance(y, str)):
                x, y = n(0), n(1)
            return V({'‹': x < y, '›': x > y, '≤': x <= y, '≥': x >= y}[g])
        if g == '∧':
            return V(b(0) and b(1))
        if g == '∨':
            return V(b(0) or b(1))
        if g == '¬':
            return V(not b(0))
        if g == '►':
            return self.call(a[0], [a[1]], pos)
        if g == '▶':
            return self.call(a[0], [a[1], a[2]], pos)
        if g == '☠':
            raise NgrError(show(a[0]), pos)
        if g == '…':
            x, y = n(0), n(1)
            if not (isinstance(x, int) and isinstance(y, int)):
                raise NgrError('…: межі ряду мають бути цілими', pos)
            if y - x > 10_000_000:
                raise NgrError('…: надто довгий ряд', pos)
            return V([V(i) for i in range(x, y + 1)])
        if g == 'ρ':
            if not isinstance(a[0].v, (str, list, dict)):
                raise NgrError(f'ρ: довжина буває в рядка, списку чи словника, а не в {kind(a[0])}', pos)
            return V(len(a[0].v), a[0].c)
        if g == '§':
            x, i = a[0].v, a[1].v
            if isinstance(x, dict):
                if not isinstance(i, str):
                    raise NgrError('§: ключ словника — рядок', pos)
                return x.get(i, V(None))
            if isinstance(x, (list, str)):
                if isinstance(i, bool) or not isinstance(i, int):
                    raise NgrError('§: індекс має бути цілим', pos)
                if not -len(x) <= i < len(x):
                    raise NgrError(f'§: індекс {i} поза межами (довжина {len(x)})', pos)
                return x[i] if isinstance(x, list) else V(x[i], a[0].c)
            raise NgrError(f'§: очікувався список, рядок чи словник, а не {kind(a[0])}', pos)
        if g == '✎':
            d = dict(self.need(a[0], 'словник', g, pos))
            d[self.need(a[1], 'рядок', g, pos)] = a[2]
            return V(d)
        if g == 'κ':
            return V([V(k) for k in self.need(a[0], 'словник', g, pos)])
        if g == '↺':
            x = a[0].v
            if isinstance(x, (list, str)):
                return V(x[::-1])
            raise NgrError(f'↺: очікувався список або рядок, а не {kind(a[0])}', pos)
        if g == '↑':
            lst = self.need(a[0], 'список', g, pos)
            try:
                return V(sorted(lst, key=lambda e: (isinstance(e.v, str), e.v)))
            except TypeError:
                raise NgrError('↑: сортувати можна лише числа й рядки', pos)
        if g == '✂':
            s, sep = self.need(a[0], 'рядок', g, pos), self.need(a[1], 'рядок', g, pos)
            return V([V(p) for p in (s.split(sep) if sep else s.split())])
        if g == '⁀':
            lst, sep = self.need(a[0], 'список', g, pos), self.need(a[1], 'рядок', g, pos)
            return V(sep.join(show(e) for e in lst))
        if g == 'σ':
            return V(show(a[0]))
        if g == 'ν':
            s = self.need(a[0], 'рядок', g, pos).strip()
            s = ''.join(str(digit(ch)) if digit(ch) is not None else ch for ch in s).replace('·', '.')
            try:
                return V(int(s))
            except ValueError:
                try:
                    return V(float(s))
                except ValueError:
                    raise NgrError(f'ν: «{s}» не число', pos)
        if g == 'δ':
            try:
                return wrap(json.loads(self.need(a[0], 'рядок', g, pos)))
            except ValueError as e:
                raise NgrError(f'δ: не JSON: {e}', pos)
        if g == 'Δ':
            return V(json.dumps(plain(a[0]), ensure_ascii=False))
        if g == '»':
            text = show(a[0])
            print(text, file=self.out, flush=True)
            self.trace('вивід', агент=self.agent, текст=text if len(text) <= 300 else text[:300] + '…')
            return V(None)
        if g == '≈':
            c = n(1)
            if not 0 <= c <= 1:
                raise NgrError('≈: впевненість має бути від 0 до 1', pos)
            self.trace('впевненість', агент=self.agent, значення=brief(a[0]), було=a[0].c, стало=c)
            return V(a[0].v, c)
        if g == '±':
            return V(a[0].c)
        if g == '⚗':
            lst, t = self.need(a[0], 'список', g, pos), n(1)
            kept = []
            for x in lst:
                ok = x.c >= t
                self.trace('відсів', агент=self.agent, значення=brief(x), впевненість=x.c, поріг=t,
                           рішення='лишено' if ok else 'відкинуто')
                if ok:
                    kept.append(x)
            return V(kept, a[0].c)
        if g == '🜄':
            key = self.need(a[0], 'рядок', g, pos)
            self.memory[key] = a[1]
            self.trace('памʼять', агент=self.agent, дія='запамʼятати', ключ=key, значення=brief(a[1]), впевненість=a[1].c)
            return V(None)
        if g == '🜃':
            key = self.need(a[0], 'рядок', g, pos)
            res = self.memory.get(key, V(None))
            self.trace('памʼять', агент=self.agent, дія='пригадати', ключ=key, значення=brief(res))
            return res
        if g == '🜍':
            r = self.call(a[1], [a[0]], pos)
            ok = self.boolean(r, g, pos)
            self.trace('перевірка', агент=self.agent, значення=brief(a[0]), результат='пройдена' if ok else 'НЕ пройдена')
            if not ok:
                raise NgrError(f'🜍: перевірку не пройдено для {brief(a[0], 60)}', pos)
            return a[0]
        raise NgrError(f'гліф «{g}» не реалізовано', pos)


# ------------------------------------------------------------------ розбір для людини


def explain(node, ind=0):
    """Перекласти дерево програми українським псевдокодом."""
    pad = '  ' * ind
    k = node[0]
    if k == 'lit':
        v = node[2]
        if isinstance(v, str):
            return '«' + v.replace('\n', '↵') + '»'
        return show(V(v))
    if k == 'var':
        return node[2]
    if k == 'list':
        return '[' + ', '.join(explain(e, ind) for e in node[2]) + ']'
    if k == 'dict':
        it = node[2]
        return '{' + ', '.join(f'{explain(it[i], ind)}: {explain(it[i + 1], ind)}' for i in range(0, len(it), 2)) + '}'
    if k == 'block':
        inner = [explain(s, ind + 1) for s in node[2]]
        return 'послідовно:\n' + '\n'.join('  ' * (ind + 1) + s for s in inner)
    if k == 'bind':
        return f'{node[2]} ← {explain(node[3], ind)}'
    if k == 'lam':
        return f'({", ".join(node[2])}) ↦ {explain(node[3], ind)}'
    if k == 'call':
        return f'{node[2]}({", ".join(explain(a, ind) for a in node[3])})'
    if k == 'seal':
        caps = '; '.join(t + (f' [{", ".join(s)}]' if s else '') for t, s in node[3].items()) or 'жодних'
        return f'ПЕЧАТКА — намір: «{node[2]}»; дозволи: {caps}'
    if k == 'tool':
        return f'інструмент {node[2]}({", ".join(explain(a, ind) for a in node[3])})'
    if k == 'deleg':
        caps = ', '.join(t + (f' [{", ".join(s)}]' if s else '') for t, s in node[4].items()) or 'жодних'
        return f'субагент «{node[2]}» (намір «{node[3]}»; дозволи: {caps}) виконує:\n{pad}  {explain(node[5], ind + 1)}'
    g, args = node[2], node[3]
    parts = [explain(a, ind) for a in args]
    lam = args[-1] if args and args[-1][0] == 'lam' else None
    if lam and g in LAMBDA_TEMPLATES:
        if g == '↻' and args[1][0] == 'lam':
            return (f'{lam[2][0]} ← {parts[0]}; поки {explain(args[1][3], ind)} (де {args[1][2][0]} — стан): '
                    f'{lam[2][0]} ← {explain(lam[3], ind)}; результат — {lam[2][0]}')
        return LAMBDA_TEMPLATES[g].format(*parts[:-1], p=', '.join(lam[2]), body=explain(lam[3], ind))
    return GLYPHS[g][3].format(*parts)


LAMBDA_TEMPLATES = {
    '∀': 'для кожного {p} з {0}: {body}',
    'μ': 'список: для кожного {p} з {0} — {body}',
    'φ': 'ті {p} з {0}, де {body}',
    'Σ': 'згорнути {0}, почавши з {1}: ({p}) ↦ {body}',
    '↻': '',
    '☂': 'спробувати {0}; якщо помилка {p}: {body}',
    '🜍': 'перевірити, що для {p} = {0}: {body}',
}


def explain_program(prog):
    return '\n'.join(explain(s) for s in prog[2])


def seal_report(prog, allowed, source, cwd):
    seal = prog[2][0]
    lines = ['ПЕЧАТКА', f'  намір: «{seal[2]}»', '  дозволи:']
    for t, s in seal[3].items():
        lines.append(f'    {t}' + (f' → {", ".join(s)}' if s else '') + f'   ({TOOLS[t][2]})')
    if not seal[3]:
        lines.append('    жодних — програма лише обчислює')
    subs = []

    def walk(n):
        if isinstance(n, tuple):
            if n and n[0] == 'deleg':
                subs.append(n)
            for x in n:
                walk(x)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    walk(prog)
    for d in subs:
        lines.append(f'  субагент «{d[2]}»: намір «{d[3]}», дозволи: {", ".join(d[4]) or "жодних"}')
    missing = check_allowlist(seal[3], allowed, cwd)
    lines.append(f'  дозволи власника: {source}')
    lines.append('  ✓ печатка в межах дозволів власника' if not missing else f'  ✗ бракує дозволу власника: {", ".join(missing)}')
    return '\n'.join(lines)


# ------------------------------------------------------------------ памʼятка


def cheatsheet():
    out = [f'# Nigredo {VERSION} — памʼятка для агентів', '',
           '_Згенеровано з інтерпретатора: `ngr --памʼятка`. Повна специфікація — `spec/SPEC.md`._', '',
           '## Як це влаштовано', '',
           '- **Префіксний запис з фіксованою арністю**: гліф, потім рівно стільки аргументів, скільки він бере.',
           '  `＋ 2 3` → 5; `» × 2 ＋ 3 4` → 14. Дужок для групування не треба: арність однозначна.',
           '- Один рядок — один вираз. Якщо вираз не завершено, він продовжується на наступному рядку;',
           '  зайве після завершеного виразу — помилка. Кілька виразів в одному рядку — через `¦`.',
           '- **Значення не змінюються**: `← імʼя вираз` називає назавжди. Цикли — `∀ μ φ Σ ↻`.',
           '- Імена — слова будь-якою мовою (кирилиця, латиниця, руни), без пробілів. Грецькі літери — гліфи.',
           '- Умови — лише `●` (так) або `○` (ні); `∅` — ніщо. Числа — будь-якими цифрами, мінус — `¯5`.',
           '- Рядок `「…」` (екранування `\\」 \\n`), список `【…】`, словник `『ключ значення …』`, блок `《…》` (значення — останній вираз).',
           '- Коментар — `※` до кінця рядка.',
           '- **Кожне значення має впевненість** (типово 1). Результат обчислення має впевненість',
           '  найменш упевненого джерела (і умови `¿`). Підняти її можна лише `≈`, і це записується в слід.',
           '', '## Печатка (обовʼязкова)', '',
           'Перший рядок кожної програми — `🜂 「намір」 【「дозвіл」 …】`. Інструмент, якого нема в печатці,',
           'не пройде розбір. Печатка має вкладатися в дозволи власника (`~/.nigredo/дозволи.json`), інакше',
           'програма не запуститься. Власник бачить печатку командою `ngr --печатка файл.ngr`.', '',
           '```', '🜂 「порахувати слова у звітах」 【「файл.читати:звіти」 「файл.писати:вихід」】', '```', '',
           'Дозвіл для файлів — тека (і все в ній); для мережі — хост; для агента — імʼя з реєстру.', '',
           ]
    groups = {}
    for g, (ar, sig, desc, _, grp) in GLYPHS.items():
        groups.setdefault(grp, []).append((g, sig, desc))
    names = {'імена': 'Імена й функції', 'числа': 'Числа', 'порівняння': 'Порівняння й логіка',
             'керування': 'Керування', 'дані': 'Дані', 'довіра': 'Довіра', 'агент': 'Агент'}
    for grp, title in names.items():
        out += [f'## {title}', '', '| Гліф | Запис | Що робить |', '|---|---|---|']
        for g, sig, desc in groups[grp]:
            out.append(f'| `{g}` | `{sig}` | {desc} |')
        out.append('')
    out += ['## Інструменти', '', '| Запис | Що робить | Дозвіл у печатці |', '|---|---|---|']
    for name, (ar, sig, desc, scoped, ex, _) in TOOLS.items():
        out.append(f'| `{sig}` | {desc} | `「{name}' + (f':{ex}' if scoped else '') + '」` |')
    out += ['', '## Приклади', '',
            '```', '🜂 「FizzBuzz」 【】',
            '∀ …1 15 λn » ¿ ＝0 ‰n 15 「FizzBuzz」 ¿ ＝0 ‰n 3 「Fizz」 ¿ ＝0 ‰n 5 「Buzz」 n', '```', '',
            '```', '🜂 「факторіал」 【】', '← факт λn ¿ ≤n 1 1 ×n факт －n 1', '» факт 10',
            '```', '',
            '```', '🜂 「спитати оракула через субагента і лишити впевнені відповіді」 【「оракул」】',
            '← відповіді μ【「чи світ чорніє?」 「чи сіль тверда?」 「чи сірка горить?」】 λq',
            '  🜁 「провидець」 「спитати оракула」 【「оракул」】 🜔оракул q',
            '← впевнені ⚗відповіді 0.6', '🜄 「впевнені」 впевнені',
            '🜍 🜃「впевнені」 λx ＝ρx ρвпевнені', '» ρвпевнені', '```', '',
            '```', '🜂 「словник, блок і перехоплення помилки」 【】',
            '← ціни 『「хліб」 28 「сіль」 12』',
            '← з_пдв λц 《', '  ← база §ціни ц', '  × база 1.2', '》',
            '» з_пдв 「хліб」',
            '» ☂ ν「не число」 λe ＋「не вийшло: 」 e', '```', '',
            '## Пастки', '',
            '- `＝0 ‰n 3` — спершу гліф, потім аргументи: «остача n на 3 дорівнює 0».',
            '- Імена склеюються з цифрами: `n15` — одне імʼя; пишіть `n 15`.',
            '- `＋` зʼєднує рядки лише з рядками: `＋「№」 σn`.',
            '- Функцію, названу `←`, викликають просто: `факт 10`. Функцію-значення (параметр) — `► f x`.',
            '- Субагент бачить імена батька лише для читання (змінити їх неможливо взагалі) і має власну памʼять.',
            '- Ціна в токенах: кириличне імʼя коштує в 3–8 разів більше за коротке латинське (`відповіді` — 8 токенів,',
            '  `ans` — 1). Для економії беріть короткі імена; рядки й коментарі — будь-якою мовою.',
            '',
            '## Чесно про межі', '',
            '- Печатку перевіряє інтерпретатор: програма не зробить нічого поза нею. Але агент, який має shell,',
            '  може обійти Nigredo взагалі — печатка захищає від помилок і робить намір видимим, а не від зловмисника.',
            '- `оракул` — імітація; `агент` — справжній виклик Claude (коштує грошей і часу).',
            '- Порівняно з Python: без печатки — приблизно стільки ж токенів; печатка додає фіксовану ціну.',
            '',
            '## Прозорість', '',
            '- `ngr --печатка файл.ngr` — що програмі дозволено, ще до запуску.',
            '- `ngr --розбір файл.ngr` — переклад українським псевдокодом.',
            '- `ngr --слід слід.jsonl файл.ngr` — журнал веде інтерпретатор (програма в нього писати не може):',
            '  печатка, кожен інструмент, делегування, памʼять, перевірки, відсів, впевненість, вивід.',
            '  Записи зчеплено хешами: `ngr --перевірити-слід слід.jsonl`.', '']
    return '\n'.join(out)


# ------------------------------------------------------------------ командний рядок

USAGE = f"""Nigredo {VERSION}
  ngr ФАЙЛ.ngr | -e КОД
    --печатка              що програмі дозволено (без виконання)
    --розбір               переклад українським псевдокодом (без виконання)
    --слід ФАЙЛ|-          журнал дій (JSONL зі звʼязаними хешами); - = stderr
    --дозволи ФАЙЛ         дозволи власника (типово ~/.nigredo/дозволи.json)
    --зерно N              зерно для «жереб» (типово 0)
    --кроки N              ліміт кроків (типово {DEFAULT_STEPS})
  ngr --перевірити-слід ФАЙЛ
  ngr --памʼятка           згенерувати памʼятку для агентів
"""


def main(argv):
    opts = {'mode': 'run', 'trace': None, 'allow': None, 'seed': 0, 'steps': DEFAULT_STEPS}
    src = path = None
    it = iter(argv)
    for a in it:
        if a in ('-h', '--help'):
            print(USAGE)
            return 0
        if a == '--памʼятка':
            print(cheatsheet())
            return 0
        if a == '--перевірити-слід':
            msg = verify_trace(next(it))
            print(msg)
            return 0 if msg.startswith('✓') else 1
        if a in ('--печатка', '--розбір'):
            opts['mode'] = a[2:]
        elif a == '--слід':
            opts['trace'] = next(it)
        elif a == '--дозволи':
            opts['allow'] = next(it)
        elif a == '--зерно':
            opts['seed'] = int(next(it))
        elif a == '--кроки':
            opts['steps'] = int(next(it))
        elif a == '-e':
            src, path = next(it), '<-e>'
        else:
            path = a
            try:
                src = open(a, encoding='utf-8').read()
            except OSError as e:
                print(f'✗ {a}: {e.strerror}', file=sys.stderr)
                return 2
    if src is None:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        prog = parse(src)
    except StaticError as e:
        print(e, file=sys.stderr)
        return 2
    try:
        allowed, source = load_allowlist(opts['allow'])
    except Refused as e:
        print(e, file=sys.stderr)
        return 3
    if opts['mode'] == 'розбір':
        print(explain_program(prog))
        return 0
    if opts['mode'] == 'печатка':
        print(seal_report(prog, allowed, source, os.getcwd() if path == '<-e>' else os.path.dirname(os.path.abspath(path))))
        return 0
    # шляхи в печатці й інструментах — відносно теки програми (для -e — поточної теки)
    cwd = os.getcwd() if path == '<-e>' else os.path.dirname(os.path.abspath(path))
    missing = check_allowlist(prog[2][0][3], allowed, cwd)
    tout = None
    if opts['trace'] == '-':
        tout = sys.stderr
    elif opts['trace']:
        tout = open(opts['trace'], 'w', encoding='utf-8')
    trace = Trace(tout)
    trace('початок', версія=VERSION, програма=path, sha256=hashlib.sha256(src.encode()).hexdigest()[:16],
          дозволи_власника=source)
    if missing:
        trace('відмова', бракує=missing)
        print(f'✗ печатка просить більше, ніж дозволив власник: {", ".join(missing)}\n'
              f'  дозволи власника: {source}', file=sys.stderr)
        return 3
    interp = Interp(trace, seed=opts['seed'], steps=opts['steps'], cwd=cwd)
    try:
        interp.run(prog)
        trace('кінець', кроків=opts['steps'] - interp.steps_left)
        return 0
    except NgrError as e:
        trace('помилка', повідомлення=str(e))
        print(e, file=sys.stderr)
        return 1
    finally:
        if tout and tout is not sys.stderr:
            tout.close()


if __name__ == '__main__':
    sys.setrecursionlimit(100_000)
    threading.stack_size(256 * 1024 * 1024)
    result = [1]

    def target():
        try:
            result[0] = main(sys.argv[1:])
        except BrokenPipeError:
            result[0] = 0
    t = threading.Thread(target=target)
    t.start()
    t.join()
    sys.exit(result[0])
