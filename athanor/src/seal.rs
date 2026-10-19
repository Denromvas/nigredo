//! Дозволи власника (~/.nigredo/дозволи.json) і перевірка печатки — як nigredo.load_allowlist / check_program.
//! Будь-яка відмова чи незвичне — до еталона (він надрукує й запише в слід).
use crate::ast::*;
use crate::json::{self, P};
use crate::lang;
use crate::lexer::{back, Back};
use crate::parser::{canon_perm, cmd_within, partition, py_ws, split_quota, tool_info};
use crate::pathx;
use crate::sha;

pub struct Allowed {
    pub items: Vec<String>,
    pub quotas: Vec<(String, String, u64)>,
    pub full: Vec<String>,
    pub source: String,
}

fn strs(p: &P) -> Result<Vec<String>, Back> {
    match p {
        P::Arr(xs) => xs
            .iter()
            .map(|x| match x {
                P::Str(s, false) => Ok(s.clone()),
                _ => back("дозвіл — не рядок"),
            })
            .collect(),
        _ => back("не список"),
    }
}

fn get<'a>(kv: &'a [(String, bool, P)], k: &str) -> Option<&'a P> {
    kv.iter().find(|(x, s, _)| x == k && !s).map(|(_, _, v)| v)
}

/// read_allowlist(path, cwd, prog).
fn read_allowlist(path: &str, cwd: Option<&str>, prog: Option<&str>) -> Result<Vec<String>, Back> {
    let text = std::fs::read_to_string(path).map_err(|_| Back("дозволи не прочитати".into()))?;
    let data = json::loads(&text).map_err(|_| Back("дозволи — не JSON".into()))?;
    let kv = match &data {
        P::Obj(kv) => kv,
        _ => return back("дозволи — не словник"),
    };
    let mut lst: Vec<String> = match get(kv, "дозволено") {
        Some(p) => strs(p)?.iter().map(|a| canon_perm(a)).collect(),
        None => Vec::new(),
    };
    let per_dir: Vec<(String, Vec<String>)> = match get(kv, "для_тек") {
        None => Vec::new(),
        Some(P::Obj(d)) => d.iter().map(|(k, _, v)| Ok((k.clone(), strs(v)?))).collect::<Result<_, Back>>()?,
        Some(_) => return back("для_тек — не словник"),
    };
    let mut writable = Vec::new();
    let mut all: Vec<String> = lst.clone();
    for (_, x) in &per_dir {
        all.extend(x.iter().map(|a| canon_perm(a)));
    }
    for e in &all {
        let (t, _, _) = partition(e, ':');
        if lang::WRITE_TOOLS.contains(&t.trim_matches(py_ws)) {
            let (base, _) = split_quota(e)?;
            let (_, _, sc) = partition(&base, ':');
            writable.push(sc.trim_matches(py_ws).to_string());
        }
    }
    for (d, extra) in &per_dir {
        let extra: Vec<String> = extra.iter().map(|a| canon_perm(a)).collect();
        let dd = pathx::expanduser(d);
        if let Some(c) = cwd {
            if dd.starts_with('/') && pathx::inside(c, &dd) {
                if let Some(p) = prog {
                    if writable.iter().any(|w| {
                        let ww = pathx::expanduser(w);
                        !w.is_empty() && ww.starts_with('/') && pathx::inside(p, &ww)
                    }) {
                        continue;
                    }
                }
                lst.extend(extra);
            }
        }
    }
    Ok(lst)
}

pub fn owner_home() -> String {
    let h = std::env::var("NIGREDO_HOME").unwrap_or_else(|_| "~/.nigredo".into());
    pathx::realpath(&pathx::expanduser(&h))
}

/// load_allowlist(None, cwd, prog): дозволи власника, квоти, джерело.
pub fn load_allowlist(home: &str, cwd: Option<&str>, prog: Option<&str>) -> Result<Allowed, Back> {
    let path = pathx::join(home, "дозволи.json");
    let (owner, source) = if pathx::exists(&path) {
        let o = read_allowlist(&path, cwd, prog)?;
        let raw = std::fs::read(&path).map_err(|_| Back("дозволи".into()))?;
        (o, format!("{} (sha256 {})", path, &sha::sha256_hex(&raw)[..16]))
    } else {
        (lang::DEFAULT_ALLOWED.iter().map(|s| s.to_string()).collect(), "(файлу власника немає: лише іграшкові інструменти)".to_string())
    };
    let mut quotas = Vec::new();
    for a in &owner {
        let (base, q) = split_quota(&canon_perm(a))?;
        if let Some(q) = q {
            let (t, _, sc) = partition(&base, ':');
            quotas.push((t.trim_matches(py_ws).to_string(), sc.trim_matches(py_ws).to_string(), q));
        }
    }
    Ok(Allowed { full: owner.clone(), items: owner, quotas, source })
}

/// check_allowlist: печатка ⊆ дозволи власника; повертає, чого бракує.
fn check_allowlist(caps: &Caps, allowed: &Allowed, cwd: &str, home: &str) -> Result<Vec<String>, Back> {
    let mut granted: Vec<(String, Vec<String>)> = Vec::new();
    for a in &allowed.items {
        let (base, _) = split_quota(a)?;
        let (name, _, scope) = partition(&base, ':');
        let name = name.trim_matches(py_ws).to_string();
        let scope = scope.trim_matches(py_ws).to_string();
        match granted.iter_mut().find(|(n, _)| *n == name) {
            Some((_, v)) => v.push(scope),
            None => granted.push((name, vec![scope])),
        }
    }
    let mut missing = Vec::new();
    for (tool, scopes) in &caps.tools {
        let g = match (tool_info(tool), granted.iter().find(|(n, _)| n == tool)) {
            (Some(_), Some((_, g))) => g,
            _ => {
                missing.push(tool.clone());
                continue;
            }
        };
        let kind = tool_info(tool).unwrap().2;
        for s in scopes {
            if kind == "тека" {
                let rs = pathx::realpath(&pathx::join(cwd, s));
                if pathx::inside(&rs, home) || pathx::inside(home, &rs) {
                    missing.push(format!("{}:{}", tool, s));
                    continue;
                }
            }
            let mut ok = false;
            for gr in g {
                if gr.is_empty() {
                    continue;
                }
                if kind == "тека" {
                    let ge = pathx::expanduser(gr);
                    if !ge.starts_with('/') {
                        continue;
                    }
                    let rs = pathx::realpath(&pathx::join(cwd, s));
                    let rg = pathx::realpath(&ge);
                    ok = ok || rs == rg || rs.starts_with(&format!("{}/", rg));
                } else if kind == "команда" {
                    ok = ok || cmd_within(s, gr);
                } else {
                    ok = ok || s == gr;
                }
            }
            if !ok {
                missing.push(format!("{}:{}", tool, s));
            }
        }
    }
    Ok(missing)
}

fn delegations<'a>(n: &'a Node, parent: &'a Caps, out: &mut Vec<(&'a Caps, &'a Caps)>) {
    match &n.k {
        K::Deleg(_, _, caps, body) => {
            out.push((parent, caps));
            delegations(body, caps, out);
        }
        K::Call(_, _, _, xs) | K::Op(_, xs) | K::List(xs) | K::Dict(xs) | K::Block(xs, _) | K::Tool(_, xs) => {
            for x in xs {
                delegations(x, parent, out);
            }
        }
        K::Bind(_, _, v) => delegations(v, parent, out),
        K::Lam(l) => delegations(&l.body, parent, out),
        K::Tmpl(ps) => {
            for p in ps {
                if let TPart::Hole(_, x) = p {
                    delegations(x, parent, out);
                }
            }
        }
        _ => {}
    }
}

/// check_program: чи все в межах (печатка й субагенти ⊆ власника; субагент ⊆ батька за справжніми шляхами).
pub fn program_ok(prog: &Node, seal: &Caps, allowed: &Allowed, cwd: &str, home: &str) -> Result<bool, Back> {
    if !check_allowlist(seal, allowed, cwd, home)?.is_empty() {
        return Ok(false);
    }
    let mut ds = Vec::new();
    delegations(prog, seal, &mut ds);
    for (parent, child) in ds {
        if !check_allowlist(child, allowed, cwd, home)?.is_empty() {
            return Ok(false);
        }
        for (t, scopes) in &child.tools {
            if tool_info(t).map(|x| x.2) != Some("тека") {
                continue;
            }
            for sc in scopes {
                let rs = pathx::realpath(&pathx::join(cwd, sc));
                let ps = parent.get(t).cloned().unwrap_or_default();
                if !ps.iter().any(|p| pathx::inside(&rs, &pathx::realpath(&pathx::join(cwd, p)))) {
                    return Ok(false);
                }
            }
        }
    }
    Ok(true)
}
