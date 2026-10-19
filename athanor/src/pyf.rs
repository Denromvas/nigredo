//! float як у Python: repr і round(x, n).
use crate::dec::{Dec, Round};

/// repr(float) у Python ('r', найкоротший запис, що відновлює те саме число).
pub fn repr(f: f64) -> String {
    if f.is_nan() {
        return "nan".into();
    }
    if f.is_infinite() {
        return if f > 0.0 { "inf".into() } else { "-inf".into() };
    }
    if f == 0.0 {
        return if f.is_sign_negative() { "-0.0".into() } else { "0.0".into() };
    }
    // найкоротші цифри — з {:e} Rust (той самий критерій, що й у Python: найкоротше, що відновлюється)
    let e = format!("{:e}", f.abs());
    let (mant, ex) = e.split_once('e').unwrap();
    let mut digits: String = mant.chars().filter(|c| *c != '.').collect();
    let mut exp10: i64 = ex.parse().unwrap();
    if digits.len() >= 16 {
        // два найкоротші записи можуть бути однаково близькі: Python (dtoa) бере найближчий, при рівності — парний
        let exact = Dec::from_f64(f.abs());
        let n = digits.len() as i64;
        let r = exact.rescale(exact.adjusted() - n + 1, Round::HalfEven);
        let s = r.coef.to_dec();
        if s.len() as i64 == n {
            digits = s;
            exp10 = r.exp + n - 1;
        }
    }
    let decpt = exp10 + 1; // значення = 0.d1d2… × 10^decpt
    let sign = if f < 0.0 { "-" } else { "" };
    let nd = digits.len() as i64;
    if decpt <= -4 || decpt > 16 {
        let m = if nd > 1 { format!("{}.{}", &digits[..1], &digits[1..]) } else { digits.clone() };
        let x = decpt - 1;
        return format!("{}{}e{}{:02}", sign, m, if x < 0 { '-' } else { '+' }, x.abs());
    }
    if decpt <= 0 {
        return format!("{}0.{}{}", sign, "0".repeat((-decpt) as usize), digits);
    }
    if decpt >= nd {
        return format!("{}{}{}.0", sign, digits, "0".repeat((decpt - nd) as usize));
    }
    format!("{}{}.{}", sign, &digits[..decpt as usize], &digits[decpt as usize..])
}

/// round(x, n) для float: точне десяткове значення, половина — до парного, назад у float.
pub fn round(x: f64, n: i64) -> f64 {
    if !x.is_finite() || x == 0.0 {
        return x;
    }
    let d = Dec::from_f64(x).rescale(-n, Round::HalfEven);
    let s = d.to_sci();
    let r: f64 = s.parse().unwrap_or(x);
    if r == 0.0 && x < 0.0 { -0.0 } else { r }
}

/// fmt_num для float: ціле до 1e15 — без «.0».
pub fn show(f: f64) -> String {
    if f.is_finite() && f.fract() == 0.0 && f.abs() < 1e15 {
        return format!("{}", f as i64);
    }
    repr(f)
}
