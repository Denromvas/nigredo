//! Регулярні вирази — як nigredo.Rx: синтаксис і помилки — re._parser Python 3.13 (дослівний порт), виконання —
//! Pike VM без відкатів (те саме, що в еталоні: ті самі кроки, той самий пріоритет гілок).
use crate::uni;

const MAXREPEAT: u32 = u32::MAX; // _sre.MAXREPEAT: {n} з n ≥ нього — OverflowError, а сам він — «без межі»
const MAXGROUPS: usize = 1_073_741_823 / 2;
pub const RX_MAX_PROG: usize = 20_000;

const F_IGNORECASE: u32 = 2;
const F_LOCALE: u32 = 4;
const F_MULTILINE: u32 = 8;
const F_DOTALL: u32 = 16;
const F_UNICODE: u32 = 32;
const F_VERBOSE: u32 = 64;
const F_ASCII: u32 = 256;
const TYPE_FLAGS: u32 = F_ASCII | F_LOCALE | F_UNICODE;

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Cat {
    Digit,
    NotDigit,
    Space,
    NotSpace,
    Word,
    NotWord,
}

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum At {
    Beginning,
    BeginningString,
    End,
    EndString,
    Boundary,
    NonBoundary,
}

#[derive(Clone, PartialEq, Debug)]
pub enum SetItem {
    Negate,
    Literal(u32),
    Range(u32, u32),
    Category(Cat),
}

#[derive(Debug)]
pub enum Op {
    Literal(u32),
    NotLiteral(u32),
    Any,
    In(Vec<SetItem>),
    Sub(Option<usize>, u32, u32, Vec<Op>), // група, додані, зняті прапорці, тіло
    Branch(Vec<Vec<Op>>),
    Repeat(u8, u32, u32, Vec<Op>), // 0 — жадібне, 1 — ліниве, 2 — присвійне
    At(At),
    GroupRef(usize),
    GroupRefExists,
    Assert,
    AssertNot,
    Atomic,
    Failure,
}

impl Op {
    /// item[0] != prefix у _parse_sub: кортежі порівнюються за значенням; SubPattern — за тотожністю (різні завжди).
    fn same(&self, o: &Op) -> bool {
        match (self, o) {
            (Op::Literal(a), Op::Literal(b)) | (Op::NotLiteral(a), Op::NotLiteral(b)) => a == b,
            (Op::Any, Op::Any) => true,
            (Op::In(a), Op::In(b)) => a == b,
            (Op::At(a), Op::At(b)) => a == b,
            (Op::GroupRef(a), Op::GroupRef(b)) => a == b,
            (Op::Failure, Op::Failure) => true,
            _ => false,
        }
    }
}

/// re.error: повідомлення й позиція (у символах).
pub struct ReErr {
    pub msg: String,
    pub pos: Option<usize>,
}

pub enum RxErr {
    Re(ReErr),      // re.error → «хибний шаблон: …»
    Rx(String),     // RxError мови
}

struct Tok<'a> {
    s: &'a [char],
    index: usize,
    next: Option<String>,
}

type PR<T> = Result<T, RxErr>;

fn re_err<T>(msg: String, pos: usize) -> PR<T> {
    Err(RxErr::Re(ReErr { msg, pos: Some(pos) }))
}

impl<'a> Tok<'a> {
    fn new(s: &'a [char]) -> PR<Tok<'a>> {
        let mut t = Tok { s, index: 0, next: None };
        t.advance()?;
        Ok(t)
    }
    fn advance(&mut self) -> PR<()> {
        let mut index = self.index;
        if index >= self.s.len() {
            self.next = None;
            return Ok(());
        }
        let mut c = self.s[index].to_string();
        if c == "\\" {
            index += 1;
            if index >= self.s.len() {
                return re_err("bad escape (end of pattern)".into(), self.s.len() - 1);
            }
            c.push(self.s[index]);
        }
        self.index = index + 1;
        self.next = Some(c);
        Ok(())
    }
    fn is(&self, c: &str) -> bool {
        self.next.as_deref() == Some(c)
    }
    fn matches(&mut self, c: &str) -> PR<bool> {
        if self.is(c) {
            self.advance()?;
            return Ok(true);
        }
        Ok(false)
    }
    fn get(&mut self) -> PR<Option<String>> {
        let t = self.next.clone();
        self.advance()?;
        Ok(t)
    }
    fn next_in(&self, set: &str) -> bool {
        match &self.next {
            Some(n) => n.chars().count() == 1 && set.contains(n.as_str()),
            None => false,
        }
    }
    fn getwhile(&mut self, n: usize, set: &str) -> PR<String> {
        let mut r = String::new();
        for _ in 0..n {
            if !self.next_in(set) {
                break;
            }
            r.push_str(self.next.as_deref().unwrap());
            self.advance()?;
        }
        Ok(r)
    }
    fn getuntil(&mut self, term: &str, name: &str) -> PR<String> {
        let mut r = String::new();
        loop {
            let c = self.next.clone();
            self.advance()?;
            match c {
                None => {
                    if r.is_empty() {
                        return self.error(format!("missing {}", name), 0);
                    }
                    let n = r.chars().count();
                    return self.error(format!("missing {}, unterminated name", term), n);
                }
                Some(c) if c == term => {
                    if r.is_empty() {
                        return self.error(format!("missing {}", name), 1);
                    }
                    return Ok(r);
                }
                Some(c) => r.push_str(&c),
            }
        }
    }
    fn tell(&self) -> usize {
        self.index - self.next.as_ref().map_or(0, |n| n.chars().count())
    }
    fn seek(&mut self, i: usize) -> PR<()> {
        self.index = i;
        self.advance()
    }
    fn error<T>(&self, msg: String, offset: usize) -> PR<T> {
        re_err(msg, self.tell() - offset)
    }
    fn checkgroupname(&self, name: &str, offset: usize) -> PR<()> {
        if !uni::is_identifier(name) {
            return self.error(format!("bad character in group name {}", uni::py_repr(name)), name.chars().count() + offset);
        }
        Ok(())
    }
}

struct State {
    flags: u32,
    groupdict: Vec<(String, usize)>,
    closed: Vec<bool>, // groupwidths[gid] is not None
    lookbehind: Option<usize>,
    grouprefpos: Vec<(usize, usize)>,
}

impl State {
    fn groups(&self) -> usize {
        self.closed.len()
    }
    fn checkgroup(&self, gid: usize) -> bool {
        gid < self.groups() && self.closed[gid]
    }
    fn checklookbehind(&self, gid: usize, src: &Tok) -> PR<()> {
        if let Some(lb) = self.lookbehind {
            if !self.checkgroup(gid) {
                return src.error("cannot refer to an open group".into(), 0);
            }
            if gid >= lb {
                return src.error("cannot refer to group defined in the same lookbehind subpattern".into(), 0);
            }
        }
        Ok(())
    }
}

const DIGITS: &str = "0123456789";
const OCTDIGITS: &str = "01234567";
const HEXDIGITS: &str = "0123456789abcdefABCDEF";
const SPECIAL: &str = ".\\[{()*+?^$|";
const REPEAT_CHARS: &str = "*+?{";
const WHITESPACE: &str = " \t\n\r\u{b}\u{c}";

fn is_ascii_letter(c: &str) -> bool {
    c.len() == 1 && c.as_bytes()[0].is_ascii_alphabetic()
}

fn escapes(e: &str) -> Option<u32> {
    Some(match e {
        "\\a" => 7,
        "\\b" => 8,
        "\\f" => 12,
        "\\n" => 10,
        "\\r" => 13,
        "\\t" => 9,
        "\\v" => 11,
        "\\\\" => 92,
        _ => return None,
    })
}

enum Code {
    Op(Op),
}

fn categories(e: &str) -> Option<Op> {
    Some(match e {
        "\\A" => Op::At(At::BeginningString),
        "\\b" => Op::At(At::Boundary),
        "\\B" => Op::At(At::NonBoundary),
        "\\d" => Op::In(vec![SetItem::Category(Cat::Digit)]),
        "\\D" => Op::In(vec![SetItem::Category(Cat::NotDigit)]),
        "\\s" => Op::In(vec![SetItem::Category(Cat::Space)]),
        "\\S" => Op::In(vec![SetItem::Category(Cat::NotSpace)]),
        "\\w" => Op::In(vec![SetItem::Category(Cat::Word)]),
        "\\W" => Op::In(vec![SetItem::Category(Cat::NotWord)]),
        "\\Z" => Op::At(At::EndString),
        _ => return None,
    })
}

fn hexval(s: &str) -> u32 {
    u32::from_str_radix(s, 16).unwrap()
}

/// Спільне для \x \u \U \N (у класі й поза ним).
fn hex_escape(src: &mut Tok, escape: &mut String, c: char) -> PR<Option<u32>> {
    let (n, total) = match c {
        'x' => (2, 4),
        'u' => (4, 6),
        'U' => (8, 10),
        _ => return Ok(None),
    };
    let more = src.getwhile(n, HEXDIGITS)?;
    escape.push_str(&more);
    if escape.chars().count() != total {
        let l = escape.chars().count();
        return src.error(format!("incomplete escape {}", escape), l);
    }
    let v = hexval(&escape[2..]);
    if c == 'U' && char::from_u32(v).is_none() && !(0xD800..=0xDFFF).contains(&v) {
        // chr(c) — ValueError → «bad escape»
        let l = escape.chars().count();
        return src.error(format!("bad escape {}", escape), l);
    }
    Ok(Some(v))
}

fn named_escape(src: &mut Tok) -> PR<u32> {
    if !src.matches("{")? {
        return src.error("missing {".into(), 0);
    }
    let name = src.getuntil("}", "character name")?;
    // базу назв Unicode Атанор не містить: лише кілька поширених
    let v = match name.to_uppercase().as_str() {
        "SPACE" => 0x20,
        "NO-BREAK SPACE" => 0xA0,
        "EM DASH" => 0x2014,
        "EN DASH" => 0x2013,
        "HORIZONTAL ELLIPSIS" => 0x2026,
        _ => {
            let l = name.chars().count() + 4;
            return src.error(format!("undefined character name {}", uni::py_repr(&name)), l);
        }
    };
    Ok(v)
}

fn class_escape(src: &mut Tok, escape: &str) -> PR<Code> {
    if let Some(v) = escapes(escape) {
        return Ok(Code::Op(Op::Literal(v)));
    }
    if let Some(op) = categories(escape) {
        if let Op::In(_) = op {
            return Ok(Code::Op(op));
        }
    }
    let mut escape = escape.to_string();
    let c = escape.chars().nth(1).unwrap();
    if let Some(v) = hex_escape(src, &mut escape, c)? {
        return Ok(Code::Op(Op::Literal(v)));
    }
    if c == 'N' {
        return Ok(Code::Op(Op::Literal(named_escape(src)?)));
    }
    if OCTDIGITS.contains(c) {
        let more = src.getwhile(2, OCTDIGITS)?;
        escape.push_str(&more);
        let v = u32::from_str_radix(&escape[1..], 8).unwrap();
        if v > 0o377 {
            let l = escape.chars().count();
            return src.error(format!("octal escape value {} outside of range 0-0o377", escape), l);
        }
        return Ok(Code::Op(Op::Literal(v)));
    }
    if DIGITS.contains(c) {
        let l = escape.chars().count();
        return src.error(format!("bad escape {}", escape), l);
    }
    if escape.chars().count() == 2 {
        if c.is_ascii_alphabetic() {
            return src.error(format!("bad escape {}", escape), 2);
        }
        return Ok(Code::Op(Op::Literal(c as u32)));
    }
    let l = escape.chars().count();
    src.error(format!("bad escape {}", escape), l)
}

fn escape_op(src: &mut Tok, escape: &str, st: &State) -> PR<Op> {
    if let Some(op) = categories(escape) {
        return Ok(op);
    }
    if let Some(v) = escapes(escape) {
        return Ok(Op::Literal(v));
    }
    let mut escape = escape.to_string();
    let c = escape.chars().nth(1).unwrap();
    if let Some(v) = hex_escape(src, &mut escape, c)? {
        return Ok(Op::Literal(v));
    }
    if c == 'N' {
        return Ok(Op::Literal(named_escape(src)?));
    }
    if c == '0' {
        let more = src.getwhile(2, OCTDIGITS)?;
        escape.push_str(&more);
        return Ok(Op::Literal(u32::from_str_radix(&escape[1..], 8).unwrap()));
    }
    if DIGITS.contains(c) {
        if src.next_in(DIGITS) {
            let n = src.get()?.unwrap();
            escape.push_str(&n);
            let e: Vec<char> = escape.chars().collect();
            if OCTDIGITS.contains(e[1]) && OCTDIGITS.contains(e[2]) && src.next_in(OCTDIGITS) {
                let n = src.get()?.unwrap();
                escape.push_str(&n);
                let v = u32::from_str_radix(&escape[1..], 8).unwrap();
                if v > 0o377 {
                    let l = escape.chars().count();
                    return src.error(format!("octal escape value {} outside of range 0-0o377", escape), l);
                }
                return Ok(Op::Literal(v));
            }
        }
        let group: usize = escape[1..].parse().unwrap();
        if group < st.groups() {
            if !st.checkgroup(group) {
                let l = escape.chars().count();
                return src.error("cannot refer to an open group".into(), l);
            }
            st.checklookbehind(group, src)?;
            return Ok(Op::GroupRef(group));
        }
        let l = escape.chars().count() - 1;
        return src.error(format!("invalid group reference {}", group), l);
    }
    if escape.chars().count() == 2 {
        if c.is_ascii_alphabetic() {
            return src.error(format!("bad escape {}", escape), 2);
        }
        return Ok(Op::Literal(c as u32));
    }
    let l = escape.chars().count();
    src.error(format!("bad escape {}", escape), l)
}

fn uniq(items: Vec<SetItem>) -> Vec<SetItem> {
    let mut out: Vec<SetItem> = Vec::new();
    for x in items {
        if !out.contains(&x) {
            out.push(x);
        }
    }
    out
}

fn parse_sub(src: &mut Tok, st: &mut State, mut verbose: bool, nested: usize) -> PR<Vec<Op>> {
    let mut items: Vec<Vec<Op>> = Vec::new();
    loop {
        let first = nested == 0 && items.is_empty();
        items.push(parse(src, st, verbose, nested + 1, first)?);
        if !src.matches("|")? {
            break;
        }
        if nested == 0 {
            verbose = st.flags & F_VERBOSE != 0;
        }
    }
    if items.len() == 1 {
        return Ok(items.pop().unwrap());
    }
    let mut sub: Vec<Op> = Vec::new();
    // спільний початок гілок — перед розгалуженням
    loop {
        let mut ok = true;
        for it in &items {
            if it.is_empty() {
                ok = false;
                break;
            }
            if !it[0].same(&items[0][0]) {
                ok = false;
                break;
            }
        }
        if !ok {
            break;
        }
        let mut prefix = None;
        for it in items.iter_mut() {
            let x = it.remove(0);
            if prefix.is_none() {
                prefix = Some(x);
            }
        }
        sub.push(prefix.unwrap());
    }
    // гілки з одного символу чи класу — клас
    let mut set: Vec<SetItem> = Vec::new();
    let mut all = true;
    for it in &items {
        if it.len() != 1 {
            all = false;
            break;
        }
        match &it[0] {
            Op::Literal(v) => set.push(SetItem::Literal(*v)),
            Op::In(av) if av.first() != Some(&SetItem::Negate) => set.extend(av.iter().cloned()),
            _ => {
                all = false;
                break;
            }
        }
    }
    if all {
        sub.push(Op::In(uniq(set)));
        return Ok(sub);
    }
    sub.push(Op::Branch(items));
    Ok(sub)
}

fn parse(src: &mut Tok, st: &mut State, mut verbose: bool, nested: usize, first: bool) -> PR<Vec<Op>> {
    let mut sp: Vec<Op> = Vec::new();
    loop {
        let this = match src.next.clone() {
            None => break,
            Some(t) => t,
        };
        if this == "|" || this == ")" {
            break;
        }
        src.advance()?;
        if verbose {
            if this.chars().count() == 1 && WHITESPACE.contains(this.as_str()) {
                continue;
            }
            if this == "#" {
                loop {
                    let t = src.get()?;
                    if t.is_none() || t.as_deref() == Some("\n") {
                        break;
                    }
                }
                continue;
            }
        }
        if this.starts_with('\\') {
            let op = escape_op(src, &this, st)?;
            sp.push(op);
        } else if !SPECIAL.contains(this.as_str()) {
            sp.push(Op::Literal(this.chars().next().unwrap() as u32));
        } else if this == "[" {
            let here = src.tell() - 1;
            let mut set: Vec<SetItem> = Vec::new();
            let negate = src.matches("^")?;
            loop {
                let this = match src.get()? {
                    None => {
                        let off = src.tell() - here;
                        return src.error("unterminated character set".into(), off);
                    }
                    Some(t) => t,
                };
                if this == "]" && !set.is_empty() {
                    break;
                }
                let code1: Op = if this.starts_with('\\') {
                    let Code::Op(o) = class_escape(src, &this)?;
                    o
                } else {
                    Op::Literal(this.chars().next().unwrap() as u32)
                };
                if src.matches("-")? {
                    let that = match src.get()? {
                        None => {
                            let off = src.tell() - here;
                            return src.error("unterminated character set".into(), off);
                        }
                        Some(t) => t,
                    };
                    if that == "]" {
                        set.push(set_item(code1));
                        set.push(SetItem::Literal('-' as u32));
                        break;
                    }
                    let code2: Op = if that.starts_with('\\') {
                        let Code::Op(o) = class_escape(src, &that)?;
                        o
                    } else {
                        Op::Literal(that.chars().next().unwrap() as u32)
                    };
                    let (lo, hi) = match (&code1, &code2) {
                        (Op::Literal(a), Op::Literal(b)) => (*a, *b),
                        _ => {
                            let off = this.chars().count() + 1 + that.chars().count();
                            return src.error(format!("bad character range {}-{}", this, that), off);
                        }
                    };
                    if hi < lo {
                        let off = this.chars().count() + 1 + that.chars().count();
                        return src.error(format!("bad character range {}-{}", this, that), off);
                    }
                    set.push(SetItem::Range(lo, hi));
                } else {
                    set.push(set_item(code1));
                }
            }
            let mut set = uniq(set);
            if set.len() == 1 {
                if let SetItem::Literal(v) = set[0] {
                    sp.push(if negate { Op::NotLiteral(v) } else { Op::Literal(v) });
                    continue;
                }
            }
            if negate {
                set.insert(0, SetItem::Negate);
            }
            sp.push(Op::In(set));
        } else if REPEAT_CHARS.contains(this.as_str()) {
            let here = src.tell();
            let (mut min, mut max) = (0u32, MAXREPEAT);
            match this.as_str() {
                "?" => max = 1,
                "*" => {}
                "+" => min = 1,
                _ => {
                    // «{»
                    if src.is("}") {
                        sp.push(Op::Literal('{' as u32));
                        continue;
                    }
                    let (mut lo, mut hi) = (String::new(), String::new());
                    while src.next_in(DIGITS) {
                        lo.push_str(&src.get()?.unwrap());
                    }
                    if src.matches(",")? {
                        while src.next_in(DIGITS) {
                            hi.push_str(&src.get()?.unwrap());
                        }
                    } else {
                        hi = lo.clone();
                    }
                    if !src.matches("}")? {
                        sp.push(Op::Literal('{' as u32));
                        src.seek(here)?;
                        continue;
                    }
                    let big = |s: &str| -> bool { s.trim_start_matches('0').len() > 10 || s.parse::<u64>().map_or(true, |v| v >= MAXREPEAT as u64) };
                    if !lo.is_empty() {
                        if big(&lo) {
                            return Err(RxErr::Re(ReErr { msg: "the repetition number is too large".into(), pos: None }));
                        }
                        min = lo.parse().unwrap();
                    }
                    if !hi.is_empty() {
                        if big(&hi) {
                            return Err(RxErr::Re(ReErr { msg: "the repetition number is too large".into(), pos: None }));
                        }
                        max = hi.parse().unwrap();
                        if max < min {
                            let off = src.tell() - here;
                            return src.error("min repeat greater than max repeat".into(), off);
                        }
                    }
                }
            }
            let off = src.tell() - here + this.chars().count();
            let last = match sp.last() {
                None => return src.error("nothing to repeat".into(), off),
                Some(Op::At(_)) => return src.error("nothing to repeat".into(), off),
                Some(Op::Repeat(..)) => return src.error("multiple repeat".into(), off),
                Some(_) => sp.pop().unwrap(),
            };
            let item = match last {
                Op::Sub(None, 0, 0, p) => p,
                x => vec![x],
            };
            let kind = if src.matches("?")? {
                1
            } else if src.matches("+")? {
                2
            } else {
                0
            };
            sp.push(Op::Repeat(kind, min, max, item));
        } else if this == "." {
            sp.push(Op::Any);
        } else if this == "(" {
            let start = src.tell() - 1;
            let mut capture = true;
            let mut name: Option<String> = None;
            let (mut add, mut del) = (0u32, 0u32);
            let mut atomic = false;
            if src.matches("?")? {
                let ch = match src.get()? {
                    None => return src.error("unexpected end of pattern".into(), 0),
                    Some(c) => c,
                };
                if ch == "P" {
                    if src.matches("<")? {
                        let n = src.getuntil(">", "group name")?;
                        src.checkgroupname(&n, 1)?;
                        name = Some(n);
                    } else if src.matches("=")? {
                        let n = src.getuntil(")", "group name")?;
                        src.checkgroupname(&n, 1)?;
                        let off = n.chars().count() + 1;
                        let gid = match st.groupdict.iter().find(|(k, _)| *k == n) {
                            Some((_, g)) => *g,
                            None => return src.error(format!("unknown group name {}", uni::py_repr(&n)), off),
                        };
                        if !st.checkgroup(gid) {
                            return src.error("cannot refer to an open group".into(), off);
                        }
                        st.checklookbehind(gid, src)?;
                        sp.push(Op::GroupRef(gid));
                        continue;
                    } else {
                        let c2 = match src.get()? {
                            None => return src.error("unexpected end of pattern".into(), 0),
                            Some(c) => c,
                        };
                        let off = c2.chars().count() + 2;
                        return src.error(format!("unknown extension ?P{}", c2), off);
                    }
                } else if ch == ":" {
                    capture = false;
                } else if ch == "#" {
                    loop {
                        if src.next.is_none() {
                            let off = src.tell() - start;
                            return src.error("missing ), unterminated comment".into(), off);
                        }
                        if src.get()?.as_deref() == Some(")") {
                            break;
                        }
                    }
                    continue;
                } else if ch == "=" || ch == "!" || ch == "<" {
                    let mut ch = ch;
                    let mut dir = 1;
                    let mut lbg_was_none = false;
                    if ch == "<" {
                        ch = match src.get()? {
                            None => return src.error("unexpected end of pattern".into(), 0),
                            Some(c) => c,
                        };
                        if ch != "=" && ch != "!" {
                            let off = ch.chars().count() + 2;
                            return src.error(format!("unknown extension ?<{}", ch), off);
                        }
                        dir = -1;
                        lbg_was_none = st.lookbehind.is_none();
                        if lbg_was_none {
                            st.lookbehind = Some(st.groups());
                        }
                    }
                    let p = parse_sub(src, st, verbose, nested + 1)?;
                    if dir < 0 && lbg_was_none {
                        st.lookbehind = None;
                    }
                    if !src.matches(")")? {
                        let off = src.tell() - start;
                        return src.error("missing ), unterminated subpattern".into(), off);
                    }
                    if ch == "=" {
                        sp.push(Op::Assert);
                    } else if !p.is_empty() {
                        sp.push(Op::AssertNot);
                    } else {
                        sp.push(Op::Failure);
                    }
                    continue;
                } else if ch == "(" {
                    let condname = src.getuntil(")", "group name")?;
                    let isdec = !condname.is_empty() && condname.bytes().all(|b| b.is_ascii_digit());
                    let condgroup;
                    if !isdec {
                        src.checkgroupname(&condname, 1)?;
                        let off = condname.chars().count() + 1;
                        condgroup = match st.groupdict.iter().find(|(k, _)| *k == condname) {
                            Some((_, g)) => *g,
                            None => return src.error(format!("unknown group name {}", uni::py_repr(&condname)), off),
                        };
                    } else {
                        let off = condname.chars().count() + 1;
                        let v: u64 = condname.trim_start_matches('0').parse().unwrap_or(if condname.trim_start_matches('0').is_empty() { 0 } else { u64::MAX });
                        if v == 0 {
                            return src.error("bad group number".into(), off);
                        }
                        if v >= MAXGROUPS as u64 {
                            return src.error(format!("invalid group reference {}", condname.trim_start_matches('0')), off);
                        }
                        condgroup = v as usize;
                        if !st.grouprefpos.iter().any(|(g, _)| *g == condgroup) {
                            let at = src.tell() - condname.chars().count() - 1;
                            st.grouprefpos.push((condgroup, at));
                        }
                    }
                    st.checklookbehind(condgroup, src)?;
                    let _yes = parse(src, st, verbose, nested + 1, false)?;
                    if src.matches("|")? {
                        let _no = parse(src, st, verbose, nested + 1, false)?;
                        if src.is("|") {
                            return src.error("conditional backref with more than two branches".into(), 0);
                        }
                    }
                    if !src.matches(")")? {
                        let off = src.tell() - start;
                        return src.error("missing ), unterminated subpattern".into(), off);
                    }
                    sp.push(Op::GroupRefExists);
                    continue;
                } else if ch == ">" {
                    capture = false;
                    atomic = true;
                } else if "iLmsxau".contains(ch.as_str()) && ch.chars().count() == 1 || ch == "-" {
                    match parse_flags(src, st, &ch)? {
                        None => {
                            if !first || !sp.is_empty() {
                                let off = src.tell() - start;
                                return src.error("global flags not at the start of the expression".into(), off);
                            }
                            verbose = st.flags & F_VERBOSE != 0;
                            continue;
                        }
                        Some((a, d)) => {
                            add = a;
                            del = d;
                            capture = false;
                        }
                    }
                } else {
                    let off = ch.chars().count() + 1;
                    return src.error(format!("unknown extension ?{}", ch), off);
                }
            }
            let group = if capture {
                let gid = st.groups();
                st.closed.push(false);
                if st.groups() > MAXGROUPS {
                    let off = name.as_ref().map_or(0, |n| n.chars().count()) + 1;
                    return src.error("too many groups".into(), off);
                }
                if let Some(n) = &name {
                    if let Some((_, og)) = st.groupdict.iter().find(|(k, _)| k == n) {
                        let off = n.chars().count() + 1;
                        let og = *og;
                        return src.error(
                            format!("redefinition of group name {} as group {}; was group {}", uni::py_repr(n), gid, og),
                            off,
                        );
                    }
                    st.groupdict.push((n.clone(), gid));
                }
                Some(gid)
            } else {
                None
            };
            let sub_verbose = (verbose || add & F_VERBOSE != 0) && del & F_VERBOSE == 0;
            let p = parse_sub(src, st, sub_verbose, nested + 1)?;
            if !src.matches(")")? {
                let off = src.tell() - start;
                return src.error("missing ), unterminated subpattern".into(), off);
            }
            if let Some(g) = group {
                st.closed[g] = true;
            }
            if atomic {
                sp.push(Op::Atomic);
            } else {
                sp.push(Op::Sub(group, add, del, p));
            }
        } else if this == "^" {
            sp.push(Op::At(At::Beginning));
        } else if this == "$" {
            sp.push(Op::At(At::End));
        }
    }
    // розгорнути незахоплювальні групи без прапорців
    let mut out = Vec::with_capacity(sp.len());
    for op in sp {
        match op {
            Op::Sub(None, 0, 0, p) => out.extend(p),
            x => out.push(x),
        }
    }
    Ok(out)
}

fn set_item(op: Op) -> SetItem {
    match op {
        Op::Literal(v) => SetItem::Literal(v),
        Op::In(mut v) => v.remove(0),
        _ => unreachable!(),
    }
}

fn flag_of(c: &str) -> u32 {
    match c {
        "i" => F_IGNORECASE,
        "L" => F_LOCALE,
        "m" => F_MULTILINE,
        "s" => F_DOTALL,
        "x" => F_VERBOSE,
        "a" => F_ASCII,
        "u" => F_UNICODE,
        _ => 0,
    }
}

fn is_flag(c: &str) -> bool {
    c.chars().count() == 1 && "iLmsxau".contains(c)
}

fn isalpha(c: &str) -> bool {
    !c.is_empty() && c.chars().all(|x| uni::is_letter(x))
}

fn parse_flags(src: &mut Tok, st: &mut State, ch: &str) -> PR<Option<(u32, u32)>> {
    let (mut add, mut del) = (0u32, 0u32);
    let mut ch = ch.to_string();
    if ch != "-" {
        loop {
            let flag = flag_of(&ch);
            if ch == "L" {
                return src.error("bad inline flags: cannot use 'L' flag with a str pattern".into(), 0);
            }
            add |= flag;
            if flag & TYPE_FLAGS != 0 && add & TYPE_FLAGS != flag {
                return src.error("bad inline flags: flags 'a', 'u' and 'L' are incompatible".into(), 0);
            }
            ch = match src.get()? {
                None => return src.error("missing -, : or )".into(), 0),
                Some(c) => c,
            };
            if ch == ")" || ch == "-" || ch == ":" {
                break;
            }
            if !is_flag(&ch) {
                let msg = if isalpha(&ch) { "unknown flag" } else { "missing -, : or )" };
                let l = ch.chars().count();
                return src.error(msg.into(), l);
            }
        }
    }
    if ch == ")" {
        st.flags |= add;
        return Ok(None);
    }
    if ch == "-" {
        ch = match src.get()? {
            None => return src.error("missing flag".into(), 0),
            Some(c) => c,
        };
        if !is_flag(&ch) {
            let msg = if isalpha(&ch) { "unknown flag" } else { "missing flag" };
            let l = ch.chars().count();
            return src.error(msg.into(), l);
        }
        loop {
            let flag = flag_of(&ch);
            if flag & TYPE_FLAGS != 0 {
                return src.error("bad inline flags: cannot turn off flags 'a', 'u' and 'L'".into(), 0);
            }
            del |= flag;
            ch = match src.get()? {
                None => return src.error("missing :".into(), 0),
                Some(c) => c,
            };
            if ch == ":" {
                break;
            }
            if !is_flag(&ch) {
                let msg = if isalpha(&ch) { "unknown flag" } else { "missing :" };
                let l = ch.chars().count();
                return src.error(msg.into(), l);
            }
        }
    }
    if add & del != 0 {
        return src.error("bad inline flags: flag turned on and off".into(), 1);
    }
    Ok(Some((add, del)))
}

/// re._parser.parse(pat): дерево, прапорці, кількість груп, назви груп.
fn parse_pattern(pat: &[char]) -> PR<(Vec<Op>, u32, usize, Vec<(String, usize)>)> {
    let mut src = Tok::new(pat)?;
    let mut st = State { flags: 0, groupdict: Vec::new(), closed: vec![false], lookbehind: None, grouprefpos: Vec::new() };
    let p = parse_sub(&mut src, &mut st, false, 0)?;
    if st.flags & F_ASCII == 0 {
        st.flags |= F_UNICODE;
    } else if st.flags & F_UNICODE != 0 {
        return Err(RxErr::Re(ReErr { msg: "ASCII and UNICODE flags are incompatible".into(), pos: None }));
    }
    if src.next.is_some() {
        return src.error("unbalanced parenthesis".into(), 0);
    }
    for (g, at) in &st.grouprefpos {
        if *g >= st.groups() {
            return re_err(format!("invalid group reference {}", g), *at);
        }
    }
    let ng = st.groups();
    Ok((p, st.flags, ng, st.groupdict))
}

// ---------------------------------------------------------------- компіляція (як nigredo.Rx)

/// Предикат одного символу — як скомпільований re CPython 3.13 (_compiler._compile, _optimize_charset).
#[derive(Clone)]
enum Pred {
    Eq { c: char, neg: bool },                           // символ як є (без (?i) чи без регістру)
    Fold { cs: Vec<char>, alow: bool, neg: bool },       // (?i): мала літера символу — у cs (з _EXTRA_CASES)
    Any { dotall: bool },
    In { neg: bool, members: std::collections::HashSet<char>, tail: Vec<Tail>, fold: Option<bool>, ascii: bool },
}

#[derive(Clone)]
enum Tail {
    Range(u32, u32),
    RangeUni(u32, u32), // поза BMP з (?i): мала літера чи її велика — у межах (RANGE_UNI_IGNORE)
    Cat(Cat),
}

/// _sre.unicode_iscased.
fn cased(c: char) -> bool {
    uni::lower1(c) != c || uni::upper1(c) != c
}

/// _sre.ascii_tolower: (?a) — регістр лише в ASCII.
fn alow(c: char) -> char {
    c.to_ascii_lowercase()
}

/// Малі літери, рівні c під (?i) (re._casefix._EXTRA_CASES).
fn fixes(c: char) -> &'static [u32] {
    match crate::lang::RX_EXTRA_CASES.binary_search_by_key(&(c as u32), |x| x.0) {
        Ok(i) => crate::lang::RX_EXTRA_CASES[i].1,
        Err(_) => &[],
    }
}

#[derive(Clone)]
enum Ins {
    Ch(usize), // номер предиката
    Split(usize, usize),
    Jmp(usize),
    Save(usize),
    At(At),
    Match,
}

pub struct Rx {
    prog: Vec<Ins>,
    preds: Vec<Pred>,
    pub ngroups: usize,
    pub names: Vec<(String, usize)>,
    multiline: bool,
    ascii: bool,
}

fn nullable(items: &[Op]) -> bool {
    for op in items {
        match op {
            Op::Literal(_) | Op::NotLiteral(_) | Op::Any | Op::In(_) => return false,
            Op::Sub(_, _, _, p) if !nullable(p) => return false,
            Op::Branch(bs) if !bs.iter().any(|b| nullable(b)) => return false,
            Op::Repeat(_, lo, _, p) if *lo > 0 && !nullable(p) => return false,
            _ => {}
        }
    }
    true
}

fn human(op: &Op) -> &'static str {
    match op {
        Op::GroupRef(_) => "зворотне посилання \\1",
        Op::Assert => "заглядання (?=…)/(?<=…)",
        Op::AssertNot => "заглядання (?!…)/(?<!…)",
        Op::GroupRefExists => "умовна група (?(1)…)",
        Op::Atomic => "атомарна група (?>…)",
        Op::Repeat(2, ..) => "присвійне повторення *+ ++ ?+",
        Op::Failure => "FAILURE",
        _ => "?",
    }
}

struct Gen {
    prog: Vec<Ins>,
    preds: Vec<Pred>,
    ascii: bool,
}

impl Gen {
    fn emit(&mut self, i: Ins) -> Result<usize, String> {
        if self.prog.len() >= RX_MAX_PROG {
            return Err(format!("шаблон розгортається понад {} інструкцій (зменште {{m,n}})", RX_MAX_PROG));
        }
        self.prog.push(i);
        Ok(self.prog.len() - 1)
    }

    fn pred(&mut self, op: &Op, icase: bool, dotall: bool) -> Result<usize, String> {
        let ascii = self.ascii;
        let low = |c: char| if ascii { alow(c) } else { uni::lower1(c) };
        let iscased = |c: char| if ascii { c.is_ascii_alphabetic() } else { cased(c) };
        let fx = |c: char| if icase && !ascii { fixes(c) } else { &[] };
        let p = match op {
            Op::Literal(v) | Op::NotLiteral(v) => {
                let c = char::from_u32(*v).unwrap_or('\u{FFFD}');
                let neg = matches!(op, Op::NotLiteral(_));
                if !icase || !iscased(c) {
                    Pred::Eq { c, neg }
                } else {
                    let lo = low(c);
                    let mut cs = vec![lo];
                    cs.extend(fx(lo).iter().filter_map(|&x| char::from_u32(x)));
                    Pred::Fold { cs, alow: ascii, neg }
                }
            }
            Op::Any => Pred::Any { dotall },
            Op::In(items) => {
                let mut neg = false;
                let mut members = std::collections::HashSet::new();
                let mut tail = Vec::new();
                let mut hascased = false;
                for it in items {
                    match it {
                        SetItem::Negate => neg = true,
                        SetItem::Literal(v) => {
                            let c = char::from_u32(*v).unwrap_or('\u{FFFD}');
                            if icase {
                                let lo = low(c);
                                members.insert(lo);
                                members.extend(fx(lo).iter().filter_map(|&x| char::from_u32(x)));
                                hascased = hascased || iscased(lo);
                            } else {
                                members.insert(c);
                            }
                        }
                        SetItem::Range(a, b) => {
                            if !icase {
                                tail.push(Tail::Range(*a, *b));
                                continue;
                            }
                            for i in *a..=(*b).min(0xFFFF) {
                                if let Some(c) = char::from_u32(i) { // сурогатів у тексті Nigredo не буває
                                    let lo = low(c);
                                    members.insert(lo);
                                    members.extend(fx(lo).iter().filter_map(|&x| char::from_u32(x)));
                                }
                            }
                            if *b > 0xFFFF {
                                tail.push(if ascii { Tail::Range(*a, *b) } else { Tail::RangeUni(*a, *b) });
                                hascased = true;
                            } else if !hascased {
                                hascased = (*a..=*b).any(|i| char::from_u32(i).map_or(false, iscased));
                            }
                        }
                        SetItem::Category(c) => tail.push(Tail::Cat(*c)),
                    }
                }
                Pred::In { neg, members, tail, fold: if icase && hascased { Some(ascii) } else { None }, ascii }
            }
            _ => unreachable!(),
        };
        self.preds.push(p);
        Ok(self.preds.len() - 1)
    }

    fn gen(&mut self, items: &[Op], icase: bool, dotall: bool) -> Result<(), String> {
        for op in items {
            self.node(op, icase, dotall)?;
        }
        Ok(())
    }

    fn node(&mut self, op: &Op, icase: bool, dotall: bool) -> Result<(), String> {
        match op {
            Op::Literal(_) | Op::NotLiteral(_) | Op::Any | Op::In(_) => {
                let p = self.pred(op, icase, dotall)?;
                self.emit(Ins::Ch(p))?;
            }
            Op::Sub(g, add, del, sub) => {
                let ic = (icase || add & F_IGNORECASE != 0) && del & F_IGNORECASE == 0;
                let dt = (dotall || add & F_DOTALL != 0) && del & F_DOTALL == 0;
                if let Some(g) = g {
                    if *g > 0 {
                        self.emit(Ins::Save(2 * g))?;
                    }
                }
                self.gen(sub, ic, dt)?;
                if let Some(g) = g {
                    if *g > 0 {
                        self.emit(Ins::Save(2 * g + 1))?;
                    }
                }
            }
            Op::Branch(alts) => {
                let mut jumps = Vec::new();
                for (k, alt) in alts.iter().enumerate() {
                    if k < alts.len() - 1 {
                        let sp = self.emit(Ins::Split(0, 0))?;
                        self.prog[sp] = Ins::Split(sp + 1, 0);
                        self.gen(alt, icase, dotall)?;
                        jumps.push(self.emit(Ins::Jmp(0))?);
                        let l = self.prog.len();
                        self.prog[sp] = Ins::Split(sp + 1, l);
                    } else {
                        self.gen(alt, icase, dotall)?;
                    }
                }
                let l = self.prog.len();
                for j in jumps {
                    self.prog[j] = Ins::Jmp(l);
                }
            }
            Op::Repeat(kind, lo, hi, sub) if *kind < 2 => {
                let greedy = *kind == 0;
                if (*hi == MAXREPEAT || *hi > 1) && nullable(sub) {
                    return Err("тіло повторення може збігтися з порожнім рядком (як у (a?)+ чи (\\d*|\\s){1,3}) — такий шаблон \
                                неоднозначний; перепишіть, щоб кожне повторення щось забирало"
                        .into());
                }
                for _ in 0..*lo {
                    self.gen(sub, icase, dotall)?;
                }
                if *hi == MAXREPEAT {
                    let l1 = self.emit(Ins::Split(0, 0))?;
                    self.gen(sub, icase, dotall)?;
                    self.emit(Ins::Jmp(l1))?;
                    let l = self.prog.len();
                    self.prog[l1] = if greedy { Ins::Split(l1 + 1, l) } else { Ins::Split(l, l1 + 1) };
                } else {
                    let mut ends = Vec::new();
                    for _ in 0..(*hi - *lo) {
                        let sp = self.emit(Ins::Split(0, 0))?;
                        ends.push(sp);
                        self.gen(sub, icase, dotall)?;
                    }
                    let end = self.prog.len();
                    for sp in ends {
                        self.prog[sp] = if greedy { Ins::Split(sp + 1, end) } else { Ins::Split(end, sp + 1) };
                    }
                }
            }
            Op::At(a) => {
                self.emit(Ins::At(*a))?;
            }
            other => {
                return Err(format!("{} вимагає відкатів — у Nigredo регулярки без відкатів (лінійний час)", human(other)));
            }
        }
        Ok(())
    }
}

/// Символ чи рядок (ch.lower() може бути довшим за символ).
fn cat_hit(cat: Cat, ch: &str, ascii: bool) -> bool {
    let hit = if ascii && !ch.is_ascii() {
        false
    } else {
        match cat {
            Cat::Digit | Cat::NotDigit => ch >= "0" && ch <= "9",
            Cat::Space | Cat::NotSpace => {
                if ascii {
                    ch.chars().count() == 1 && " \t\n\r\u{c}\u{b}".contains(ch)
                } else {
                    !ch.is_empty() && ch.chars().all(uni::isspace)
                }
            }
            Cat::Word | Cat::NotWord => (!ch.is_empty() && ch.chars().all(uni::isalnum)) || ch == "_",
        }
    };
    if matches!(cat, Cat::NotDigit | Cat::NotSpace | Cat::NotWord) { !hit } else { hit }
}

impl Pred {
    fn test(&self, c: char) -> Result<bool, String> {
        Ok(match self {
            Pred::Any { dotall } => *dotall || c != '\n',
            Pred::Eq { c: x, neg } => (c == *x) != *neg,
            Pred::Fold { cs, alow: a, neg } => cs.contains(&if *a { alow(c) } else { uni::lower1(c) }) != *neg,
            Pred::In { neg, members, tail, fold, ascii } => {
                let ch = match fold {
                    Some(true) => alow(c),
                    Some(false) => uni::lower1(c),
                    None => c,
                };
                let mut hit = members.contains(&ch);
                if !hit {
                    let o = ch as u32;
                    let mut buf = [0u8; 4];
                    for t in tail {
                        hit = match t {
                            Tail::Range(a, b) => *a <= o && o <= *b,
                            Tail::RangeUni(a, b) => (*a <= o && o <= *b) || {
                                let u = uni::upper1(ch) as u32;
                                *a <= u && u <= *b
                            },
                            Tail::Cat(k) => cat_hit(*k, ch.encode_utf8(&mut buf), *ascii),
                        };
                        if hit {
                            break;
                        }
                    }
                }
                hit != *neg
            }
        })
    }
}

pub type Slots = Vec<Option<usize>>;

/// Частина розібраного шаблону заміни.
pub enum Piece {
    Lit(String),
    Group(usize),
}

impl Rx {
    pub fn new(pat: &str) -> Result<Rx, RxErr> {
        let cs: Vec<char> = pat.chars().collect();
        if cs.len() > 1000 {
            return Err(RxErr::Rx("шаблон довший за 1000 символів".into()));
        }
        let mut i = 0;
        while i + 1 < cs.len() {        // \N{назва}: бази назв Unicode немає — однаково з еталоном (суд 9)
            if cs[i] == '\\' {
                if cs[i + 1] == 'N' {
                    return Err(RxErr::Rx("\\N{…} (назва символу) у шаблоні не підтримано — напишіть сам символ".into()));
                }
                i += 1;
            }
            i += 1;
        }
        let (tree, flags, ngroups, names) = parse_pattern(&cs)?;
        let mut g = Gen { prog: Vec::new(), preds: Vec::new(), ascii: flags & F_ASCII != 0 };
        let r = (|| -> Result<(), String> {
            g.emit(Ins::Save(0))?;
            g.gen(&tree, flags & F_IGNORECASE != 0, flags & F_DOTALL != 0)?;
            g.emit(Ins::Save(1))?;
            g.emit(Ins::Match)?;
            Ok(())
        })();
        r.map_err(RxErr::Rx)?;
        Ok(Rx { prog: g.prog, preds: g.preds, ngroups, names, multiline: flags & F_MULTILINE != 0, ascii: flags & F_ASCII != 0 })
    }

    fn at(&self, code: At, t: &[char], pos: usize) -> bool {
        let n = t.len();
        match code {
            At::Beginning => pos == 0 || (self.multiline && t[pos - 1] == '\n'),
            At::BeginningString => pos == 0,
            At::End => {
                if self.multiline {
                    pos == n || t[pos] == '\n'
                } else {
                    pos == n || (pos + 1 == n && t[pos] == '\n')
                }
            }
            At::EndString => pos == n,
            At::Boundary | At::NonBoundary => {
                let w = |c: char| uni::isalnum(c) || c == '_';
                let a = pos > 0 && w(t[pos - 1]);
                let b = pos < n && w(t[pos]);
                if code == At::Boundary { a != b } else { a == b }
            }
        }
    }

    fn add(&self, lst: &mut Vec<(usize, Slots)>, seen: &mut Vec<bool>, pc: usize, slots: Slots, t: &[char], pos: usize) {
        let mut stack = vec![(pc, slots)];
        while let Some((pc, slots)) = stack.pop() {
            if seen[pc] {
                continue;
            }
            seen[pc] = true;
            match &self.prog[pc] {
                Ins::Jmp(x) => stack.push((*x, slots)),
                Ins::Split(x, y) => {
                    stack.push((*y, slots.clone()));
                    stack.push((*x, slots));
                }
                Ins::Save(k) => {
                    let mut s = slots;
                    s[*k] = Some(pos);
                    stack.push((pc + 1, s));
                }
                Ins::At(code) => {
                    if self.at(*code, t, pos) {
                        stack.push((pc + 1, slots));
                    }
                }
                _ => lst.push((pc, slots)),
            }
        }
    }

    /// Найлівіший збіг від start (пріоритет Perl); pay(k) — оплата кроків.
    pub fn search(&self, t: &[char], start: usize, pay: &mut dyn FnMut(i64) -> Result<(), String>, no_empty_at: Option<usize>)
        -> Result<Option<Slots>, String> {
        let n = t.len();
        let empty: Slots = vec![None; 2 * self.ngroups];
        let mut clist = Vec::new();
        let mut seen = vec![false; self.prog.len()];
        self.add(&mut clist, &mut seen, 0, empty.clone(), t, start);
        let mut matched: Option<Slots> = None;
        let mut pos = start;
        loop {
            pay(clist.len() as i64 + 1)?;
            let mut nlist = Vec::new();
            let mut nseen = vec![false; self.prog.len()];
            let ch = if pos < n { Some(t[pos]) } else { None };
            for (pc, slots) in clist.into_iter() {
                match &self.prog[pc] {
                    Ins::Match => {
                        if let Some(e) = no_empty_at {
                            if slots[0] == Some(e) && slots[1] == Some(e) {
                                continue;
                            }
                        }
                        matched = Some(slots);
                        break;
                    }
                    Ins::Ch(p) => {
                        if let Some(c) = ch {
                            if self.preds[*p].test(c)? {
                                self.add(&mut nlist, &mut nseen, pc + 1, slots, t, pos + 1);
                            }
                        }
                    }
                    _ => {}
                }
            }
            if pos >= n {
                break;
            }
            pos += 1;
            if matched.is_none() {
                self.add(&mut nlist, &mut nseen, 0, empty.clone(), t, pos);
            }
            if nlist.is_empty() && matched.is_some() {
                break;
            }
            clist = nlist;
        }
        Ok(matched)
    }

    pub fn finditer(&self, t: &[char], pay: &mut dyn FnMut(i64) -> Result<(), String>,
                    each: &mut dyn FnMut(&Slots) -> Result<(), String>) -> Result<(), String> {
        let n = t.len();
        let mut pos = 0;
        let mut prev_empty: Option<usize> = None;
        while pos <= n {
            let m = match self.search(t, pos, pay, prev_empty)? {
                None => return Ok(()),
                Some(m) => m,
            };
            each(&m)?;
            let (s, e) = (m[0].unwrap(), m[1].unwrap());
            prev_empty = if s == e { Some(e) } else { None };
            pos = e;
        }
        Ok(())
    }

    pub fn groups(&self, t: &[char], m: &Slots) -> Vec<Option<String>> {
        (0..self.ngroups)
            .map(|g| match (m[2 * g], m[2 * g + 1]) {
                (Some(a), Some(b)) => Some(t[a..b.max(a)].iter().collect()),
                (Some(a), None) => Some(t[a..].iter().collect()),
                _ => None,
            })
            .collect()
    }

    /// Шаблон заміни — як re._parser.parse_template (CPython 3.13, nigredo.Rx.template): рядки й номери груп;
    /// хибний — помилка одразу, навіть без збігу.
    pub fn template(&self, tmpl: &[char]) -> Result<Vec<Piece>, String> {
        let (mut out, mut lit) = (Vec::new(), String::new());
        let groups = self.ngroups as u64 - 1;
        let n = tmpl.len();
        let mut i = 0;
        let group = |k: u64, shown: String, lit: &mut String, out: &mut Vec<Piece>| -> Result<(), String> {
            if k > groups {
                return Err(format!("у заміні немає групи {}", shown));
            }
            out.push(Piece::Lit(std::mem::take(lit)));
            out.push(Piece::Group(k as usize));
            Ok(())
        };
        let oct = |c: char| ('0'..='7').contains(&c);
        while i < n {
            let c = tmpl[i];
            i += 1;
            if c != '\\' {
                lit.push(c);
                continue;
            }
            if i >= n {
                return Err("заміна закінчується на «\\»".into());
            }
            let d = tmpl[i];
            i += 1;
            if d == 'g' {
                if i >= n || tmpl[i] != '<' {
                    return Err("у заміні \\g без <…>".into());
                }
                let j = match tmpl[i + 1..].iter().position(|&x| x == '>') {
                    Some(p) => i + 1 + p,
                    None => return Err("у заміні незакрите \\g<".into()),
                };
                let name: String = tmpl[i + 1..j].iter().collect();
                i = j + 1;
                if !name.is_empty() && name.chars().all(|x| x.is_ascii_digit()) {
                    let t = name.trim_start_matches('0');
                    let shown = if t.is_empty() { "0".to_string() } else { t.to_string() };
                    let k = if shown.len() > 18 { u64::MAX } else { shown.parse::<u64>().unwrap() };
                    group(k, shown, &mut lit, &mut out)?;
                } else if name.is_empty() {
                    return Err("у заміні порожнє \\g<>".into());
                } else {
                    match self.names.iter().find(|(nm, _)| *nm == name) {
                        Some((_, g)) if uni::is_identifier(&name) => group(*g as u64, g.to_string(), &mut lit, &mut out)?,
                        _ => return Err(format!("у заміні немає групи «{}»", name)),
                    }
                }
            } else if d == '0' {
                let mut v = 0u32;
                let mut j = i;
                while j < n && j < i + 2 && oct(tmpl[j]) {
                    v = v * 8 + tmpl[j] as u32 - '0' as u32;
                    j += 1;
                }
                lit.push(char::from_u32(v & 0xff).unwrap());
                i = j;
            } else if ('1'..='9').contains(&d) {
                let k;
                if i < n && tmpl[i].is_ascii_digit() {
                    if oct(d) && oct(tmpl[i]) && i + 1 < n && oct(tmpl[i + 1]) {
                        let v = (d as u32 - 48) * 64 + (tmpl[i] as u32 - 48) * 8 + (tmpl[i + 1] as u32 - 48);
                        if v > 0o377 {
                            return Err(format!("у заміні вісімкове \\{}{}{} понад \\377", d, tmpl[i], tmpl[i + 1]));
                        }
                        lit.push(char::from_u32(v).unwrap());
                        i += 2;
                        continue;
                    }
                    k = (d as u64 - 48) * 10 + (tmpl[i] as u64 - 48);
                    i += 1;
                } else {
                    k = d as u64 - 48;
                }
                group(k, k.to_string(), &mut lit, &mut out)?;
            } else {
                let e = match d {
                    'a' => '\u{7}',
                    'b' => '\u{8}',
                    'f' => '\u{c}',
                    'n' => '\n',
                    'r' => '\r',
                    't' => '\t',
                    'v' => '\u{b}',
                    '\\' => '\\',
                    x if x.is_ascii_alphabetic() => return Err(format!("у заміні невідоме екранування \\{}", x)),
                    x => {
                        lit.push('\\');
                        x
                    }
                };
                lit.push(e);
            }
        }
        out.push(Piece::Lit(lit));
        Ok(out)
    }
}

/// int(s) для рядка з isdigit-символів: десяткові (будь-якого письма) — число; інші (², ①) — ValueError.
fn py_int(s: &str) -> Result<i64, String> {
    let mut v: i64 = 0;
    for c in s.chars() {
        match uni::decimal(c) {
            Some(d) => v = v * 10 + d as i64,
            None => return Err(format!("ValueError: invalid literal for int() with base 10: {}", uni::py_repr(s))),
        }
    }
    Ok(v)
}

/// Текст помилки re.error (як str(e)).
pub fn re_error_text(e: &ReErr, pat: &str) -> String {
    match e.pos {
        None => e.msg.clone(),
        Some(pos) => {
            let mut m = format!("{} at position {}", e.msg, pos);
            if pat.contains('\n') {
                let cs: Vec<char> = pat.chars().collect();
                let before = &cs[..pos.min(cs.len())];
                let line = before.iter().filter(|&&c| c == '\n').count() + 1;
                let col = match before.iter().rposition(|&c| c == '\n') {
                    Some(p) => pos - p,
                    None => pos + 1,
                };
                m = format!("{} (line {}, column {})", m, line, col);
            }
            m
        }
    }
}
