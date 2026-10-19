//! Типи до запуску — як nigredo.type_errors. Атанорові досить знати, чи є помилка: тоді програму віддає еталону
//! (той надрукує всі). Типи ті самі: 'list:' + тип елемента.
use crate::ast::*;
use crate::lang;
use crate::lexer::Lit;
use std::collections::HashMap;
use std::rc::Rc;

#[derive(Clone, PartialEq, Debug)]
enum Ty {
    Num,
    Str,
    Bool,
    None,
    List,
    Dict,
    Fn,
    Any,
    ListOf(Rc<Ty>),
}

fn base(t: &Ty) -> Ty {
    match t {
        Ty::ListOf(_) => Ty::List,
        x => x.clone(),
    }
}

fn elem(t: &Ty) -> Ty {
    match t {
        Ty::ListOf(e) => (**e).clone(),
        Ty::Str => Ty::Str,
        _ => Ty::Any,
    }
}

fn list_of(t: Ty) -> Ty {
    if t == Ty::Any { Ty::List } else { Ty::ListOf(Rc::new(t)) }
}

fn join(a: Ty, b: Ty) -> Ty {
    if a == b {
        a
    } else if base(&a) == Ty::List && base(&b) == Ty::List {
        Ty::List
    } else {
        Ty::Any
    }
}

fn named(s: &str) -> Ty {
    match s {
        "num" => Ty::Num,
        "str" => Ty::Str,
        "bool" => Ty::Bool,
        "none" => Ty::None,
        "list" => Ty::List,
        "dict" => Ty::Dict,
        "fn" => Ty::Fn,
        _ => Ty::Any,
    }
}

fn alts(s: &str) -> Vec<Ty> {
    if s.is_empty() { Vec::new() } else { s.split(',').map(named).collect() }
}

fn fits(actual: &[Ty], alt: &[Vec<Ty>]) -> bool {
    alt.iter().any(|a| {
        a.len() == actual.len()
            && a.iter().zip(actual).all(|(r, t)| *r == Ty::Any || *t == Ty::Any || *r == base(t))
    })
}

fn lit_type(l: &Lit) -> Ty {
    match l {
        Lit::Bool(_) => Ty::Bool,
        Lit::Int(_) | Lit::Dec(_) => Ty::Num,
        Lit::Str(_) => Ty::Str,
        Lit::None => Ty::None,
    }
}

struct Ck {
    errs: usize,
    env: Vec<HashMap<Rc<str>, Ty>>,
}

const ITER_FN: &str = "∀μφ⇅⊞∫‖№Σ";

impl Ck {
    fn lam_t(&mut self, l: &Lambda, ptypes: &[Ty]) -> Ty {
        let mut sc = HashMap::new();
        for p in &l.params {
            match p {
                Param::Name(x) => {
                    sc.insert(x.clone(), Ty::Any);
                }
                Param::Pat(_, xs) => {
                    for x in xs {
                        sc.insert(x.clone(), Ty::Any);
                    }
                }
            }
        }
        for (p, pt) in l.params.iter().zip(ptypes) {
            if let Param::Name(x) = p {
                sc.insert(x.clone(), pt.clone());
            }
        }
        self.env.push(sc);
        let r = self.t(&l.body);
        self.env.pop();
        r
    }

    fn t(&mut self, n: &Node) -> Ty {
        match &n.k {
            K::Lit(l) => lit_type(l),
            K::Tmpl(ps) => {
                for p in ps {
                    if let TPart::Hole(_, e) = p {
                        self.t(e);
                    }
                }
                Ty::Str
            }
            K::Var(name, ..) => {
                for sc in self.env.iter().rev() {
                    if let Some(t) = sc.get(name) {
                        return t.clone();
                    }
                }
                Ty::Any
            }
            K::List(xs) => {
                let es: Vec<Ty> = xs.iter().map(|x| self.t(x)).collect();
                if !es.is_empty() && es.iter().all(|e| *e == es[0]) {
                    list_of(es[0].clone())
                } else {
                    Ty::List
                }
            }
            K::Dict(xs) => {
                for x in xs {
                    self.t(x);
                }
                Ty::Dict
            }
            K::Block(xs, _) => {
                self.env.push(HashMap::new());
                let mut out = Ty::None;
                for x in xs {
                    out = self.t(x);
                }
                self.env.pop();
                out
            }
            K::Bind(name, _, v) => {
                let first = if v.is_lam() { Ty::Fn } else { Ty::Any };
                self.env.last_mut().unwrap().insert(name.clone(), first);
                let ty = self.t(v);
                self.env.last_mut().unwrap().insert(name.clone(), ty.clone());
                ty
            }
            K::Lam(l) => {
                self.lam_t(l, &[]);
                Ty::Fn
            }
            K::Call(_, _, _, args) => {
                for a in args {
                    self.t(a);
                }
                Ty::Any
            }
            K::Tool(name, args) => {
                let actual: Vec<Ty> = args.iter().map(|a| self.t(a)).collect();
                let (req, res) = match lang::TOOL_TYPES.iter().find(|x| x.0 == *name) {
                    Some(x) => (Some(alts(x.1)), named(x.2)),
                    None => (None, Ty::Any),
                };
                let res = if *name == "файл.список" { Ty::ListOf(Rc::new(Ty::Str)) } else { res };
                if let Some(r) = req {
                    if !fits(&actual, &[r]) {
                        self.errs += 1;
                    }
                }
                res
            }
            K::Deleg(_, _, _, body) => self.t(body),
            K::Seal(..) => Ty::None,
            K::Op(g, args) => self.op(*g, args, n),
        }
    }

    fn op(&mut self, g: char, args: &[Node], _n: &Node) -> Ty {
        let (actual, body) = if ITER_FN.contains(g) && args.last().map_or(false, |a| a.is_lam()) {
            let mut actual: Vec<Ty> = args[..args.len() - 1].iter().map(|a| self.t(a)).collect();
            let el = elem(&actual[0]);
            let l = match &args.last().unwrap().k {
                K::Lam(l) => l.clone(),
                _ => unreachable!(),
            };
            let body = if g == 'Σ' { self.lam_t(&l, &[Ty::Any, el]) } else { self.lam_t(&l, &[el]) };
            actual.push(Ty::Fn);
            (actual, body)
        } else {
            (args.iter().map(|a| self.t(a)).collect::<Vec<Ty>>(), Ty::Any)
        };
        if let Ok(i) = lang::TYPE_REQ.binary_search_by(|x| x.0.cmp(&g)) {
            let alt: Vec<Vec<Ty>> = lang::TYPE_REQ[i].1.iter().map(|s| alts(s)).collect();
            if !fits(&actual, &alt) {
                self.errs += 1;
            }
        }
        if (g == '÷' || g == '‰') && args.len() == 2 {
            let zero = match &args[1].k {
                K::Lit(Lit::Int(i)) => i.is_zero(),
                K::Lit(Lit::Dec(d)) => d.is_zero(),
                _ => false,
            };
            if zero {
                self.errs += 1;
            }
        }
        let lit_pat = match args.get(1).map(|a| &a.k) {
            Some(K::Lit(Lit::Str(p))) if g == '⌕' || g == '≋' => Some(p.clone()),
            _ => None,
        };
        let mut pat_groups = None;
        if let Some(p) = &lit_pat {
            match crate::rx::Rx::new(p) {
                Ok(r) => pat_groups = Some(r.ngroups),
                Err(_) => self.errs += 1, // помилка шаблону (чи вада еталона) — до еталона
            }
        }
        match g {
            '＋' => {
                let known: Vec<&Ty> = actual.iter().filter(|x| **x != Ty::Any).collect();
                if !known.is_empty() && known.iter().all(|x| base(x) == Ty::List) {
                    return if known.len() == actual.len() && known.iter().all(|x| *x == known[0]) {
                        known[0].clone()
                    } else {
                        Ty::List
                    };
                }
                if !known.is_empty() && known.iter().all(|x| *x == known[0]) {
                    known[0].clone()
                } else {
                    Ty::Any
                }
            }
            '¿' => join(actual[1].clone(), actual[2].clone()),
            '⊏' | '↺' | '≈' | '🜍' => actual[0].clone(),
            '↑' | '⇅' | 'φ' if base(&actual[0]) == Ty::List => actual[0].clone(),
            '§' if matches!(base(&actual[0]), Ty::List | Ty::Str) => elem(&actual[0]),
            'φ' | '⇅' if actual[0] == Ty::Str => Ty::ListOf(Rc::new(Ty::Str)),
            'μ' => list_of(body),
            '✂' | 'κ' => Ty::ListOf(Rc::new(Ty::Str)),
            '…' => Ty::ListOf(Rc::new(Ty::Num)),
            '⌕' if lit_pat.is_some() => match pat_groups {
                Some(1) => Ty::ListOf(Rc::new(Ty::Str)),
                Some(_) => Ty::ListOf(Rc::new(Ty::ListOf(Rc::new(Ty::Str)))),
                None => Ty::List,
            },
            _ => match lang::TYPE_RES.binary_search_by(|x| x.0.cmp(&g)) {
                Ok(i) => named(lang::TYPE_RES[i].1),
                Err(_) => Ty::Any,
            },
        }
    }
}

/// Чи знайде еталон помилки типів у програмі.
pub fn has_type_errors(prog: &Node) -> bool {
    let mut ck = Ck { errs: 0, env: vec![HashMap::new()] };
    ck.t(prog);
    ck.errs > 0
}
