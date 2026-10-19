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
        Node { pos, k, eff, tt, lv }
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
