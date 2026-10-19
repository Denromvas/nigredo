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

pub fn glyph_twin(skel: &str) -> Option<&'static str> {
    GLYPH_TWIN.binary_search_by(|&(a, _)| a.cmp(skel)).ok().map(|i| GLYPH_TWIN[i].1)
}

pub fn invisible(c: char) -> bool {
    in_ranges(&INVISIBLE, c as u32)
}

pub fn isspace(c: char) -> bool {
    in_ranges(&ISSPACE, c as u32)
}

pub fn isalnum(c: char) -> bool {
    in_ranges(&ISALNUM, c as u32)
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
pub fn hidden(text: &str, allow: &str) -> Vec<char> {
    if !text.chars().any(|c| !allow.contains(c) && invisible(c)) {
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
    let mut out = String::with_capacity(text.len() + 16);
    for c in text.chars() {
        if bad.contains(&c) {
            out.push_str(&ucode(c));
        } else {
            out.push(c);
        }
    }
    out
}

/// safe(s): новий рядок і табуляція — ↵ ⇥, решта невидимого — ⟨U+XXXX⟩.
pub fn safe(s: &str) -> String {
    let bad = hidden(s, "");
    if bad.is_empty() {
        return s.to_string();
    }
    let mut out = String::with_capacity(s.len() + 16);
    for c in s.chars() {
        if bad.contains(&c) {
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
