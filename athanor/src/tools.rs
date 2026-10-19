//! Інструменти, які Атанор виконує сам: оракул, жереб, час, файли. Решту (бд, мережа, процес, агент) — еталон.
use crate::int::Int;
use crate::interp::*;
use crate::lang;
use crate::lexer::Pos;
use crate::pathx;
use crate::pyf;
use crate::sha;
use crate::value::*;
use std::rc::Rc;

pub fn supported(name: &str) -> bool {
    matches!(name, "оракул" | "жереб" | "час" | "файл.читати" | "файл.писати" | "файл.список")
}

pub fn os_err(tool: &str, e: &std::io::Error, p: &str) -> String {
    let code = e.raw_os_error().unwrap_or(0);
    let (name, text) = lang::STRERROR.iter().find(|x| x.0 == code).map(|x| (x.1, x.2)).unwrap_or(("", "Unknown error"));
    let msg = match name {
        "ENOENT" => "немає такого файлу чи теки",
        "EACCES" => "немає доступу",
        "EISDIR" => "це тека, а не файл",
        "ENOTDIR" => "це не тека",
        "ENOSPC" => "немає місця на диску",
        _ => text,
    };
    format!("{}: {}: {}", tool, msg, p)
}

/// Поточний час UTC: (рік, місяць, день, година, хвилина, секунда).
pub fn utc_now() -> (i64, u32, u32, u32, u32, u32) {
    let secs = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0);
    let days = secs.div_euclid(86400);
    let rem = secs.rem_euclid(86400);
    let (y, m, d) = civil(days);
    (y, m, d, (rem / 3600) as u32, (rem % 3600 / 60) as u32, (rem % 60) as u32)
}

/// Дні від 1970-01-01 → дата (алгоритм Хіннанта).
pub fn civil(z: i64) -> (i64, u32, u32) {
    let z = z + 719468;
    let era = z.div_euclid(146097);
    let doe = z.rem_euclid(146097);
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

pub fn iso_now() -> String {
    let (y, mo, d, h, mi, s) = utc_now();
    format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}+00:00", y, mo, d, h, mi, s)
}

/// Текст файлу як open(encoding='utf-8').read(n): строгий UTF-8, універсальні переноси (\r\n і \r → \n).
fn read_text(path: &str, limit: usize) -> Result<Result<String, ()>, std::io::Error> {
    let bytes = std::fs::read(path)?;
    let s = match String::from_utf8(bytes) {
        Ok(s) => s,
        Err(_) => return Ok(Err(())),
    };
    let s = if s.contains('\r') { s.replace("\r\n", "\n").replace('\r', "\n") } else { s };
    if s.len() <= limit || s.chars().count() <= limit {
        return Ok(Ok(s));
    }
    match s.char_indices().nth(limit) {
        Some((b, _)) => Ok(Ok(s[..b].to_string())),
        None => Ok(Ok(s)),
    }
}

pub fn run(it: &mut Interp, name: &str, args: &[V], pos: Pos) -> R<V> {
    match name {
        "оракул" => {
            let h = sha::sha256(show(&args[0], true).as_bytes());
            let k = ((h[1] as u32) << 8 | h[2] as u32) as f64;
            let c = pyf::round(0.3 + 0.69 * k / 65535.0, 2);
            Ok(V::new(Val::Bool(h[0] & 1 == 1), c))
        }
        "жереб" => match &args[0].v {
            Val::Int(n) if n.cmp(&Int::S(1)) != std::cmp::Ordering::Less => Ok(V::int(it.rng.randint1(n))),
            _ => ngr("жереб: потрібне ціле ≥ 1", pos),
        },
        "час" => Ok(V::str(iso_now())),
        "файл.читати" => {
            let real = it.path_ok(name, &args[0].v, pos, false)?;
            let p = path_text(&args[0]);
            match read_text(&real, 2_000_000) {
                Ok(Ok(s)) => Ok(V::str(s)),
                Ok(Err(())) => ngr(format!("файл.читати: не UTF-8: {}", p), pos),
                Err(e) => ngr(os_err("файл.читати", &e, &p), pos),
            }
        }
        "файл.писати" => {
            let real = it.path_ok(name, &args[0].v, pos, true)?;
            let text = match &args[1].v {
                Val::Str(s) => s.clone(),
                _ => return ngr("файл.писати: вміст має бути рядком (для даних — Δ)", pos),
            };
            let p = path_text(&args[0]);
            let r = std::fs::create_dir_all(pathx::dirname(&real)).and_then(|_| std::fs::write(&real, text.s.as_bytes()));
            match r {
                Ok(()) => Ok(V::none()),
                Err(e) => ngr(os_err("файл.писати", &e, &p), pos),
            }
        }
        "файл.список" => {
            let real = it.path_ok(name, &args[0].v, pos, false)?;
            let p = path_text(&args[0]);
            match std::fs::read_dir(&real) {
                Ok(rd) => {
                    let mut names: Vec<String> = Vec::new();
                    for e in rd {
                        match e {
                            Ok(e) => names.push(e.file_name().to_string_lossy().into_owned()),
                            Err(e) => return ngr(os_err("файл.список", &e, &p), pos),
                        }
                    }
                    names.sort();
                    Ok(V::list(names.into_iter().map(V::str).collect()))
                }
                Err(e) => ngr(os_err("файл.список", &e, &p), pos),
            }
        }
        _ => fatal(format!("інструмент «{}» Атанор не виконує", name), Some(pos)),
    }
}

fn path_text(v: &V) -> String {
    match &v.v {
        Val::Str(s) => s.s.to_string(),
        _ => show(v, true),
    }
}

pub fn _unused(_: Rc<()>) {}
