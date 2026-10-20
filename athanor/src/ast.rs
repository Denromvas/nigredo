//! Дерево програми. Кожен вузол знає, які стани може змінити (effects) і чи може впасти (total_type) —
//! це рахує еталон для впевненості й каналу завершення; тут — один раз під час розбору.
use crate::lang;
use crate::lexer::{Lit, Pos};
use std::rc::Rc;

pub const MEM: u8 = 1;
pub const WORLD: u8 = 2;

/// total_type: 0 — може впасти; інакше тип, який вузол дає гарантовано.
pub const T_NONE: u8 = 0;
pub const T_ANY: u8 = 1;
pub const T_BOOL: u8 = 2;
pub const T_NUM: u8 = 3;
pub const T_STR: u8 = 4;
pub const T_FN: u8 = 5;
pub const T_LIST: u8 = 6;
pub const T_DICT: u8 = 7;

#[derive(Debug)]
pub struct Node {
    pub pos: Pos,
    pub k: K,
    pub eff: u8,
    pub tt: u8,
    pub lv: Option<crate::value::V>, // значення літерала (готове: виконання лише ставить впевненість)
    pub ints: u32,  // цілочислове дерево (＋ － × ‰ над іменами й цілими літералами): скільки вузлів; 0 — не таке
    pub icmp: bool, // корінь такого дерева — порівняння (‹ › ≤ ≥ ＝ ≠): дає ●/○, тож не буває операндом
}

#[derive(Debug)]
pub enum Param {
    Name(Rc<str>),
    Pat(Pos, Vec<Rc<str>>),
}

#[derive(Debug)]
pub struct Lambda {
    pub params: Vec<Param>,
    pub nslots: usize,
    pub body: Node,
    pub simple: bool,
    pub escapes: bool, // у тілі є λ чи 🜁: середовище виклику може пережити виклик (у циклі — нове щоразу)
    pub height: u64,   // висота тіла (рівнів вкладеності від λ, ≥ 1) — для межі MAX_WORK
}

/// Чи є у піддереві вузол, що захоплює середовище (λ, 🜁).
pub fn captures(n: &Node) -> bool {
    match &n.k {
        K::Lam(_) | K::Deleg(..) => true,
        K::Call(_, _, _, xs) | K::Op(_, xs) | K::List(xs) | K::Dict(xs) | K::Block(xs, _) | K::Tool(_, xs) => {
            xs.iter().any(captures)
        }
        K::Bind(_, _, v) => captures(v),
        K::Tmpl(ps) => ps.iter().any(|p| matches!(p, TPart::Hole(_, x) if captures(x))),
        _ => false,
    }
}

#[derive(Debug)]
pub enum TPart {
    Text(Pos, Rc<str>),
    Hole(Pos, Node),
}

#[derive(Debug, Clone, Default)]
pub struct Caps {
    pub tools: Vec<(String, Vec<String>)>,
    pub quotas: Vec<((String, String), u64)>,
}

impl Caps {
    pub fn get(&self, t: &str) -> Option<&Vec<String>> {
        self.tools.iter().find(|(k, _)| k == t).map(|(_, v)| v)
    }
    pub fn has(&self, t: &str) -> bool {
        self.get(t).is_some()
    }
    pub fn entry(&mut self, t: &str) -> &mut Vec<String> {
        if let Some(i) = self.tools.iter().position(|(k, _)| k == t) {
            return &mut self.tools[i].1;
        }
        self.tools.push((t.to_string(), Vec::new()));
        &mut self.tools.last_mut().unwrap().1
    }
}

#[derive(Debug)]
pub enum K {
    Lit(Lit),
    Var(Rc<str>, u32, u32),             // імʼя, скільки середовищ угору, номер
    Call(Rc<str>, u32, u32, Vec<Node>), // функція, названа ←
    Op(char, Vec<Node>),
    Bind(Rc<str>, u32, Box<Node>),
    Lam(Rc<Lambda>),
    List(Vec<Node>),
    Dict(Vec<Node>),
    Tmpl(Vec<TPart>),
    Block(Vec<Node>, u32),
    Seal(Rc<str>, Rc<Caps>),
    Tool(&'static str, Vec<Node>),
    Deleg(Rc<str>, Rc<str>, Rc<Caps>, Box<Node>),
    Import(Rc<ModImport>),
}

/// ⊃: розібраний модуль (дерево, кількість імен верхнього рівня, печатка).
#[derive(Debug)]
pub struct Module {
    pub prog: Node,
    pub nslots: u32,
    pub caps: Rc<Caps>,
}

#[derive(Debug)]
pub struct ModImport {
    pub rel: String,                      // шлях відносно кореня (як у еталона: relpath(real, root))
    pub names: Vec<(Rc<str>, u32, u32)>,  // імʼя, номер у модулі, номер тут
    pub module: Rc<Module>,
    pub sha: String,
    pub real: String,
}

/// const_expr: сталий вираз верхнього рівня модуля.
pub fn const_expr(n: &Node) -> bool {
    match &n.k {
        K::Lit(_) | K::Var(..) => true,
        K::List(xs) | K::Dict(xs) => xs.iter().all(const_expr),
        K::Tmpl(ps) => ps.iter().all(|p| match p {
            TPart::Text(..) => true,
            TPart::Hole(_, x) => const_expr(x),
        }),
        K::Op(g, xs) => lang::is_pure_glyphs(*g) && xs.iter().all(const_expr),
        _ => false,
    }
}

pub fn fn_slots(g: char) -> Option<&'static [usize]> {
    lang::FN_SLOTS.binary_search_by(|&(c, _)| c.cmp(&g)).ok().map(|i| lang::FN_SLOTS[i].1)
}

fn lit_tt(l: &Lit) -> u8 {
    match l {
        Lit::Bool(_) => T_BOOL,
        Lit::Int(_) | Lit::Dec(_) => T_NUM,
        Lit::Str(_) => T_STR,
        Lit::None => T_ANY,
    }
}

impl Node {
    pub fn new(pos: Pos, k: K) -> Node {
        let (eff, tt) = props(&k);
        let lv = match &k {
            K::Lit(l) => Some(crate::value::V::new(crate::value::lit_val(l), 1.0)),
            _ => None,
        };
        let (ints, icmp) = int_shape(&k, &lv);
        Node { pos, k, eff, tt, lv, ints, icmp }
    }

    pub fn is_lam(&self) -> bool {
        matches!(self.k, K::Lam(_))
    }

    /// may_stop(node, called)
    pub fn may_stop(&self, called: bool) -> bool {
        if called {
            return match &self.k {
                K::Lam(l) => l.body.may_stop(false) || l.params.iter().any(|p| matches!(p, Param::Pat(..))),
                _ => true,
            };
        }
        self.tt == T_NONE
    }
}

fn int_shape(k: &K, lv: &Option<crate::value::V>) -> (u32, bool) {
    use crate::value::Val;
    match k {
        K::Lit(_) => (matches!(lv, Some(v) if matches!(v.v, Val::Int(crate::int::Int::S(_)))) as u32, false),
        K::Var(..) => (1, false),
        K::Op(g, args) if args.len() == 2 && args.iter().all(|a| a.ints > 0 && !a.icmp) => {
            let n = 1 + args[0].ints + args[1].ints;
            match g {
                '＋' | '－' | '×' | '‰' => (n, false),
                '‹' | '›' | '≤' | '≥' | '＝' | '≠' => (n, true),
                _ => (0, false),
            }
        }
        _ => (0, false),
    }
}

fn props(k: &K) -> (u8, u8) {
    let kids_eff = |ns: &[Node]| ns.iter().fold(0u8, |a, n| a | n.eff);
    match k {
        K::Lit(l) => (0, lit_tt(l)),
        K::Var(..) => (0, T_ANY),
        K::Call(_, _, _, args) => (MEM | WORLD | kids_eff(args), T_NONE),
        K::Op(g, args) => {
            let mut e = kids_eff(args);
            if *g == '🜄' {
                e |= MEM;
            } else if *g == '►' || *g == '▶' {
                e |= MEM | WORLD;
            } else if let Some(slots) = fn_slots(*g) {
                if slots.iter().any(|&i| !args[i].is_lam()) {
                    e |= MEM | WORLD;
                }
            }
            (e, op_tt(*g, args))
        }
        K::Bind(_, _, v) => (v.eff, T_NONE),
        K::Lam(l) => (l.body.eff, T_FN),
        K::List(xs) => (kids_eff(xs), if xs.iter().all(|x| x.tt != T_NONE) { T_LIST } else { T_NONE }),
        K::Dict(xs) => (kids_eff(xs), if xs.iter().all(|x| x.tt != T_NONE) { T_DICT } else { T_NONE }),
        K::Tmpl(ps) => {
            let mut e = 0;
            let mut ok = true;
            for p in ps {
                if let TPart::Hole(_, n) = p {
                    e |= n.eff;
                    ok &= n.tt != T_NONE;
                }
            }
            (e, if ok { T_STR } else { T_NONE })
        }
        K::Block(xs, _) => (kids_eff(xs), T_NONE),
        K::Seal(..) => (0, T_NONE),
        K::Tool(name, args) => {
            let mut e = kids_eff(args);
            if lang::WORLD_WRITERS.contains(name) {
                e |= WORLD;
            }
            (e, T_NONE)
        }
        K::Deleg(_, _, _, body) => (body.eff & WORLD, T_NONE),
        K::Import(m) => (m.module.prog.eff, T_NONE),
    }
}

fn op_tt(g: char, args: &[Node]) -> u8 {
    let ts: Vec<u8> = args.iter().map(|a| a.tt).collect();
    if ts.contains(&T_NONE) {
        return T_NONE;
    }
    match g {
        'σ' | 'τ' => T_STR,
        '±' => T_NUM,
        '＝' | '≠' => T_BOOL,
        '＋' if ts[0] == ts[1] && (ts[0] == T_STR || ts[0] == T_NUM) => ts[0],
        '¬' if ts[0] == T_BOOL => T_BOOL,
        '∧' | '∨' if ts[0] == T_BOOL && ts[1] == T_BOOL => T_BOOL,
        '¿' if ts[0] == T_BOOL => {
            if ts[1] == ts[2] {
                ts[1]
            } else {
                T_ANY
            }
        }
        _ => T_NONE,
    }
}
