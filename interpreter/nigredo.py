#!/usr/bin/env python3
"""Nigredo 0.2 — еталонний інтерпретатор.

Специфікація: spec/SPEC.md. Без залежностей, Python ≥ 3.10.
Таблиці GLYPHS і TOOLS нижче — єдине джерело правди: з них генеруються
памʼятка (`--памʼятка`) і переклад (`--розбір`).
"""
import functools
import hashlib
import hmac
import json
import os
import random
import sys
import threading
import unicodedata
from datetime import datetime, timezone
import decimal
import math
from decimal import ROUND_HALF_UP, Decimal

VERSION = '0.6-dev'
MAX_DEPTH = 2000
MAX_SIZE = 5_000_000      # найбільший логічний розмір значення (символів + елементів); --розмір N
ALLOC_FACTOR = 20         # сумарно за запуск можна створити не більше ALLOC_FACTOR × --розмір
MAX_INT_BITS = 100_000    # найбільше ціле (≈ 30 000 десяткових цифр)
MAX_TRACE = 50_000_000    # найбільший слід у байтах; --слід-розмір N
HEAVY = set('＝≠σΔ⁀∋↑⇅⊞≈⇣⇡⊳⌕≋')  # робота пропорційна розміру — і кроки теж
if hasattr(sys, 'set_int_max_str_digits'):
    sys.set_int_max_str_digits(0)
DEFAULT_STEPS = 10_000_000
OWNER_HOME = os.path.realpath(os.path.expanduser(os.environ.get('NIGREDO_HOME', '~/.nigredo')))
# реєстр агентів для інструмента «агент»: {"agents": [{"name": …, "path": …}]}
AGENTS_REGISTRY = os.environ.get('NIGREDO_AGENTS', os.path.join(OWNER_HOME, 'агенти.json'))
DEFAULT_ALLOWED = ['оракул', 'жереб', 'час']



class NgrError(Exception):
    """Помилка програми: її можна перехопити ☂. c — впевненість даних, через які вона сталася."""

    def __init__(self, msg, pos=None, c=1.0):
        super().__init__(msg)
        self.msg, self.pos, self.c, self.where, self.file = msg, pos, c, False, None

    def __str__(self):
        where = (f'{self.file}:' if self.file else '') + (f'{self.pos[0]}:{self.pos[1]} ' if self.pos else '')
        return f'✗ {where}{self.msg}'


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
    'λ': (None, 'λ x тіло', 'функція одного аргументу; λ【k v】 — розібрати список-пару (рівно стільки елементів)',
          'функція ({p}) ↦ {0}', 'імена'),
    'Λ': (None, 'Λ a b тіло', 'функція двох аргументів', 'функція ({p}) ↦ {0}', 'імена'),
    '⊃': (None, '⊃ 「модуль.ngr」 【「імʼя」 …】', 'взяти названі значення з модуля (лише на початку інструкції верхнього '
          'рівня; печатка модуля ⊆ печатки програми)', 'з модуля {0} взяти {1}', 'імена'),
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
    '‖': (2, '‖ список λx 🜔інструмент …', 'паралельно: для кожного елемента — один виклик інструмента (мережа, агент, '
          'процес, читання); аргументи — по черзі, дії — разом (до 8), результати й слід — у порядку елементів',
          'паралельно для кожного з {0}: {1}', 'керування'),
    'φ': (2, 'φ список λx умова', 'лишити елементи, для яких умова ● (filter)', 'з {0} лишити ті, де {1}', 'керування'),
    'Σ': (3, 'Σ список початок Λa x тіло', 'згорнути (reduce): a ← тіло для кожного x', 'згорнути {0} від {1}: {2}', 'керування'),
    '∫': (2, '∫ список λx число', 'сума: для кожного елемента — число, усе додати точно', 'сума по {0}: {1}', 'керування'),
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
    'ε': (1, 'ε словник', 'пари 【ключ значення】 (у порядку ключів); з розбором: μ εd λ【k v】 …', 'пари({0})', 'дані'),
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
    '⇣': (1, '⇣ рядок', 'малими літерами', 'малими({0})', 'дані'),
    '◷': (2, '◷ дата дата або ◷ дата дні', 'дати ISO (2026-10-15, 2026-10-15T09:30:00+03:00): дві дати — скільки днів від першої '
          'до другої (дріб, якщо є час); дата й число — дата через стільки днів', 'дати({0}, {1})', 'дані'),
    '▦': (1, '▦ текст', 'CSV → список словників (перший рядок — заголовки; значення — рядки)', 'csv({0})', 'дані'),
    '✓': (2, '✓ значення схема', 'перевірити за схемою й повернути значення (інакше — помилка з усіма розбіжностями). '
          'Схема: 「число」 「ціле」 「рядок」 「дата」 「●/○」 「∅」 「будь-що」 「список」 「словник」; …? — ще й ∅; '
          '「число:0..100」 межі (рядок, список — довжина); 「рядок:a|b」 перелік; 【S】 — кожен елемент; '
          '『「поле」 S 「поле?」 S』 — поля (зайві — помилка; 「…」 「будь-що」 — дозволити інші)', 'перевірене({0} за схемою {1})', 'дані'),
    'χ': (1, 'χ текст | χ елемент', 'XML: рядок → елемент 『「тег」 … 「атрибути」 『…』 「текст」 … 「діти」 【…】』 (простори імен '
          'знято з тегів; DTD і сутності — заборонено); елемент → рядок XML (назви — лише XML Name)', 'xml({0})', 'дані'),
    '↘': (2, '↘ елемент 「шлях」', 'XPath-підмножина: a/b — діти, //b — будь-де нижче, * — будь-який, [@атр=\'x\'] '
          '[дитина=\'x\'] [n] — відбір, …/@атр — значення атрибутів; /a… — від самого елемента. → список вузлів '
          'без повторів, у порядку документа; інше (.., text(), !=) — помилка',
          'знайти в {0} шлях {1}', 'дані'),
    '⇡': (1, '⇡ рядок', 'великими літерами', 'великими({0})', 'дані'),
    '⊏': (3, '⊏ x від до', 'зріз рядка чи списку [від, до); відʼємні — з кінця; до ∅ — до кінця', '{0}[{1}…{2}]', 'дані'),
    '⊳': (2, '⊳ x що', 'позиція підрядка в рядку чи елемента в списку; ¯1 — немає', 'позиція {1} у {0}', 'дані'),
    '⌕': (2, '⌕ рядок шаблон', 'усі збіги регулярного виразу (з групами — списки груп)', 'усі збіги {1} у {0}', 'дані'),
    '≋': (3, '≋ рядок шаблон заміна', 'замінити збіги регулярного виразу (\\1 — група)', 'у {0} замінити збіги {1} на {2}', 'дані'),
    '⇅': (2, '⇅ список λx ключ', 'відсортувати за ключем (рядки — за українською абеткою)', 'відсортувати {0} за {1}', 'дані'),
    '⊞': (2, '⊞ список λx ключ', 'згрупувати: словник ключ-рядок → список елементів', 'згрупувати {0} за {1}', 'дані'),
    '№': (2, '№ список λx ключ', 'порахувати: словник ключ-рядок → скільки елементів (у порядку появи)',
          'порахувати {0} за {1}', 'дані'),
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
TMPL_OPEN, TMPL_CLOSE = '〔', '〕'      # шаблонний рядок: 〔текст {вираз} текст〕
GREEK = range(0x0370, 0x0400)
ASCII_HINTS = {
    '+': '＋', '-': '－ (або ¯ перед числом)', '*': '×', '/': '÷', '=': '＝', '<': '‹', '>': '›',
    '%': '‰', '!': '¬', '&': '∧', '|': '∨', '(': '《 … 》', ')': '《 … 》', '[': '【 … 】', ']': '【 … 】',
    '{': '『 … 』', '}': '『 … 』', '"': '「 … 」', "'": '「 … 」', '#': '※', ';': '¦', ':': '←',
    'µ': 'μ (грецька мю)', '−': '－', '’': 'ʼ', '＞': '›', '＜': '‹', '.': '… (ряд) або 0.5 (дріб)',
    '@': '∘ (функція як значення)', '«': '「 … 」', '»': '» (це друк; рядок — 「 … 」)',
    '✔': '✓ (перевірити за схемою)', '∈': '∋ (чи містить: ∋ x y)', 'ϵ': 'ε (пари словника) або ∋ (чи містить)', '∑': '∫ (сума: ∫ xs λx число) або Σ (згортка)',
    '∥': '‖ (паралельно)', '∏': 'Σ з × (добуток: Σ xs 1 Λa x ×a x)',
}

# ------------------------------------------------------------------ значення


class V:
    """Значення з впевненістю c ∈ [0, 1]. Для списку/словника/рядка c — мінімум вмісту,
    а s — впевненість будови: які елементи є, скільки їх і в якому порядку."""
    __slots__ = ('v', 'c', 's', 'n')

    def __init__(self, v, c=1.0, s=None):
        self.v, self.c = v, c
        self.s = c if s is None else s
        # логічний розмір (спільні посилання рахуються стільки разів, скільки трапляються); точний тип — швидко
        t = type(v)
        if t is int:
            self.n = 1 + v.bit_length() // 3            # ≈ десяткових цифр
        elif t is str:
            self.n = len(v) + 1
        elif t is list:
            self.n = 1 + sum(e.n for e in v)
        elif t is dict:
            self.n = 1 + sum(len(k) + e.n for k, e in v.items())
        elif t is Decimal and v.is_finite():
            self.n = 1 + abs(v.adjusted()) + len(v.as_tuple().digits)
        else:
            self.n = 1


class Fn:
    __slots__ = ('params', 'body', 'env', 'name', 'mod', 'simple')

    def __init__(self, params, body, env, name=None):
        self.params, self.body, self.env, self.name = params, body, env, name
        self.simple = all(isinstance(p, str) for p in params)   # без розбору 【a b】 — швидкий виклик
        e = env                                   # функція модуля: (шлях, печатка модуля) — права при виклику
        while e is not None and '\0модуль' not in e:
            e = e.get('\0parent')
        self.mod = e['\0модуль'] if e is not None else None


def kind(x):
    v = x.v
    if v is None:
        return 'ніщо'
    if isinstance(v, bool):
        return 'істинність'
    if isinstance(v, NUM):
        return 'число'
    if isinstance(v, str):
        return 'рядок'
    if isinstance(v, list):
        return 'список'
    if isinstance(v, dict):
        return 'словник'
    return 'функція'


try:
    INTERP_SHA = hashlib.sha256(open(os.path.realpath(__file__), 'rb').read()).hexdigest()   # яким кодом зроблено слід
except OSError:
    INTERP_SHA = None
NUM = (int, float, Decimal)
DEC_EXP = 30_000            # найбільший порядок десяткового (як і ціле — до ~30 тис. цифр)
DEC_CTX = decimal.Context(prec=28, Emax=DEC_EXP, Emin=-DEC_EXP,              # ÷: 28 значущих цифр
                          traps=[decimal.InvalidOperation, decimal.DivisionByZero, decimal.Overflow])
WIDE_CTX = decimal.Context(prec=2 * DEC_EXP + 40, Emax=DEC_EXP + 20, Emin=-DEC_EXP - 20)   # ≅ ⌗: без втрати цифр
EXACT_CTX = decimal.Context(prec=60, Emax=DEC_EXP, Emin=-DEC_EXP,            # ＋ － ×: точно або помилка
                            traps=[decimal.InvalidOperation, decimal.DivisionByZero, decimal.Overflow, decimal.Inexact])


def dec_ok(d, what, pos):
    """Десяткове з даних: скінченне й з порядком у межах — інакше помилка програми (а не зависання чи код 4)."""
    if not d.is_finite():
        raise NgrError(f'{what}: «{d}» — не число', pos)
    if abs(d.adjusted()) > DEC_EXP:
        raise NgrError(f'{what}: порядок числа понад {DEC_EXP} цифр', pos)
    return d      # дробові числа мови — точні десяткові (Decimal); float — лише впевненість (±)


def fmt_num(n):
    if isinstance(n, Decimal):          # як число, а не запис: 1300.0 → 1300, 2.50 → 2.5 (знаки для грошей — ⌗)
        t = format(n, 'f')              # точно, без округлення до точності контексту (normalize() округлював до 28 цифр)
        t = t.rstrip('0').rstrip('.') if '.' in t else t
        return '0' if t == '-0' else t
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
    if isinstance(v, NUM):
        return fmt_num(v)
    if isinstance(v, list):
        return '【' + ' '.join(show(e, False) for e in v) + '】'
    if isinstance(v, dict):
        return '『' + ' '.join(f'{show(V(k), False)} {show(e, False)}' for k, e in v.items()) + '』'
    return f'λ{v.name or ""}'


def to_json(x):
    """JSON без втрат: десяткові пишуться числом JSON точно (без float)."""
    v = x.v
    if isinstance(v, list):
        return '[' + ', '.join(to_json(e) for e in v) + ']'
    if isinstance(v, dict):
        return '{' + ', '.join(f'{json.dumps(k, ensure_ascii=False)}: {to_json(e)}' for k, e in v.items()) + '}'
    if isinstance(v, Decimal):
        return fmt_num(v)
    if isinstance(v, Fn):
        return '"λ"'
    return json.dumps(v, ensure_ascii=False)


def plain(x):
    """У Python-значення (для JSON і сліду)."""
    v = x.v
    if isinstance(v, list):
        return [plain(e) for e in v]
    if isinstance(v, dict):
        return {k: plain(e) for k, e in v.items()}
    if isinstance(v, Fn):
        return 'λ'
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() and abs(v) < 10 ** 15 else float(v)
    return v


def wrap(p, c=1.0):
    if isinstance(p, str) and any(0xD800 <= ord(ch) <= 0xDFFF for ch in p):
        raise ValueError('у рядку неповний символ (сурогат)')
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
    """Ключ сортування: числа, рядки (українська абетка) і списки з них — поелементно (складений ключ)."""
    v = e.v
    if isinstance(v, str):
        return (1, [(UA_ORDER.get(ch, 100 + ord(ch)), ch) for ch in v.casefold()], v)
    if isinstance(v, list):
        return (2, [sort_key(x) for x in v])
    return (0, v)


FILLERS = set('ㅤᅟᅠﾠ⠀')
# Default_Ignorable_Code_Point з Unicode (DerivedCoreProperties): невидимі, навіть коли категорія — літера чи знак
IGNORABLE = ((0x00AD, 0x00AD), (0x034F, 0x034F), (0x061C, 0x061C), (0x115F, 0x1160), (0x17B4, 0x17B5),
             (0x180B, 0x180F), (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F), (0x3164, 0x3164),
             (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF), (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8), (0x1BCA0, 0x1BCA3),
             (0x1D173, 0x1D17A), (0xE0000, 0xE0FFF))


@functools.lru_cache(maxsize=65536)
def invisible(ch):
    """Одне правило видимості для всієї мови: керівні, форматні, роздільники рядків, приватні, непризначені,
    сурогати, Default_Ignorable (U+034F, теги U+E00xx, ZWSP…), нестандартні пробіли, заповнювачі (U+3164, U+2800)."""
    o, cat = ord(ch), unicodedata.category(ch)
    return (cat in ('Cc', 'Cf', 'Zl', 'Zp', 'Co', 'Cn', 'Cs') or (cat == 'Zs' and ch != ' ') or ch in FILLERS
            or any(a <= o <= b for a, b in IGNORABLE))


def hidden(text, allow='\n\t'):
    """Невидимі символи тексту (крім allow). Селектор вигляду емодзі (U+FE0E/F) одразу після значка — видимий."""
    if not any(invisible(ch) for ch in set(text) if ch not in allow):   # швидко: різних символів зазвичай мало
        return []
    return [ch for i, ch in enumerate(text) if ch not in allow and invisible(ch)
            and not (ch in '︎️' and i and unicodedata.category(text[i - 1]) == 'So')]


def visible(text, allow='\n\t', bracket=True):
    """Текст для виводу й сліду: кожен невидимий символ (крім allow) — як ⟨U+XXXX⟩; прихованого каналу немає.
    bracket=False — для тексту, який уже пройшов visible (MCP): не екранувати позначки вдруге."""
    bad = set(hidden(text, allow))
    if bracket and '⟨' in text:                  # справжній ⟨ — теж кодом: «⟨U+200B⟩» у тексті ≠ невидимий U+200B (суд 7)
        bad.add('⟨')
    return ''.join(f'⟨U+{ord(ch):04X}⟩' if ch in bad else ch for ch in text) if bad else text


def safe(s):
    """Для виводу людині: новий рядок і табуляція — ↵ ⇥, решта невидимого — ⟨U+XXXX⟩."""
    bad = set(hidden(s, ''))
    return ''.join({'\n': '↵', '\t': '⇥'}.get(ch, f'⟨U+{ord(ch):04X}⟩') if ch in bad else ch for ch in s)


def deep_eq(a, b):
    if a is b:
        return True
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
    return is_name_start(ch) or unicodedata.category(ch) == 'Nd' or ch in 'ʼ\''


def digit(ch):
    return unicodedata.decimal(ch, None)


def script_of(ch):
    """Письмо символу за назвою Unicode: LATIN, CYRILLIC, RUNIC, FULLWIDTH, ARABIC-INDIC …"""
    name = unicodedata.name(ch, '')
    if unicodedata.category(ch) == 'Nd':
        return name.split('DIGIT')[0].strip() or 'ASCII'
    return name.split(' ')[0]


DIGIT_LIKE = str.maketrans('ОOЗБ', '0036')
NAME_SCRIPTS = {'LATIN', 'CYRILLIC', 'CJK', 'HIRAGANA', 'KATAKANA', 'HANGUL', 'ARABIC', 'HEBREW', 'DEVANAGARI',
                'BENGALI', 'TAMIL', 'THAI', 'GEORGIAN'}     # мала o — звичне імʼя змінної, лишаємо (мірило)
_CONFUSABLES = {}


def confusables():
    """Таблиця UTS #39 (interpreter/двійники.tsv): символ → коди скелета (hex), як він виглядає. Коди в символи
    перетворюються лише для тих символів, що трапилися в іменах (запуск не платить за всю таблицю)."""
    if not _CONFUSABLES:
        path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'двійники.tsv')
        try:
            text = open(path, encoding='utf-8').read()
        except OSError as e:
            raise Fatal(f'немає таблиці двійників {path}: {e.strerror} — без неї двійників не відловити')
        for line in text.split('\n'):
            if line and line[0] != '#':
                k, _, v = line.partition('\t')
                _CONFUSABLES[chr(int(k, 16))] = v
    return _CONFUSABLES


_PROTO = {}


def _proto(ch, t):
    """Прототип символу: коди з таблиці перетворюються один раз і кешуються окремо."""
    p = _PROTO.get(ch)
    if p is None:
        v = t.get(ch)
        p = _PROTO[ch] = ch if v is None else ''.join(chr(int(x, 16)) for x in v.split())
    return p


def skeleton(name):
    """Як імʼя виглядає: скелет UTS #39 — NFD, кожен символ → його прототип із confusables.txt, знову NFD."""
    t = confusables()
    return unicodedata.normalize('NFD', ''.join(_proto(c, t) for c in unicodedata.normalize('NFD', name)))


def glyph_twin(name):
    """Гліф, на який схоже імʼя (х → ×, р → ρ, v → ν), або None."""
    sk = skeleton(name)
    if not hasattr(glyph_twin, 'table'):
        glyph_twin.table = {skeleton(g): g for g in [*GLYPHS, *CONSTS] if len(g) == 1}
    return glyph_twin.table.get(sk)


def check_twins(toks):
    """Два різні імена, однакові на вигляд (x і х, cop і сор, h і һ, I і l), — помилка (скелети UTS #39). Так само
    імʼя, що виглядає як число (З, О), і імʼя з символів сумісності (ｘ, 𝚡, ﬁ). Імʼя функції, схоже на гліф, —
    помилка в розборі (Parser.expr)."""
    seen = {}
    for kind_, val, pos in toks:
        if kind_ != 'name':
            continue
        if unicodedata.normalize('NFKC', val) != val:
            raise StaticError(f'імʼя «{val}» містить символи сумісності (повноширинні, математичні, лігатури)', pos)
        if val.translate(DIGIT_LIKE).isdigit():
            raise StaticError(f'імʼя «{val}» виглядає як число', pos)
        sk = skeleton(val)
        if sk in seen and seen[sk] != val:
            raise StaticError(f'імена «{seen[sk]}» і «{val}» однакові на вигляд — двійники заборонені', pos)
        seen.setdefault(sk, val)


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

    modes = []          # стек шаблонів: 'текст' — усередині 〔〕, 'дірка' — у {вираз} шаблону
    while i < n:
        ch, pos = src[i], (line, col)
        if modes and modes[-1] == 'текст':
            buf = []
            while True:
                if i >= n:
                    raise StaticError(f'незакритий шаблон «{TMPL_OPEN}» — бракує «{TMPL_CLOSE}»', pos)
                c = src[i]
                if c == TMPL_CLOSE or c == '{':
                    break
                if c == '\\' and i + 1 < n:
                    e = src[i + 1]
                    buf.append({'n': '\n', 't': '\t', '\\': '\\', '{': '{', '}': '}', TMPL_CLOSE: TMPL_CLOSE}.get(e, '\\' + e))
                    adv(2)
                    continue
                if c == '\r' and src[i + 1:i + 2] == '\n':
                    adv()
                    continue
                buf.append(c)
                adv()
            text = ''.join(buf)
            bad = hidden(text)
            if bad:
                raise StaticError(f'у шаблоні невидимий чи керівний символ U+{ord(bad[0]):04X}', pos)
            if text:
                toks.append(('tpart', text, pos))
            tpos = (line, col)
            if src[i] == TMPL_CLOSE:
                toks.append(('tclose', TMPL_CLOSE, tpos))
                modes.pop()
            else:
                toks.append(('hopen', '{', tpos))
                modes[-1] = 'текст'
                modes.append('дірка')
            adv()
            continue
        if modes and modes[-1] == 'дірка' and (ch == '}' or ch == '\n' or ch == SEP):
            if ch != '}':
                raise StaticError('вираз у {…} шаблону — в одному рядку і без ¦', pos)
            toks.append(('hclose', '}', pos))
            modes.pop()
            adv()
            continue
        if ch == TMPL_OPEN:
            toks.append(('topen', TMPL_OPEN, pos))
            modes.append('текст')
            adv()
            continue
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
        elif ch in ' \t' or (ch == '\r' and src[i + 1:i + 2] == '\n'):
            adv()
        elif ch.isspace() or invisible(ch):
            raise StaticError(f'нестандартний чи невидимий символ U+{ord(ch):04X} поза рядком — у коді лише пробіл, '
                              f'табуляція й новий рядок', pos)
        elif ch == COMMENT:
            j = src.find('\n', i)
            j = n if j < 0 else j
            text = src[i:j - 1] if src[j - 1:j] == '\r' and j > i else src[i:j]
            bad = hidden(text, '\t')
            if bad:
                raise StaticError(f'у коментарі невидимий чи керівний символ U+{ord(bad[0]):04X} (CR, ESC, bidi, '
                                  f'теги…) — ним ховають код від людини, що читає сирий текст', pos)
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
                if c == '\r' and src[i + 1:i + 2] == '\n':     # CRLF у файлі — звичайний новий рядок
                    adv()
                    continue
                buf.append(c)
                adv()
            text = ''.join(buf)
            bad = hidden(text)
            if bad:
                raise StaticError(f'у рядку коду невидимий чи керівний символ U+{ord(bad[0]):04X} — у тексті програми '
                                  f'лише видиме (і \\n, \\t); такі символи беріть із даних: δ 「"\\u…"」', pos)
            toks.append(('str', text, pos))
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
            if scripts - {'ASCII', 'FULLWIDTH'}:
                raise StaticError('у числі лише цифри 0–9 або ０–９: цифри інших письмен схожі на інші (৪ — це 4, '
                                  'а виглядає як 8)', pos)
            val = Decimal(num) if '.' in num else int(num)      # дріб — точний десятковий: 0.1 ＋ 0.2 = 0.3
            toks.append(('num', -val if neg else val, pos))
        elif is_name_start(ch):
            buf = ''
            while i < n and (is_name_char(src[i]) or (src[i] == '.' and i + 1 < n and is_name_start(src[i + 1]))):
                buf += src[i]
                adv()
            buf = unicodedata.normalize('NFC', buf)
            scripts = {script_of(c) for c in buf if unicodedata.category(c) in ('Lu', 'Ll', 'Lt', 'Lo')}
            if len(scripts) > 1:
                raise StaticError(f'імʼя «{buf}» змішує письма ({", ".join(sorted(scripts))}): однакові на вигляд '
                                  f'літери різних абеток у Nigredo заборонені', pos)
            if scripts - NAME_SCRIPTS:
                raise StaticError(f'імʼя «{buf}»: письмо {", ".join(sorted(scripts - NAME_SCRIPTS))} в іменах не дозволене — '
                                  f'його літери-двійники (як коптська ⲁ і а) таблиця Unicode ловить не всі', pos)
            if any(ch in FILLERS for ch in buf):
                raise StaticError('імʼя з невидимим заповнювачем (U+3164 тощо) заборонене', pos)
            if any(unicodedata.category(ch) == 'Nd' and not '0' <= ch <= '9' for ch in buf):
                raise StaticError(f'в імені «{buf}» — лише цифри 0–9 (інші письма цифр плутаються з ними)', pos)
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
    if modes:
        raise StaticError(f'незакритий шаблон «{TMPL_OPEN}» — бракує «{TMPL_CLOSE}» чи «}}»', (line, col))
    toks.append(('eof', None, (line, col)))
    return toks


# ------------------------------------------------------------------ розбір
# Вузол: (вид, позиція, ...). Види: lit var call op bind lam list dict block seal tool deleg


def plain_text(text, what, pos, name=False):
    """Намір, дозволи й імена субагентів бачить отримувач у --печатка: лише видимий текст, без пробілів поспіль чи
    по краях і без 「」, якими звіт обрамлює слова автора; в імені субагента ще й без «/» (ним звіт пише вкладеність)."""
    bad = hidden(text, '')
    if bad:
        raise StaticError(f'{what}: керівні чи невидимі символи заборонені ({", ".join(f"U+{ord(c):04X}" for c in bad[:3])})', pos)
    if '  ' in text or text != text.strip(' '):
        raise StaticError(f'{what}: пробіли поспіль чи по краях заборонені — ними ховають текст за край екрана', pos)
    if '「' in text or '」' in text or (name and '/' in text):
        raise StaticError(f'{what}: символи {"「」 /" if name else "「」"} заборонені — ними звіт печатки обрамлює '
                          f'слова автора' + (' і пише вкладеність' if name else ''), pos)


class Caps(dict):
    """Дозволи: інструмент → [обмеження]; quotas: (інструмент, обмеження) → найбільше викликів за запуск («≤N»)."""
    def __init__(self, *a, quotas=None, **k):
        super().__init__(*a, **k)
        self.quotas = dict(quotas or {})



def split_quota(perm, pos=None):
    """「взяти:api.x≤100」 → («взяти:api.x», 100); без ≤ — (perm, None)."""
    import re as _re
    m = _re.fullmatch(r'(.*?)\s*≤\s*([0-9]+)', perm)
    if not m:
        if '≤' in perm:                # ≤৪, ≤¯1, ≤ у середині — не квота й не шлях (суд 8)
            raise StaticError(f'дозвіл «{safe(perm)}»: квота — «≤N» у кінці, N — цифри 0–9', pos)
        return perm, None
    if '≤' in m.group(1):
        raise StaticError(f'дозвіл «{safe(perm)}»: одна квота ≤N — у кінці', pos)
    if int(m.group(2)) < 1:
        raise StaticError(f'дозвіл «{safe(perm)}»: квота ≤0 нічого не дозволяє — приберіть дозвіл', pos)
    return m.group(1), int(m.group(2))


def narrower(tool, child, parent):
    """Обмеження субагента — те саме або вужче: для тек — підтека (без виходу через ..), інакше точний збіг."""
    if child == parent:
        return True
    if TOOLS.get(tool, (0, '', '', False, ''))[4] == 'команда':
        return cmd_within(child, parent)
    if TOOLS.get(tool, (0, '', '', False, ''))[4] != 'тека':
        return False
    c, p = os.path.normpath(child), os.path.normpath(parent)
    if os.path.isabs(c) != os.path.isabs(p):
        return False
    if p == '.':
        rest = c
    elif c.startswith(p.rstrip(os.sep) + os.sep):
        rest = c[len(p.rstrip(os.sep)) + 1:]
    else:
        return False
    # решта шляху — лише вглиб: жодного «..» (суд 4: «..» → «../../..» вважалося підтекою)
    return '..' not in rest.split(os.sep)


def param_names(params):
    """Імена параметрів λ/Λ, зокрема з розборів 【a b】."""
    return [x for p in params for x in (p[2] if isinstance(p, tuple) else [p])]


def param_text(params):
    return ', '.join(f'【{", ".join(p[2])}】' if isinstance(p, tuple) else p for p in params)


class Parser:
    def __init__(self, toks, base=None, root=None, stack=(), module=False):
        self.t, self.i = toks, 0
        self.base, self.root, self.stack, self.module = base, root or base, stack, module   # для ⊃
        self.scopes = [{}]          # імʼя → арність функції або 0 для значення
        self.cap_stack = []         # дозволи найближчої печатки / субагента: {інструмент: [обмеження]}
        self.agent_names = {skeleton("головний"): "головний"}   # скелет імені субагента → імʼя
        self.ctx = [('stmt', 0)]    # ('stmt', відступ інструкції) або ('items',) усередині 【】『』
        self.head = -1              # індекс токена, з якого почалася поточна інструкція
        self.frames = []            # незавершені вирази [початок, [(початок, кінець, вкладені)…]] — для підказки арності
        self.last_span = None       # (початок, кінець, вкладені) щойно розібраного виразу

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
                              'наступному рядку, зробіть там більший відступ)' + self.hungry(), tok[2])

    def tok_text(self, t):
        k, v = t[0], t[1]
        if k == 'str':
            v = v if len(v) <= 12 else v[:10] + '…'
            return '「' + v.replace('\n', '\\n') + '」'
        if k == 'tpart':
            return v if len(v) <= 12 else v[:10] + '…'
        return str(v)

    def shape(self, span, limit=300):
        """Як розібрано вираз: кожен вираз з аргументами — у дужках (підказка, коли не зійшлася арність)."""
        def go(s, e, kids, top=False):
            out, i, k = [], s, 0
            while i < e:
                if k < len(kids) and kids[k][0] == i:
                    out.append(go(*kids[k]))
                    i = kids[k][1]
                    k += 1
                    continue
                if self.t[i][0] != 'nl':
                    out.append(self.tok_text(self.t[i]))
                i += 1
            text = ' '.join(out)
            return f'({text})' if kids and not top and self.t[s][0] not in ('open', 'topen') else text
        text = go(*span, top=True)
        return text if len(text) <= limit else text[:limit] + ' …'

    def hungry(self):
        """Які вирази ще чекають аргументів — найглибші спершу."""
        out = []
        for start, kids in reversed(self.frames):
            if start >= self.i or self.t[start][0] in ('open', 'topen'):
                continue
            k, v, pos = self.t[start]
            if k == 'glyph' and v in GLYPHS and isinstance(GLYPHS[v][0], int):
                out.append(f'{v} ({pos[0]}:{pos[1]}) бере {GLYPHS[v][0]}, є {len(kids)}')
            elif k == 'name' and self.lookup(v):
                out.append(f'{v} ({pos[0]}:{pos[1]}) бере {self.lookup(v)}, є {len(kids)}')
            else:
                out.append(f'{self.tok_text(self.t[start])} ({pos[0]}:{pos[1]})')
            if len(out) == 3:
                break
        return (' — чекають аргументів: ' + '; '.join(out)) if out else ''

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
        if self.module:
            for st in stmts[1:]:
                if st[0] not in ('bind', 'import') or (st[0] == 'bind' and st[3][0] != 'lam' and not const_expr(st[3])):
                    raise StaticError('модуль на верхньому рівні лише називає функції (← f λ…) і сталі (літерали й '
                                      'обчислення без викликів) і бере інші модулі (⊃); будь-які виклики й дії — лише '
                                      'всередині функцій', st[1])
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
                rest = []
                for t in self.t[self.i:]:
                    if t[0] in ('nl', 'eof'):
                        break
                    rest.append(self.tok_text(t))
                raise StaticError('вираз уже завершено, а в рядку ще щось є — зайве чи бракує аргументу раніше? '
                                  '(кілька виразів в одному рядку розділяйте ¦)'
                                  f' — розібрано: {self.shape(self.last_span)} — зайве: {" ".join(rest)[:120]}', after[2])

    def expr(self):
        start, kids = self.i, []
        self.frames.append([start, kids])
        try:
            node = self.expr_()
        finally:
            self.frames.pop()
        self.last_span = (start, self.i, kids)
        if self.frames:
            self.frames[-1][1].append(self.last_span)
        return node

    def expr_(self):
        self.cont_nl()
        if self.frames[-1][0] < self.i:                 # перенос рядка — вираз починається далі
            self.frames[-1][0] = self.i
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
                twin = glyph_twin(val)
                if twin:
                    raise StaticError(f'функція «{val}» на вигляд — гліф «{twin}»: «{val} …» читається як «{twin} …»; '
                                      f'назвіть її інакше', pos)
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
        if kind_ == 'topen':
            parts = []
            while True:
                k2, v2, p2 = self.next()
                if k2 == 'tclose':
                    return ('tmpl', pos, parts)
                if k2 == 'tpart':
                    parts.append(('lit', p2, v2))
                    continue
                if k2 != 'hopen':
                    raise StaticError('шаблон обірвався — бракує «〕»', p2)
                part = self.expr()                      # після 'hopen' — рівно один вираз
                end = self.next()
                if end[0] != 'hclose':
                    raise StaticError('у {…} шаблону — рівно один вираз; після нього має бути «}»', end[2])
                parts.append(('hole', p2, part))
        if kind_ in ('hclose', 'tclose', 'hopen', 'tpart'):
            raise StaticError(f'«{val}» тут не очікувалося — бракує виразу в шаблоні', pos)
        if kind_ == 'close':
            self.i -= 1
            raise StaticError(f'«{val}» тут не очікувалося — бракує аргументу' + self.hungry(), pos)
        if kind_ == 'eof' or kind_ == 'nl':
            self.i -= 1
            raise StaticError('бракує аргументу: вираз обірвався' + self.hungry(), pos)
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

    def param(self, what):
        """Параметр λ/Λ: імʼя або розбір списку 【a b …】 (рівно стільки елементів)."""
        self.cont_nl()
        nxt = self.peek()
        if nxt[0] == 'open' and nxt[1] == '【':
            _, _, ppos = self.next()
            names = []
            while not (self.peek()[0] == 'close' and self.peek()[1] == '】'):
                names.append(self.name_tok(what)[0])
            self.next()
            if len(names) < 2:
                raise StaticError(f'{what}【…】: розбір — щонайменше два імені', ppos)
            return ('pat', ppos, names)
        return self.name_tok(what)[0]

    def lam(self, n, pos):
        params = [self.param('λ' if n == 1 else 'Λ') for _ in range(n)]
        flat = param_names(params)
        if len(set(flat)) != len(flat):
            raise StaticError('однакові імена параметрів', pos)
        self.scopes.append({p: 0 for p in flat})
        body = self.expr()
        self.scopes.pop()
        return ('lam', pos, params, body)

    def import_(self, pos):
        """⊃ 「шлях.ngr」 【「імʼя」 …】: розібрати модуль зараз (щоб знати арності), перевірити його печатку."""
        if self.i - 1 != self.head or len(self.scopes) != 1:
            raise StaticError('⊃ — лише на початку інструкції верхнього рівня (не у функції чи блоці)', pos)
        path, names = self.expr(), self.expr()
        if path[0] != 'lit' or not isinstance(path[2], str):
            raise StaticError('⊃: шлях до модуля — буквальний рядок 「…」', pos)
        if names[0] != 'list' or not names[2] or any(e[0] != 'lit' or not isinstance(e[2], str) for e in names[2]):
            raise StaticError('⊃: імена — непорожній буквальний список рядків 【「імʼя」 …】', pos)
        rel = path[2]
        if self.base is None:
            raise StaticError('⊃: модулі — лише в програмах із текою', pos)
        if not rel.endswith('.ngr') or os.path.isabs(rel):
            raise StaticError('⊃: модуль — відносний шлях до файлу .ngr', pos)
        plain_text(rel, 'шлях модуля', pos)
        real = os.path.realpath(os.path.join(self.base, rel))
        if not inside(real, self.root) or inside(real, OWNER_HOME):
            raise StaticError(f'⊃: модуль «{safe(rel)}» поза текою програми — модулі лише з її теки й підтек', pos)
        if real in self.stack:
            raise StaticError(f'⊃: циклічний імпорт «{safe(rel)}»', pos)
        try:
            raw = open(real, 'rb').read()
            src = raw.decode('utf-8')
        except (OSError, UnicodeDecodeError) as e:
            raise StaticError(f'⊃: модуль «{safe(rel)}» не прочитати: {getattr(e, "strerror", None) or e}', pos)
        try:
            toks = lex(src)
            check_twins(toks)
            sub = Parser(toks, os.path.dirname(real), self.root, self.stack + (real,), module=True)
            mod = sub.program()
            errs = type_errors(mod)
            if errs:
                raise errs[0]
        except StaticError as e:
            raise StaticError(f'у модулі «{safe(rel)}»: {e}', pos)
        mcaps = mod[2][0][3]
        parent = self.cap_stack[-1]
        for t, scopes in mcaps.items():
            if t not in parent:
                raise StaticError(f'модуль «{safe(rel)}» просить «{t}», якого немає в печатці програми', pos)
            for sc in scopes:
                if parent[t] and sc not in parent[t] and not any(narrower(t, sc, ps) for ps in parent[t]):
                    raise StaticError(f'модуль «{safe(rel)}» просить «{t}:{sc}» — ширше, ніж у печатці програми', pos)
        for e in names[2]:
            nm = e[2]
            if nm not in sub.scopes[0]:
                raise StaticError(f'у модулі «{safe(rel)}» немає «{safe(nm)}»', e[1])
            if nm in self.scopes[0]:
                raise StaticError(f'«{nm}» уже назване тут — значення в Nigredo не перепризначаються', e[1])
            self.scopes[0][nm] = sub.scopes[0][nm]
        return ('import', pos, os.path.relpath(real, self.root), [e[2] for e in names[2]], mod,
                hashlib.sha256(raw).hexdigest(), real)

    def caps_literal(self, what, pos, inherit=False):
        node = self.expr()
        if node[0] != 'list' or any(e[0] != 'lit' or not isinstance(e[2], str) for e in node[2]):
            raise StaticError(f'дозволи {what} мають бути буквальним списком рядків 【「…」 …】', pos)
        caps = Caps()
        for e in node[2]:
            plain_text(e[2], f'дозвіл {what}', e[1])
            text, quota = split_quota(e[2], e[1])
            names, sep, scope = text.partition(':')
            for nm in names.split(' '):        # 「читати писати:тимч」 = 「читати:тимч」 「писати:тимч」
                perm = canon_perm(nm + sep + scope)
                self.cap_one(caps, perm, e[1], inherit)
                if quota is not None:          # 「взяти:api.x≤100」 — не більше 100 викликів за запуск
                    t, _, sc = perm.partition(':')
                    if (t.strip(), sc.strip()) in caps.quotas:     # дві квоти — яка діє? помилка (суд 8)
                        raise StaticError(f'дві квоти на «{t.strip()}{":" + sc.strip() if sc.strip() else ""}» '
                                          f'(≤{caps.quotas[(t.strip(), sc.strip())]} і ≤{quota}) — залиште одну', e[1])
                    caps.quotas[(t.strip(), sc.strip())] = quota
        return node, caps

    @staticmethod
    def cap_one(caps, perm, pos, inherit):
        name, _, scope = perm.partition(':')
        name = name.strip()
        if name not in TOOLS:
            raise StaticError(f'невідомий інструмент у дозволах: «{name}»', pos)
        if TOOLS[name][3] and not scope.strip() and not inherit:
            raise StaticError(f'«{name}» потребує обмеження: «{name}:{TOOLS[name][4]}»', pos)
        if TOOLS[name][4] == 'команда' and scope.strip() and not (
                os.path.isabs(w := scope.strip().split(' ')[0]) or '/' not in w):
            raise StaticError(f'«{name}»: команда — імʼя з PATH (git) або абсолютний шлях, не відносний', pos)
        lst = caps.setdefault(name, [])
        if (s := scope.strip()) and s not in lst:      # дубль — один раз
            lst.append(s)

    def glyph(self, g, pos):
        if g == '🜂':
            if self.cap_stack:
                raise StaticError('печатка 🜂 — лише одна й лише першим рядком програми', pos)
            if self.peek()[0] in ('nl', 'eof'):          # гола 🜂 — програма без дозволів
                self.cap_stack.append({})
                return ('seal', pos, '', {})
            nxt = self.peek()
            intent = ('lit', pos, '') if nxt[0] == 'open' and nxt[1] == '【' else self.expr()   # намір — за бажанням
            if intent[0] != 'lit' or not isinstance(intent[2], str) or (intent[2] == '' and nxt[0] != 'open'):
                raise StaticError('печатка: 🜂 「намір」 【「дозвіл」 …】, 🜂 【「дозвіл」 …】 або сама 🜂', pos)
            if intent[2]:
                plain_text(intent[2], 'намір печатки', pos)
            if self.peek()[0] in ('nl', 'eof'):          # 🜂 「намір」 — намір без дозволів
                self.cap_stack.append({})
                return ('seal', pos, intent[2], {})
            _, caps = self.caps_literal('печатки', pos)
            self.cap_stack.append(caps)
            return ('seal', pos, intent[2], caps)
        if g == '🜔':
            kind_, name, npos = self.next()
            if kind_ != 'name':
                raise StaticError('після 🜔 очікувалася назва інструмента: 🜔читати …', npos)
            name = TOOL_ALIASES.get(name, name)
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
        if g == '⊃':
            return self.import_(pos)
        if g == '∘':
            name, npos = self.name_tok('∘')
            if not self.lookup(name):
                raise StaticError(f'∘ бере функцію, названу ← (λ або Λ); «{name}» — не така', npos)
            return ('var', pos, name)
        if g == '🜁':
            name = self.expr()
            nxt = self.peek()
            intent = ('lit', pos, '') if nxt[0] == 'open' and nxt[1] == '【' else self.expr()   # намір — за бажанням
            if name[0] != 'lit' or not isinstance(name[2], str) or intent[0] != 'lit' or not isinstance(intent[2], str):
                raise StaticError('🜁: імʼя (і, за бажанням, намір) субагента — буквальні рядки', pos)
            plain_text(name[2], 'імʼя субагента', pos, name=True)
            seen = self.agent_names.setdefault(skeleton(name[2]), name[2])
            if seen != name[2]:
                raise StaticError(f'субагенти «{seen}» і «{name[2]}» однакові на вигляд — двійники заборонені', pos)
            if intent[2]:
                plain_text(intent[2], 'намір субагента', pos)
            _, caps = self.caps_literal('субагента', pos, inherit=True)
            parent = self.cap_stack[-1]
            for t, scopes in caps.items():
                if t not in parent:
                    raise StaticError(f'субагент «{name[2]}» просить «{t}», якого немає в батька', pos)
                for s in scopes:
                    if not any(narrower(t, s, p) for p in parent[t]):
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


WORLD_WRITERS = {'жереб', 'файл.писати', 'бд.писати', 'процес', 'агент', 'мережа.взяти', 'мережа.послати'}      # змінюють стан, який потім можна прочитати
WORLD_READERS = {'жереб', 'файл.читати', 'файл.список', 'файл.писати', 'бд.читати', 'бд.писати', 'процес', 'агент', 'мережа.взяти', 'мережа.послати'}
_EFFECTS = {}
FN_SLOTS = {'∀': (1,), 'μ': (1,), '∫': (1,), '‖': (1,), '№': (1,), 'φ': (1,), '⇅': (1,), '⊞': (1,), 'Σ': (2,), '↻': (1, 2), '☂': (1,), '🜍': (1,)}


def effects(node):
    """Які стани може змінити цей код, якщо виконається: {'mem', 'world'}. Невідома функція — усе."""
    key = id(node)
    if key in _EFFECTS:
        return _EFFECTS[key][1]
    out = set()

    def walk(n):
        if isinstance(n, tuple) and n:
            k = n[0]
            if k == 'op' and n[2] == '🜄':
                out.add('mem')
            elif k == 'op' and n[2] in '►▶':
                out.update(('mem', 'world'))
            elif k == 'call':
                out.update(('mem', 'world'))
            elif k == 'tool' and n[2] in WORLD_WRITERS:
                out.add('world')
            elif k == 'op' and n[2] in FN_SLOTS and any(n[3][i][0] != 'lam' for i in FN_SLOTS[n[2]]):
                out.update(('mem', 'world'))      # функцію передано значенням (∘, змінна, вираз) — її тіла тут не видно
            elif k == 'deleg':           # памʼять субагента — своя; зовнішній світ — спільний
                if 'world' in effects(n[5]):
                    out.add('world')
                return
            for x in n:
                walk(x)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    walk(node)
    _EFFECTS[key] = (node, frozenset(out))      # тримаємо вузол, щоб id не переписався
    return _EFFECTS[key][1]


def total_type(node):
    """Тип, який вузол дає гарантовано без помилки (крім лімітів розміру й кроків), або None — може впасти.
    Маленький вивід типів лише для каналу завершення: σ ± ＝ ≠ ¬ ∧ ∨ ¿ і ＋ рядків чи чисел не падають, якщо
    аргументи відомих типів; імʼя — «будь-що»; решта (виклики, інструменти, ÷, §, ☠, 🜍, цикли…) — може впасти."""
    k = node[0]
    if k == 'lit':
        v = node[2]
        return 'bool' if isinstance(v, bool) else 'num' if isinstance(v, NUM) else 'str' if isinstance(v, str) else 'any'
    if k == 'var':
        return 'any'
    if k == 'lam':
        return 'fn'
    if k in ('list', 'dict'):
        return k if all(total_type(x) for x in node[2]) else None
    if k == 'tmpl':
        return 'str' if all(total_type(x[2] if x[0] == 'hole' else x) for x in node[2]) else None
    if k != 'op':
        return None
    g, ts = node[2], [total_type(x) for x in node[3]]
    if None in ts:
        return None
    if g == 'σ':
        return 'str'
    if g == '±':
        return 'num'
    if g in ('＝', '≠'):
        return 'bool'
    if g == '＋' and ts[0] == ts[1] and ts[0] in ('str', 'num'):
        return ts[0]
    if g == '¬' and ts[0] == 'bool':
        return 'bool'
    if g in ('∧', '∨') and ts == ['bool', 'bool']:
        return 'bool'
    if g == '¿' and ts[0] == 'bool':
        return ts[1] if ts[1] == ts[2] else 'any'
    return None


INT_FAST = {'＋': lambda x, y: x + y, '－': lambda x, y: x - y, '×': lambda x, y: x * y, '‰': lambda x, y: x % y,
            '‹': lambda x, y: x < y, '›': lambda x, y: x > y, '≤': lambda x, y: x <= y, '≥': lambda x, y: x >= y,
            '＝': lambda x, y: x == y, '≠': lambda x, y: x != y}
NEED_FAST = {'рядок': str, 'список': list, 'словник': dict}
LAZY_GLYPHS = set('¿☂‖∀μφ⇅⊞∫№Σ↻')   # гліфи, що самі вирішують, які аргументи й коли обчислювати
OWN_CONF = set('≈±⚗►▶🜃🜍🜄§⌂ρκ')     # гліфи, що самі встановлюють впевненість результату
NEVER_FAILS = set('σ±＝≠¬∧∨ρ⇣⇡⊢↺∋»κ✎⊳✂＋－×‹›≤≥Δ⌂🜄🜃')     # падіння цих не залежить від значень аргументів
PURE_GLYPHS = set('＋－×÷‰⌊≅⌗＝≠‹›≤≥∧∨¬¿ρ§✂⁀σνδΔ∋⇄⊢⇣⇡⊏⊳⌕≋↺↑κ✎…±⌂')


def const_expr(node):
    """Сталий вираз для верхнього рівня модуля: літерали, імена, списки, словники, шаблони й чисті гліфи — без
    викликів функцій, гліфів, що беруть функції (∀ μ … ► ▶), інструментів, субагентів, друку, памʼяті."""
    k = node[0]
    if k in ('lit', 'var'):
        return True
    if k in ('list', 'dict', 'tmpl'):
        return all(const_expr(x[2] if x[0] == 'hole' else x) for x in node[2])
    if k == 'op':
        return node[2] in PURE_GLYPHS and all(const_expr(x) for x in node[3])
    return False


def acts(node):
    """Чи діє цей код у світі поза функціями (інструмент, субагент, друк, памʼять, слід) — для модулів."""
    if isinstance(node, tuple) and node:
        if node[0] == 'lam':
            return False
        if node[0] in ('tool', 'deleg', 'import') or node[0] == 'op' and node[2] in ('»', '🜄', '🜃', '≈', '⚗', '🜍', '☠'):
            return True
        return any(acts(x) for x in node)
    if isinstance(node, list):
        return any(acts(x) for x in node)
    return False


def may_stop(node, called=False):
    """Чи може цей код зупинити програму — для каналу завершення (☠, 🜍, ÷ 0, § поза межами, невідповідний тип,
    виклик, інструмент…). called: вузол — функція, яку викличуть (λ — дивимося тіло; інше — невідомо, отже може)."""
    if called:                       # розбір 【a b】 падає на списку іншої довжини
        return may_stop(node[3]) or any(isinstance(p, tuple) for p in node[2]) if node[0] == 'lam' else True
    return total_type(node) is None


# ------------------------------------------------------------------ типи до запуску
# Значення незмінні, тож тип названого значення відомий раз і назавжди: вивід без анотацій ловить певні помилки
# (обидва типи відомі й не підходять) до запуску. Невідоме ('any': параметр функції, δ, §) — не помилка.

TYPE_NAMES = {'num': 'число', 'str': 'рядок', 'bool': '●/○', 'none': '∅', 'list': 'список', 'dict': 'словник',
              'fn': 'функція', 'any': 'будь-що'}
_N, _S, _B, _L, _D, _F, _A = 'num', 'str', 'bool', 'list', 'dict', 'fn', 'any'
TYPE_REQ = {
    '＋': [(_N, _N), (_S, _S), (_L, _L)], '－': [(_N, _N)], '×': [(_N, _N)], '÷': [(_N, _N)], '‰': [(_N, _N)],
    '⌊': [(_N,)], '≅': [(_N, _N)], '⌗': [(_N, _N)], '…': [(_N, _N)],
    '‹': [(_N, _N), (_S, _S)], '›': [(_N, _N), (_S, _S)], '≤': [(_N, _N), (_S, _S)], '≥': [(_N, _N), (_S, _S)],
    '∧': [(_B, _B)], '∨': [(_B, _B)], '¬': [(_B,)], '¿': [(_B, _A, _A)],
    'ρ': [(_S,), (_L,), (_D,)], '§': [(_L, _N), (_S, _N), (_D, _S)], '✂': [(_S, _S)], '⁀': [(_L, _S)],
    '⇄': [(_S, _S, _S)], '⊢': [(_S,)], '⇣': [(_S,)], '⇡': [(_S,)], 'ν': [(_S,)], 'δ': [(_S,)],
    '◷': [(_S, _S), (_S, _N)], '▦': [(_S,)], 'χ': [(_S,), (_D,)], '↘': [(_D, _S)], '✓': [(_A, _S), (_A, _L), (_A, _D)],
    '⌕': [(_S, _S)], '≋': [(_S, _S, _S)], '⊏': [(c, a, b) for c in (_S, _L) for a in (_N, 'none') for b in (_N, 'none')],
    '⊳': [(_S, _S), (_L, _A)], '∋': [(_S, _S), (_L, _A), (_D, _S)], 'κ': [(_D,)], 'ε': [(_D,)], '↑': [(_L,)],
    '↺': [(_S,), (_L,)], '✎': [(_D, _S, _A)], '⚗': [(_L, _N)], '≈': [(_A, _N)],
    '∀': [(_L, _F), (_S, _F)], 'μ': [(_L, _F), (_S, _F)], 'φ': [(_L, _F), (_S, _F)], '⇅': [(_L, _F), (_S, _F)],
    '⊞': [(_L, _F), (_S, _F)], '∫': [(_L, _F), (_S, _F)], '‖': [(_L, _F), (_S, _F)], '№': [(_L, _F), (_S, _F)], 'Σ': [(_L, _A, _F), (_S, _A, _F)],
    '↻': [(_A, _F, _F)], '☂': [(_A, _F)], '🜍': [(_A, _F)], '►': [(_F, _A)], '▶': [(_F, _A, _A)],
}
TYPE_RES = {'∫': _N, '－': _N, '×': _N, '÷': _N, '‰': _N, '⌊': _N, '≅': _N, 'ρ': _N, 'ν': _N, '±': _N, '⊳': _N,
            '＝': _B, '≠': _B, '‹': _B, '›': _B, '≤': _B, '≥': _B, '∧': _B, '∨': _B, '¬': _B, '∋': _B,
            'σ': _S, '⌗': _S, '⁀': _S, '⇄': _S, '⊢': _S, '⇣': _S, '⇡': _S, '≋': _S, 'Δ': _S,
            '▦': _L, 'ε': _L, '↘': _L, '‖': _L, '✂': _L, 'μ': _L, 'φ': _L, '⇅': _L, '↑': _L, '⌕': _L, 'κ': _L, '…': _L, '⚗': _L, '⌂': _L,
            '⊞': _D, '№': _D, '✎': _D, '∀': 'none', '»': 'none', '🜄': 'none', '☠': 'none'}
TOOL_TYPES = {'оракул': ((_A,), _B), 'жереб': ((_N,), _N), 'час': ((), _S), 'файл.читати': ((_S,), _S),
              'файл.писати': ((_S, _S), 'none'), 'файл.список': ((_S,), _L), 'мережа.взяти': ((_S,), _S),
              'мережа.послати': ((_S, _A), _S), 'бд.читати': ((_S, _S, _L), _L), 'бд.писати': ((_S, _S, _L), _N), 'процес': ((_L,), _S),
              'агент': ((_S, _S), _S)}


def lit_type(v):
    return _B if isinstance(v, bool) else _N if isinstance(v, NUM) else _S if isinstance(v, str) \
        else 'none' if v is None else _A


def _fits(actual, alts):
    return any(len(a) == len(actual) and all(r == _A or t == _A or r == t for r, t in zip(a, actual)) for a in alts)


def type_errors(prog):
    """Певні помилки типів у програмі — список StaticError (порожній — помилок не знайдено)."""
    errs = []

    def say(g, actual, alts, pos):
        got = ', '.join(TYPE_NAMES[t] for t in actual)
        want = ' або '.join('(' + ', '.join(TYPE_NAMES[t] for t in a) + ')' for a in alts)
        hint = ''
        if g == '＋' and set(actual) == {_S, _N}:
            hint = ' — число в рядок: σ або шаблон 〔…{n}〕'
        elif g in '¿∧∨¬':
            hint = ' — умова має бути ● або ○ (порівняння: ＝ ≠ ‹ › ≤ ≥)'
        errs.append(StaticError(f'{g}: аргументи ({got}) не підходять, очікувалося {want}{hint}', pos))

    def t(n, env):
        k = n[0]
        if k == 'lit':
            return lit_type(n[2])
        if k == 'tmpl':
            for e in n[2]:
                t(e[2] if e[0] == 'hole' else e, env)
            return _S
        if k == 'var':
            for sc in reversed(env):
                if n[2] in sc:
                    return sc[n[2]]
            return _A
        if k == 'list':
            for e in n[2]:
                t(e, env)
            return _L
        if k == 'dict':
            for e in n[2]:
                t(e, env)
            return _D
        if k == 'block':
            env = env + [{}]
            out = 'none'
            for st in n[2]:
                out = t(st, env)
            return out
        if k == 'bind':
            env[-1][n[2]] = _F if n[3][0] == 'lam' else _A
            env[-1][n[2]] = t(n[3], env)
            return env[-1][n[2]]
        if k == 'lam':
            t(n[3], env + [{p: _A for p in param_names(n[2])}])
            return _F
        if k == 'call':
            for e in n[3]:
                t(e, env)
            return _A
        if k == 'tool':
            actual = [t(e, env) for e in n[3]]
            req, res = TOOL_TYPES.get(n[2], (None, _A))
            if req is not None and not _fits(actual, [req]):
                errs.append(StaticError(f'🜔{n[2]}: аргументи ({", ".join(TYPE_NAMES[x] for x in actual)}) не підходять, '
                                        f'очікувалося ({", ".join(TYPE_NAMES[x] for x in req)})', n[1]))
            return res
        if k == 'deleg':
            return t(n[5], env)
        if k in ('seal', 'import'):
            if k == 'import':
                for nm in n[3]:
                    env[-1][nm] = _A
            return 'none'
        if k == 'op':
            g, args = n[2], n[3]
            actual = [t(e, env) for e in args]
            if g in TYPE_REQ and not _fits(actual, TYPE_REQ[g]):
                say(g, actual, TYPE_REQ[g], n[1])
            if g == '‖' and not (args[1][0] == 'lam' and len(args[1][2]) == 1 and args[1][3][0] == 'tool'
                                 and args[1][3][2] in PARALLEL_TOOLS):        # зібрати всі, а не лише першу (суд 7)
                errs.append(StaticError('‖ список λx 🜔інструмент …: тіло — рівно один виклик інструмента без спільного '
                                        'стану (' + ', '.join(TOOL_SHORT.get(t, t) for t in PARALLEL_TOOLS) +
                                        '; не запис і не жереб — їхній порядок був би випадковим)', n[1]))
            if g in '÷‰' and args[1][0] == 'lit' and args[1][2] == 0 and not isinstance(args[1][2], bool):
                errs.append(StaticError(f'{g}: ділення на буквальний нуль', n[1]))
            if g in '⌕≋' and args[1][0] == 'lit' and isinstance(args[1][2], str):
                try:
                    regex(args[1][2], g, n[1])
                except NgrError as e:
                    errs.append(StaticError(e.msg, n[1]))
            if g == '＋':
                known = [x for x in actual if x != _A]
                return known[0] if known and all(x == known[0] for x in known) else _A
            if g == '¿':
                return actual[1] if actual[1] == actual[2] else _A
            if g in ('⊏', '↺', '≈', '🜍'):
                return actual[0]
            return TYPE_RES.get(g, _A)
        return _A

    t(prog, [{}])
    return errs


def parse(src, base=None, path=None, all_errors=None):
    """Розібрати й перевірити типи; перша помилка — StaticError. all_errors (список) — зібрати всі помилки типів."""
    toks = lex(src)
    check_twins(toks)
    p = Parser(toks, base, stack=(os.path.realpath(path),) if path else ())
    prog = p.program()
    errs = type_errors(prog)
    if all_errors is not None:
        all_errors.extend(errs)
    elif errs:
        raise errs[0]
    return prog


# ------------------------------------------------------------------ слід


class Trace:
    """Слід веде інтерпретатор, а не програма. JSONL; кожен запис підписано HMAC-SHA256 ключем власника
    (теку власника програма не бачить) і зчеплено з попереднім. Останній запис — «кінець» або «помилка»."""

    def __init__(self, outs, key, limit=MAX_TRACE, stores=()):
        self.outs, self.key, self.prev, self.n = outs, key, '0' * 16, 0
        self.stores, self.kept = list(stores), set()   # СЛІД.дані: точні результати інструментів для --повторити
        self.depth, self.bytes, self.limit = 0, 0, limit
        self.tl = threading.local()     # ‖: записи з потоку дії — у його буфер, потім у порядку елементів

    def _check_strings(self, data):
        if _bad_str(data):
            raise Fatal('у даних для сліду неповний символ (сурогат) — запис неможливий, програму зупинено')

    def __call__(self, event, **data):
        buf = getattr(self.tl, 'buf', None)
        if buf is not None:
            buf.append((event, data))
            return
        self._check_strings(data)
        if self.bytes > self.limit and event not in ('помилка', 'кінець', 'відмова'):
            raise Fatal(f'слід перевищив {self.limit} байтів (--слід-розмір) — програму зупинено')
        self.n += 1
        rec = {'№': self.n, 'подія': event, 'глибина': self.depth, **data, 'попередній': self.prev}
        h = sign(self.key, rec)
        rec['хеш'] = h
        self.prev = h
        line = trace_line(rec) + '\n'
        self.bytes += len(line.encode())
        for o in self.outs:
            o.write(line)
            o.flush()

    def keep(self, x):
        """Записати точне значення в сховище (раз на вміст) і повернути його sha256 — для запису в слід."""
        e = enc_v(x)
        h = enc_hash(e)
        if h not in self.kept and self.stores:
            self.kept.add(h)
            line = json.dumps({'sha256': h, 'значення': e}, ensure_ascii=False) + '\n'
            self.bytes += len(line.encode())
            if self.bytes > self.limit:
                raise Fatal(f'слід перевищив {self.limit} байтів (--слід-розмір) — програму зупинено')
            for o in self.stores:
                o.write(line)
                o.flush()
        return h


def enc_v(x):
    """Точне кодування значення для сховища повтору (типи, великі числа, десяткові, порядок ключів, впевненість)."""
    v = x.v
    if isinstance(v, bool) or v is None or isinstance(v, str):
        e = v
    elif isinstance(v, int):
        e = {'ц': str(v)}
    elif isinstance(v, (Decimal, float)):
        e = {'д': str(v)}
    elif isinstance(v, list):
        e = {'л': [enc_v(i) for i in v]}
    elif isinstance(v, dict):
        e = {'с': [[k, enc_v(i)] for k, i in v.items()]}
    else:
        raise TypeError(f'не кодується: {kind(x)}')
    return e if x.c == 1 and x.s == 1 else {'в': repr(x.c), 'б': repr(x.s), 'з': e}


def dec_v(e):
    if isinstance(e, dict) and 'з' in e:
        x = dec_v(e['з'])
        return V(x.v, float(e['в']), float(e['б']))
    if isinstance(e, dict):
        (k, val), = e.items()
        if k == 'ц':
            return V(int(val))
        if k == 'д':
            return V(Decimal(val))
        if k == 'л':
            return V([dec_v(i) for i in val])
        return V({kk: dec_v(i) for kk, i in val})
    return V(e)


def enc_hash(e):
    return hashlib.sha256(json.dumps(e, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _bad_str(x):
    if isinstance(x, str):
        return any(0xD800 <= ord(ch) <= 0xDFFF for ch in x)
    if isinstance(x, dict):
        return any(_bad_str(k) or _bad_str(v) for k, v in x.items())
    if isinstance(x, (list, tuple)):
        return any(_bad_str(v) for v in x)
    return False


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


def _no_dups(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError('ключ повторюється')
    return dict(pairs)


def _summarized(x):
    if isinstance(x, dict):
        return 1 if x.get('підсумок') is True else sum(_summarized(v) for v in x.values())
    if isinstance(x, list):
        return sum(_summarized(v) for v in x)
    return 0


def verify_trace(path, program=None, as_json=False):
    """Перевірка сліду; з as_json — словник для машин. Див. _verify."""
    msg, info = _verify(path, program)
    if not as_json:
        return msg
    return json.dumps({'цілий': msg.startswith('✓'), 'повідомлення': msg, **info}, ensure_ascii=False, indent=1)


def _verify(path, program=None):
    """✓ лише якщо: кожен рядок — канонічний JSON без повторених ключів; підписи й ланцюжок цілі; слід
    завершено («кінець», «помилка» або «відмова» на старті); якщо дано програму — її sha256 збігається.
    Підсумок цілого сліду каже й те, що отримувачу важливо без читання сліду: спроби поза правами («заборонено»),
    перехоплені помилки, підсумовані (не повністю записані) значення, теку й аргументи запуску."""
    key, prev, n, last, head = owner_key(), '0' * 16, 0, None, None
    denied, caught, summed, modules, dry, raised, quota_hits = [], 0, 0, [], False, 0, []
    info = {}
    try:
        st = os.stat(path)
        if not os.path.isfile(path):
            return '✗ це не файл сліду', info
        if st.st_size > 2 * MAX_TRACE:
            return f'✗ файл завеликий для сліду ({st.st_size} байтів)', info
        lines = open(path, encoding='utf-8', newline='').read().split('\n')    # лише \n: U+2028 — це дані
        if lines and lines[-1] == '':
            lines.pop()
    except (OSError, UnicodeDecodeError) as e:
        return f'✗ слід не прочитати: {e}', info
    for lineno, line in enumerate(lines, 1):
        try:
            rec = json.loads(line, object_pairs_hook=_no_dups)
            if line not in (trace_line(rec), json.dumps(rec, ensure_ascii=False)):
                raise ValueError('не канонічний запис')
            h = rec.pop('хеш')
        except (ValueError, KeyError, AttributeError, TypeError):
            return f'✗ слід пошкоджено в рядку {lineno}: це не запис сліду (або змінений запис)', info
        if rec.get('№') != n + 1:
            return f'✗ слід пошкоджено в рядку {lineno}: пропущено чи переставлено запис (№ {rec.get("№")} замість {n + 1})', info
        if rec.get('попередній') != prev or not hmac.compare_digest(sign(key, rec), str(h)):
            return f'✗ слід пошкоджено або змінено в рядку {lineno}', info
        if n == 0:
            head = rec
        if rec.get('подія') == 'заборонено':
            what = rec.get('шлях') or rec.get('адреса') or rec.get('субагент') or rec.get('аргументи') or ''
            denied.append(f'{rec.get("агент", "?")}: {rec.get("назва") or "делегування"} '
                          f'{safe(str(what))[:80]} — {rec.get("причина") or "бракує прав"}')
        if rec.get('подія') == 'квоту вичерпано':
            quota_hits.append(f'{rec.get("агент", "?")}: {rec.get("квота", "?")} ({rec.get("чия", "?")})')
        caught += rec.get('подія') == 'помилку перехоплено'
        dry = dry or rec.get('подія') == 'сухо'
        if rec.get('подія') == 'впевненість' and isinstance(rec.get('стало'), (int, float)) and \
                isinstance(rec.get('було'), (int, float)) and rec['стало'] > rec['було']:
            raised += 1
        if rec.get('подія') == 'модуль':
            modules.append((rec.get('шлях'), rec.get('файл'), rec.get('sha256')))
        summed += _summarized(rec)
        prev, n, last = h, n + 1, rec.get('подія')
    if not (last in ('кінець', 'помилка') or (last == 'відмова' and n == 2)):
        return f'✗ слід обірвано: {n} записів, останній — «{last}», а не кінець/помилка/відмова на старті', info
    if not head or head.get('подія') != 'початок':
        return '✗ слід не починається з «початок»', info
    about = (f'програма {safe(str(head.get("програма")))}, sha256 {str(head.get("sha256"))[:16]}…, '
             f'час {head.get("час", "—")}, запуск {head.get("запуск", "—")}')
    if 'час' not in head or 'запуск' not in head:
        return f'⚠ слід цілий, але старого формату (без часу й запуску): не доводить, коли і котрий це запуск; {about}' , info
    if program is not None:
        try:
            real = hashlib.sha256(open(program, 'rb').read()).hexdigest()
        except OSError as e:
            return f'✗ не прочитати програму: {e}', info
        if not real.startswith(str(head.get('sha256'))):
            return f'✗ слід цілий, але від ІНШОЇ програми ({about})', info
        for rel, path, sha in modules:              # програма — це й усі її модулі
            try:
                now = hashlib.sha256(open(path, 'rb').read()).hexdigest() if path else None
            except OSError:
                now = None
            if now != sha:
                return (f'✗ слід цілий, але модуль «{safe(str(rel))}» тепер ІНШИЙ (у сліді sha256 {str(sha)[:16]}…, '
                        f'зараз {"немає файлу" if now is None else now[:16] + "…"}) — виконано не той код, що зараз', info)
    info.update({'модулі': [{'шлях': r, 'sha256': h} for r, _, h in modules],
                 'інтерпретатор': head.get('інтерпретатор'),
                 'записів': n, 'останній': last, 'заборонено': denied, 'квоту_вичерпано': quota_hits,
                 'перехоплено_помилок': caught,
                 'підсумовано_значень': summed, 'тека': head.get('тека'), 'аргументи': head.get('аргументи'),
                 'режим': 'повтор' if head.get('повтор') else 'сухо' if dry else 'звичайний'})
    notes = [f'тека {safe(str(head.get("тека", "—")))}',
             f'аргументи {safe(json.dumps(head.get("аргументи"), ensure_ascii=False))}']
    notes.append(f'⚠ спроб поза правами («заборонено»): {len(denied)} — ' + '; '.join(denied[:5])
                 + (' …' if len(denied) > 5 else '') if denied else 'спроб поза правами немає')
    if quota_hits:                     # не порушення прав: оголошена межа (печатка, модуль, субагент, власник)
        notes.append(f'квоту вичерпано (межа спрацювала, дію не виконано): {len(quota_hits)} — '
                     + '; '.join(quota_hits[:5]) + (' …' if len(quota_hits) > 5 else ''))
    if modules:
        notes.append('модулі: ' + ', '.join(f'{safe(str(r))} (sha256 {str(h)[:16]}…)' for r, _, h in modules)
                     + ('' if program is not None else ' — щоб звірити з файлами, перевірте слід разом із програмою'))
    if caught:
        notes.append(f'перехоплено помилок (☂): {caught}')
    if raised:
        notes.append(f'⚠ програма ПІДНЯЛА впевненість (≈) {raised} раз(и) — це твердження автора, а не перевірка')
    info['піднято_впевненість'] = raised
    if summed:
        notes.append(f'⚠ значень записано лише підсумком (довжина, sha256, початок): {summed}')
    if last == 'помилка' and lines and '"внутрішня": true' in lines[-1]:
        notes.insert(0, '⚠ ВНУТРІШНЯ ПОМИЛКА інтерпретатора (код 4): вада мови, а не програми; останній виклик інструмента '
                        '(якщо був) — у записі «помилка»')
        info['внутрішня_помилка'] = True
    mode = (f' — ПОВТОР сліду {safe(str(head.get("повтор")))}: жоден інструмент не діяв, «інструмент» — записані значення'
            if head.get('повтор') else ' — СУХИЙ ПРОГІН: записи, надсилання, процеси й агенти НЕ виконувалися, їхні '
            '«інструмент» — заглушки з впевненістю 0' if dry else '')
    return f'✓ слід цілий і завершений ({last}){mode}: {n} записів; {about}\n  ' + '\n  '.join(notes), info


def trace_val(x, full=False):
    """Значення для сліду (невидиме — як ⟨U+…⟩): повністю; дуже довгий аргумент, що не йде назовні, — довжина,
    sha256 і початок (запис позначено «підсумок»; --перевірити-слід їх лічить)."""
    s = visible(show(x, False))
    if full or len(s) <= 4000:
        return s
    return {'підсумок': True, 'довжина': len(s), 'sha256': hashlib.sha256(s.encode()).hexdigest(), 'початок': s[:1000]}


LINE_BREAKS = {'\u2028': '\\u2028', '\u2029': '\\u2029', '\x85': '\\u0085'}


def trace_line(rec):
    """Рядок JSONL: роздільники рядків Unicode, яких JSON не екранує, — екрановано (запис — рівно один рядок)."""
    line = json.dumps(rec, ensure_ascii=False)
    return ''.join(LINE_BREAKS.get(ch, ch) for ch in line) if any(ch in line for ch in LINE_BREAKS) else line


# ------------------------------------------------------------------ інструменти


OS_ERRORS = {'ENOENT': 'немає такого файлу чи теки', 'EACCES': 'немає доступу', 'EISDIR': 'це тека, а не файл',
             'ENOTDIR': 'це не тека', 'ENOSPC': 'немає місця на диску'}


def os_err(tool, e, p):
    import errno
    return f'{tool}: {OS_ERRORS.get(errno.errorcode.get(e.errno, ""), e.strerror)}: {p}'


def _path_ok(it, tool, p, pos, write=False):
    if not isinstance(p, str):
        raise NgrError(f'{tool}: шлях має бути рядком', pos)
    if '\0' in p or any(invisible(ch) for ch in p):
        it.deny(агент=it.agent, назва=tool, шлях=safe(p), причина='керівні чи невидимі символи в шляху')
        raise NgrError(f'{tool}: у шляху керівні чи невидимі символи', pos)
    def allowed(real):
        if inside(real, OWNER_HOME) or real in it.protected:
            it.deny(агент=it.agent, назва=tool, шлях=safe(p), причина='тека власника або слід')
            raise NgrError(f'{tool}: «{safe(p)}» — це тека власника або слід; програмі туди не можна', pos)
        check = os.path.dirname(real) if write else real
        for base in it.caps[tool]:
            b = os.path.realpath(os.path.join(it.cwd, base))
            if check == b or check.startswith(b + os.sep) or (not write and real == b):
                return True
        return False
    seen = getattr(it.tl, 'paths', None)            # справжні шляхи — у запис «інструмент» (що прочитано насправді)
    real = first = os.path.realpath(os.path.join(it.cwd, p))
    if allowed(real):
        if seen is not None:
            seen.append(safe(real))
        return real
    # шлях один раз: відносний шлях поза дозволом — відносно єдиної теки з печатки (🜔читати 「x.json」 при 「читати:дані」)
    # (дозволено один файл — відносно його теки; перевірка однаково пропустить лише сам файл)
    # лише коли шляху від теки програми немає (а для шляху з текою — і самої теки): назвали наявне поза дозволом —
    # відмова, а не тихо інший файл (суд 7)
    named = os.path.exists(first) or ('/' in p.rstrip('/') and os.path.isdir(os.path.dirname(first)))
    if not os.path.isabs(p) and len(it.caps[tool]) == 1 and not named:
        base = os.path.realpath(os.path.join(it.cwd, it.caps[tool][0]))
        real = os.path.realpath(os.path.join(os.path.dirname(base) if os.path.isfile(base) else base, p))
        if allowed(real):
            if seen is not None:
                seen.append(safe(real))
            return real
    it.deny(агент=it.agent, назва=tool, шлях=safe(p), причина='поза дозволеною текою')
    raise NgrError(f'{tool}: «{safe(p)}» поза дозволеним ({", ".join(safe(x) for x in it.caps[tool])})', pos)


# ------------------------------------------------------------------ регулярні вирази без відкатів
# Синтаксис — Python re (розбір — re._parser), виконання — Pike VM: час O(довжина × розмір шаблону) на пошук, кожен
# крок списується з --кроки. Те, що потребує відкатів (зворотні посилання, заглядання, умовні й атомарні групи,
# присвійні повторення), і неоднозначне повторення порожнього тіла — помилка. Звірено з re на ~16 тис. випадків.
import re                                            # noqa: E402
import re._constants as C                            # noqa: E402
import re._parser as P                               # noqa: E402

RX_MAX_PROG = 20_000           # найбільша кількість інструкцій (розгорнуті {m,n})


class RxError(Exception):
    pass


def _cat(code, ch, ascii_):
    name = str(code)
    if ascii_ and not ch.isascii():
        hit = False
    elif 'DIGIT' in name:
        hit = ch.isdecimal() if not ascii_ else '0' <= ch <= '9'
    elif 'SPACE' in name:
        hit = ch.isspace() if not ascii_ else ch in ' \t\n\r\f\v'
    elif 'WORD' in name:
        hit = ch.isalnum() or ch == '_'
    else:
        raise RxError(f'клас {name} не підтримано')
    return (not hit) if 'NOT' in name else hit


def _pred(op, av, icase, dotall, ascii_):
    """Предикат одного символу."""
    if op == C.LITERAL or op == C.NOT_LITERAL:
        c = chr(av)
        cs = {c, c.lower(), c.upper()} if icase else {c}
        return (lambda ch: ch in cs or (icase and ch.lower() in cs)) if op == C.LITERAL else \
               (lambda ch: not (ch in cs or (icase and ch.lower() in cs)))
    if op == C.ANY:
        return (lambda ch: True) if dotall else (lambda ch: ch != '\n')
    if op == C.IN:
        neg, parts = False, []
        for o2, a2 in av:
            if o2 == C.NEGATE:
                neg = True
            elif o2 == C.LITERAL:
                parts.append(('l', chr(a2)))
            elif o2 == C.RANGE:
                parts.append(('r', a2))
            elif o2 == C.CATEGORY:
                parts.append(('c', a2))
            else:
                raise RxError(f'у класі символів {o2} не підтримано')

        def one(ch):
            for kind, a in parts:
                if kind == 'l' and ch == a:
                    return True
                if kind == 'r' and a[0] <= ord(ch) <= a[1]:
                    return True
                if kind == 'c' and _cat(a, ch, ascii_):
                    return True
            return False

        def pred(ch):
            hit = one(ch) or (icase and (one(ch.lower()) or one(ch.upper())))
            return hit != neg
        return pred
    raise RxError(f'{op} не підтримано')


class Rx:
    """Скомпільований шаблон: програма Pike VM."""

    def __init__(self, pat):
        if len(pat) > 1000:
            raise RxError('шаблон довший за 1000 символів')
        try:
            tree = P.parse(pat)
        except re.error as e:
            raise RxError(f'хибний шаблон: {e}')
        flags = tree.state.flags
        self.ngroups = tree.state.groups              # з нульовою (увесь збіг)
        self.names = dict(tree.state.groupdict)
        self.multiline = bool(flags & re.MULTILINE)
        self.ascii = bool(flags & re.ASCII)
        self.prog = []
        self._emit(('save', 0))
        self._gen(list(tree), bool(flags & re.IGNORECASE), bool(flags & re.DOTALL))
        self._emit(('save', 1))
        self._emit(('match',))

    def _emit(self, ins):
        if len(self.prog) >= RX_MAX_PROG:
            raise RxError(f'шаблон розгортається понад {RX_MAX_PROG} інструкцій (зменште {{m,n}})')
        self.prog.append(ins)
        return len(self.prog) - 1

    def _gen(self, items, icase, dotall):
        for op, av in items:
            self._node(op, av, icase, dotall)

    def _node(self, op, av, icase, dotall):
        e = self._emit
        if op in (C.LITERAL, C.NOT_LITERAL, C.ANY, C.IN):
            e(('ch', _pred(op, av, icase, dotall, self.ascii)))
        elif op == C.SUBPATTERN:
            g, add, rem, sub = av
            ic = (icase or bool(add & re.IGNORECASE)) and not (rem & re.IGNORECASE)
            dt = (dotall or bool(add & re.DOTALL)) and not (rem & re.DOTALL)
            if g:
                e(('save', 2 * g))
            self._gen(list(sub), ic, dt)
            if g:
                e(('save', 2 * g + 1))
        elif op == C.BRANCH:
            alts = av[1]
            jumps = []
            for k, alt in enumerate(alts):
                if k < len(alts) - 1:
                    sp = e(('split', None, None))
                    self.prog[sp] = ('split', sp + 1, None)
                    self._gen(list(alt), icase, dotall)
                    jumps.append(e(('jmp', None)))
                    self.prog[sp] = ('split', sp + 1, len(self.prog))
                else:
                    self._gen(list(alt), icase, dotall)
            for j in jumps:
                self.prog[j] = ('jmp', len(self.prog))
        elif op in (C.MAX_REPEAT, C.MIN_REPEAT):
            lo, hi, sub = av
            greedy = op == C.MAX_REPEAT
            sub = list(sub)
            if (hi is C.MAXREPEAT or hi > 1) and _nullable(sub):
                raise RxError('тіло повторення може збігтися з порожнім рядком (як у (a?)+ чи (\\d*|\\s){1,3}) — '
                              'такий шаблон неоднозначний; перепишіть, щоб кожне повторення щось забирало')
            for _ in range(lo):
                self._gen(sub, icase, dotall)
            if hi is C.MAXREPEAT:
                l1 = e(('split', None, None))
                self._gen(sub, icase, dotall)
                e(('jmp', l1))
                self.prog[l1] = ('split', l1 + 1, len(self.prog)) if greedy else ('split', len(self.prog), l1 + 1)
            else:
                ends = []
                for _ in range(hi - lo):
                    sp = e(('split', None, None))
                    ends.append(sp)
                    self._gen(sub, icase, dotall)
                end = len(self.prog)
                for sp in ends:
                    self.prog[sp] = ('split', sp + 1, end) if greedy else ('split', end, sp + 1)
        elif op == C.AT:
            e(('at', av))
        else:
            raise RxError(f'{_human(op)} вимагає відкатів — у Nigredo регулярки без відкатів (лінійний час)')

    # ---------------------------------------------------------------- виконання

    def _at(self, code, text, pos):
        n = len(text)
        if code in (C.AT_BEGINNING, C.AT_BEGINNING_LINE):
            return pos == 0 or (self.multiline or code == C.AT_BEGINNING_LINE) and text[pos - 1] == '\n'
        if code == C.AT_BEGINNING_STRING:
            return pos == 0
        if code in (C.AT_END, C.AT_END_LINE):
            if self.multiline or code == C.AT_END_LINE:
                return pos == n or text[pos] == '\n'
            return pos == n or (pos == n - 1 and text[pos] == '\n')
        if code == C.AT_END_STRING:
            return pos == n
        if code in (C.AT_BOUNDARY, C.AT_NON_BOUNDARY):
            w = lambda ch: ch.isalnum() or ch == '_'      # noqa: E731
            a = pos > 0 and w(text[pos - 1])
            b = pos < n and w(text[pos])
            return (a != b) if code == C.AT_BOUNDARY else (a == b)
        raise RxError(f'{code} не підтримано')

    def _add(self, lst, seen, pc, slots, text, pos):
        stack = [(pc, slots)]
        prog = self.prog
        while stack:
            pc, slots = stack.pop()
            if pc in seen:
                continue
            seen.add(pc)
            ins = prog[pc]
            op = ins[0]
            if op == 'jmp':
                stack.append((ins[1], slots))
            elif op == 'split':
                stack.append((ins[2], slots))
                stack.append((ins[1], slots))
            elif op == 'save':
                s = list(slots)
                s[ins[1]] = pos
                stack.append((pc + 1, tuple(s)))
            elif op == 'at':
                if self._at(ins[1], text, pos):
                    stack.append((pc + 1, slots))
            else:
                lst.append((pc, slots))

    def search(self, text, start, pay, no_empty_at=None):
        """Найлівіший збіг з пріоритетом Perl (як у re) від start: кортеж слотів або None. pay(k) — оплата кроків."""
        n = len(text)
        empty = (None,) * (2 * self.ngroups)
        clist, seen = [], set()
        self._add(clist, seen, 0, empty, text, start)
        matched = None
        pos = start
        while True:
            pay(len(clist) + 1)
            nlist, nseen = [], set()
            ch = text[pos] if pos < n else None
            for pc, slots in clist:
                ins = self.prog[pc]
                if ins[0] == 'match':
                    if no_empty_at is not None and slots[0] == slots[1] == no_empty_at:
                        continue
                    matched = slots
                    break                       # нижчий пріоритет — відкинуто
                if ch is not None and ins[1](ch):
                    self._add(nlist, nseen, pc + 1, slots, text, pos + 1)
            if pos >= n:
                break
            pos += 1
            if matched is None:
                self._add(nlist, nseen, 0, empty, text, pos)
            if not nlist and matched is not None:
                break
            clist = nlist
        return matched

    def finditer(self, text, pay):
        pos, n, prev_empty_end = 0, len(text), None
        while pos <= n:
            m = self.search(text, pos, pay, no_empty_at=prev_empty_end)
            if m is None:
                return
            yield m
            s, e = m[0], m[1]
            prev_empty_end = e if s == e else None
            pos = e

    def groups(self, text, m):
        return [None if m[2 * g] is None else text[m[2 * g]:m[2 * g + 1]] for g in range(self.ngroups)]

    def expand(self, tmpl, gs):
        """Шаблон заміни як у re.sub: \\1…\\99, \\g<n>, \\g<імʼя>, \\n \\t \\\\; решта \\x — помилка."""
        out, i, n = [], 0, len(tmpl)
        while i < n:
            c = tmpl[i]
            if c != '\\':
                out.append(c)
                i += 1
                continue
            if i + 1 >= n:
                raise RxError('заміна закінчується на «\\»')
            d = tmpl[i + 1]
            if d.isdigit():
                j = i + 1
                while j < n and j < i + 3 and tmpl[j].isdigit():
                    j += 1
                k = int(tmpl[i + 1:j])
                if not 0 < k < self.ngroups:
                    raise RxError(f'у заміні немає групи {k}')
                out.append(gs[k] or '')
                i = j
            elif d == 'g' and i + 2 < n and tmpl[i + 2] == '<':
                j = tmpl.find('>', i + 3)
                if j < 0:
                    raise RxError('у заміні незакрите \\g<')
                ref = tmpl[i + 3:j]
                k = int(ref) if ref.isdigit() else self.names.get(ref)
                if k is None or not 0 <= k < self.ngroups:
                    raise RxError(f'у заміні немає групи «{ref}»')
                out.append(gs[k] or '')
                i = j + 1
            else:
                esc = {'n': '\n', 't': '\t', 'r': '\r', '\\': '\\', 'f': '\f', 'v': '\v', 'a': '\a', 'b': '\b'}
                if d not in esc:
                    raise RxError(f'у заміні невідоме екранування \\{d}')
                out.append(esc[d])
                i += 2
        return ''.join(out)

    def sub(self, tmpl, text, pay, size_limit):
        out, last, total = [], 0, 0
        for m in self.finditer(text, pay):
            gs = self.groups(text, m)
            piece = text[last:m[0]] + self.expand(tmpl, gs)
            total += len(piece)
            if total > size_limit:
                raise OverflowError
            out.append(piece)
            last = m[1]
        out.append(text[last:])
        return ''.join(out)


def _nullable(items):
    """Чи може ця частина шаблону збігтися з порожнім рядком."""
    for op, av in items:
        if op in (C.LITERAL, C.NOT_LITERAL, C.ANY, C.IN):
            return False
        if op == C.SUBPATTERN and not _nullable(list(av[3])):
            return False
        if op == C.BRANCH and not any(_nullable(list(b)) for b in av[1]):
            return False
        if op in (C.MAX_REPEAT, C.MIN_REPEAT, C.POSSESSIVE_REPEAT) and av[0] > 0 and not _nullable(list(av[2])):
            return False
    return True


def _human(op):
    return {C.GROUPREF: 'зворотне посилання \\1', C.ASSERT: 'заглядання (?=…)/(?<=…)', C.ASSERT_NOT: 'заглядання (?!…)/(?<!…)',
            C.GROUPREF_EXISTS: 'умовна група (?(1)…)', C.ATOMIC_GROUP: 'атомарна група (?>…)',
            C.POSSESSIVE_REPEAT: 'присвійне повторення *+ ++ ?+'}.get(op, str(op))


_RX_CACHE = {}


def regex(pat, g, pos):
    """Скомпільований шаблон (кешується) або NgrError з поясненням."""
    r = _RX_CACHE.get(pat)
    if r is None:
        try:
            r = Rx(pat)
        except RxError as e:
            raise NgrError(f'{g}: {e}', pos)
        if len(_RX_CACHE) > 256:
            _RX_CACHE.clear()
        _RX_CACHE[pat] = r
    return r


SCHEMA_TYPES = {'число', 'ціле', 'рядок', 'дата', '●/○', 'істинність', '∅', 'ніщо', 'будь-що', 'список', 'словник'}


def check_schema(x, sch, path, errs, pos, depth=0):
    """✓: x проти схеми (дані мови). Розбіжності — у errs як «шлях: що не так»; кривa схема — помилка одразу."""
    if depth > 200:
        raise NgrError('✓: схема вкладена надто глибоко', pos)
    where = path or 'значення'
    sv, v = sch.v, x.v
    if isinstance(sv, str):
        t, _, rest = sv.partition(':')
        nullable = t.endswith('?')
        t = t.rstrip('?')
        if t not in SCHEMA_TYPES:
            raise NgrError(f'✓: невідомий тип у схемі «{safe(sv)}» (є: {", ".join(sorted(SCHEMA_TYPES))})', pos)
        if v is None and (nullable or t in ('∅', 'ніщо', 'будь-що')):
            return
        ok = {'число': isinstance(v, NUM) and not isinstance(v, bool),
              'ціле': isinstance(v, int) and not isinstance(v, bool) or isinstance(v, Decimal) and v == v.to_integral_value(),
              'рядок': isinstance(v, str), 'дата': isinstance(v, str), '●/○': isinstance(v, bool), 'істинність': isinstance(v, bool),
              '∅': v is None, 'ніщо': v is None, 'будь-що': True, 'список': isinstance(v, list), 'словник': isinstance(v, dict)}[t]
        if t == 'дата' and ok:
            try:
                _iso(v, pos)
            except NgrError:
                ok = False
        if not ok:
            errs.append(f'{where}: очікувалося {sv}, а не {kind(x)} {brief(x, 30)}')
            return
        if rest:
            if '..' in rest:
                lo, _, hi = rest.partition('..')
                try:
                    lo_, hi_ = (Decimal(lo) if lo.strip() else None), (Decimal(hi) if hi.strip() else None)
                except decimal.InvalidOperation:
                    raise NgrError(f'✓: межі «{safe(rest)}» — числа: 0..100, 1.., ..50', pos)
                n = len(v) if isinstance(v, (str, list, dict)) else v
                if not isinstance(n, NUM) or isinstance(n, bool):
                    raise NgrError(f'✓: межі «{safe(rest)}» — для числа, рядка чи списку', pos)
                if (lo_ is not None and n < lo_) or (hi_ is not None and n > hi_):
                    what = 'довжина ' if isinstance(v, (str, list, dict)) else ''
                    errs.append(f'{where}: {what}{fmt_num(n) if isinstance(n, NUM) else n} поза {rest}')
            elif show(x) not in rest.split('|'):
                errs.append(f'{where}: {brief(x, 30)} — не з переліку {rest}')
        return
    if isinstance(sv, list):
        if not isinstance(v, list):
            errs.append(f'{where}: очікувався список, а не {kind(x)}')
            return
        if len(sv) > 1:
            raise NgrError('✓: схема списку — 【S】 (один елемент-схема) або 【】 (будь-який список)', pos)
        if sv:
            for i, e in enumerate(v):
                check_schema(e, sv[0], f'{path}[{i}]', errs, pos, depth + 1)
                if len(errs) > 50:
                    return
        return
    if isinstance(sv, dict):
        if not isinstance(v, dict):
            errs.append(f'{where}: очікувався словник, а не {kind(x)}')
            return
        fields = {k.rstrip('?'): (k.endswith('?'), s_) for k, s_ in sv.items() if k != '…'}
        for k, (opt, s_) in fields.items():
            if k in v:
                check_schema(v[k], s_, f'{path}.{k}' if path else k, errs, pos, depth + 1)
            elif not opt:
                errs.append(f'{(path + ".") if path else ""}{k}: бракує поля')
        if '…' not in sv:
            extra = [k for k in v if k not in fields]
            if extra:
                errs.append(f'{where}: зайві поля {", ".join(safe(k) for k in extra[:5])} (дозволити — 「…」 「будь-що」)')
        return
    raise NgrError(f'✓: схема — рядок-тип, 【S】 або 『поле S …』, а не {kind(sch)}', pos)


XML_MAX_DEPTH = 500


def xml_name_ok(name):
    """Назва тегу чи атрибута для запису: підмножина XML Name — літера або «_», далі літери, цифри, «-», «.», «_»
    і знаки, що поєднуються; один префікс «x:» дозволено. Нічого, що змінило б будову документа (суд 8)."""
    parts = name.split(':')
    if len(parts) > 2:
        return False
    for p in parts:
        if not p or not (p[0].isalpha() or p[0] == '_'):
            return False
        for ch in p[1:]:
            if not (ch.isalnum() or ch in '-._' or unicodedata.category(ch) in ('Mn', 'Mc')):
                return False
    return True


def xml_char_bad(s):
    """Перший символ, якого не може бути в XML 1.0 (керівні, крім \\t \\n \\r; сурогати; U+FFFE/FFFF), або None."""
    for ch in s:
        o = ord(ch)
        if (o < 0x20 and ch not in '\t\n\r') or 0xD800 <= o <= 0xDFFF or o in (0xFFFE, 0xFFFF):
            return ch
    return None


def xml_parse(text, pos, max_size, charge):
    """XML → елемент (словник): тег (без простору імен), простір (якщо є), атрибути, текст (власний, без країв), діти.
    DTD і сутності заборонено (XXE, «мільярд сміхів»): у документах даних вони не потрібні. Заборону ставить сам
    розбирач — <!DOCTYPE у коментарі чи CDATA не заважає (суд 8)."""
    import xml.parsers.expat as expat
    charge(len(text))

    def forbid(*a):
        raise NgrError('χ: DTD і сутності (<!DOCTYPE, <!ENTITY) заборонено — небезпечні (XXE, «мільярд сміхів»)', pos)

    def local(name):               # expat з простором: «uri}назва»
        return (name.rsplit('}', 1)[1], name.split('}', 1)[0]) if '}' in name else (name, None)
    stack, top = [], []            # [словник, частини тексту, діти]

    def start(name, attrib):
        if len(stack) >= XML_MAX_DEPTH:
            raise NgrError(f'χ: вкладеність глибша за {XML_MAX_DEPTH}', pos)
        charge(1)
        tag, ns = local(name)
        attrs = {}
        for k, v in attrib.items():
            nm = local(k)[0]
            if nm in attrs:          # p:x і q:x — не зливати мовчки (суд 8)
                raise NgrError(f'χ: у «{safe(tag)}» два атрибути «{safe(nm)}» з різних просторів імен — '
                               f'назви атрибутів тут без простору, тож їх не розрізнити', pos)
            attrs[nm] = V(v)
        d = {'тег': V(tag)}
        if ns:
            d['простір'] = V(ns)
        d['атрибути'] = V(attrs)
        stack.append((d, [], []))

    def end(name):
        d, parts, kids = stack.pop()
        d['текст'] = V(''.join(parts).strip())
        d['діти'] = V(kids)
        (stack[-1][2] if stack else top).append(V(d))

    def chars(data):
        if stack:
            stack[-1][1].append(data)
    p = expat.ParserCreate(namespace_separator='}')
    p.StartDoctypeDeclHandler = forbid
    p.EntityDeclHandler = forbid
    p.StartElementHandler, p.EndElementHandler, p.CharacterDataHandler = start, end, chars
    try:
        p.Parse(text.removeprefix('\ufeff'), True)
    except expat.ExpatError as e:
        raise NgrError(f'χ: не XML ({expat.errors.messages[e.code]}: рядок {e.lineno}, стовпець {e.offset})', pos)
    if len(top) != 1:
        raise NgrError('χ: не XML (немає кореневого елемента)', pos)
    res = top[0]
    if res.n > max_size:
        raise NgrError(f'χ: документ завеликий (понад --розмір {max_size})', pos)
    return res


def xml_write(el, pos, charge):
    """Елемент (словник з тег / атрибути / текст / діти) → рядок XML. Назви — лише XML Name, керівних символів
    немає: дані не змінять будови документа, а χ прочитає записане назад (суд 8)."""
    import xml.etree.ElementTree as ET

    def value(v, what, tag):
        s = show(v)
        bad = xml_char_bad(s)
        if bad is not None:
            raise NgrError(f'χ: {what} елемента «{safe(tag)}» має символ U+{ord(bad):04X}, якого не буває в XML', pos)
        return s

    def build(x, depth, parent_ns=None):
        if depth > XML_MAX_DEPTH:
            raise NgrError(f'χ: вкладеність глибша за {XML_MAX_DEPTH}', pos)
        charge(1)
        if not isinstance(x.v, dict) or not isinstance(x.v.get('тег', V(None)).v, str):
            raise NgrError('χ: елемент — словник із 「тег」 (рядок) і, за бажанням, 「атрибути」 「текст」 「діти」', pos)
        d = x.v
        tag = d['тег'].v
        if not xml_name_ok(tag):
            raise NgrError(f'χ: «{safe(tag)}» — не назва тегу XML (літера чи _, далі літери, цифри, - . _)', pos)
        attrs = d.get('атрибути', V({})).v
        if not isinstance(attrs, dict):
            raise NgrError(f'χ: 「атрибути」 елемента «{safe(tag)}» — словник', pos)
        for k in attrs:
            if not xml_name_ok(k) or k == 'xmlns' or k.startswith('xmlns:'):
                raise NgrError(f'χ: «{safe(k)}» — не назва атрибута XML (у «{safe(tag)}»; простір — ключем 「простір」)', pos)
        node = ET.Element(tag, {k: value(v, f'атрибут «{safe(k)}»', tag) for k, v in attrs.items()})
        ns = d.get('простір', V(None)).v
        if isinstance(ns, str) and ns != parent_ns:
            node.set('xmlns', value(V(ns), 'простір', tag))
        t = d.get('текст', V('')).v
        node.text = value(V(t), 'текст', tag) if t not in (None, '') else None
        kids = d.get('діти', V([])).v
        if not isinstance(kids, list):
            raise NgrError(f'χ: 「діти」 елемента «{safe(tag)}» — список', pos)
        for k in kids:
            node.append(build(k, depth + 1, ns if isinstance(ns, str) else parent_ns))
        return node
    try:
        return ET.tostring(build(el, 1), encoding='unicode')
    except ValueError as e:
        raise NgrError(f'χ: {e}', pos)


XPATH_HELP = ('є: a/b, //b, *, [n], [@атр=\'x\'], [дитина=\'x\'], …/@атр, //@атр, /a… від самого елемента; '
              'текст — §e 「текст」, батька й text() немає')


def xml_path(root, path, pos, charge):
    """↘: підмножина XPath над елементами з χ — як у XPath: вузли без повторів, у порядку документа; [n] — n-й серед
    своїх сусідів; //b від кореня бачить і сам корінь. Усе поза підмножиною — помилка, не тихий 【】; кожен
    відвіданий вузол — крок (суд 8)."""
    import re as _re
    if not path:
        raise NgrError('↘: порожній шлях', pos)

    def bad(what):
        raise NgrError(f'↘: {what} — поза підмножиною XPath ({XPATH_HELP})', pos)
    name_re = r'(?:\*|[^\W\d][\w.\-]*(?::[^\W\d][\w.\-]*)?)'
    cond_re = r"\[\s*(?:\d+|@?[^\W\d][\w.\-]*(?::[^\W\d][\w.\-]*)?\s*=\s*(?:'[^']*'|\"[^\"]*\"))\s*\]"
    tok = _re.fullmatch(rf'((?:/|//)?)((?:{name_re}(?:{cond_re})*)(?:(?:/|//){name_re}(?:{cond_re})*)*)?'
                        rf'(?:(^|/|//)@({name_re}))?', path)
    only = _re.fullmatch(rf'(//|/)?@({name_re})', path)     # лише атрибут: @a, //@a (жадібний розбір нижче
    if only:                                                  # прочитав би «//@a» як «/» + «/@a»)
        lead, body, attr_sep, attr = '', '', only.group(1) or '', only.group(2)
    elif not tok or (not tok.group(2) and tok.group(4) is None):
        bad(f'шлях «{safe(path)}»')
    else:
        lead, body, attr_sep, attr = tok.group(1), tok.group(2) or '', tok.group(3), tok.group(4)
    if attr == '*':
        bad('@*')
    steps = []                     # (вниз_будь-де, локальна назва, [умови])
    for sep, step in _re.findall(rf'(^|/|//)({name_re}(?:{cond_re})*)', body):
        nm = _re.match(name_re, step).group(0)
        conds = _re.findall(r'\[([^\]]*)\]', step[len(nm):])
        steps.append((sep == '//', nm.split(':')[-1], conds))
    absolute = lead == '/'
    if lead == '//' and steps:
        steps[0] = (True,) + steps[0][1:]

    def check(e):
        charge(1)
        if not isinstance(e.v, dict) or not isinstance(e.v.get('тег', V(None)).v, str):
            raise NgrError('↘: вузол — не елемент (словник із 「тег」 — рядок)', pos)
        for key, typ, tn in (('атрибути', dict, 'словник'), ('діти', list, 'список'), ('текст', str, 'рядок')):
            if key in e.v and not isinstance(e.v[key].v, typ):
                raise NgrError(f'↘: 「{key}」 елемента «{safe(e.v["тег"].v)}» — {tn}', pos)
        return e

    def kids(e):
        k = e.v.get('діти')
        return [check(x) for x in k.v] if k is not None else []

    def attrs(e):
        a = e.v.get('атрибути')
        return a.v if a is not None else {}

    def text_of(e):
        t = e.v.get('текст')
        return t.v if t is not None else ''

    order = {}                     # id → порядок документа (глибина спершу, як у XPath)
    stack = [check(root)]
    while stack:
        e = stack.pop()
        if id(e) not in order:
            order[id(e)] = len(order)
            stack.extend(reversed(kids(e)))

    def ok(e, cond, idx):
        cond = cond.strip()
        if cond.isdigit():
            return idx == int(cond)
        mm = _re.fullmatch(r"(@?)([^=\s]+)\s*=\s*(?:'([^']*)'|\"([^\"]*)\")", cond)
        want = mm.group(3) if mm.group(3) is not None else mm.group(4)
        name = mm.group(2).split(':')[-1]
        if mm.group(1):
            v = attrs(e).get(name)
            return v is not None and v.v == want
        return any(k.v['тег'].v == name and text_of(k) == want for k in kids(e))

    def uniq(nodes):
        seen, out = set(), []
        for e in nodes:
            if id(e) not in seen:
                seen.add(id(e))
                out.append(e)
        return sorted(out, key=lambda e: order.get(id(e), 0))

    # контекст: «документ» над коренем, щоб //b і /a бачили сам корінь
    doc = V({'тег': V(''), 'діти': V([root])})
    cur = [doc] if (absolute or lead == '//' or (not steps and attr_sep == '//')) else [root]

    def self_or_below(nodes):      # нащадки-або-сам кожного; спільні піддерева — один раз
        seen, out = set(), []
        stack = list(reversed(nodes))
        while stack:
            e = stack.pop()
            if id(e) in seen:
                continue
            seen.add(id(e))
            out.append(e)
            stack.extend(reversed(kids(e)))
        return out
    for anywhere, name, conds in steps:
        parents = self_or_below(cur) if anywhere else cur
        nxt = []
        for p in parents:          # [n] — серед дітей одного батька, як у XPath
            sel = [k for k in kids(p) if name == '*' or k.v['тег'].v == name]
            for c in conds:
                sel = [k for i, k in enumerate(sel, 1) if ok(k, c, i)]
            nxt.extend(sel)
        cur = uniq(nxt)
    if attr is not None:
        if attr_sep == '//':
            cur = self_or_below(cur)
        name = attr.split(':')[-1]
        return V([attrs(e)[name] for e in cur if name in attrs(e)])
    return V(cur)


def _iso(s, pos):
    from datetime import date as _d
    if not isinstance(s, str):
        raise NgrError(f'◷: дата — рядок ISO (2026-10-15 або 2026-10-15T09:30:00), а не {type(s).__name__}', pos)
    import re as _re
    try:
        if not _re.fullmatch(r'\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})?)?', s):
            raise ValueError
        return _d.fromisoformat(s) if len(s) == 10 else datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        raise NgrError(f'◷: «{safe(s)[:40]}» — не дата ISO (2026-10-15 або 2026-10-15T09:30:00)', pos)


def date_op(x, y, pos):
    """◷ a b: дві дати — дні від a до b (ціле для дат, дріб із часом); дата й число — дата через стільки днів."""
    from datetime import date as _d, timedelta
    a = _iso(x, pos)
    if isinstance(y, str):
        b = _iso(y, pos)
        if type(a) is _d and type(b) is _d:
            return (b - a).days
        a2 = a if isinstance(a, datetime) else datetime(a.year, a.month, a.day)
        b2 = b if isinstance(b, datetime) else datetime(b.year, b.month, b.day)
        if (a2.tzinfo is None) != (b2.tzinfo is None):
            raise NgrError('◷: одна дата з часовим поясом, інша — без; додайте пояс до обох', pos)
        d = b2 - a2
        us = (d.days * 86400 + d.seconds) * 10 ** 6 + d.microseconds
        q = Decimal(us) / Decimal(86400 * 10 ** 6)
        return int(q) if q == q.to_integral_value() else q
    if isinstance(y, bool) or not isinstance(y, NUM):
        raise NgrError('◷: другий аргумент — дата (рядок ISO) або кількість днів (число)', pos)
    n = Decimal(repr(y)) if isinstance(y, float) else Decimal(y)
    try:
        if type(a) is _d and n == n.to_integral_value():
            return (a + timedelta(days=int(n))).isoformat()
        base = a if isinstance(a, datetime) else datetime(a.year, a.month, a.day)
        return (base + timedelta(microseconds=int(n * 86400 * 10 ** 6))).isoformat()
    except OverflowError:
        raise NgrError('◷: дата поза межами (рік 1–9999)', pos)


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


def _http(it, pos, tool, url, body=None):
    """HTTP до хоста з печатки (порти 80/443 або явний хост:порт), без логіна в адресі й без переадресацій."""
    u = url.v
    import urllib.parse
    import urllib.request                 # ліниво: мережа потрібна рідко, а імпорт коштує ~0,05 с запуску
    parts = urllib.parse.urlsplit(u) if isinstance(u, str) else None
    try:
        port = parts.port if parts else None
    except ValueError:
        port = -1
    allowed = it.caps[tool]
    ok = parts and parts.scheme in ('http', 'https') and not parts.username and not parts.password and (
        (parts.hostname in allowed and port in (None, 80, 443)) or f'{parts.hostname}:{port}' in allowed)
    if not ok:
        it.deny(агент=it.agent, назва=tool, адреса=safe(str(u)), причина='хост, порт чи адреса поза печаткою')
        raise NgrError(f'{tool}: «{u}» поза дозволеним ({", ".join(allowed)}; інший порт, ніж 80/443, '
                       f'треба дозволити явно як хост:порт; без логіна в адресі)', pos)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise NgrError(f'{tool}: переадресацію на «{newurl}» заборонено — дозвольте й візьміть ту адресу явно', pos)
    headers = {'User-Agent': f'nigredo/{VERSION}'}
    data = None
    if body is not None:                  # рядок — як текст; список чи словник — як JSON (точні десяткові)
        if isinstance(body.v, str):
            data, headers['Content-Type'] = body.v.encode(), 'text/plain; charset=utf-8'
        elif isinstance(body.v, (list, dict)):
            data, headers['Content-Type'] = to_json(body).encode(), 'application/json'
        else:
            raise NgrError(f'{tool}: тіло — рядок, список чи словник, а не {kind(body)}', pos)
    try:
        opener = urllib.request.build_opener(NoRedirect)
        q = urllib.parse.quote
        u = urllib.parse.urlunsplit(parts._replace(path=q(parts.path, safe='/%'), query=q(parts.query, safe='=&%+')))
        req = urllib.request.Request(u, data=data, headers=headers, method='POST' if body is not None else 'GET')
        with opener.open(req, timeout=30) as r:
            return V(r.read(1_000_000).decode('utf-8', 'replace'))
    except NgrError:
        raise
    except Exception as e:
        raise NgrError(f'{tool}: {e}', pos)


def t_fetch(it, pos, url):
    return _http(it, pos, 'мережа.взяти', url)


def t_send(it, pos, url, body):
    return _http(it, pos, 'мережа.послати', url, body)


# SQLite: лише дії з білого списку (authorizer) і жодного ATTACH (ліміт 0) — VACUUM INTO та ATTACH пишуть файли
# поза текою з печатки. Читання — ще й файл лише на читання. Кроки SQLite списуються з --кроки.
DB_STEPS_PER_SEC = 1_000_000         # кроків за секунду роботи запиту SQLite (на додачу до 10 за 1000 інструкцій)
DB_MAX_BYTES = 64 * 1024 * 1024        # найбільша база для бд.писати
DB_INFO_PRAGMAS = {'table_info', 'table_xinfo', 'table_list', 'index_list', 'index_info', 'index_xinfo',
                   'foreign_key_list'}
def _db_acts():
    import sqlite3 as q                  # іменовані сталі SQLite, а не числа (суд 7: 13/14 замість 16/17)
    read = {q.SQLITE_READ, q.SQLITE_SELECT, q.SQLITE_FUNCTION, q.SQLITE_RECURSIVE}
    write = read | {q.SQLITE_INSERT, q.SQLITE_UPDATE, q.SQLITE_DELETE, q.SQLITE_CREATE_TABLE, q.SQLITE_DROP_TABLE,
                    q.SQLITE_ALTER_TABLE, q.SQLITE_CREATE_INDEX, q.SQLITE_DROP_INDEX, q.SQLITE_REINDEX,
                    q.SQLITE_CREATE_VIEW, q.SQLITE_DROP_VIEW, q.SQLITE_CREATE_TRIGGER, q.SQLITE_DROP_TRIGGER}
    return read, write


def _db(it, pos, tool, p, sql, params, write):
    import sqlite3
    import time
    import urllib.request
    real = _path_ok(it, tool, p.v, pos, write=write)
    if not isinstance(sql.v, str):
        raise NgrError(f'{tool}: запит має бути рядком', pos)
    if not isinstance(params.v, list):
        raise NgrError(f'{tool}: параметри — список (для ? у запиті), а не {kind(params)}', pos)
    args = []
    for x in params.v:              # дробове — текстом, щоб не втратити точність (колонка REAL/NUMERIC перетворить)
        v = x.v
        if isinstance(v, bool) or isinstance(v, int) or v is None or isinstance(v, str):
            args.append(int(v) if isinstance(v, bool) else v)
        elif isinstance(v, (Decimal, float)):
            args.append(int(v) if v == int(v) and abs(v) < 2 ** 63 else str(v))
        else:
            raise NgrError(f'{tool}: параметр — рядок, число, істинність чи ∅, а не {kind(x)}', pos)
    acts = _db_acts()[1 if write else 0]

    def auth(action, a1, a2, db, view):
        if action == 31 and (a2 or '').lower() == 'load_extension':
            return sqlite3.SQLITE_DENY
        if action in acts or (action == 19 and a1 in DB_INFO_PRAGMAS):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    if not write and not os.path.isfile(real):
        raise NgrError(f'{tool}: немає такого файлу: {p.v}', pos)
    deadline = min(time.monotonic() + 30, getattr(it, 'par_deadline', None) or float('inf'))   # у ‖ — спільні 30 с

    last = [time.monotonic()]

    def progress():                 # ~1000 інструкцій SQLite ≈ 10 кроків, і ще кроки за часом потоку: у ‖ потоки
        now = time.monotonic()      # змагаються, тож лише «за інструкції» межа слабшала б у рази (суд 7)
        it.steps_left -= 10 + int((now - last[0]) * DB_STEPS_PER_SEC)
        last[0] = now
        return it.steps_left < 0 or time.monotonic() > deadline
    try:
        con = sqlite3.connect(f'file:{urllib.request.pathname2url(real)}?mode={"rwc" if write else "ro"}', uri=True,
                              isolation_level=None, timeout=5)
    except sqlite3.Error as e:
        raise NgrError(f'{tool}: {e}: {p.v}', pos)
    try:
        con.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
        con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 4 * it.max_size)      # одне значення — не більше за --розмір (суд 7)
        con.execute(f'PRAGMA hard_heap_limit = {max(64 << 20, 32 * it.max_size)}')   # і памʼять самого SQLite (суд 7)
        if write:                        # база не росте без меж (zeroblob заповнив би диск телефона)
            page = con.execute('PRAGMA page_size').fetchone()[0]
            con.execute(f'PRAGMA max_page_count = {DB_MAX_BYTES // page}')
        con.set_authorizer(auth)
        con.set_progress_handler(progress, 1000)
        try:
            before = con.total_changes
            cur = con.execute(sql.v, args)
            if write:                       # усі змінені рядки (зокрема з RETURNING і тригерами), а не rowcount
                cur.fetchall()
                return V(con.total_changes - before)
            cols = [d[0] for d in cur.description or []]
            if len(set(cols)) != len(cols):
                raise NgrError(f'{tool}: однакові назви стовпців ({", ".join(cols)}) — дайте різні через AS', pos)
            rows, size = [], 1
            for r in cur:
                row = {}
                for k, x in zip(cols, r):
                    if isinstance(x, bytes):
                        raise NgrError(f'{tool}: стовпець «{k}» — двійкові дані; візьміть hex({k})', pos)
                    if isinstance(x, float) and (x != x or x in (float('inf'), float('-inf'))):
                        raise NgrError(f'{tool}: стовпець «{k}» — не число ({x}); SQLite переповнився', pos)
                    row[k] = V(Decimal(repr(x)) if isinstance(x, float) else x)
                rows.append(V(row))
                size += rows[-1].n
                if size > it.max_size:
                    raise NgrError(f'{tool}: відповідь завелика (понад --розмір {it.max_size}); додайте LIMIT', pos)
            return V(rows)
        except MemoryError:
            raise NgrError(f'{tool}: запит перевищив межу памʼяті SQLite — зменште вибірку (LIMIT, менші значення)', pos)
        except sqlite3.Error as e:
            if it.steps_left < 0:
                raise Fatal('перевищено ліміт кроків (--кроки)', pos)
            if time.monotonic() > deadline:
                raise NgrError(f'{tool}: запит довший за 30 с', pos)
            denied = any(w in str(e) for w in ('not authorized', 'authorization denied', 'too many attached',
                                               'readonly database'))
            if denied:
                it.deny(агент=it.agent, назва=tool, шлях=safe(p.v), запит=safe(sql.v)[:500],
                         причина='дія SQLite поза дозволеним')
            msg = 'дія поза дозволеним (лише ' + ('SELECT' if not write else 'SELECT, INSERT, UPDATE, DELETE, '
                                                  'CREATE/DROP/ALTER') + '; без ATTACH, VACUUM, PRAGMA)' \
                if denied else 'лише одна інструкція SQL за раз' if 'one statement at a time' in str(e) \
                else sql_err(str(e))
            raise NgrError(f'{tool}: {msg}', pos)
    finally:
        con.close()


SQL_ERRORS = [('Incorrect number of bindings', 'кількість «?» у запиті не дорівнює кількості параметрів'),
              ('no such table', 'немає такої таблиці'), ('no such column', 'немає такого стовпця'),
              ('syntax error', 'синтаксична помилка SQL'), ('UNIQUE constraint failed', 'порушено унікальність'),
              ('NOT NULL constraint failed', 'порожнє значення там, де заборонено'), ('database is locked', 'база зайнята'),
              ('database or disk is full', 'база досягла межі розміру'), ('string or blob too big', 'значення більше за --розмір'), ('unable to open', 'не вдалося відкрити базу')]


def sql_err(msg):
    for en, uk in SQL_ERRORS:
        if en in msg:
            return f'{uk} ({msg})'
    return msg


def t_db_read(it, pos, p, sql, params):
    return _db(it, pos, 'бд.читати', p, sql, params, False)


def t_db_write(it, pos, p, sql, params):
    return _db(it, pos, 'бд.писати', p, sql, params, True)


PROC_CAP, PROC_TIME = 1_000_000, 60
DRY_SUPPRESS = {'файл.писати': None, 'бд.писати': 0, 'мережа.послати': '‹сухо›', 'мережа.взяти': '‹сухо›',
                'процес': '‹сухо›', 'агент': '‹сухо›'}   # взяти теж: адреса сама виносить дані назовні (суд 7)
PAR_MAX = 8                    # ‖: найбільше одночасних дій
PARALLEL_TOOLS = ('мережа.взяти', 'мережа.послати', 'агент', 'процес', 'бд.читати', 'файл.читати', 'файл.список',
                  'оракул', 'час')   # ‖: дії без спільного стану (не жереб; не запис — порядок записів був би випадковим)


def cmd_within(s, g):
    """Команда s — та сама або вужча за g: g — початок s за словами («git status» ⊆ «git»)."""
    a, b = s.split(' '), g.split(' ')
    return a[:len(b)] == b


def resolve_cmd(name):
    """(шлях, яким запускати, справжній шлях) виконуваного файла: абсолютний або з абсолютних тек PATH (жодної
    поточної теки). Запускати — через знайдене імʼя (симлінк), щоб і скрипт, і busybox бачили дозволену назву;
    перевіряти — і його, і ціль (None, якщо немає)."""
    import shutil
    if os.path.isabs(name):
        found = name if os.path.isfile(name) and os.access(name, os.X_OK) else None
    else:
        path = os.pathsep.join(d for d in os.environ.get('PATH', '').split(os.pathsep) if os.path.isabs(d))
        found = shutil.which(name, path=path) if '/' not in name else None
    if not found:
        return None
    via = os.path.join(os.path.realpath(os.path.dirname(os.path.abspath(found))), os.path.basename(found))
    return via, os.path.realpath(found)


def t_proc(it, pos, argv):
    if not isinstance(argv.v, list) or not argv.v or not all(isinstance(x.v, str) for x in argv.v):
        raise NgrError('процес: команда — непорожній список рядків 【「git」 「status」】 (без оболонки)', pos)
    args = [x.v for x in argv.v]
    if any('\0' in a for a in args):
        raise NgrError('процес: нульовий символ в аргументі', pos)
    if not any(args[:len(g.split(' '))] == g.split(' ') for g in it.caps['процес']):
        it.deny(агент=it.agent, назва='процес', аргументи=[safe(a) for a in args],
                 причина='команди немає в печатці')
        raise NgrError(f'процес: «{safe(" ".join(args))}» поза дозволеним ({", ".join(it.caps["процес"])}; '
                       f'дозвіл — початок команди за словами)', pos)
    found = resolve_cmd(args[0])
    if found is None:
        raise NgrError(f'процес: команди «{safe(args[0])}» немає (шукаю лише в абсолютних теках PATH)', pos)
    via, exe = found
    if any(inside(x, os.path.realpath(os.path.join(it.cwd, w))) for x in found
           for t in WRITE_TOOLS for w in it.seal_caps.get(t, [])):    # ні симлінк, ні ціль — не з теки запису
        raise NgrError(f'процес: «{safe(via)}» чи його ціль лежить у теці, куди програмі дозволено писати', pos)
    import signal
    import subprocess                     # ліниво: процеси потрібні рідко, а імпорт коштує ~10 мс запуску
    try:
        # argv[0] — як дозволено, а не ціль симлінка: busybox/toybox обирають команду за argv[0] (суд 7)
        pr = subprocess.Popen(args, executable=via, cwd=it.cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, start_new_session=True)
    except OSError as e:
        raise NgrError(f'процес: {e}', pos)
    bufs, over = (bytearray(), bytearray()), []

    def kill():
        try:
            os.killpg(pr.pid, signal.SIGKILL)
        except OSError:
            pass

    def pump(f, buf):
        for chunk in iter(lambda: f.read1(65536), b''):
            if len(buf) + len(chunk) > PROC_CAP:
                over.append(1)
                kill()
                return
            buf += chunk
    ts = [threading.Thread(target=pump, args=(f, b), daemon=True) for f, b in zip((pr.stdout, pr.stderr), bufs)]
    for t in ts:
        t.start()
    try:
        code = pr.wait(timeout=PROC_TIME)
    except subprocess.TimeoutExpired:
        kill()
        pr.wait()
        raise NgrError(f'процес: «{safe(args[0])}» довший за {PROC_TIME} с — зупинено', pos)
    finally:
        for t in ts:
            t.join(5)
        kill()                       # нащадки, що лишилися після виходу, — теж
    if over:
        raise NgrError(f'процес: вивід понад {PROC_CAP // 1_000_000} МБ — зупинено', pos)
    out, err = (b.decode('utf-8', 'replace') for b in bufs)
    if code:
        raise NgrError(f'процес: «{safe(args[0])}» завершився з кодом {code}' + (f': {safe(err.strip()[-500:])}'
                                                                                   if err.strip() else ''), pos)
    return V(out)


def t_agent(it, pos, name, prompt):
    import subprocess
    if name.v not in it.caps['агент']:
        raise NgrError(f'агент: «{name.v}» поза дозволеними ({", ".join(it.caps["агент"])})', pos)
    try:
        reg = {a['name']: a['path'] for a in json.load(open(AGENTS_REGISTRY, encoding='utf-8'))['agents']}
    except OSError:
        raise NgrError('агент: немає реєстру агентів', pos)
    if name.v not in reg:
        raise NgrError(f'агент: «{name.v}» немає в реєстрі', pos)
    try:
        q = show(prompt)
        q = ' ' + q if q.startswith('-') else q      # запит не може стати прапорцем claude
        r = subprocess.run(['claude', '-p', q], cwd=reg[name.v], capture_output=True, text=True, timeout=900,
                           stdin=subprocess.DEVNULL)
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
    'файл.читати': (1, '🜔читати шлях → рядок', 'прочитати текстовий файл', True, 'тека', t_read),
    'файл.писати': (2, '🜔писати шлях текст → ∅', 'записати (перезаписати) текстовий файл', True, 'тека', t_write),
    'файл.список': (1, '🜔список тека → список', 'імена в теці', True, 'тека', t_list),
    'бд.читати': (3, '🜔бд.читати шлях 「SELECT … ?」 【параметри】 → список словників', 'запит SQLite лише на читання '
                  '(лише SELECT і довідкові PRAGMA table_info, index_list…; файл відкрито лише на читання)', True, 'тека', t_db_read),
    'бд.писати': (3, '🜔бд.писати шлях 「INSERT … ?」 【параметри】 → змінено рядків', 'зміна SQLite (INSERT UPDATE DELETE, '
                  'CREATE/DROP/ALTER; без ATTACH, VACUUM, PRAGMA); файл створюється, якщо нема', True, 'тека', t_db_write),
    'мережа.взяти': (1, '🜔взяти url → рядок', 'HTTP GET (до 1 МБ, 30 с; адреса — повністю в сліді: даними в адресі '
                     'теж можна поділитися з хостом, тож дозволяйте лише хости, яким довіряєте)', True, 'хост', t_fetch),
    'мережа.послати': (2, '🜔послати url тіло → рядок', 'HTTP POST: тіло-рядок — як текст, список чи словник — як JSON; '
                       'відповідь до 1 МБ, 30 с (окремий дозвіл: надсилання даних назовні)', True, 'хост', t_send),
    'процес': (1, '🜔процес 【「git」 「status」】 → вивід', 'запустити команду з печатки без оболонки (60 с, вивід до '
               '1 МБ; не 0 — помилка). Дозвіл — початок команди: 「процес:git status」 не дає git push. Команда діє з правами '
               'процесу: межі тек Nigredo на неї не діють (git, make, npm у теці, куди можна писати, — довільний код; команда, що '
               'читає файли, прочитає й ключ власника — тоді слід можна підробити)', True,
               'команда', t_proc),
    'агент': (2, '🜔агент 「імʼя」 「запит」 → рядок', 'спитати справжнього агента з реєстру лаунчера '
              '(claude -p у його теці; він діє з власними правами)', True, 'імʼя', t_agent),
}


# короткі назви інструментів (у печатці, 🜔 і дозволах власника) — синоніми повних; у звітах, сліді — повні
TOOL_ALIASES = {'читати': 'файл.читати', 'писати': 'файл.писати', 'список': 'файл.список', 'взяти': 'мережа.взяти',
                'послати': 'мережа.послати'}
TOOL_SHORT = {v: k for k, v in TOOL_ALIASES.items()}
WRITE_TOOLS = ('файл.писати', 'бд.писати')          # теки, куди програма може писати (і звідки не беруть код)


def read_allowlist(path, cwd=None, prog=None):
    """«дозволено» — для всіх програм; «для_тек» — {"/абсолютна/тека": [дозволи]} лише для програм у цій теці."""
    try:
        data = json.load(open(path, encoding='utf-8'))
        lst = [canon_perm(a) for a in data.get('дозволено', [])]
        per_dir = data.get('для_тек', {})
        if not isinstance(per_dir, dict):
            raise ValueError('«для_тек» має бути словником тека → список')
        common = list(lst)
        for d, extra in per_dir.items():
            if not isinstance(extra, list):
                raise ValueError(f'«для_тек» → «{d}»: потрібен список')
            extra = [canon_perm(a) for a in extra]
            if cwd and os.path.isabs(os.path.expanduser(d)) and inside(cwd, os.path.expanduser(d)):
                # програма, що лежить там, куди програмам дозволено писати, могла бути написана програмою —
                # права теки їй не належать
                writable = [split_quota(e)[0].partition(':')[2].strip() for e in common + extra
                            if e.partition(':')[0].strip() in WRITE_TOOLS]
                if prog and any(w and os.path.isabs(os.path.expanduser(w)) and inside(prog, os.path.expanduser(w))
                                for w in writable):
                    continue
                lst += extra
        if not all(isinstance(x, str) for x in lst):
            raise ValueError('дозволи мають бути рядками')
        return lst
    except (OSError, ValueError, AttributeError) as e:
        raise Refused(f'не вдалося прочитати дозволи {path}: {e}')


def load_allowlist(narrow=None, cwd=None, prog=None):
    """Дозволи власника — OWNER_HOME/дозволи.json (без нього — лише іграшкові інструменти).
    --дозволи ФАЙЛ лише звужує їх: лишається те, що є в обох."""
    try:
        return _load_allowlist(narrow, cwd, prog)
    except StaticError as e:           # квота «≤N» з помилкою у файлі дозволів
        raise Refused(f'дозволи: {e.msg}')


def _load_allowlist(narrow, cwd, prog):
    path = os.path.join(OWNER_HOME, 'дозволи.json')
    if os.path.exists(path):
        owner = read_allowlist(path, cwd, prog)
        source = f'{path} (sha256 {hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]})'
    else:
        owner, source = list(DEFAULT_ALLOWED), '(файлу власника немає: лише іграшкові інструменти)'
    quotas = owner_quotas(owner)
    if narrow:                         # звуження: права — спільні; квоти власника лишаються, свої — додаються (суд 8)
        extra = read_allowlist(narrow)
        kept = [a for a in extra if not check_allowlist(parse_caps(split_quota(a)[0]), owner, '/')]
        quotas += owner_quotas(kept)
        owner = [split_quota(a)[0] for a in kept]
        source += f'; звужено {narrow}'
    return Allowed(owner, quotas), source


class Allowed(list):
    """Дозволи власника (рядки) і квоти — окремо: звуження не скидає квот власника."""
    def __init__(self, items, quotas):
        super().__init__(items)
        self.quotas = list(quotas)


def owner_quotas(allowed):
    """[(інструмент, обмеження, N)] з дозволів власника «…≤N» (або вже зібрані — у Allowed)."""
    if isinstance(allowed, Allowed):
        return list(allowed.quotas)
    out = []
    for a in allowed:
        base, q = split_quota(canon_perm(a))
        if q is not None:
            t, _, sc = base.partition(':')
            out.append((t.strip(), sc.strip(), q))
    return out


def canon_perm(entry):
    """Дозвіл у повній формі: «читати:дані» → «файл.читати:дані»."""
    if not isinstance(entry, str):
        return entry
    name, sep, scope = entry.partition(':')
    full = TOOL_ALIASES.get(name.strip())
    return f'{full}{sep}{scope}' if full else entry


def parse_caps(entry):
    name, _, scope = canon_perm(entry).partition(':')
    name = name.strip()
    if name not in TOOLS:
        return {name: []}
    return {name: [scope.strip()] if scope.strip() else []}


def inside(path, base):
    path, base = os.path.realpath(path), os.path.realpath(base)
    return path == base or path.startswith(base + os.sep)


def intersect_caps(a, b, cwd):
    """Права, що є і в a, і в b (теки — за справжніми шляхами; хости й імена — точний збіг)."""
    out = {}
    for t, sa in a.items():
        if t not in b:
            continue
        sb = b[t]
        if not TOOLS[t][3]:
            out[t] = []
            continue
        if TOOLS[t][4] == 'тека':
            real = lambda x: os.path.realpath(os.path.join(cwd, x))      # noqa: E731
            keep = [x for x in sa if any(inside(real(x), real(y)) for y in sb)] + \
                   [y for y in sb if any(inside(real(y), real(x)) for x in sa)]
        elif TOOLS[t][4] == 'команда':
            keep = [x for x in sa if any(cmd_within(x, y) for y in sb)] + [y for y in sb if any(cmd_within(y, x) for x in sa)]
        else:
            keep = [x for x in sa if x in sb]
        if keep:
            out[t] = sorted(set(keep))
    return out


def delegations(prog):
    """Пари (дозволи батька, дозволи субагента, імʼя) для всіх 🜁 у програмі."""
    out = []

    def walk(n, parent):
        if isinstance(n, tuple) and n:
            if n[0] == 'seal':
                parent = n[3]
            if n[0] == 'import':
                out.append((parent, n[4][2][0][3], f'модуль {n[2]}'))
                walk(n[4], n[4][2][0][3])
                return
            if n[0] == 'deleg':
                out.append((parent, n[4], n[2]))
                walk(n[5], n[4])
                return
            for x in n:
                walk(x, parent)
        elif isinstance(n, list):
            for x in n:
                walk(x, parent)
    walk(prog, prog[2][0][3] if prog[2] and prog[2][0][0] == 'seal' else {})
    return out


def check_program(prog, allowed, cwd):
    """Печатка й печатки ВСІХ субагентів ⊆ дозволи власника; кожен субагент ⊆ батька за справжніми шляхами."""
    missing = check_allowlist(prog[2][0][3], allowed, cwd)
    writable = [os.path.realpath(os.path.join(cwd, os.path.expanduser(split_quota(a)[0].partition(':')[2].strip())))
                for a in allowed if a.partition(':')[0].strip() in WRITE_TOOLS]
    writable += [os.path.realpath(os.path.join(cwd, w)) for t in WRITE_TOOLS for w in prog[2][0][3].get(t, [])]

    def mods(n):
        if isinstance(n, tuple) and n:
            if n[0] == 'import':
                yield n
                yield from mods(n[4])
                return
            for x in n:
                yield from mods(x)
        elif isinstance(n, list):
            for x in n:
                yield from mods(x)
    for sc in prog[2][0][3].get('процес', []):       # виконуваний файл, який могла написати програма, — теж
        found = resolve_cmd(sc.split(' ')[0])
        if found and any(inside(x, w) for x in found for w in writable):
            missing.append(f'процес:{sc} ({safe(found[0])} чи його ціль лежить у теці, куди програмам дозволено писати)')
    for m in mods(prog):            # код, який могла написати програма, — не модуль (як «права теки» для теки запису)
        if any(inside(m[6], w) for w in writable):
            missing.append(f'модуль {safe(m[2])} лежить у теці, куди програмам дозволено писати')
    for parent, child, name in delegations(prog):
        who = safe(name) if name.startswith('модуль ') else f'субагент «{safe(name)}»'
        missing += [f'{m} ({who})' for m in check_allowlist(child, allowed, cwd)]
        for t, scopes in child.items():
            if TOOLS[t][4] != 'тека':
                continue
            for sc in scopes:
                rs = os.path.realpath(os.path.join(cwd, sc))
                if not any(inside(rs, os.path.realpath(os.path.join(cwd, p))) for p in parent.get(t, [])):
                    missing.append(f'{t}:{sc} ({who} виходить за межі батька)')
    return sorted(set(missing))


def check_allowlist(caps, allowed, cwd):
    """Печатка ⊆ дозволи власника. Теки — вкладеність, хости й агенти — точний збіг."""
    granted = {}
    for a in allowed:
        name, _, scope = split_quota(a)[0].partition(':')      # квота власника діє під час виконання
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
                elif TOOLS[tool][4] == 'команда':
                    ok = ok or cmd_within(s, g)
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
        self.alloc = 0
        self.steps_left, self.cwd = steps, os.path.abspath(cwd)
        self.out = out or sys.stdout
        self.memory, self.agent, self.caps, self.seal_caps = {}, 'головний', {}, {}
        self.modules = {}      # справжній шлях модуля → його імена (модуль виконується один раз)
        self.pc = 1.0          # впевненість контексту керування: усе, що створено тут, не впевненіше
        self.halt_c = 1.0      # канал завершення: після пройденої сумнівної 🜍 решта запуску не впевненіша
        self.mem_c = 1.0       # наскільки сумнівними були ключі, якими писали в памʼять
        self.try_stack = []    # для кожного ☂: найменша впевненість усього, що обчислено в його тілі
        self.world_c = 1.0     # наскільки сумнівно могли змінити зовнішній стан (жереб, файли, агенти, мережа)
        self.decided_c = 1.0   # найсумнівніше рішення в запуску: від нього залежить і тривалість (годинник)

        self.depth = 0
        self.defer_node = None  # тіло ‖, чий виклик інструмента відкладено
        self.tl = threading.local()   # для дії інструмента (і в потоці ‖): справжні шляхи, які він узяв
        self.ends = 0           # скільки записів «інструмент» уже зроблено (номер виклику для повтору)
        self.par_deadline = None   # ‖: спільний ліміт часу запитів SQLite
        self.last_call = None      # останній розпочатий виклик інструмента (для сліду внутрішньої помилки)
        self.quota_stack = []      # (хто, таблиця, лічильник): власник, печатка, модулі, субагенти (поки активні)
        self.quota_used = {}       # (лічильник, інструмент, обмеження) → скільки вже викликів
        self.quota_seq = 0         # кожен запуск субагента — свій лічильник (його квота — «поки він працює»)
        self.quota_lock = threading.Lock()
        self.replay = None      # --повторити: (записи «інструмент», сховище значень)
        self.dry = None         # --сухо: список придушених дій (записи, надсилання, процеси, агенти)

    def tool_begin(self, name, args, pos):
        """Перевірка прав, впевненість аргументів і запис «виклик» — до дії (для ‖ — по черзі, до паралельних дій)."""
        full = name in ('агент', 'мережа.взяти', 'мережа.послати', 'файл.писати', 'бд.писати', 'процес')  # те, що йде назовні, — у слід повністю
        targs = [trace_val(a, full) for a in args]
        if name not in self.caps:          # права — того, хто виконує зараз, а не того, хто написав функцію
            self.trace('заборонено', агент=self.agent, назва=name, аргументи=targs,
                       причина='інструмента немає в дозволах цього агента')
            raise NgrError(f'агент «{self.agent}» не має дозволу «{name}» (функцію з інструментом '
                           f'викликано там, де цього дозволу немає)', pos)
        ac = min([self.cpc] + [a.c for a in args])
        self.taint(ac)
        self.last_call = {'назва': name, 'аргументи': targs}   # якщо інтерпретатор упаде (код 4) — у слід
        hits = self.check_quota(name, args, targs, pos)
        if name in WORLD_WRITERS:
            self.trace('виклик', агент=self.agent, назва=name, аргументи=targs)   # до дії: видно, навіть якщо процес уб'ють
            self.world_c = min(self.world_c, ac)
        return {'назва': name, 'аргументи': args, 'слід': targs, 'ac': ac, 'pos': pos, 'агент': self.agent, 'квота': hits}

    def quota_covers(self, tool, scope, args):
        """Чи підпадає виклик під обмеження scope (для квоти): тека — шлях у ній, хост — та адреса, імʼя, команда."""
        kind_ = TOOLS[tool][4] if TOOLS[tool][3] else ''
        if not scope or not kind_:
            return True
        a0 = args[0].v if args else None
        if kind_ == 'тека' and isinstance(a0, str):
            base = os.path.realpath(os.path.join(self.cwd, scope))
            cands = [os.path.realpath(os.path.join(self.cwd, a0)), os.path.realpath(os.path.join(base, a0))]
            return any(inside(c, base) for c in cands)
        if kind_ == 'хост' and isinstance(a0, str):
            import urllib.parse
            try:
                u = urllib.parse.urlsplit(a0)
                return scope in (u.hostname, f'{u.hostname}:{u.port}')
            except ValueError:
                return False
        if kind_ == 'імʼя':
            return a0 == scope
        if kind_ == 'команда' and isinstance(a0, list):
            return [x.v for x in a0][:len(scope.split(' '))] == scope.split(' ')
        return False

    def check_quota(self, name, args, targs, pos):
        """Квоти «≤N»: кожна таблиця (власник, печатка, активні субагенти) рахує свої виклики; понад — відмова."""
        hits, seen = [], set()
        with self.quota_lock:
            for who, table, tok in self.quota_stack:
                if tok in seen:            # та сама таблиця двічі (рекурсія в модуль) — рахуємо раз
                    continue
                seen.add(tok)
                for (t, sc), limit in table.quotas.items():
                    if t == name and self.quota_covers(name, sc, args):
                        key = (tok, t, sc)
                        if self.quota_used.get(key, 0) >= limit:
                            # не порушення прав: межа, яку оголосили печатка, модуль, субагент чи власник (суд 8)
                            self.trace('квоту вичерпано', агент=self.agent, назва=name, аргументи=targs, чия=who,
                                       квота=f'{name}{":" + sc if sc else ""}≤{limit}')
                            raise NgrError(f'{name}: вичерпано квоту ({who}: «{name}{":" + sc if sc else ""}≤{limit}»)', pos)
                        hits.append(key)
            for key in hits:
                self.quota_used[key] = self.quota_used.get(key, 0) + 1
        return hits

    def quota_refund(self, hits):
        """Виклик не відбувся (відмова за правами, скасування в ‖) — квоту не списано."""
        with self.quota_lock:
            for key in hits or ():
                self.quota_used[key] -= 1

    def deny(self, **kw):
        """«Заборонено» з дії інструмента: дію не виконано — і квоту поверне tool_do."""
        self.tl.denied = True
        self.trace('заборонено', **kw)

    def tool_do(self, job):
        """Сама дія (у ‖ — у своєму потоці; записи сліду з потоку — у його буфер). У повторі — записане."""
        if self.replay is not None:
            return self.replayed(job)
        if self.dry is not None and job['назва'] in DRY_SUPPRESS:   # --сухо: дія не відбувається, результат невідомий
            self.dry.append((job['назва'], job['слід'], job['ac']))
            job['сухо'] = True
            return V(DRY_SUPPRESS[job['назва']], 0.0), None
        self.tl.paths = job['шляхи'] = []
        self.tl.denied = False
        try:
            return TOOLS[job['назва']][5](self, job['pos'], *job['аргументи']), None
        except (NgrError, Fatal) as e:
            if self.tl.denied:             # відмова за правами — виклику не було, квоту не списано (суд 8)
                self.quota_refund(job.get('квота'))
            return None, e
        finally:
            self.tl.paths = None

    def replayed(self, job):
        recs, store = self.replay
        i = job.get('№', self.ends)
        if i >= len(recs):
            raise Fatal(f'повтор розійшовся зі слідом: виклик №{i + 1} ({job["назва"]}) — у сліді їх лише {len(recs)}')
        r = recs[i]
        if r.get('назва') != job['назва'] or r.get('аргументи') != job['слід']:
            show_args = lambda a: safe(' '.join(x if isinstance(x, str) else '…' for x in a or []))[:120]   # noqa: E731
            raise Fatal(f'повтор розійшовся зі слідом на виклику №{i + 1}: у сліді {r.get("назва")} '
                        f'{show_args(r.get("аргументи"))}, а програма — {job["назва"]} {show_args(job["слід"])}')
        if 'помилка' in r:
            return None, NgrError(r['помилка'], job['pos'], float(r.get('впевненість', 1.0)))
        if r.get('значення') not in store:
            raise Fatal(f'повтор: значення виклику №{i + 1} немає у сховищі (СЛІД.дані) — слід записано без нього')
        return dec_v(store[r['значення']]), None

    def tool_end(self, job, outcome):
        res, err = outcome
        self.ends += 1
        if job.get('сухо'):                 # дію придушено: стан світу тепер не той, що був би (читання після — сумнівні)
            self.world_c = 0.0
        name, targs, ac = job['назва'], job['слід'], job['ac']
        if err is not None:
            if isinstance(err, Fatal):
                raise err
            err.c = min(err.c, ac, self.world_c if name in WORLD_READERS else 1.0)
            self.trace('інструмент', агент=job['агент'], назва=name, аргументи=targs, помилка=err.msg, впевненість=err.c)
            raise err
        if name not in ('оракул', 'час'):                    # інструмент міг упасти на сумнівному аргументі — і не впав
            self.halt_risk(ac, ('op', job['pos'], '☠', []))
        c = min([res.c, ac] + ([self.world_c] if name in WORLD_READERS else [])
                + ([self.decided_c] if name == 'час' else []))
        keep = getattr(self.trace, 'keep', None)
        stored = {'значення': keep(res)} if keep else {}     # сирий результат — для --повторити
        res = capc(res, c) if c < 1 else res
        self.taint(c)
        self.trace('інструмент', агент=job['агент'], назва=name, аргументи=targs, результат=trace_val(res), впевненість=c,
                   **stored, **({'сухо': 'не виконано'} if job.get('сухо') else {}),
                   **({'шлях': job['шляхи']} if job.get('шляхи') else {}))
        return res

    def parallel(self, lst, fn, pos, fnode):
        """‖ список λx 🜔інструмент …: аргументи — по черзі (друк, помилки, «виклик» у слід — у порядку елементів),
        дії — паралельно (до PAR_MAX потоків), результати й слід — у порядку елементів."""
        from concurrent.futures import ThreadPoolExecutor
        if not (isinstance(fn.v, Fn) and len(fn.v.params) == 1 and fn.v.body[0] == 'tool'
                and fn.v.body[2] in PARALLEL_TOOLS):        # до запуску це ловить перевірка; тут — друга межа
            raise NgrError('‖: тіло — рівно один виклик інструмента без спільного стану (λx 🜔взяти …)', pos)
        items = self.seq(lst, '‖', pos)
        saved, saved_node = self.pc, self.defer_node
        self.pc = min(saved, lst.s)
        self.defer_node = fn.v.body
        jobs = []
        try:
            for i, x in enumerate(items):
                jobs.append(self.each('‖', i, fn, [x], pos))
        except NgrError:                 # аргументи наступного елемента впали — уже розпочаті дії НЕ виконуються
            for j in jobs:
                self.quota_refund(j.v[1].get('квота'))      # не виконано — квоту не списано (суд 8)
                self.trace('скасовано', агент=j.v[1]['агент'], назва=j.v[1]['назва'], аргументи=j.v[1]['слід'],
                           причина='‖: помилка в аргументах іншого елемента — дію не виконано, квоту не списано')
            raise
        finally:
            self.pc, self.defer_node = saved, saved_node
        for i, j in enumerate(jobs):                         # номер виклику — порядок записів «інструмент»
            j.v[1]['№'] = self.ends + i
        trace = self.trace

        def run(job):
            tl = getattr(trace, 'tl', None)
            if tl is not None:
                tl.buf = []
            try:
                return self.tool_do(job), (tl.buf if tl is not None else [])
            finally:
                if tl is not None:
                    tl.buf = None
        import time
        self.par_deadline = time.monotonic() + 30     # один ліміт часу на всі запити ‖, а не 30 с кожному (суд 7)
        try:
            with ThreadPoolExecutor(max_workers=max(1, min(PAR_MAX, len(jobs)))) as ex:
                done = list(ex.map(run, [j.v[1] for j in jobs]))
        finally:
            self.par_deadline = None
        out, first = [], None
        for i, (j, (outcome, buf)) in enumerate(zip(jobs, done)):
            for event, data in buf:                          # записи з потоку — на своєму місці
                self.trace(event, **data)
            try:
                r = self.tool_end(j.v[1], outcome)
                out.append(capc(r, j.c) if j.c < r.c else r)
            except NgrError as e:
                if not e.where:
                    e.msg, e.where = f'‖, елемент №{i}: {e.msg}', True
                first = first or e                           # решта дій уже відбулася — у слід усе, потім помилка
        if first:
            raise first
        self.fn_effects(fnode, lst.s)
        self.halt_risk(lst.s, fnode, called=True)
        return mk(out, lst.s)

    def fn_effects(self, node, c):
        """Те саме для місця функції: λ — дивимося тіло; будь-що інше (∘, змінна) — невідомо, отже все."""
        if c < 1 and node[0] != 'lam':
            self.decided_c = min(self.decided_c, c)
            self.mem_c, self.world_c = min(self.mem_c, c), min(self.world_c, c)
        else:
            self.taint_effects((node,), c)

    def halt_risk(self, c, *nodes, called=False):
        """Канал завершення: код, що виконувався чи ні (або скільки разів) залежно від даних з впевненістю c і міг
        зупинити програму, — тоді те, що програма йде далі, теж знання про ці дані: решта запуску не впевненіша."""
        if c < 1 and any(may_stop(n, called) for n in nodes):
            self.halt_c = min(self.halt_c, c)

    @property
    def cpc(self):
        return min(self.pc, self.halt_c)

    def taint_effects(self, nodes, c):
        """Код, який міг виконатися чи ні залежно від даних з впевненістю c, міг змінити стан — отже стан сумнівний."""
        if c >= 1:
            return
        self.decided_c = min(self.decided_c, c)
        eff = set()
        for n in nodes:
            eff |= effects(n)
        if 'mem' in eff:
            self.mem_c = min(self.mem_c, c)
        if 'world' in eff:
            self.world_c = min(self.world_c, c)

    def taint(self, c):
        if c < 1:
            for i, t in enumerate(self.try_stack):
                if c < t:
                    self.try_stack[i] = c

    def sized(self, res, g, pos):
        """Межі памʼяті: одне значення, ціле, сумарно створене."""
        if res.n > self.max_size:
            raise Fatal(f'{g}: значення завелике (логічний розмір {res.n} > --розмір {self.max_size})', pos)
        if type(res.v) is int and res.v.bit_length() > MAX_INT_BITS:
            raise Fatal(f'{g}: число завелике (понад {MAX_INT_BITS} біт)', pos)
        if res.n > 1:
            self.work(res.n, pos)
            self.alloc += res.n
            if self.alloc > ALLOC_FACTOR * self.max_size:
                raise Fatal(f'сумарно створено забагато ({self.alloc} > {ALLOC_FACTOR} × --розмір)', pos)
        return res

    def work(self, units, pos):
        self.steps_left -= units // 64
        if self.steps_left < 0:
            raise Fatal('перевищено ліміт кроків (--кроки)', pos)

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
            raise NgrError(f'очікувалася функція, а не {kind(fn)}', pos, min(fn.c, self.cpc))
        f = fn.v
        if len(f.params) != len(args):
            raise NgrError(f'функція чекає {len(f.params)} аргумент(и), а дано {len(args)}', pos, min(fn.c, self.cpc))
        if fn.c >= 1 and f.mod is None and f.simple:      # швидкий шлях: pc, taint, права не змінюються
            self.depth += 1
            if self.depth > MAX_DEPTH:
                self.depth -= 1
                raise Fatal('надто глибока рекурсія', pos)
            env = dict(zip(f.params, args))
            env['\0parent'] = f.env
            try:
                return self.eval(f.body, env)
            finally:
                self.depth -= 1
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise Fatal('надто глибока рекурсія', pos)
        saved = self.pc
        self.pc = min(saved, fn.c)
        self.taint(fn.c)
        if fn.c < 1:
            self.taint_effects((f.body,), fn.c)
            self.halt_risk(fn.c, f.body)
        saved_caps = self.caps
        mod_q = f.mod is not None and bool(getattr(f.mod[1], 'quotas', None))
        if f.mod is not None:          # печатка модуля діє: права — перетин прав агента й печатки модуля
            self.caps = intersect_caps(self.caps, f.mod[1], self.cwd)
            if mod_q:                  # і квоти модуля — на весь запуск, усі виклики його функцій (суд 8)
                self.quota_stack.append((f'модуль {f.mod[0]}', f.mod[1], id(f.mod[1])))
        try:
            env = {}
            for p, a in zip(f.params, args):
                if isinstance(p, tuple):       # розбір 【a b】: список рівно такої довжини
                    if not isinstance(a.v, list) or len(a.v) != len(p[2]):
                        raise NgrError(f'розбір 【{" ".join(p[2])}】: очікувався список із {len(p[2])} елементів, а не '
                                       f'{kind(a)} {brief(a, 40)}', pos, min(a.c, a.s))
                    env.update((nm, capc(e, a.s) if a.s < e.c else e) for nm, e in zip(p[2], a.v))
                    if min(a.c, a.s) < 1:      # розбір міг упасти на сумнівному аргументі — і не впав (канал завершення)
                        self.halt_risk(min(a.c, a.s), ('op', pos, '☠', []))
                else:
                    env[p] = a
            env['\0parent'] = f.env
            res = self.eval(f.body, env)
            return capc(res, fn.c) if fn.c < res.c else res
        except NgrError as e:
            if f.mod is not None and e.file is None:
                e.file = f.mod[0]
            raise
        finally:
            if mod_q:
                self.quota_stack.pop()
            self.caps = saved_caps
            self.pc = saved
            self.depth -= 1

    def need(self, x, k, g, pos):
        if type(x.v) is NEED_FAST.get(k):           # швидко: точний тип (bool окремо від int — тут не трапляється)
            return x.v
        if kind(x) != k:
            raise NgrError(f'{g}: очікувалося {k}, а не {kind(x)} {brief(x, 40)}', pos)
        return x.v

    def exact(self, f, x, y, g, pos):
        """＋ － × з десятковими — точно (до 60 значущих цифр) або помилка, а не тихе округлення."""
        if type(x) is int and type(y) is int:
            return f(x, y)
        with decimal.localcontext(EXACT_CTX):
            try:
                return f(Decimal(x), Decimal(y))
            except decimal.Inexact:
                raise NgrError(f'{g}: точний результат довший за 60 значущих цифр — округліть (≅) або ділить (÷)', pos)

    def num(self, x, g, pos):
        t = type(x.v)
        if t is int or t is Decimal:
            return x.v
        if t is float:
            return Decimal(repr(x.v))                 # ± дає float — в арифметиці лише десяткові
        raise NgrError(f'{g}: очікувалося число, а не {kind(x)} {brief(x, 40)}', pos)

    def boolean(self, x, g, pos):
        if not isinstance(x.v, bool):
            raise NgrError(f'{g}: умова має бути ● або ○, а не {kind(x)} {brief(x, 40)}', pos)
        return x.v

    def eval(self, node, env):
        k, pos = node[0], node[1]
        self.steps_left -= 1                      # = self.step(pos), без виклику: eval — найгарячіше місце
        if self.steps_left < 0:
            raise Fatal('перевищено ліміт кроків (--кроки)', pos)
        if k == 'lit':
            return V(node[2], self.cpc)
        if k == 'var':
            val = self.lookup(env, node[2], pos)
            if self.try_stack:
                self.taint(val.c)          # усе, з чим працює тіло ☂, може визначити успіх чи помилку
            return val
        if k == 'op':                          # найчастіший вузол — раніше за решту (швидкість)
            return self.sized(self.op(node[2], node[3], env, pos), node[2], pos)
        if k == 'list':
            return self.sized(mk([self.eval(e, env) for e in node[2]], self.cpc), '【】', pos)
        if k == 'tmpl':                    # 〔текст {вираз}〕: рядок, не впевненіший за жодну підстановку
            vals = [self.eval(e[2] if e[0] == 'hole' else e, env) for e in node[2]]
            if sum(v.n for v in vals) > self.max_size:
                raise Fatal(f'〔〕: значення завелике (> --розмір {self.max_size})', pos)
            self.work(sum(v.n for v in vals), pos)
            return V(''.join(show(v) for v in vals), min([self.cpc] + [v.c for v in vals]))
        if k == 'dict':
            d, c, sc = {}, self.cpc, self.cpc
            items = node[2]
            for i in range(0, len(items), 2):
                key = self.eval(items[i], env)
                if not isinstance(key.v, str):
                    raise NgrError('ключ словника має бути рядком', items[i][1], min(key.c, self.cpc))
                d[key.v] = self.eval(items[i + 1], env)
                c, sc = min(c, key.c, d[key.v].c), min(sc, key.c)
            return self.sized(V(d, c, sc), '『』', pos)
        if k == 'block':
            inner = {'\0parent': env}
            result = V(None)
            for s in node[2]:
                result = self.eval(s, inner)
            return result
        if k == 'bind':
            if node[3][0] == 'lam':
                fn = V(Fn(node[3][2], node[3][3], env, node[2]), self.cpc)
                env[node[2]] = fn
                return fn
            val = self.eval(node[3], env)
            env[node[2]] = val
            return val
        if k == 'lam':
            return V(Fn(node[2], node[3], env), self.cpc)
        if k == 'call':
            fn = self.lookup(env, node[2], pos)
            return self.call(fn, [self.eval(a, env) for a in node[3]], pos)
        if k == 'import':
            path, names, mod, sha, real = node[2], node[3], node[4], node[5], node[6]
            menv = self.modules.get(real)
            if menv is None:
                self.trace('модуль', агент=self.agent, шлях=safe(path), файл=safe(real), sha256=sha, дозволи=mod[2][0][3])
                menv = self.modules[real] = {'\0модуль': (safe(os.path.relpath(real, self.cwd)), mod[2][0][3])}
                for st in mod[2][1:]:          # печатку модуля НЕ виконуємо: права агента вона не змінює
                    self.eval(st, menv)
            for nm in names:
                env[nm] = menv[nm]
            return V(None)
        if k == 'seal':
            self.caps = self.seal_caps = node[3]
            if getattr(node[3], 'quotas', None):
                self.quota_stack.append(('печатка', node[3], id(node[3])))
            self.trace('печатка', агент=self.agent, намір=node[2], дозволи=node[3])
            return V(None)
        if k == 'tool':
            job = self.tool_begin(node[2], [self.eval(a, env) for a in node[3]], pos)
            if node is self.defer_node:         # ‖ збирає виклики, щоб виконати їх разом
                return V(('\0виклик', job))
            return self.tool_end(job, self.tool_do(job))
        if k == 'deleg':
            return self.delegate(node, env)
        return self.sized(self.op(node[2], node[3], env, pos), node[2], pos)

    def exceeds(self, caps):
        """Що з caps виходить за права поточного агента (теки — за справжніми шляхами)."""
        over = []
        for t, scopes in caps.items():
            if t not in self.caps:
                over.append(t)
                continue
            for sc in scopes:
                if TOOLS[t][4] == 'тека':
                    rs = os.path.realpath(os.path.join(self.cwd, sc))
                    ok = any(inside(rs, os.path.realpath(os.path.join(self.cwd, p))) for p in self.caps[t])
                elif TOOLS[t][4] == 'команда':
                    ok = any(cmd_within(sc, p) for p in self.caps[t])
                else:
                    ok = sc in self.caps[t]
                if not ok:
                    over.append(f'{t}:{sc}')
        return over

    def delegate(self, node, env):
        _, pos, name, intent, caps, body = node
        over = self.exceeds(caps)
        if over:              # функцію з 🜁 викликав агент з меншими правами — субагент не може мати більше за нього
            self.trace('заборонено', агент=self.agent, субагент=name, дозволи=caps, бракує=over,
                       причина='субагент просить більше, ніж має агент, що його викликає')
            raise NgrError(f'агент «{self.agent}» не може дати субагенту «{name}» більше, ніж має сам: {", ".join(over)}', pos)
        saved = (self.memory, self.agent, self.caps, self.mem_c)
        self.trace('делегування', агент=self.agent, субагент=name, намір=intent, дозволи=caps)
        self.memory, self.agent, self.caps, self.mem_c = {}, f'{self.agent}/{name}', caps, 1.0
        self.trace.depth += 1
        pushed = bool(getattr(caps, 'quotas', None))
        if pushed:
            self.quota_seq += 1
            self.quota_stack.append((f'субагент {name}', caps, ('суб', self.quota_seq)))
        try:
            res = self.eval(body, {'\0parent': env})
        except Fatal:
            raise
        except NgrError as e:
            self.trace('субагент впав', агент=self.agent, помилка=e.msg)
            raise NgrError(f'у субагенті «{name}»: {e.msg}', e.pos or pos, e.c)
        finally:
            if pushed:
                self.quota_stack.pop()
            self.trace.depth -= 1
            self.memory, self.agent, self.caps, self.mem_c = saved
        self.trace('субагент повернув', агент=self.agent, субагент=name, результат=trace_val(res), впевненість=res.c)
        return res

    def op(self, g, argn, env, pos):
        if g not in LAZY_GLYPHS:                  # звичайний гліф: аргументи — завжди всі, одразу (швидкий шлях)
            args = [self.eval(a, env) for a in argn]
            if g in INT_FAST and len(args) == 2:      # певні цілі в певному контексті: те саме, що strict + prim
                x, y = args
                if (type(x.v) is int and type(y.v) is int and x.c >= 1 and y.c >= 1 and self.pc >= 1
                        and self.halt_c >= 1 and (g != '‰' or y.v) and (g != '×' or x.v.bit_length() + y.v.bit_length() <= MAX_INT_BITS)):
                    if g in HEAVY:
                        self.work(x.n + y.n, pos)
                    return V(INT_FAST[g](x.v, y.v))
            return self.strict(g, args, pos)
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
            self.taint_effects((argn[1], argn[2]), c.c)
            self.halt_risk(c.c, argn[1], argn[2])
            if c.c < 1 and isinstance(branch.v, Fn):     # обрано функцію: інша могла б зупинити програму при виклику
                self.halt_c = min(self.halt_c, c.c)
            if c.c < branch.c:
                self.work(branch.n, pos)
                return capc(branch, min(c.c, branch.c))
            return branch
        if g == '☂':
            if argn[1][0] != 'lam':               # обробник — функція завжди, а не лише коли сталася помилка
                h = E(1)
                if not isinstance(h.v, Fn):
                    raise NgrError(f'☂: обробник має бути функцією (λe …), а не {kind(h)}', pos)
            self.try_stack.append(self.cpc)
            try:
                res = E(0)
                tc = self.try_stack.pop()
                self.taint_effects((argn[0],), tc)            # чи дійшло тіло до кінця й чи був обробник — від даних
                self.fn_effects(argn[1], tc)
                return capc(res, tc) if tc < res.c else res
            except Fatal:
                raise
            except NgrError as e:
                tc = min(self.try_stack.pop(), e.c)
                self.taint_effects((argn[0],), tc)
                self.fn_effects(argn[1], tc)
                self.trace('помилку перехоплено', агент=self.agent, помилка=e.msg, впевненість=tc)
                saved = self.pc
                self.pc = min(saved, tc)
                try:
                    res = self.call(E(1), [V(e.msg, tc)], pos)
                finally:
                    self.pc = saved
                return capc(res, tc) if tc < res.c else res
        if g == '‖':
            lst = E(0)
            self.taint(lst.c)
            return self.parallel(lst, E(1), pos, argn[1])
        if g in '∀μφ⇅⊞∫№':
            lst = E(0)
            self.taint(lst.c)
            items = self.seq(lst, g, pos)
            fn = E(1)
            saved = self.pc
            self.pc = min(saved, lst.s)          # скільки разів виконується тіло — залежить від будови списку
            try:
                results = [self.each(g, i, fn, [x], pos) for i, x in enumerate(items)]
            finally:
                self.pc = saved
            self.fn_effects(argn[1], lst.s)
            self.halt_risk(lst.s, argn[1], called=True)
            if g == '∀':
                return V(None, min(self.cpc, lst.s))
            if g == 'μ':
                return mk(results, lst.s)
            # відбір, порядок і групи залежать від результатів функції — це будова результату (s);
            # елемент, відібраний чи згрупований за власною умовою, ще й не впевненіший за неї
            m = min([lst.s] + [r.c for r in results])
            self.taint(m)
            if g == '∫':                          # сума залежить від кожного числа й від того, які елементи є
                total = 0
                for r in results:
                    total = self.exact(lambda x, y: x + y, total, self.num(r, '∫', pos), '∫', pos)
                self.halt_risk(m, ('op', pos, '☠', []))      # «не число» могло зупинити — і не зупинило
                return V(total, m)
            if g == 'φ':
                conds = [self.boolean(r, g, pos) for r in results]
                return mk([capc(x, r.c) if r.c < x.c else x for x, r, ok in zip(items, results, conds) if ok], m)
            if g == '⇅':
                try:
                    order = sorted(range(len(items)), key=lambda i: sort_key(results[i]))
                except TypeError:
                    raise NgrError('⇅: ключі мають бути одного типу (числа, рядки або списки з них — поелементно)', pos)
                return mk([items[i] for i in order], m)
            if g == '№':                          # скільки елементів з кожним ключем — будова й ключі, як у ⊞
                counts = {}
                for r in results:
                    k = self.need(r, 'рядок', '№ (ключ)', pos)
                    counts[k] = counts.get(k, 0) + 1
                return V({k: V(n, m) for k, n in counts.items()}, m, m)
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
            self.fn_effects(argn[2], lst.s)
            self.halt_risk(lst.s, argn[2], called=True)
            return capc(acc, lst.s) if lst.s < acc.c else acc
        if g == '↻':
            s, cond, stepf = E(0), E(1), E(2)
            for f in (cond, stepf):                 # обидві — функції завжди, навіть якщо крок не знадобився
                if not isinstance(f.v, Fn):
                    raise NgrError(f'↻: умова й крок мають бути функціями (λs …), а не {kind(f)}', pos)
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
            self.fn_effects(argn[1], cc)
            self.fn_effects(argn[2], cc)
            self.halt_risk(cc, argn[1], argn[2], called=True)
            return capc(s, cc) if cc < s.c else s
        return self.strict(g, [E(i) for i in range(len(argn))], pos)

    def strict(self, g, args, pos):
        """Гліф з обчисленими аргументами: межі, сама дія, канал завершення, впевненість результату."""
        amin = min([1.0] + [a.c for a in args])
        self.taint(amin)                          # будь-яка операція може впасти — це видно ☂
        if g in HEAVY:
            self.work(sum(a.n for a in args), pos)
        try:
            res = self.prim(g, args, pos)
        except Fatal:
            raise
        except NgrError as e:
            e.c = min(e.c, self.cpc, amin)
            raise
        except RecursionError:
            raise NgrError(f'{g}: значення вкладене надто глибоко', pos, min(self.cpc, amin))
        except decimal.DecimalException as e:
            raise NgrError(f'{g}: десяткове число поза межами ({type(e).__name__})', pos, min(self.cpc, amin))
        if amin < 1 and g not in NEVER_FAILS and not (g == '§' and isinstance(args[0].v, dict)):
            self.halt_risk(amin, ('op', pos, '☠', []))   # могло впасти — і не впало
        if g in 'ρκ§⌂⚗🜃' and self.cpc < res.c:   # свою впевненість задають, але й вони — не певніші за контекст
            res = capc(res, self.cpc)
        if g not in OWN_CONF:
            c = min(res.c, amin, self.cpc)        # новий результат — не впевненіший за контекст (pc і канал завершення)
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
        raise NgrError(f'{g}: очікувався список або рядок, а не {kind(x)}', pos, min(x.c, self.cpc))

    def prim(self, g, a, pos):
        if len(a) == 2 and g in INT_FAST and type(a[0].v) is int and type(a[1].v) is int:   # цілі — точні й так
            x, y = a[0].v, a[1].v
            if g != '‰' or y != 0:
                return V(INT_FAST[g](x, y))
        n = lambda i: self.num(a[i], g, pos)      # noqa: E731
        b = lambda i: self.boolean(a[i], g, pos)  # noqa: E731
        if g == '＋':
            x, y = a[0].v, a[1].v
            if isinstance(x, str) and isinstance(y, str) or isinstance(x, list) and isinstance(y, list):
                if a[0].n + a[1].n > self.max_size:
                    raise Fatal(f'＋: значення завелике ({a[0].n + a[1].n} > --розмір {self.max_size})', pos)
                return V(x + y)
            if isinstance(x, str) or isinstance(y, str):
                raise NgrError(f'＋: рядок можна зʼєднати лише з рядком (для числа — σ): {brief(a[0], 30)} ＋ {brief(a[1], 30)}', pos)
            return V(self.exact(lambda x, y: x + y, n(0), n(1), g, pos))
        if g == '－':
            return V(self.exact(lambda x, y: x - y, n(0), n(1), g, pos))
        if g == '×':
            x, y = n(0), n(1)
            if isinstance(x, int) and isinstance(y, int) and x.bit_length() + y.bit_length() > MAX_INT_BITS:
                raise Fatal(f'×: число завелике (понад {MAX_INT_BITS} біт)', pos)
            return V(self.exact(lambda x, y: x * y, x, y, g, pos))
        if g in '÷‰':
            x, y = n(0), n(1)
            if y == 0:
                raise NgrError(f'{g}: ділення на нуль', pos)
            if g == '‰':                          # як у цілих Python: знак остачі — як у дільника
                if isinstance(x, int) and isinstance(y, int):
                    return V(x % y)
                with decimal.localcontext(EXACT_CTX):
                    try:
                        r = Decimal(x) % Decimal(y)       # точно (інакше DivisionImpossible)
                    except decimal.InvalidOperation:
                        raise NgrError('‰: частка завелика для точної остачі (понад 60 цифр)', pos)
                    if r and (r < 0) != (Decimal(y) < 0):
                        r += Decimal(y)
                return V(r)
            ctx = DEC_CTX.copy()                     # 28 цифр ПІСЛЯ цілої частини: ⌊ ÷ великих — правильне ціле
            ctx.prec = 28 + max(0, Decimal(x).adjusted() - Decimal(y).adjusted() + 1)
            with decimal.localcontext(ctx):
                if isinstance(x, int) and isinstance(y, int):
                    return V(x // y if x % y == 0 else Decimal(x) / Decimal(y))
                return V(Decimal(x) / Decimal(y))
        if g == '⌊':
            x = n(0)
            return V(math.floor(dec_ok(x, '⌊', pos) if isinstance(x, Decimal) else x))
        if g == '＝':
            return V(deep_eq(a[0], a[1]))
        if g == '≠':
            return V(not deep_eq(a[0], a[1]))
        if g in '‹›≤≥':
            x, y = a[0].v, a[1].v
            if not (isinstance(x, str) and isinstance(y, str)):
                x, y = n(0), n(1)
            return V({'‹': x < y, '›': x > y, '≤': x <= y, '≥': x >= y}[g])
        if g == '∧':                              # обидва — ●/○ (без скороченого обчислення: тип перевірено завжди)
            x, y = b(0), b(1)
            return V(x and y)
        if g == '∨':
            x, y = b(0), b(1)
            return V(x or y)
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
            if y - x + 1 > self.max_size:
                raise Fatal(f'…: ряд завеликий ({y - x + 1} > --розмір {self.max_size})', pos)
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
        if g == 'ε':
            return mk([mk([V(k, a[0].s), e]) for k, e in self.need(a[0], 'словник', g, pos).items()], a[0].s)
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
            if a[0].n + len(sep) * len(lst) > self.max_size:
                raise Fatal(f'⁀: значення завелике (> --розмір {self.max_size})', pos)
            return V(sep.join(show(e) for e in lst))
        if g == 'σ':
            if a[0].n > self.max_size:
                raise Fatal(f'{g}: значення завелике (> --розмір {self.max_size})', pos)
            return V(show(a[0]))
        if g == 'ν':
            s = self.need(a[0], 'рядок', g, pos).strip().lstrip('\ufeff')
            s = ''.join(str(digit(ch)) if digit(ch) is not None else ch for ch in s).replace('·', '.').replace('¯', '-')
            try:
                return V(int(s))
            except ValueError:
                try:
                    d = Decimal(s)
                except decimal.InvalidOperation:
                    d = None
                if d is None or not d.is_finite():
                    raise NgrError(f'ν: «{s}» не число', pos)
                return V(dec_ok(d, 'ν', pos))
        if g == 'δ':
            try:
                def bad_const(c):
                    raise ValueError(f'«{c}» — не число JSON')
                return wrap(json.loads(self.need(a[0], 'рядок', g, pos), parse_constant=bad_const,
                                       parse_float=lambda t: dec_ok(Decimal(t), 'δ', pos)), a[0].c)
            except RecursionError:
                raise NgrError('δ: JSON вкладений надто глибоко', pos)
            except ValueError as e:
                raise NgrError(f'δ: не JSON: {e}', pos)
        if g == 'Δ':
            if a[0].n > self.max_size:
                raise Fatal(f'{g}: значення завелике (> --розмір {self.max_size})', pos)
            return V(to_json(a[0]))
        if g == '»':
            if a[0].n > self.max_size:
                raise Fatal(f'»: значення завелике для друку (> --розмір {self.max_size})', pos)
            text = visible(show(a[0]))          # невидиме — як ⟨U+…⟩: прихованого тексту для отримувача немає
            self.trace('вивід', агент=self.agent, текст=trace_val(V(text), True))   # спершу слід, повністю — тоді вивід
            print(text, file=self.out, flush=True)
            return V(None)
        if g == '≈':
            c = n(1)
            if not 0 <= c <= 1:
                raise NgrError('≈: впевненість має бути від 0 до 1', pos)
            c = float(c)
            self.trace('впевненість', агент=self.agent, значення=trace_val(a[0]), було=a[0].c, стало=c)
            return capc(a[0], c)
        if g == '±':
            return V(a[0].c, min(a[0].c, self.cpc))    # впевненість — теж дані: не певніша за саму себе
        if g == '⚗':
            lst, t = self.need(a[0], 'список', g, pos), float(n(1))
            # що лишилось — залежить від упевненостей елементів і порогу: це будова результату
            sc = min([a[0].s, a[1].c, self.cpc] + [x.c for x in lst])
            if not 0 <= t <= 1:
                raise NgrError('⚗: поріг має бути від 0 до 1', pos)
            kept = []
            for x in lst:
                ok = x.c >= t
                self.trace('відсів', агент=self.agent, значення=trace_val(x), впевненість=x.c, поріг=t,
                           рішення='лишено' if ok else 'відкинуто')
                if ok:
                    kept.append(x)
            return mk(kept, sc)
        if g == '🜄':
            key = self.need(a[0], 'рядок', g, pos)
            kc = min(a[0].c, self.cpc)
            self.mem_c = min(self.mem_c, kc)       # сам факт запису під таким ключем — теж інформація
            val = capc(a[1], kc) if kc < a[1].c else a[1]
            self.memory[key] = val
            self.trace('памʼять', агент=self.agent, дія='запамʼятати', ключ=key, значення=trace_val(val), впевненість=val.c)
            return V(None, self.cpc)
        if g == '🜃':
            key = self.need(a[0], 'рядок', g, pos)
            res = self.memory.get(key, V(None))
            c = min(a[0].c, self.mem_c, self.cpc)  # і знайдене, і відсутнє залежить від того, як писали
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
                raise NgrError(f'🜍: перевірку не пройдено для {brief(a[0], 60)}', pos, min(r.c, a[0].c, self.cpc))
            self.halt_c = min(self.halt_c, r.c)     # те, що програма йде далі, — теж знання про умову
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
        if g == '◷':
            return V(date_op(a[0].v, a[1].v, pos))
        if g == '✓':
            errs = []
            check_schema(a[0], a[1], '', errs, pos)
            if errs:
                more = f' … ще {len(errs) - 10}' if len(errs) > 10 else ''
                raise NgrError('✓: не відповідає схемі: ' + '; '.join(errs[:10]) + more, pos)
            return a[0]
        if g == 'χ':
            x = a[0].v
            if isinstance(x, str):
                return xml_parse(x, pos, self.max_size, lambda k: self.work(k, pos))
            if isinstance(x, dict):
                return V(xml_write(a[0], pos, lambda k: self.step(pos)))
            raise NgrError(f'χ: очікувався рядок XML або елемент (словник), а не {kind(a[0])}', pos)
        if g == '↘':
            self.need(a[0], 'словник', g, pos)
            return xml_path(a[0], self.need(a[1], 'рядок', g, pos), pos, lambda k: self.step(pos))
        if g == '▦':
            import csv
            import io as _io
            text = self.need(a[0], 'рядок', g, pos).removeprefix('\ufeff')   # BOM з 1С/Excel — не частина ключа
            csv.field_size_limit(max(len(text), 1))      # довге поле — не «внутрішня помилка» (суд 7)
            try:
                rd = list(csv.reader(_io.StringIO(text), strict=True))
            except csv.Error as e:
                raise NgrError(f'▦: не CSV ({e})', pos)
            if not rd:
                return V([])
            head = rd[0]
            if len(set(head)) != len(head):
                raise NgrError(f'▦: однакові заголовки ({", ".join(head)}) — значення загубилися б', pos)
            out = []
            for i, r in enumerate(rd[1:], 2):
                if not r:
                    continue                             # порожній рядок
                if len(r) != len(head):
                    raise NgrError(f'▦: рядок {i} має {len(r)} полів, а заголовків {len(head)} — нічого не губимо мовчки', pos)
                out.append(V(dict(zip(head, (V(x) for x in r)))))
            return V(out)
        if g in '⇣⇡':
            x = self.need(a[0], 'рядок', g, pos)
            return V(x.lower() if g == '⇣' else x.upper())
        if g == '⊏':
            x = a[0].v
            if not isinstance(x, (str, list)):
                raise NgrError(f'⊏: очікувався рядок чи список, а не {kind(a[0])}', pos)
            ends = []
            for b in (a[1], a[2]):
                if b.v is not None and (isinstance(b.v, bool) or not isinstance(b.v, int)):
                    raise NgrError('⊏: межі — цілі числа (до ∅ — до кінця)', pos)
                ends.append(b.v)
            return V(x[ends[0]:ends[1]])
        if g == '⊳':
            x = a[0].v
            if isinstance(x, str):
                return V(x.find(self.need(a[1], 'рядок', g, pos)))
            if isinstance(x, list):
                return V(next((i for i, e in enumerate(x) if deep_eq(e, a[1])), -1))
            raise NgrError(f'⊳: очікувався рядок чи список, а не {kind(a[0])}', pos)
        if g in '⌕≋':
            x = self.need(a[0], 'рядок', g, pos)
            r = regex(self.need(a[1], 'рядок', g, pos), g, pos)

            def pay(k):                       # кожен крок рушія — з бюджету --кроки
                self.steps_left -= k
                if self.steps_left < 0:
                    raise Fatal('перевищено ліміт кроків (--кроки) у регулярному виразі', pos)
            if g == '≋':
                try:
                    return V(r.sub(self.need(a[2], 'рядок', g, pos), x, pay, self.max_size))
                except RxError as e:
                    raise NgrError(f'≋: {e}', pos)
                except OverflowError:
                    raise Fatal(f'≋: значення завелике (> --розмір {self.max_size})', pos)
            out, size = [], 0
            for m in r.finditer(x, pay):
                gs = r.groups(x, m)
                item = gs[0] if r.ngroups == 1 else [p or '' for p in gs[1:]]   # з групами — завжди список груп
                size += 1 + (len(item) if isinstance(item, str) else sum(len(p) + 1 for p in item))
                if size > self.max_size:              # межа — під час пошуку, а не після
                    raise Fatal(f'⌕: значення завелике (> --розмір {self.max_size})', pos)
                out.append(V([V(p) for p in item]) if isinstance(item, list) else V(item))
            return V(out)
        if g == '⇄':
            src_, old, new = (self.need(a[i], 'рядок', g, pos) for i in range(3))
            cnt = src_.count(old) if old else len(src_) + 1
            if len(src_) + cnt * len(new) > self.max_size:
                raise Fatal(f'⇄: значення завелике (> --розмір {self.max_size})', pos)
            return V(src_.replace(old, new))
        if g == '⊢':
            return V(self.need(a[0], 'рядок', g, pos).strip().strip('\ufeff\u200b').strip())
        if g in '≅⌗':
            x, k = n(0), n(1)
            if isinstance(k, bool) or not isinstance(k, int) or not 0 <= k <= 12:
                raise NgrError(f'{g}: кількість знаків — ціле від 0 до 12', pos)
            with decimal.localcontext(WIDE_CTX):          # точність — під будь-яке допустиме число (не 28 цифр)
                q = Decimal(x).quantize(Decimal(1).scaleb(-k), rounding=ROUND_HALF_UP)
            if g == '⌗':
                return V(format(q, 'f'))
            return V(int(q) if k == 0 else q)
        if g == '⌂':
            return V([V(x) for x in self.argv])
        raise NgrError(f'гліф «{g}» не реалізовано', pos)


# ------------------------------------------------------------------ розбір для людини


def quote(text):
    """Слова автора в --розбір: у «…» з екрануванням «, », \\ і переносу — лапки не можна закрити зсередини (суд 7)."""
    t = safe(text).replace('\\', '\\\\').replace('«', '\\«').replace('»', '\\»').replace('\n', '\\n')
    return '«' + t + '»'


def explain(node, ind=0):
    """Перекласти дерево програми українським псевдокодом."""
    pad = '  ' * ind
    k = node[0]
    if k == 'lit':
        v = node[2]
        if isinstance(v, str):
            return quote(v)
        return show(V(v))
    if k == 'var':
        return node[2]
    if k == 'op' and node[2] == '⌂':
        return 'аргументи програми'
    if k == 'list':
        return '[' + ', '.join(explain(e, ind) for e in node[2]) + ']'
    if k == 'tmpl':              # текст — у лапках, підстановки — поза ними: текст «{…}» від дії не сплутати
        out = ' + '.join(quote(e[2]) if e[0] == 'lit' else f'рядок({explain(e[2], ind)})' for e in node[2])
        return out or '«»'
    if k == 'dict':
        it = node[2]
        return '{' + ', '.join(f'{explain(it[i], ind)}: {explain(it[i + 1], ind)}' for i in range(0, len(it), 2)) + '}'
    if k == 'block':
        inner = [explain(s, ind + 1) for s in node[2]]
        return 'послідовно:\n' + '\n'.join('  ' * (ind + 1) + s for s in inner)
    if k == 'bind':
        return f'{node[2]} ← {explain(node[3], ind)}'
    if k == 'lam':
        return f'({param_text(node[2])}) ↦ {explain(node[3], ind)}'
    if k == 'call':
        inner = ', '.join(explain(a, ind) for a in node[3])
        if len(node[3]) == 1 and inner.startswith('(') and inner.endswith(')'):
            inner = inner[1:-1]
        return f'{node[2]}({inner})'
    if k == 'import':
        caps = '; '.join(t + (f' [{", ".join(s)}]' if s else '') for t, s in node[4][2][0][3].items()) or 'жодних'
        body = '\n'.join('  ' * (ind + 1) + explain(st, ind + 1) for st in node[4][2][1:])
        qs = quota_list(node[4][2][0][3])
        caps += f'; КВОТА на весь запуск: {quota_text(qs)}' if qs else ''
        return (f'з модуля {quote(node[2])} (sha256 {node[5][:16]}…, дозволи: {caps}) взяти: '
                f'{", ".join(node[3])}; модуль:\n{body}')
    if k == 'seal':
        caps = '; '.join(t + (f' [{", ".join(s)}]' if s else '') for t, s in node[3].items()) or 'жодних'
        qs = quota_list(node[3])
        return (f'ПЕЧАТКА — намір: {quote(node[2]) if node[2] else "не вказано"}; дозволи: {caps}'
                + (f'; КВОТА: {quota_text(qs)}' if qs else ''))
    if k == 'tool':
        return f'інструмент {node[2]}({", ".join(explain(a, ind) for a in node[3])})'
    if k == 'deleg':
        caps = ', '.join(t + (f' [{", ".join(s)}]' if s else '') for t, s in node[4].items()) or 'жодних'
        intent = f'намір {quote(node[3])}; ' if node[3] else ''
        qs = quota_list(node[4])
        caps += f'; КВОТА на кожен запуск: {quota_text(qs)}' if qs else ''
        return (f'субагент «{safe(node[2])}» ({intent}дозволи: {caps}) виконує:\n'
                f'{pad}  {explain(node[5], ind + 1)}')
    g, args = node[2], node[3]
    tmpl = GLYPHS[g][3]
    parts = [explain(a, ind) if f'({{{i}}})' in tmpl else par(a, explain(a, ind)) for i, a in enumerate(args)]
    lam = args[-1] if args and args[-1][0] == 'lam' else None
    if lam and g in LAMBDA_TEMPLATES:
        if g == '↻' and args[1][0] == 'lam':
            st, cst = param_text(lam[2][:1]), param_text(args[1][2][:1])
            return (f'{st} ← {parts[0]}; поки {explain(args[1][3], ind)} (де {cst} — стан): '
                    f'{st} ← {explain(lam[3], ind)}; результат — {st}')
        return LAMBDA_TEMPLATES[g].format(*parts[:-1], p=param_text(lam[2]), body=explain(lam[3], ind))
    return GLYPHS[g][3].format(*parts)


LAMBDA_TEMPLATES = {
    '∀': 'для кожного {p} з {0}: {body}',
    'μ': 'список: для кожного {p} з {0} — {body}',
    'φ': 'ті {p} з {0}, де {body}',
    'Σ': 'згорнути {0}, почавши з {1}: ({p}) ↦ {body}',
    '∫': 'сума для кожного {p} з {0}: {body}',
    '‖': 'паралельно для кожного {p} з {0}: {body}',
    '№': 'порахувати {0} за ключем: ({p}) ↦ {body}',
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
    lines = [explain(s) for s in prog[2]]
    seal = prog[2][0][3] if prog[2] and prog[2][0][0] == 'seal' else {}
    one = [t for t, sc in seal.items() if TOOLS[t][4] == 'тека' and len(sc) == 1]
    if one:                           # шлях один раз: де саме шукатиметься файл (суд 7)
        lines.insert(1, '(шляхи ' + ', '.join(one) + ': від теки програми; якщо там такого шляху немає — від єдиної теки '
                     'з печатки; справжній шлях — у сліді, поле «шлях»)')
    return '\n'.join(lines)


def quota_list(caps):
    return [{'інструмент': t, 'обмеження': safe(sc), 'не_більше': n} for (t, sc), n in getattr(caps, 'quotas', {}).items()]


def quota_text(qs):
    """Квоти для людини: «взяти:хост ≤ 5»."""
    return ', '.join(f'«{x["інструмент"]}{":" + x["обмеження"] if x["обмеження"] else ""}» ≤ {x["не_більше"]}' for x in qs)


def seal_info(prog, allowed, source, cwd, dir_extra=None):
    """Усе, що отримувач має знати до запуску, — словником (для --печатка і --печатка --json)."""
    def scopes(t, sc):
        if TOOLS[t][4] == 'тека':
            return [safe(os.path.realpath(os.path.join(cwd, x))) for x in sc]
        return [safe(x) for x in sc]

    seal = prog[2][0]
    subs, explicit, mods = [], 0, []

    def walk(n, owner):
        nonlocal explicit
        if isinstance(n, tuple) and n:
            if n[0] == 'op' and n[2] == '≈':
                explicit += 1
            if n[0] == 'import':
                mods.append({'шлях': safe(n[2]), 'sha256': n[5], 'намір': safe(n[4][2][0][2]), 'імена': n[3],
                             'дозволи': {t: scopes(t, sc) for t, sc in n[4][2][0][3].items()},
                             'квоти': quota_list(n[4][2][0][3])})
            if n[0] == 'deleg':
                subs.append({'імʼя': safe(n[2]), 'намір': safe(n[3]), 'усередині': owner,
                             'дозволи': {t: scopes(t, sc) for t, sc in n[4].items()}, 'квоти': quota_list(n[4])})
                walk(n[5], owner + [safe(n[2])])
                return
            for x in n:
                walk(x, owner)
        elif isinstance(n, list):
            for x in n:
                walk(x, owner)
    walk(prog, ['головний'])
    missing = [safe(m) for m in check_program(prog, allowed, cwd)]
    return {'намір': safe(seal[2]), 'дозволи': {t: scopes(t, sc) for t, sc in seal[3].items()},
            'субагенти': subs, 'модулі': mods, 'явні_зміни_впевненості': explicit, 'дозволи_власника': safe(source),
            'квоти': quota_list(seal[3]),
            'права_теки': [safe(x) for x in dir_extra] if dir_extra is not None else None, 'тека': safe(cwd), 'в_межах': not missing, 'бракує': missing}


def seal_report(prog, allowed, source, cwd, dir_extra=None):
    """Текст для людини й моделі: слова автора (намір, імена, шляхи) — у 「」, решта — слова інтерпретатора."""
    i = seal_info(prog, allowed, source, cwd, dir_extra)
    q = lambda sc: ', '.join(f'「{x}」' for x in sc)
    lines = ['ПЕЧАТКА', f'  намір (слова автора): 「{i["намір"]}」' if i['намір'] else '  намір: не вказано автором',
             '  дозволи:']
    quotas = getattr(prog[2][0][3], 'quotas', {}) if prog[2] else {}
    for t, sc in i['дозволи'].items():
        qs = [f'«{t}{":" + s_ if s_ else ""}» ≤ {n}' for (t2, s_), n in quotas.items() if t2 == t]
        lines.append(f'    {t}' + (f' → {q(sc)}' if sc else '') + (f'   КВОТА: {", ".join(qs)}' if qs else '')
                     + f'   ({TOOLS[t][2]})')
    if not i['дозволи']:
        lines.append('    жодних — програма лише обчислює')
    for d in i['субагенти']:
        caps = '; '.join(t + (f' → {q(sc)}' if sc else '') for t, sc in d['дозволи'].items()) or 'жодних'
        where = ' → '.join(f'「{x}」' for x in d['усередині'])
        lines.append(f'  субагент 「{d["імʼя"]}」 (у коді: {where}): дозволи: {caps}'
                     + (f'; КВОТА на кожен запуск: {quota_text(d["квоти"])}' if d['квоти'] else '')
                     + (f'; намір 「{d["намір"]}」' if d['намір'] else ''))
    for m in i['модулі']:
        caps = '; '.join(t + (f' → {q(sc)}' if sc else '') for t, sc in m['дозволи'].items()) or 'жодних'
        lines.append(f'  модуль 「{m["шлях"]}」 (sha256 {m["sha256"][:16]}…): бере {", ".join(m["імена"])}; дозволи: {caps}; '
                     + (f'КВОТА на весь запуск: {quota_text(m["квоти"])}; ' if m['квоти'] else '') + f'намір 「{m["намір"]}」')
    if i['явні_зміни_впевненості']:
        lines.append(f'  явні зміни впевненості ≈: {i["явні_зміни_впевненості"]} (кожна — у сліді)')
    lines.append(f'  дозволи власника: {i["дозволи_власника"]}')
    if i['права_теки'] is None:
        lines.append('  права теки: жодних (код рядком без --тека)')
    elif i['права_теки']:
        lines.append(f'  права теки {i["тека"]}: {", ".join(i["права_теки"])}')
    else:
        lines.append('  права теки: немає (для цієї теки власник нічого не дав, або це тека, куди програмам дозволено писати)')
    lines.append('  ✓ печатка в межах дозволів власника' if i['в_межах'] else f'  ✗ бракує дозволу власника: {", ".join(i["бракує"])}')
    lines.append('  (права перевіряються й під час виконання: кожен інструмент і кожен субагент — лише в межах агента, '
                 'що його викликає. Цього необхідно, але не досить: намір, імена й вивід — слова автора програми)')
    return '\n'.join(lines)


# ------------------------------------------------------------------ памʼятка


def cheatsheet():
    out = [f'# Nigredo {VERSION} — памʼятка для агентів', '',
           '_Згенеровано з інтерпретатора: `ngr --памʼятка`. Повна специфікація — `spec/SPEC.md`._', '',
           '## Як це влаштовано', '',
           '- **Префіксний запис з фіксованою арністю**: гліф, потім рівно стільки аргументів, скільки він бере.',
           '  `＋ 2 3` → 5; `» × 2 ＋ 3 4` → 14. Дужок для групування не треба: арність однозначна.',
           '- **Помилки до запуску.** Значення незмінні, тож тип кожного названого значення відомий: `＋ 「рядок」 n`,',
           '  `‹ 「5」 3`, умова не ●/○, `§ список 「ключ」`, небезпечна регулярка, `÷ x 0` — помилка до запуску.',
           '  `ngr --перевірити --json файл` — усі помилки одразу (з місцем і підказкою) і печатка, без виконання.',
           '- **Кінець рядка завершує вираз.** Бракує аргументу в кінці рядка — помилка до запуску. Довгий вираз',
           '  продовжуйте на наступних рядках **з більшим відступом**; усередині `【】` і `『』` перенос вільний.',
           '  Зайве після завершеного виразу — теж помилка. Кілька виразів в одному рядку — через `¦`.',
           '- **Значення не змінюються**: `← імʼя вираз` називає назавжди, і лише на початку інструкції',
           '  (усередині виразу — блок `《 ← … 》`). Цикли — `∀ μ φ Σ ↻`.',
           '- Імена — слова будь-якою мовою, але **одним письмом** (`звiт` з латинською i — помилка). Грецькі літери — гліфи.',
           '  **Двійники** — два різні імена, однакові на вигляд за скелетом UTS #39 (`x`/`х`, `h`/`һ`, `I`/`l`), — помилка;',
           '  так само імʼя з символів сумісності (`ｘ`, `𝚡`), імʼя, схоже на число (великі `О O З Б`), і **функція**, схожа на',
           '  гліф (`х р v ф σ` — `х 2 3` читалося б як `× 2 3`; змінна `x` — можна). Письма імен: латиниця, кирилиця, CJK,',
           '  кана, хангиль, арабське, іврит, деванагарі, бенгальське, тамільське, тайське, грузинське; інші — помилка.',
           '- **Невидимого в тексті програми немає**: керівні, bidi, теги, ZWSP, U+034F, нестандартні пробіли, заповнювачі',
           '  (U+3164) — помилка всюди: в коді, рядках, коментарях, печатці. Такі дані беріть через `δ 「"\\u…"」`;',
           '  у виводі й сліді вони показані як `⟨U+…⟩`.',
           '- Умови — лише `●` (так) або `○` (ні); `∅` — ніщо. Числа — цифри `0–9` або `０–９`, мінус — `¯5`; дроби точні.',
           '- Рядок `「…」` (екранування `\\」 \\n \\t \\\\`; інше `\\x` лишається як є — `「\\w+」` доходить до регулярки),',
           '  список `【…】`, словник `『ключ значення …』`, блок `《…》` (значення — останній вираз).',
           '- **Шаблонний рядок** `〔текст {вираз} текст〕` — як f-рядок: у `{…}` рівно один вираз в одному рядку,',
           '  `\\{ \\} \\〕` — буквально; вкладений шаблон — у дірці `{〔…〕}`. `〔{k}: {⌗ v 2} грн〕`. У `「…」` фігурні',
           '  дужки — звичайні символи (JSON пишіть там): `「n = {n}」` друкує `{n}` буквально.',
           '- Регулярні вирази (`⌕` усі збіги, `≋` заміна, `\\1`/`\\g<імʼя>` — групи) — синтаксис Python `re`, рушій **без',
           '  відкатів**: час лінійний, кожен крок — з `--кроки`, зависання неможливе. Помилка: зворотне посилання в шаблоні,',
           '  заглядання `(?=…)`, умовні й атомарні групи, присвійні повторення, повторення порожнього тіла `(a?)+`.',
           '  JSON: `true/false/null` ↔ `●/○/∅`. `§` словника без такого ключа дає `∅`. Значення верхнього рівня без `»` нікуди не йде.',
           '- Коментар — `※` до кінця рядка. Відносні шляхи — від теки файлу програми.',
           '- **Модулі:** `⊃ 「мод.ngr」 【「f」 「g」】` на початку інструкції верхнього рівня бере названі значення з файлу',
           '  в теці програми. Модуль має свою печатку, і вона ⊆ печатки програми; на верхньому рівні модуль лише називає',
           '  функції (`← f λ…`) і сталі (без викликів), дії — лише у функціях. Функцію модуля кличуть за імʼям (`f x`); вона',
           '  діє з **перетином** прав того, хто кличе, і печатки модуля. Шляхи в модулі — від теки програми. Модуль із теки,',
           '  куди програмам дозволено писати, — відмова. `--перевірити-слід СЛІД ПРОГРАМА` звіряє й sha256 кожного модуля.',
           '- **Кожне значення має впевненість** (типово 1). Усе, що обчислено з даних, не впевненіше за них —',
           '  і через операції, і через **керування**: значення, створене під сумнівною умовою `¿`, у циклі `↻`,',
           '  у функції, обраній сумнівно, після сумнівної перевірки `🜍` чи в `☂`, несе цю сумнівність.',
           '  Відібране `φ`, упорядковане `⇅`, згруповане `⊞`, пригадане `🜃` за сумнівним ключем — теж.',
           '  Список має дві міри: впевненість вмісту й **будови** (які елементи, скільки, в якому порядку);',
           '  `ρ`, `§`, цикли зважають на будову. Побічний стан (памʼять, `жереб`, файли, годинник) після сумнівного',
           '  рішення теж сумнівний — навіть якщо гілку не виконано. **Канал завершення**: якщо код під сумнівною умовою',
           '  (гілка `¿`, тіло циклу, сумнівна чи сумнівно обрана функція) міг зупинити програму (`☠`, `🜍`, `÷ 0`, `§` поза',
           '  межами, виклик…) або операція могла впасти на сумнівному аргументі (`÷ 1 x`, `ν x`, `⌕ т x`), то сам факт, що',
           '  програма йде далі, — знання: решта запуску не впевненіша. Невідстежене — лише вичерпання лімітів.',
           '  **Явно** змінити впевненість можна лише `≈`',
           '  (і це записується в слід); інтерпретатор лише консервативно *знижує* її — це оцінка, не ймовірність.',
           '', '## Печатка (обовʼязкова)', '',
           'Перший рядок кожної програми — `🜂 「намір」 【「дозвіл」 …】`. Намір — за бажанням (`🜂 【「дозвіл」 …】`; його',
           'ніхто не перевіряє, це слова автора), програма без дозволів — просто `🜂`. Інструмент, якого нема в печатці,',
           'не пройде розбір; під час виконання кожен виклик ще раз звіряється з дозволами агента, що його робить.',
           'Печатка має вкладатися в дозволи власника (`~/.nigredo/дозволи.json`: «дозволено» — для всіх програм,',
           '«для_тек» — лише для програм у певній теці; `--дозволи` може їх лише звузити), інакше програма не',
           'запуститься. Власник бачить печатку командою `ngr --печатка файл.ngr`: слова автора (намір, імена',
           'субагентів, шляхи) — у `「」`, тож у печатці заборонено `「」`, пробіли поспіль чи по краях і невидиме,',
           'а в імені субагента ще й `/` (ним пишеться вкладеність).', '',
           '```', '🜂 【「читати:звіти」 「писати:вихід」】', '```', '',
           'Назви інструментів короткі (`читати писати список взяти`); повні (`файл.читати`, `мережа.взяти`) — синоніми,',
           'і в `--печатка`, `--розбір` та сліді показано саме повні.', '',
           'Дозвіл для файлів — тека (і все в ній); для мережі — хост (порти 80/443) або `хост:порт`;',
           'для агента — імʼя з реєстру. Теку власника (`~/.nigredo`) дозволити не можна.',
           'Тести мовою: файли `*.тест.ngr` з перевірками `🜍 x λv умова`; `ngr --тести тека` — підсумок і код виходу.',
           'Кілька інструментів на одне обмеження: `「читати писати:тимч」`. Квота: `「взяти:api.x≤100」` — не більше 100',
           'викликів за запуск (понад — помилка й «заборонено»; так само в дозволах власника).',
           'Шлях один раз: якщо для інструмента в печатці одна тека, пишіть шлях відносно неї —',
           '`🜂 【「читати:дані」】` і `🜔читати 「x.json」` (лише якщо від теки програми такого шляху немає; назвали наявне',
           'поза дозволом — відмова, «заборонено»). Справжній шлях — у сліді.',
           '☂ ловить помилки програми, але не вичерпання лімітів (--кроки, --розмір, «число завелике»).', '',
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
        out.append(f'| `{sig}` | {desc} | `「{TOOL_SHORT.get(name, name)}' + (f':{ex}' if scoped else '') + '」` |')
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
            '```', '🜂 「найдорожчий товар у кожній категорії」',
            '← т 【『「назва」 「кава」 「кат」 「напої」 「ціна」 120』 『「назва」 「сир」 「кат」 「їжа」 「ціна」 310』 '
            '『「назва」 「чай」 「кат」 「напої」 「ціна」 90』】',
            '∀ ⇅ ε⊞ т λp §p 「кат」 λ【k l】 k λ【k l】 《 ← н §⇅ l λp －0 §p 「ціна」 0 ¦ » 〔{k}: {§н 「назва」} ({§н 「ціна」})〕 》',
            '```', '',
            '```', '🜂 「дати й заміна регулярними виразами」 【】',
            '← т 「Звіт 2026-10-15, оплата 2026-11-01. ДЕДЛАЙН!」',
            '∀ ⌕ т 「(\\d{4})-(\\d{2})-(\\d{2})」 λd » 〔{§d 2}.{§d 1}.{§d 0}〕',
            '» ≋ т 「(\\d{4})-(\\d{2})-(\\d{2})」 「\\3.\\2.\\1」', '```', '',
            '## Пастки', '',
            '- `＝0 ‰n 3` — спершу гліф, потім аргументи: «остача n на 3 дорівнює 0».',
            '- Не зійшлася арність — помилка каже, як розібрано рядок: `розібрано: ¿ (＝ a 0) (÷ s 2) 2` (кожен вираз',
            '  з аргументами — у дужках) і `чекають аргументів: ÷ (4:9) бере 2, є 1`. Вираз довший за рядок — розбийте',
            '  на `←` проміжні імена.',
            '- Імена склеюються з цифрами: `n15` — одне імʼя; пишіть `n 15`.',
            '- Однолітерні імена з різних абеток — двійники (r і г, x і х, p і р, a і а, o і о, c і с, e і е, y і у):',
            '  програму не приймуть. Беріть імена одного письма або довші (рядок, група).',
            '- `⌕` із групами — завжди список груп, навіть з однією: `§§ ⌕ т 「(\\d+)」 0 0` — перша група першого збігу.',
            '- `∧ ∨` обчислюють ОБИДВА боки (не як and/or у Python): `∧ › ρxs 0 ＝ §xs 0 1` впаде на порожньому',
            '  списку; захист — `¿ › ρxs 0 ＝ §xs 0 1 ○` (¿ обчислює лише потрібну гілку).',
            '- `χ` пише числа як число (12.50 → 12.5); суми в XML — рядком `⌗ x 2`.',
            '- `↘` — підмножина XPath: `..`, `text()`, `!=` — помилка; текст вузла — `§e 「текст」`.',
            '- Квота `≤N` і `‖`: «усе або нічого» — список довший за квоту не дасть нічого; `‖ ⊏ xs 0 N`.',
            '- SQLite рахує дроби у float: `SUM(сума)` дає `0.30000000000000004`; гроші — сумуйте в Nigredo (`∫`) або',
            '  зберігайте копійками (INTEGER).',
            '- `＋` зʼєднує рядки лише з рядками: `＋「№」 σn`; коротше — шаблон `〔№{n}〕`.',
            '- Функцію, названу `←`, викликають просто: `факт 10`; передати як значення — `∘факт`.',
            '  Функцію-значення (параметр) викликають `► f x`.',
            '- `✂ рядок 「」` ріже за пробілами. `↑` сортує рядки за українською абеткою. `⇅` **стабільне**; ключ може бути',
            '  списком (складений): `⇅ п λp 【－0 §p 1 §p 0】` — за спаданням числа, при рівності за абеткою. Мінус виразу —',
            '  `－ 0 x` (`¯` — лише в літералі). `↺` обертає список.',
            '- Дробові числа — **точні десяткові** (і з JSON теж): `＋ 0.1 0.2` → `0.3`, `≅ 2.675 2` → `2.68`. `＋ － ×` —',
            '  точно до 60 значущих цифр (довше — помилка, не тихе округлення); `÷` — 28 значущих цифр (`÷ 1 3`).',
            '  Рівно n знаків (гроші): `⌗ x 2` (рядок) або `≅ x 2` (число), n від 0 до 12; обидва — половина вгору.',
            '  `ν` і `δ` відкидають NaN/Infinity і порядок понад 30 000; `ν` бере й цифри інших письмен із даних (`١٢` → 12).',
            '- `☂` перехоплює помилки програми, але не ліміти (кроки, розмір, глибина рекурсії); `÷ x 0` з буквальним',
            '  нулем — помилка ще до запуску, навіть у `☂`.',
            '- Субагент бачить імена батька лише для читання (змінити їх неможливо взагалі) і має власну памʼять.',
            '- Ціна в токенах: кириличне імʼя коштує в 3–8 разів більше за коротке латинське (`відповіді` — 8 токенів,',
            '  `ans` — 1). Для економії беріть короткі імена; рядки й коментарі — будь-якою мовою.',
            '',
            '## Чесно про межі', '',
            '- **Nigredo — інструмент прозорості й аудиту, а не пісочниця.** Інтерпретатор гарантує, що *програма*',
            '  не зробить нічого поза печаткою і не допише, не змінить і не обріже свій слід непомітно. Але *агент*,',
            '  що має shell, може обійти Nigredo взагалі чи змінити `~/.nigredo` (дозволи, ключ сліду). Від такого',
            '  агента захищають права процесу й пісочниця ОС, а не мова.',
            '- Впевненість відстежується через дані, керування й побічний стан, але це консервативна оцінка, а не',
            '  ймовірність. Канал завершення відстежується (див. вище); лишається лише вичерпання лімітів кроків і',
            '  розміру — їх задає той, хто запускає, однаково для всіх гілок.',
            '- Намір, імена субагентів і вивід програми — слова її автора. Печатка (`--печатка`, код 3, якщо не в',
            '  межах дозволів; `--печатка --json` для машин) необхідна, але не досить; довіряй ще сліду, перевіреному',
            '  разом із програмою.',
            '- Ліміти: `--кроки` (обчислення; створення великих значень теж коштує кроків), `--розмір` (логічний',
            '  розмір значення — символи й елементи разом зі спільними посиланнями, і цілі), сумарно створене за запуск',
            '  ≤ 20 × `--розмір`, `--слід-розмір` (байти сліду), глибина рекурсії.',
            '- Права теки («для_тек») має програма-**файл** у тій теці, але не та, що лежить у теці, куди програмам',
            '  дозволено писати. Код рядком (`-e`) прав теки не має, доки не вказано `--тека` — а її вибирає той, хто',
            '  запускає: від агента з shell це не захищає.',
            '- Субагент може взяти ті самі або вужчі права (підтеку без `..`); печатку кожного субагента звіряють з',
            '  дозволами власника за справжніми шляхами.',
            '- `оракул` — імітація; `агент` — справжній виклик Claude (коштує грошей і часу).',
            '- Порівняно з Python: без печатки — приблизно стільки ж токенів; печатка додає фіксовану ціну.',
            '',
            '## Прозорість', '',
            '- `ngr --печатка файл.ngr` — що програмі дозволено, ще до запуску.',
            '- `ngr --розбір файл.ngr` — переклад українським псевдокодом.',
            '- **Слід ведеться завжди** — у `~/.nigredo/сліди/`, куди програма не має доступу; `--слід ФАЙЛ` — ще одна',
            '  копія (новий файл, не в теці власника й не в теках із печатки). Печатка, кожен інструмент, відмови,',
            '  делегування, памʼять, перевірки, відсів, впевненість, вивід — **повністю** (лише довгі аргументи, що не',
            '  йдуть назовні, — «підсумок»: довжина, sha256, початок); спроба без дозволу — запис «заборонено». Записи',
            '  підписано ключем власника (HMAC) і зчеплено; `ngr --перевірити-слід ФАЙЛ` виявить зміну, вставку чи',
            '  обрізання (завершальні записи — лише «кінець», «помилка» або «відмова» на старті) і в підсумку скаже',
            '  теку, аргументи, кількість «заборонено», перехоплених помилок і підсумованих значень (`--json` — для машин).',
            '- `ngr --перевірити-слід СЛІД ПРОГРАМА` — ще й чи слід саме від цієї програми; у сліді є час і',
            '  ідентифікатор запуску (слід старого формату без них — «⚠»). Навіть відкинута до запуску програма лишає слід.',
            '']
    return '\n'.join(out)


def cheatsheet_short():
    """Стисла памʼятка для контексту агента (MCP-опис, ~1–1.5 тис. токенів)."""
    lines = [f'Nigredo {VERSION}: префіксний запис, фіксована арність, 1 рядок = 1 вираз (продовження — більший відступ, ¦ — розділювач).',
             'Перший рядок — ПЕЧАТКА: 🜂 【「дозвіл」 …】 (намір за бажанням: 🜂 「намір」 【…】; без дозволів — просто 🜂);',
             'дозволи: 「оракул」 「жереб」 「час」 「читати:тека」 「писати:тека」 「список:тека」 「взяти:хост」 「послати:хост」 「агент:імʼя」',
             '「бд.читати:тека」 「бд.писати:тека」 「процес:git status」 (дозвіл — початок команди); кілька на одне: 「читати список:дані」.',
             'Шлях — від теки програми; якщо такого немає, а в печатці для інструмента одна тека, — від неї (「x.json」 при 「читати:дані」).',
             '‖ список λx 🜔інструмент … — паралельно: тіло — рівно один виклик (не запис, не жереб); аргументи — по черзі.',
             '☂ ловить помилки програми, але не вичерпання лімітів (--кроки, --розмір, «число завелике»).',
             'Квота: 「взяти:api.x≤100」, 「агент:аналітик≤5」, 「жереб≤3」 — не більше N викликів за запуск (понад — помилка).',
             '(повні назви файл.читати, мережа.взяти — синоніми). Поза печаткою — помилка до запуску.',
             'Рядок 「…」 (\\n \\」), список 【…】, словник 『к з …』, блок 《…》, коментар ※, так/ні/ніщо ● ○ ∅, мінус ¯5.',
             'До запуску ловляться: типи (＋ рядка й числа, умова не ●/○…), невідомі імена, арність, небезпечні регулярки.',
             'Модуль: ⊃ 「мод.ngr」 【「f」】 (верхній рівень); f кличуть за імʼям; печатка модуля ⊆ програми й діє (перетин прав);',
             'у модулі на верхньому рівні — лише функції й сталі.',
             'Шаблон 〔текст {вираз} текст〕 — як f-рядок (у {} один вираз): 〔{k}: {⌗ v 2}〕. Регулярки ⌕ ≋ — синтаксис re;',
             'Регулярки — рушій без відкатів (лінійний, кроки з --кроки); \\1 у шаблоні, (?=…), (?>…), (a?)+ — помилка.',
             '⇅ стабільне, ключ-список — складений: ⇅ п λp 【－0 §p 1 §p 0】 (спадання числа, потім абетка).',
             'Дроби — точні десяткові: ＋ － × до 60 цифр, ÷ — 28; ⌗ x 2 / ≅ x 2 — гроші (0–12 знаків).',
             'Імена — слова одного письма; ← імʼя вираз (лише на початку інструкції, назавжди). Умови — лише ●/○.',
             'УВАГА: ＋ － ＝ — ПОВНОШИРИННІ (U+FF0B, U+FF0D, U+FF1D), мінус числа ¯ (U+00AF). ASCII + - = — помилка.',
             'Опис інструмента клієнт може нормалізувати (＋→+); точні гліфи — в результаті nigredo_pamyatka.',
             'Гліфи (арність через сигнатуру):']
    for g, (ar, sig, desc, _, grp) in GLYPHS.items():
        lines.append(f'  {sig} — {desc}')
    lines.append('Інструменти: ' + '; '.join(TOOLS[t][1] for t in TOOLS))
    lines += ['Приклад: 🜂 【「читати:дані」】 ¦ ← n δ🜔читати 「x.json」 ¦ » ∫ n λx x',
              'Впевненість: усе з даних і під сумнівними умовами не впевненіше за джерело; змінити — лише ≈ (у слід).',
              'Канал завершення: якщо гілка під сумнівною умовою могла зупинити програму (☠ 🜍 ÷0 § виклик…) або операція',
              'могла впасти на сумнівному аргументі, то й решта запуску не впевненіша. Ліміти — єдиний невідстежений залишок.',
              'Двійники імен (x/х, h/һ, I/l за UTS #39), імена-«числа» (О O З Б), функція, схожа на гліф (х р v ф ~ × ρ ν φ),',
              'письма імен поза поширеними (коптське, вірменське…), і будь-що',
              'невидиме в тексті програми (керівні, bidi, теги, ZWSP, U+3164) — помилки. Числа — лише 0–9 або ０–９.',
              'Слід веде інтерпретатор (підписаний). Nigredo — прозорість і аудит, не пісочниця ОС.',
              'Намір, імена і вивід — слова автора (у печатці вони в 「」). Печатка необхідна, але не досить: перевіряй',
              'і слід (nigredo_pereviryty_slid з code) — він каже, чи були спроби поза правами («заборонено»).',
              'Субагент не може мати більше прав, ніж агент, що його викликає (і ніж дозволив власник).']
    return '\n'.join(lines)


# ------------------------------------------------------------------ командний рядок

USAGE = f"""Nigredo {VERSION}
  ngr ФАЙЛ.ngr | -e КОД  [-- аргументи програми]
    --печатка [--json]     що програмі дозволено (без виконання); код 3, якщо не в межах дозволів власника
    --розбір               переклад українським псевдокодом (без виконання)
    --слід ФАЙЛ|-          де ще вести слід (новий файл; - = stderr); слід ведеться завжди
                           у {OWNER_HOME}/сліди/
    --дозволи ФАЙЛ         звузити дозволи власника ({OWNER_HOME}/дозволи.json)
    --тека ТЕКА            для -e: виконувати як програму з цієї теки (з її правами «для_тек»)
    --слід-розмір N        найбільший слід у байтах (типово {MAX_TRACE})
    --зерно N              зерно для «жереб» (типово 0)
    --кроки N              ліміт кроків (типово {DEFAULT_STEPS})
    --розмір N             найбільший рядок/список (типово {MAX_SIZE})
  ngr --перевірити [--json] ФАЙЛ   усі помилки до запуску (розбір, типи, регулярки) і печатка — без виконання
  ngr --перевірити-слід ФАЙЛ [ПРОГРАМА]   (з програмою — ще й чи слід саме від неї)
  ngr --сухо ФАЙЛ.ngr      виконати без записів, надсилань, процесів і агентів (читання — так): їхній результат —
                           невідомий (впевненість 0); наприкінці — перелік дій, які програма зробила б
  ngr --тести [ТЕКА|ФАЙЛ …] [--json]   прогнати всі *.тест.ngr (кожен — програма з 🜍-перевірками; код 0 — пройшов)
  ngr --повторити СЛІД [ПРОГРАМА]   виконати знову без дій у світі: інструменти повертають записане (СЛІД.дані);
                           ті самі аргументи, тека, зерно; наприкінці — чи збігся вивід і завершення
  ngr --памʼятка           згенерувати памʼятку для агентів
"""


def run_tests(targets, as_json=False):
    """ngr --тести [ТЕКА|ФАЙЛ …]: кожен *.тест.ngr — окрема програма (зі своєю печаткою, слідом і 🜍-перевірками);
    пройшов — код 0. Підсумок і код виходу: 0 — усі пройшли, 1 — ні, 2 — тестів не знайдено."""
    import contextlib
    import io
    files = []
    for t in targets or ['.']:
        if os.path.isdir(t):
            for root_, _, names in os.walk(t):
                files += [os.path.join(root_, n) for n in names if n.endswith('.тест.ngr')]
        elif t.endswith('.ngr'):
            files.append(t)
    files = sorted(set(files))
    if not files:
        print('✗ тестів не знайдено (файли *.тест.ngr)', file=sys.stderr)
        return 2
    results = []
    for f in files:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main([f])
            except SystemExit as e:
                code = e.code
        first = (err.getvalue().strip().splitlines() or [''])[0]
        results.append({'файл': safe(f), 'код': code, 'пройшов': code == 0, 'помилка': safe(first) if code else ''})
    ok = sum(r['пройшов'] for r in results)
    if as_json:
        print(json.dumps({'пройшли': ok, 'усього': len(results), 'тести': results}, ensure_ascii=False, indent=1))
    else:
        for r in results:
            print(f'{"✓" if r["пройшов"] else "✗"} {r["файл"]}' + (f' — код {r["код"]}: {r["помилка"]}' if not r['пройшов'] else ''))
        print(f'{ok} з {len(results)} тестів пройшли')
    return 0 if ok == len(results) else 1


def load_replay(tpath, program=None):
    """Слід для --повторити: цілий (і від цієї програми, якщо її дано) + сховище значень, звірене з хешами."""
    msg = verify_trace(tpath, program)
    if not msg.startswith('✓'):
        return None, f'✗ повторити неможливо: {msg}'
    recs = [json.loads(line) for line in open(tpath, encoding='utf-8', newline='').read().split('\n') if line]
    store = {}
    try:
        with open(tpath + '.дані', encoding='utf-8') as f:
            for line in f:
                r = json.loads(line)
                if enc_hash(r['значення']) != r['sha256']:
                    return None, '✗ сховище значень (СЛІД.дані) змінено: вміст не збігається з хешем'
                store[r['sha256']] = r['значення']
    except FileNotFoundError:
        pass
    except (OSError, ValueError, KeyError, TypeError) as e:
        return None, f'✗ сховище значень (СЛІД.дані) не прочитати: {e}'
    tools = [r for r in recs if r.get('подія') == 'інструмент']
    lost = [i + 1 for i, r in enumerate(tools) if 'помилка' not in r and r.get('значення') not in store]
    if lost:
        return None, (f'✗ повторити неможливо: для викликів №{", ".join(map(str, lost[:5]))} немає значень '
                      f'(слід записано без СЛІД.дані або старою версією)')
    return {'початок': recs[0], 'інструменти': tools, 'сховище': store, 'вивід': [r.get('текст') for r in recs
            if r.get('подія') == 'вивід'], 'кінець': recs[-1]}, None


def dry_report(done, decided=1.0):
    print(f'── --сухо: {len(done)} дій не виконано' + (':' if done else ' (жодної дії назовні)'), file=sys.stderr)
    unsure = 0
    for name, args, ac in done:
        shown = ' '.join(a if isinstance(a, str) else f'‹{a.get("довжина")} символів›' for a in args)
        mark = ''
        if ac < 1:                   # аргументи чи сам вибір цієї дії залежать від невідомого (впевненість < 1)
            mark, unsure = f'  ⚠ залежить від невідомого (впевненість {ac:.2g}) — справжній запуск може зробити інше', unsure + 1
        print(f'  {name} {safe(shown)[:300]}{mark}', file=sys.stderr)
    if decided < 1:
        print(f'  ⚠ рішення програми залежали від невідомих у сухому прогоні значень (впевненість {decided:.2g}): '
              f'справжній запуск може піти іншим шляхом і зробити дії, яких тут немає', file=sys.stderr)
    if unsure:
        print(f'  ⚠ {unsure} з {len(done)} дій обрано чи складено за значеннями, яких сухий прогін не знає (зокрема за '
              f'результатами придушених дій): перелік — не обіцянка того, що зробить справжній запуск', file=sys.stderr)


def replay_report(replay, new_trace, ends):
    """Чи збігся повтор із записаним: вивід, кількість викликів, завершення."""
    recs = [json.loads(line) for line in open(new_trace, encoding='utf-8', newline='').read().split('\n') if line]
    out = [r.get('текст') for r in recs if r.get('подія') == 'вивід']
    end_old, end_new = replay['кінець'], recs[-1] if recs else {}
    same_end = end_old.get('подія') == end_new.get('подія') and end_old.get('повідомлення') == end_new.get('повідомлення')
    used = ends
    problems = []
    if out != replay['вивід']:
        k = next((i for i, (a, b) in enumerate(zip(out, replay['вивід'])) if a != b), min(len(out), len(replay['вивід'])))
        problems.append(f'вивід інший з рядка {k + 1}')
    if used != len(replay['інструменти']):
        problems.append(f'викликів інструментів {used}, а в сліді {len(replay["інструменти"])}')
    if not same_end:
        problems.append(f'завершення інше: було «{end_old.get("подія")}», тепер «{end_new.get("подія")}»')
    if problems:
        print(f'✗ повтор розійшовся зі слідом: {"; ".join(problems)}', file=sys.stderr)
        return 5
    if replay['початок'].get('інтерпретатор') != INTERP_SHA:
        print('  (слід записано іншою версією інтерпретатора — повтор перевіряє й те, що поведінка не змінилася)',
              file=sys.stderr)
    print(f'✓ повтор збігся зі слідом: {used} викликів інструментів (без дій у світі), {len(out)} записів виводу, '
          f'завершення «{end_new.get("подія")}»; слід повтору: {new_trace}', file=sys.stderr)
    return 0


def main(argv):
    decimal.setcontext(DEC_CTX.copy())
    opts = {'mode': 'run', 'trace': None, 'allow': None, 'seed': 0, 'steps': DEFAULT_STEPS, 'size': MAX_SIZE,
            'dir': None, 'tsize': MAX_TRACE, 'json': False}
    src = path = raw = None
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
            rest = [r for r in it]
            js = '--json' in rest or '--json' in argv[:argv.index(a)]
            rest = [r for r in rest if r != '--json']
            if not rest:
                print('✗ --перевірити-слід СЛІД [ПРОГРАМА] [--json]', file=sys.stderr)
                return 2
            tpath, rest = rest[0], rest[1:]
            msg = verify_trace(tpath, rest[0] if rest else None)
            print(verify_trace(tpath, rest[0] if rest else None, True) if js else msg)
            return 0 if msg.startswith('✓') else 1
        if a == '--тести':
            return run_tests([r for r in it if r != '--json'], '--json' in argv)
        if a == '--повторити':
            opts['mode'], opts['replay'] = 'повторити', next(it, None)
            if opts['replay'] is None:
                print('✗ --повторити СЛІД [ПРОГРАМА]', file=sys.stderr)
                return 2
            continue
        if a == '--сухо':
            opts['dry'] = True
            continue
        if a in ('--печатка', '--розбір', '--перевірити'):
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
        elif a == '--слід-розмір':
            opts['tsize'] = int(next(it))
        elif a == '--json':
            opts['json'] = True
        elif a == '--тека':
            opts['dir'] = os.path.realpath(next(it))
        elif a == '-e':
            src, path = next(it), '<-e>'
        else:
            if src is not None:
                print(f'✗ зайвий аргумент «{safe(a)}»: програма вже задана ({safe(path)}); аргументи програми — після --',
                      file=sys.stderr)
                return 2
            path = a
            try:
                raw = open(a, 'rb').read()
                src = raw.decode('utf-8')
            except (OSError, UnicodeDecodeError) as e:
                print(f'✗ {a}: {getattr(e, "strerror", None) or e}', file=sys.stderr)
                return 2
    replay = None
    if opts['mode'] == 'повторити':
        replay, err = load_replay(opts['replay'], path)
        if err:
            print(err, file=sys.stderr)
            return 1
        head = replay['початок']
        if src is None:
            if head.get('програма') == '<-e>':
                src, path, opts['dir'] = head.get('код'), '<-e>', head.get('тека')
                if src is None:
                    print('✗ у сліді немає коду -e програми (старий слід) — повторити неможливо', file=sys.stderr)
                    return 1
            else:
                path = os.path.join(head.get('тека', ''), os.path.basename(str(head.get('програма'))))
                try:
                    raw = open(path, 'rb').read()
                    src = raw.decode('utf-8')
                except (OSError, UnicodeDecodeError) as e:
                    print(f'✗ програму сліду не прочитати ({safe(path)}): {e} — дайте шлях: --повторити СЛІД ПРОГРАМА',
                          file=sys.stderr)
                    return 1
        if path != '<-e>':               # програма — це й її модулі: звірити sha256 кожного (суд 7)
            msg = verify_trace(opts['replay'], path)
            if not msg.startswith('✓'):
                print(f'✗ повторити неможливо: {msg}', file=sys.stderr)
                return 1
        sha_now = hashlib.sha256(raw if path != '<-e>' else src.encode()).hexdigest()
        if sha_now != head.get('sha256'):
            print('✗ програма не та, що в сліді (sha256 інший) — повторюється лише та сама програма', file=sys.stderr)
            return 1
        lim = head.get('ліміти') or {}
        prog_args = list(head.get('аргументи') or [])
        opts.update(seed=lim.get('зерно', 0), steps=lim.get('кроки', DEFAULT_STEPS), size=lim.get('розмір', MAX_SIZE),
                    tsize=lim.get('слід', MAX_TRACE))
    if src is None:
        print(USAGE, file=sys.stderr)
        return 2
    # шляхи — відносно теки програми; для -e — теки --тека (права теки) або поточної (без прав теки)
    if path == '<-e>':
        cwd = opts['dir'] or os.getcwd()
        dir_rights = opts['dir'] is not None
    else:
        cwd = os.path.dirname(os.path.abspath(path))
        dir_rights = True
    errors = []
    try:
        prog, perr = parse(src, cwd, None if path == '<-e>' else path, errors), None
        perr = errors[0] if errors else None
    except StaticError as e:
        prog, perr, errors = None, e, [e]
    try:
        allowed, source = load_allowlist(opts['allow'], cwd if dir_rights else None,
                                         os.path.realpath(path) if path != '<-e>' else None)
        base, _ = load_allowlist(opts['allow'])
        dir_extra = [a for a in allowed if a not in base] if dir_rights else None
    except Refused as e:
        print(e, file=sys.stderr)
        return 3
    if opts['mode'] == 'перевірити':
        missing = [safe(m) for m in check_program(prog, allowed, cwd)] if prog else []
        if opts['json']:
            print(json.dumps({'гаразд': not errors and not missing,
                              'помилки': [{'рядок': e.pos[0] if e.pos else None, 'стовпець': e.pos[1] if e.pos else None,
                                           'повідомлення': safe(e.msg)} for e in errors],
                              'печатка': {'в_межах': not missing, 'бракує': missing} if prog else None},
                             ensure_ascii=False, indent=1))
        else:
            for e in errors:
                print(safe(str(e)))
            if missing:
                print(f'✗ печатка просить більше, ніж дозволив власник: {", ".join(missing)}')
            if not errors and not missing:
                print('✓ помилок до запуску не знайдено; печатка в межах дозволів власника')
        return 2 if errors else 3 if missing else 0
    if opts['mode'] in ('розбір', 'печатка'):
        if perr:
            if opts['json']:
                print(json.dumps({'в_межах': False, 'помилка_розбору': safe(str(perr))}, ensure_ascii=False, indent=1))
            print(perr, file=sys.stderr)
            return 2
        if opts['mode'] == 'розбір':
            try:
                print(explain_program(prog))
            except RecursionError:
                print('✗ програма вкладена надто глибоко для перекладу (--розбір)', file=sys.stderr)
                return 2
            return 0
        info = seal_info(prog, allowed, source, cwd, dir_extra)
        info['програма'] = safe(path if path == '<-e>' else os.path.realpath(path))       # що саме перевірено
        info['sha256'] = hashlib.sha256(raw if path != '<-e>' else src.encode()).hexdigest()
        print(json.dumps(info, ensure_ascii=False, indent=1) if opts['json'] else seal_report(prog, allowed, source, cwd, dir_extra))
        return 0 if info['в_межах'] else 3
    # повтор нічого не робить у світі — дозволи власника не потрібні (і можуть уже змінитися)
    missing = check_program(prog, allowed, cwd) if prog and not replay else []
    sha = hashlib.sha256(raw if path != '<-e>' else src.encode()).hexdigest()
    key = owner_key()
    os.makedirs(os.path.join(OWNER_HOME, 'сліди'), mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    main_trace = os.path.join(OWNER_HOME, 'сліди', f'{stamp}-{sha[:8]}-{os.getpid()}.jsonl')
    paths = [main_trace]
    extra_stderr = opts['trace'] == '-'
    if opts['trace'] and not extra_stderr:
        paths.append(os.path.realpath(opts['trace']))
    seal_caps = prog[2][0][3] if prog else {}
    scopes = [os.path.realpath(os.path.join(cwd, w)) for t, ws in seal_caps.items() if t.startswith('файл.') for w in ws]
    for tp in paths[1:]:
        if inside(tp, OWNER_HOME) or any(inside(tp, w) for w in scopes):
            print(f'✗ слід «{safe(tp)}» лежить у теці власника чи в теці з печатки програми (читати, писати, список) — '
                  f'оберіть інше місце', file=sys.stderr)
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
    try:
        stores = [open(tp + '.дані', 'x', encoding='utf-8') for tp in paths]
    except OSError as e:
        print(f'✗ не вдалося створити сховище значень сліду: {e}', file=sys.stderr)
        return 3
    trace = Trace(outs, key, opts['tsize'], stores)
    code = 0
    shown_args = [a.encode('utf-8', 'surrogateescape').decode('utf-8', 'backslashreplace') for a in prog_args]
    try:
        trace('початок', версія=VERSION, інтерпретатор=INTERP_SHA, програма=safe(path.encode('utf-8', 'surrogateescape').decode('utf-8', 'backslashreplace')),
              sha256=sha, аргументи=shown_args,
              час=datetime.now(timezone.utc).isoformat(timespec='seconds'), запуск=os.urandom(6).hex(),
              тека=safe(cwd), дозволи_власника=safe(source), дозволено=allowed,
              ліміти={'кроки': opts['steps'], 'розмір': opts['size'], 'слід': opts['tsize'], 'зерно': opts['seed']},
              **({'код': src} if path == '<-e>' else {}), **({'повтор': safe(os.path.realpath(opts['replay']))} if replay else {}))
        if shown_args != prog_args:
            trace('відмова', причина='аргумент — не UTF-8 (неповний символ)')
            print('✗ аргумент програми — не UTF-8 (неповний символ); запуск відхилено', file=sys.stderr)
            return 2
        if perr:
            trace('відмова', причина='помилка до запуску', повідомлення=safe(str(perr)))
            print(perr, file=sys.stderr)
            return replay_report(replay, main_trace, 0) if replay else 2
        if missing:
            trace('відмова', бракує=missing)
            print(f'✗ печатка просить більше, ніж дозволив власник: {", ".join(missing)}\n'
                  f'  дозволи власника: {source}', file=sys.stderr)
            return 3
        interp = Interp(trace, seed=opts['seed'], steps=opts['steps'], cwd=cwd, argv=prog_args, protected=paths,
                        max_size=opts['size'])
        owner_q = Caps()
        for t, sc, q in owner_quotas(allowed):      # кілька квот на те саме — діє менша (суд 8)
            owner_q.quotas[(t, sc)] = min(q, owner_q.quotas.get((t, sc), q))
        if owner_q.quotas:                # квоти власника — для всього запуску (тека — як у дозволі: абсолютна)
            interp.quota_stack.append(('власник', owner_q, 'власник'))
        if replay:
            interp.replay = (replay['інструменти'], replay['сховище'])
        if opts.get('dry'):
            interp.dry = []
            trace('сухо', причина='--сухо: записи, надсилання, процеси й агенти не виконуються')
        try:
            try:
                interp.run(prog)
                trace('кінець', кроків=opts['steps'] - interp.steps_left)
            finally:
                if replay or opts.get('dry'):
                    sys.stdout.flush()
            if opts.get('dry'):
                dry_report(interp.dry, min(interp.decided_c, interp.halt_c, interp.pc))
            if replay:
                return replay_report(replay, main_trace, interp.ends)
        except NgrError as e:
            if interp.dry is not None:
                dry_report(interp.dry, min(interp.decided_c, interp.halt_c, interp.pc))
            trace('помилка', повідомлення=safe(str(e)))
            print(safe(str(e)), file=sys.stderr)
            code = 1
            if replay:
                return replay_report(replay, main_trace, interp.ends)
        except BrokenPipeError:                      # читач закрив вивід (| head) — тихо, без «вади мови»
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
            trace('помилка', повідомлення='вивід обірвано: читач закрив трубу')
            code = 1
        except Exception as e:                       # вада інтерпретатора: чесно, без трасування Python
            trace('помилка', внутрішня=True, повідомлення=f'{type(e).__name__}: {e}',
                  **({'останній_виклик': interp.last_call} if getattr(interp, 'last_call', None) else {}))
            print(f'✗ внутрішня помилка інтерпретатора Nigredo ({type(e).__name__}: {e}) — це вада мови, '
                  f'не програми; слід: {main_trace}', file=sys.stderr)
            code = 4
        return code
    finally:
        if os.environ.get('NIGREDO_TRACE_PATH_FILE'):
            try:
                with open(os.environ['NIGREDO_TRACE_PATH_FILE'], 'w', encoding='utf-8') as f:
                    f.write(main_trace)
            except OSError:
                pass
        for o in outs:
            if o is not sys.stderr:
                o.close()
        for o in locals().get('stores', []):
            o.close()


def entry():
    """Точка входу: глибока рекурсія — в окремому потоці з великим стеком. Запускач — interpreter/ngr.py."""
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
    return result[0]


if __name__ == '__main__':
    sys.exit(entry())
