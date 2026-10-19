//! Розбір — як nigredo.Parser (без ⊃: модулі розбирає еталон). Імена зводяться до (середовищ угору, номер);
//! перекриття імені, на яке вже посилалися ззовні в цьому середовищі, — до еталона (там пошук за іменем під час
//! виконання, і замикання могло б побачити нову привʼязку).
use crate::ast::*;
use crate::lang;
use crate::lexer::{back, close_of, glyph_arity, is_name_start, Back, Lit, Pos, Tok, Token};
use crate::uni;
use std::collections::{HashMap, HashSet};
use std::rc::Rc;

struct Scope {
    names: HashMap<Rc<str>, (Option<u8>, u32)>, // арність (None — ще обчислюється), номер
    order: Vec<Rc<str>>,
    outward: HashSet<Rc<str>>,
}

impl Scope {
    fn new() -> Scope {
        Scope { names: HashMap::new(), order: Vec::new(), outward: HashSet::new() }
    }
}

enum Ctx {
    Stmt(i64),
    Items,
}

pub struct Parser {
    t: Vec<Token>,
    i: usize,
    scopes: Vec<Scope>,
    cap_stack: Vec<Rc<Caps>>,
    agent_names: HashMap<String, String>,
    ctx: Vec<Ctx>,
    head: isize,
    depth: usize,
    /// інструменти й гліфи, які Атанор виконує сам (решта — еталон)
    pub supported_tool: fn(&str) -> bool,
    pub supported_glyph: fn(char) -> bool,
}

pub fn tool_info(name: &str) -> Option<(u8, bool, &'static str, &'static str)> {
    lang::TOOLS.iter().find(|t| t.0 == name).map(|t| (t.1, t.2, t.3, t.0))
}

fn alias(name: &str) -> &str {
    lang::TOOL_ALIASES.iter().find(|a| a.0 == name).map(|a| a.1).unwrap_or(name)
}

/// canon_perm: «читати:дані» → «файл.читати:дані».
pub fn canon_perm(entry: &str) -> String {
    let (name, sep, scope) = partition(entry, ':');
    match lang::TOOL_ALIASES.iter().find(|a| a.0 == name.trim_matches(py_ws)) {
        Some(a) => format!("{}{}{}", a.1, sep, scope),
        None => entry.to_string(),
    }
}

/// str.strip() без аргументів — пробіли Unicode.
pub fn py_ws(c: char) -> bool {
    uni::isspace(c)
}

pub fn partition<'a>(s: &'a str, sep: char) -> (&'a str, &'a str, &'a str) {
    match s.find(sep) {
        Some(i) => (&s[..i], &s[i..i + sep.len_utf8()], &s[i + sep.len_utf8()..]),
        None => (s, "", ""),
    }
}

/// split_quota: («взяти:api.x», Some(100)) з «взяти:api.x≤100»; помилка — Back.
pub fn split_quota(perm: &str) -> Result<(String, Option<u64>), Back> {
    let cs: Vec<char> = perm.chars().collect();
    for p in 0..=cs.len() {
        if cs[..p].contains(&'\n') {
            break;
        }
        // решта: \s* ≤ \s* [0-9]+ \Z
        let mut k = p;
        while k < cs.len() && uni::isspace(cs[k]) {
            k += 1;
        }
        if k >= cs.len() || cs[k] != '≤' {
            continue;
        }
        k += 1;
        while k < cs.len() && uni::isspace(cs[k]) {
            k += 1;
        }
        let d0 = k;
        while k < cs.len() && cs[k].is_ascii_digit() {
            k += 1;
        }
        if k == d0 || k != cs.len() {
            continue;
        }
        let g1: String = cs[..p].iter().collect();
        if g1.contains('≤') {
            return back("одна квота — у кінці");
        }
        let ds: String = cs[d0..].iter().collect();
        let ds = ds.trim_start_matches('0');
        if ds.is_empty() {
            return back("квота ≤0");
        }
        let q = if ds.len() > 19 { u64::MAX } else { ds.parse::<u64>().unwrap_or(u64::MAX) };
        return Ok((g1, Some(q)));
    }
    if perm.contains('≤') {
        return back("квота не в кінці");
    }
    Ok((perm.to_string(), None))
}

/// plain_text: намір, дозволи, імена субагентів — лише видимий текст.
pub fn plain_text(text: &str, name: bool) -> Result<(), Back> {
    if !uni::hidden(text, "").is_empty() {
        return back("невидимі символи в печатці");
    }
    if text.contains("  ") || text != text.trim_matches(' ') {
        return back("пробіли в печатці");
    }
    if text.contains('「') || text.contains('」') || (name && text.contains('/')) {
        return back("「」 у печатці");
    }
    Ok(())
}

/// os.path.normpath (POSIX).
pub fn normpath(p: &str) -> String {
    if p.is_empty() {
        return ".".into();
    }
    let initial = if p.starts_with("//") && !p.starts_with("///") {
        2
    } else if p.starts_with('/') {
        1
    } else {
        0
    };
    let mut out: Vec<&str> = Vec::new();
    for c in p.split('/') {
        if c.is_empty() || c == "." {
            continue;
        }
        if c != ".." || (initial == 0 && out.is_empty()) || out.last() == Some(&"..") {
            out.push(c);
        } else if !out.is_empty() {
            out.pop();
        }
    }
    let body = out.join("/");
    let res = format!("{}{}", "/".repeat(initial), body);
    if res.is_empty() { ".".into() } else { res }
}

pub fn cmd_within(s: &str, g: &str) -> bool {
    let a: Vec<&str> = s.split(' ').collect();
    let b: Vec<&str> = g.split(' ').collect();
    a.len() >= b.len() && a[..b.len()] == b[..]
}

/// narrower: обмеження субагента — те саме або вужче.
pub fn narrower(tool: &str, child: &str, parent: &str) -> bool {
    if child == parent {
        return true;
    }
    let kind = tool_info(tool).map(|t| t.2).unwrap_or("");
    if kind == "команда" {
        return cmd_within(child, parent);
    }
    if kind != "тека" {
        return false;
    }
    let (c, p) = (normpath(child), normpath(parent));
    if c.starts_with('/') != p.starts_with('/') {
        return false;
    }
    let rest = if p == "." {
        c.clone()
    } else {
        let pp = format!("{}/", p.trim_end_matches('/'));
        match c.strip_prefix(&pp) {
            Some(r) => r.to_string(),
            None => return false,
        }
    };
    !rest.split('/').any(|x| x == "..")
}

impl Parser {
    pub fn new(t: Vec<Token>, supported_tool: fn(&str) -> bool, supported_glyph: fn(char) -> bool) -> Parser {
        let mut agent_names = HashMap::new();
        agent_names.insert(uni::skeleton("головний").unwrap(), "головний".to_string());
        Parser {
            t,
            i: 0,
            scopes: vec![Scope::new()],
            cap_stack: Vec::new(),
            agent_names,
            ctx: vec![Ctx::Stmt(0)],
            head: -1,
            depth: 0,
            supported_tool,
            supported_glyph,
        }
    }

    fn peek(&self) -> &Tok {
        &self.t[self.i].t
    }

    fn next(&mut self) -> Token {
        let t = self.t[self.i].clone();
        self.i += 1;
        t
    }

    fn skip_nl(&mut self) {
        while matches!(self.peek(), Tok::Nl(_)) {
            self.i += 1;
        }
    }

    fn cont_nl(&mut self) -> Result<(), Back> {
        while let Tok::Nl(ind) = *self.peek() {
            let ok = match self.ctx.last().unwrap() {
                Ctx::Items => true,
                Ctx::Stmt(s) => ind > *s,
            };
            if !ok {
                return back("рядок закінчився, а виразові бракує аргументу");
            }
            self.i += 1;
        }
        Ok(())
    }

    /// (арність, середовищ угору, номер) — як Parser.lookup, плюс адреса.
    fn lookup(&self, name: &str) -> Option<(Option<u8>, u32, u32)> {
        let n = self.scopes.len();
        for (k, s) in self.scopes.iter().enumerate().rev() {
            if let Some(&(ar, slot)) = s.names.get(name) {
                return Some((ar, (n - 1 - k) as u32, slot));
            }
        }
        None
    }

    fn resolve(&mut self, name: &Rc<str>) -> Option<(Option<u8>, u32, u32)> {
        let r = self.lookup(name)?;
        let n = self.scopes.len();
        for k in (n - r.1 as usize)..n {
            self.scopes[k].outward.insert(name.clone());
        }
        Some(r)
    }

    pub fn program(&mut self) -> Result<Node, Back> {
        self.skip_nl();
        if !matches!(self.peek(), Tok::Glyph('🜂')) {
            return back("програма має починатися з печатки");
        }
        let stmts = self.statements(None)?;
        let n = self.scopes[0].order.len() as u32;
        Ok(Node::new((1, 1), K::Block(stmts, n)))
    }

    pub fn seal_caps(&self) -> Option<Rc<Caps>> {
        self.cap_stack.first().cloned()
    }

    fn statements(&mut self, end: Option<char>) -> Result<Vec<Node>, Back> {
        let mut stmts = Vec::new();
        loop {
            self.skip_nl();
            match self.peek().clone() {
                Tok::Eof => {
                    if end.is_some() {
                        return back("незакрите");
                    }
                    return Ok(stmts);
                }
                Tok::Close(c) => {
                    if let Some(o) = end {
                        if close_of(o) == c {
                            self.i += 1;
                            return Ok(stmts);
                        }
                    }
                    return back("зайва дужка");
                }
                _ => {}
            }
            self.head = self.i as isize;
            let col = self.t[self.i].pos.1 as i64;
            self.ctx.push(Ctx::Stmt(col - 1));
            stmts.push(self.expr()?);
            self.ctx.pop();
            if !matches!(self.peek(), Tok::Nl(_) | Tok::Eof | Tok::Close(_)) {
                return back("вираз уже завершено, а в рядку ще щось є");
            }
        }
    }

    fn expr(&mut self) -> Result<Node, Back> {
        if self.depth >= lang::MAX_NEST as usize {
            return back("вкладено глибше за MAX_NEST");
        }
        self.depth += 1;
        let r = self.expr_();
        self.depth -= 1;
        r
    }

    fn expr_(&mut self) -> Result<Node, Back> {
        self.cont_nl()?;
        let Token { t, pos } = self.next();
        match t {
            Tok::Num(l) => Ok(Node::new(pos, K::Lit(l))),
            Tok::Str(s) => Ok(Node::new(pos, K::Lit(Lit::Str(s)))),
            Tok::Glyph('●') => Ok(Node::new(pos, K::Lit(Lit::Bool(true)))),
            Tok::Glyph('○') => Ok(Node::new(pos, K::Lit(Lit::Bool(false)))),
            Tok::Glyph('∅') => Ok(Node::new(pos, K::Lit(Lit::None))),
            Tok::Name(v) => {
                if v.contains('.') {
                    return back("імʼя з крапкою");
                }
                let (ar, hops, slot) = match self.resolve(&v) {
                    Some(x) => x,
                    None => return back("невідоме імʼя"),
                };
                let ar = match ar {
                    None => return back("ще обчислюється"),
                    Some(a) => a,
                };
                if ar > 0 {
                    let sk = uni::skeleton(&v).ok_or(Back("скелет".into()))?;
                    if uni::glyph_twin(&sk).is_some() {
                        return back("функція на вигляд — гліф");
                    }
                    let mut args = Vec::new();
                    for _ in 0..ar {
                        args.push(self.expr()?);
                    }
                    return Ok(Node::new(pos, K::Call(v, hops, slot, args)));
                }
                Ok(Node::new(pos, K::Var(v, hops, slot)))
            }
            Tok::Open('【') => {
                self.ctx.push(Ctx::Items);
                let items = self.items('】')?;
                self.ctx.pop();
                Ok(Node::new(pos, K::List(items)))
            }
            Tok::Open('『') => {
                self.ctx.push(Ctx::Items);
                let items = self.items('』')?;
                self.ctx.pop();
                if items.len() % 2 == 1 {
                    return back("непарний словник");
                }
                let mut seen = HashSet::new();
                for kn in items.iter().step_by(2) {
                    if let K::Lit(Lit::Str(s)) = &kn.k {
                        if !seen.insert(s.clone()) {
                            return back("ключ двічі");
                        }
                    }
                }
                Ok(Node::new(pos, K::Dict(items)))
            }
            Tok::Open(o) => {
                self.scopes.push(Scope::new());
                self.ctx.push(Ctx::Stmt(1_000_000_000));
                let stmts = self.statements(Some(o));
                self.ctx.pop();
                let sc = self.scopes.pop().unwrap();
                let stmts = stmts?;
                Ok(Node::new(pos, K::Block(stmts, sc.order.len() as u32)))
            }
            Tok::TOpen => {
                let mut parts = Vec::new();
                loop {
                    let Token { t: t2, pos: p2 } = self.next();
                    match t2 {
                        Tok::TClose => return Ok(Node::new(pos, K::Tmpl(parts))),
                        Tok::TPart(s) => parts.push(TPart::Text(p2, s)),
                        Tok::HOpen => {
                            let part = self.expr()?;
                            if !matches!(self.next().t, Tok::HClose) {
                                return back("у {…} — рівно один вираз");
                            }
                            parts.push(TPart::Hole(p2, part));
                        }
                        _ => return back("шаблон обірвався"),
                    }
                }
            }
            Tok::Glyph(g) => self.glyph(g, pos),
            _ => back("бракує аргументу"),
        }
    }

    fn items(&mut self, close: char) -> Result<Vec<Node>, Back> {
        let mut out = Vec::new();
        loop {
            self.skip_nl();
            match self.peek() {
                Tok::Close(c) if *c == close => {
                    self.i += 1;
                    return Ok(out);
                }
                Tok::Eof => return back("бракує дужки"),
                _ => out.push(self.expr()?),
            }
        }
    }

    fn name_tok(&mut self) -> Result<Rc<str>, Back> {
        self.cont_nl()?;
        match self.next().t {
            Tok::Name(v) if !v.contains('.') => Ok(v),
            _ => back("очікувалося імʼя"),
        }
    }

    fn param(&mut self) -> Result<Param, Back> {
        self.cont_nl()?;
        if matches!(self.peek(), Tok::Open('【')) {
            let ppos = self.next().pos;
            let mut names = Vec::new();
            while !matches!(self.peek(), Tok::Close('】')) {
                names.push(self.name_tok()?);
            }
            self.i += 1;
            if names.len() < 2 {
                return back("розбір — щонайменше два імені");
            }
            return Ok(Param::Pat(ppos, names));
        }
        Ok(Param::Name(self.name_tok()?))
    }

    fn lam(&mut self, n: usize, pos: Pos) -> Result<Node, Back> {
        let mut params = Vec::new();
        for _ in 0..n {
            params.push(self.param()?);
        }
        let mut flat: Vec<Rc<str>> = Vec::new();
        for p in &params {
            match p {
                Param::Name(x) => flat.push(x.clone()),
                Param::Pat(_, xs) => flat.extend(xs.iter().cloned()),
            }
        }
        let set: HashSet<&Rc<str>> = flat.iter().collect();
        if set.len() != flat.len() {
            return back("однакові імена параметрів");
        }
        let mut sc = Scope::new();
        for (k, p) in flat.iter().enumerate() {
            sc.names.insert(p.clone(), (Some(0), k as u32));
            sc.order.push(p.clone());
        }
        self.scopes.push(sc);
        let body = self.expr();
        self.scopes.pop();
        let body = body?;
        let simple = params.iter().all(|p| matches!(p, Param::Name(_)));
        let escapes = captures(&body);
        Ok(Node::new(pos, K::Lam(Rc::new(Lambda { params, nslots: flat.len(), body, simple, escapes }))))
    }

    fn caps_literal(&mut self, inherit: bool) -> Result<Caps, Back> {
        let node = self.expr()?;
        let items = match &node.k {
            K::List(xs) => xs,
            _ => return back("дозволи — буквальний список"),
        };
        let mut caps = Caps::default();
        for e in items {
            let text = match &e.k {
                K::Lit(Lit::Str(s)) => s.clone(),
                _ => return back("дозволи — рядки"),
            };
            plain_text(&text, false)?;
            let (text, quota) = split_quota(&text)?;
            let (names, sep, scope) = partition(&text, ':');
            for nm in names.split(' ') {
                let perm = canon_perm(&format!("{}{}{}", nm, sep, scope));
                cap_one(&mut caps, &perm, inherit)?;
                if let Some(q) = quota {
                    let (t, _, sc) = partition(&perm, ':');
                    let key = (t.trim_matches(py_ws).to_string(), sc.trim_matches(py_ws).to_string());
                    if caps.quotas.iter().any(|(k, _)| *k == key) {
                        return back("дві квоти");
                    }
                    caps.quotas.push((key, q));
                }
            }
        }
        Ok(caps)
    }

    fn glyph(&mut self, g: char, pos: Pos) -> Result<Node, Back> {
        match g {
            '🜂' => {
                if !self.cap_stack.is_empty() {
                    return back("друга печатка");
                }
                if matches!(self.peek(), Tok::Nl(_) | Tok::Eof) {
                    let c = Rc::new(Caps::default());
                    self.cap_stack.push(c.clone());
                    return Ok(Node::new(pos, K::Seal("".into(), c)));
                }
                let nxt_open = matches!(self.peek(), Tok::Open('【'));
                let intent: Rc<str> = if nxt_open {
                    "".into()
                } else {
                    match self.expr()?.k {
                        K::Lit(Lit::Str(s)) if !s.is_empty() => s,
                        _ => return back("печатка"),
                    }
                };
                if !intent.is_empty() {
                    plain_text(&intent, false)?;
                }
                if matches!(self.peek(), Tok::Nl(_) | Tok::Eof) {
                    let c = Rc::new(Caps::default());
                    self.cap_stack.push(c.clone());
                    return Ok(Node::new(pos, K::Seal(intent, c)));
                }
                let caps = Rc::new(self.caps_literal(false)?);
                for (t, _) in &caps.tools {
                    if !(self.supported_tool)(t) {
                        return back(format!("інструмент {} — еталон", t));
                    }
                }
                self.cap_stack.push(caps.clone());
                Ok(Node::new(pos, K::Seal(intent, caps)))
            }
            '🜔' => {
                let name = match self.next().t {
                    Tok::Name(v) => v,
                    _ => return back("після 🜔 — назва"),
                };
                let full = alias(&name);
                let (ar, _, _, stat) = match tool_info(full) {
                    Some(x) => x,
                    None => return back("невідомий інструмент"),
                };
                if !self.cap_stack.last().map_or(false, |c| c.has(stat)) {
                    return back("інструмента немає в печатці");
                }
                if !(self.supported_tool)(stat) {
                    return back("інструмент — еталон");
                }
                let mut args = Vec::new();
                for _ in 0..ar {
                    args.push(self.expr()?);
                }
                Ok(Node::new(pos, K::Tool(stat, args)))
            }
            '←' => {
                if self.i as isize - 1 != self.head {
                    return back("← лише на початку інструкції");
                }
                let name = self.name_tok()?;
                if self.scopes.last().unwrap().names.contains_key(&name) {
                    return back("уже назване");
                }
                if self.scopes.last().unwrap().outward.contains(&name) {
                    return back("перекриття імені, яке вже брали ззовні");
                }
                self.cont_nl()?;
                let ar = match self.peek() {
                    Tok::Glyph('λ') => Some(1),
                    Tok::Glyph('Λ') => Some(2),
                    _ => None,
                };
                let sc = self.scopes.last_mut().unwrap();
                let slot = sc.order.len() as u32;
                sc.names.insert(name.clone(), (ar, slot));
                sc.order.push(name.clone());
                let value = self.expr()?;
                let sc = self.scopes.last_mut().unwrap();
                if sc.names[&name].0.is_none() {
                    sc.names.insert(name.clone(), (Some(0), slot));
                }
                Ok(Node::new(pos, K::Bind(name, slot, Box::new(value))))
            }
            'λ' => self.lam(1, pos),
            'Λ' => self.lam(2, pos),
            '⊃' => back("модулі — еталон"),
            '∘' => {
                let name = self.name_tok()?;
                match self.resolve(&name) {
                    Some((Some(a), hops, slot)) if a > 0 => Ok(Node::new(pos, K::Var(name, hops, slot))),
                    _ => back("∘ бере функцію, названу ←"),
                }
            }
            '🜁' => {
                let name = self.expr()?;
                let nxt_open = matches!(self.peek(), Tok::Open('【'));
                let intent = if nxt_open { None } else { Some(self.expr()?) };
                let name: Rc<str> = match &name.k {
                    K::Lit(Lit::Str(s)) => s.clone(),
                    _ => return back("імʼя субагента — рядок"),
                };
                let intent: Rc<str> = match intent {
                    None => "".into(),
                    Some(n) => match n.k {
                        K::Lit(Lit::Str(s)) => s,
                        _ => return back("намір субагента — рядок"),
                    },
                };
                plain_text(&name, true)?;
                let sk = uni::skeleton(&name).ok_or(Back("скелет".into()))?;
                let seen = self.agent_names.entry(sk).or_insert_with(|| name.to_string()).clone();
                if *seen != *name {
                    return back("двійники субагентів");
                }
                if !intent.is_empty() {
                    plain_text(&intent, false)?;
                }
                let mut caps = self.caps_literal(true)?;
                let parent = self.cap_stack.last().cloned().unwrap_or_default();
                for (t, scopes) in caps.tools.iter_mut() {
                    let ps = match parent.get(t) {
                        Some(ps) => ps,
                        None => return back("субагент просить, чого нема в батька"),
                    };
                    for s in scopes.iter() {
                        if !ps.iter().any(|p| narrower(t, s, p)) {
                            return back("субагент просить ширше");
                        }
                    }
                    if scopes.is_empty() {
                        *scopes = ps.clone();
                    }
                }
                let caps = Rc::new(caps);
                self.cap_stack.push(caps.clone());
                self.scopes.push(Scope::new());
                let body = self.expr();
                self.scopes.pop();
                self.cap_stack.pop();
                Ok(Node::new(pos, K::Deleg(name, intent, caps, Box::new(body?))))
            }
            _ => {
                if !(self.supported_glyph)(g) {
                    return back(format!("гліф {} — еталон", g));
                }
                let ar = glyph_arity(g);
                if ar < 0 {
                    return back("особлива форма");
                }
                let mut args = Vec::new();
                for _ in 0..ar {
                    args.push(self.expr()?);
                }
                Ok(Node::new(pos, K::Op(g, args)))
            }
        }
    }
}

fn cap_one(caps: &mut Caps, perm: &str, inherit: bool) -> Result<(), Back> {
    let (name, _, scope) = partition(perm, ':');
    let name = name.trim_matches(py_ws);
    let (_, needs, kind, stat) = match tool_info(name) {
        Some(x) => x,
        None => return back("невідомий інструмент у дозволах"),
    };
    let sc = scope.trim_matches(py_ws);
    if needs && sc.is_empty() && !inherit {
        return back("потрібне обмеження");
    }
    if kind == "команда" && !sc.is_empty() {
        let w = sc.split(' ').next().unwrap();
        if !(w.starts_with('/') || !w.contains('/')) {
            return back("команда — відносний шлях");
        }
    }
    let lst = caps.entry(stat);
    if !sc.is_empty() && !lst.iter().any(|x| x == sc) {
        lst.push(sc.to_string());
    }
    Ok(())
}

pub fn is_name_start_pub(c: char) -> bool {
    is_name_start(c)
}
