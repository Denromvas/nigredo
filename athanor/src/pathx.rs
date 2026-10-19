//! Шляхи як posixpath Python 3.13: join, dirname, abspath, realpath (не строгий), inside.
use crate::parser::normpath;
use std::os::unix::fs::MetadataExt;

pub fn join(a: &str, b: &str) -> String {
    if b.starts_with('/') || a.is_empty() {
        b.to_string()
    } else if a.ends_with('/') {
        format!("{}{}", a, b)
    } else {
        format!("{}/{}", a, b)
    }
}

pub fn dirname(p: &str) -> String {
    let i = p.rfind('/').map(|x| x + 1).unwrap_or(0);
    let head = &p[..i];
    if !head.is_empty() && head.chars().any(|c| c != '/') {
        head.trim_end_matches('/').to_string()
    } else {
        head.to_string()
    }
}

pub fn basename(p: &str) -> String {
    let i = p.rfind('/').map(|x| x + 1).unwrap_or(0);
    p[i..].to_string()
}

pub fn getcwd() -> String {
    std::env::current_dir().map(|p| p.to_string_lossy().into_owned()).unwrap_or_else(|_| "/".into())
}

pub fn abspath(p: &str) -> String {
    if p.starts_with('/') {
        normpath(p)
    } else {
        normpath(&join(&getcwd(), p))
    }
}

pub fn expanduser(p: &str) -> String {
    if !p.starts_with('~') {
        return p.to_string();
    }
    let i = p[1..].find('/').map(|x| x + 1).unwrap_or(p.len());
    if i != 1 {
        return p.to_string(); // ~імʼя — не розгортаємо (як Python без такого користувача — лишає)
    }
    let home = std::env::var("HOME").unwrap_or_else(|_| "/".into());
    let home = home.trim_end_matches('/');
    let rest = &p[i..];
    let r = format!("{}{}", home, rest);
    if r.is_empty() { "/".into() } else { r }
}

/// os.path.realpath(filename) (strict=False), алгоритм Python 3.13.
pub fn realpath(filename: &str) -> String {
    let mut rest: Vec<Option<String>> = filename.split('/').rev().map(|s| Some(s.to_string())).collect();
    let mut part_count = rest.len();
    let mut path = if filename.starts_with('/') { "/".to_string() } else { getcwd() };
    let mut seen: std::collections::HashMap<String, Option<String>> = std::collections::HashMap::new();
    while part_count > 0 {
        let name = rest.pop().unwrap();
        let name = match name {
            None => {
                if let Some(Some(link)) = rest.pop() {
                    seen.insert(link, Some(path.clone()));
                }
                continue;
            }
            Some(n) => n,
        };
        part_count -= 1;
        if name.is_empty() || name == "." {
            continue;
        }
        if name == ".." {
            let i = path.rfind('/').unwrap_or(0);
            path = if i == 0 { "/".to_string() } else { path[..i].to_string() };
            continue;
        }
        let newpath = if path == "/" { format!("/{}", name) } else { format!("{}/{}", path, name) };
        let md = match std::fs::symlink_metadata(&newpath) {
            Ok(m) => m,
            Err(_) => {
                path = newpath;
                continue;
            }
        };
        if !md.file_type().is_symlink() {
            path = newpath;
            continue;
        }
        if let Some(v) = seen.get(&newpath) {
            match v {
                Some(p) => {
                    path = p.clone();
                    continue;
                }
                None => {
                    path = newpath;
                    continue;
                }
            }
        }
        let target = match std::fs::read_link(&newpath) {
            Ok(t) => t.to_string_lossy().into_owned(),
            Err(_) => {
                path = newpath;
                continue;
            }
        };
        if target.starts_with('/') {
            path = "/".to_string();
        }
        seen.insert(newpath.clone(), None);
        rest.push(Some(newpath));
        rest.push(None);
        let parts: Vec<&str> = target.split('/').collect();
        for p in parts.iter().rev() {
            rest.push(Some(p.to_string()));
        }
        part_count += parts.len();
    }
    path
}

pub fn inside(path: &str, base: &str) -> bool {
    let (p, b) = (realpath(path), realpath(base));
    p == b || p.starts_with(&format!("{}/", b))
}

pub fn exists(p: &str) -> bool {
    std::fs::metadata(p).is_ok()
}

pub fn isdir(p: &str) -> bool {
    std::fs::metadata(p).map(|m| m.is_dir()).unwrap_or(false)
}

pub fn isfile(p: &str) -> bool {
    std::fs::metadata(p).map(|m| m.is_file()).unwrap_or(false)
}

pub fn _ino(p: &str) -> u64 {
    std::fs::metadata(p).map(|m| m.ino()).unwrap_or(0)
}
