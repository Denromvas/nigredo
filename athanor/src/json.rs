//! JSON як у модулі json Python: dumps (ensure_ascii=False, розділювачі «, » і «: », sort_keys) і loads
//! (граматика й повідомлення про помилки — як у C-сканері _json, позиції — у символах).
use crate::pyf;

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

pub fn escape_into(out: &mut String, s: &str) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
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

/// Розібране значення: числа — сирим записом (ціле чи дробове вирішує той, хто будує).
#[derive(Debug)]
pub enum P {
    Null,
    Bool(bool),
    Int(String),
    Float(String),
    Str(String, bool), // bool — у рядку був самотній сурогат (\ud800): Python лишає його, wrap відкидає
    Arr(Vec<P>),
    Obj(Vec<(String, bool, P)>),
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
    c: Vec<char>,
    i: usize,
    depth: usize,
    _s: &'a str,
}

const C_RECURSION: usize = 9_990; // межа рекурсії C-сканера Python (перевищення — RecursionError)

pub fn loads(s: &str) -> Result<P, LoadErr> {
    let chars: Vec<char> = s.chars().collect();
    let fmt = |e: PErr, chars: &Vec<char>| -> LoadErr {
        let pos = e.pos;
        let line = chars[..pos.min(chars.len())].iter().filter(|&&c| c == '\n').count() + 1;
        let col = match chars[..pos.min(chars.len())].iter().rposition(|&c| c == '\n') {
            Some(nl) => pos - nl,
            None => pos + 1,
        };
        LoadErr::Syntax(format!("{}: line {} column {} (char {})", e.msg, line, col, pos))
    };
    if chars.first() == Some(&'\u{feff}') {
        return Err(fmt(PErr { msg: "Unexpected UTF-8 BOM (decode using utf-8-sig)".into(), pos: 0 }, &chars));
    }
    let mut p = Parser { c: chars, i: 0, depth: 0, _s: s };
    p.ws();
    let start = p.i;
    let v = match p.value(start) {
        Ok(Some(v)) => v,
        Ok(None) => return Err(fmt(PErr { msg: "Expecting value".into(), pos: start }, &p.c)),
        Err(Inner::E(e)) => return Err(fmt(e, &p.c)),
        Err(Inner::Const(c)) => return Err(LoadErr::Constant(c)),
        Err(Inner::Deep) => return Err(LoadErr::TooDeep),
        Err(Inner::Ngr(m)) => return Err(LoadErr::Ngr(m)),
    };
    p.ws();
    if p.i != p.c.len() {
        return Err(fmt(PErr { msg: "Extra data".into(), pos: p.i }, &p.c));
    }
    let _ = &p._s;
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
    fn ws(&mut self) {
        while self.i < self.c.len() && matches!(self.c[self.i], ' ' | '\t' | '\n' | '\r') {
            self.i += 1;
        }
    }

    fn peek(&self) -> Option<char> {
        self.c.get(self.i).copied()
    }

    fn starts(&self, w: &str) -> bool {
        let mut k = self.i;
        for ch in w.chars() {
            if self.c.get(k) != Some(&ch) {
                return false;
            }
            k += 1;
        }
        true
    }

    /// Значення з позиції self.i; Ok(None) — «Expecting value» (StopIteration у сканері).
    fn value(&mut self, _at: usize) -> Result<Option<P>, Inner> {
        let c = match self.peek() {
            None => return Ok(None),
            Some(c) => c,
        };
        match c {
            '"' => {
                self.i += 1;
                let (t, sur) = self.string()?;
                Ok(Some(P::Str(t, sur)))
            }
            '{' => {
                self.enter()?;
                self.i += 1;
                let r = self.object();
                self.depth -= 1;
                r.map(Some)
            }
            '[' => {
                self.enter()?;
                self.i += 1;
                let r = self.array();
                self.depth -= 1;
                r.map(Some)
            }
            'n' if self.starts("null") => {
                self.i += 4;
                Ok(Some(P::Null))
            }
            't' if self.starts("true") => {
                self.i += 4;
                Ok(Some(P::Bool(true)))
            }
            'f' if self.starts("false") => {
                self.i += 5;
                Ok(Some(P::Bool(false)))
            }
            'N' if self.starts("NaN") => Err(Inner::Const("NaN".into())),
            'I' if self.starts("Infinity") => Err(Inner::Const("Infinity".into())),
            '-' if self.starts("-Infinity") => Err(Inner::Const("-Infinity".into())),
            '-' | '0'..='9' => self.number(),
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

    fn number(&mut self) -> Result<Option<P>, Inner> {
        let start = self.i;
        let mut k = self.i;
        if self.c.get(k) == Some(&'-') {
            k += 1;
        }
        match self.c.get(k) {
            Some('0') => k += 1,
            Some(d) if d.is_ascii_digit() => {
                while self.c.get(k).map_or(false, |d| d.is_ascii_digit()) {
                    k += 1;
                }
            }
            _ => return Ok(None),
        }
        let mut is_float = false;
        if self.c.get(k) == Some(&'.') && self.c.get(k + 1).map_or(false, |d| d.is_ascii_digit()) {
            k += 2;
            while self.c.get(k).map_or(false, |d| d.is_ascii_digit()) {
                k += 1;
            }
            is_float = true;
        }
        if matches!(self.c.get(k), Some('e') | Some('E')) {
            let mut e = k + 1;
            if matches!(self.c.get(e), Some('+') | Some('-')) {
                e += 1;
            }
            if self.c.get(e).map_or(false, |d| d.is_ascii_digit()) {
                while self.c.get(e).map_or(false, |d| d.is_ascii_digit()) {
                    e += 1;
                }
                k = e;
                is_float = true;
            }
        }
        let s: String = self.c[start..k].iter().collect();
        self.i = k;
        if is_float {
            // parse_float = dec_ok(Decimal(t)): порядок понад межу — помилка мови одразу, під час розбору
            if let Ok(d) = crate::dec::Dec::parse(&s) {
                if d.adjusted().abs() > crate::dec::DEC_EXP {
                    return Err(Inner::Ngr(format!("δ: порядок числа понад {} цифр", crate::dec::DEC_EXP)));
                }
            }
            return Ok(Some(P::Float(s)));
        }
        Ok(Some(P::Int(s)))
    }

    fn string(&mut self) -> Result<(String, bool), Inner> {
        let begin = self.i - 1;
        let mut out = String::new();
        let mut sur = false;
        loop {
            let c = match self.peek() {
                None => return Err(err("Unterminated string starting at", begin)),
                Some(c) => c,
            };
            if c == '"' {
                self.i += 1;
                return Ok((out, sur));
            }
            if c != '\\' {
                if (c as u32) <= 0x1f {
                    return Err(err("Invalid control character at", self.i));
                }
                out.push(c);
                self.i += 1;
                continue;
            }
            // зворотна коса
            let next = self.i + 1;
            let e = match self.c.get(next) {
                None => return Err(err("Unterminated string starting at", begin)),
                Some(&e) => e,
            };
            if e != 'u' {
                let r = match e {
                    '"' => '"',
                    '\\' => '\\',
                    '/' => '/',
                    'b' => '\u{8}',
                    'f' => '\u{c}',
                    'n' => '\n',
                    'r' => '\r',
                    't' => '\t',
                    _ => return Err(err("Invalid \\escape", next - 1)),
                };
                out.push(r);
                self.i = next + 1;
                continue;
            }
            let h = next + 1; // перша шістнадцяткова
            let end = h + 4;
            if end >= self.c.len() {
                return Err(err("Invalid \\uXXXX escape", h - 1));
            }
            let mut u = match hex4(&self.c[h..end]) {
                Some(u) => u,
                None => return Err(err("Invalid \\uXXXX escape", h - 1)),
            };
            let mut after = end;
            if (0xD800..=0xDBFF).contains(&u) && end + 6 < self.c.len() && self.c[end] == '\\' && self.c[end + 1] == 'u' {
                let h2 = end + 2;
                let u2 = match hex4(&self.c[h2..h2 + 4]) {
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

    fn object(&mut self) -> Result<P, Inner> {
        let mut kv: Vec<(String, bool, P)> = Vec::new();
        let mut index: std::collections::HashMap<(String, bool), usize> = std::collections::HashMap::new();
        self.ws();
        if self.peek() == Some('}') {
            self.i += 1;
            return Ok(P::Obj(kv));
        }
        loop {
            if self.peek() != Some('"') {
                return Err(err("Expecting property name enclosed in double quotes", self.i));
            }
            self.i += 1;
            let (key, ksur) = self.string()?;
            self.ws();
            if self.peek() != Some(':') {
                return Err(err("Expecting ':' delimiter", self.i));
            }
            self.i += 1;
            self.ws();
            let at = self.i;
            let v = match self.value(at)? {
                Some(v) => v,
                None => return Err(err("Expecting value", at)),
            };
            match index.get(&(key.clone(), ksur)) {
                Some(&p) => kv[p].2 = v,
                None => {
                    index.insert((key.clone(), ksur), kv.len());
                    kv.push((key, ksur, v));
                }
            }
            self.ws();
            match self.peek() {
                Some('}') => {
                    self.i += 1;
                    return Ok(P::Obj(kv));
                }
                Some(',') => {
                    let comma = self.i;
                    self.i += 1;
                    self.ws();
                    if self.peek() == Some('}') {
                        return Err(err("Illegal trailing comma before end of object", comma));
                    }
                }
                _ => return Err(err("Expecting ',' delimiter", self.i)),
            }
        }
    }

    fn array(&mut self) -> Result<P, Inner> {
        let mut v = Vec::new();
        self.ws();
        if self.peek() == Some(']') {
            self.i += 1;
            return Ok(P::Arr(v));
        }
        loop {
            let at = self.i;
            match self.value(at)? {
                Some(x) => v.push(x),
                None => return Err(err("Expecting value", at)),
            }
            self.ws();
            match self.peek() {
                Some(']') => {
                    self.i += 1;
                    return Ok(P::Arr(v));
                }
                Some(',') => {
                    let comma = self.i;
                    self.i += 1;
                    self.ws();
                    if self.peek() == Some(']') {
                        return Err(err("Illegal trailing comma before end of array", comma));
                    }
                }
                _ => return Err(err("Expecting ',' delimiter", self.i)),
            }
        }
    }
}

fn hex4(cs: &[char]) -> Option<u32> {
    let mut u = 0u32;
    for &d in cs {
        u = u << 4 | d.to_digit(16)?;
    }
    Some(u)
}
