//! JSON як у модулі json Python: dumps (ensure_ascii=False, розділювачі «, » і «: », sort_keys) і loads
//! (граматика й повідомлення про помилки — як у C-сканері _json, позиції — у символах).
use crate::pyf;
use std::borrow::Cow;

#[derive(Clone, Debug)]
pub enum J {
    Null,
    Bool(bool),
    Int(i64),
    Num(String), // уже готовий запис числа (велике ціле, десяткове)
    Float(f64),
    Str(String),
    Arr(Vec<J>),
    Obj(Vec<(String, J)>),
}

impl J {
    pub fn s(x: &str) -> J {
        J::Str(x.to_string())
    }
}

/// Скільки байтів дає екранування байта в рядку JSON (ensure_ascii=False): 1 — як є, 2 — \" \\ \n \r \t \b \f,
/// 6 — \u00XX.
const ESC_LEN: [u8; 256] = {
    let mut t = [1u8; 256];
    let mut i = 0;
    while i < 0x20 {
        t[i] = 6;
        i += 1;
    }
    t[b'"' as usize] = 2;
    t[b'\\' as usize] = 2;
    t[b'\n' as usize] = 2;
    t[b'\r' as usize] = 2;
    t[b'\t' as usize] = 2;
    t[8] = 2;
    t[12] = 2;
    t
};

/// Рядок у JSON (ensure_ascii=False): звичайні байти — по 8 одним записом до першого особливого, особливі —
/// екрануванням; місце дорезервовується, коли його лишається менше, ніж треба на найгірший крок.
pub fn escape_into(out: &mut String, s: &str) {
    let b = s.as_bytes();
    const LO: u64 = 0x0101_0101_0101_0101;
    const HI: u64 = 0x8080_8080_8080_8080;
    let zero = |x: u64| x.wrapping_sub(LO) & !x & HI;
    // SAFETY: пишемо в зарезервоване місце (перед кожним кроком його ≥ 16 байтів: 8 — звичайні, 6 — \u00XX)
    // лише цілі символи UTF-8 (байти поза ASCII копіюються як є, підряд) і ASCII-екранування; довжину ставимо
    // перед кожним дорезервуванням і наприкінці.
    unsafe {
        let v = out.as_mut_vec();
        v.reserve(b.len() + b.len() / 8 + 18);
        v.push(b'"');
        let mut d = v.as_mut_ptr().add(v.len());
        let mut end = v.as_mut_ptr().add(v.capacity());
        let mut i = 0;
        while i < b.len() {
            if (end as usize) - (d as usize) < 16 {
                let len = d as usize - v.as_ptr() as usize;
                v.set_len(len);
                v.reserve(b.len() - i + (b.len() - i) / 8 + 18);
                d = v.as_mut_ptr().add(v.len());
                end = v.as_mut_ptr().add(v.capacity());
            }
            if i + 8 <= b.len() {
                // найнижчий позначений байт масок — завжди справжній особливий (позики йдуть лише вгору)
                let w = u64::from_le_bytes(b[i..i + 8].try_into().unwrap());
                std::ptr::copy_nonoverlapping(w.to_le_bytes().as_ptr(), d, 8);
                let m = (w.wrapping_sub(LO * 0x20) & !w & HI) | zero(w ^ (LO * b'"' as u64)) | zero(w ^ (LO * b'\\' as u64));
                if m == 0 {
                    d = d.add(8);
                    i += 8;
                    continue;
                }
                let k = (m.trailing_zeros() / 8) as usize;
                d = d.add(k);
                i += k;
            }
            let c = b[i];
            i += 1;
            match ESC_LEN[c as usize] {
                1 => {
                    *d = c;
                    d = d.add(1);
                }
                2 => {
                    *d = b'\\';
                    *d.add(1) = match c {
                        b'"' => b'"',
                        b'\\' => b'\\',
                        b'\n' => b'n',
                        b'\r' => b'r',
                        b'\t' => b't',
                        8 => b'b',
                        _ => b'f',
                    };
                    d = d.add(2);
                }
                _ => {
                    const HEX: &[u8; 16] = b"0123456789abcdef";
                    for (k, x) in [b'\\', b'u', b'0', b'0', HEX[(c >> 4) as usize], HEX[(c & 15) as usize]].into_iter().enumerate() {
                        *d.add(k) = x;
                    }
                    d = d.add(6);
                }
            }
        }
        let len = d as usize - v.as_ptr() as usize;
        v.set_len(len);
        v.push(b'"');
    }
}

pub fn dumps(j: &J, sort_keys: bool) -> String {
    let mut out = String::new();
    write(&mut out, j, sort_keys);
    out
}

fn write(out: &mut String, j: &J, sort: bool) {
    match j {
        J::Null => out.push_str("null"),
        J::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        J::Int(i) => out.push_str(&i.to_string()),
        J::Num(s) => out.push_str(s),
        J::Float(f) => {
            if f.is_nan() {
                out.push_str("NaN")
            } else if f.is_infinite() {
                out.push_str(if *f > 0.0 { "Infinity" } else { "-Infinity" })
            } else {
                out.push_str(&pyf::repr(*f))
            }
        }
        J::Str(s) => escape_into(out, s),
        J::Arr(v) => {
            out.push('[');
            for (i, x) in v.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                write(out, x, sort);
            }
            out.push(']');
        }
        J::Obj(kv) => {
            out.push('{');
            if sort {
                let mut idx: Vec<usize> = (0..kv.len()).collect();
                idx.sort_by(|&a, &b| kv[a].0.cmp(&kv[b].0));
                for (n, &i) in idx.iter().enumerate() {
                    if n > 0 {
                        out.push_str(", ");
                    }
                    escape_into(out, &kv[i].0);
                    out.push_str(": ");
                    write(out, &kv[i].1, sort);
                }
            } else {
                for (n, (k, v)) in kv.iter().enumerate() {
                    if n > 0 {
                        out.push_str(", ");
                    }
                    escape_into(out, k);
                    out.push_str(": ");
                    write(out, v, sort);
                }
            }
            out.push('}');
        }
    }
}

/// Розібране значення: числа — сирим записом (ціле чи дробове вирішує той, хто будує); рядки без екранування —
/// шматками самого тексту (без копій).
#[derive(Debug)]
pub enum P<'a> {
    Null,
    Bool(bool),
    Int(&'a str),
    Float(&'a str),
    Str(Cow<'a, str>, bool), // bool — у рядку був самотній сурогат (\ud800): Python лишає його, wrap відкидає
    Arr(Vec<P<'a>>),
    Obj(Vec<(Cow<'a, str>, bool, P<'a>)>),
}

pub struct PErr {
    pub msg: String,
    pub pos: usize, // у символах
}

/// Помилка розбору: «повідомлення: line L column C (char P)» або сталі NaN/Infinity (як parse_constant).
pub enum LoadErr {
    Syntax(String),
    Constant(String),
    TooDeep,
    Ngr(String), // помилка мови під час розбору (порядок десяткового понад межу — як dec_ok у parse_float)
}

struct Parser<'a> {
    s: &'a str,
    b: &'a [u8],
    i: usize, // у байтах (помилки переводяться в символи лише при виведенні)
    depth: usize,
    dup: bool, // у якомусь словнику ключ повторився
}

const C_RECURSION: usize = 9_990; // межа рекурсії C-сканера Python (перевищення — RecursionError)

pub fn loads(s: &str) -> Result<P<'_>, LoadErr> {
    load_with(s, false)
}

/// Як loads, але повтор ключа — помилка (дозволи власника: «останній перемагає» мовчки стирав би схвалення; суд 9).
pub fn loads_unique(s: &str) -> Result<P<'_>, LoadErr> {
    load_with(s, true)
}

fn load_with(s: &str, unique: bool) -> Result<P<'_>, LoadErr> {
    // позиція помилки — у символах, як у Python: байтова позиція завжди на межі символу
    let fmt = |e: PErr| -> LoadErr {
        let pre: Vec<char> = s[..e.pos.min(s.len())].chars().collect();
        let pos = pre.len();
        let line = pre.iter().filter(|&&c| c == '\n').count() + 1;
        let col = match pre.iter().rposition(|&c| c == '\n') {
            Some(nl) => pos - nl,
            None => pos + 1,
        };
        LoadErr::Syntax(format!("{}: line {} column {} (char {})", e.msg, line, col, pos))
    };
    if s.starts_with('\u{feff}') {
        return Err(fmt(PErr { msg: "Unexpected UTF-8 BOM (decode using utf-8-sig)".into(), pos: 0 }));
    }
    let mut p = Parser { s, b: s.as_bytes(), i: 0, depth: 0, dup: false };
    p.ws();
    let start = p.i;
    let v = match p.value() {
        Ok(Some(v)) => v,
        Ok(None) => return Err(fmt(PErr { msg: "Expecting value".into(), pos: start })),
        Err(Inner::E(e)) => return Err(fmt(e)),
        Err(Inner::Const(c)) => return Err(LoadErr::Constant(c)),
        Err(Inner::Deep) => return Err(LoadErr::TooDeep),
        Err(Inner::Ngr(m)) => return Err(LoadErr::Ngr(m)),
    };
    p.ws();
    if p.i != p.b.len() {
        return Err(fmt(PErr { msg: "Extra data".into(), pos: p.i }));
    }
    if unique && p.dup {
        return Err(LoadErr::Syntax("ключ повторюється".into()));
    }
    Ok(v)
}

enum Inner {
    E(PErr),
    Const(String),
    Deep,
    Ngr(String),
}

fn err(msg: &str, pos: usize) -> Inner {
    Inner::E(PErr { msg: msg.into(), pos })
}

impl<'a> Parser<'a> {
    #[inline]
    fn ws(&mut self) {
        while self.i < self.b.len() && matches!(self.b[self.i], b' ' | b'\t' | b'\n' | b'\r') {
            self.i += 1;
        }
    }

    #[inline]
    fn peek(&self) -> Option<u8> {
        self.b.get(self.i).copied()
    }

    fn starts(&self, w: &str) -> bool {
        self.b[self.i..].starts_with(w.as_bytes())
    }

    /// Чи лишилося від байта at щонайменше n символів (умови C-сканера рахують символи).
    fn chars_from(&self, at: usize, n: usize) -> bool {
        at <= self.b.len() && self.s[at..].chars().take(n).count() == n
    }

    /// Значення з позиції self.i; Ok(None) — «Expecting value» (StopIteration у сканері).
    fn value(&mut self) -> Result<Option<P<'a>>, Inner> {
        let c = match self.peek() {
            None => return Ok(None),
            Some(c) => c,
        };
        match c {
            b'"' => {
                self.i += 1;
                let (t, sur) = self.string()?;
                Ok(Some(P::Str(t, sur)))
            }
            b'{' => {
                self.enter()?;
                self.i += 1;
                let r = self.object();
                self.depth -= 1;
                r.map(Some)
            }
            b'[' => {
                self.enter()?;
                self.i += 1;
                let r = self.array();
                self.depth -= 1;
                r.map(Some)
            }
            b'n' if self.starts("null") => {
                self.i += 4;
                Ok(Some(P::Null))
            }
            b't' if self.starts("true") => {
                self.i += 4;
                Ok(Some(P::Bool(true)))
            }
            b'f' if self.starts("false") => {
                self.i += 5;
                Ok(Some(P::Bool(false)))
            }
            b'N' if self.starts("NaN") => Err(Inner::Const("NaN".into())),
            b'I' if self.starts("Infinity") => Err(Inner::Const("Infinity".into())),
            b'-' if self.starts("-Infinity") => Err(Inner::Const("-Infinity".into())),
            b'-' | b'0'..=b'9' => self.number(),
            _ => Ok(None),
        }
    }

    fn enter(&mut self) -> Result<(), Inner> {
        self.depth += 1;
        if self.depth > C_RECURSION {
            return Err(Inner::Deep);
        }
        Ok(())
    }

    fn number(&mut self) -> Result<Option<P<'a>>, Inner> {
        let b = self.b;
        let digit = |k: usize| b.get(k).map_or(false, |d| d.is_ascii_digit());
        let start = self.i;
        let mut k = self.i;
        if b.get(k) == Some(&b'-') {
            k += 1;
        }
        match b.get(k) {
            Some(b'0') => k += 1,
            Some(d) if d.is_ascii_digit() => {
                while digit(k) {
                    k += 1;
                }
            }
            _ => return Ok(None),
        }
        let mut is_float = false;
        if b.get(k) == Some(&b'.') && digit(k + 1) {
            k += 2;
            while digit(k) {
                k += 1;
            }
            is_float = true;
        }
        if matches!(b.get(k), Some(b'e') | Some(b'E')) {
            let mut e = k + 1;
            if matches!(b.get(e), Some(b'+') | Some(b'-')) {
                e += 1;
            }
            if digit(e) {
                while digit(e) {
                    e += 1;
                }
                k = e;
                is_float = true;
            }
        }
        let s: &'a str = &self.s[start..k];
        self.i = k;
        if is_float {
            // parse_float = dec_ok(Decimal(t)): порядок понад межу — помилка мови одразу, під час розбору
            if let Ok(d) = crate::dec::Dec::parse(s) {
                if d.adjusted().abs() > crate::dec::DEC_EXP {
                    return Err(Inner::Ngr(format!("δ: порядок числа понад {} цифр", crate::dec::DEC_EXP)));
                }
            }
            return Ok(Some(P::Float(s)));
        }
        Ok(Some(P::Int(s)))
    }

    fn string(&mut self) -> Result<(Cow<'a, str>, bool), Inner> {
        let begin = self.i - 1;
        let b = self.b;
        let mut out = String::new();
        let mut plain = true; // поки без екранувань — шматок тексту
        let mut sur = false;
        loop {
            // звичайні символи — шматком (кінець шматка — ASCII-байт або кінець, тобто межа символу)
            let run = self.i;
            while self.i < b.len() && !matches!(b[self.i], b'"' | b'\\' | 0..=0x1f) {
                self.i += 1;
            }
            let c = match self.peek() {
                None => return Err(err("Unterminated string starting at", begin)),
                Some(c) => c,
            };
            if c == b'"' && plain {
                self.i += 1;
                return Ok((Cow::Borrowed(&self.s[run..self.i - 1]), sur));
            }
            out.push_str(&self.s[run..self.i]);
            plain = false;
            if c == b'"' {
                self.i += 1;
                return Ok((Cow::Owned(out), sur));
            }
            if c != b'\\' {
                return Err(err("Invalid control character at", self.i));
            }
            // зворотна коса
            let next = self.i + 1;
            let e = match b.get(next) {
                None => return Err(err("Unterminated string starting at", begin)),
                Some(&e) => e,
            };
            if e != b'u' {
                let r = match e {
                    b'"' => '"',
                    b'\\' => '\\',
                    b'/' => '/',
                    b'b' => '\u{8}',
                    b'f' => '\u{c}',
                    b'n' => '\n',
                    b'r' => '\r',
                    b't' => '\t',
                    _ => return Err(err("Invalid \\escape", next - 1)),
                };
                out.push(r);
                self.i = next + 1;
                continue;
            }
            let h = next + 1; // перша шістнадцяткова
            let end = h + 4;
            // C-сканер: end >= len (у символах) — та сама помилка й позиція, що й нешістнадцяткова цифра
            if end >= b.len() {
                return Err(err("Invalid \\uXXXX escape", h - 1));
            }
            let mut u = match hex4(&b[h..end]) {
                Some(u) => u,
                None => return Err(err("Invalid \\uXXXX escape", h - 1)),
            };
            let mut after = end;
            if (0xD800..=0xDBFF).contains(&u) && self.chars_from(end, 7) && b[end] == b'\\' && b[end + 1] == b'u' {
                let h2 = end + 2;
                let u2 = match hex4(&b[h2..h2 + 4]) {
                    Some(u2) => u2,
                    None => return Err(err("Invalid \\uXXXX escape", h2 - 1)),
                };
                if (0xDC00..=0xDFFF).contains(&u2) {
                    u = 0x10000 + (((u - 0xD800) << 10) | (u2 - 0xDC00));
                    after = h2 + 4;
                }
            }
            match char::from_u32(u) {
                Some(ch) => out.push(ch),
                None => {
                    sur = true;
                    out.push('\u{FFFD}');
                }
            }
            self.i = after;
        }
    }

    fn object(&mut self) -> Result<P<'a>, Inner> {
        let mut kv: Vec<(Cow<'a, str>, bool, P<'a>)> = Vec::new();
        // повтор ключа: значення — останнє, місце — першої появи (як dict); пошук — перебором, у великих — словником
        let mut index: Option<crate::value::FxMap<(String, bool), usize>> = None; // ключі — копії (лише ≥ 16)
        self.ws();
        if self.peek() == Some(b'}') {
            self.i += 1;
            return Ok(P::Obj(kv));
        }
        loop {
            if self.peek() != Some(b'"') {
                return Err(err("Expecting property name enclosed in double quotes", self.i));
            }
            self.i += 1;
            let (key, ksur) = self.string()?;
            self.ws();
            if self.peek() != Some(b':') {
                return Err(err("Expecting ':' delimiter", self.i));
            }
            self.i += 1;
            self.ws();
            let at = self.i;
            let v = match self.value()? {
                Some(v) => v,
                None => return Err(err("Expecting value", at)),
            };
            let found = match &index {
                Some(m) => m.get(&(key.to_string(), ksur)).copied(),
                None => kv.iter().position(|(k, s, _)| *k == key && *s == ksur),
            };
            match found {
                Some(p) => {
                    self.dup = true;
                    kv[p].2 = v
                }
                None => {
                    if let Some(m) = &mut index {
                        m.insert((key.to_string(), ksur), kv.len());
                    }
                    kv.push((key, ksur, v));
                    if index.is_none() && kv.len() >= 16 {
                        index = Some(kv.iter().enumerate().map(|(i, (k, s, _))| ((k.to_string(), *s), i)).collect());
                    }
                }
            }
            self.ws();
            match self.peek() {
                Some(b'}') => {
                    self.i += 1;
                    return Ok(P::Obj(kv));
                }
                Some(b',') => {
                    let comma = self.i;
                    self.i += 1;
                    self.ws();
                    if self.peek() == Some(b'}') {
                        return Err(err("Illegal trailing comma before end of object", comma));
                    }
                }
                _ => return Err(err("Expecting ',' delimiter", self.i)),
            }
        }
    }

    fn array(&mut self) -> Result<P<'a>, Inner> {
        let mut v = Vec::new();
        self.ws();
        if self.peek() == Some(b']') {
            self.i += 1;
            return Ok(P::Arr(v));
        }
        loop {
            let at = self.i;
            match self.value()? {
                Some(x) => v.push(x),
                None => return Err(err("Expecting value", at)),
            }
            self.ws();
            match self.peek() {
                Some(b']') => {
                    self.i += 1;
                    return Ok(P::Arr(v));
                }
                Some(b',') => {
                    let comma = self.i;
                    self.i += 1;
                    self.ws();
                    if self.peek() == Some(b']') {
                        return Err(err("Illegal trailing comma before end of array", comma));
                    }
                }
                _ => return Err(err("Expecting ',' delimiter", self.i)),
            }
        }
    }
}

fn hex4(cs: &[u8]) -> Option<u32> {
    let mut u = 0u32;
    for &d in cs {
        u = u << 4 | (d as char).to_digit(16)?;
    }
    Some(u)
}
