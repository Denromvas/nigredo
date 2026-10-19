//! Цілі Python: мале (i64) або велике (знак + Nat). Ділення й остача — до мінус нескінченності, як у Python.
use crate::nat::Nat;
use std::cmp::Ordering;
use std::rc::Rc;

#[derive(Clone, Debug)]
pub enum Int {
    S(i64),
    B(Rc<Big>),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Big {
    pub neg: bool,
    pub mag: Nat,
}

impl Int {
    pub fn from_big(neg: bool, mag: Nat) -> Int {
        if let Some(x) = mag.to_u64() {
            if !neg && x <= i64::MAX as u64 {
                return Int::S(x as i64);
            }
            if neg && x <= 1u64 << 63 {
                return Int::S((x as i64).wrapping_neg());
            }
        }
        Int::B(Rc::new(Big { neg: neg && !mag.is_zero(), mag }))
    }

    pub fn parts(&self) -> (bool, Nat) {
        match self {
            Int::S(x) => (*x < 0, Nat::from_u64(x.unsigned_abs())),
            Int::B(b) => (b.neg, b.mag.clone()),
        }
    }

    pub fn is_zero(&self) -> bool {
        matches!(self, Int::S(0))
    }

    pub fn is_neg(&self) -> bool {
        match self {
            Int::S(x) => *x < 0,
            Int::B(b) => b.neg,
        }
    }

    pub fn to_i64(&self) -> Option<i64> {
        match self {
            Int::S(x) => Some(*x),
            Int::B(_) => None,
        }
    }

    pub fn bit_length(&self) -> u64 {
        match self {
            Int::S(x) => 64 - x.unsigned_abs().leading_zeros() as u64,
            Int::B(b) => b.mag.bits(),
        }
    }

    pub fn add(&self, o: &Int) -> Int {
        if let (Int::S(a), Int::S(b)) = (self, o) {
            if let Some(r) = a.checked_add(*b) {
                return Int::S(r);
            }
        }
        let (an, am) = self.parts();
        let (bn, bm) = o.parts();
        add_signed(an, &am, bn, &bm)
    }

    pub fn neg(&self) -> Int {
        match self {
            Int::S(x) => match x.checked_neg() {
                Some(r) => Int::S(r),
                None => Int::from_big(false, Nat::from_u64(1u64 << 63)),
            },
            Int::B(b) => Int::from_big(!b.neg, b.mag.clone()),
        }
    }

    pub fn sub(&self, o: &Int) -> Int {
        if let (Int::S(a), Int::S(b)) = (self, o) {
            if let Some(r) = a.checked_sub(*b) {
                return Int::S(r);
            }
        }
        let (an, am) = self.parts();
        let (bn, bm) = o.parts();
        add_signed(an, &am, !bn, &bm)
    }

    pub fn mul(&self, o: &Int) -> Int {
        if let (Int::S(a), Int::S(b)) = (self, o) {
            if let Some(r) = a.checked_mul(*b) {
                return Int::S(r);
            }
        }
        let (an, am) = self.parts();
        let (bn, bm) = o.parts();
        Int::from_big(an != bn, am.mul(&bm))
    }

    /// (x // y, x % y) як у Python; y ≠ 0.
    pub fn divmod(&self, o: &Int) -> (Int, Int) {
        if let (Int::S(a), Int::S(b)) = (self, o) {
            if !(*a == i64::MIN && *b == -1) {
                let mut q = a / b;
                let mut r = a % b;
                if r != 0 && ((r < 0) != (*b < 0)) {
                    q -= 1;
                    r += b;
                }
                return (Int::S(q), Int::S(r));
            }
        }
        let (an, am) = self.parts();
        let (bn, bm) = o.parts();
        let (q, r) = am.divmod(&bm);
        let mut qi = Int::from_big(an != bn, q);
        let mut ri = Int::from_big(an, r);
        if !ri.is_zero() && (ri.is_neg() != bn) {
            qi = qi.sub(&Int::S(1));
            ri = ri.add(o);
        }
        (qi, ri)
    }

    pub fn cmp(&self, o: &Int) -> Ordering {
        if let (Int::S(a), Int::S(b)) = (self, o) {
            return a.cmp(b);
        }
        let (an, am) = self.parts();
        let (bn, bm) = o.parts();
        match (an, bn) {
            (false, true) => Ordering::Greater,
            (true, false) => Ordering::Less,
            (false, false) => am.cmp(&bm),
            (true, true) => bm.cmp(&am),
        }
    }

    pub fn to_string(&self) -> String {
        match self {
            Int::S(x) => x.to_string(),
            Int::B(b) => {
                let s = b.mag.to_dec();
                if b.neg { format!("-{}", s) } else { s }
            }
        }
    }

    /// Із рядка: необовʼязковий знак і цифри 0–9 (перевірено раніше).
    pub fn from_dec(neg: bool, digits: &str) -> Int {
        if digits.len() <= 18 {
            let x: i64 = digits.parse().unwrap_or(0);
            return Int::S(if neg { -x } else { x });
        }
        Int::from_big(neg, Nat::from_dec(digits))
    }

    pub fn to_f64(&self) -> f64 {
        match self {
            Int::S(x) => *x as f64,
            Int::B(_) => self.to_string().parse().unwrap_or(f64::INFINITY),
        }
    }
}

fn add_signed(an: bool, am: &Nat, bn: bool, bm: &Nat) -> Int {
    if an == bn {
        return Int::from_big(an, am.add(bm));
    }
    match am.cmp(bm) {
        Ordering::Equal => Int::S(0),
        Ordering::Greater => Int::from_big(an, am.sub(bm)),
        Ordering::Less => Int::from_big(bn, bm.sub(am)),
    }
}
