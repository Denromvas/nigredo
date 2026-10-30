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
    /// Довжина в символах уже відома (зʼєднання рядків: сума довжин) — без підрахунку.
    #[inline]
    pub fn owned(s: String, nch: usize) -> PStr {
        PStr { s: s.into_boxed_str(), nch, idx: RefCell::new(None) }
    }
    /// Довжина в символах уже відома (частина рядка, розрізаного ✂).
    #[inline]
    pub fn with_nch(s: &str, nch: usize) -> PStr {
        PStr { s: s.into(), nch, idx: RefCell::new(None) }
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

/// Одна копія на всі повтори коротких рядків (слова з ✂, ключі й значення JSON): рядки незмінні, тож спільне значення
/// нічим не відрізнити від окремих копій. Якщо повторів мало (після 1024 різних — повторів менше), кеш вимикається.
pub struct Interner<'a> {
    recent: [Option<(&'a str, Rc<PStr>)>; 4], // останні — без хешування (ключі записів ідуть тим самим порядком)
    turn: usize,
    map: FxMap<&'a str, Rc<PStr>>,
    misses: u32,
    hits: u32,
    on: bool,
    always: bool,
}

impl<'a> Interner<'a> {
    pub fn new() -> Interner<'a> {
        Interner { recent: [None, None, None, None], turn: 0, map: FxMap::default(), misses: 0, hits: 0, on: true, always: false }
    }
    /// Без вимикання — для ключів словників (їх мало й вони повторюються майже завжди).
    pub fn always() -> Interner<'a> {
        Interner { always: true, ..Interner::new() }
    }
    #[inline]
    pub fn get(&mut self, s: &'a str, nch: impl FnOnce() -> usize) -> Rc<PStr> {
        if self.on && s.len() <= 32 {
            for (k, r) in self.recent.iter().flatten() {
                if k.len() == s.len() && *k == s {
                    self.hits += 1;
                    return r.clone();
                }
            }
            if let Some(r) = self.map.get(s) {
                self.hits += 1;
                let r = r.clone();
                self.recent[self.turn & 3] = Some((s, r.clone()));
                self.turn += 1;
                return r;
            }
            self.misses += 1;
            if self.misses == 1024 && self.hits < self.misses && !self.always {
                self.on = false;
                self.map = FxMap::default();
                self.recent = [None, None, None, None];
            }
            let r = Rc::new(PStr::with_nch(s, nch()));
            if self.on {
                self.map.insert(s, r.clone());
                self.recent[self.turn & 3] = Some((s, r.clone()));
                self.turn += 1;
            }
            return r;
        }
        Rc::new(PStr::with_nch(s, nch()))
    }
}

/// Елементи списку (Vec, але звільнення глибоко вкладеного — без рекурсії, див. drop_later).
#[derive(Debug, Default, Clone)]
pub struct List(pub Vec<V>);

impl std::ops::Deref for List {
    type Target = Vec<V>;
    #[inline]
    fn deref(&self) -> &Vec<V> {
        &self.0
    }
}

impl FromIterator<V> for List {
    fn from_iter<I: IntoIterator<Item = V>>(it: I) -> List {
        List(it.into_iter().collect())
    }
}

impl Drop for List {
    fn drop(&mut self) {
        if cascades(&self.0) {
            drop_later(Later::Vals(std::mem::take(&mut self.0)));
        }
    }
}

/// Чи звільнення цих значень потягне звільнення вкладених (єдині власники списків, словників, функцій).
#[inline]
fn cascades(vals: &[V]) -> bool {
    vals.iter().any(|e| match &e.v {
        Val::List(l) => Rc::strong_count(l) == 1 && !l.0.is_empty(),
        Val::Dict(d) => Rc::strong_count(d) == 1 && !d.vals.is_empty(),
        Val::Fn(f) => Rc::strong_count(f) == 1,
        _ => false,
    })
}

enum Later {
    Vals(#[allow(dead_code)] Vec<V>),
    Env(#[allow(dead_code)] Vec<V>, #[allow(dead_code)] Option<Rc<Env>>),
}

thread_local! {
    static DROP_DEPTH: std::cell::Cell<u32> = const { std::cell::Cell::new(0) };
    static DROP_QUEUE: RefCell<Vec<Later>> = const { RefCell::new(Vec::new()) };
}

/// Звільнити вкладене: до 1000 рівнів — рекурсією, глибше — у чергу, яку розбирає найзовнішній виклик
/// (значення в мільйони рівнів — Σ, що загортає, чи ланцюг замикань — не переповнюють стек).
fn drop_later(x: Later) {
    let d = DROP_DEPTH.with(|c| c.get());
    if d >= 1000 {
        DROP_QUEUE.with(|q| q.borrow_mut().push(x));
        return;
    }
    DROP_DEPTH.with(|c| c.set(d + 1));
    drop(x);
    if d == 0 {
        while let Some(y) = DROP_QUEUE.with(|q| q.borrow_mut().pop()) {
            drop(y);
        }
    }
    DROP_DEPTH.with(|c| c.set(d));
}

#[derive(Debug, Default)]
pub struct Dict {
    pub keys: Vec<Rc<PStr>>,
    pub vals: Vec<V>,
    index: RefCell<Option<FxMap<Rc<str>, usize>>>,
}

impl Drop for Dict {
    fn drop(&mut self) {
        if cascades(&self.vals) {
            drop_later(Later::Vals(std::mem::take(&mut self.vals)));
        }
    }
}

impl Dict {
    pub fn new() -> Dict {
        Dict::default()
    }
    /// Ключі, про які відомо, що вони не повторюються (у порядку).
    pub fn from_unique(keys: Vec<Rc<PStr>>, vals: Vec<V>) -> Dict {
        Dict { keys, vals, index: RefCell::new(None) }
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

/// Модуль, у якому визначено функцію: (шлях для повідомлень, печатка модуля) — права при виклику.
#[derive(Debug)]
pub struct ModInfo {
    pub rel: String,
    pub caps: Rc<crate::ast::Caps>,
}

pub struct Env {
    pub vars: RefCell<Vec<V>>,
    pub parent: Option<Rc<Env>>,
    pub module: Option<Rc<ModInfo>>,
}

impl Env {
    pub fn new(n: usize, parent: Option<Rc<Env>>) -> Rc<Env> {
        let module = parent.as_ref().and_then(|p| p.module.clone());
        Rc::new(Env { vars: RefCell::new(vec![V::none(); n]), parent, module })
    }
    pub fn child(vars: Vec<V>, parent: &Rc<Env>) -> Rc<Env> {
        Rc::new(Env { vars: RefCell::new(vars), parent: Some(parent.clone()), module: parent.module.clone() })
    }
    pub fn at(self: &Rc<Env>, hops: u32) -> Rc<Env> {
        let mut e = self.clone();
        for _ in 0..hops {
            e = e.parent.clone().unwrap();
        }
        e
    }
}

impl Drop for Env {
    fn drop(&mut self) {
        let vars = self.vars.get_mut();
        if cascades(vars) || self.parent.as_ref().map_or(false, |p| Rc::strong_count(p) == 1) {
            drop_later(Later::Env(std::mem::take(vars), self.parent.take()));
        }
    }
}

pub struct Func {
    pub lam: Rc<Lambda>,
    pub env: Rc<Env>,
    pub name: Option<Rc<str>>,
    pub module: Option<Rc<ModInfo>>,
}

impl std::fmt::Debug for Func {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "λ{}", self.name.as_deref().unwrap_or(""))
    }
}

#[derive(Debug)]
pub enum Val {
    None,
    Bool(bool),
    Int(Int),
    Dec(Rc<Dec>),
    Float(f64),
    Str(Rc<PStr>),
    List(Rc<List>),
    Dict(Rc<Dict>),
    Fn(Rc<Func>),
}

impl Clone for Val {
    /// Скаляри — копіюванням на місці (найчастіше в циклах), решта — збільшення лічильника посилань.
    #[inline(always)]
    fn clone(&self) -> Val {
        match self {
            Val::Int(Int::S(x)) => Val::Int(Int::S(*x)),
            Val::None => Val::None,
            Val::Bool(b) => Val::Bool(*b),
            Val::Float(f) => Val::Float(*f),
            _ => self.clone_rc(),
        }
    }
}

impl Val {
    #[inline(never)]
    fn clone_rc(&self) -> Val {
        match self {
            Val::Int(i) => Val::Int(i.clone()),
            Val::Dec(d) => Val::Dec(d.clone()),
            Val::Str(x) => Val::Str(x.clone()),
            Val::List(x) => Val::List(x.clone()),
            Val::Dict(x) => Val::Dict(x.clone()),
            Val::Fn(x) => Val::Fn(x.clone()),
            Val::None => Val::None,
            Val::Bool(b) => Val::Bool(*b),
            Val::Float(f) => Val::Float(*f),
        }
    }
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
        V::new(lst(items), 1.0)
    }
    pub fn listc(items: Vec<V>, c: f64) -> V {
        V::new(lst(items), c)
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

#[inline]
pub fn lst(items: Vec<V>) -> Val {
    Val::List(Rc::new(List(items)))
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
    V::cs(lst(items), c, extra)
}

/// Обхід значення (показ, порівняння, JSON, ключі ⇅) — не глибше за стільки рівнів (WALK_MAX_DEPTH еталона).
pub const WALK: usize = crate::lang::WALK_MAX_DEPTH as usize;

/// Значення глибше за WALK: місце виклику перетворює на свою помилку (як RecursionError в еталоні).
pub fn deep<T>() -> crate::interp::R<T> {
    Err(Box::new(crate::interp::E {
        msg: format!("DeepValue: значення вкладене глибше за {} рівнів", WALK),
        pos: None,
        c: 1.0,
        wh: false,
        file: None,
        fatal: true,
        pipe: false,
        internal: true,
        deep: true,
    }))
}

/// capc: встановити впевненість c значенню і всьому, що в ньому (будь-якої глибини — не падає).
pub fn capc(x: &V, c: f64) -> V {
    capc_d(x, c, 0)
}

fn capc_d(x: &V, c: f64, d: usize) -> V {
    match &x.v {
        Val::List(_) | Val::Dict(_) if d >= WALK => capc_deep(x, c),
        Val::List(l) => {
            let items: Vec<V> = l.iter().map(|e| capc_d(e, c, d + 1)).collect();
            V { v: lst(items), c, s: x.s.min(c), n: x.n }
        }
        Val::Dict(dd) => {
            let nd = Dict { keys: dd.keys.clone(), vals: dd.vals.iter().map(|e| capc_d(e, c, d + 1)).collect(), index: RefCell::new(None) };
            V { v: Val::Dict(Rc::new(nd)), c, s: x.s.min(c), n: x.n }
        }
        _ => V { v: x.v.clone(), c, s: c, n: x.n },
    }
}

/// capc без рекурсії: список чи словник збирається, щойно готові всі його елементи.
fn capc_deep(x: &V, c: f64) -> V {
    let mut out: Vec<V> = Vec::new();
    let mut todo: Vec<(&V, bool)> = vec![(x, false)];
    while let Some((e, ready)) = todo.pop() {
        let kids: &[V] = match &e.v {
            Val::List(l) => &l.0,
            Val::Dict(dd) => &dd.vals,
            _ => {
                out.push(V { v: e.v.clone(), c, s: c, n: e.n });
                continue;
            }
        };
        if !ready {
            todo.push((e, true));
            todo.extend(kids.iter().rev().map(|k| (k, false)));
            continue;
        }
        let items = out.split_off(out.len() - kids.len());
        let v = match &e.v {
            Val::Dict(dd) => Val::Dict(Rc::new(Dict { keys: dd.keys.clone(), vals: items, index: RefCell::new(None) })),
            _ => lst(items),
        };
        out.push(V { v, c, s: e.s.min(c), n: e.n });
    }
    out.pop().unwrap()
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

/// Чи є в 8 байтах «\\», перенос рядка чи 0xE3 (перший байт «」») — SWAR.
#[inline(always)]
pub fn word_has_show_esc(w: u64) -> bool {
    const LO: u64 = 0x0101_0101_0101_0101;
    const HI: u64 = 0x8080_8080_8080_8080;
    let zero = |x: u64| x.wrapping_sub(LO) & !x & HI;
    (zero(w ^ (LO * 0x5C)) | zero(w ^ (LO * 0x0A)) | zero(w ^ (LO * 0xE3))) != 0
}

fn show_str(out: &mut String, t: &str) {
    out.push('「');
    let b = t.as_bytes();
    out.reserve(b.len() + 4);
    let mut start = 0;
    let mut i = 0;
    while i < b.len() {
        if i + 8 <= b.len() && !word_has_show_esc(u64::from_le_bytes(b[i..i + 8].try_into().unwrap())) {
            i += 8;
            continue;
        }
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

/// Показ скаляра (не списку й не словника) — як show(x, False).
fn show_leaf(out: &mut String, x: &V) {
    match &x.v {
        Val::Str(s) => show_str(out, &s.s),
        Val::None => out.push('∅'),
        Val::Bool(b) => out.push(if *b { '●' } else { '○' }),
        Val::Int(_) | Val::Dec(_) | Val::Float(_) => out.push_str(&fmt_num(&x.v)),
        Val::Fn(f) => {
            out.push('λ');
            if let Some(n) = &f.name {
                out.push_str(n);
            }
        }
        Val::List(_) | Val::Dict(_) => unreachable!(),
    }
}

fn show_into(out: &mut String, x: &V, d: usize) -> crate::interp::R<()> {
    match &x.v {
        Val::List(l) => {
            if d >= WALK {
                return deep();
            }
            out.push('【');
            for (i, e) in l.iter().enumerate() {
                if i > 0 {
                    out.push(' ');
                }
                show_into(out, e, d + 1)?;
            }
            out.push('】');
        }
        Val::Dict(dd) => {
            if d >= WALK {
                return deep();
            }
            out.push('『');
            for (i, (k, e)) in dd.keys.iter().zip(&dd.vals).enumerate() {
                if i > 0 {
                    out.push(' ');
                }
                show_str(out, &k.s);
                out.push(' ');
                show_into(out, e, d + 1)?;
            }
            out.push('』');
        }
        _ => show_leaf(out, x),
    }
    Ok(())
}

/// Друкована форма (рядок верхнього рівня — як є); глибше за WALK — deep().
pub fn show(x: &V, top: bool) -> crate::interp::R<String> {
    match (&x.v, top) {
        (Val::Str(s), true) => return Ok(s.s.to_string()),
        (Val::Int(_) | Val::Dec(_) | Val::Float(_), _) => return Ok(fmt_num(&x.v)), // те саме, що show_leaf, без копії
        _ => {}
    }
    let mut out = String::new();
    show_into(&mut out, x, 0)?;
    Ok(out)
}

/// show_head еталона: початок show(x, False) — щонайменше n символів (або весь) без обходу всього значення.
pub fn show_head(x: &V, n: usize) -> String {
    let mut out = String::new();
    let mut size = 0usize;
    let mut stack: Vec<(char, &V, usize)> = Vec::new(); // (закриття, список чи словник, наступний елемент)
    let mut e: Option<&V> = Some(x);
    loop {
        if let Some(cur) = e.take() {
            match &cur.v {
                Val::List(_) => {
                    out.push('【');
                    size += 1;
                    stack.push(('】', cur, 0));
                }
                Val::Dict(_) => {
                    out.push('『');
                    size += 1;
                    stack.push(('』', cur, 0));
                }
                _ => {
                    let at = out.len();
                    show_leaf(&mut out, cur);
                    size += out[at..].chars().count();
                }
            }
        }
        if size >= n {
            return out;
        }
        let top = match stack.last_mut() {
            Some(t) => t,
            None => return out,
        };
        let (close, cont, i) = (top.0, top.1, top.2);
        let len = match &cont.v {
            Val::List(l) => l.len(),
            Val::Dict(dd) => dd.len(),
            _ => 0,
        };
        if i >= len {
            stack.pop();
            out.push(close);
            size += 1;
            continue;
        }
        top.2 += 1;
        let at = out.len();
        if i > 0 {
            out.push(' ');
        }
        match &cont.v {
            Val::List(l) => e = Some(&l[i]),
            Val::Dict(dd) => {
                show_str(&mut out, &dd.keys[i].s);
                out.push(' ');
                e = Some(&dd.vals[i]);
            }
            _ => {}
        }
        size += out[at..].chars().count();
    }
}

fn to_json_into(out: &mut String, x: &V, d: usize) -> crate::interp::R<()> {
    match &x.v {
        Val::List(l) => {
            if d >= WALK {
                return deep();
            }
            out.push('[');
            for (i, e) in l.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                to_json_into(out, e, d + 1)?;
            }
            out.push(']');
        }
        Val::Dict(dd) => {
            if d >= WALK {
                return deep();
            }
            out.push('{');
            for (i, (k, e)) in dd.keys.iter().zip(&dd.vals).enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                json::escape_into(out, &k.s);
                out.push_str(": ");
                to_json_into(out, e, d + 1)?;
            }
            out.push('}');
        }
        Val::Dec(dd) => out.push_str(&fmt_dec(dd)),
        Val::Fn(_) => {
            // суд 12: не мовчазний рядок «λ», а помилка (місце — дає Δ)
            return Err(Box::new(crate::interp::E {
                msg: "Δ: функцію не записати в JSON".into(),
                pos: None,
                c: 1.0,
                wh: false,
                file: None,
                fatal: false,
                pipe: false,
                internal: false,
                deep: false,
            }));
        }
        Val::Str(s) => json::escape_into(out, &s.s),
        Val::None => out.push_str("null"),
        Val::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Val::Int(i) => out.push_str(&i.to_string()),
        Val::Float(f) => out.push_str(&json::dumps(&json::J::Float(*f), false)),
    }
    Ok(())
}

pub fn to_json(x: &V) -> crate::interp::R<String> {
    let mut out = String::new();
    to_json_into(&mut out, x, 0)?;
    Ok(out)
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

/// deep_eq еталона: той самий список чи словник — рівний без обходу; глибше за WALK — deep().
pub fn deep_eq(a: &V, b: &V) -> crate::interp::R<bool> {
    deep_eq_d(a, b, 0)
}

fn deep_eq_d(a: &V, b: &V, d: usize) -> crate::interp::R<bool> {
    Ok(match (&a.v, &b.v) {
        (Val::List(x), Val::List(y)) if Rc::ptr_eq(x, y) => true,
        (Val::Dict(x), Val::Dict(y)) if Rc::ptr_eq(x, y) => true,
        (Val::Bool(x), Val::Bool(y)) => x == y,
        (Val::Bool(_), _) | (_, Val::Bool(_)) => false,
        (Val::List(x), Val::List(y)) => {
            if d >= WALK {
                return deep();
            }
            if x.len() != y.len() {
                return Ok(false);
            }
            for (p, q) in x.iter().zip(y.iter()) {
                if !deep_eq_d(p, q, d + 1)? {
                    return Ok(false);
                }
            }
            true
        }
        (Val::Dict(x), Val::Dict(y)) => {
            if d >= WALK {
                return deep();
            }
            // спершу множини ключів (va.keys() == vb.keys()), потім значення в порядку першого
            if x.len() != y.len() || x.keys.iter().any(|k| y.find(&k.s).is_none()) {
                return Ok(false);
            }
            for (k, v) in x.keys.iter().zip(&x.vals) {
                if !deep_eq_d(v, y.get(&k.s).unwrap(), d + 1)? {
                    return Ok(false);
                }
            }
            true
        }
        (Val::Str(x), Val::Str(y)) => x.s == y.s,
        (Val::None, Val::None) => true,
        (Val::Fn(x), Val::Fn(y)) => Rc::ptr_eq(x, y),
        (x, y) if is_num(x) && is_num(y) => num_cmp(x, y) == Some(Ordering::Equal),
        _ => false,
    })
}

/// Значення для повідомлення: перші n символів показу (весь показ не будується — глибоке не заважає).
pub fn brief(x: &V, n: usize) -> String {
    let s = uni::safe(&show_head(x, n + 1));
    if s.chars().count() <= n {
        s
    } else {
        let mut t: String = s.chars().take(n).collect();
        t.push('…');
        t
    }
}
