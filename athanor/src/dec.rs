//! Десяткові числа Python (decimal): знак, коефіцієнт, порядок; контексти й сигнали як у libmpdec/_pydecimal.
use crate::int::Int;
use crate::nat::Nat;
use std::cmp::Ordering;

#[derive(Clone, Debug)]
pub struct Dec {
    pub neg: bool,
    pub coef: Nat,
    pub exp: i64,
}

pub const INVALID: u32 = 1;
pub const DIVZERO: u32 = 2;
pub const OVERFLOW: u32 = 4;
pub const UNDERFLOW: u32 = 8;
pub const SUBNORMAL: u32 = 16;
pub const INEXACT: u32 = 32;
pub const ROUNDED: u32 = 64;
pub const CLAMPED: u32 = 128;

/// Назва сигналу, як type(e).__name__ у Python.
/// Чому впала десяткова операція — словами (dec_why еталона; суд 9б: було «(Inexact)»).
pub fn why(s: u32) -> &'static str {
    match s {
        OVERFLOW => "порядок числа завеликий",
        UNDERFLOW | SUBNORMAL => "порядок числа замалий",
        INEXACT | ROUNDED => "точний результат довший за 60 значущих цифр — округліть (≅)",
        DIVZERO => "ділення на нуль",
        INVALID => "недопустима операція з числом",
        _ => "порядок числа поза межами",
    }
}

pub fn signal_name(s: u32) -> &'static str {
    match s {
        INVALID => "InvalidOperation",
        DIVZERO => "DivisionByZero",
        OVERFLOW => "Overflow",
        UNDERFLOW => "Underflow",
        SUBNORMAL => "Subnormal",
        INEXACT => "Inexact",
        ROUNDED => "Rounded",
        _ => "Clamped",
    }
}

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Round {
    HalfEven,
    HalfUp,
    Down,
    Floor,
}

#[derive(Clone, Copy, Debug)]
pub struct Ctx {
    pub prec: u64,
    pub emax: i64,
    pub emin: i64,
    pub round: Round,
    pub traps: u32,
}

pub const DEC_EXP: i64 = 30_000;

pub fn dec_ctx() -> Ctx {
    Ctx { prec: 28, emax: DEC_EXP, emin: -DEC_EXP, round: Round::HalfEven, traps: INVALID | DIVZERO | OVERFLOW }
}

pub fn wide_ctx() -> Ctx {
    Ctx { prec: 2 * DEC_EXP as u64 + 40, emax: DEC_EXP + 20, emin: -DEC_EXP - 20, round: Round::HalfEven,
          traps: INVALID | DIVZERO | OVERFLOW }
}

pub fn exact_ctx() -> Ctx {
    Ctx { prec: 60, emax: DEC_EXP, emin: -DEC_EXP, round: Round::HalfEven, traps: INVALID | DIVZERO | OVERFLOW | INEXACT }
}

/// Перший сигнал, що зупиняє (у порядку signal_map _decimal).
fn raise(flags: u32, ctx: &Ctx) -> Result<(), u32> {
    let t = flags & ctx.traps;
    if t == 0 {
        return Ok(());
    }
    for s in [INVALID, DIVZERO, OVERFLOW, UNDERFLOW, SUBNORMAL, INEXACT, ROUNDED, CLAMPED] {
        if t & s != 0 {
            return Err(s);
        }
    }
    Ok(())
}

/// Відкинути drop останніх цифр із округленням: (результат, чи було неточно).
fn round_drop(coef: &Nat, drop: u64, neg: bool, mode: Round) -> (Nat, bool) {
    if drop == 0 {
        return (coef.clone(), false);
    }
    let nd = coef.ndigits();
    let (q, r) = if drop > nd + 1 { (Nat::zero(), coef.clone()) } else { coef.divmod(&Nat::pow10(drop)) };
    if r.is_zero() {
        return (q, false);
    }
    let up = match mode {
        Round::Down => false,
        Round::Floor => neg,
        Round::HalfUp | Round::HalfEven => {
            // r порівняти з половиною 10^drop: 2r ? 10^drop
            let two_r = r.mul_small(2);
            let c = if drop > nd + 1 { Ordering::Less } else { two_r.cmp(&Nat::pow10(drop)) };
            match c {
                Ordering::Greater => true,
                Ordering::Less => false,
                Ordering::Equal => mode == Round::HalfUp || q.is_odd(),
            }
        }
    };
    (if up { q.add_small(1) } else { q }, true)
}

impl Dec {
    pub fn zero() -> Dec {
        Dec { neg: false, coef: Nat::zero(), exp: 0 }
    }

    pub fn from_int(i: &Int) -> Dec {
        let (neg, mag) = i.parts();
        Dec { neg, coef: mag, exp: 0 }
    }

    pub fn is_zero(&self) -> bool {
        self.coef.is_zero()
    }

    pub fn digits(&self) -> u64 {
        self.coef.ndigits()
    }

    pub fn adjusted(&self) -> i64 {
        self.exp + self.digits() as i64 - 1
    }

    fn finalize(mut self, ctx: &Ctx, mut flags: u32) -> Result<Dec, u32> {
        let prec = ctx.prec as i64;
        let etiny = ctx.emin - (prec - 1);
        if self.coef.is_zero() {
            if self.exp > ctx.emax {
                self.exp = ctx.emax;
                flags |= CLAMPED;
            } else if self.exp < etiny {
                self.exp = etiny;
                flags |= CLAMPED;
            }
            raise(flags, ctx)?;
            return Ok(self);
        }
        let digits = self.digits() as i64;
        let adj = self.exp + digits - 1;
        if adj > ctx.emax {
            flags |= OVERFLOW | INEXACT | ROUNDED;
            raise(flags, ctx)?;
            return Err(OVERFLOW); // нескінченності в мові немає; усі контексти мови зупиняють Overflow
        }
        if adj < ctx.emin {
            flags |= SUBNORMAL;
            if self.exp < etiny {
                let (q, inexact) = round_drop(&self.coef, (etiny - self.exp) as u64, self.neg, ctx.round);
                self.coef = q;
                self.exp = etiny;
                flags |= ROUNDED;
                if inexact {
                    flags |= INEXACT | UNDERFLOW;
                }
                if self.coef.is_zero() {
                    flags |= CLAMPED;
                }
            }
            raise(flags, ctx)?;
            return Ok(self);
        }
        if digits > prec {
            let drop = (digits - prec) as u64;
            let (mut q, inexact) = round_drop(&self.coef, drop, self.neg, ctx.round);
            let mut exp = self.exp + drop as i64;
            if q.ndigits() as i64 > prec {
                q = q.divmod_small(10).0;
                exp += 1;
            }
            if exp + prec - 1 > ctx.emax {
                flags |= OVERFLOW | INEXACT | ROUNDED;
                raise(flags, ctx)?;
                return Err(OVERFLOW);
            }
            self.coef = q;
            self.exp = exp;
            flags |= ROUNDED;
            if inexact {
                flags |= INEXACT;
            }
        }
        raise(flags, ctx)?;
        Ok(self)
    }

    /// Звести до спільного порядку (найменшого): (коеф. a, коеф. b, порядок).
    fn align(a: &Dec, b: &Dec) -> (Nat, Nat, i64) {
        let e = a.exp.min(b.exp);
        (a.coef.mul_pow10((a.exp - e) as u64), b.coef.mul_pow10((b.exp - e) as u64), e)
    }

    pub fn add(&self, o: &Dec, ctx: &Ctx) -> Result<Dec, u32> {
        let (ca, cb, e) = Dec::align(self, o);
        let (neg, coef) = if self.neg == o.neg {
            (self.neg, ca.add(&cb))
        } else {
            match ca.cmp(&cb) {
                Ordering::Greater => (self.neg, ca.sub(&cb)),
                Ordering::Less => (o.neg, cb.sub(&ca)),
                Ordering::Equal => (ctx.round == Round::Floor, Nat::zero()),
            }
        };
        let neg = if coef.is_zero() && self.neg == o.neg { self.neg } else { neg };
        Dec { neg, coef, exp: e }.finalize(ctx, 0)
    }

    /// ＋ － × у exact_ctx над малими (знак, коефіцієнт до 64 біт, порядок): те саме, що add/sub/mul + finalize, без
    /// довгої арифметики. Порядки — у ±20 000 (межі контексту ±30 000), вирівнювання — до 19 розрядів: коефіцієнт
    /// результату вміщається в u128 (≤ 39 цифр < prec 60), тож finalize нічого не округлює, не обрізає й не сигналить.
    /// Інакше None — загальний шлях.
    pub fn small_exact(op: char, a: (bool, u64, i64), b: (bool, u64, i64)) -> Option<Dec> {
        const SAFE: i64 = 20_000;
        let ((na, ca, ea), (nb, cb, eb)) = (a, b);
        if ea.abs() > SAFE || eb.abs() > SAFE {
            return None;
        }
        let (neg, coef, exp) = if op == '×' {
            if (ea + eb).abs() > SAFE {
                return None;
            }
            (na != nb, ca as u128 * cb as u128, ea + eb)
        } else {
            let nb = if op == '－' { !nb } else { nb }; // sub = add(negate)
            let e = ea.min(eb);
            let (da, db) = ((ea - e) as u32, (eb - e) as u32);
            if da > 19 || db > 19 {
                return None;
            }
            let (xa, xb) = (ca as u128 * 10u128.pow(da), cb as u128 * 10u128.pow(db));
            if na == nb {
                (na, xa + xb, e) // нуль — зі знаком доданків, як в add
            } else {
                match xa.cmp(&xb) {
                    Ordering::Greater => (na, xa - xb, e),
                    Ordering::Less => (nb, xb - xa, e),
                    Ordering::Equal => (false, 0, e), // exact_ctx — HalfEven, не Floor: нуль додатний
                }
            }
        };
        Some(Dec { neg, coef: Nat::from_u128(coef), exp })
    }

    /// -d у контексті (як Decimal.__neg__): нуль — додатний; результат округлено до контексту.
    pub fn minus(&self, ctx: &Ctx) -> Result<Dec, u32> {
        let neg = if self.is_zero() { false } else { !self.neg };
        Dec { neg, coef: self.coef.clone(), exp: self.exp }.finalize(ctx, 0)
    }

    pub fn fix(self, ctx: &Ctx) -> Result<Dec, u32> {
        self.finalize(ctx, 0)
    }

    pub fn negate(&self) -> Dec {
        Dec { neg: !self.neg, coef: self.coef.clone(), exp: self.exp }
    }

    pub fn sub(&self, o: &Dec, ctx: &Ctx) -> Result<Dec, u32> {
        self.add(&o.negate(), ctx)
    }

    pub fn mul(&self, o: &Dec, ctx: &Ctx) -> Result<Dec, u32> {
        Dec { neg: self.neg != o.neg, coef: self.coef.mul(&o.coef), exp: self.exp + o.exp }.finalize(ctx, 0)
    }

    /// Ділення (o ≠ 0) — як _pydecimal __truediv__.
    pub fn div(&self, o: &Dec, ctx: &Ctx) -> Result<Dec, u32> {
        let neg = self.neg != o.neg;
        if self.is_zero() {
            return Dec { neg, coef: Nat::zero(), exp: self.exp - o.exp }.finalize(ctx, 0);
        }
        let shift = o.digits() as i64 - self.digits() as i64 + ctx.prec as i64 + 1;
        let mut exp = self.exp - o.exp - shift;
        let (mut coef, rem) = if shift >= 0 {
            self.coef.mul_pow10(shift as u64).divmod(&o.coef)
        } else {
            self.coef.divmod(&o.coef.mul_pow10((-shift) as u64))
        };
        if !rem.is_zero() {
            if coef.divmod_small(5).1 == 0 {
                coef = coef.add_small(1);
            }
        } else {
            let ideal = self.exp - o.exp;
            while exp < ideal {
                let (q, r) = coef.divmod_small(10);
                if r != 0 {
                    break;
                }
                coef = q;
                exp += 1;
            }
        }
        Dec { neg, coef, exp }.finalize(ctx, 0)
    }

    /// Остача (знак — як у діленого), як _pydecimal __mod__; o ≠ 0.
    pub fn rem(&self, o: &Dec, ctx: &Ctx) -> Result<Dec, u32> {
        let ideal = self.exp.min(o.exp);
        let expdiff = self.adjusted() - o.adjusted();
        let r = if self.is_zero() || expdiff <= -2 {
            self.rescale(ideal, Round::HalfEven)
        } else {
            if expdiff > ctx.prec as i64 {
                raise(INVALID, ctx)?;
                return Err(INVALID);
            }
            let (ca, cb, _) = Dec::align(self, o);
            let (q, r) = ca.divmod(&cb);
            if q.cmp(&Nat::pow10(ctx.prec)) != Ordering::Less {
                raise(INVALID, ctx)?;
                return Err(INVALID);
            }
            Dec { neg: self.neg, coef: r, exp: ideal }
        };
        r.finalize(ctx, 0)
    }

    /// _rescale: до порядку exp з округленням.
    pub fn rescale(&self, exp: i64, mode: Round) -> Dec {
        if self.is_zero() {
            return Dec { neg: self.neg, coef: Nat::zero(), exp };
        }
        if self.exp >= exp {
            return Dec { neg: self.neg, coef: self.coef.mul_pow10((self.exp - exp) as u64), exp };
        }
        let (q, _) = round_drop(&self.coef, (exp - self.exp) as u64, self.neg, mode);
        Dec { neg: self.neg, coef: q, exp }
    }

    /// quantize(10^exp, mode) у контексті ctx (як _pydecimal).
    pub fn quantize(&self, exp: i64, mode: Round, ctx: &Ctx) -> Result<Dec, u32> {
        let etiny = ctx.emin - (ctx.prec as i64 - 1);
        if !(etiny <= exp && exp <= ctx.emax) {
            raise(INVALID, ctx)?;
            return Err(INVALID);
        }
        if self.is_zero() {
            return Dec { neg: self.neg, coef: Nat::zero(), exp }.finalize(ctx, 0);
        }
        let adj = self.adjusted();
        if adj > ctx.emax || adj - exp + 1 > ctx.prec as i64 {
            raise(INVALID, ctx)?;
            return Err(INVALID);
        }
        let ans = self.rescale(exp, mode);
        if (!ans.is_zero() && ans.adjusted() > ctx.emax) || ans.digits() > ctx.prec {
            raise(INVALID, ctx)?;
            return Err(INVALID);
        }
        let mut flags = 0;
        if !ans.is_zero() && ans.adjusted() < ctx.emin {
            flags |= SUBNORMAL;
        }
        if ans.exp > self.exp {
            if ans.cmp(self) != Ordering::Equal {
                flags |= INEXACT;
            }
            flags |= ROUNDED;
        }
        ans.finalize(ctx, flags)
    }

    pub fn is_integral(&self) -> bool {
        if self.exp >= 0 || self.is_zero() {
            return true;
        }
        let tz = self.coef.trailing_zeros10();
        tz >= (-self.exp) as u64
    }

    /// int(d): до нуля.
    pub fn trunc(&self) -> Int {
        if self.exp >= 0 {
            return Int::from_big(self.neg, self.coef.mul_pow10(self.exp as u64));
        }
        let (q, _) = round_drop(&self.coef, (-self.exp) as u64, self.neg, Round::Down);
        Int::from_big(self.neg, q)
    }

    /// math.floor(d).
    pub fn floor(&self) -> Int {
        if self.exp >= 0 {
            return self.trunc();
        }
        let (q, _) = round_drop(&self.coef, (-self.exp) as u64, self.neg, Round::Floor);
        Int::from_big(self.neg, q)
    }

    pub fn cmp(&self, o: &Dec) -> Ordering {
        let (az, bz) = (self.is_zero(), o.is_zero());
        if az && bz {
            return Ordering::Equal;
        }
        let sa = if az { 0 } else if self.neg { -1 } else { 1 };
        let sb = if bz { 0 } else if o.neg { -1 } else { 1 };
        if sa != sb {
            return sa.cmp(&sb);
        }
        // однаковий знак, обидва ненульові
        let mag = {
            let (aa, ba) = (self.adjusted(), o.adjusted());
            if aa != ba {
                aa.cmp(&ba)
            } else {
                let (ca, cb, _) = Dec::align(self, o);
                ca.cmp(&cb)
            }
        };
        if sa < 0 { mag.reverse() } else { mag }
    }

    /// Точне значення float (Decimal.from_float).
    pub fn from_f64(f: f64) -> Dec {
        if f == 0.0 {
            return Dec { neg: f.is_sign_negative(), coef: Nat::zero(), exp: 0 };
        }
        let bits = f.to_bits();
        let neg = bits >> 63 == 1;
        let e = ((bits >> 52) & 0x7ff) as i64;
        let m = bits & ((1u64 << 52) - 1);
        let (mut mant, mut exp2) = if e == 0 { (m, -1074) } else { (m | 1 << 52, e - 1075) };
        while mant & 1 == 0 && exp2 < 0 {
            mant >>= 1;
            exp2 += 1;
        }
        if exp2 >= 0 {
            let mut c = Nat::from_u64(mant);
            for _ in 0..exp2 {
                c = c.mul_small(2);
            }
            Dec { neg, coef: c, exp: 0 }
        } else {
            // mant / 2^k = mant·5^k / 10^k
            let k = (-exp2) as u64;
            let mut c = Nat::from_u64(mant);
            for _ in 0..k {
                c = c.mul_small(5);
            }
            Dec { neg, coef: c, exp: -(k as i64) }
        }
    }

    /// str(d) — науковий запис Python.
    pub fn to_sci(&self) -> String {
        let s = self.coef.to_dec();
        let sign = if self.neg { "-" } else { "" };
        let left = self.exp + s.len() as i64;
        let dot = if self.exp <= 0 && left > -6 { left } else { 1 };
        let (ip, fp) = if dot <= 0 {
            ("0".to_string(), format!(".{}{}", "0".repeat((-dot) as usize), s))
        } else if dot >= s.len() as i64 {
            (format!("{}{}", s, "0".repeat((dot - s.len() as i64) as usize)), String::new())
        } else {
            (s[..dot as usize].to_string(), format!(".{}", &s[dot as usize..]))
        };
        let e = if left == dot { String::new() } else { format!("E{:+}", left - dot) };
        format!("{}{}{}{}", sign, ip, fp, e)
    }

    /// format(d, 'f').
    pub fn to_fixed(&self) -> String {
        let d = if self.is_zero() && self.exp > 0 { Dec { neg: self.neg, coef: Nat::zero(), exp: 0 } } else { self.clone() };
        let s = d.coef.to_dec();
        let sign = if d.neg { "-" } else { "" };
        let dot = d.exp + s.len() as i64;
        let (ip, fp) = if dot < 0 {
            ("0".to_string(), format!("{}{}", "0".repeat((-dot) as usize), s))
        } else if dot > s.len() as i64 {
            (format!("{}{}", s, "0".repeat((dot - s.len() as i64) as usize)), String::new())
        } else {
            let ip = &s[..dot as usize];
            (if ip.is_empty() { "0".to_string() } else { ip.to_string() }, s[dot as usize..].to_string())
        };
        if fp.is_empty() { format!("{}{}", sign, ip) } else { format!("{}{}.{}", sign, ip, fp) }
    }

    pub fn to_f64(&self) -> f64 {
        self.to_sci().parse().unwrap_or(0.0)
    }

    /// Рядок за синтаксисом Decimal(str) (після strip): Some(скінченне) / Err(true) — нескінченне чи NaN / Err(false) — не число.
    pub fn parse(t: &str) -> Result<Dec, bool> {
        let b = t.as_bytes();
        let mut i = 0;
        let mut neg = false;
        if i < b.len() && (b[i] == b'+' || b[i] == b'-') {
            neg = b[i] == b'-';
            i += 1;
        }
        let rest = &t[i..];
        let low = rest.to_ascii_lowercase();
        if low == "inf" || low == "infinity" {
            return Err(true);
        }
        let nan = low.strip_prefix('s').unwrap_or(&low);
        if let Some(d) = nan.strip_prefix("nan") {
            if d.bytes().all(|c| c.is_ascii_digit()) {
                return Err(true);
            }
            return Err(false);
        }
        let s0 = i;
        while i < b.len() && b[i].is_ascii_digit() {
            i += 1;
        }
        let ip = &t[s0..i];
        let mut fp = "";
        if i < b.len() && b[i] == b'.' {
            i += 1;
            let f0 = i;
            while i < b.len() && b[i].is_ascii_digit() {
                i += 1;
            }
            fp = &t[f0..i];
        }
        if ip.is_empty() && fp.is_empty() {
            return Err(false);
        }
        let mut exp: i64 = 0;
        if i < b.len() && (b[i] == b'e' || b[i] == b'E') {
            i += 1;
            let mut eneg = false;
            if i < b.len() && (b[i] == b'+' || b[i] == b'-') {
                eneg = b[i] == b'-';
                i += 1;
            }
            let e0 = i;
            while i < b.len() && b[i].is_ascii_digit() {
                i += 1;
            }
            if e0 == i {
                return Err(false);
            }
            let es = t[e0..i].trim_start_matches('0');
            if es.len() > 15 {
                exp = if eneg { -(1i64 << 55) } else { 1i64 << 55 }; // поза будь-якими межами мови
            } else {
                exp = es.parse::<i64>().unwrap_or(0);
                if eneg {
                    exp = -exp;
                }
            }
        }
        if i != b.len() {
            return Err(false);
        }
        let digits = format!("{}{}", ip, fp);
        let digits = digits.trim_start_matches('0');
        let coef = if digits.is_empty() { Nat::zero() } else { Nat::from_dec(digits) };
        Ok(Dec { neg, coef, exp: exp - fp.len() as i64 })
    }
}
