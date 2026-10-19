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
    twins = sorted({N.skeleton(g): g for g in [*N.GLYPHS, *N.CONSTS] if len(g) == 1}.items())
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

    # регістр: символ → рядок (лише де відрізняється); остання сигма — класи case-ignorable / cased
    for name, f in (('LOWER', str.lower), ('UPPER', str.upper), ('CASEFOLD', str.casefold)):
        m = [(cp, f(ch(cp))) for cp in range(MAXCP) if not 0xD800 <= cp <= 0xDFFF and f(ch(cp)) != ch(cp)]
        out.append(f'pub static {name}: [(u32, &str); {len(m)}] = [' + ', '.join(f'({a}, {rs(b)})' for a, b in m) + '];')

    def sigma_class(cp):
        c = ch(cp)
        if 0xD800 <= cp <= 0xDFFF or cp == 0x3A3:
            return 0
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
    for name in ('MAX_DEPTH', 'MAX_NEST', 'MAX_SIZE', 'ALLOC_FACTOR', 'MAX_INT_BITS', 'MAX_TRACE', 'DEFAULT_STEPS',
                 'VALUE_MAX_DEPTH', 'DEC_EXP'):
        out.append(f'pub const {name}: u64 = {getattr(N, name)};')
    out.append(f'pub const UA_ORDER: &str = {rs("абвгґдеєжзиіїйклмнопрстуфхцчшщьюя")};')
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
    import errno
    se = [(i, errno.errorcode.get(i, ''), os.strerror(i)) for i in range(1, 134)]
    out.append(f'pub static STRERROR: [(i32, &str, &str); {len(se)}] = [' +
               ', '.join(f'({i}, {rs(c)}, {rs(t)})' for i, c, t in se) + '];')
    path = os.path.join(HERE, 'src', 'lang.rs')
    open(path, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    print(f'{path}: {os.path.getsize(path)} байтів')


if __name__ == '__main__':
    main()
