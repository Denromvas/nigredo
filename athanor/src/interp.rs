//! Виконання — як nigredo.Interp: крок на вузол, ті самі межі, впевненість, канал завершення, слід.
use crate::ast::*;
use crate::dec::{self, Dec};
use crate::int::Int;
use crate::json::J;
use crate::lang;
use crate::lexer::{Lit, Pos};
use crate::pathx;
use crate::pyf;
use crate::rng::Mt;
use crate::trace::{trace_val, Trace, TraceErr};
use crate::uni;
use crate::value::*;
use std::cmp::Ordering;
use std::collections::HashMap;
use std::io::Write;
use std::rc::Rc;

#[derive(Debug)]
pub struct E {
    pub msg: String,
    pub pos: Option<Pos>,
    pub c: f64,
    pub wh: bool,
    pub file: Option<String>,
    pub fatal: bool,
    pub pipe: bool,
    pub internal: bool,
    pub deep: bool, // значення глибше за WALK (DeepValue еталона): місце виклику дає свою помилку
}

impl E {
    pub fn text(&self) -> String {
        let mut w = String::new();
        // file: None — ще не відомо, "" — код програми (λ програми, викликана з модуля, — місце в програмі, суд 10)
        if let Some(f) = self.file.as_ref().filter(|f| !f.is_empty()) {
            // локальний модуль, чий шлях схожий на адресу, — з «./» (огляд 10в; еталон: looks_like_address)
            if !f.contains("#sha256=") && !f.starts_with('/') && !f.starts_with('.') && addr_like(f) {
                w.push_str("./");
            }
            w.push_str(f);
            w.push(':');
        }
        if let Some((l, c)) = self.pos {
            w.push_str(&format!("{}:{} ", l, c));
        }
        format!("✗ {}{}", w, self.msg)
    }
}

/// Шлях схожий на адресу модуля з мережі: «github.com/» чи «raw.githubusercontent.com/» на початку чи після «/» (регістр
/// — лише ASCII), або «@» і рівно 40 hex, далі «/» чи кінець — як looks_like_address еталона (re.I | re.A).
fn addr_like(f: &str) -> bool {
    let b = f.as_bytes();
    for pre in [&b"github.com/"[..], &b"raw.githubusercontent.com/"[..]] {
        for i in 0..b.len() {
            if (i == 0 || b[i - 1] == b'/') && b.len() - i >= pre.len() && b[i..i + pre.len()].eq_ignore_ascii_case(pre) {
                return true;
            }
        }
    }
    for (i, &c) in b.iter().enumerate() {
        if c == b'@' {
            let hex = b[i + 1..].iter().take_while(|c| c.is_ascii_hexdigit()).count();
            if hex == 40 && (i + 41 == b.len() || b[i + 41] == b'/') {
                return true;
            }
        }
    }
    false
}

pub type R<T> = Result<T, Box<E>>;

/// Помилка в λ програми: місце — у програмі, а не в модулі, що її викликав (суд 10; еталон: e.file = '').
fn prog_file(mut e: Box<E>) -> Box<E> {
    if e.file.is_none() && !e.pipe && !e.internal {
        e.file = Some(String::new());
    }
    e
}

pub fn ngr<T>(msg: impl Into<String>, pos: Pos) -> R<T> {
    Err(Box::new(E { msg: msg.into(), pos: Some(pos), c: 1.0, wh: false, file: None, fatal: false, pipe: false, internal: false, deep: false }))
}

pub fn ngr_c<T>(msg: impl Into<String>, pos: Pos, c: f64) -> R<T> {
    Err(Box::new(E { msg: msg.into(), pos: Some(pos), c, wh: false, file: None, fatal: false, pipe: false, internal: false, deep: false }))
}

/// Вада еталона (виняток Python, не помилка мови) — у еталоні код 4; Атанор повторює те саме.
pub fn internal<T>(msg: impl Into<String>) -> R<T> {
    Err(Box::new(E { msg: msg.into(), pos: None, c: 1.0, wh: false, file: None, fatal: true, pipe: false, internal: true, deep: false }))
}

pub fn fatal<T>(msg: impl Into<String>, pos: Option<Pos>) -> R<T> {
    Err(Box::new(E { msg: msg.into(), pos, c: 1.0, wh: false, file: None, fatal: true, pipe: false, internal: false, deep: false }))
}

fn terr(e: TraceErr) -> Box<E> {
    match e {
        TraceErr::Fatal(m) => Box::new(E { msg: m, pos: None, c: 1.0, wh: false, file: None, fatal: true, pipe: false, internal: false, deep: false }),
        TraceErr::Io(m) => Box::new(E { msg: format!("слід: {}", m), pos: None, c: 1.0, wh: false, file: None, fatal: true, pipe: false, internal: false, deep: false }),
    }
}

pub fn has(set: &str, g: char) -> bool {
    set.contains(g)
}

pub struct Job {
    pub name: &'static str,
    pub args: Vec<V>,
    pub targs: Vec<J>,
    pub ac: f64,
    pub pos: Pos,
    pub agent: String,
    pub quota: Vec<(String, String, String)>,
    pub paths: Vec<String>,
}

pub struct QuotaTable {
    pub who: String,
    pub quotas: Vec<((String, String), u64)>,
    pub tok: String,
}

pub struct Interp {
    pub trace: Trace,
    pub rng: Mt,
    pub argv: Vec<String>,
    pub protected: Vec<String>,
    pub max_size: u64,
    pub alloc: u64,
    pub steps_left: i64,
    pub cwd: String,
    pub out: Box<dyn Write>,
    pub memory: HashMap<String, V>,
    pub agent: String,
    pub caps: Rc<Caps>,
    pub seal_caps: Rc<Caps>,
    pub pc: f64,
    pub halt_c: f64,
    pub mem_c: f64,
    pub try_stack: Vec<f64>,
    pub world_c: f64,
    pub decided_c: f64,
    pub depth: u64,
    pub wdepth: u64, // сумарна висота тіл активних викликів (MAX_WORK)
    pub ends: u64,
    pub quota_stack: Vec<Rc<QuotaTable>>,
    pub quota_used: HashMap<(String, String, String), u64>,
    pub quota_seq: u64,
    pub owner_home: String, // уже справжній шлях (realpath під час запуску)
    pub paths_seen: Option<Vec<String>>,
    pub rp_cache: HashMap<String, String>, // realpath тек із печатки: програма симлінків не створює (у proot stat дорогий)
    pub denied: bool,
    pub last_call: Option<(String, Vec<J>)>,
    pub modules: HashMap<String, Rc<Env>>,
    pub prof: Option<HashMap<String, (u64, std::time::Duration)>>,
    pub os_mode: Option<&'static str>, // замок ОС (фаза 6.1): «печатка» — закрити групи, яких печатка не просить; «усе»
    pub write_shut: bool, // ядро справді закрило «запис» (бд.читати: тимчасове — у памʼяті, чиста база WAL — незмінна; суд 11)
    pub dry: Option<Vec<(u64, &'static str, Vec<J>, f64, bool, Option<String>)>>, // --сухо: придушені дії (№, назва, аргументи, впевненість, запит не скомпілювався, що без виконання не перевірено)
    pub db_unchecked: bool, // права без дії: запит SQLite не скомпілювався на нинішній базі (огляд 0.8.1в)
    pub db_unverified: Option<String>, // права без дії: годинник SQLite з даних — без виконання не перевірити (суд 12)
}

impl Interp {
    pub fn prof_add(&mut self, k: &str, t: Option<std::time::Instant>) {
        if let (Some(p), Some(t)) = (self.prof.as_mut(), t) {
            let e = p.entry(k.to_string()).or_insert((0, std::time::Duration::ZERO));
            e.0 += 1;
            e.1 += t.elapsed();
        }
    }

    /// Мітка часу — лише під ATHANOR_PROFILE: під proot годинник — системний виклик, і `¿` у циклі витрачав на нього
    /// більше, ніж на саму роботу (суд 9б: 0,9 с системного часу на 2 млн кроків).
    #[inline]
    pub fn clock(&self) -> Option<std::time::Instant> {
        if self.prof.is_some() { Some(std::time::Instant::now()) } else { None }
    }
}

macro_rules! data {
    ($($k:expr => $v:expr),* $(,)?) => { vec![$(($k.to_string(), $v)),*] };
}

pub fn caps_json(c: &Caps) -> J {
    J::Obj(c.tools.iter().map(|(t, s)| (t.clone(), J::Arr(s.iter().map(|x| J::s(x)).collect()))).collect())
}

fn fj(f: f64) -> J {
    J::Float(f)
}

fn lit_val(l: &Lit) -> Val {
    match l {
        Lit::None => Val::None,
        Lit::Bool(b) => Val::Bool(*b),
        Lit::Int(i) => Val::Int(i.clone()),
        Lit::Dec(d) => Val::Dec(d.clone()),
        Lit::Str(s) => Val::Str(Rc::new(PStr::from(s))),
    }
}

/// Тип для τ (як у схемах ✓).
fn type_of(x: &V) -> &'static str {
    match kind(x) {
        "істинність" => "●/○",
        "ніщо" => "∅",
        k => k,
    }
}

fn env_up(env: &Rc<Env>, hops: u32) -> Option<&Env> {
    let mut e: &Env = env;
    for _ in 0..hops {
        e = e.parent.as_deref()?;
    }
    Some(e)
}

/// Вузол F_IDX (`§ імʼя ціле`): $body з $e — елементом, якщо імʼя — певний список певної будови, а номер у межах
/// (як швидкий § у strict_); інакше None. Макрос, а не функція із замиканням: на гарячому шляху — без викликів.
macro_rules! index_leaf {
    ($n:expr, $env:expr, |$e:ident| $body:expr) => {
        'leaf: {
            let K::Op(_, args) = &$n.k else { break 'leaf None };
            let (K::Var(_, hops, slot), Some(V { v: Val::Int(Int::S(i)), .. })) = (&args[0].k, &args[1].lv) else {
                break 'leaf None;
            };
            let Some(e0) = env_up($env, *hops) else { break 'leaf None };
            let vars = e0.vars.borrow();
            let Some(V { v: Val::List(l), c, s, .. }) = vars.get(*slot as usize) else { break 'leaf None };
            if *c < 1.0 || *s < 1.0 {
                break 'leaf None;
            }
            let len = l.len() as i64;
            if !(-len <= *i && *i < len) {
                break 'leaf None;
            }
            let $e = &l[if *i < 0 { (*i + len) as usize } else { *i as usize }];
            $body
        }
    };
}

impl Interp {
    #[inline]
    pub fn cpc(&self) -> f64 {
        self.pc.min(self.halt_c)
    }

    pub fn rec(&mut self, event: &str, data: Vec<(String, J)>) -> R<()> {
        let t = self.clock();
        let r = self.trace.rec(event, data).map_err(terr);
        self.prof_add("слід", t);
        r
    }

    #[inline]
    fn step(&mut self, pos: Pos) -> R<()> {
        self.steps_left -= 1;
        if self.steps_left < 0 {
            return fatal("перевищено ліміт кроків (--кроки)", Some(pos));
        }
        Ok(())
    }

    pub fn step_pub(&mut self, pos: Pos) -> R<()> {
        self.step(pos)
    }

    pub fn work(&mut self, units: u64, pos: Pos) -> R<()> {
        self.steps_left -= (units / 64) as i64;
        if self.steps_left < 0 {
            return fatal("перевищено ліміт кроків (--кроки)", Some(pos));
        }
        Ok(())
    }

    /// Межі розміру й облік створеного; g — гліф чи назва для повідомлення (char — без перекодування щоразу).
    /// Частий випадок — мале значення в межах — на місці: лише облік створеного (work(n < 64) — нуль кроків).
    #[inline(always)]
    fn sized(&mut self, res: V, g: impl std::fmt::Display, pos: Pos) -> R<V> {
        if res.n < 64 && res.n <= self.max_size && self.steps_left >= 0 && !matches!(res.v, Val::Int(Int::B(_))) {
            if res.n > 1 {
                self.alloc += res.n;
                if self.alloc > lang::ALLOC_FACTOR * self.max_size {
                    return fatal(format!("сумарно створено забагато ({} > {} × --розмір)", self.alloc, lang::ALLOC_FACTOR), Some(pos));
                }
            }
            return Ok(res);
        }
        self.sized_full(res, g, pos)
    }

    #[inline(never)]
    fn sized_full(&mut self, res: V, g: impl std::fmt::Display, pos: Pos) -> R<V> {
        if res.n > self.max_size {
            return fatal(format!("{}: значення завелике (логічний розмір {} > --розмір {})", g, res.n, self.max_size), Some(pos));
        }
        if let Val::Int(i) = &res.v {
            if i.bit_length() > lang::MAX_INT_BITS {
                return fatal(format!("{}: число завелике (понад {} біт)", g, lang::MAX_INT_BITS), Some(pos));
            }
        }
        if res.n > 1 {
            self.work(res.n, pos)?;
            self.alloc += res.n;
            if self.alloc > lang::ALLOC_FACTOR * self.max_size {
                return fatal(format!("сумарно створено забагато ({} > {} × --розмір)", self.alloc, lang::ALLOC_FACTOR), Some(pos));
            }
        }
        Ok(res)
    }

    pub fn taint(&mut self, c: f64) {
        if c < 1.0 {
            for t in self.try_stack.iter_mut() {
                if c < *t {
                    *t = c;
                }
            }
        }
    }

    fn halt_risk(&mut self, c: f64, nodes: &[&Node], called: bool) {
        if c < 1.0 && nodes.iter().any(|n| n.may_stop(called)) {
            self.halt_c = self.halt_c.min(c);
        }
    }

    /// halt_risk(c, ('op', pos, '☠', [])) — «могло впасти — і не впало».
    fn halt_risk_any(&mut self, c: f64) {
        if c < 1.0 {
            self.halt_c = self.halt_c.min(c);
        }
    }

    fn taint_effects(&mut self, nodes: &[&Node], c: f64) {
        if c >= 1.0 {
            return;
        }
        self.decided_c = self.decided_c.min(c);
        let eff = nodes.iter().fold(0u8, |a, n| a | n.eff);
        if eff & MEM != 0 {
            self.mem_c = self.mem_c.min(c);
        }
        if eff & WORLD != 0 {
            self.world_c = self.world_c.min(c);
        }
    }

    fn fn_effects(&mut self, node: &Node, c: f64) {
        if c < 1.0 && !node.is_lam() {
            self.decided_c = self.decided_c.min(c);
            self.mem_c = self.mem_c.min(c);
            self.world_c = self.world_c.min(c);
        } else {
            self.taint_effects(&[node], c);
        }
    }

    fn halt_cap(&mut self, env: &Rc<Env>, hops: u32, slot: u32, val: V, pos: Pos) -> R<V> {
        self.work(val.n, pos)?;
        let capped = capc(&val, self.halt_c);
        env.at(hops).vars.borrow_mut()[slot as usize] = capped.clone();
        Ok(capped)
    }

    /// Аргумент: літерал і імʼя — на місці (без повного виклику eval з його великим кадром), решта — eval.
    #[inline(always)]
    fn arg(&mut self, n: &Node, env: &Rc<Env>) -> R<V> {
        match &n.k {
            K::Lit(_) => self.eval_lit(n),
            K::Var(_, hops, slot) => self.eval_var(n.pos, env, *hops, *slot),
            _ => self.eval(n, env),
        }
    }

    #[inline(always)]
    fn eval_lit(&mut self, n: &Node) -> R<V> {
        self.step(n.pos)?;
        let mut v = n.lv.clone().unwrap();
        let c = self.cpc();
        v.c = c;
        v.s = c;
        Ok(v)
    }

    #[inline(always)]
    fn eval_var(&mut self, pos: Pos, env: &Rc<Env>, hops: u32, slot: u32) -> R<V> {
        self.step(pos)?;
        let val = env_get(env, hops, slot);
        let val = if self.halt_c < val.c { self.halt_cap(env, hops, slot, val, pos)? } else { val };
        if !self.try_stack.is_empty() {
            self.taint(val.c);
        }
        Ok(val)
    }

    pub fn eval(&mut self, n: &Node, env: &Rc<Env>) -> R<V> {
        let pos = n.pos;
        match &n.k {
            K::Lit(_) => self.eval_lit(n),
            K::Var(_, hops, slot) => self.eval_var(pos, env, *hops, *slot),
            K::Op(g, args) if !lang::is_lazy_glyphs(*g) => {
                if n.fast != 0 && self.pc >= 1.0 && self.halt_c >= 1.0 && self.steps_left >= n.ints as i64 {
                    if n.fast == F_TREE {
                        if self.max_size >= 22 {
                            if let Some(r) = self.int_tree(n, env) {
                                return Ok(r);
                            }
                        }
                    } else if let Some(e) = index_leaf!(n, env, |e| Some(e.clone())) {
                        // § імʼя ціле: ті самі три кроки (§, імʼя, номер) і sized елемента, що й eval_var + eval_lit +
                        // швидкий § у strict_ (певний список і будова, номер у межах) — без значень-посередників
                        self.steps_left -= 3;
                        return self.sized(e, '§', pos);
                    }
                }
                self.step(pos)?;
                let g = *g;
                let r = match args.len() {
                    1 => {
                        let a = [self.arg(&args[0], env)?];
                        self.strict(g, &a, pos)?
                    }
                    2 => {
                        let a0 = self.arg(&args[0], env)?;
                        let a1 = self.arg(&args[1], env)?;
                        let a = [a0, a1];
                        if let (Val::Int(_), Val::Int(_)) = (&a[0].v, &a[1].v) {
                            if let Some(r) = self.int_fast(g, &a, pos)? {
                                return Ok(r);
                            }
                        }
                        self.strict(g, &a, pos)?
                    }
                    3 => {
                        let a0 = self.arg(&args[0], env)?;
                        let a1 = self.arg(&args[1], env)?;
                        let a2 = self.arg(&args[2], env)?;
                        self.strict(g, &[a0, a1, a2], pos)?
                    }
                    _ => {
                        let mut a = Vec::with_capacity(args.len());
                        for x in args {
                            a.push(self.eval(x, env)?);
                        }
                        self.strict(g, &a, pos)?
                    }
                };
                self.sized(r, g, pos)
            }
            K::Call(_, hops, slot, args) => {
                self.step(pos)?;
                let f = env_get(env, *hops, *slot);
                let mut a = Vec::with_capacity(args.len());
                for x in args {
                    a.push(self.eval(x, env)?);
                }
                self.call(&f, a, pos)
            }
            _ => self.eval_node(n, env),
        }
    }

    /// Цілочислове дерево (Node::ints) певних малих цілих — одним проходом без значень-посередників: ті самі кроки
    /// (по одному на вузол), той самий облік створеного (alloc), що й eval + int_fast вузол за вузлом. Будь-що інше
    /// (невпевнене, велике, переповнення, ‰ 0, межа alloc) — None, і вузол рахує звичайний eval (тут нічого не змінено).
    /// Листок `§ імʼя ціле` — те саме, що eval + швидкий § у strict_ + sized: певний список (і будова), номер у межах,
    /// елемент — певне мале ціле; sized елемента додає його розмір до alloc (n ≤ 22 ≤ --розмір: work — нуль кроків).
    #[inline(always)]
    fn int_tree(&mut self, n: &Node, env: &Rc<Env>) -> Option<V> {
        // операнд: листок — на місці, операція — go (виклик лише на внутрішній вузол, не на кожен)
        #[inline(always)]
        fn arg(n: &Node, env: &Rc<Env>, alloc: &mut u64) -> Option<i64> {
            match &n.k {
                K::Lit(_) => match &n.lv {
                    Some(V { v: Val::Int(Int::S(x)), .. }) => Some(*x),
                    _ => None,
                },
                K::Var(_, hops, slot) => match env_up(env, *hops)?.vars.borrow().get(*slot as usize)? {
                    V { v: Val::Int(Int::S(x)), c, .. } if *c >= 1.0 => Some(*x),
                    _ => None,
                },
                K::Op('§', _) => index_leaf!(n, env, |e| match e {
                    V { v: Val::Int(Int::S(x)), c, n, .. } if *c >= 1.0 && *n <= 22 => {
                        if *n > 1 {
                            *alloc += *n;
                        }
                        Some(*x)
                    }
                    _ => None,
                }),
                _ => go(n, env, alloc),
            }
        }
        fn go(n: &Node, env: &Rc<Env>, alloc: &mut u64) -> Option<i64> {
            let K::Op(g, args) = &n.k else { return None };
            let x = arg(&args[0], env, alloc)?;
            let y = arg(&args[1], env, alloc)?;
            let r = match g {
                '＋' => x.checked_add(y)?,
                '－' => x.checked_sub(y)?,
                '×' => x.checked_mul(y)?,
                _ => {
                    let r = x.checked_rem(y)?;
                    if r != 0 && ((r < 0) != (y < 0)) { r + y } else { r }
                }
            };
            let nn = 1 + (64 - r.unsigned_abs().leading_zeros() as u64) / 3;
            if nn > 1 {
                *alloc += nn;
            }
            Some(r)
        }
        let mut alloc = 0u64;
        let res = if n.icmp {
            let K::Op(g, args) = &n.k else { return None };
            let x = arg(&args[0], env, &mut alloc)?;
            let y = arg(&args[1], env, &mut alloc)?;
            V::b(match g {
                '‹' => x < y,
                '›' => x > y,
                '≤' => x <= y,
                '≥' => x >= y,
                '＝' => x == y,
                _ => x != y,
            })
        } else {
            let r = go(n, env, &mut alloc)?;
            V { v: Val::Int(Int::S(r)), c: 1.0, s: 1.0, n: 1 + (64 - r.unsigned_abs().leading_zeros() as u64) / 3 }
        };
        if self.alloc + alloc > lang::ALLOC_FACTOR * self.max_size {
            return None;
        }
        self.alloc += alloc;
        self.steps_left -= n.ints as i64;
        Some(res)
    }

    /// Швидкий шлях певних цілих (компільований вузол еталона).
    fn int_fast(&mut self, g: char, a: &[V], pos: Pos) -> R<Option<V>> {
        let (x, y) = match (&a[0].v, &a[1].v) {
            (Val::Int(x), Val::Int(y)) => (x, y),
            _ => return Ok(None),
        };
        if !matches!(g, '＋' | '－' | '×' | '‰' | '‹' | '›' | '≤' | '≥' | '＝' | '≠') {
            return Ok(None);
        }
        if !(a[0].c >= 1.0 && a[1].c >= 1.0 && self.pc >= 1.0 && self.halt_c >= 1.0) {
            return Ok(None);
        }
        if g == '‰' && y.is_zero() {
            return Ok(None);
        }
        if g == '×' && x.bit_length() + y.bit_length() > lang::MAX_INT_BITS {
            return Ok(None);
        }
        if lang::is_heavy(g) {
            self.work(a[0].n + a[1].n, pos)?;
        }
        let r = match g {
            '＋' => x.add(y),
            '－' => x.sub(y),
            '×' => x.mul(y),
            '‰' => x.divmod(y).1,
            '‹' => return Ok(Some(V::b(x.cmp(y) == Ordering::Less))),
            '›' => return Ok(Some(V::b(x.cmp(y) == Ordering::Greater))),
            '≤' => return Ok(Some(V::b(x.cmp(y) != Ordering::Greater))),
            '≥' => return Ok(Some(V::b(x.cmp(y) != Ordering::Less))),
            '＝' => return Ok(Some(V::b(x.cmp(y) == Ordering::Equal))),
            _ => return Ok(Some(V::b(x.cmp(y) != Ordering::Equal))),
        };
        let bl = r.bit_length();
        if bl > lang::MAX_INT_BITS {
            return fatal(format!("{}: число завелике (понад {} біт)", g, lang::MAX_INT_BITS), Some(pos));
        }
        let res = V { v: Val::Int(r), c: 1.0, s: 1.0, n: 1 + bl / 3 };
        if res.n > self.max_size {
            return fatal(format!("{}: значення завелике (логічний розмір {} > --розмір {})", g, res.n, self.max_size), Some(pos));
        }
        if res.n > 1 {
            self.alloc += res.n;
            if res.n >= 64 {
                self.work(res.n, pos)?;
            }
            if self.alloc > lang::ALLOC_FACTOR * self.max_size {
                return fatal(format!("сумарно створено забагато ({} > {} × --розмір)", self.alloc, lang::ALLOC_FACTOR), Some(pos));
            }
        }
        Ok(Some(res))
    }

    fn eval_node(&mut self, n: &Node, env: &Rc<Env>) -> R<V> {
        let pos = n.pos;
        self.step(pos)?;
        match &n.k {
            K::List(xs) => {
                let mut items = Vec::with_capacity(xs.len());
                for x in xs {
                    items.push(self.eval(x, env)?);
                }
                let c = self.cpc();
                self.sized(mk(items, c), "【】", pos)
            }
            K::Tmpl(parts) => {
                let mut vals = Vec::with_capacity(parts.len());
                for p in parts {
                    match p {
                        TPart::Text(p2, s) => {
                            self.step(*p2)?;
                            vals.push(V::new(Val::Str(Rc::new(PStr::from(s))), self.cpc()));
                        }
                        TPart::Hole(_, e) => vals.push(self.eval(e, env)?),
                    }
                }
                let total: u64 = vals.iter().map(|v| v.n).sum();
                if total > self.max_size {
                    return fatal(format!("〔〕: значення завелике (> --розмір {})", self.max_size), Some(pos));
                }
                self.work(total, pos)?;
                let c = vals.iter().fold(self.cpc(), |a, v| a.min(v.c));
                let mut s = String::new();
                for v in &vals {
                    match show(v, true) {
                        Ok(t) => s.push_str(&t),
                        Err(e) if e.deep => return ngr_c("〔〕: значення вкладене надто глибоко", pos, c),
                        Err(e) => return Err(e),
                    }
                }
                Ok(V::strc(s, c))
            }
            K::Dict(items) => {
                let mut d = Dict::new();
                let (mut c, mut sc) = (self.cpc(), self.cpc());
                let mut i = 0;
                while i < items.len() {
                    let key = self.eval(&items[i], env)?;
                    let ks = match &key.v {
                        Val::Str(s) => s.clone(),
                        _ => return ngr_c("ключ словника має бути рядком", items[i].pos, key.c.min(self.cpc())),
                    };
                    if d.find(&ks.s).is_some() {
                        return ngr_c(format!("у словнику 『』 ключ «{}» двічі", uni::safe(&ks.s)), items[i].pos, key.c.min(self.cpc()));
                    }
                    let val = self.eval(&items[i + 1], env)?;
                    c = c.min(key.c).min(val.c);
                    sc = sc.min(key.c);
                    d.set(ks, val);
                    i += 2;
                }
                self.sized(V::cs(Val::Dict(Rc::new(d)), c, sc), "『』", pos)
            }
            K::Block(stmts, nslots) => {
                let inner = Env::new(*nslots as usize, Some(env.clone()));
                let mut result = V::none();
                for s in stmts {
                    result = self.eval(s, &inner)?;
                }
                Ok(result)
            }
            K::Bind(name, slot, value) => {
                if let K::Lam(l) = &value.k {
                    let f = V::new(Val::Fn(Rc::new(Func { lam: l.clone(), env: env.clone(), name: Some(name.clone()), module: env.module.clone() })), self.cpc());
                    env.vars.borrow_mut()[*slot as usize] = f.clone();
                    return Ok(f);
                }
                let val = self.eval(value, env)?;
                env.vars.borrow_mut()[*slot as usize] = val.clone();
                Ok(val)
            }
            K::Lam(l) => Ok(V::new(Val::Fn(Rc::new(Func { lam: l.clone(), env: env.clone(), name: None, module: env.module.clone() })), self.cpc())),
            K::Seal(intent, caps) => {
                self.caps = caps.clone();
                self.seal_caps = caps.clone();
                if !caps.quotas.is_empty() {
                    self.quota_stack.push(Rc::new(QuotaTable {
                        who: "печатка".into(),
                        quotas: caps.quotas.clone(),
                        tok: "печатка".into(),
                    }));
                }
                let agent = self.agent.clone();
                self.rec("печатка", data!["агент" => J::Str(agent), "намір" => J::s(intent), "дозволи" => caps_json(caps)])?;
                if let Some(m) = self.os_mode.take() {
                    // замок ОС — раз, на печатці програми (фаза 6.1; еталон: os_lock)
                    let closed = if m == "усе" { crate::lang::OS_GROUPS.to_vec() } else { crate::oslock::closed(caps) };
                    let d = crate::oslock::lock(&closed);
                    self.write_shut = closed.contains(&"запис")
                        && d.iter().any(|(k, v)| k == "ядро" && matches!(v, J::Str(s) if s == "seccomp"));
                    self.rec("ізоляція", d)?;
                }
                Ok(V::none())
            }
            K::Tool(name, args) => {
                let mut a = Vec::with_capacity(args.len());
                for x in args {
                    a.push(self.eval(x, env)?);
                }
                let job = self.tool_begin(name, a, pos)?;
                let outcome = self.tool_do(&job);
                self.tool_end(job, outcome)
            }
            K::Deleg(..) => self.delegate(n, env),
            K::Import(m) => {
                let menv = match self.modules.get(&m.real) {
                    Some(e) => e.clone(),
                    None => {
                        let agent = self.agent.clone();
                        self.rec(
                            "модуль",
                            data!["агент" => J::Str(agent), "шлях" => J::Str(uni::safe(&m.rel)), "файл" => J::Str(uni::safe(&m.real)),
                                  "sha256" => J::s(&m.sha), "дозволи" => caps_json(&m.module.caps)],
                        )?;
                        let info = Rc::new(ModInfo { rel: uni::safe(&pathx::relpath(&m.real, &self.cwd)), caps: m.module.caps.clone() });
                        let rel = info.rel.clone();
                        let menv = Rc::new(Env { vars: std::cell::RefCell::new(vec![V::none(); m.module.nslots as usize]), parent: None, module: Some(info) });
                        self.modules.insert(m.real.clone(), menv.clone());
                        if let K::Block(stmts, _) = &m.module.prog.k {
                            for st in &stmts[1..] {
                                // сталі модуля (§ поза межами…): місце — у модулі, а не в програмі (огляд 10б)
                                self.eval(st, &menv).map_err(|mut e| {
                                    if e.file.is_none() && !e.pipe && !e.internal {
                                        e.file = Some(rel.clone());
                                    }
                                    e
                                })?;
                            }
                        }
                        menv
                    }
                };
                for (_, mslot, slot) in &m.names {
                    let v = menv.vars.borrow()[*mslot as usize].clone();
                    env.vars.borrow_mut()[*slot as usize] = v;
                }
                Ok(V::none())
            }
            K::Op(g, args) => {
                let t = self.clock();
                let r = self.lazy_op(*g, args, env, pos);
                if self.prof.is_some() {
                    self.prof_add(&format!("лінивий {}", g), t);
                }
                let r = r?;
                self.sized(r, g, pos)
            }
            K::Lit(_) | K::Var(..) | K::Call(..) => unreachable!(),
        }
    }

    /// Межа глибини (too_deep еталона): 2000 викликів чи MAX_WORK — сума висот тіл активних викликів (суд 9б).
    fn enter(&mut self, h: u64, pos: Pos) -> R<()> {
        self.depth += 1;
        self.wdepth += h;
        if self.depth > lang::MAX_DEPTH || self.wdepth > lang::MAX_WORK {
            let msg = if self.depth > lang::MAX_DEPTH {
                "надто глибока рекурсія".to_string()
            } else {
                format!("надто глибока рекурсія: виклики × вкладеність їхнього коду — понад {} рівнів", lang::MAX_WORK)
            };
            self.depth -= 1;
            self.wdepth -= h;
            return fatal(msg, Some(pos));
        }
        Ok(())
    }

    fn leave(&mut self, h: u64) {
        self.depth -= 1;
        self.wdepth -= h;
    }

    /// Швидкий шлях call для λ з одним параметром у вже створеному середовищі (↻): ті самі глибина й межа.
    fn call_in(&mut self, func: &Rc<Func>, env: &Rc<Env>, arg: V, pos: Pos) -> R<V> {
        self.enter(func.lam.height, pos)?;
        env.vars.borrow_mut()[0] = arg;
        let r = self.eval(&func.lam.body, env).map_err(prog_file);
        self.leave(func.lam.height);
        r
    }

    pub fn call(&mut self, f: &V, args: Vec<V>, pos: Pos) -> R<V> {
        let func = match &f.v {
            Val::Fn(func) => func.clone(),
            _ => return ngr_c(format!("очікувалася функція, а не {}", kind(f)), pos, f.c.min(self.cpc())),
        };
        let lam = &func.lam;
        if lam.params.len() != args.len() {
            return ngr_c(
                format!("функція чекає {} аргумент(и), а дано {}", lam.params.len(), args.len()),
                pos,
                f.c.min(self.cpc()),
            );
        }
        self.enter(lam.height, pos)?;
        if f.c >= 1.0 && lam.simple && func.module.is_none() {
            let env = Env::child(args, &func.env);
            let r = self.eval(&lam.body, &env).map_err(prog_file);
            self.leave(lam.height);
            return r;
        }
        let saved = self.pc;
        self.pc = saved.min(f.c);
        self.taint(f.c);
        if f.c < 1.0 {
            self.taint_effects(&[&lam.body], f.c);
            self.halt_risk(f.c, &[&lam.body], false);
        }
        let saved_caps = self.caps.clone();
        let mut mod_q = false;
        if let Some(m) = &func.module {
            // печатка модуля діє: права — перетин прав агента й печатки модуля
            self.caps = Rc::new(intersect_caps(&self.caps, &m.caps, &self.cwd));
            if !m.caps.quotas.is_empty() {
                mod_q = true;
                self.quota_stack.push(Rc::new(QuotaTable {
                    who: format!("модуль {}", m.rel),
                    quotas: m.caps.quotas.clone(),
                    tok: format!("модуль@{:p}", Rc::as_ptr(&m.caps)),
                }));
            }
        }
        let r = (|| -> R<V> {
            let mut vars = Vec::with_capacity(lam.nslots);
            for (p, a) in lam.params.iter().zip(args) {
                match p {
                    Param::Pat(_, names) => {
                        let ok = matches!(&a.v, Val::List(l) if l.len() == names.len());
                        if !ok {
                            let what: Vec<&str> = names.iter().map(|x| &**x).collect();
                            return ngr_c(
                                format!(
                                    "розбір 【{}】: очікувався список із {} елементів, а не {} {}",
                                    what.join(" "),
                                    names.len(),
                                    kind(&a),
                                    brief(&a, 40)
                                ),
                                pos,
                                a.c.min(a.s),
                            );
                        }
                        if let Val::List(l) = &a.v {
                            for e in l.iter() {
                                vars.push(if a.s < e.c { capc(e, a.s) } else { e.clone() });
                            }
                        }
                        if a.c.min(a.s) < 1.0 {
                            self.halt_risk_any(a.c.min(a.s));
                        }
                    }
                    Param::Name(_) => vars.push(a),
                }
            }
            let env = Env::child(vars, &func.env);
            let res = self.eval(&lam.body, &env)?;
            Ok(if f.c < res.c { capc(&res, f.c) } else { res })
        })();
        let r = match (r, &func.module) {
            (Err(mut e), Some(m)) if e.file.is_none() && !e.pipe && !e.internal => {
                e.file = Some(m.rel.clone());
                Err(e)
            }
            (r, None) => r.map_err(prog_file),
            (r, _) => r,
        };
        if mod_q {
            self.quota_stack.pop();
        }
        self.caps = saved_caps;
        self.pc = saved;
        self.leave(lam.height);
        r
    }

    fn need_str<'a>(&self, x: &'a V, g: &str, pos: Pos) -> R<&'a Rc<PStr>> {
        match &x.v {
            Val::Str(s) => Ok(s),
            _ => ngr(format!("{}: очікувалося рядок, а не {} {}", g, kind(x), brief(x, 40)), pos),
        }
    }

    fn need_list<'a>(&self, x: &'a V, g: &str, pos: Pos) -> R<&'a Rc<List>> {
        match &x.v {
            Val::List(l) => Ok(l),
            _ => ngr(format!("{}: очікувалося список, а не {} {}", g, kind(x), brief(x, 40)), pos),
        }
    }

    fn need_dict<'a>(&self, x: &'a V, g: &str, pos: Pos) -> R<&'a Rc<Dict>> {
        match &x.v {
            Val::Dict(d) => Ok(d),
            _ => ngr(format!("{}: очікувалося словник, а не {} {}", g, kind(x), brief(x, 40)), pos),
        }
    }

    fn boolean(&self, x: &V, g: char, pos: Pos) -> R<bool> {
        match x.v {
            Val::Bool(b) => Ok(b),
            _ => ngr(format!("{}: умова має бути ● або ○, а не {} {}", g, kind(x), brief(x, 40)), pos),
        }
    }

    /// num(): ціле або десяткове; float — Decimal(repr).
    fn num(&self, x: &V, g: char, pos: Pos) -> R<Val> {
        match &x.v {
            Val::Int(_) | Val::Dec(_) => Ok(x.v.clone()),
            Val::Float(f) => Ok(Val::Dec(Rc::new(Dec::parse(&pyf::repr(*f)).unwrap()))),
            _ => ngr(format!("{}: очікувалося число, а не {} {}", g, kind(x), brief(x, 40)), pos),
        }
    }

    fn seq(&self, x: &V, g: char, pos: Pos) -> R<Rc<List>> {
        match &x.v {
            Val::List(l) => Ok(l.clone()),
            Val::Str(s) => Ok(Rc::new(s.s.chars().map(|ch| V::strc(ch.to_string(), x.c)).collect())),
            _ => ngr_c(format!("{}: очікувався список або рядок, а не {}", g, kind(x)), pos, x.c.min(self.cpc())),
        }
    }

    fn each(&mut self, g: char, i: usize, f: &V, args: Vec<V>, pos: Pos) -> R<V> {
        match self.call(f, args, pos) {
            Err(mut e) if !e.fatal => {
                if !e.wh {
                    e.msg = format!("{}, елемент №{} (§ {}): {}", g, i + 1, i, e.msg);
                    e.wh = true;
                }
                Err(e)
            }
            r => r,
        }
    }

    /// f для кожного елемента (з acc — згортка Σ: повертає [acc]). Швидкий шлях — одне середовище на весь цикл, коли
    /// функція певна, з простими параметрами і без λ/🜁 у тілі (середовище не може пережити виклик): те саме, що
    /// call() для кожного, без створення середовища щоразу.
    fn each_all(&mut self, g: char, items: &Items, f: &V, acc: Option<V>, pos: Pos) -> R<Vec<V>> {
        if acc.is_some() {
            return Ok(vec![self.each_sink(g, items, f, acc, pos, &mut |_, _| ())?.unwrap()]);
        }
        let mut out = Vec::with_capacity(items.len());
        self.each_sink(g, items, f, None, pos, &mut |_, r| out.push(r))?;
        Ok(out)
    }

    /// Те саме, але кожен результат — одразу в sink (∀ не тримає результатів, ∫ сумує на ходу); з acc — підсумок.
    fn each_sink(&mut self, g: char, items: &Items, f: &V, acc: Option<V>, pos: Pos, sink: &mut dyn FnMut(&mut Interp, V)) -> R<Option<V>> {
        let n = items.len();
        let want = if acc.is_some() { 2 } else { 1 };
        let fast = match &f.v {
            Val::Fn(func) if f.c >= 1.0 && func.lam.simple && func.module.is_none() && !func.lam.escapes && func.lam.params.len() == want => Some(func.clone()),
            _ => None,
        };
        let wrap = |mut e: Box<E>, i: usize| -> Box<E> {
            if !e.fatal && !e.wh {
                e.msg = format!("{}, елемент №{} (§ {}): {}", g, i + 1, i, e.msg);
                e.wh = true;
            }
            e
        };
        match (fast, acc) {
            (Some(func), None) => {
                if matches!(func.lam.body.k, K::Var(_, 0, 0)) && self.halt_c >= 1.0 && self.try_stack.is_empty() {
                    // λx x: результат — сам елемент (той самий крок на імʼя, та сама межа глибини)
                    for i in 0..n {
                        self.enter(func.lam.height, pos)?;
                        self.leave(func.lam.height);
                        self.step(func.lam.body.pos)?;
                        sink(self, items.get(i));
                    }
                    return Ok(None);
                }
                let env1 = Env::child(vec![V::none()], &func.env);
                for i in 0..n {
                    let x = items.get(i);
                    self.enter(func.lam.height, pos)?;
                    env1.vars.borrow_mut()[0] = x;
                    let r = self.eval(&func.lam.body, &env1);
                    self.leave(func.lam.height);
                    let r = r.map_err(|e| wrap(e, i))?;
                    sink(self, r);
                }
                Ok(None)
            }
            (Some(func), Some(mut acc)) => {
                let env1 = Env::child(vec![V::none(), V::none()], &func.env);
                for i in 0..n {
                    let x = items.get(i);
                    self.enter(func.lam.height, pos)?;
                    {
                        let mut v = env1.vars.borrow_mut();
                        v[0] = acc;
                        v[1] = x;
                    }
                    let r = self.eval(&func.lam.body, &env1);
                    self.leave(func.lam.height);
                    acc = r.map_err(|e| wrap(e, i))?;
                }
                Ok(Some(acc))
            }
            (None, None) => {
                for i in 0..n {
                    let r = self.each(g, i, f, vec![items.get(i)], pos)?;
                    sink(self, r);
                }
                Ok(None)
            }
            (None, Some(mut acc)) => {
                for i in 0..n {
                    acc = self.each(g, i, f, vec![acc.clone(), items.get(i)], pos)?;
                }
                Ok(Some(acc))
            }
        }
    }

    /// Список для циклу. `… a b` з малими цілими — без створення списку: ті самі кроки, межі, впевненість, що й
    /// у eval(Op …) + strict + sized, а елементи — на льоту (Items::Range).
    fn eval_list_arg(&mut self, n: &Node, env: &Rc<Env>) -> R<(V, Option<Items>)> {
        let args = match &n.k {
            K::Op('…', args) => args,
            _ => return Ok((self.eval(n, env)?, None)),
        };
        let pos = n.pos;
        self.step(pos)?;
        let a0 = self.eval(&args[0], env)?;
        let a1 = self.eval(&args[1], env)?;
        let (x, y) = match (&a0.v, &a1.v) {
            (Val::Int(Int::S(x)), Val::Int(Int::S(y))) if self.prof.is_none() => (*x, *y),
            _ => {
                let r = self.strict('…', &[a0, a1], pos)?;
                return Ok((self.sized(r, "…", pos)?, None));
            }
        };
        let amin = 1.0f64.min(a0.c).min(a1.c);
        self.taint(amin);
        let cnt = y as i128 - x as i128 + 1;
        if cnt > self.max_size as i128 {
            return fatal(format!("…: ряд завеликий ({} > --розмір {})", cnt, self.max_size), Some(pos));
        }
        let len = if cnt > 0 { cnt as usize } else { 0 };
        let ce = a0.c.min(a1.c);
        let n_list = 1 + len as u64 + range_bl3(x, len);
        if amin < 1.0 {
            self.halt_risk_any(amin);
        }
        let c2 = ce.min(amin).min(self.cpc());
        let meta = V { v: Val::None, c: ce.min(c2), s: ce.min(a0.s).min(a1.s), n: n_list };
        if n_list > self.max_size {
            return fatal(format!("…: значення завелике (логічний розмір {} > --розмір {})", n_list, self.max_size), Some(pos));
        }
        if n_list > 1 {
            self.work(n_list, pos)?;
            self.alloc += n_list;
            if self.alloc > lang::ALLOC_FACTOR * self.max_size {
                return fatal(format!("сумарно створено забагато ({} > {} × --розмір)", self.alloc, lang::ALLOC_FACTOR), Some(pos));
            }
        }
        Ok((meta, Some(Items::Range { start: x, len, c: ce })))
    }

    fn lazy_op(&mut self, g: char, argn: &[Node], env: &Rc<Env>, pos: Pos) -> R<V> {
        match g {
            '¿' => {
                let c = self.eval(&argn[0], env)?;
                self.taint(c.c);
                let saved = self.pc;
                self.pc = saved.min(c.c);
                let r = (|| -> R<V> {
                    if self.boolean(&c, g, pos)? { self.eval(&argn[1], env) } else { self.eval(&argn[2], env) }
                })();
                self.pc = saved;
                let branch = r?;
                self.taint_effects(&[&argn[1], &argn[2]], c.c);
                self.halt_risk(c.c, &[&argn[1], &argn[2]], false);
                if c.c < 1.0 && matches!(branch.v, Val::Fn(_)) {
                    self.halt_c = self.halt_c.min(c.c);
                }
                if c.c < branch.c {
                    self.work(branch.n, pos)?;
                    return Ok(capc(&branch, c.c.min(branch.c)));
                }
                Ok(branch)
            }
            '∧' | '∨' => {
                let c = self.eval(&argn[0], env)?;
                self.taint(c.c);
                let p = self.boolean(&c, g, pos)?;
                let saved = self.pc;
                self.pc = saved.min(c.c);
                let r = (|| -> R<V> {
                    if p == (g == '∧') {
                        let res = self.eval(&argn[1], env)?;
                        self.boolean(&res, g, pos)?;
                        Ok(res)
                    } else {
                        Ok(V::new(Val::Bool(p), self.cpc()))
                    }
                })();
                self.pc = saved;
                let res = r?;
                self.taint_effects(&[&argn[1]], c.c);
                self.halt_risk(c.c, &[&argn[1]], false);
                Ok(if c.c < res.c { capc(&res, c.c) } else { res })
            }
            '☂' => {
                if !argn[1].is_lam() {
                    let h = self.eval(&argn[1], env)?;
                    if !matches!(h.v, Val::Fn(_)) {
                        return ngr(format!("☂: обробник має бути функцією (λe …), а не {}", kind(&h)), pos);
                    }
                }
                let cpc = self.cpc();
                self.try_stack.push(cpc);
                match self.eval(&argn[0], env) {
                    Ok(res) => {
                        let tc = self.try_stack.pop().unwrap();
                        self.taint_effects(&[&argn[0]], tc);
                        self.fn_effects(&argn[1], tc);
                        Ok(if tc < res.c { capc(&res, tc) } else { res })
                    }
                    Err(e) if e.fatal => Err(e),
                    Err(e) => {
                        let tc = self.try_stack.pop().unwrap().min(e.c);
                        self.taint_effects(&[&argn[0]], tc);
                        self.fn_effects(&argn[1], tc);
                        let agent = self.agent.clone();
                        self.rec("помилку перехоплено", data!["агент" => J::Str(agent), "помилка" => J::Str(e.msg.clone()), "впевненість" => fj(tc)])?;
                        let saved = self.pc;
                        self.pc = saved.min(tc);
                        let r = (|| -> R<V> {
                            let h = self.eval(&argn[1], env)?;
                            self.call(&h, vec![V::strc(e.msg.clone(), tc)], pos)
                        })();
                        self.pc = saved;
                        let res = r?;
                        Ok(if tc < res.c { capc(&res, tc) } else { res })
                    }
                }
            }
            '∀' | 'μ' | 'φ' | '⇅' | '⊞' | '∫' | '№' => {
                let (lst, range) = self.eval_list_arg(&argn[0], env)?;
                self.taint(lst.c);
                let items = match range {
                    Some(r) => r,
                    None => Items::List(self.seq(&lst, g, pos)?),
                };
                let f = self.eval(&argn[1], env)?;
                let saved = self.pc;
                self.pc = saved.min(lst.s);
                if g == '∀' || g == '∫' || g == '№' {
                    // результати не тримаємо: ∀ їх відкидає, ∫ сумує, № лічить на ходу; помилку (не число, 60 цифр,
                    // ключ не рядок) — лише після всіх викликів, як в еталоні (спершу всі виклики, потім підсумок)
                    let (mut total, mut m, mut bad): (Val, f64, Option<Box<E>>) = (Val::Int(Int::S(0)), lst.s, None);
                    let mut counts: Vec<(Rc<PStr>, i64)> = Vec::new();
                    let mut idx: FxMap<Rc<str>, usize> = FxMap::default();
                    let r = self.each_sink(g, &items, &f, None, pos, &mut |it, r| {
                        if g == '№' {
                            m = m.min(r.c);
                            if bad.is_some() {
                                return;
                            }
                            match &r.v {
                                Val::Str(k) => match idx.get(&*k.s) {
                                    Some(&i) => counts[i].1 += 1,
                                    None => {
                                        idx.insert(Rc::from(&*k.s), counts.len());
                                        counts.push((k.clone(), 1));
                                    }
                                },
                                _ => bad = ngr::<()>(format!("№ (ключ): очікувалося рядок, а не {} {}", kind(&r), brief(&r, 40)), pos).err(),
                            }
                        } else if g == '∫' {
                            m = m.min(r.c);
                            if let (Val::Int(Int::S(t)), Val::Int(Int::S(x))) = (&total, &r.v) {
                                if let Some(t2) = t.checked_add(*x) {
                                    total = Val::Int(Int::S(t2));
                                    return;
                                }
                            }
                            if bad.is_none() {
                                match it.num(&r, '∫', pos).and_then(|v| it.exact('＋', &total, &v, '∫', pos)) {
                                    Ok(t) => total = t,
                                    Err(e) => bad = Some(e),
                                }
                            }
                        }
                    });
                    self.pc = saved;
                    r?;
                    self.fn_effects(&argn[1], lst.s);
                    self.halt_risk(lst.s, &[&argn[1]], true);
                    if g == '∀' {
                        return Ok(V::none_c(self.cpc().min(lst.s)));
                    }
                    self.taint(m);
                    if let Some(e) = bad {
                        return Err(e);
                    }
                    if g == '№' {
                        let mut d = Dict::new();
                        for (k, n) in counts {
                            d.set(k, V::new(Val::Int(Int::S(n)), m));
                        }
                        return Ok(V::cs(Val::Dict(Rc::new(d)), m, m));
                    }
                    self.halt_risk_any(m);
                    return Ok(V::new(total, m));
                }
                let r = self.each_all(g, &items, &f, None, pos);
                self.pc = saved;
                let results = r?;
                self.fn_effects(&argn[1], lst.s);
                self.halt_risk(lst.s, &[&argn[1]], true);
                if g == 'μ' {
                    return Ok(mk(results, lst.s));
                }
                let m = results.iter().fold(lst.s, |a, r| a.min(r.c));
                self.taint(m);
                match g {
                    'φ' => {
                        let mut kept = Vec::new();
                        let mut conds = Vec::with_capacity(results.len());
                        for r in &results {
                            conds.push(self.boolean(r, g, pos)?);
                        }
                        for (i, (r, ok)) in results.iter().zip(conds).enumerate() {
                            if ok {
                                let x = items.get(i);
                                kept.push(if r.c < x.c { capc(&x, r.c) } else { x });
                            }
                        }
                        Ok(mk(kept, m))
                    }
                    '⇅' => {
                        let order = match crate::sort::sort_order(&results, pos) {
                            Ok(o) => o,
                            Err(e) if e.deep => return ngr_c("⇅: ключі вкладені надто глибоко", pos, m),
                            Err(e) => return Err(e),
                        };
                        Ok(mk(order.into_iter().map(|i| items.get(i)).collect(), m))
                    }
                    _ => {
                        // ⊞
                        let mut groups: Vec<(Rc<PStr>, Vec<V>)> = Vec::new();
                        let mut idx: FxMap<Rc<str>, usize> = FxMap::default();
                        for (i, r) in results.iter().enumerate() {
                            let x = items.get(i);
                            let k = match &r.v {
                                Val::Str(s) => s.clone(),
                                _ => return ngr(format!("⊞ (ключ): очікувалося рядок, а не {} {}", kind(r), brief(r, 40)), pos),
                            };
                            let el = if r.c < x.c { capc(&x, r.c) } else { x };
                            match idx.get(&*k.s) {
                                Some(&i) => groups[i].1.push(el),
                                None => {
                                    idx.insert(Rc::from(&*k.s), groups.len());
                                    groups.push((k, vec![el]));
                                }
                            }
                        }
                        let mut d = Dict::new();
                        let mut c = m;
                        for (k, v) in groups {
                            let g = mk(v, m);
                            c = c.min(g.c);
                            d.set(k, g);
                        }
                        Ok(V::cs(Val::Dict(Rc::new(d)), c, m))
                    }
                }
            }
            'Σ' => {
                let (lst, range) = self.eval_list_arg(&argn[0], env)?;
                let acc = self.eval(&argn[1], env)?;
                let f = self.eval(&argn[2], env)?;
                let saved = self.pc;
                self.pc = saved.min(lst.s);
                let r = (|| -> R<V> {
                    let items = match range {
                        Some(r) => r,
                        None => Items::List(self.seq(&lst, g, pos)?),
                    };
                    let out = self.each_all(g, &items, &f, Some(acc), pos)?;
                    Ok(out.into_iter().next().unwrap())
                })();
                self.pc = saved;
                let acc = r?;
                self.fn_effects(&argn[2], lst.s);
                self.halt_risk(lst.s, &[&argn[2]], true);
                Ok(if lst.s < acc.c { capc(&acc, lst.s) } else { acc })
            }
            '↻' => {
                let mut s = self.eval(&argn[0], env)?;
                let cond = self.eval(&argn[1], env)?;
                let stepf = self.eval(&argn[2], env)?;
                for f in [&cond, &stepf] {
                    if !matches!(f.v, Val::Fn(_)) {
                        return ngr(format!("↻: умова й крок мають бути функціями (λs …), а не {}", kind(f)), pos);
                    }
                }
                let saved = self.pc;
                let mut cc = 1.0f64;
                // λ без замикань і модуля, певна, з одним параметром — одне середовище на весь цикл (як у ∀ ∫):
                // те саме, що швидкий шлях call, без нового Env щокроку
                let reuse = |f: &V| match &f.v {
                    Val::Fn(func) if f.c >= 1.0 && func.lam.simple && func.module.is_none() && !func.lam.escapes
                        && func.lam.params.len() == 1 => Some((func.clone(), Env::child(vec![V::none()], &func.env))),
                    _ => None,
                };
                let (rc, rs) = (reuse(&cond), reuse(&stepf));
                let r = (|| -> R<V> {
                    loop {
                        let r = match &rc {
                            Some((func, e)) => self.call_in(func, e, s.clone(), pos)?,
                            None => self.call(&cond, vec![s.clone()], pos)?,
                        };
                        cc = cc.min(r.c);
                        self.taint(r.c);
                        if !self.boolean(&r, g, pos)? {
                            break;
                        }
                        self.pc = saved.min(cc);
                        s = match &rs {
                            Some((func, e)) => self.call_in(func, e, s.clone(), pos)?,
                            None => self.call(&stepf, vec![s.clone()], pos)?,
                        };
                    }
                    Ok(s.clone())
                })();
                self.pc = saved;
                let s = r?;
                self.fn_effects(&argn[1], cc);
                self.fn_effects(&argn[2], cc);
                self.halt_risk(cc, &[&argn[1], &argn[2]], true);
                Ok(if cc < s.c { capc(&s, cc) } else { s })
            }
            _ => {
                let mut buf: [V; 4] = [V::none(), V::none(), V::none(), V::none()];
                for (i, x) in argn.iter().enumerate() {
                    buf[i] = self.eval(x, env)?;
                }
                self.strict(g, &buf[..argn.len()], pos)
            }
        }
    }

    /// ＋ － × з десятковими — точно (до 60 значущих цифр) або помилка.
    fn exact(&self, op: char, x: &Val, y: &Val, g: char, pos: Pos) -> R<Val> {
        if let (Val::Int(a), Val::Int(b)) = (x, y) {
            return Ok(Val::Int(match op {
                '＋' => a.add(b),
                '－' => a.sub(b),
                _ => a.mul(b),
            }));
        }
        if let Some(r) = crate::prims::small_exact(op, x, y) {
            return Ok(r);
        }
        let (a, b) = (to_dec(x), to_dec(y));
        let ctx = dec::exact_ctx();
        let r = match op {
            '＋' => a.add(&b, &ctx),
            '－' => a.sub(&b, &ctx),
            _ => a.mul(&b, &ctx),
        };
        match r {
            Ok(d) => Ok(Val::Dec(Rc::new(d))),
            Err(s) if s == dec::INEXACT || s == dec::OVERFLOW || s == dec::UNDERFLOW => {
                ngr(format!("{}: точний результат довший за 60 значущих цифр — округліть (≅) або діліть (÷)", g), pos)
            }
            Err(s) => dec_err(g, s, pos),
        }
    }

    fn strict(&mut self, g: char, args: &[V], pos: Pos) -> R<V> {
        if self.prof.is_some() {
            let t = self.clock();
            let r = self.strict_(g, args, pos);
            self.prof_add(&g.to_string(), t);
            return r;
        }
        self.strict_(g, args, pos)
    }

    fn strict_(&mut self, g: char, args: &[V], pos: Pos) -> R<V> {
        if g == '§' && args.len() == 2 {
            // § список ціле, усе певне (і контекст): елемент як є — те саме, що дає загальний шлях нижче, без нього
            if let (Val::List(l), Val::Int(Int::S(i))) = (&args[0].v, &args[1].v) {
                let len = l.len() as i64;
                if -len <= *i && *i < len && args[0].c >= 1.0 && args[0].s >= 1.0 && args[1].c >= 1.0 && args[1].s >= 1.0
                    && self.cpc() >= 1.0
                {
                    return Ok(l[if *i < 0 { (*i + len) as usize } else { *i as usize }].clone());
                }
            }
        }
        let amin = args.iter().fold(1.0f64, |a, x| a.min(x.c));
        self.taint(amin);
        if lang::is_heavy(g) {
            let total: u64 = args.iter().map(|a| a.n).sum();
            self.work(total, pos)?;
        }
        let res = match self.prim(g, args, pos) {
            Ok(r) => r,
            Err(e) if e.deep => return ngr_c(format!("{}: значення вкладене надто глибоко", g), pos, self.cpc().min(amin)),
            Err(mut e) => {
                if !e.fatal {
                    e.c = e.c.min(self.cpc()).min(amin);
                }
                return Err(e);
            }
        };
        if amin < 1.0 && !lang::is_never_fails(g) && !(g == '§' && matches!(args[0].v, Val::Dict(_))) {
            // § і ⚗ падають лише через індекс чи поріг і будову, не через вміст (суд 12)
            self.halt_risk_any(if g == '§' || g == '⚗' { args[0].s.min(args[1].c) } else { amin });
        }
        let mut res = res;
        if matches!(g, 'ρ' | 'κ' | '§' | '⌂' | '⚗' | '🜃') && self.cpc() < res.c {
            res = capc(&res, self.cpc());
        }
        if !lang::is_own_conf(g) {
            let c = res.c.min(amin).min(self.cpc());
            if matches!(res.v, Val::List(_) | Val::Dict(_)) {
                let s = args.iter().fold(res.s, |a, x| a.min(x.s));
                res = res.with(res.c.min(c), s);
            } else if c < res.c {
                res = res.with(c, c);
            }
        }
        Ok(res)
    }

    fn prim(&mut self, g: char, a: &[V], pos: Pos) -> R<V> {
        if a.len() == 2 {
            if let (Val::Int(x), Val::Int(y)) = (&a[0].v, &a[1].v) {
                if matches!(g, '＋' | '－' | '×' | '‰' | '‹' | '›' | '≤' | '≥' | '＝' | '≠') && !(g == '‰' && y.is_zero()) {
                    return Ok(match g {
                        '＋' => V::int(x.add(y)),
                        '－' => V::int(x.sub(y)),
                        '×' => V::int(x.mul(y)),
                        '‰' => V::int(x.divmod(y).1),
                        '‹' => V::b(x.cmp(y) == Ordering::Less),
                        '›' => V::b(x.cmp(y) == Ordering::Greater),
                        '≤' => V::b(x.cmp(y) != Ordering::Greater),
                        '≥' => V::b(x.cmp(y) != Ordering::Less),
                        '＝' => V::b(x.cmp(y) == Ordering::Equal),
                        _ => V::b(x.cmp(y) != Ordering::Equal),
                    });
                }
            }
        }
        crate::prims::prim(self, g, a, pos)
    }

    // ---------------------------------------------------------------- інструменти

    pub fn tool_begin(&mut self, name: &'static str, args: Vec<V>, pos: Pos) -> R<Job> {
        let full = matches!(name, "агент" | "мережа.взяти" | "мережа.послати" | "файл.писати" | "бд.писати" | "процес");
        let targs: Vec<J> = match args.iter().map(|a| trace_val(a, full)).collect() {
            Ok(t) => t,
            Err(e) if e.deep => {
                let c = args.iter().fold(self.cpc(), |m, a| m.min(a.c));
                return ngr_c(format!("{}: аргумент вкладений надто глибоко", name), pos, c);
            }
            Err(e) => return Err(e),
        };
        if !self.caps.has(name) {
            let agent = self.agent.clone();
            self.rec(
                "заборонено",
                data!["агент" => J::Str(agent.clone()), "назва" => J::s(name), "аргументи" => J::Arr(targs),
                      "причина" => J::s("інструмента немає в дозволах цього агента")],
            )?;
            return ngr(
                format!("агент «{}» не має дозволу «{}» (функцію з інструментом викликано там, де цього дозволу немає)", agent, name),
                pos,
            );
        }
        let ac = args.iter().fold(self.cpc(), |a, x| a.min(x.c));
        self.taint(ac);
        self.last_call = Some((name.to_string(), targs.clone()));
        let hits = self.check_quota(name, &args, &targs, pos)?;
        if lang::WORLD_WRITERS.contains(&name) {
            let agent = self.agent.clone();
            self.rec("виклик", data!["агент" => J::Str(agent), "назва" => J::s(name), "аргументи" => J::Arr(targs.clone())])?;
            self.world_c = self.world_c.min(ac);
        }
        Ok(Job { name, args, targs, ac, pos, agent: self.agent.clone(), quota: hits, paths: Vec::new() })
    }

    fn quota_covers(&self, tool: &str, scope: &str, args: &[V]) -> bool {
        let (_, needs, kind, _) = crate::parser::tool_info(tool).unwrap();
        let kind = if needs { kind } else { "" };
        if scope.is_empty() || kind.is_empty() {
            return true;
        }
        let a0 = args.first().map(|a| &a.v);
        match (kind, a0) {
            ("тека", Some(Val::Str(s))) => {
                let base = pathx::realpath(&pathx::join(&self.cwd, scope));
                let c1 = pathx::realpath(&pathx::join(&self.cwd, &s.s));
                let c2 = pathx::realpath(&pathx::join(&base, &s.s));
                pathx::inside(&c1, &base) || pathx::inside(&c2, &base)
            }
            ("імʼя", Some(Val::Str(s))) => &*s.s == scope,
            _ => false,
        }
    }

    fn check_quota(&mut self, name: &str, args: &[V], targs: &[J], pos: Pos) -> R<Vec<(String, String, String)>> {
        let mut hits = Vec::new();
        let mut seen: Vec<String> = Vec::new();
        let mut over: Option<(String, String, u64)> = None;
        let stack = self.quota_stack.clone();
        for t in &stack {
            if seen.contains(&t.tok) {
                continue;
            }
            seen.push(t.tok.clone());
            for ((tool, sc), limit) in &t.quotas {
                if tool == name && self.quota_covers(name, sc, args) {
                    let key = (t.tok.clone(), tool.clone(), sc.clone());
                    if *self.quota_used.get(&key).unwrap_or(&0) >= *limit && over.is_none() {
                        over = Some((t.who.clone(), sc.clone(), *limit));
                    }
                    hits.push(key);
                }
            }
        }
        match over {
            None => {
                for k in &hits {
                    *self.quota_used.entry(k.clone()).or_insert(0) += 1;
                }
                Ok(hits)
            }
            Some((who, sc, limit)) => {
                self.db_unverified = None;
                if name.starts_with("файл.") {
                    self.denied = false;
                    let a0 = args[0].v.clone();
                    self.path_ok(name, &a0, pos, name == "файл.писати")?;
                } else if name.starts_with("бд.") {
                    self.denied = false;
                    let a = args.to_vec();
                    crate::sqlite::rights(self, name, &a, pos, name == "бд.писати")?;
                }
                let q = format!("{}{}≤{}", name, if sc.is_empty() { String::new() } else { format!(":{}", sc) }, limit);
                let agent = self.agent.clone();
                let mut d = data!["агент" => J::Str(agent), "назва" => J::s(name), "аргументи" => J::Arr(targs.to_vec()),
                                  "чия" => J::Str(who.clone()), "квота" => J::Str(q.clone())];
                if let Some(uv) = self.db_unverified.clone() {
                    d.push(("не_перевірено".into(), J::Str(uv))); // годинник SQLite з даних (суд 12)
                }
                self.rec("квоту вичерпано", d)?;
                ngr(format!("{}: вичерпано квоту ({}: «{}»)", name, who, q), pos)
            }
        }
    }

    fn quota_refund(&mut self, hits: &[(String, String, String)]) {
        for k in hits {
            if let Some(v) = self.quota_used.get_mut(k) {
                *v -= 1;
            }
        }
    }

    pub fn deny(&mut self, data: Vec<(String, J)>) -> R<()> {
        self.denied = true;
        self.rec("заборонено", data)
    }

    /// Запобіжна відмова: дію не виконано через стан світу (стара база на межі rowid), а не через права (суд 9д).
    pub fn caution(&mut self, data: Vec<(String, J)>) -> R<()> {
        self.denied = true;
        self.rec("запобіжна відмова", data)
    }

    fn tool_do(&mut self, job: &Job) -> (Option<V>, Option<Box<E>>, Vec<String>) {
        if self.dry.is_some() && matches!(job.name, "файл.писати" | "бд.писати") {
            // --сухо (нативно, суд 9): дія не відбувається, результат невідомий; права — як завжди: поза ними
            // «заборонено», а не «дій не виконано»; інша помилка (таблиці ще немає) — не судимо
            self.denied = false;
            self.db_unchecked = false;
            self.db_unverified = None;
            let r = if job.name == "файл.писати" {
                let a0 = job.args[0].v.clone();
                self.path_ok(job.name, &a0, job.pos, true).map(|_| ())
            } else {
                let a = job.args.clone();
                crate::sqlite::rights(self, job.name, &a, job.pos, true)
            };
            if let Err(e) = r {
                if self.denied {
                    let q = job.quota.clone();
                    self.quota_refund(&q);
                    return (None, Some(e), Vec::new());
                }
            }
            let n = self.ends;
            let unchecked = job.name == "бд.писати" && self.db_unchecked;
            let uv = if job.name == "бд.писати" { self.db_unverified.clone() } else { None };
            self.dry.as_mut().unwrap().push((n, job.name, job.targs.clone(), job.ac, unchecked, uv));
            let v = if job.name == "файл.писати" { Val::None } else { Val::Int(Int::S(0)) };
            return (Some(V::new(v, 0.0)), None, Vec::new());
        }
        self.paths_seen = Some(Vec::new());
        self.denied = false;
        let t = self.clock();
        let r = crate::tools::run(self, job.name, &job.args, job.pos);
        self.prof_add(job.name, t);
        let paths = self.paths_seen.take().unwrap_or_default();
        match r {
            Ok(v) => (Some(v), None, paths),
            Err(e) if e.deep => (None, ngr_c::<()>(format!("{}: значення вкладене надто глибоко", job.name), job.pos, job.ac).err(), paths),
            Err(e) => {
                if self.denied {
                    let q = job.quota.clone();
                    self.quota_refund(&q);
                }
                (None, Some(e), paths)
            }
        }
    }

    fn tool_end(&mut self, mut job: Job, outcome: (Option<V>, Option<Box<E>>, Vec<String>)) -> R<V> {
        let (res, err, paths) = outcome;
        job.paths = paths;
        self.ends += 1;
        let name = job.name;
        let dry = self.dry.is_some();
        let suppressed = dry && err.is_none() && matches!(name, "файл.писати" | "бд.писати");
        if suppressed {
            self.world_c = 0.0; // дію придушено: стан світу тепер не той, що був би (читання після — сумнівні)
        }
        // у сухому прогоні придушені дії не забирали часу й не змінювали світу: час і оракул — теж невідомі
        let reads = lang::WORLD_READERS.contains(&name) || (dry && matches!(name, "час" | "оракул"));
        if let Some(mut e) = err {
            if e.fatal {
                return Err(e);
            }
            e.c = e.c.min(job.ac).min(if reads { self.world_c } else { 1.0 });
            self.rec(
                "інструмент",
                data!["агент" => J::Str(job.agent.clone()), "назва" => J::s(name), "аргументи" => J::Arr(job.targs.clone()),
                      "помилка" => J::Str(e.msg.clone()), "впевненість" => fj(e.c)],
            )?;
            return Err(e);
        }
        let res = res.unwrap();
        if name != "оракул" && name != "час" {
            self.halt_risk_any(job.ac);
        }
        let mut c = res.c.min(job.ac);
        if reads {
            c = c.min(self.world_c);
        }
        if name == "час" {
            c = c.min(self.decided_c);
        }
        if dry && matches!(name, "час" | "оракул") {
            c = 0.0;
        }
        if dry && name == "бд.читати" && (self.caps.has("час") || self.caps.has("жереб")) {
            c = 0.0; // date('now'), random() у сухому прогоні — не ті, що будуть у справжньому (суд 9)
        }
        let t = self.clock();
        let stored = self.trace.keep(&res).map_err(terr)?;
        self.prof_add("сховище", t);
        let res = if c < 1.0 { capc(&res, c) } else { res };
        self.taint(c);
        let t = self.clock();
        let tv = trace_val(&res, false)?;
        self.prof_add("trace_val", t);
        let mut d = data!["агент" => J::Str(job.agent.clone()), "назва" => J::s(name), "аргументи" => J::Arr(job.targs.clone()),
                          "результат" => tv, "впевненість" => fj(c), "значення" => J::Str(stored)];
        if suppressed {
            d.push(("сухо".into(), J::s("не виконано")));
        }
        if !job.paths.is_empty() {
            d.push(("шлях".into(), J::Arr(job.paths.iter().map(|p| J::s(p)).collect())));
        }
        self.rec("інструмент", d)?;
        Ok(res)
    }

    /// _path_ok: права на шлях (теки з печатки, не тека власника й не слід).
    pub fn path_ok(&mut self, tool: &str, p: &Val, pos: Pos, write: bool) -> R<String> {
        let t = self.clock();
        let r = self.path_ok_(tool, p, pos, write);
        self.prof_add("path_ok", t);
        r
    }

    fn path_ok_(&mut self, tool: &str, p: &Val, pos: Pos, write: bool) -> R<String> {
        let p = match p {
            Val::Str(s) => s.s.to_string(),
            _ => return ngr(format!("{}: шлях має бути рядком", tool), pos),
        };
        if p.contains('\0') || p.chars().any(uni::invisible) {
            let agent = self.agent.clone();
            self.deny(data!["агент" => J::Str(agent), "назва" => J::s(tool), "шлях" => J::Str(uni::safe(&p)),
                            "причина" => J::s("керівні чи невидимі символи в шляху")])?;
            return ngr(format!("{}: у шляху керівні чи невидимі символи", tool), pos);
        }
        let scopes: Vec<String> = self.caps.get(tool).cloned().unwrap_or_default();
        let allowed = |it: &mut Interp, real: &str| -> R<bool> {
            // real і тека власника — вже справжні шляхи: inside без повторного realpath
            if pathx::inside_canon(real, &it.owner_home) || it.protected.iter().any(|x| x == real) {
                let agent = it.agent.clone();
                it.deny(data!["агент" => J::Str(agent), "назва" => J::s(tool), "шлях" => J::Str(uni::safe(&p)),
                              "причина" => J::s("тека власника або слід")])?;
                return ngr(format!("{}: «{}» — це тека власника або слід; програмі туди не можна", tool, uni::safe(&p)), pos);
            }
            let check = if write { pathx::dirname(real) } else { real.to_string() };
            for base in &scopes {
                let joined = pathx::join(&it.cwd, base);
                let b = match it.rp_cache.get(&joined) {
                    Some(b) => b.clone(),
                    None => {
                        let b = pathx::realpath(&joined);
                        it.rp_cache.insert(joined, b.clone());
                        b
                    }
                };
                if check == b || check.starts_with(&format!("{}/", b)) || (!write && real == b) {
                    return Ok(true);
                }
            }
            Ok(false)
        };
        let first = pathx::realpath(&pathx::join(&self.cwd, &p));
        if allowed(self, &first)? {
            if let Some(s) = self.paths_seen.as_mut() {
                s.push(uni::safe(&first));
            }
            return Ok(first);
        }
        let named = pathx::exists(&first) || (p.trim_end_matches('/').contains('/') && pathx::isdir(&pathx::dirname(&first)));
        if !p.starts_with('/') && scopes.len() == 1 && !named {
            let base = pathx::realpath(&pathx::join(&self.cwd, &scopes[0]));
            let dir = if pathx::isfile(&base) { pathx::dirname(&base) } else { base };
            let real = pathx::realpath(&pathx::join(&dir, &p));
            if allowed(self, &real)? {
                if let Some(s) = self.paths_seen.as_mut() {
                    s.push(uni::safe(&real));
                }
                return Ok(real);
            }
        }
        let agent = self.agent.clone();
        self.deny(data!["агент" => J::Str(agent), "назва" => J::s(tool), "шлях" => J::Str(uni::safe(&p)),
                        "причина" => J::s("поза дозволеною текою")])?;
        let allowed_list: Vec<String> = scopes.iter().map(|x| uni::safe(x)).collect();
        let file = write && scopes.iter().any(|b| pathx::realpath(&pathx::join(&self.cwd, b)) == first); // суд 9г, Скептик
        ngr(format!("{}: «{}» поза дозволеним ({}){}", tool, uni::safe(&p), allowed_list.join(", "),
                    if file { "; для запису в печатці — тека, а не сам файл" } else { "" }), pos)
    }

    // ---------------------------------------------------------------- субагенти

    fn exceeds(&self, caps: &Caps) -> Vec<String> {
        let mut over = Vec::new();
        for (t, scopes) in &caps.tools {
            let mine = match self.caps.get(t) {
                Some(m) => m,
                None => {
                    over.push(t.clone());
                    continue;
                }
            };
            let kind = crate::parser::tool_info(t).map(|x| x.2).unwrap_or("");
            for sc in scopes {
                let ok = if kind == "тека" {
                    let rs = pathx::realpath(&pathx::join(&self.cwd, sc));
                    mine.iter().any(|p| pathx::inside(&rs, &pathx::realpath(&pathx::join(&self.cwd, p))))
                } else if kind == "команда" {
                    mine.iter().any(|p| crate::parser::cmd_within(sc, p))
                } else {
                    mine.contains(sc)
                };
                if !ok {
                    over.push(format!("{}:{}", t, sc));
                }
            }
        }
        over
    }

    fn delegate(&mut self, n: &Node, env: &Rc<Env>) -> R<V> {
        let (name, intent, caps, body) = match &n.k {
            K::Deleg(a, b, c, d) => (a.clone(), b.clone(), c.clone(), d),
            _ => unreachable!(),
        };
        let pos = n.pos;
        let over = self.exceeds(&caps);
        if !over.is_empty() {
            let agent = self.agent.clone();
            self.rec(
                "заборонено",
                data!["агент" => J::Str(agent.clone()), "субагент" => J::s(&name), "дозволи" => caps_json(&caps),
                      "бракує" => J::Arr(over.iter().map(|x| J::s(x)).collect()),
                      "причина" => J::s("субагент просить більше, ніж має агент, що його викликає")],
            )?;
            return ngr(format!("агент «{}» не може дати субагенту «{}» більше, ніж має сам: {}", agent, name, over.join(", ")), pos);
        }
        let saved_mem = std::mem::take(&mut self.memory);
        let saved_agent = self.agent.clone();
        let saved_caps = self.caps.clone();
        let saved_memc = self.mem_c;
        let agent = self.agent.clone();
        self.rec("делегування", data!["агент" => J::Str(agent.clone()), "субагент" => J::s(&name), "намір" => J::s(&intent), "дозволи" => caps_json(&caps)])?;
        self.agent = format!("{}/{}", agent, name);
        self.caps = caps.clone();
        self.mem_c = 1.0;
        self.trace.depth += 1;
        let pushed = !caps.quotas.is_empty();
        if pushed {
            self.quota_seq += 1;
            self.quota_stack.push(Rc::new(QuotaTable {
                who: format!("субагент {}", name),
                quotas: caps.quotas.clone(),
                tok: format!("суб{}", self.quota_seq),
            }));
        }
        let inner = Env::new(0, Some(env.clone()));
        let r = self.eval(body, &inner);
        let r = match r {
            Err(e) if !e.fatal => {
                let a = self.agent.clone();
                let rr = self.rec("субагент впав", data!["агент" => J::Str(a), "помилка" => J::Str(e.msg.clone())]);
                match rr {
                    Err(x) => Err(x),
                    Ok(()) => Err(Box::new(E {
                        msg: format!("у субагенті «{}»: {}", name, e.msg),
                        pos: e.pos.or(Some(pos)),
                        c: e.c,
                        wh: false,
                        file: None,
                        fatal: false,
                        pipe: false,
                        internal: false,
                        deep: false,
                    })),
                }
            }
            r => r,
        };
        if pushed {
            self.quota_stack.pop();
        }
        self.trace.depth -= 1;
        self.memory = saved_mem;
        self.agent = saved_agent;
        self.caps = saved_caps;
        self.mem_c = saved_memc;
        let res = r?;
        let shown = match trace_val(&res, false) {
            Ok(s) => s,
            Err(e) if e.deep => return ngr_c(format!("субагент «{}»: результат вкладений надто глибоко", name), pos, res.c),
            Err(e) => return Err(e),
        };
        let agent = self.agent.clone();
        self.rec("субагент повернув", data!["агент" => J::Str(agent), "субагент" => J::s(&name), "результат" => shown, "впевненість" => fj(res.c)])?;
        Ok(res)
    }
}

pub fn to_dec(x: &Val) -> Dec {
    match x {
        Val::Int(i) => Dec::from_int(i),
        Val::Dec(d) => (**d).clone(),
        Val::Float(f) => Dec::parse(&pyf::repr(*f)).unwrap(),
        _ => Dec::zero(),
    }
}

pub fn dec_err<T>(g: char, s: u32, pos: Pos) -> R<T> {
    ngr(format!("{}: {}", g, dec::why(s)), pos)
}

/// Елементи циклу: справжній список або ряд цілих `…` (на льоту).
pub enum Items {
    List(Rc<List>),
    Range { start: i64, len: usize, c: f64 },
}

impl Items {
    pub fn len(&self) -> usize {
        match self {
            Items::List(l) => l.len(),
            Items::Range { len, .. } => *len,
        }
    }

    #[inline]
    pub fn get(&self, i: usize) -> V {
        match self {
            Items::List(l) => l[i].clone(),
            Items::Range { start, c, .. } => {
                let v = start + i as i64;
                V { v: Val::Int(Int::S(v)), c: *c, s: *c, n: 1 + (64 - v.unsigned_abs().leading_zeros() as u64) / 3 }
            }
        }
    }
}

/// Σ bit_length(|i|) // 3 для i від x, len штук (логічний розмір ряду без створення списку).
fn range_bl3(x: i64, len: usize) -> u64 {
    if len == 0 {
        return 0;
    }
    let y = x + (len as i64 - 1);
    let mut total = 0u64;
    // невідʼємна частина [max(x,0), y]
    if y >= 0 {
        total += pos_bl3(x.max(0) as u64, y as u64);
    }
    // відʼємна частина [x, min(y,-1)] → |i| ∈ [-min(y,-1), -x]
    if x < 0 {
        let hi = x.unsigned_abs();
        let lo = if y < 0 { y.unsigned_abs() } else { 1 };
        total += pos_bl3(lo, hi);
    }
    total
}

fn pos_bl3(a: u64, b: u64) -> u64 {
    let mut total = 0u64;
    for k in 1..=64u32 {
        let lo = 1u64 << (k - 1);
        let hi = if k == 64 { u64::MAX } else { (1u64 << k) - 1 };
        let (l, h) = (a.max(lo), b.min(hi));
        if l <= h {
            total += (h - l + 1) * (k as u64 / 3);
        }
    }
    total
}

/// intersect_caps: права, що є і в a, і в b (теки — за справжніми шляхами; хости й імена — точний збіг).
pub fn intersect_caps(a: &Caps, b: &Caps, cwd: &str) -> Caps {
    let mut out = Caps::default();
    for (t, sa) in &a.tools {
        let sb = match b.get(t) {
            Some(x) => x,
            None => continue,
        };
        let (_, needs, kind, _) = crate::parser::tool_info(t).unwrap();
        if !needs {
            out.tools.push((t.clone(), Vec::new()));
            continue;
        }
        let real = |x: &str| pathx::realpath(&pathx::join(cwd, x));
        let mut keep: Vec<String> = if kind == "тека" {
            let mut k: Vec<String> = sa.iter().filter(|x| sb.iter().any(|y| pathx::inside(&real(x), &real(y)))).cloned().collect();
            k.extend(sb.iter().filter(|y| sa.iter().any(|x| pathx::inside(&real(y), &real(x)))).cloned());
            k
        } else if kind == "команда" {
            let mut k: Vec<String> = sa.iter().filter(|x| sb.iter().any(|y| crate::parser::cmd_within(x, y))).cloned().collect();
            k.extend(sb.iter().filter(|y| sa.iter().any(|x| crate::parser::cmd_within(y, x))).cloned());
            k
        } else {
            sa.iter().filter(|x| sb.contains(x)).cloned().collect()
        };
        if !keep.is_empty() {
            keep.sort();
            keep.dedup();
            out.tools.push((t.clone(), keep));
        }
    }
    out
}
