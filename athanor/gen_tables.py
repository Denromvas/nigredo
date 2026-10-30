#!/usr/bin/env python3
"""Таблиці Unicode для Атанора — з того самого Python і тих самих функцій інтерпретатора (interpreter/nigredo.py),
тож нативний виконавець бачить символи точно як еталон: категорії, цифри, письма, видимість, регістр, пробіли,
двійники. Запуск: python3 athanor/gen_tables.py → athanor/src/tables.rs (файл у репозиторії; збірка Python не
потребує). Звірка (athanor/звірка.py) перевіряє, що версія Unicode таблиць = версії Python, яким звіряють.

Нормалізація (NFC імен, NFKC у двійниках, NFD у скелетах) — не переноситься: символ, з яким вона могла б щось змінити
(«небезпечний»), Атанор не розбирає сам — передає програму еталону. Тут це перевірено на випадкових рядках."""
import os
import random
import sys
import unicodedata as U

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'interpreter'))
import nigredo as N  # noqa: E402

MAXCP = 0x110000
CATS = ['Lu', 'Ll', 'Lt', 'Lm', 'Lo', 'Mn', 'Mc', 'Me', 'Nd', 'Nl', 'No', 'Pc', 'Pd', 'Ps', 'Pe', 'Pi', 'Pf', 'Po',
        'Sm', 'Sc', 'Sk', 'So', 'Zs', 'Zl', 'Zp', 'Cc', 'Cf', 'Cs', 'Co', 'Cn']
SCRIPTS = sorted(N.NAME_SCRIPTS) + ['OTHER']


def rs(s):
    """Рядок Rust."""
    return '"' + ''.join(ch if 0x20 <= ord(ch) < 0x7f and ch not in '"\\' else f'\\u{{{ord(ch):x}}}' for ch in s) + '"'


def ranges(pred):
    """[(початок, кінець)] кодів, для яких pred істинне."""
    out, start = [], None
    for cp in range(MAXCP):
        ok = pred(cp)
        if ok and start is None:
            start = cp
        elif not ok and start is not None:
            out.append((start, cp - 1))
            start = None
    if start is not None:
        out.append((start, MAXCP - 1))
    return out


def ch(cp):
    return chr(cp)


def main():
    out = ['// Згенеровано athanor/gen_tables.py — не редагувати руками.',
           f'// Python {sys.version.split()[0]}, Unicode {U.unidata_version}.', '',
           f'pub const UNIDATA_VERSION: &str = {rs(U.unidata_version)};', '']

    # категорії: (початок, індекс категорії) — до наступного початку
    cat_runs, prev = [], None
    for cp in range(MAXCP):
        c = CATS.index(U.category(ch(cp)))
        if c != prev:
            cat_runs.append((cp, c))
            prev = c
    out.append(f'pub const CAT_NAMES: [&str; {len(CATS)}] = [' + ', '.join(rs(c) for c in CATS) + '];')
    out.append(f'pub static CAT_RUNS: [(u32, u8); {len(cat_runs)}] = [' +
               ', '.join(f'({a}, {b})' for a, b in cat_runs) + '];')

    # десяткові цифри (Nd): код → значення
    dec = [(cp, U.decimal(ch(cp))) for cp in range(MAXCP) if U.decimal(ch(cp), None) is not None]
    out.append(f'pub static DECIMAL: [(u32, u8); {len(dec)}] = [' + ', '.join(f'({a}, {b})' for a, b in dec) + '];')

    # письмо літер (Lu Ll Lt Lo) — лише ті, що мають значення для імен; решта — OTHER
    letters = [cp for cp in range(MAXCP) if U.category(ch(cp)) in ('Lu', 'Ll', 'Lt', 'Lo')]
    lr = []
    for cp in letters:
        sc = N.script_of(ch(cp))
        si = SCRIPTS.index(sc) if sc in N.NAME_SCRIPTS else len(SCRIPTS) - 1
        if lr and lr[-1][2] == si:
            lr[-1][1] = cp
        else:
            lr.append([cp, cp, si])
    out.append(f'pub const SCRIPT_NAMES: [&str; {len(SCRIPTS)}] = [' + ', '.join(rs(s) for s in SCRIPTS) + '];')
    out.append(f'pub static LETTER_SCRIPT: [(u32, u32, u8); {len(lr)}] = [' +
               ', '.join(f'({a}, {b}, {c})' for a, b, c in lr) + '];')

    # «небезпечні» для нормалізації: з ними NFC/NFKC/NFD рядка могли б відрізнятися від посимвольних
    second = set()
    for cp in range(MAXCP):
        d = U.decomposition(ch(cp))
        if d and not d.startswith('<'):
            parts = d.split()
            if len(parts) == 2:
                second.add(int(parts[1], 16))
    second |= set(range(0x1161, 0x1176)) | set(range(0x11A8, 0x11C3))      # голосні й кінцеві чамо хангиля

    def unsafe(cp):
        c = ch(cp)
        if 0xD800 <= cp <= 0xDFFF:
            return True
        if U.combining(c) or cp in second:
            return True
        if U.normalize('NFC', c) != c or U.normalize('NFKC', c) != c:
            return True
        d = U.normalize('NFD', c)
        if U.combining(d[0]):
            return True
        sk = N.skeleton(c)
        if sk and U.combining(sk[0]):
            return True
        return False
    unsafe_r = ranges(unsafe)
    out.append(f'pub static NORM_UNSAFE: [(u32, u32); {len(unsafe_r)}] = [' +
               ', '.join(f'({a}, {b})' for a, b in unsafe_r) + '];')

    # скелети UTS #39 для безпечних символів, де скелет ≠ символ
    skel = []
    for cp in range(MAXCP):
        if 0xD800 <= cp <= 0xDFFF or unsafe(cp):
            continue
        s = N.skeleton(ch(cp))
        if s != ch(cp):
            skel.append((cp, s))
    out.append(f'pub static SKELETON: [(u32, &str); {len(skel)}] = [' +
               ', '.join(f'({a}, {rs(b)})' for a, b in skel) + '];')
    # підпис автора (огляди 11б, 11в): посимвольна міра nigredo.sig_char. Атанор бере скелет із SKELETON (чи сам символ)
    # і клас (літера/знак/цифра — сам, малими; решта — межа \x01), «небезпечний» — розрив \0; де еталон бачить інакше
    # (NFKD, знак зі скелетом-розділовим, повноширинні…), — виняток SIG_CHARS. Порівнюються зведені форми: літери
    # «ed25519» — самі, межа — \x01, решта — \0 (для пошуку з початку слова цього досить)
    sig_t = N.sig_marks('ed25519')[0]
    assert '\x01' not in sig_t and '\0' not in sig_t, ascii(sig_t)

    def sig_reduce(xs):
        r = ''.join(x if x in sig_t or x == '\x01' else '\0' for x in xs)
        while '\0\0' in r or '\x01\x01' in r:
            r = r.replace('\0\0', '\0').replace('\x01\x01', '\x01')
        return r
    smap0 = dict(skel)

    def sig_default(cp):
        if unsafe(cp):
            return '\0'
        return ''.join(x.lower() if x.isascii() and U.category(x)[0] in 'LMN' else
                       x if U.category(x)[0] in 'LMN' else '\x01' for x in smap0.get(cp, ch(cp)))
    sig_u = []
    for cp in range(MAXCP):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        ref = sig_reduce(N.sig_char(ch(cp)))
        if U.combining(ch(cp)):
            assert not set(ref) & set(sig_t), hex(cp)        # знак літер «ed25519» не дає
        if sig_reduce(sig_default(cp)) != ref:
            sig_u.append((cp, ref))
    out.append(f'pub static SIG_TARGET: &str = {rs(sig_t)};')
    out.append(f'pub static SIG_CHARS: [(u32, &str); {len(sig_u)}] = [' +
               ', '.join(f'({a}, {rs(b)})' for a, b in sig_u) + '];')
    twins = sorted(N.glyph_twin_table().items())
    out.append(f'pub static DIGIT_SKELETON: &str = {rs(N.digit_skeleton())};')
    # літери, яких UTS #39 не радить для імен (interpreter/літери.tsv), і літери-цифри (丨 Ҙ ҙ): імʼя з ними розбирає еталон
    N.restricted_letter('\u0100')
    rl = []
    for a, b, _ in N._LETTERS:
        if rl and rl[-1][1] == a - 1:
            rl[-1][1] = b
        else:
            rl.append([a, b])
    out.append(f'pub static RESTRICTED_LETTERS: [(u32, u32); {len(rl)}] = [' + ', '.join(f'({a}, {b})' for a, b in rl) + '];')
    out.append(f'pub static DIGIT_LETTERS: &str = {rs("".join(sorted(N.DIGIT_LETTERS)))};')
    out.append(f'pub static GLYPH_TWIN: [(&str, &str); {len(twins)}] = [' +
               ', '.join(f'({rs(a)}, {rs(b)})' for a, b in twins) + '];')

    # видимість, пробіли, літери-й-цифри (\\w), цифри (isdigit)
    for name, pred in (('INVISIBLE', lambda cp: N.invisible(ch(cp))), ('ISSPACE', lambda cp: ch(cp).isspace()),
                       ('ISALNUM', lambda cp: ch(cp).isalnum()), ('ISDIGIT', lambda cp: ch(cp).isdigit())):
        r = ranges(pred)
        out.append(f'pub static {name}: [(u32, u32); {len(r)}] = [' + ', '.join(f'({a}, {b})' for a, b in r) + '];')

    # бітові карти BMP (0..0xFFFF) для швидкої перевірки: невидимі, пробіли, літери-й-цифри
    for name, pred in (('INVISIBLE_BMP', lambda cp: N.invisible(ch(cp))), ('ISSPACE_BMP', lambda cp: ch(cp).isspace()),
                       ('ISALNUM_BMP', lambda cp: ch(cp).isalnum())):
        words = [0] * 1024
        for cp in range(0x10000):
            if pred(cp):
                words[cp >> 6] |= 1 << (cp & 63)
        out.append(f'pub static {name}: [u64; 1024] = [' + ', '.join(f'{w:#x}' for w in words) + '];')

    # ідентифікатори Python (назви груп у регулярках): початок і продовження
    r = ranges(lambda cp: not 0xD800 <= cp <= 0xDFFF and ch(cp).isidentifier())
    out.append(f'pub static ID_START: [(u32, u32); {len(r)}] = [' + ', '.join(f'({a}, {b})' for a, b in r) + '];')
    r = ranges(lambda cp: not 0xD800 <= cp <= 0xDFFF and ('a' + ch(cp)).isidentifier())
    out.append(f'pub static ID_CONT: [(u32, u32); {len(r)}] = [' + ', '.join(f'({a}, {b})' for a, b in r) + '];')
    r = ranges(lambda cp: not 0xD800 <= cp <= 0xDFFF and ch(cp).isprintable())
    out.append(f'pub static PRINTABLE: [(u32, u32); {len(r)}] = [' + ', '.join(f'({a}, {b})' for a, b in r) + '];')

    # регістр: символ → рядок (лише де відрізняється); остання сигма — класи case-ignorable / cased
    for name, f in (('LOWER', str.lower), ('UPPER', str.upper), ('CASEFOLD', str.casefold)):
        m = [(cp, f(ch(cp))) for cp in range(MAXCP) if not 0xD800 <= cp <= 0xDFFF and f(ch(cp)) != ch(cp)]
        out.append(f'pub static {name}: [(u32, &str); {len(m)}] = [' + ', '.join(f'({a}, {rs(b)})' for a, b in m) + '];')

    def sigma_class(cp):
        c = ch(cp)
        if 0xD800 <= cp <= 0xDFFF:
            return 0
        if cp == 0x3A3:                  # сама Σ — cased (пробою «…Σ» її не визначити; суд 9: ΣΣ → σσ замість σς)
            return 2
        back_a = ('A' + c + 'Σ').lower()[-1] == 'ς'
        back_c = (c + 'Σ').lower()[-1] == 'ς'
        fwd = ('AΣ' + c).lower()[1] == 'ς'
        if back_a and not back_c:
            assert fwd, hex(cp)
            return 1                     # case-ignorable
        if back_c:
            assert back_a and not fwd, hex(cp)
            return 2                     # cased, не ignorable
        assert fwd, hex(cp)
        return 0
    runs, prev = [], None
    for cp in range(MAXCP):
        k = sigma_class(cp)
        if k != prev:
            runs.append((cp, k))
            prev = k
    out.append(f'pub static SIGMA_CLASS: [(u32, u8); {len(runs)}] = [' + ', '.join(f'({a}, {b})' for a, b in runs) + '];')

    path = os.path.join(HERE, 'src', 'tables.rs')
    open(path, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    print(f'{path}: {os.path.getsize(path)} байтів')
    lang()

    # перевірка: на рядках із безпечних символів нормалізація нічого не міняє, а скелет — посимвольний
    rng = random.Random(1)
    unsafe_set = set()
    for a, b in unsafe_r:
        if b - a < 100000:
            unsafe_set.update(range(a, b + 1))
    pool = [cp for cp in letters if cp not in unsafe_set] + list(range(0x30, 0x3A)) + [0x5F, 0x2BC, 0x27]
    near = [cp for cp in pool if cp < 0x3000]          # латиниця, кирилиця й сусіди — частіше за CJK
    smap = dict(skel)
    for _ in range(300000):
        s = ''.join(ch(rng.choice(near if rng.random() < .8 else pool)) for _ in range(rng.randint(1, 6)))
        assert U.normalize('NFC', s) == s and U.normalize('NFKC', s) == s, ascii(s)
        assert N.skeleton(s) == ''.join(smap.get(ord(c), c) for c in s), ascii(s)
    print('перевірка нормалізації й скелетів: гаразд')

    # перевірка sig_like Атанора (uni::sig_like) проти еталона: кожен символ, де Атанор бере SIG_CHARS чи розрив, — у
    # кожному місці «ed25519», замість кожної його літери й перед ним; і випадкові рядки з двійників, знаків (і тих, чий
    # скелет — розділовий), розділових, пробілів і слів, що закінчуються на «ed» (огляди 11б, 11в)
    import bisect
    starts = [a for a, _ in unsafe_r]
    sig_map = dict(sig_u)

    def is_unsafe(cp):
        i = bisect.bisect_right(starts, cp) - 1
        return i >= 0 and unsafe_r[i][0] <= cp <= unsafe_r[i][1]
    tl = list(sig_t)

    def ath_sig(text):
        sk = []

        def push(x):
            if x != '\x01' or not sk or sk[-1] != '\x01':
                sk.append(x)
        for c in text:
            cp = ord(c)
            if cp in sig_map:
                for x in sig_map[cp]:
                    push(x)
            elif is_unsafe(cp):
                push('\0')
            else:
                for x in smap.get(cp, c):
                    push((x.lower() if x.isascii() else x) if U.category(x)[0] in 'LMN' else '\x01')
        for p in range(len(sk)):
            if sk[p] != tl[0] or (p > 0 and sk[p - 1] != '\x01'):
                continue
            i, j = p, 0
            while i < len(sk) and j < len(tl):
                if sk[i] == tl[j]:
                    i, j = i + 1, j + 1
                elif sk[i] == '\x01' and j > 0:
                    i += 1
                else:
                    break
            if j == len(tl):
                return True
        return False
    base = 'ed25519'
    n = 0
    for cp in sorted(set(sig_map) | {cp for cp in range(0x300, 0x370)}):
        c = ch(cp)
        for i in range(len(base) + 1):
            for s in (base[:i] + c + base[i:], base[:i] + c + base[i + 1:], 'x' + c + base, c + ' ' + base):
                assert ath_sig(s) == N.sig_like(s), (hex(cp), ascii(s))
                n += 1
    marks = [cp for cp in range(0x300, 0x370)] + [0x31A, 0x32E, 0x348, 0x5B0, 0x5BC, 0x1BF3, 0x1CD8, 0x1DE8, 0x2DEE,
                                                   0x1D16D, 0x1AB0, 0x1DC0, 0x20D0, 0x302A, 0xFE20]
    pool = ([ord(x) for x in 'edEDl1I259 -_.:rs'] + [a for a, _ in sig_u][::7] + marks +
            [cp for cp in range(0xFF01, 0xFF5F)] + [0x2011, 0x2014, 0x00B7, 0x037E, 0x0435, 0x0501, 0x2147, 0x2146,
                                                    0x217E, 0x24D4, 0x24D3, 0x00B2, 0x00A0, 0x3000, 0x0301, 0x0306])
    for _ in range(300000):
        s = ''.join(ch(rng.choice(pool)) for _ in range(rng.randint(5, 12)))
        if rng.random() < .5:
            k = rng.randint(0, len(s))
            s = s[:k] + rng.choice(['ed2551', 'd25519', 'ed25', '25519', 'Ed', 'ED2', ' ed-2', 'red 255', ' e d ']) + s[k:]
        assert ath_sig(s) == N.sig_like(s), ascii(s)
        n += 1
    print(f'перевірка sig_like ({len(sig_u)} винятків у SIG_CHARS, {n} рядків): гаразд')


def lang():
    """Таблиці мови з nigredo.py: гліфи (арність; -1 — особлива форма), сталі, інструменти, синоніми, множини."""
    out = ['// Згенеровано athanor/gen_tables.py з interpreter/nigredo.py — не редагувати руками.', '',
           f'pub const VERSION: &str = {rs(N.VERSION)};']
    gl = sorted(N.GLYPHS.items())
    out.append(f'pub static GLYPHS: [(char, i8); {len(gl)}] = [' +
               ', '.join(f"('\\u{{{ord(g):x}}}', {-1 if v[0] is None else v[0]})" for g, v in gl) + '];')
    tools = list(N.TOOLS.items())
    out.append(f'pub static TOOLS: [(&str, u8, bool, &str); {len(tools)}] = [' +
               ', '.join(f'({rs(k)}, {v[0]}, {str(v[3]).lower()}, {rs(v[4])})' for k, v in tools) + '];')
    al = list(N.TOOL_ALIASES.items())
    for name in ('SQL_ERRORS', 'RE_ERRORS', 'XML_ERRORS'):
        t = getattr(N, name)
        out.append(f'pub static {name}: [(&str, &str); {len(t)}] = [' + ', '.join(f'({rs(a)}, {rs(b)})' for a, b in t) + '];')
    out.append(f'pub static TOOL_ALIASES: [(&str, &str); {len(al)}] = [' + ', '.join(f'({rs(a)}, {rs(b)})' for a, b in al) + '];')
    for name in ('HEAVY', 'LAZY_GLYPHS', 'OWN_CONF', 'NEVER_FAILS', 'PURE_GLYPHS'):
        out.append(f'pub const {name}: &str = {rs("".join(sorted(getattr(N, name))))};')
        alts = ' | '.join(f"'\\u{{{ord(g):x}}}'" for g in sorted(getattr(N, name)))
        out.append(f'#[inline]\npub fn is_{name.lower()}(g: char) -> bool {{\n    matches!(g, {alts})\n}}')
    for name in ('WORLD_WRITERS', 'WORLD_READERS', 'PARALLEL_TOOLS', 'WRITE_TOOLS', 'DEFAULT_ALLOWED'):
        v = getattr(N, name)
        v = sorted(v) if isinstance(v, set) else list(v)
        out.append(f'pub static {name}: [&str; {len(v)}] = [' + ', '.join(rs(x) for x in v) + '];')
    fs = sorted(N.FN_SLOTS.items())
    out.append(f'pub static FN_SLOTS: [(char, &[usize]); {len(fs)}] = [' +
               ', '.join(f"('\\u{{{ord(g):x}}}', &[{', '.join(map(str, v))}])" for g, v in fs) + '];')
    for name in ('MAX_DEPTH', 'MAX_NEST', 'MAX_WORK', 'MAX_SIZE', 'ALLOC_FACTOR', 'MAX_INT_BITS', 'MAX_TRACE', 'DEFAULT_STEPS',
                 'VALUE_MAX_DEPTH', 'WALK_MAX_DEPTH', 'DEC_EXP'):
        out.append(f'pub const {name}: u64 = {getattr(N, name)};')
    out.append(f'pub const UA_ORDER: &str = {rs("абвгґдеєжзиіїйклмнопрстуфхцчшщьюя")};')
    xc = sorted(N.RX_EXTRA_CASES.items())      # (?i): малі літери, рівні між собою (re._casefix)
    out.append(f'pub static RX_EXTRA_CASES: [(u32, &[u32]); {len(xc)}] = [' +
               ', '.join(f"(0x{k:x}, &[{', '.join(f'0x{x:x}' for x in v)}])" for k, v in xc) + '];')
    # типи до запуску: TYPE_REQ — гліф → альтернативи (рядок назв через кому), TYPE_RES, TOOL_TYPES
    req = sorted(N.TYPE_REQ.items())
    out.append(f'pub static TYPE_REQ: [(char, &[&str]); {len(req)}] = [' +
               ', '.join(f"('\\u{{{ord(g):x}}}', &[{', '.join(rs(','.join(a)) for a in alts)}])" for g, alts in req) + '];')
    res = sorted(N.TYPE_RES.items())
    out.append(f'pub static TYPE_RES: [(char, &str); {len(res)}] = [' +
               ', '.join(f"('\\u{{{ord(g):x}}}', {rs(t)})" for g, t in res) + '];')
    tt = list(N.TOOL_TYPES.items())
    out.append(f'pub static TOOL_TYPES: [(&str, &str, &str); {len(tt)}] = [' +
               ', '.join(f'({rs(k)}, {rs(",".join(a))}, {rs(r)})' for k, (a, r) in tt) + '];')
    # замок ОС (фаза 6.1): ті самі групи й номери системних викликів, що й в еталоні — фільтр будують обидва однаково
    out.append(f'pub static OS_GROUPS: [&str; {len(N.OS_GROUPS)}] = [' + ', '.join(rs(g) for g in N.OS_GROUPS) + '];')
    out.append(f'pub static OS_OPENED_BY: [&[&str]; {len(N.OS_GROUPS)}] = [' +
               ', '.join('&[' + ', '.join(rs(t) for t in N.OS_OPENED_BY[g]) + ']' for g in N.OS_GROUPS) + '];')
    out.append(f'pub const OS_WRITE_FLAGS: u32 = {N.OS_WRITE_FLAGS};')
    out.append(f'pub const ED_SMALL: [&str; {len(N.ED_SMALL)}] = [' + ', '.join(rs(x) for x in sorted(N.ED_SMALL)) + '];')
    out.append('pub struct OsTable {\n    pub arch: &\'static str,\n    pub audit: u32,\n    pub seccomp: i64,\n    pub x32: bool,\n'
               '    pub always: &\'static [u32],\n    pub groups: [&\'static [u32]; 3],\n    pub open: &\'static [(u32, u32)],\n'
               '    pub open2: &\'static [u32],\n}')
    nums = lambda xs: '&[' + ', '.join(str(x) for x in xs) + ']'   # noqa: E731
    out.append(f'pub static OS_TABLES: [OsTable; {len(N.OS_TABLES)}] = [' + ', '.join(
        f'OsTable {{ arch: {rs(a)}, audit: {T["audit"]:#x}, seccomp: {T["seccomp"]}, x32: {str(T["x32"]).lower()}, '
        f'always: {nums(T["завжди"])}, groups: [{", ".join(nums(T[g]) for g in N.OS_GROUPS)}], '
        f'open: &[{", ".join(f"({n}, {i})" for n, i in T["відкрити"])}], open2: {nums(T["відкрити2"])} }}'
        for a, T in N.OS_TABLES.items()) + '];')
    import errno
    se = [(i, errno.errorcode.get(i, ''), os.strerror(i)) for i in range(1, 134)]
    out.append(f'pub static STRERROR: [(i32, &str, &str); {len(se)}] = [' +
               ', '.join(f'({i}, {rs(c)}, {rs(t)})' for i, c, t in se) + '];')
    path = os.path.join(HERE, 'src', 'lang.rs')
    open(path, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    print(f'{path}: {os.path.getsize(path)} байтів')


if __name__ == '__main__':
    main()
