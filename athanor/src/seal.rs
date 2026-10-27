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
                P::Str(s, false) => Ok(s.to_string()),
                _ => back("дозвіл — не рядок"),
            })
            .collect(),
        _ => back("не список"),
    }
}

fn get<'a, 'b>(kv: &'a [(std::borrow::Cow<'b, str>, bool, P<'b>)], k: &str) -> Option<&'a P<'b>> {
    kv.iter().find(|(x, s, _)| x == k && !s).map(|(_, _, v)| v)
}

/// «для_програм»: відбиток (без пробілів по краях, малими літерами) → дозволи; не словник чи не списки — до еталона.
fn per_programs(kv: &[(std::borrow::Cow<'_, str>, bool, P<'_>)]) -> Result<Vec<(String, Vec<String>)>, Back> {
    match get(kv, "для_програм") {
        None => Ok(Vec::new()),
        Some(P::Obj(d)) => {
            let out: Vec<(String, Vec<String>)> =
                d.iter().map(|(k, _, v)| Ok((k.trim_matches(py_ws).to_lowercase(), strs(v)?))).collect::<Result<_, Back>>()?;
            let uniq: std::collections::HashSet<&String> = out.iter().map(|(k, _)| k).collect();
            if uniq.len() != out.len() {
                return back("для_програм — той самий відбиток двічі"); // помилку пише еталон (суд 9б)
            }
            Ok(out)
        }
        Some(_) => back("для_програм — не словник"),
    }
}

/// read_allowlist(path, cwd, prog, approval).
fn read_allowlist(path: &str, cwd: Option<&str>, prog: Option<&str>, approval: Option<&str>) -> Result<Vec<String>, Back> {
    let text = std::fs::read_to_string(path).map_err(|_| Back("дозволи не прочитати".into()))?;
    let data = json::loads_unique(&text).map_err(|_| Back("дозволи — не JSON чи ключ повторюється".into()))?;
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
        Some(P::Obj(d)) => d.iter().map(|(k, _, v)| Ok((k.to_string(), strs(v)?))).collect::<Result<_, Back>>()?,
        Some(_) => return back("для_тек — не словник"),
    };
    let per_prog = per_programs(kv)?;
    // «джерела_модулів» (модулі з git, §4.2): на програму без модулів з мережі не впливає, але криве значення — відмова
    // еталона всім програмам; тут — лише список із «github.com» чи порожній, решта (дзеркало, вада) — до еталона
    match get(kv, "джерела_модулів") {
        None => {}
        Some(P::Arr(xs)) if xs.len() <= 1 && xs.iter().all(|x| matches!(x, P::Str(s, false) if s == "github.com")) => {}
        Some(_) => return back("джерела_модулів — еталон"),
    }
    let mut writable = Vec::new();
    let mut all: Vec<String> = lst.clone();
    for (_, x) in per_dir.iter().chain(per_prog.iter()) {
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
    if let Some(h) = approval {
        // словник Python: повтор ключа — діє останній
        if let Some((_, extra)) = per_prog.iter().rev().find(|(k, _)| k == h) {
            lst.extend(extra.iter().map(|a| canon_perm(a)));
        }
    }
    Ok(lst)
}

pub fn owner_home() -> String {
    let h = std::env::var("NIGREDO_HOME").unwrap_or_else(|_| "~/.nigredo".into());
    pathx::realpath(&pathx::expanduser(&h))
}

/// load_allowlist(None, cwd, prog, approval): дозволи власника, квоти, джерело.
pub fn load_allowlist(home: &str, cwd: Option<&str>, prog: Option<&str>, approval: Option<&str>) -> Result<Allowed, Back> {
    let path = pathx::join(home, "дозволи.json");
    let (owner, source) = if pathx::exists(&path) {
        let o = read_allowlist(&path, cwd, prog, approval)?;
        let raw = std::fs::read(&path).map_err(|_| Back("дозволи".into()))?;
        let mut source = format!("{} (sha256 {})", path, &sha::sha256_hex(&raw)[..16]);
        if let Some(h) = approval {
            let text = String::from_utf8(raw).map_err(|_| Back("дозволи".into()))?;
            if let Ok(P::Obj(kv)) = json::loads(&text) {
                if per_programs(&kv)?.iter().any(|(k, _)| k == h) {
                    source.push_str(&format!("; схвалено власником: програма {}…", &h[..16]));
                }
            }
        }
        (o, source)
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
        K::Import(m) => {
            out.push((parent, &m.module.caps));
            delegations(&m.module.prog, &m.module.caps, out);
        }
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

fn modules<'a>(n: &'a Node, out: &mut Vec<&'a str>) {
    match &n.k {
        K::Import(m) => {
            out.push(&m.real);
            modules(&m.module.prog, out);
        }
        K::Block(xs, _) => {
            for x in xs {
                modules(x, out);
            }
        }
        _ => {}
    }
}

/// approval_of: відбиток програми для «для_програм» — sha256 її байтів, а з модулями — sha256 рядків «sha програми»,
/// «sha модуля»… (модулі — у порядку ⊃, вкладені одразу за своїм).
pub fn approval_of(raw: &[u8], prog: &Node) -> String {
    fn walk(n: &Node, out: &mut Vec<String>) {
        match &n.k {
            K::Import(m) => {
                out.push(m.sha.clone());
                walk(&m.module.prog, out);
            }
            K::Block(xs, _) => {
                for x in xs {
                    walk(x, out);
                }
            }
            _ => {}
        }
    }
    let mut shas = Vec::new();
    walk(prog, &mut shas);
    let own = sha::sha256_hex(raw);
    if shas.is_empty() {
        return own;
    }
    let mut text = own;
    for s in shas {
        text.push('\n');
        text.push_str(&s);
    }
    sha::sha256_hex(text.as_bytes())
}

/// Теки, куди програмам дозволено писати (write_dirs еталона): з усіх записів власника.
fn write_dirs(home: &str) -> Vec<String> {
    let path = pathx::join(home, "дозволи.json");
    let text = match std::fs::read_to_string(&path) {
        Ok(t) => t,
        Err(_) => return Vec::new(),
    };
    let data = match json::loads(&text) {
        Ok(P::Obj(kv)) => kv,
        _ => return Vec::new(),
    };
    let mut entries: Vec<String> = Vec::new();
    if let Some(P::Arr(xs)) = get(&data, "дозволено") {
        for x in xs {
            if let P::Str(s, false) = x {
                entries.push(s.to_string());
            }
        }
    }
    for key in ["для_тек", "для_програм"] {
        if let Some(P::Obj(d)) = get(&data, key) {
            for (_, _, v) in d {
                if let P::Arr(xs) = v {
                    for x in xs {
                        if let P::Str(s, false) = x {
                            entries.push(s.to_string());
                        }
                    }
                }
            }
        }
    }
    let mut out = Vec::new();
    for e in entries {
        let base = match split_quota(&canon_perm(&e)) {
            Ok((b, _)) => b,
            Err(_) => continue,
        };
        let (t, _, sc) = partition(&base, ':');
        let sc = pathx::expanduser(sc.trim_matches(py_ws));
        if lang::WRITE_TOOLS.contains(&t.trim_matches(py_ws)) && sc.starts_with('/') {
            out.push(pathx::realpath(&sc));
        }
    }
    out
}

/// check_program: чи все в межах (печатка й субагенти ⊆ власника; субагент ⊆ батька за справжніми шляхами).
pub fn program_ok(prog: &Node, seal: &Caps, allowed: &Allowed, cwd: &str, home: &str) -> Result<bool, Back> {
    if !check_allowlist(seal, allowed, cwd, home)?.is_empty() {
        return Ok(false);
    }
    let mut mods = Vec::new();
    modules(prog, &mut mods);
    if !mods.is_empty() {
        // код, який могла написати програма, — не модуль
        let mut writable = Vec::new();
        for a in &allowed.full {
            let (cb, _) = split_quota(&canon_perm(a))?;
            if lang::WRITE_TOOLS.contains(&partition(&cb, ':').0.trim_matches(py_ws)) {
                let (b, _) = split_quota(a)?;
                let sc = partition(&b, ':').2.trim_matches(py_ws).to_string();
                writable.push(pathx::realpath(&pathx::join(cwd, &pathx::expanduser(&sc))));
            }
        }
        for t in lang::WRITE_TOOLS.iter() {
            for w in seal.get(t).cloned().unwrap_or_default() {
                writable.push(pathx::realpath(&pathx::join(cwd, &w)));
            }
        }
        writable.extend(write_dirs(home));
        for m in mods {
            if writable.iter().any(|w| pathx::inside(m, w)) {
                return Ok(false);
            }
        }
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
