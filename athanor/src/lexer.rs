//! Лексика — як nigredo.lex. Будь-яка помилка (чи символ, з яким Атанор не певен) — Back: програму розбирає еталон.
use crate::dec::Dec;
use crate::int::Int;
use crate::lang;
use crate::uni;
use std::rc::Rc;

pub type Pos = (u32, u32);

/// Причина віддати програму еталонові (до будь-якої дії).
#[derive(Debug)]
pub struct Back(pub String);

pub fn back<T>(why: impl Into<String>) -> Result<T, Back> {
    Err(Back(why.into()))
}

#[derive(Clone, Debug)]
pub enum Lit {
    None,
    Bool(bool),
    Int(Int),
    Dec(Rc<Dec>),
    Str(Rc<str>),
}

#[derive(Clone, Debug)]
pub enum Tok {
    Name(Rc<str>),
    Glyph(char),
    Num(Lit),
    Str(Rc<str>),
    Open(char),
    Close(char),
    Nl(i64),
    TOpen,
    TClose,
    TPart(Rc<str>),
    HOpen,
    HClose,
    Eof,
}

#[derive(Clone, Debug)]
pub struct Token {
    pub t: Tok,
    pub pos: Pos,
}

pub const STR_OPEN: char = '「';
pub const STR_CLOSE: char = '」';
pub const COMMENT: char = '※';
pub const SEP: char = '¦';
pub const NEG: char = '¯';
pub const TMPL_OPEN: char = '〔';
pub const TMPL_CLOSE: char = '〕';

pub fn is_glyph(c: char) -> bool {
    lang::GLYPHS.binary_search_by(|&(g, _)| g.cmp(&c)).is_ok() || matches!(c, '●' | '○' | '∅')
}

pub fn glyph_arity(c: char) -> i8 {
    lang::GLYPHS[lang::GLYPHS.binary_search_by(|&(g, _)| g.cmp(&c)).unwrap()].1
}

pub fn close_of(c: char) -> char {
    match c {
        '【' => '】',
        '『' => '』',
        _ => '》',
    }
}

fn is_open(c: char) -> bool {
    matches!(c, '【' | '『' | '《')
}

fn is_close(c: char) -> bool {
    matches!(c, '】' | '』' | '》')
}

pub fn is_name_start(c: char) -> bool {
    (uni::is_letter(c) && !(0x370..0x400).contains(&(c as u32))) || c == '_'
}

pub fn is_name_char(c: char) -> bool {
    is_name_start(c) || uni::category(c) == "Nd" || c == 'ʼ' || c == '\''
}

fn digit_script(c: char) -> Option<&'static str> {
    if c.is_ascii_digit() {
        Some("ASCII")
    } else if ('\u{FF10}'..='\u{FF19}').contains(&c) {
        Some("FULLWIDTH")
    } else {
        None
    }
}

pub fn lex(src: &str) -> Result<Vec<Token>, Back> {
    let s: Vec<char> = src.chars().collect();
    let n = s.len();
    let mut toks: Vec<Token> = Vec::new();
    let (mut i, mut line, mut col) = (0usize, 1u32, 1u32);
    macro_rules! adv {
        ($k:expr) => {
            for _ in 0..$k {
                if s[i] == '\n' {
                    line += 1;
                    col = 1;
                } else {
                    col += 1;
                }
                i += 1;
            }
        };
    }
    let mut modes: Vec<u8> = Vec::new(); // 1 — текст шаблону, 2 — дірка {вираз}
    while i < n {
        let ch = s[i];
        let pos = (line, col);
        if modes.last() == Some(&1) {
            let mut buf = String::new();
            loop {
                if i >= n {
                    return back("незакритий шаблон");
                }
                let c = s[i];
                if c == TMPL_CLOSE || c == '{' {
                    break;
                }
                if c == '\\' && i + 1 < n {
                    let e = s[i + 1];
                    match e {
                        'n' => buf.push('\n'),
                        't' => buf.push('\t'),
                        '\\' | '{' | '}' | TMPL_CLOSE => buf.push(e),
                        _ => {
                            buf.push('\\');
                            buf.push(e);
                        }
                    }
                    adv!(2);
                    continue;
                }
                if c == '\r' && i + 1 < n && s[i + 1] == '\n' {
                    adv!(1);
                    continue;
                }
                buf.push(c);
                adv!(1);
            }
            if !uni::hidden(&buf, "\n\t").is_empty() {
                return back("невидимий символ у шаблоні");
            }
            if !buf.is_empty() {
                toks.push(Token { t: Tok::TPart(buf.into()), pos });
            }
            let tpos = (line, col);
            if s[i] == TMPL_CLOSE {
                toks.push(Token { t: Tok::TClose, pos: tpos });
                modes.pop();
            } else {
                toks.push(Token { t: Tok::HOpen, pos: tpos });
                modes.push(2);
            }
            adv!(1);
            continue;
        }
        if modes.last() == Some(&2) && (ch == '}' || ch == '\n' || ch == SEP) {
            if ch != '}' {
                return back("вираз у {…} шаблону — в одному рядку");
            }
            toks.push(Token { t: Tok::HClose, pos });
            modes.pop();
            adv!(1);
            continue;
        }
        if ch == TMPL_OPEN {
            toks.push(Token { t: Tok::TOpen, pos });
            modes.push(1);
            adv!(1);
            continue;
        }
        if ch == '\n' {
            let mut j = i + 1;
            while j < n && (s[j] == ' ' || s[j] == '\t') {
                j += 1;
            }
            let indent = (j - i - 1) as i64;
            match toks.last_mut() {
                Some(Token { t: Tok::Nl(v), .. }) if *v >= 0 => *v = indent,
                _ => toks.push(Token { t: Tok::Nl(indent), pos }),
            }
            adv!(1);
        } else if ch == ' ' || ch == '\t' || (ch == '\r' && i + 1 < n && s[i + 1] == '\n') {
            adv!(1);
        } else if uni::isspace(ch) || uni::invisible(ch) {
            return back("невидимий символ поза рядком");
        } else if ch == COMMENT {
            let mut j = i;
            while j < n && s[j] != '\n' {
                j += 1;
            }
            let mut end = j;
            if end > i && s[end - 1] == '\r' {
                end -= 1;
            }
            let text: String = s[i..end].iter().collect();
            if !uni::hidden(&text, "\t").is_empty() {
                return back("невидимий символ у коментарі");
            }
            while i < n && s[i] != '\n' {
                adv!(1);
            }
        } else if ch == STR_OPEN {
            adv!(1);
            let mut buf = String::new();
            loop {
                if i >= n {
                    return back("незакритий рядок");
                }
                let c = s[i];
                if c == STR_CLOSE {
                    adv!(1);
                    break;
                }
                if c == '\\' && i + 1 < n {
                    let e = s[i + 1];
                    match e {
                        'n' => buf.push('\n'),
                        't' => buf.push('\t'),
                        STR_CLOSE | '\\' => buf.push(e),
                        _ => {
                            buf.push('\\');
                            buf.push(e);
                        }
                    }
                    adv!(2);
                    continue;
                }
                if c == '\r' && i + 1 < n && s[i + 1] == '\n' {
                    adv!(1);
                    continue;
                }
                buf.push(c);
                adv!(1);
            }
            if !uni::hidden(&buf, "\n\t").is_empty() {
                return back("невидимий символ у рядку коду");
            }
            toks.push(Token { t: Tok::Str(buf.into()), pos });
        } else if uni::decimal(ch).is_some() || (ch == NEG && i + 1 < n && uni::decimal(s[i + 1]).is_some()) {
            let neg = ch == NEG;
            if neg {
                adv!(1);
            }
            let mut num = String::new();
            let mut script: Option<&str> = None;
            let mut frac = false;
            loop {
                while i < n && uni::decimal(s[i]).is_some() {
                    let sc = match digit_script(s[i]) {
                        Some(x) => x,
                        None => return back("цифри іншого письма"),
                    };
                    if script.map_or(false, |x| x != sc) {
                        return back("змішані цифри");
                    }
                    script = Some(sc);
                    num.push(char::from_digit(uni::decimal(s[i]).unwrap(), 10).unwrap());
                    adv!(1);
                }
                if !frac && i + 1 < n && (s[i] == '.' || s[i] == '·') && uni::decimal(s[i + 1]).is_some() {
                    num.push('.');
                    frac = true;
                    adv!(1);
                    continue;
                }
                break;
            }
            let lit = if frac {
                let mut d = Dec::parse(&num).map_err(|_| Back("число".into()))?;
                if neg {
                    // -Decimal у контексті запуску (28 цифр, як у еталона), нуль — додатний
                    d = d.minus(&crate::dec::dec_ctx()).map_err(|_| Back("число".into()))?;
                }
                Lit::Dec(Rc::new(d))
            } else {
                let digits = num.trim_start_matches('0');
                Lit::Int(Int::from_dec(neg, if digits.is_empty() { "0" } else { digits }))
            };
            toks.push(Token { t: Tok::Num(lit), pos });
        } else if is_name_start(ch) {
            let mut buf = String::new();
            while i < n && (is_name_char(s[i]) || (s[i] == '.' && i + 1 < n && is_name_start(s[i + 1]))) {
                buf.push(s[i]);
                adv!(1);
            }
            // NFC: з безпечними символами нічого не змінює; інакше — еталон
            if buf.chars().any(uni::norm_unsafe) {
                return back("імʼя з символами, які змінює нормалізація");
            }
            let mut script: Option<&str> = None;
            for c in buf.chars() {
                if matches!(uni::category(c), "Lu" | "Ll" | "Lt" | "Lo") {
                    let sc = uni::letter_script(c);
                    if sc == "OTHER" || script.map_or(false, |x| x != sc) {
                        return back("письмо імені");
                    }
                    script = Some(sc);
                }
            }
            if buf.chars().any(|c| "ㅤᅟᅠﾠ⠀".contains(c)) {
                return back("заповнювач в імені");
            }
            if buf.chars().any(|c| uni::category(c) == "Nd" && !c.is_ascii_digit()) {
                return back("цифри іншого письма в імені");
            }
            toks.push(Token { t: Tok::Name(buf.into()), pos });
        } else if is_glyph(ch) {
            toks.push(Token { t: Tok::Glyph(ch), pos });
            adv!(1);
        } else if is_open(ch) {
            toks.push(Token { t: Tok::Open(ch), pos });
            adv!(1);
        } else if is_close(ch) {
            toks.push(Token { t: Tok::Close(ch), pos });
            adv!(1);
        } else if ch == SEP {
            toks.push(Token { t: Tok::Nl(-1), pos });
            adv!(1);
        } else {
            return back(format!("невідомий символ U+{:04X}", ch as u32));
        }
    }
    if !modes.is_empty() {
        return back("незакритий шаблон");
    }
    toks.push(Token { t: Tok::Eof, pos: (line, col) });
    Ok(toks)
}

/// check_twins: символи сумісності, «імʼя як число», двійники за скелетом.
pub fn check_twins(toks: &[Token]) -> Result<(), Back> {
    let mut seen: std::collections::HashMap<String, Rc<str>> = std::collections::HashMap::new();
    for t in toks {
        if let Tok::Name(v) = &t.t {
            // NFKC ≠ імʼя можливе лише з небезпечними символами — їх лексер уже віддав еталону
            if v.chars().all(|c| matches!(c, 'О' | 'O' | 'З' | 'Б') || uni::isdigit(c)) {
                return back("імʼя виглядає як число");
            }
            let sk = match uni::skeleton(v) {
                Some(sk) => sk,
                None => return back("скелет імені"),
            };
            match seen.get(&sk) {
                Some(prev) if **prev != **v => return back("двійники"),
                Some(_) => {}
                None => {
                    seen.insert(sk, v.clone());
                }
            }
        }
    }
    Ok(())
}
