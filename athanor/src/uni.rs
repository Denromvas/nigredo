//! Символи як у еталоні (Python 3 str + unicodedata): таблиці — з gen_tables.py.
use crate::tables::*;

fn in_ranges(t: &[(u32, u32)], cp: u32) -> bool {
    match t.binary_search_by(|&(a, _)| a.cmp(&cp)) {
        Ok(_) => true,
        Err(0) => false,
        Err(i) => cp <= t[i - 1].1,
    }
}

fn run_val(t: &[(u32, u8)], cp: u32) -> u8 {
    match t.binary_search_by(|&(a, _)| a.cmp(&cp)) {
        Ok(i) => t[i].1,
        Err(i) => t[i - 1].1,
    }
}

fn map_str(t: &'static [(u32, &'static str)], cp: u32) -> Option<&'static str> {
    t.binary_search_by(|&(a, _)| a.cmp(&cp)).ok().map(|i| t[i].1)
}

pub fn category(c: char) -> &'static str {
    CAT_NAMES[run_val(&CAT_RUNS, c as u32) as usize]
}

pub fn is_letter(c: char) -> bool {
    run_val(&CAT_RUNS, c as u32) <= 4 // Lu Ll Lt Lm Lo
}

pub fn decimal(c: char) -> Option<u32> {
    if c.is_ascii_digit() {
        return Some(c as u32 - 48);
    }
    let cp = c as u32;
    DECIMAL.binary_search_by(|&(a, _)| a.cmp(&cp)).ok().map(|i| DECIMAL[i].1 as u32)
}

/// Письмо літери (Lu Ll Lt Lo) для правила «одне письмо в імені»: назва з NAME_SCRIPTS або «OTHER».
pub fn letter_script(c: char) -> &'static str {
    let cp = c as u32;
    let i = match LETTER_SCRIPT.binary_search_by(|&(a, _, _)| a.cmp(&cp)) {
        Ok(i) => i,
        Err(0) => return "OTHER",
        Err(i) => i - 1,
    };
    let (a, b, s) = LETTER_SCRIPT[i];
    if a <= cp && cp <= b {
        SCRIPT_NAMES[s as usize]
    } else {
        "OTHER"
    }
}

/// Символ, з яким нормалізація (NFC/NFKC/NFD) рядка могла б відрізнятися від посимвольної: такі імена розбирає еталон.
pub fn norm_unsafe(c: char) -> bool {
    in_ranges(&NORM_UNSAFE, c as u32)
}

/// Скелет UTS #39 рядка з безпечних символів (як nigredo.skeleton); None — є небезпечний символ.
pub fn skeleton(s: &str) -> Option<String> {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        if norm_unsafe(c) {
            return None;
        }
        match map_str(&SKELETON, c as u32) {
            Some(t) => out.push_str(t),
            None => out.push(c),
        }
    }
    Some(out)
}

const SIG_SEP: char = '\u{1}';

fn sig_push(sk: &mut Vec<char>, x: char) {
    if x != SIG_SEP || sk.last() != Some(&SIG_SEP) {
        sk.push(x);
    }
}

fn sig_class(x: char) -> char {
    if matches!(category(x).as_bytes()[0], b'L' | b'M' | b'N') {
        x.to_ascii_lowercase()
    } else {
        SIG_SEP
    }
}

/// Коментар, схожий на рядок підпису (як nigredo.sig_like): та сама посимвольна міра sig_char — літери, знаки й цифри
/// скелета (латиниця малими), решта — межа; «ed25519» з початку слова, межі між літерами не важать. Символ, для якого
/// скелет із SKELETON (чи сам символ) дав би не те, що еталон (NFKD, повноширинні, математичні, ⅇ, ⅾ, ⓔ, знак зі скелетом-
/// розділовим…), — із таблиці SIG_CHARS; решта «небезпечних» — розрив. gen_tables.py звіряє кожен символ Unicode й
/// контексти (огляди 11б, 11в).
pub fn sig_like(text: &str) -> bool {
    let mut sk: Vec<char> = Vec::with_capacity(text.len());
    for c in text.chars() {
        if let Some(t) = map_str(&SIG_CHARS, c as u32) {
            t.chars().for_each(|x| sig_push(&mut sk, x));
        } else if norm_unsafe(c) {
            sig_push(&mut sk, '\0');
        } else {
            match map_str(&SKELETON, c as u32) {
                Some(t) => t.chars().for_each(|x| sig_push(&mut sk, sig_class(x))),
                None => sig_push(&mut sk, sig_class(c)),
            }
        }
    }
    let t: Vec<char> = SIG_TARGET.chars().collect();
    (0..sk.len()).any(|p| {
        if sk[p] != t[0] || (p > 0 && sk[p - 1] != SIG_SEP) {
            return false;
        }
        let (mut i, mut j) = (p, 0);
        while i < sk.len() && j < t.len() {
            if sk[i] == t[j] {
                i += 1;
                j += 1;
            } else if sk[i] == SIG_SEP && j > 0 {
                i += 1;
            } else {
                break;
            }
        }
        j == t.len()
    })
}

pub fn glyph_twin(skel: &str) -> Option<&'static str> {
    GLYPH_TWIN.binary_search_by(|&(a, _)| a.cmp(skel)).ok().map(|i| GLYPH_TWIN[i].1)
}

/// Літера, якої UTS #39 не радить для імен (interpreter/літери.tsv; ƻ ≈ 2, ꜫ ≈ 3 — суд 9д), чи літера-цифра (丨 Ҙ ҙ):
/// імʼя з нею розбирає еталон.
pub fn odd_letter(c: char) -> bool {
    c as u32 >= 0x80 && (in_ranges(&RESTRICTED_LETTERS, c as u32) || DIGIT_LETTERS.contains(c))
}

/// Найкоротший шматок, повтором якого є рядок (xx → x, 乂乂 → 乂), або сам рядок (як nigredo.unit).
pub fn unit(cs: &[char]) -> &[char] {
    let n = cs.len();
    (1..=n / 2).find(|&k| n % k == 0 && cs.chunks(k).all(|c| c == &cs[..k])).map_or(cs, |k| &cs[..k])
}

/// Гліф, на який схоже імʼя функції, — і з цифрами в кінці (x5 ≈ ×5, 十5 ≈ ＋5; суд 9в), і повтором (xx ≈ ××; суд 9г),
/// як nigredo.glyph_twin.
pub fn glyph_twin_name(skel: &str) -> Option<&'static str> {
    let cs: Vec<char> = skel.chars().collect();
    let s = |c: &[char]| c.iter().collect::<String>();
    let hit = |c: &[char]| glyph_twin(&s(c)).or_else(|| glyph_twin(&s(unit(c))));
    let mut k = cs.len();
    while k > 1 && DIGIT_SKELETON.contains(cs[k - 1]) && hit(&cs[..k]).is_none() {
        k -= 1;
    }
    hit(&cs[..k])
}

/// Імʼя без хвоста з цифр 0–9 (乂5 → 乂, ø1 → ø; лише цифри — саме імʼя).
pub fn digitless(v: &str) -> &str {
    let t = v.trim_end_matches(|c: char| c.is_ascii_digit());
    if t.is_empty() { v } else { t }
}

/// Імʼя функції — повтор одного ієрогліфа чи знака кани (匚匚 ≈ ⊏⊏, ハハ; суд 9д), і з цифрами: помилку пише еталон.
pub fn cjk_repeat(v: &str) -> bool {
    let cs: Vec<char> = digitless(v).chars().collect();
    let u = unit(&cs);
    u.len() == 1 && matches!(letter_script(u[0]), "CJK" | "HIRAGANA" | "KATAKANA")
}

/// NAME_TWINS еталона (за самим іменем, без цифр і повтору): ƒ ≈ ∫, ɜ ≈ ∋.
pub fn name_twin(v: &str) -> bool {
    let cs: Vec<char> = digitless(v).chars().collect();
    matches!(unit(&cs).iter().collect::<String>().as_str(), "ƒ" | "ɜ")
}

/// in_words: текст помилки бібліотеки — словами (оригінал у дужках), за першим збігом з таблиці (як nigredo.in_words).
pub fn in_words(table: &[(&str, &str)], m: &str) -> String {
    for (en, uk) in table {
        if m.contains(en) {
            return format!("{} ({})", uk, m);
        }
    }
    m.to_string()
}

/// Імʼя лише зі скелетів цифр (l0 ≈ 10, б ≈ 6, IOO ≈ 100; суд 9в) — виглядає як число.
pub fn looks_numeric(skel: &str) -> bool {
    !skel.is_empty() && skel.chars().all(|c| DIGIT_SKELETON.contains(c))
}

#[inline]
fn bit(t: &[u64; 1024], cp: u32) -> bool {
    t[(cp >> 6) as usize] >> (cp & 63) & 1 == 1
}

#[inline]
pub fn invisible(c: char) -> bool {
    let cp = c as u32;
    if cp < 0x10000 { bit(&INVISIBLE_BMP, cp) } else { in_ranges(&INVISIBLE, cp) }
}

#[inline]
pub fn isspace(c: char) -> bool {
    let cp = c as u32;
    if cp < 0x10000 { bit(&ISSPACE_BMP, cp) } else { in_ranges(&ISSPACE, cp) }
}

#[inline]
pub fn isalnum(c: char) -> bool {
    let cp = c as u32;
    if cp < 0x10000 { bit(&ISALNUM_BMP, cp) } else { in_ranges(&ISALNUM, cp) }
}

pub fn isdigit(c: char) -> bool {
    in_ranges(&ISDIGIT, c as u32)
}

fn sigma_class(c: char) -> u8 {
    run_val(&SIGMA_CLASS, c as u32)
}

/// str.lower() з правилом кінцевої сигми (як у CPython).
pub fn lower(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let chars: Vec<char> = if s.contains('Σ') { s.chars().collect() } else { Vec::new() };
    for (i, c) in s.chars().enumerate() {
        if c == 'Σ' {
            out.push(final_sigma(&chars, i));
            continue;
        }
        if c.is_ascii() {
            out.push(c.to_ascii_lowercase());
        } else {
            match map_str(&LOWER, c as u32) {
                Some(t) => out.push_str(t),
                None => out.push(c),
            }
        }
    }
    out
}

fn final_sigma(cs: &[char], i: usize) -> char {
    let mut j = i as isize - 1;
    while j >= 0 && sigma_class(cs[j as usize]) == 1 {
        j -= 1;
    }
    let mut fin = j >= 0 && sigma_class(cs[j as usize]) == 2;
    if fin && i + 1 < cs.len() {
        let mut k = i + 1;
        while k < cs.len() && sigma_class(cs[k]) == 1 {
            k += 1;
        }
        fin = k == cs.len() || sigma_class(cs[k]) != 2;
    }
    if fin { 'ς' } else { 'σ' }
}

pub fn upper(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        if c.is_ascii() {
            out.push(c.to_ascii_uppercase());
        } else {
            match map_str(&UPPER, c as u32) {
                Some(t) => out.push_str(t),
                None => out.push(c),
            }
        }
    }
    out
}

pub fn casefold(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match map_str(&CASEFOLD, c as u32) {
            Some(t) => out.push_str(t),
            None => out.push(c),
        }
    }
    out
}

/// Один символ у нижньому регістрі (рядок: може бути довшим за символ).
pub fn lower_char(c: char) -> String {
    match map_str(&LOWER, c as u32) {
        Some(t) => t.to_string(),
        None => c.to_string(),
    }
}

/// Проста мала літера (_sre.unicode_tolower): перший символ повної.
pub fn lower1(c: char) -> char {
    match map_str(&LOWER, c as u32) {
        Some(t) => t.chars().next().unwrap_or(c),
        None => c,
    }
}

/// Проста велика літера (_sre.unicode_toupper): перший символ повної («ß» → «S»).
pub fn upper1(c: char) -> char {
    match map_str(&UPPER, c as u32) {
        Some(t) => t.chars().next().unwrap_or(c),
        None => c,
    }
}

pub fn upper_char(c: char) -> String {
    match map_str(&UPPER, c as u32) {
        Some(t) => t.to_string(),
        None => c.to_string(),
    }
}

/// str.strip() — пробіли Unicode з обох країв.
pub fn strip(s: &str) -> &str {
    s.trim_matches(|c: char| isspace(c))
}

pub fn strip_chars<'a>(s: &'a str, set: &str) -> &'a str {
    s.trim_matches(|c: char| set.contains(c))
}

/// str.split() без роздільника.
pub fn split_ws(s: &str) -> Vec<&str> {
    s.split(|c: char| isspace(c)).filter(|p| !p.is_empty()).collect()
}

/// hidden(text, allow): невидимі символи тексту (крім allow), селектор вигляду після значка (So) — видимий.
/// Чи є в тексті невидимий символ (крім allow) — швидко: ASCII і двобайтові без невидимих пропускаються за байтом.
fn any_invisible(text: &str, allow: &str) -> bool {
    let b = text.as_bytes();
    let (nl, tab) = (allow.contains('\n'), allow.contains('\t'));
    let mut i = 0;
    while i < b.len() {
        // 8 видимих ASCII поспіль (0x20–0x7E) — одним кроком
        if i + 8 <= b.len() {
            let w = u64::from_le_bytes(b[i..i + 8].try_into().unwrap());
            const LO: u64 = 0x0101_0101_0101_0101;
            const HI: u64 = 0x8080_8080_8080_8080;
            let lt20 = w.wrapping_sub(LO * 0x20) & !w & HI;
            let ge7f = ((w & !HI) + LO) | w; // старший біт: молодші 7 бітів = 0x7F (без переносу між байтами) або ≥ 0x80
            if (lt20 | (ge7f & HI)) == 0 {
                i += 8;
                continue;
            }
        }
        let x = b[i];
        if x < 0x80 {
            if (x < 0x20 || x == 0x7f) && !((x == b'\n' && nl) || (x == b'\t' && tab)) {
                if !allow.contains(x as char) {
                    return true;
                }
            }
            i += 1;
            continue;
        }
        let w = if x < 0xE0 { 2 } else if x < 0xF0 { 3 } else { 4 };
        if w == 2 && !LEAD2[(x & 0x1f) as usize] {
            i += 2;
            continue;
        }
        let c = text[i..].chars().next().unwrap();
        if invisible(c) && !allow.contains(c) {
            return true;
        }
        i += w;
    }
    false
}

/// Двобайтові UTF-8 (U+0080…U+07FF) за провідним байтом: чи є в цій сотні невидимі (C1, U+00AD, U+034F, U+061C…).
static LEAD2: [bool; 32] = {
    let mut t = [false; 32];
    let mut lead = 2;
    while lead < 32 {
        let mut cp = (lead as u32) << 6;
        let end = cp + 64;
        while cp < end {
            if INVISIBLE_BMP[(cp >> 6) as usize] >> (cp & 63) & 1 == 1 {
                t[lead] = true;
            }
            cp += 1;
        }
        lead += 1;
    }
    t
};

/// hidden(text, allow): невидимі символи тексту (крім allow), селектор вигляду після значка (So) — видимий.
pub fn hidden(text: &str, allow: &str) -> Vec<char> {
    if !any_invisible(text, allow) {
        return Vec::new();
    }
    let mut out = Vec::new();
    let mut prev: Option<char> = None;
    for c in text.chars() {
        if !allow.contains(c) && invisible(c) {
            let sel = (c == '\u{FE0E}' || c == '\u{FE0F}') && prev.map_or(false, |p| category(p) == "So");
            if !sel {
                out.push(c);
            }
        }
        prev = Some(c);
    }
    out
}

fn ucode(c: char) -> String {
    format!("⟨U+{:04X}⟩", c as u32)
}

/// visible(text): кожен невидимий символ (крім allow) — ⟨U+XXXX⟩; справжній ⟨ — теж кодом (bracket).
pub fn visible(text: &str, allow: &str, bracket: bool) -> String {
    let mut bad = hidden(text, allow);
    if bracket && text.contains('⟨') {
        bad.push('⟨');
    }
    if bad.is_empty() {
        return text.to_string();
    }
    bad.sort_unstable(); // множина, як set() еталона: k невидимих — не k порівнянь на кожен символ (суд 9: O(n·k))
    bad.dedup();
    let mut out = String::with_capacity(text.len() + 16);
    for c in text.chars() {
        if bad.binary_search(&c).is_ok() {
            out.push_str(&ucode(c));
        } else {
            out.push(c);
        }
    }
    out
}

/// safe(s): новий рядок і табуляція — ↵ ⇥, решта невидимого — ⟨U+XXXX⟩.
pub fn safe(s: &str) -> String {
    let mut bad = hidden(s, "");
    if bad.is_empty() {
        return s.to_string();
    }
    bad.sort_unstable();
    bad.dedup();
    let mut out = String::with_capacity(s.len() + 16);
    for c in s.chars() {
        if bad.binary_search(&c).is_ok() {
            match c {
                '\n' => out.push('↵'),
                '\t' => out.push('⇥'),
                _ => out.push_str(&ucode(c)),
            }
        } else {
            out.push(c);
        }
    }
    out
}

pub fn is_identifier(s: &str) -> bool {
    let mut it = s.chars();
    match it.next() {
        None => false,
        Some(c) => in_ranges(&ID_START, c as u32) && it.all(|c| in_ranges(&ID_CONT, c as u32)),
    }
}

pub fn isprintable(c: char) -> bool {
    in_ranges(&PRINTABLE, c as u32)
}

/// repr(str) Python.
pub fn py_repr(s: &str) -> String {
    let q = if s.contains('\'') && !s.contains('"') { '"' } else { '\'' };
    let mut out = String::new();
    out.push(q);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\t' => out.push_str("\\t"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            c if c == q => {
                out.push('\\');
                out.push(c);
            }
            c if (c as u32) < 0x20 || c as u32 == 0x7f => out.push_str(&format!("\\x{:02x}", c as u32)),
            c if (c as u32) < 0x7f => out.push(c),
            c if isprintable(c) => out.push(c),
            c if (c as u32) <= 0xff => out.push_str(&format!("\\x{:02x}", c as u32)),
            c if (c as u32) <= 0xffff => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push_str(&format!("\\U{:08x}", c as u32)),
        }
    }
    out.push(q);
    out
}
