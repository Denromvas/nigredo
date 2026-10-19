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
}

impl E {
    pub fn text(&self) -> String {
        let mut w = String::new();
        if let Some(f) = &self.file {
            w.push_str(f);
            w.push(':');
        }
        if let Some((l, c)) = self.pos {
            w.push_str(&format!("{}:{} ", l, c));
        }
        format!("✗ {}{}", w, self.msg)
    }
}

pub type R<T> = Result<T, Box<E>>;

pub fn ngr<T>(msg: impl Into<String>, pos: Pos) -> R<T> {
    Err(Box::new(E { msg: msg.into(), pos: Some(pos), c: 1.0, wh: false, file: None, fatal: false, pipe: false }))
}

pub fn ngr_c<T>(msg: impl Into<String>, pos: Pos, c: f64) -> R<T> {
    Err(Box::new(E { msg: msg.into(), pos: Some(pos), c, wh: false, file: None, fatal: false, pipe: false }))
}

pub fn fatal<T>(msg: impl Into<String>, pos: Option<Pos>) -> R<T> {
    Err(Box::new(E { msg: msg.into(), pos, c: 1.0, wh: false, file: None, fatal: true, pipe: false }))
}

fn terr(e: TraceErr) -> Box<E> {
    match e {
        TraceErr::Fatal(m) => Box::new(E { msg: m, pos: None, c: 1.0, wh: false, file: None, fatal: true, pipe: false }),
        TraceErr::Io(m) => Box::new(E { msg: format!("слід: {}", m), pos: None, c: 1.0, wh: false, file: None, fatal: true, pipe: false }),
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
    pub ends: u64,
    pub quota_stack: Vec<Rc<QuotaTable>>,
    pub quota_used: HashMap<(String, String, String), u64>,
    pub quota_seq: u64,
    pub owner_home: String,
    pub paths_seen: Option<Vec<String>>,
    pub denied: bool,
    pub prof: Option<HashMap<String, (u64, std::time::Duration)>>,
}

impl Interp {
    pub fn prof_add(&mut self, k: &str, t: std::time::Instant) {
        if let Some(p) = self.prof.as_mut() {
            let e = p.entry(k.to_string()).or_insert((0, std::time::Duration::ZERO));
            e.0 += 1;
            e.1 += t.elapsed();
        }
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

impl Interp {
    #[inline]
    pub fn cpc(&self) -> f64 {
        self.pc.min(self.halt_c)
    }

    pub fn rec(&mut self, event: &str, data: Vec<(String, J)>) -> R<()> {
        let t = std::time::Instant::now();
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

    pub fn work(&mut self, units: u64, pos: Pos) -> R<()> {
        self.steps_left -= (units / 64) as i64;
        if self.steps_left < 0 {
            return fatal("перевищено ліміт кроків (--кроки)", Some(pos));
        }
        Ok(())
    }

    fn sized(&mut self, res: V, g: &str, pos: Pos) -> R<V> {
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

    pub fn eval(&mut self, n: &Node, env: &Rc<Env>) -> R<V> {
        let pos = n.pos;
        match &n.k {
            K::Lit(_) => {
                self.step(pos)?;
                let mut v = n.lv.clone().unwrap();
                let c = self.cpc();
                v.c = c;
                v.s = c;
                Ok(v)
            }
            K::Var(_, hops, slot) => {
                self.step(pos)?;
                let val = env_get(env, *hops, *slot);
                let val = if self.halt_c < val.c { self.halt_cap(env, *hops, *slot, val, pos)? } else { val };
                if !self.try_stack.is_empty() {
                    self.taint(val.c);
                }
                Ok(val)
            }
            K::Op(g, args) if !lang::is_lazy_glyphs(*g) => {
                self.step(pos)?;
                let g = *g;
                let r = match args.len() {
                    1 => {
                        let a = [self.eval(&args[0], env)?];
                        self.strict(g, &a, pos)?
                    }
                    2 => {
                        let a0 = self.eval(&args[0], env)?;
                        let a1 = self.eval(&args[1], env)?;
                        let a = [a0, a1];
                        if let Some(r) = self.int_fast(g, &a, pos)? {
                            return Ok(r);
                        }
                        self.strict(g, &a, pos)?
                    }
                    3 => {
                        let a0 = self.eval(&args[0], env)?;
                        let a1 = self.eval(&args[1], env)?;
                        let a2 = self.eval(&args[2], env)?;
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
                self.sized(r, g.encode_utf8(&mut [0u8; 4]), pos)
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
                    s.push_str(&show(v, true));
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
                    let f = V::new(Val::Fn(Rc::new(Func { lam: l.clone(), env: env.clone(), name: Some(name.clone()) })), self.cpc());
                    env.vars.borrow_mut()[*slot as usize] = f.clone();
                    return Ok(f);
                }
                let val = self.eval(value, env)?;
                env.vars.borrow_mut()[*slot as usize] = val.clone();
                Ok(val)
            }
            K::Lam(l) => Ok(V::new(Val::Fn(Rc::new(Func { lam: l.clone(), env: env.clone(), name: None })), self.cpc())),
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
            K::Op(g, args) => {
                let t = std::time::Instant::now();
                let r = self.lazy_op(*g, args, env, pos);
                if self.prof.is_some() {
                    self.prof_add(&format!("лінивий {}", g), t);
                }
                let r = r?;
                self.sized(r, g.encode_utf8(&mut [0u8; 4]), pos)
            }
            K::Lit(_) | K::Var(..) | K::Call(..) => unreachable!(),
        }
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
        self.depth += 1;
        if self.depth > lang::MAX_DEPTH {
            self.depth -= 1;
            return fatal("надто глибока рекурсія", Some(pos));
        }
        if f.c >= 1.0 && lam.simple {
            let env = Rc::new(Env { vars: std::cell::RefCell::new(args), parent: Some(func.env.clone()) });
            let r = self.eval(&lam.body, &env);
            self.depth -= 1;
            return r;
        }
        let saved = self.pc;
        self.pc = saved.min(f.c);
        self.taint(f.c);
        if f.c < 1.0 {
            self.taint_effects(&[&lam.body], f.c);
            self.halt_risk(f.c, &[&lam.body], false);
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
            let env = Rc::new(Env { vars: std::cell::RefCell::new(vars), parent: Some(func.env.clone()) });
            let res = self.eval(&lam.body, &env)?;
            Ok(if f.c < res.c { capc(&res, f.c) } else { res })
        })();
        self.pc = saved;
        self.depth -= 1;
        r
    }

    fn need_str<'a>(&self, x: &'a V, g: &str, pos: Pos) -> R<&'a Rc<PStr>> {
        match &x.v {
            Val::Str(s) => Ok(s),
            _ => ngr(format!("{}: очікувалося рядок, а не {} {}", g, kind(x), brief(x, 40)), pos),
        }
    }

    fn need_list<'a>(&self, x: &'a V, g: &str, pos: Pos) -> R<&'a Rc<Vec<V>>> {
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

    fn seq(&self, x: &V, g: char, pos: Pos) -> R<Rc<Vec<V>>> {
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
                let lst = self.eval(&argn[0], env)?;
                self.taint(lst.c);
                let items = self.seq(&lst, g, pos)?;
                let f = self.eval(&argn[1], env)?;
                let saved = self.pc;
                self.pc = saved.min(lst.s);
                let r = (|| -> R<Vec<V>> {
                    let mut out = Vec::with_capacity(items.len());
                    for (i, x) in items.iter().enumerate() {
                        out.push(self.each(g, i, &f, vec![x.clone()], pos)?);
                    }
                    Ok(out)
                })();
                self.pc = saved;
                let results = r?;
                self.fn_effects(&argn[1], lst.s);
                self.halt_risk(lst.s, &[&argn[1]], true);
                if g == '∀' {
                    return Ok(V::none_c(self.cpc().min(lst.s)));
                }
                if g == 'μ' {
                    return Ok(mk(results, lst.s));
                }
                let m = results.iter().fold(lst.s, |a, r| a.min(r.c));
                self.taint(m);
                match g {
                    '∫' => {
                        let mut total = Val::Int(Int::S(0));
                        for r in &results {
                            let v = self.num(r, '∫', pos)?;
                            total = self.exact('＋', &total, &v, '∫', pos)?;
                        }
                        self.halt_risk_any(m);
                        Ok(V::new(total, m))
                    }
                    'φ' => {
                        let mut kept = Vec::new();
                        let mut conds = Vec::with_capacity(results.len());
                        for r in &results {
                            conds.push(self.boolean(r, g, pos)?);
                        }
                        for ((x, r), ok) in items.iter().zip(&results).zip(conds) {
                            if ok {
                                kept.push(if r.c < x.c { capc(x, r.c) } else { x.clone() });
                            }
                        }
                        Ok(mk(kept, m))
                    }
                    '⇅' => {
                        let order = crate::sort::sort_order(&results, pos)?;
                        Ok(mk(order.into_iter().map(|i| items[i].clone()).collect(), m))
                    }
                    '№' => {
                        let mut counts: Vec<(Rc<PStr>, i64)> = Vec::new();
                        let mut idx: FxMap<Rc<str>, usize> = FxMap::default();
                        for r in &results {
                            let k = match &r.v {
                                Val::Str(s) => s.clone(),
                                _ => return ngr(format!("№ (ключ): очікувалося рядок, а не {} {}", kind(r), brief(r, 40)), pos),
                            };
                            match idx.get(&*k.s) {
                                Some(&i) => counts[i].1 += 1,
                                None => {
                                    idx.insert(Rc::from(&*k.s), counts.len());
                                    counts.push((k, 1));
                                }
                            }
                        }
                        let mut d = Dict::new();
                        for (k, n) in counts {
                            d.set(k, V::new(Val::Int(Int::S(n)), m));
                        }
                        Ok(V::cs(Val::Dict(Rc::new(d)), m, m))
                    }
                    _ => {
                        // ⊞
                        let mut groups: Vec<(Rc<PStr>, Vec<V>)> = Vec::new();
                        let mut idx: FxMap<Rc<str>, usize> = FxMap::default();
                        for (x, r) in items.iter().zip(&results) {
                            let k = match &r.v {
                                Val::Str(s) => s.clone(),
                                _ => return ngr(format!("⊞ (ключ): очікувалося рядок, а не {} {}", kind(r), brief(r, 40)), pos),
                            };
                            let el = if r.c < x.c { capc(x, r.c) } else { x.clone() };
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
                let lst = self.eval(&argn[0], env)?;
                let mut acc = self.eval(&argn[1], env)?;
                let f = self.eval(&argn[2], env)?;
                let saved = self.pc;
                self.pc = saved.min(lst.s);
                let r = (|| -> R<V> {
                    let items = self.seq(&lst, g, pos)?;
                    for (i, x) in items.iter().enumerate() {
                        acc = self.each(g, i, &f, vec![acc.clone(), x.clone()], pos)?;
                    }
                    Ok(acc.clone())
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
                let r = (|| -> R<V> {
                    loop {
                        let r = self.call(&cond, vec![s.clone()], pos)?;
                        cc = cc.min(r.c);
                        self.taint(r.c);
                        if !self.boolean(&r, g, pos)? {
                            break;
                        }
                        self.pc = saved.min(cc);
                        s = self.call(&stepf, vec![s.clone()], pos)?;
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
                ngr(format!("{}: точний результат довший за 60 значущих цифр — округліть (≅) або ділить (÷)", g), pos)
            }
            Err(s) => dec_err(g, s, pos),
        }
    }

    fn strict(&mut self, g: char, args: &[V], pos: Pos) -> R<V> {
        if self.prof.is_some() {
            let t = std::time::Instant::now();
            let r = self.strict_(g, args, pos);
            self.prof_add(&g.to_string(), t);
            return r;
        }
        self.strict_(g, args, pos)
    }

    fn strict_(&mut self, g: char, args: &[V], pos: Pos) -> R<V> {
        let amin = args.iter().fold(1.0f64, |a, x| a.min(x.c));
        self.taint(amin);
        if lang::is_heavy(g) {
            let total: u64 = args.iter().map(|a| a.n).sum();
            self.work(total, pos)?;
        }
        let res = match self.prim(g, args, pos) {
            Ok(r) => r,
            Err(mut e) => {
                if !e.fatal {
                    e.c = e.c.min(self.cpc()).min(amin);
                }
                return Err(e);
            }
        };
        if amin < 1.0 && !lang::is_never_fails(g) && !(g == '§' && matches!(args[0].v, Val::Dict(_))) {
            self.halt_risk_any(amin);
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
        let targs: Vec<J> = args.iter().map(|a| trace_val(a, full)).collect();
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
                if name.starts_with("файл.") {
                    self.denied = false;
                    let a0 = args[0].v.clone();
                    self.path_ok(name, &a0, pos, name == "файл.писати")?;
                }
                let q = format!("{}{}≤{}", name, if sc.is_empty() { String::new() } else { format!(":{}", sc) }, limit);
                let agent = self.agent.clone();
                self.rec(
                    "квоту вичерпано",
                    data!["агент" => J::Str(agent), "назва" => J::s(name), "аргументи" => J::Arr(targs.to_vec()),
                          "чия" => J::Str(who.clone()), "квота" => J::Str(q.clone())],
                )?;
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

    fn tool_do(&mut self, job: &Job) -> (Option<V>, Option<Box<E>>, Vec<String>) {
        self.paths_seen = Some(Vec::new());
        self.denied = false;
        let t = std::time::Instant::now();
        let r = crate::tools::run(self, job.name, &job.args, job.pos);
        self.prof_add(job.name, t);
        let paths = self.paths_seen.take().unwrap_or_default();
        match r {
            Ok(v) => (Some(v), None, paths),
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
        let reads = lang::WORLD_READERS.contains(&name);
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
        let t = std::time::Instant::now();
        let stored = self.trace.keep(&res).map_err(terr)?;
        self.prof_add("сховище", t);
        let res = if c < 1.0 { capc(&res, c) } else { res };
        self.taint(c);
        let t = std::time::Instant::now();
        let tv = trace_val(&res, false);
        self.prof_add("trace_val", t);
        let mut d = data!["агент" => J::Str(job.agent.clone()), "назва" => J::s(name), "аргументи" => J::Arr(job.targs.clone()),
                          "результат" => tv, "впевненість" => fj(c), "значення" => J::Str(stored)];
        if !job.paths.is_empty() {
            d.push(("шлях".into(), J::Arr(job.paths.iter().map(|p| J::s(p)).collect())));
        }
        self.rec("інструмент", d)?;
        Ok(res)
    }

    /// _path_ok: права на шлях (теки з печатки, не тека власника й не слід).
    pub fn path_ok(&mut self, tool: &str, p: &Val, pos: Pos, write: bool) -> R<String> {
        let t = std::time::Instant::now();
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
            if pathx::inside(real, &it.owner_home) || it.protected.iter().any(|x| x == real) {
                let agent = it.agent.clone();
                it.deny(data!["агент" => J::Str(agent), "назва" => J::s(tool), "шлях" => J::Str(uni::safe(&p)),
                              "причина" => J::s("тека власника або слід")])?;
                return ngr(format!("{}: «{}» — це тека власника або слід; програмі туди не можна", tool, uni::safe(&p)), pos);
            }
            let check = if write { pathx::dirname(real) } else { real.to_string() };
            for base in &scopes {
                let b = pathx::realpath(&pathx::join(&it.cwd, base));
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
        ngr(format!("{}: «{}» поза дозволеним ({})", tool, uni::safe(&p), allowed_list.join(", ")), pos)
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
        let shown = trace_val(&res, false);
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
    ngr(format!("{}: десяткове число поза межами ({})", g, dec::signal_name(s)), pos)
}
