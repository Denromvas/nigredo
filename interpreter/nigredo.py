#!/usr/bin/env python3
"""Nigredo 0.2 — еталонний інтерпретатор.

Специфікація: spec/SPEC.md. Без залежностей, Python ≥ 3.10.
Таблиці GLYPHS і TOOLS нижче — єдине джерело правди: з них генеруються
памʼятка (`--памʼятка`) і переклад (`--розбір`).
"""
import hashlib
import hmac
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
from decimal import ROUND_HALF_UP, Decimal

VERSION = '0.4'
MAX_DEPTH = 2000
MAX_SIZE = 5_000_000      # найбільший рядок/список/словник (символів чи елементів); --розмір N
DEFAULT_STEPS = 10_000_000
OWNER_HOME = os.path.realpath(os.path.expanduser(os.environ.get('NIGREDO_HOME', '~/.nigredo')))
# реєстр агентів для інструмента «агент»: {"agents": [{"name": …, "path": …}]}
AGENTS_REGISTRY = os.environ.get('NIGREDO_AGENTS', os.path.join(OWNER_HOME, 'агенти.json'))
DEFAULT_ALLOWED = ['оракул', 'жереб', 'час']



class NgrError(Exception):
    """Помилка програми: її можна перехопити ☂. c — впевненість даних, через які вона сталася."""

    def __init__(self, msg, pos=None, c=1.0):
        super().__init__(msg)
        self.msg, self.pos, self.c, self.where = msg, pos, c, False

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
    '∘': (None, '∘ імʼя', 'функція, названа ←, як значення: μ 【1 2】 ∘факт', '{name}', 'імена'),
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
    '∋': (2, '∋ x y', 'чи містить: підрядок у рядку, елемент у списку, ключ у словнику', '({0} містить {1})', 'дані'),
    '⇄': (3, '⇄ рядок що чим', 'замінити всі входження', 'у {0} замінити {1} на {2}', 'дані'),
    '⊢': (1, '⊢ рядок', 'обрізати пробіли й невидимі символи (BOM) з країв', 'обрізати({0})', 'дані'),
    '⇅': (2, '⇅ список λx ключ', 'відсортувати за ключем (рядки — за українською абеткою)', 'відсортувати {0} за {1}', 'дані'),
    '⊞': (2, '⊞ список λx ключ', 'згрупувати: словник ключ-рядок → список елементів', 'згрупувати {0} за {1}', 'дані'),
    '≅': (2, '≅ x n', 'округлити до n знаків після коми (половину — вгору, як у грошах)', 'округлити({0}, {1})', 'числа'),
    '⌗': (2, '⌗ x n', 'число в рядок рівно з n знаками після коми: ⌗ 245.5 2 → 「245.50」', 'формат({0}, {1})', 'числа'),
    '⌂': (0, '⌂', 'аргументи програми (список рядків): ngr файл.ngr -- а б', 'аргументи програми', 'дані'),
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
    'µ': 'μ (грецька мю)', '−': '－', '’': 'ʼ', '＞': '›', '＜': '‹', '.': '… (ряд) або 0.5 (дріб)',
    '@': '∘ (функція як значення)', '«': '「 … 」', '»': '» (це друк; рядок — 「 … 」)',
}

# ------------------------------------------------------------------ значення


class V:
    """Значення з впевненістю c ∈ [0, 1]. Для списку/словника/рядка c — мінімум вмісту,
    а s — впевненість будови: які елементи є, скільки їх і в якому порядку."""
    __slots__ = ('v', 'c', 's')

    def __init__(self, v, c=1.0, s=None):
        self.v, self.c = v, c
        self.s = c if s is None else s


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
        return repr(n)
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


def wrap(p, c=1.0):
    if isinstance(p, list):
        return V([wrap(e, c) for e in p], c)
    if isinstance(p, dict):
        return V({str(k): wrap(e, c) for k, e in p.items()}, c)
    return V(p, c)


def mk(items, extra=1.0):
    """Список, чия впевненість — мінімум вмісту (і extra)."""
    return V(items, min([extra] + [e.c for e in items]), extra)


def capc(x, c):
    """Встановити впевненість c значенню і всьому, що в ньому."""
    v = x.v
    if isinstance(v, list):
        return V([capc(e, c) for e in v], c, min(x.s, c))
    if isinstance(v, dict):
        return V({k: capc(e, c) for k, e in v.items()}, c, min(x.s, c))
    return V(v, c)


UA_ORDER = {ch: i for i, ch in enumerate('абвгґдеєжзиіїйклмнопрстуфхцчшщьюя')}


def sort_key(e):
    v = e.v
    if isinstance(v, str):
        return (1, [(UA_ORDER.get(ch, 100 + ord(ch)), ch) for ch in v.casefold()], v)
    return (0, v)


def safe(s):
    """Для виводу людині: керівні й невидимі символи — видимими."""
    out = []
    for ch in s:
        if ch == '\n':
            out.append('↵')
        elif ch == '\t':
            out.append('⇥')
        elif unicodedata.category(ch) in ('Cc', 'Cf', 'Zl', 'Zp', 'Co', 'Cn'):
            out.append(f'⟨U+{ord(ch):04X}⟩')
        else:
            out.append(ch)
    return ''.join(out)


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
    s = safe(show(x, False))
    return s if len(s) <= n else s[:n] + '…'


# ------------------------------------------------------------------ лексика


def is_name_start(ch):
    return unicodedata.category(ch).startswith('L') and ord(ch) not in GREEK or ch == '_'


def is_name_char(ch):
    return is_name_start(ch) or unicodedata.category(ch) in ('Nd', 'Mn', 'Mc') or ch in 'ʼ\''


def digit(ch):
    return unicodedata.decimal(ch, None)


def script_of(ch):
    """Письмо символу за назвою Unicode: LATIN, CYRILLIC, RUNIC, FULLWIDTH, ARABIC-INDIC …"""
    name = unicodedata.name(ch, '')
    if unicodedata.category(ch) == 'Nd':
        return name.split('DIGIT')[0].strip() or 'ASCII'
    return name.split(' ')[0]


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
            j = i + 1
            while j < n and src[j] in ' \t':
                j += 1
            indent = j - i - 1
            if toks and toks[-1][0] == 'nl' and toks[-1][1] >= 0:
                toks[-1] = ('nl', indent, toks[-1][2])     # порожні рядки й коментарі між ними не рахуються
            else:
                toks.append(('nl', indent, pos))
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
            num, scripts = '', set()
            while i < n and digit(src[i]) is not None:
                scripts.add(script_of(src[i]))
                num += str(digit(src[i]))
                adv()
            if i + 1 < n and src[i] in '.·' and digit(src[i + 1]) is not None:
                num += '.'
                adv()
                while i < n and digit(src[i]) is not None:
                    scripts.add(script_of(src[i]))
                    num += str(digit(src[i]))
                    adv()
            if len(scripts) > 1:
                raise StaticError('у числі змішано цифри різних письмен — так легко сховати інше значення', pos)
            val = float(num) if '.' in num else int(num)
            toks.append(('num', -val if neg else val, pos))
        elif is_name_start(ch):
            buf = ''
            while i < n and (is_name_char(src[i]) or (src[i] == '.' and i + 1 < n and is_name_start(src[i + 1]))):
                buf += src[i]
                adv()
            buf = unicodedata.normalize('NFC', buf)
            scripts = {script_of(c) for c in buf if unicodedata.category(c).startswith('L')}
            if len(scripts) > 1:
                raise StaticError(f'імʼя «{buf}» змішує письма ({", ".join(sorted(scripts))}): однакові на вигляд '
                                  f'літери різних абеток у Nigredo заборонені', pos)
            toks.append(('name', buf, pos))
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
            toks.append(('nl', -1, pos))
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
        self.ctx = [('stmt', 0)]    # ('stmt', відступ інструкції) або ('items',) усередині 【】『』
        self.head = -1              # індекс токена, з якого почалася поточна інструкція

    def peek(self):
        return self.t[self.i]

    def next(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def skip_nl(self):
        while self.peek()[0] == 'nl':
            self.i += 1

    def cont_nl(self):
        """Перенос усередині виразу: у 【】『』 — завжди; інакше — лише на рядок з більшим відступом."""
        while self.peek()[0] == 'nl':
            tok = self.peek()
            ctx = self.ctx[-1]
            if ctx[0] == 'items' or tok[1] > ctx[1]:
                self.i += 1
                continue
            raise StaticError('рядок закінчився, а виразові бракує аргументу (щоб продовжити вираз на '
                              'наступному рядку, зробіть там більший відступ)', tok[2])

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
            self.head = self.i
            self.ctx.append(('stmt', tok[2][1] - 1))
            stmts.append(self.expr())
            self.ctx.pop()
            after = self.peek()
            if after[0] not in ('nl', 'eof', 'close'):
                raise StaticError('вираз уже завершено, а в рядку ще щось є — зайве чи бракує аргументу раніше? '
                                  '(кілька виразів в одному рядку розділяйте ¦)', after[2])

    def expr(self):
        self.cont_nl()
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
                self.ctx.append(('items',))
                items = self.items('】')
                self.ctx.pop()
                return ('list', pos, items)
            if val == '『':
                self.ctx.append(('items',))
                items = self.items('』')
                self.ctx.pop()
                if len(items) % 2:
                    raise StaticError('у словнику 『』 має бути парна кількість: ключ значення …', pos)
                return ('dict', pos, items)
            self.scopes.append({})
            self.ctx.append(('stmt', 10 ** 9))      # між інструкціями блоку — лише skip_nl
            stmts = self.statements(end=(val, pos))
            self.ctx.pop()
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
        self.cont_nl()
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

    def caps_literal(self, what, pos, inherit=False):
        node = self.expr()
        if node[0] != 'list' or any(e[0] != 'lit' or not isinstance(e[2], str) for e in node[2]):
            raise StaticError(f'дозволи {what} мають бути буквальним списком рядків 【「…」 …】', pos)
        caps = {}
        for e in node[2]:
            name, _, scope = e[2].partition(':')
            name = name.strip()
            if name not in TOOLS:
                raise StaticError(f'невідомий інструмент у дозволах: «{name}»', e[1])
            if TOOLS[name][3] and not scope.strip() and not inherit:
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
            if self.i - 1 != self.head:
                raise StaticError('← називає лише на початку інструкції; усередині виразу — блок 《 ← … 》', pos)
            name, npos = self.name_tok('←')
            if name in self.scopes[-1]:
                raise StaticError(f'«{name}» уже назване тут — значення в Nigredo не перепризначаються', npos)
            self.cont_nl()
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
        if g == '∘':
            name, npos = self.name_tok('∘')
            if not self.lookup(name):
                raise StaticError(f'∘ бере функцію, названу ← (λ або Λ); «{name}» — не така', npos)
            return ('var', pos, name)
        if g == '🜁':
            name = self.expr()
            intent = self.expr()
            if name[0] != 'lit' or not isinstance(name[2], str) or intent[0] != 'lit' or not isinstance(intent[2], str):
                raise StaticError('🜁: імʼя і намір субагента мають бути буквальними рядками', pos)
            _, caps = self.caps_literal('субагента', pos, inherit=True)
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
    """Слід веде інтерпретатор, а не програма. JSONL; кожен запис підписано HMAC-SHA256 ключем власника
    (теку власника програма не бачить) і зчеплено з попереднім. Останній запис — «кінець» або «помилка»."""

    def __init__(self, outs, key):
        self.outs, self.key, self.prev, self.n = outs, key, '0' * 16, 0
        self.depth = 0

    def __call__(self, event, **data):
        self.n += 1
        rec = {'№': self.n, 'подія': event, 'глибина': self.depth, **data, 'попередній': self.prev}
        h = sign(self.key, rec)
        rec['хеш'] = h
        self.prev = h
        line = json.dumps(rec, ensure_ascii=False) + '\n'
        for o in self.outs:
            o.write(line)
            o.flush()


def sign(key, rec):
    body = json.dumps(rec, ensure_ascii=False, sort_keys=True).encode()
    return hmac.new(key, body, hashlib.sha256).hexdigest()[:16]


def owner_key():
    os.makedirs(OWNER_HOME, mode=0o700, exist_ok=True)
    path = os.path.join(OWNER_HOME, 'ключ')
    if not os.path.exists(path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(os.urandom(32).hex())
    return open(path).read().strip().encode()


def verify_trace(path):
    key, prev, n, last = owner_key(), '0' * 16, 0, None
    try:
        lines = open(path, encoding='utf-8').read().splitlines()
    except (OSError, UnicodeDecodeError) as e:
        return f'✗ слід не прочитати: {e}'
    for lineno, line in enumerate(lines, 1):
        try:
            rec = json.loads(line)
            h = rec.pop('хеш')
        except (ValueError, KeyError, AttributeError, TypeError):
            return f'✗ слід пошкоджено в рядку {lineno}: це не запис сліду'
        if rec.get('попередній') != prev or not hmac.compare_digest(sign(key, rec), str(h)):
            return f'✗ слід пошкоджено або змінено в рядку {lineno}'
        prev, n, last = h, n + 1, rec.get('подія')
    # завершальні: «кінець», «помилка» або «відмова» на старті (запис №2, до будь-якої дії);
    # «заборонено» посеред роботи — не кінець
    if not (last in ('кінець', 'помилка') or (last == 'відмова' and n == 2)):
        return f'✗ слід обірвано: {n} записів, останній — «{last}», а не кінець/помилка/відмова на старті'
    return f'✓ слід цілий і завершений ({last}): {n} записів, останній хеш {prev}'


def trace_val(x, full=False):
    """Значення для сліду: повністю; дуже довге — довжина, sha256 і початок."""
    s = show(x, False)
    if full or len(s) <= 4000:
        return s
    return {'довжина': len(s), 'sha256': hashlib.sha256(s.encode()).hexdigest(), 'початок': s[:1000]}


# ------------------------------------------------------------------ інструменти


OS_ERRORS = {'ENOENT': 'немає такого файлу чи теки', 'EACCES': 'немає доступу', 'EISDIR': 'це тека, а не файл',
             'ENOTDIR': 'це не тека', 'ENOSPC': 'немає місця на диску'}


def os_err(tool, e, p):
    import errno
    return f'{tool}: {OS_ERRORS.get(errno.errorcode.get(e.errno, ""), e.strerror)}: {p}'


def _path_ok(it, tool, p, pos, write=False):
    if not isinstance(p, str):
        raise NgrError(f'{tool}: шлях має бути рядком', pos)
    real = os.path.realpath(os.path.join(it.cwd, p))
    if inside(real, OWNER_HOME) or real in it.protected:
        raise NgrError(f'{tool}: «{p}» — це тека власника або слід; програмі туди не можна', pos)
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
    except UnicodeDecodeError:
        raise NgrError(f'файл.читати: не UTF-8: {p.v}', pos)
    except OSError as e:
        raise NgrError(os_err('файл.читати', e, p.v), pos)


def t_write(it, pos, p, text):
    real = _path_ok(it, 'файл.писати', p.v, pos, write=True)
    if not isinstance(text.v, str):
        raise NgrError('файл.писати: вміст має бути рядком (для даних — Δ)', pos)
    try:
        os.makedirs(os.path.dirname(real), exist_ok=True)
        with open(real, 'w', encoding='utf-8') as f:
            f.write(text.v)
    except OSError as e:
        raise NgrError(os_err('файл.писати', e, p.v), pos)
    return V(None)


def t_list(it, pos, p):
    real = _path_ok(it, 'файл.список', p.v, pos)
    try:
        return V([V(x) for x in sorted(os.listdir(real))])
    except OSError as e:
        raise NgrError(os_err('файл.список', e, p.v), pos)


def t_fetch(it, pos, url):
    u = url.v
    parts = urllib.parse.urlsplit(u) if isinstance(u, str) else None
    try:
        port = parts.port if parts else None
    except ValueError:
        port = -1
    allowed = it.caps['мережа.взяти']
    ok = parts and parts.scheme in ('http', 'https') and not parts.username and not parts.password and (
        (parts.hostname in allowed and port in (None, 80, 443)) or f'{parts.hostname}:{port}' in allowed)
    if not ok:
        raise NgrError(f'мережа.взяти: «{u}» поза дозволеним ({", ".join(allowed)}; інший порт, ніж 80/443, '
                       f'треба дозволити явно як хост:порт; без логіна в адресі)', pos)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise NgrError(f'мережа.взяти: переадресацію на «{newurl}» заборонено — дозвольте й візьміть ту адресу явно', pos)
    try:
        opener = urllib.request.build_opener(NoRedirect)
        q = urllib.parse.quote
        u = urllib.parse.urlunsplit(parts._replace(path=q(parts.path, safe='/%'), query=q(parts.query, safe='=&%+')))
        with opener.open(urllib.request.Request(u, headers={'User-Agent': f'nigredo/{VERSION}'}), timeout=30) as r:
            return V(r.read(1_000_000).decode('utf-8', 'replace'))
    except NgrError:
        raise
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


def read_allowlist(path, cwd=None):
    """«дозволено» — для всіх програм; «для_тек» — {"/абсолютна/тека": [дозволи]} лише для програм у цій теці."""
    try:
        data = json.load(open(path, encoding='utf-8'))
        lst = list(data.get('дозволено', []))
        per_dir = data.get('для_тек', {})
        if not isinstance(per_dir, dict):
            raise ValueError('«для_тек» має бути словником тека → список')
        for d, extra in per_dir.items():
            if not isinstance(extra, list):
                raise ValueError(f'«для_тек» → «{d}»: потрібен список')
            if cwd and os.path.isabs(os.path.expanduser(d)) and inside(cwd, os.path.expanduser(d)):
                lst += extra
        if not all(isinstance(x, str) for x in lst):
            raise ValueError('дозволи мають бути рядками')
        return lst
    except (OSError, ValueError, AttributeError) as e:
        raise Refused(f'не вдалося прочитати дозволи {path}: {e}')


def load_allowlist(narrow=None, cwd=None):
    """Дозволи власника — OWNER_HOME/дозволи.json (без нього — лише іграшкові інструменти).
    --дозволи ФАЙЛ лише звужує їх: лишається те, що є в обох."""
    path = os.path.join(OWNER_HOME, 'дозволи.json')
    if os.path.exists(path):
        owner = read_allowlist(path, cwd)
        source = f'{path} (sha256 {hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]})'
    else:
        owner, source = list(DEFAULT_ALLOWED), '(файлу власника немає: лише іграшкові інструменти)'
    if narrow:
        extra = read_allowlist(narrow)
        owner = [a for a in extra if not check_allowlist(parse_caps(a), owner, '/')]
        source += f'; звужено {narrow}'
    return owner, source


def parse_caps(entry):
    name, _, scope = entry.partition(':')
    name = name.strip()
    if name not in TOOLS:
        return {name: []}
    return {name: [scope.strip()] if scope.strip() else []}


def inside(path, base):
    path, base = os.path.realpath(path), os.path.realpath(base)
    return path == base or path.startswith(base + os.sep)


def check_allowlist(caps, allowed, cwd):
    """Печатка ⊆ дозволи власника. Теки — вкладеність, хости й агенти — точний збіг."""
    granted = {}
    for a in allowed:
        name, _, scope = a.partition(':')
        granted.setdefault(name.strip(), []).append(scope.strip())
    missing = []
    for tool, scopes in caps.items():
        if tool not in TOOLS or tool not in granted:
            missing.append(tool)
            continue
        for s in scopes:
            ok = False
            if TOOLS[tool][4] == 'тека':
                rs = os.path.realpath(os.path.join(cwd, s))
                if inside(rs, OWNER_HOME) or inside(OWNER_HOME, rs):
                    missing.append(f'{tool}:{s} (зачіпає теку власника {OWNER_HOME})')
                    continue
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
    def __init__(self, trace, seed=0, steps=DEFAULT_STEPS, cwd='.', out=None, argv=(), protected=(), max_size=MAX_SIZE):
        self.trace, self.rng = trace, random.Random(seed)
        self.argv, self.protected = list(argv), set(protected)
        self.max_size = max_size
        self.steps_left, self.cwd = steps, os.path.abspath(cwd)
        self.out = out or sys.stdout
        self.memory, self.agent, self.caps = {}, 'головний', {}
        self.pc = 1.0          # впевненість контексту керування: усе, що створено тут, не впевненіше
        self.mem_c = 1.0       # наскільки сумнівними були ключі, якими писали в памʼять
        self.try_stack = []    # для кожного ☂: найменша впевненість усього, що обчислено в його тілі

        self.depth = 0

    def taint(self, c):
        if c < 1:
            for i, t in enumerate(self.try_stack):
                if c < t:
                    self.try_stack[i] = c

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
        saved = self.pc
        self.pc = min(saved, fn.c)
        self.taint(fn.c)
        try:
            env = dict(zip(f.params, args))
            env['\0parent'] = f.env
            res = self.eval(f.body, env)
            return capc(res, fn.c) if fn.c < res.c else res
        finally:
            self.pc = saved
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
            return V(node[2], self.pc)
        if k == 'var':
            return self.lookup(env, node[2], pos)
        if k == 'list':
            if len(node[2]) > self.max_size:
                raise Fatal('список завеликий', pos)
            return mk([self.eval(e, env) for e in node[2]], self.pc)
        if k == 'dict':
            d, c, sc = {}, self.pc, self.pc
            items = node[2]
            for i in range(0, len(items), 2):
                key = self.eval(items[i], env)
                if not isinstance(key.v, str):
                    raise NgrError('ключ словника має бути рядком', items[i][1])
                d[key.v] = self.eval(items[i + 1], env)
                c, sc = min(c, key.c, d[key.v].c), min(sc, key.c)
            return V(d, c, sc)
        if k == 'block':
            inner = {'\0parent': env}
            result = V(None)
            for s in node[2]:
                result = self.eval(s, inner)
            return result
        if k == 'bind':
            if node[3][0] == 'lam':
                fn = V(Fn(node[3][2], node[3][3], env, node[2]), self.pc)
                env[node[2]] = fn
                return fn
            val = self.eval(node[3], env)
            env[node[2]] = val
            return val
        if k == 'lam':
            return V(Fn(node[2], node[3], env), self.pc)
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
            full = name in ('агент', 'мережа.взяти')
            targs = [trace_val(a, full) for a in args]
            if name not in self.caps:          # права — того, хто виконує зараз, а не того, хто написав функцію
                self.trace('заборонено', агент=self.agent, назва=name, аргументи=targs,
                           причина='інструмента немає в дозволах цього агента')
                raise NgrError(f'агент «{self.agent}» не має дозволу «{name}» (функцію з інструментом '
                               f'викликано там, де цього дозволу немає)', pos)
            try:
                res = TOOLS[name][5](self, pos, *args)
            except NgrError as e:
                self.trace('інструмент', агент=self.agent, назва=name, аргументи=targs, помилка=e.msg)
                raise
            c = min([res.c, self.pc] + [a.c for a in args])
            res = capc(res, c) if c < 1 else res
            self.taint(c)
            self.trace('інструмент', агент=self.agent, назва=name, аргументи=targs,
                       результат=trace_val(res), впевненість=c)
            return res
        if k == 'deleg':
            return self.delegate(node, env)
        return self.op(node[2], node[3], env, pos)

    def delegate(self, node, env):
        _, pos, name, intent, caps, body = node
        saved = (self.memory, self.agent, self.caps, self.mem_c)
        self.trace('делегування', агент=self.agent, субагент=name, намір=intent, дозволи=caps)
        self.memory, self.agent, self.caps, self.mem_c = {}, f'{self.agent}/{name}', caps, 1.0
        self.trace.depth += 1
        try:
            res = self.eval(body, {'\0parent': env})
        except Fatal:
            raise
        except NgrError as e:
            self.trace('субагент впав', агент=self.agent, помилка=e.msg)
            raise NgrError(f'у субагенті «{name}»: {e.msg}', e.pos or pos, e.c)
        finally:
            self.trace.depth -= 1
            self.memory, self.agent, self.caps, self.mem_c = saved
        self.trace('субагент повернув', агент=self.agent, субагент=name, результат=trace_val(res), впевненість=res.c)
        return res

    def op(self, g, argn, env, pos):
        E = lambda i: self.eval(argn[i], env)   # noqa: E731
        if g == '¿':
            c = E(0)
            self.taint(c.c)
            saved = self.pc
            self.pc = min(saved, c.c)
            try:
                branch = E(1) if self.boolean(c, g, pos) else E(2)
            finally:
                self.pc = saved
            return capc(branch, min(c.c, branch.c)) if c.c < branch.c else branch
        if g == '☂':
            self.try_stack.append(self.pc)
            try:
                res = E(0)
                tc = self.try_stack.pop()
                return capc(res, tc) if tc < res.c else res
            except Fatal:
                raise
            except NgrError as e:
                tc = min(self.try_stack.pop(), e.c)
                self.trace('помилку перехоплено', агент=self.agent, помилка=e.msg, впевненість=tc)
                saved = self.pc
                self.pc = min(saved, tc)
                try:
                    res = self.call(E(1), [V(e.msg, tc)], pos)
                finally:
                    self.pc = saved
                return capc(res, tc) if tc < res.c else res
        if g in '∀μφ⇅⊞':
            lst = E(0)
            items = self.seq(lst, g, pos)
            fn = E(1)
            saved = self.pc
            self.pc = min(saved, lst.s)          # скільки разів виконується тіло — залежить від будови списку
            try:
                results = [self.each(g, i, fn, [x], pos) for i, x in enumerate(items)]
            finally:
                self.pc = saved
            if g == '∀':
                return V(None, min(self.pc, lst.s))
            if g == 'μ':
                return mk(results, lst.s)
            # відбір, порядок і групи залежать від результатів функції — це будова результату (s);
            # елемент, відібраний чи згрупований за власною умовою, ще й не впевненіший за неї
            m = min([lst.s] + [r.c for r in results])
            self.taint(m)
            if g == 'φ':
                conds = [self.boolean(r, g, pos) for r in results]
                return mk([capc(x, r.c) if r.c < x.c else x for x, r, ok in zip(items, results, conds) if ok], m)
            if g == '⇅':
                try:
                    order = sorted(range(len(items)), key=lambda i: sort_key(results[i]))
                except TypeError:
                    raise NgrError('⇅: ключі мають бути одного типу (числа або рядки)', pos)
                return mk([items[i] for i in order], m)
            groups = {}
            for x, r in zip(items, results):
                groups.setdefault(self.need(r, 'рядок', '⊞ (ключ)', pos), []).append(capc(x, r.c) if r.c < x.c else x)
            out = {k: mk(v, m) for k, v in groups.items()}
            return V(out, min([m] + [v.c for v in out.values()]), m)
        if g == 'Σ':
            lst, acc, fn = E(0), E(1), E(2)
            saved = self.pc
            self.pc = min(saved, lst.s)
            try:
                for i, x in enumerate(self.seq(lst, g, pos)):
                    acc = self.each(g, i, fn, [acc, x], pos)
            finally:
                self.pc = saved
            return capc(acc, lst.s) if lst.s < acc.c else acc
        if g == '↻':
            s, cond, stepf = E(0), E(1), E(2)
            cc, saved = 1.0, self.pc
            try:
                while True:
                    r = self.call(cond, [s], pos)
                    cc = min(cc, r.c)
                    self.taint(r.c)
                    if not self.boolean(r, g, pos):
                        break
                    self.pc = min(saved, cc)     # кожен наступний крок залежить від усіх перевірених умов
                    s = self.call(stepf, [s], pos)
            finally:
                self.pc = saved
            return capc(s, cc) if cc < s.c else s
        args = [E(i) for i in range(len(argn))]
        self.taint(min([1.0] + [a.c for a in args]))   # будь-яка операція може впасти — це видно ☂
        try:
            res = self.prim(g, args, pos)
        except Fatal:
            raise
        except NgrError as e:
            e.c = min([e.c, self.pc] + [a.c for a in args])
            raise
        if isinstance(res.v, (str, list, dict)) and len(res.v) > self.max_size:
            raise Fatal(f'{g}: значення завелике ({len(res.v)} > --розмір {self.max_size})', pos)
        if g not in ('≈', '±', '⚗', '►', '▶', '🜃', '🜍', '🜄', '§', '⌂', 'ρ', 'κ'):
            c = min([res.c] + [a.c for a in args])
            if isinstance(res.v, (list, dict)):        # вміст лишає свою впевненість; будова — від аргументів
                res = V(res.v, min(res.c, c), min([res.s] + [a.s for a in args]))
            elif c < res.c:
                res = V(res.v, c)
        return res

    def each(self, g, i, fn, args, pos):
        try:
            return self.call(fn, args, pos)
        except Fatal:
            raise
        except NgrError as e:
            if not e.where:
                e.msg, e.where = f'{g}, елемент №{i}: {e.msg}', True
            raise

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
            c = min(a[0].c, a[1].c)
            return V([V(i, c) for i in range(x, y + 1)], c)
        if g == 'ρ':
            if not isinstance(a[0].v, (str, list, dict)):
                raise NgrError(f'ρ: довжина буває в рядка, списку чи словника, а не в {kind(a[0])}', pos)
            return V(len(a[0].v), a[0].s)
        if g == '§':
            x, i = a[0].v, a[1].v
            if isinstance(x, dict):
                if not isinstance(i, str):
                    raise NgrError('§: ключ словника — рядок', pos)
                el = x.get(i, V(None, a[0].s))
            elif isinstance(x, (list, str)):
                if isinstance(i, bool) or not isinstance(i, int):
                    raise NgrError('§: індекс має бути цілим', pos)
                if not -len(x) <= i < len(x):
                    raise NgrError(f'§: індекс {i} поза межами (довжина {len(x)})', pos)
                el = x[i] if isinstance(x, list) else V(x[i], a[0].c)
            else:
                raise NgrError(f'§: очікувався список, рядок чи словник, а не {kind(a[0])}', pos)
            c = min(a[1].c, a[0].s)                   # який елемент узято — залежить від індексу й будови
            return capc(el, c) if c < el.c else el
        if g == '✎':
            d = dict(self.need(a[0], 'словник', g, pos))
            d[self.need(a[1], 'рядок', g, pos)] = a[2]
            return V(d)
        if g == 'κ':
            return V([V(k, a[0].s) for k in self.need(a[0], 'словник', g, pos)], a[0].s)
        if g == '↺':
            x = a[0].v
            if isinstance(x, (list, str)):
                return V(x[::-1])
            raise NgrError(f'↺: очікувався список або рядок, а не {kind(a[0])}', pos)
        if g == '↑':
            lst = self.need(a[0], 'список', g, pos)
            kinds = {kind(e) for e in lst}
            if not kinds <= {'число'} and not kinds <= {'рядок'}:
                raise NgrError(f'↑: сортувати можна лише самі числа або самі рядки, а тут {", ".join(sorted(kinds))}', pos)
            return V(sorted(lst, key=sort_key), a[0].c)
        if g == '✂':
            s, sep = self.need(a[0], 'рядок', g, pos), self.need(a[1], 'рядок', g, pos)
            c = min(a[0].c, a[1].c)
            return V([V(p, c) for p in (s.split(sep) if sep else s.split())], c)
        if g == '⁀':
            lst, sep = self.need(a[0], 'список', g, pos), self.need(a[1], 'рядок', g, pos)
            return V(sep.join(show(e) for e in lst))
        if g == 'σ':
            return V(show(a[0]))
        if g == 'ν':
            s = self.need(a[0], 'рядок', g, pos).strip().lstrip('\ufeff')
            s = ''.join(str(digit(ch)) if digit(ch) is not None else ch for ch in s).replace('·', '.').replace('¯', '-')
            try:
                return V(int(s))
            except ValueError:
                try:
                    return V(float(s))
                except ValueError:
                    raise NgrError(f'ν: «{s}» не число', pos)
        if g == 'δ':
            try:
                return wrap(json.loads(self.need(a[0], 'рядок', g, pos)), a[0].c)
            except ValueError as e:
                raise NgrError(f'δ: не JSON: {e}', pos)
        if g == 'Δ':
            return V(json.dumps(plain(a[0]), ensure_ascii=False))
        if g == '»':
            text = show(a[0])
            print(text, file=self.out, flush=True)
            self.trace('вивід', агент=self.agent, текст=trace_val(V(text)))
            return V(None)
        if g == '≈':
            c = n(1)
            if not 0 <= c <= 1:
                raise NgrError('≈: впевненість має бути від 0 до 1', pos)
            self.trace('впевненість', агент=self.agent, значення=trace_val(a[0]), було=a[0].c, стало=c)
            return capc(a[0], c)
        if g == '±':
            return V(a[0].c)
        if g == '⚗':
            lst, t = self.need(a[0], 'список', g, pos), n(1)
            if not 0 <= t <= 1:
                raise NgrError('⚗: поріг має бути від 0 до 1', pos)
            kept = []
            for x in lst:
                ok = x.c >= t
                self.trace('відсів', агент=self.agent, значення=trace_val(x), впевненість=x.c, поріг=t,
                           рішення='лишено' if ok else 'відкинуто')
                if ok:
                    kept.append(x)
            return mk(kept, a[0].s)
        if g == '🜄':
            key = self.need(a[0], 'рядок', g, pos)
            kc = min(a[0].c, self.pc)
            self.mem_c = min(self.mem_c, kc)       # сам факт запису під таким ключем — теж інформація
            val = capc(a[1], kc) if kc < a[1].c else a[1]
            self.memory[key] = val
            self.trace('памʼять', агент=self.agent, дія='запамʼятати', ключ=key, значення=trace_val(val), впевненість=val.c)
            return V(None, self.pc)
        if g == '🜃':
            key = self.need(a[0], 'рядок', g, pos)
            res = self.memory.get(key, V(None))
            c = min(a[0].c, self.mem_c, self.pc)  # і знайдене, і відсутнє залежить від того, як писали
            res = capc(res, c) if c < res.c else res
            self.trace('памʼять', агент=self.agent, дія='пригадати', ключ=key, значення=trace_val(res), впевненість=res.c)
            return res
        if g == '🜍':
            r = self.call(a[1], [a[0]], pos)
            ok = self.boolean(r, g, pos)
            self.taint(r.c)                          # пройде чи впаде — залежить від умови
            self.trace('перевірка', агент=self.agent, значення=trace_val(a[0]), результат='пройдена' if ok else 'НЕ пройдена',
                       впевненість=r.c)
            if not ok:
                raise NgrError(f'🜍: перевірку не пройдено для {brief(a[0], 60)}', pos, min(r.c, a[0].c, self.pc))
            return capc(a[0], r.c) if r.c < a[0].c else a[0]
        if g == '∋':
            x, y = a[0].v, a[1]
            if isinstance(x, str):
                return V(self.need(y, 'рядок', g, pos) in x)
            if isinstance(x, list):
                return V(any(deep_eq(e, y) for e in x))
            if isinstance(x, dict):
                return V(self.need(y, 'рядок', g, pos) in x)
            raise NgrError(f'∋: очікувався рядок, список чи словник, а не {kind(a[0])}', pos)
        if g == '⇄':
            return V(self.need(a[0], 'рядок', g, pos).replace(self.need(a[1], 'рядок', g, pos),
                                                              self.need(a[2], 'рядок', g, pos)))
        if g == '⊢':
            return V(self.need(a[0], 'рядок', g, pos).strip().strip('\ufeff\u200b').strip())
        if g in '≅⌗':
            x, k = n(0), n(1)
            if isinstance(k, bool) or not isinstance(k, int) or not 0 <= k <= 12:
                raise NgrError(f'{g}: кількість знаків — ціле від 0 до 12', pos)
            q = Decimal(repr(x)).quantize(Decimal(1).scaleb(-k), rounding=ROUND_HALF_UP)
            if g == '⌗':
                return V(format(q, 'f'))
            return V(int(q) if k == 0 else float(q))
        if g == '⌂':
            return V([V(x) for x in self.argv])
        raise NgrError(f'гліф «{g}» не реалізовано', pos)


# ------------------------------------------------------------------ розбір для людини


def explain(node, ind=0):
    """Перекласти дерево програми українським псевдокодом."""
    pad = '  ' * ind
    k = node[0]
    if k == 'lit':
        v = node[2]
        if isinstance(v, str):
            return '«' + safe(v) + '»'
        return show(V(v))
    if k == 'var':
        return node[2]
    if k == 'op' and node[2] == '⌂':
        return 'аргументи програми'
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
        inner = ', '.join(explain(a, ind) for a in node[3])
        if len(node[3]) == 1 and inner.startswith('(') and inner.endswith(')'):
            inner = inner[1:-1]
        return f'{node[2]}({inner})'
    if k == 'seal':
        caps = '; '.join(t + (f' [{", ".join(s)}]' if s else '') for t, s in node[3].items()) or 'жодних'
        return f'ПЕЧАТКА — намір: «{safe(node[2])}»; дозволи: {caps}'
    if k == 'tool':
        return f'інструмент {node[2]}({", ".join(explain(a, ind) for a in node[3])})'
    if k == 'deleg':
        caps = ', '.join(t + (f' [{", ".join(s)}]' if s else '') for t, s in node[4].items()) or 'жодних'
        return (f'субагент «{safe(node[2])}» (намір «{safe(node[3])}»; дозволи: {caps}) виконує:\n'
                f'{pad}  {explain(node[5], ind + 1)}')
    g, args = node[2], node[3]
    tmpl = GLYPHS[g][3]
    parts = [explain(a, ind) if f'({{{i}}})' in tmpl else par(a, explain(a, ind)) for i, a in enumerate(args)]
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


def par(node, text):
    """Складений підвираз — у дужках, щоб переклад читався однозначно."""
    if node[0] in ('op', 'call', 'tool') and not (text.startswith('(') and text.endswith(')')) and ' ' in text \
            and '\n' not in text:
        return f'({text})'
    return text


def explain_program(prog):
    return '\n'.join(explain(s) for s in prog[2])


def seal_report(prog, allowed, source, cwd):
    def scopes(t, sc):
        if TOOLS[t][4] == 'тека':
            return ', '.join(os.path.realpath(os.path.join(cwd, x)) for x in sc)
        return ', '.join(safe(x) for x in sc)

    seal = prog[2][0]
    lines = ['ПЕЧАТКА', f'  намір: «{safe(seal[2])}»', '  дозволи:']
    for t, sc in seal[3].items():
        lines.append(f'    {t}' + (f' → {scopes(t, sc)}' if sc else '') + f'   ({TOOLS[t][2]})')
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
        caps = '; '.join(t + (f' → {scopes(t, sc)}' if sc else '') for t, sc in d[4].items()) or 'жодних'
        lines.append(f'  субагент «{safe(d[2])}»: намір «{safe(d[3])}», дозволи: {caps}')
    missing = check_allowlist(seal[3], allowed, cwd)
    lines.append(f'  дозволи власника: {source}')
    lines.append('  ✓ печатка в межах дозволів власника' if not missing else f'  ✗ бракує дозволу власника: {", ".join(missing)}')
    lines.append('  (права перевіряються й під час виконання: кожен інструмент — лише в межах агента, що його викликає)')
    return '\n'.join(lines)


# ------------------------------------------------------------------ памʼятка


def cheatsheet():
    out = [f'# Nigredo {VERSION} — памʼятка для агентів', '',
           '_Згенеровано з інтерпретатора: `ngr --памʼятка`. Повна специфікація — `spec/SPEC.md`._', '',
           '## Як це влаштовано', '',
           '- **Префіксний запис з фіксованою арністю**: гліф, потім рівно стільки аргументів, скільки він бере.',
           '  `＋ 2 3` → 5; `» × 2 ＋ 3 4` → 14. Дужок для групування не треба: арність однозначна.',
           '- **Кінець рядка завершує вираз.** Бракує аргументу в кінці рядка — помилка до запуску. Довгий вираз',
           '  продовжуйте на наступних рядках **з більшим відступом**; усередині `【】` і `『』` перенос вільний.',
           '  Зайве після завершеного виразу — теж помилка. Кілька виразів в одному рядку — через `¦`.',
           '- **Значення не змінюються**: `← імʼя вираз` називає назавжди, і лише на початку інструкції',
           '  (усередині виразу — блок `《 ← … 》`). Цикли — `∀ μ φ Σ ↻`.',
           '- Імена — слова будь-якою мовою, але **одним письмом** (`звiт` з латинською i — помилка). Грецькі літери — гліфи.',
           '- Умови — лише `●` (так) або `○` (ні); `∅` — ніщо. Числа — цифрами одного письма, мінус — `¯5`.',
           '- Рядок `「…」` (екранування `\\」 \\n`), список `【…】`, словник `『ключ значення …』`, блок `《…》` (значення — останній вираз).',
           '  JSON: `true/false/null` ↔ `●/○/∅`. `§` словника без такого ключа дає `∅`. Значення верхнього рівня без `»` нікуди не йде.',
           '- Коментар — `※` до кінця рядка. Відносні шляхи — від теки файлу програми.',
           '- **Кожне значення має впевненість** (типово 1). Усе, що обчислено з даних, не впевненіше за них —',
           '  і через операції, і через **керування**: значення, створене під сумнівною умовою `¿`, у циклі `↻`,',
           '  у функції, обраній сумнівно, після сумнівної перевірки `🜍` чи в `☂`, несе цю сумнівність.',
           '  Відібране `φ`, упорядковане `⇅`, згруповане `⊞`, пригадане `🜃` за сумнівним ключем — теж.',
           '  Список має дві міри: впевненість вмісту й **будови** (які елементи, скільки, в якому порядку);',
           '  `ρ`, `§`, цикли зважають на будову. Змінити впевненість можна лише `≈`, і це записується в слід.',
           '', '## Печатка (обовʼязкова)', '',
           'Перший рядок кожної програми — `🜂 「намір」 【「дозвіл」 …】`. Інструмент, якого нема в печатці,',
           'не пройде розбір; під час виконання кожен виклик ще раз звіряється з дозволами агента, що його робить.',
           'Печатка має вкладатися в дозволи власника (`~/.nigredo/дозволи.json`: «дозволено» — для всіх програм,',
           '«для_тек» — лише для програм у певній теці; `--дозволи` може їх лише звузити), інакше програма не',
           'запуститься. Власник бачить печатку командою `ngr --печатка файл.ngr`.', '',
           '```', '🜂 「порахувати слова у звітах」 【「файл.читати:звіти」 「файл.писати:вихід」】', '```', '',
           'Дозвіл для файлів — тека (і все в ній); для мережі — хост (порти 80/443) або `хост:порт`;',
           'для агента — імʼя з реєстру. Теку власника (`~/.nigredo`) дозволити не можна.', '',
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
            '```', '🜂 「групування, гроші, абетка」 【】',
            '← продажі 【『「місто」 「Хотин」 「сума」 70』 『「місто」 「Київ」 「сума」 99.5』 『「місто」 「Хотин」 「сума」 830.25』】',
            '← групи ⊞ продажі λp §p 「місто」',
            '∀ ↑κгрупи λм » ＋ м ＋ 「: 」 ⌗ Σ §групи м 0 Λa p ＋a §p 「сума」 2', '```', '',
            '## Пастки', '',
            '- `＝0 ‰n 3` — спершу гліф, потім аргументи: «остача n на 3 дорівнює 0».',
            '- Імена склеюються з цифрами: `n15` — одне імʼя; пишіть `n 15`.',
            '- `＋` зʼєднує рядки лише з рядками: `＋「№」 σn`.',
            '- Функцію, названу `←`, викликають просто: `факт 10`; передати як значення — `∘факт`.',
            '  Функцію-значення (параметр) викликають `► f x`.',
            '- `✂ рядок 「」` ріже за пробілами. `↑` сортує рядки за українською абеткою.',
            '- Дробові числа друкуються точно (`＋ 0.1 0.2` → `0.30000000000000004`); для грошей — `≅ x 2` і `⌗ x 2`.',
            '- Субагент бачить імена батька лише для читання (змінити їх неможливо взагалі) і має власну памʼять.',
            '- Ціна в токенах: кириличне імʼя коштує в 3–8 разів більше за коротке латинське (`відповіді` — 8 токенів,',
            '  `ans` — 1). Для економії беріть короткі імена; рядки й коментарі — будь-якою мовою.',
            '',
            '## Чесно про межі', '',
            '- **Nigredo — інструмент прозорості й аудиту, а не пісочниця.** Інтерпретатор гарантує, що *програма*',
            '  не зробить нічого поза печаткою і не допише, не змінить і не обріже свій слід непомітно. Але *агент*,',
            '  що має shell, може обійти Nigredo взагалі чи змінити `~/.nigredo` (дозволи, ключ сліду). Від такого',
            '  агента захищають права процесу й пісочниця ОС, а не мова.',
            '- Впевненість відстежується через дані й керування, але це консервативна оцінка, а не ймовірність.',
            '- Ліміти: `--кроки` (обчислення), `--розмір` (найбільший рядок/список), глибина рекурсії.',
            '- `оракул` — імітація; `агент` — справжній виклик Claude (коштує грошей і часу).',
            '- Порівняно з Python: без печатки — приблизно стільки ж токенів; печатка додає фіксовану ціну.',
            '',
            '## Прозорість', '',
            '- `ngr --печатка файл.ngr` — що програмі дозволено, ще до запуску.',
            '- `ngr --розбір файл.ngr` — переклад українським псевдокодом.',
            '- **Слід ведеться завжди** — у `~/.nigredo/сліди/`, куди програма не має доступу; `--слід ФАЙЛ` — ще одна',
            '  копія (новий файл, не в теці запису програми). Печатка, кожен інструмент повністю, відмови, делегування,',
            '  памʼять, перевірки, відсів, впевненість, вивід; спроба без дозволу — запис «заборонено». Записи',
            '  підписано ключем власника (HMAC) і зчеплено; `ngr --перевірити-слід ФАЙЛ` виявить зміну, вставку чи',
            '  обрізання (завершальні записи — лише «кінець», «помилка» або «відмова» на старті).', '']
    return '\n'.join(out)


def cheatsheet_short():
    """Стисла памʼятка для контексту агента (MCP-опис, ~1–1.5 тис. токенів)."""
    lines = [f'Nigredo {VERSION}: префіксний запис, фіксована арність, 1 рядок = 1 вираз (продовження — більший відступ, ¦ — розділювач).',
             'Перший рядок — ПЕЧАТКА: 🜂 「намір」 【「дозвіл」 …】; дозволи: 「оракул」 「жереб」 「час」 「файл.читати:тека」',
             '「файл.писати:тека」 「файл.список:тека」 「мережа.взяти:хост」 「агент:імʼя」. Поза печаткою — помилка до запуску.',
             'Рядок 「…」 (\\n \\」), список 【…】, словник 『к з …』, блок 《…》, коментар ※, так/ні/ніщо ● ○ ∅, мінус ¯5.',
             'Імена — слова одного письма; ← імʼя вираз (лише на початку інструкції, назавжди). Умови — лише ●/○.',
             'Гліфи (арність через сигнатуру):']
    for g, (ar, sig, desc, _, grp) in GLYPHS.items():
        lines.append(f'  {sig} — {desc}')
    lines.append('Інструменти: ' + '; '.join(TOOLS[t][1] for t in TOOLS))
    lines += ['Приклад: 🜂 「сума чисел」 【「файл.читати:дані」】 ¦ ← n δ🜔файл.читати 「дані/x.json」 ¦ » Σ n 0 Λa x ＋a x',
              'Впевненість: усе з даних і під сумнівними умовами не впевненіше за джерело; змінити — лише ≈ (у слід).',
              'Слід веде інтерпретатор (підписаний). Nigredo — прозорість і аудит, не пісочниця ОС.']
    return '\n'.join(lines)


# ------------------------------------------------------------------ командний рядок

USAGE = f"""Nigredo {VERSION}
  ngr ФАЙЛ.ngr | -e КОД  [-- аргументи програми]
    --печатка              що програмі дозволено (без виконання)
    --розбір               переклад українським псевдокодом (без виконання)
    --слід ФАЙЛ|-          де ще вести слід (новий файл; - = stderr); слід ведеться завжди
                           у {OWNER_HOME}/сліди/
    --дозволи ФАЙЛ         звузити дозволи власника ({OWNER_HOME}/дозволи.json)
    --зерно N              зерно для «жереб» (типово 0)
    --кроки N              ліміт кроків (типово {DEFAULT_STEPS})
    --розмір N             найбільший рядок/список (типово {MAX_SIZE})
  ngr --перевірити-слід ФАЙЛ
  ngr --памʼятка           згенерувати памʼятку для агентів
"""


def main(argv):
    opts = {'mode': 'run', 'trace': None, 'allow': None, 'seed': 0, 'steps': DEFAULT_STEPS, 'size': MAX_SIZE}
    src = path = None
    prog_args = []
    it = iter(argv)
    for a in it:
        if a in ('-h', '--help'):
            print(USAGE)
            return 0
        if a == '--':
            prog_args = list(it)
            break
        if a == '--памʼятка':
            print(cheatsheet())
            return 0
        if a == '--памʼятка-коротка':
            print(cheatsheet_short())
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
        elif a == '--розмір':
            opts['size'] = int(next(it))
        elif a == '-e':
            src, path = next(it), '<-e>'
        else:
            path = a
            try:
                src = open(a, encoding='utf-8').read()
            except (OSError, UnicodeDecodeError) as e:
                print(f'✗ {a}: {getattr(e, "strerror", None) or e}', file=sys.stderr)
                return 2
    if src is None:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        prog = parse(src)
    except StaticError as e:
        print(e, file=sys.stderr)
        return 2
    # шляхи в печатці й інструментах — відносно теки програми (для -e — поточної теки)
    cwd = os.getcwd() if path == '<-e>' else os.path.dirname(os.path.abspath(path))
    try:
        allowed, source = load_allowlist(opts['allow'], cwd)
    except Refused as e:
        print(e, file=sys.stderr)
        return 3
    if opts['mode'] == 'розбір':
        print(explain_program(prog))
        return 0
    if opts['mode'] == 'печатка':
        print(seal_report(prog, allowed, source, cwd))
        return 0
    missing = check_allowlist(prog[2][0][3], allowed, cwd)
    sha = hashlib.sha256(src.encode()).hexdigest()
    key = owner_key()
    os.makedirs(os.path.join(OWNER_HOME, 'сліди'), mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    main_trace = os.path.join(OWNER_HOME, 'сліди', f'{stamp}-{sha[:8]}-{os.getpid()}.jsonl')
    paths = [main_trace]
    extra_stderr = opts['trace'] == '-'
    if opts['trace'] and not extra_stderr:
        paths.append(os.path.realpath(opts['trace']))
    write_scopes = prog[2][0][3].get('файл.писати', [])
    for tp in paths[1:]:
        if any(inside(tp, os.path.join(cwd, w)) for w in write_scopes):
            print(f'✗ слід «{tp}» лежить у теці, куди програмі дозволено писати — оберіть інше місце',
                  file=sys.stderr)
            return 3
    outs = []
    try:
        for tp in paths:
            outs.append(open(tp, 'x', encoding='utf-8'))
    except FileExistsError as e:
        print(f'✗ файл сліду вже існує ({e.filename}) — слід не перезаписується', file=sys.stderr)
        return 3
    except OSError as e:
        print(f'✗ не вдалося створити слід: {e}', file=sys.stderr)
        return 3
    if extra_stderr:
        outs.append(sys.stderr)
    trace = Trace(outs, key)
    code = 0
    try:
        trace('початок', версія=VERSION, програма=path, sha256=sha[:16], аргументи=prog_args,
              дозволи_власника=source, дозволено=allowed)
        if missing:
            trace('відмова', бракує=missing)
            print(f'✗ печатка просить більше, ніж дозволив власник: {", ".join(missing)}\n'
                  f'  дозволи власника: {source}', file=sys.stderr)
            return 3
        interp = Interp(trace, seed=opts['seed'], steps=opts['steps'], cwd=cwd, argv=prog_args, protected=paths,
                        max_size=opts['size'])
        try:
            interp.run(prog)
            trace('кінець', кроків=opts['steps'] - interp.steps_left)
        except NgrError as e:
            trace('помилка', повідомлення=safe(str(e)))
            print(e, file=sys.stderr)
            code = 1
        except Exception as e:                       # вада інтерпретатора: чесно, без трасування Python
            trace('помилка', внутрішня=True, повідомлення=f'{type(e).__name__}: {e}')
            print(f'✗ внутрішня помилка інтерпретатора Nigredo ({type(e).__name__}: {e}) — це вада мови, '
                  f'не програми; слід: {main_trace}', file=sys.stderr)
            code = 4
        return code
    finally:
        for o in outs:
            if o is not sys.stderr:
                o.close()


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
