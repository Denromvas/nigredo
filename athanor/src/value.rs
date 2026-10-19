//! Значення з впевненістю — як nigredo.V: c — впевненість, s — впевненість будови, n — логічний розмір.
use crate::ast::Lambda;
use crate::dec::Dec;
use crate::int::Int;
use crate::json;
use crate::pyf;
use crate::uni;
use std::cell::RefCell;
use std::cmp::Ordering;
use std::collections::HashMap;
use std::rc::Rc;

/// Рядок Python: символи (code points); довжина — у символах.
#[derive(Debug)]
pub struct PStr {
    pub s: Box<str>,
    pub nch: usize,
    idx: RefCell<Option<Rc<Vec<u32>>>>, // зміщення символів (для індексів у довгих не-ASCII рядках)
}

impl PStr {
    pub fn new(s: String) -> PStr {
        let nch = if s.is_ascii() { s.len() } else { s.chars().count() };
        PStr { s: s.into_boxed_str(), nch, idx: RefCell::new(None) }
    }
    pub fn from(s: &str) -> PStr {
        PStr::new(s.to_string())
    }
    pub fn ascii(&self) -> bool {
        self.nch == self.s.len()
    }
    /// Байтове зміщення i-го символу (i ≤ nch).
    pub fn byte_at(&self, i: usize) -> usize {
        if self.ascii() {
            return i;
        }
        if i >= self.nch {
            return self.s.len();
        }
        if self.nch < 64 {
            return self.s.char_indices().nth(i).map(|(b, _)| b).unwrap_or(self.s.len());
        }
        let mut cache = self.idx.borrow_mut();
        let v = cache.get_or_insert_with(|| Rc::new(self.s.char_indices().map(|(b, _)| b as u32).collect())).clone();
        v[i] as usize
    }
    /// Зріз [a, b) у символах.
    pub fn slice(&self, a: usize, b: usize) -> &str {
        if a >= b {
            return "";
        }
        let x = self.byte_at(a);
        let y = self.byte_at(b);
        &self.s[x..y]
    }
    pub fn char_at(&self, i: usize) -> char {
        let b = self.byte_at(i);
        self.s[b..].chars().next().unwrap()
    }
    /// Позиція в символах за байтовим зміщенням.
    pub fn char_index(&self, byte: usize) -> usize {
        if self.ascii() { byte } else { self.s[..byte].chars().count() }
    }
}

/// FxHash (rustc): швидкий хеш для коротких ключів-рядків (стійкість до колізій тут не потрібна: ключі — дані
/// програми, а найгірший випадок лише сповільнює, не змінює результат).
#[derive(Default, Clone, Copy)]
pub struct Fx(u64);

impl std::hash::Hasher for Fx {
    #[inline]
    fn write(&mut self, bytes: &[u8]) {
        let mut h = self.0;
        let mut b = bytes;
        while b.len() >= 8 {
            h = (h.rotate_left(5) ^ u64::from_le_bytes(b[..8].try_into().unwrap())).wrapping_mul(0x51_7c_c1_b7_27_22_0a_95);
            b = &b[8..];
        }
        for &x in b {
            h = (h.rotate_left(5) ^ x as u64).wrapping_mul(0x51_7c_c1_b7_27_22_0a_95);
        }
        self.0 = h;
    }
    #[inline]
    fn finish(&self) -> u64 {
        self.0
    }
}

pub type FxBuild = std::hash::BuildHasherDefault<Fx>;
pub type FxMap<K, V> = HashMap<K, V, FxBuild>;

#[derive(Debug, Default)]
pub struct Dict {
    pub keys: Vec<Rc<PStr>>,
    pub vals: Vec<V>,
    index: RefCell<Option<FxMap<Rc<str>, usize>>>,
}

impl Dict {
    pub fn new() -> Dict {
        Dict::default()
    }
    pub fn len(&self) -> usize {
        self.keys.len()
    }
    pub fn find(&self, k: &str) -> Option<usize> {
        if self.keys.len() <= 8 {
            return self.keys.iter().position(|x| &*x.s == k);
        }
        let mut idx = self.index.borrow_mut();
        let m = idx.get_or_insert_with(|| {
            let mut m = FxMap::with_capacity_and_hasher(self.keys.len(), Default::default());
            for (i, x) in self.keys.iter().enumerate() {
                m.insert(Rc::from(&*x.s), i);
            }
            m
        });
        m.get(k).copied()
    }
    pub fn get(&self, k: &str) -> Option<&V> {
        self.find(k).map(|i| &self.vals[i])
    }
    /// Вставити або замінити (порядок — першої появи), як dict у Python.
    pub fn set(&mut self, k: Rc<PStr>, v: V) {
        match self.find(&k.s) {
            Some(i) => self.vals[i] = v,
            None => {
                if let Some(m) = self.index.get_mut().as_mut() {
                    m.insert(Rc::from(&*k.s), self.keys.len());
                }
                self.keys.push(k);
                self.vals.push(v);
            }
        }
    }
    pub fn copy(&self) -> Dict {
        Dict { keys: self.keys.clone(), vals: self.vals.clone(), index: RefCell::new(None) }
    }
}

pub struct Env {
    pub vars: RefCell<Vec<V>>,
    pub parent: Option<Rc<Env>>,
}

impl Env {
    pub fn new(n: usize, parent: Option<Rc<Env>>) -> Rc<Env> {
        Rc::new(Env { vars: RefCell::new(vec![V::none(); n]), parent })
    }
    pub fn at(self: &Rc<Env>, hops: u32) -> Rc<Env> {
        let mut e = self.clone();
        for _ in 0..hops {
            e = e.parent.clone().unwrap();
        }
        e
    }
}

pub struct Func {
    pub lam: Rc<Lambda>,
    pub env: Rc<Env>,
    pub name: Option<Rc<str>>,
}

impl std::fmt::Debug for Func {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "λ{}", self.name.as_deref().unwrap_or(""))
    }
}

#[derive(Clone, Debug)]
pub enum Val {
    None,
    Bool(bool),
    Int(Int),
    Dec(Rc<Dec>),
    Float(f64),
    Str(Rc<PStr>),
    List(Rc<Vec<V>>),
    Dict(Rc<Dict>),
    Fn(Rc<Func>),
}

#[derive(Clone, Debug)]
pub struct V {
    pub v: Val,
    pub c: f64,
    pub s: f64,
    pub n: u64,
}

pub fn size_of(v: &Val) -> u64 {
    match v {
        Val::Int(i) => 1 + i.bit_length() / 3,
        Val::Str(s) => s.nch as u64 + 1,
        Val::List(l) => 1 + l.iter().map(|e| e.n).sum::<u64>(),
        Val::Dict(d) => 1 + d.keys.iter().zip(&d.vals).map(|(k, e)| k.nch as u64 + e.n).sum::<u64>(),
        Val::Dec(d) => 1 + d.adjusted().unsigned_abs() + d.digits(),
        _ => 1,
    }
}

impl V {
    pub fn new(v: Val, c: f64) -> V {
        let n = size_of(&v);
        V { v, c, s: c, n }
    }
    pub fn cs(v: Val, c: f64, s: f64) -> V {
        let n = size_of(&v);
        V { v, c, s, n }
    }
    pub fn none() -> V {
        V { v: Val::None, c: 1.0, s: 1.0, n: 1 }
    }
    pub fn none_c(c: f64) -> V {
        V { v: Val::None, c, s: c, n: 1 }
    }
    pub fn b(x: bool) -> V {
        V { v: Val::Bool(x), c: 1.0, s: 1.0, n: 1 }
    }
    pub fn int(i: Int) -> V {
        V::new(Val::Int(i), 1.0)
    }
    pub fn i64(i: i64) -> V {
        V::int(Int::S(i))
    }
    pub fn str(s: String) -> V {
        V::new(Val::Str(Rc::new(PStr::new(s))), 1.0)
    }
    pub fn strc(s: String, c: f64) -> V {
        V::new(Val::Str(Rc::new(PStr::new(s))), c)
    }
    pub fn list(items: Vec<V>) -> V {
        V::new(Val::List(Rc::new(items)), 1.0)
    }
    pub fn listc(items: Vec<V>, c: f64) -> V {
        V::new(Val::List(Rc::new(items)), c)
    }
    pub fn dec(d: Dec) -> V {
        V::new(Val::Dec(Rc::new(d)), 1.0)
    }
    /// Те саме значення з іншими впевненостями (n — те саме).
    pub fn with(&self, c: f64, s: f64) -> V {
        V { v: self.v.clone(), c, s, n: self.n }
    }
    pub fn is_str(&self) -> bool {
        matches!(self.v, Val::Str(_))
    }
}

pub fn lit_val(l: &crate::lexer::Lit) -> Val {
    use crate::lexer::Lit;
    match l {
        Lit::None => Val::None,
        Lit::Bool(b) => Val::Bool(*b),
        Lit::Int(i) => Val::Int(i.clone()),
        Lit::Dec(d) => Val::Dec(d.clone()),
        Lit::Str(s) => Val::Str(Rc::new(PStr::from(s))),
    }
}

/// Значення змінної: (середовищ угору, номер) — без копій вказівників.
#[inline]
pub fn env_get(env: &Rc<Env>, hops: u32, slot: u32) -> V {
    let mut e: &Env = env;
    for _ in 0..hops {
        e = e.parent.as_deref().unwrap();
    }
    e.vars.borrow()[slot as usize].clone()
}

/// mk: список, чия впевненість — мінімум вмісту (і extra); будова — extra.
pub fn mk(items: Vec<V>, extra: f64) -> V {
    let c = items.iter().fold(extra, |a, e| a.min(e.c));
    V::cs(Val::List(Rc::new(items)), c, extra)
}

/// capc: встановити впевненість c значенню і всьому, що в ньому.
pub fn capc(x: &V, c: f64) -> V {
    match &x.v {
        Val::List(l) => {
            let items: Vec<V> = l.iter().map(|e| capc(e, c)).collect();
            V { v: Val::List(Rc::new(items)), c, s: x.s.min(c), n: x.n }
        }
        Val::Dict(d) => {
            let nd = Dict {
                keys: d.keys.clone(),
                vals: d.vals.iter().map(|e| capc(e, c)).collect(),
                index: RefCell::new(None),
            };
            V { v: Val::Dict(Rc::new(nd)), c, s: x.s.min(c), n: x.n }
        }
        _ => V { v: x.v.clone(), c, s: c, n: x.n },
    }
}

pub fn kind(x: &V) -> &'static str {
    match x.v {
        Val::None => "ніщо",
        Val::Bool(_) => "істинність",
        Val::Int(_) | Val::Dec(_) | Val::Float(_) => "число",
        Val::Str(_) => "рядок",
        Val::List(_) => "список",
        Val::Dict(_) => "словник",
        Val::Fn(_) => "функція",
    }
}

pub fn fmt_dec(d: &Dec) -> String {
    let t = d.to_fixed();
    let t = if t.contains('.') { t.trim_end_matches('0').trim_end_matches('.').to_string() } else { t };
    if t == "-0" { "0".into() } else { t }
}

pub fn fmt_num(v: &Val) -> String {
    match v {
        Val::Int(i) => i.to_string(),
        Val::Dec(d) => fmt_dec(d),
        Val::Float(f) => pyf::show(*f),
        Val::Bool(b) => (if *b { "1" } else { "0" }).into(),
        _ => String::new(),
    }
}

fn show_into(out: &mut String, x: &V, top: bool) {
    match &x.v {
        Val::Str(s) => {
            if top {
                out.push_str(&s.s);
            } else {
                out.push('「');
                let t: &str = &s.s;
                let b = t.as_bytes();
                out.reserve(b.len() + 4);
                let mut start = 0;
                let mut i = 0;
                while i < b.len() {
                    let c = b[i];
                    let rep = if c == b'\\' {
                        Some(("\\\\", 1))
                    } else if c == b'\n' {
                        Some(("\\n", 1))
                    } else if c == 0xE3 && i + 2 < b.len() && b[i + 1] == 0x80 && b[i + 2] == 0x8D {
                        Some(("\\」", 3))
                    } else {
                        None
                    };
                    if let Some((r, w)) = rep {
                        out.push_str(&t[start..i]);
                        out.push_str(r);
                        i += w;
                        start = i;
                    } else {
                        i += 1;
                    }
                }
                out.push_str(&t[start..]);
                out.push('」');
            }
        }
        Val::None => out.push('∅'),
        Val::Bool(b) => out.push(if *b { '●' } else { '○' }),
        Val::Int(_) | Val::Dec(_) | Val::Float(_) => out.push_str(&fmt_num(&x.v)),
        Val::List(l) => {
            out.push('【');
            for (i, e) in l.iter().enumerate() {
                if i > 0 {
                    out.push(' ');
                }
                show_into(out, e, false);
            }
            out.push('】');
        }
        Val::Dict(d) => {
            out.push('『');
            for (i, (k, e)) in d.keys.iter().zip(&d.vals).enumerate() {
                if i > 0 {
                    out.push(' ');
                }
                show_into(out, &V::new(Val::Str(k.clone()), 1.0), false);
                out.push(' ');
                show_into(out, e, false);
            }
            out.push('』');
        }
        Val::Fn(f) => {
            out.push('λ');
            if let Some(n) = &f.name {
                out.push_str(n);
            }
        }
    }
}

pub fn show(x: &V, top: bool) -> String {
    if let (true, Val::Str(s)) = (top, &x.v) {
        return s.s.to_string();
    }
    let mut out = String::new();
    show_into(&mut out, x, top);
    out
}

/// Глибина вкладеності значення (для меж рекурсії еталона).
pub fn depth(x: &V) -> usize {
    match &x.v {
        Val::List(l) => 1 + l.iter().map(depth).max().unwrap_or(0),
        Val::Dict(d) => 1 + d.vals.iter().map(depth).max().unwrap_or(0),
        _ => 0,
    }
}

pub fn to_json_into(out: &mut String, x: &V) {
    match &x.v {
        Val::List(l) => {
            out.push('[');
            for (i, e) in l.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                to_json_into(out, e);
            }
            out.push(']');
        }
        Val::Dict(d) => {
            out.push('{');
            for (i, (k, e)) in d.keys.iter().zip(&d.vals).enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                json::escape_into(out, &k.s);
                out.push_str(": ");
                to_json_into(out, e);
            }
            out.push('}');
        }
        Val::Dec(d) => out.push_str(&fmt_dec(d)),
        Val::Fn(_) => out.push_str("\"λ\""),
        Val::Str(s) => json::escape_into(out, &s.s),
        Val::None => out.push_str("null"),
        Val::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Val::Int(i) => out.push_str(&i.to_string()),
        Val::Float(f) => out.push_str(&json::dumps(&json::J::Float(*f), false)),
    }
}

pub fn to_json(x: &V) -> String {
    let mut out = String::new();
    to_json_into(&mut out, x);
    out
}

/// Числове значення для порівнянь: ціле, десяткове (float — точно).
pub fn num_cmp(a: &Val, b: &Val) -> Option<Ordering> {
    let as_dec = |v: &Val| -> Option<Dec> {
        match v {
            Val::Int(i) => Some(Dec::from_int(i)),
            Val::Dec(d) => Some((**d).clone()),
            Val::Float(f) => Some(Dec::from_f64(*f)),
            Val::Bool(b) => Some(Dec::from_int(&Int::S(*b as i64))),
            _ => None,
        }
    };
    if let (Val::Int(x), Val::Int(y)) = (a, b) {
        return Some(x.cmp(y));
    }
    if let (Val::Float(x), Val::Float(y)) = (a, b) {
        return x.partial_cmp(y);
    }
    Some(as_dec(a)?.cmp(&as_dec(b)?))
}

pub fn is_num(v: &Val) -> bool {
    matches!(v, Val::Int(_) | Val::Dec(_) | Val::Float(_))
}

/// Python ==: числа (і bool як число), рядки, ∅; списки й словники — за вмістом (deep_eq окремо); функції — тотожність.
pub fn deep_eq(a: &V, b: &V) -> bool {
    match (&a.v, &b.v) {
        (Val::Bool(x), Val::Bool(y)) => x == y,
        (Val::Bool(_), _) | (_, Val::Bool(_)) => false,
        (Val::List(x), Val::List(y)) => {
            Rc::ptr_eq(x, y) || (x.len() == y.len() && x.iter().zip(y.iter()).all(|(p, q)| deep_eq(p, q)))
        }
        (Val::Dict(x), Val::Dict(y)) => {
            if Rc::ptr_eq(x, y) {
                return true;
            }
            if x.len() != y.len() {
                return false;
            }
            for (k, v) in x.keys.iter().zip(&x.vals) {
                match y.get(&k.s) {
                    Some(w) => {
                        if !deep_eq(v, w) {
                            return false;
                        }
                    }
                    None => return false,
                }
            }
            true
        }
        (Val::Str(x), Val::Str(y)) => x.s == y.s,
        (Val::None, Val::None) => true,
        (Val::Fn(x), Val::Fn(y)) => Rc::ptr_eq(x, y),
        (x, y) if is_num(x) && is_num(y) => num_cmp(x, y) == Some(Ordering::Equal),
        _ => false,
    }
}

pub fn brief(x: &V, n: usize) -> String {
    let s = uni::safe(&show(x, false));
    if s.chars().count() <= n {
        s
    } else {
        let mut t: String = s.chars().take(n).collect();
        t.push('…');
        t
    }
}
