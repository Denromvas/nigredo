//! Дати ◷ — як nigredo.date_op: date/datetime.fromisoformat Python (лише підмножина з регулярки еталона), різниця в
//! днях (ціле для дат, десяткове з часом — 28 цифр), додавання днів (timedelta), isoformat.
use crate::dec::{self, Dec};
use crate::int::Int;
use crate::nat::Nat;

const DAY_US: i128 = 86_400_000_000;

#[derive(Clone, Copy)]
pub struct Dt {
    pub days: i64,          // від 1970-01-01
    pub us: i64,            // мікросекунд від початку доби (місцевого)
    pub off: Option<i64>,   // зсув поясу в секундах
    pub date_only: bool,
}

pub fn days_from_civil(y: i64, m: u32, d: u32) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y.rem_euclid(400);
    let mp = (m as i64 + 9) % 12;
    let doy = (153 * mp + 2) / 5 + d as i64 - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

fn dim(y: i64, m: u32) -> u32 {
    match m {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        _ => {
            if (y % 4 == 0 && y % 100 != 0) || y % 400 == 0 {
                29
            } else {
                28
            }
        }
    }
}

fn num(b: &[u8]) -> i64 {
    b.iter().fold(0i64, |a, &c| a * 10 + (c - b'0') as i64)
}

/// _iso: Some — дата; None — «не дата ISO».
pub fn iso(s: &str) -> Option<Dt> {
    let b = s.as_bytes();
    let dig = |i: usize| i < b.len() && b[i].is_ascii_digit();
    let digs = |i: usize, n: usize| (i..i + n).all(dig);
    if !(digs(0, 4) && b.get(4) == Some(&b'-') && digs(5, 2) && b.get(7) == Some(&b'-') && digs(8, 2)) {
        return None;
    }
    let (y, m, d) = (num(&b[0..4]), num(&b[5..7]) as u32, num(&b[8..10]) as u32);
    let mut i = 10;
    let mut us = 0i64;
    let mut off = None;
    let date_only = b.len() == 10;
    if !date_only {
        if !(b.get(10) == Some(&b'T') && digs(11, 2) && b.get(13) == Some(&b':') && digs(14, 2)) {
            return None;
        }
        let (hh, mm) = (num(&b[11..13]), num(&b[14..16]));
        i = 16;
        let mut ss = 0;
        let mut frac = 0;
        if b.get(i) == Some(&b':') && digs(i + 1, 2) {
            ss = num(&b[i + 1..i + 3]);
            i += 3;
            if b.get(i) == Some(&b'.') && dig(i + 1) {
                let mut j = i + 1;
                while dig(j) {
                    j += 1;
                }
                let n = j - i - 1;
                if n > 6 {
                    return None;
                }
                frac = num(&b[i + 1..j]) * 10i64.pow((6 - n) as u32);
                i = j;
            }
        }
        if b.get(i) == Some(&b'Z') {
            off = Some(0);
            i += 1;
        } else if matches!(b.get(i), Some(b'+') | Some(b'-')) && digs(i + 1, 2) && b.get(i + 3) == Some(&b':') && digs(i + 4, 2) {
            let sign = if b[i] == b'-' { -1 } else { 1 };
            let o = num(&b[i + 1..i + 3]) * 3600 + num(&b[i + 4..i + 6]) * 60;
            if o >= 86400 {
                return None;
            }
            off = Some(sign * o);
            i += 6;
        }
        if hh > 23 || mm > 59 || ss > 59 {
            return None;
        }
        us = ((hh * 60 + mm) * 60 + ss) * 1_000_000 + frac;
    }
    if i != b.len() {
        return None;
    }
    if !(1..=9999).contains(&y) || !(1..=12).contains(&m) || d < 1 || d > dim(y, m) {
        return None;
    }
    Some(Dt { days: days_from_civil(y, m, d), us, off, date_only })
}

pub fn fmt(t: &Dt) -> String {
    let (y, m, d) = crate::tools::civil(t.days);
    if t.date_only {
        return format!("{:04}-{:02}-{:02}", y, m, d);
    }
    let secs = t.us / 1_000_000;
    let frac = t.us % 1_000_000;
    let mut s = format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}", y, m, d, secs / 3600, secs / 60 % 60, secs % 60);
    if frac != 0 {
        s.push_str(&format!(".{:06}", frac));
    }
    if let Some(o) = t.off {
        let (sign, a) = if o < 0 { ('-', -o) } else { ('+', o) };
        s.push_str(&format!("{}{:02}:{:02}", sign, a / 3600, a / 60 % 60));
    }
    s
}

fn in_range(days: i64) -> bool {
    let lo = days_from_civil(1, 1, 1);
    let hi = days_from_civil(9999, 12, 31);
    (lo..=hi).contains(&days)
}

pub enum DateErr {
    Tz,
    Range,
    Dec(u32),
}

/// Різниця b − a у днях: ціле (дві дати) або десяткове.
pub fn diff(a: &Dt, b: &Dt) -> Result<crate::value::Val, DateErr> {
    use crate::value::Val;
    if a.date_only && b.date_only {
        return Ok(Val::Int(Int::S(b.days - a.days)));
    }
    if a.off.is_some() != b.off.is_some() {
        return Err(DateErr::Tz);
    }
    let abs = |t: &Dt| t.days as i128 * DAY_US + t.us as i128 - t.off.unwrap_or(0) as i128 * 1_000_000;
    let us = abs(b) - abs(a);
    let q = Dec { neg: us < 0, coef: Nat::from_u128(us.unsigned_abs()), exp: 0 }
        .div(&Dec { neg: false, coef: Nat::from_u128(DAY_US as u128), exp: 0 }, &dec::dec_ctx())
        .map_err(DateErr::Dec)?;
    if q.is_integral() {
        return Ok(Val::Int(q.trunc()));
    }
    Ok(Val::Dec(std::rc::Rc::new(q)))
}

/// a + n днів (n — десяткове): рядок isoformat.
pub fn add(a: &Dt, n: &Dec) -> Result<String, DateErr> {
    if a.date_only && n.is_integral() {
        let k = n.trunc();
        let k = match k.to_i64() {
            Some(k) if k.abs() <= 999_999_999 => k,
            _ => return Err(DateErr::Range),
        };
        let days = a.days + k;
        if !in_range(days) {
            return Err(DateErr::Range);
        }
        return Ok(fmt(&Dt { days, ..*a }));
    }
    let ctx = dec::dec_ctx();
    let m = n
        .mul(&Dec { neg: false, coef: Nat::from_u64(86400), exp: 0 }, &ctx)
        .and_then(|x| x.mul(&Dec { neg: false, coef: Nat::from_u64(1_000_000), exp: 0 }, &ctx))
        .map_err(DateErr::Dec)?;
    let k = m.trunc();
    let k = match k.to_i64() {
        Some(k) => k as i128,
        None => return Err(DateErr::Range),
    };
    // timedelta(microseconds=k): дні не понад 999 999 999
    if k.div_euclid(DAY_US).abs() > 999_999_999 {
        return Err(DateErr::Range);
    }
    let base = a.days as i128 * DAY_US + a.us as i128 + k;
    let days = base.div_euclid(DAY_US) as i64;
    let us = base.rem_euclid(DAY_US) as i64;
    if !in_range(days) {
        return Err(DateErr::Range);
    }
    Ok(fmt(&Dt { days, us, off: a.off, date_only: false }))
}
