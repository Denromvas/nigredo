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
    match name {
        "оракул" | "жереб" | "час" | "файл.читати" | "файл.писати" | "файл.список" => true,
        "бд.читати" | "бд.писати" => crate::sqlite::available(), // та сама libsqlite3, що в Python (dlopen)
        _ => false,
    }
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
    let secs = crate::sys::now_secs();
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
    // TextIOWrapper.read(n) бере не більше ~8n байтів (n символів по ≤ 4 байти й один шматок понад них) — решту файлу
    // не читаємо (суд 9: файл на 500 МБ читався цілим)
    let cap = limit.saturating_mul(8).saturating_add(65536);
    let bytes = crate::sys::read_limited(path, cap)?;
    let s = match String::from_utf8(bytes) {
        Ok(s) => s,
        Err(e) => return Ok(read_chunked(e.as_bytes(), limit)),
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

/// Невалідний UTF-8 — так, як читає його TextIOWrapper.read(n) (CPython 3.13): шматками (перший — n байтів, далі —
/// за співвідношенням байтів до символів попереднього шматка, щонайменше 8192), кожен декодується строго (незавершений
/// символ у кінці шматка чекає наступного), \r у кінці шматка — теж; помилка — лише якщо погані байти в прочитаних
/// шматках, а прочитано рівно стільки, щоб набрати n символів.
fn read_chunked(bytes: &[u8], limit: usize) -> Result<String, ()> {
    let (mut pos, mut ratio, mut remaining) = (0usize, 0.0f64, limit);
    let mut pending: Vec<u8> = Vec::new();
    let mut pending_cr = false;
    let mut out = String::new();
    while remaining > 0 {
        let hint = (ratio.max(1.0) * remaining as f64) as usize;
        let size = hint.max(8192);
        let chunk = &bytes[pos..(pos + size).min(bytes.len())];
        pos += chunk.len();
        let eof = chunk.is_empty();
        let mut data = std::mem::take(&mut pending);
        data.extend_from_slice(chunk);
        let decoded: &str = match std::str::from_utf8(&data) {
            Ok(t) => t,
            Err(e) if e.error_len().is_none() && !eof => {
                pending = data[e.valid_up_to()..].to_vec();
                std::str::from_utf8(&data[..e.valid_up_to()]).unwrap()
            }
            Err(_) => return Err(()),
        };
        let mut text = String::new();
        if pending_cr && (eof || !decoded.is_empty()) {
            text.push('\r');
            pending_cr = false;
        }
        text.push_str(decoded);
        if !eof && text.ends_with('\r') {
            text.pop();
            pending_cr = true;
        }
        if text.contains('\r') {
            text = text.replace("\r\n", "\n").replace('\r', "\n");
        }
        let nchars = text.chars().count();
        ratio = if nchars > 0 { chunk.len() as f64 / nchars as f64 } else { 0.0 };
        match text.char_indices().nth(remaining) {
            Some((b, _)) => {
                out.push_str(&text[..b]);
                remaining = 0;
            }
            None => {
                out.push_str(&text);
                remaining -= nchars;
            }
        }
        if eof && nchars == 0 {
            break;
        }
    }
    Ok(out)
}

pub fn run(it: &mut Interp, name: &str, args: &[V], pos: Pos) -> R<V> {
    match name {
        "оракул" => {
            let h = sha::sha256(show(&args[0], true)?.as_bytes());
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
            let max = it.max_size as usize;
            match read_text(&real, max.saturating_add(1)) {
                // довший за --розмір — помилка, а не тихе обрізання (суд 9)
                Ok(Ok(s)) if s.chars().nth(max).is_some() => {
                    ngr(format!("файл.читати: у файлі понад {} символів (--розмір) — частину не читаю мовчки: {}", max, p), pos)
                }
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
            let r = crate::sys::write_file(&pathx::dirname(&real), &real, text.s.as_bytes());
            match r {
                Ok(()) => Ok(V::none()),
                Err(e) => ngr(os_err("файл.писати", &e, &p), pos),
            }
        }
        "файл.список" => {
            let real = it.path_ok(name, &args[0].v, pos, false)?;
            let p = path_text(&args[0]);
            match crate::sys::list_dir(&real) {
                Ok(mut names) => {
                    names.sort();
                    Ok(V::list(names.into_iter().map(V::str).collect()))
                }
                Err(e) => ngr(os_err("файл.список", &e, &p), pos),
            }
        }
        "бд.читати" => crate::sqlite::run(it, name, args, pos, false),
        "бд.писати" => crate::sqlite::run(it, name, args, pos, true),
        _ => fatal(format!("інструмент «{}» Атанор не виконує", name), Some(pos)),
    }
}

fn path_text(v: &V) -> String {
    match &v.v {
        Val::Str(s) => s.s.to_string(),
        _ => show(v, true).unwrap_or_default(), // не рядок — відмова раніше, ніж знадобиться показ
    }
}

pub fn _unused(_: Rc<()>) {}
