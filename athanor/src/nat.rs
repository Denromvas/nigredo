//! Натуральні числа довільної довжини (основа цілих Python і коефіцієнтів десяткових).
use std::cmp::Ordering;

#[derive(Clone, PartialEq, Eq, Debug, Default, Hash)]
pub struct Nat(pub Vec<u32>); // молодші розряди першими, без нулів у кінці; нуль — порожній

impl Nat {
    pub fn zero() -> Nat {
        Nat(Vec::new())
    }

    pub fn from_u64(x: u64) -> Nat {
        let mut v = Vec::new();
        if x != 0 {
            v.push(x as u32);
            if x >> 32 != 0 {
                v.push((x >> 32) as u32);
            }
        }
        Nat(v)
    }

    pub fn from_u128(x: u128) -> Nat {
        let mut v = Vec::new();
        let mut y = x;
        while y != 0 {
            v.push(y as u32);
            y >>= 32;
        }
        Nat(v)
    }

    pub fn is_zero(&self) -> bool {
        self.0.is_empty()
    }

    fn trim(mut self) -> Nat {
        while let Some(&0) = self.0.last() {
            self.0.pop();
        }
        self
    }

    pub fn to_u64(&self) -> Option<u64> {
        match self.0.len() {
            0 => Some(0),
            1 => Some(self.0[0] as u64),
            2 => Some(self.0[0] as u64 | (self.0[1] as u64) << 32),
            _ => None,
        }
    }

    pub fn to_u128(&self) -> Option<u128> {
        if self.0.len() > 4 {
            return None;
        }
        let mut r: u128 = 0;
        for (i, &d) in self.0.iter().enumerate() {
            r |= (d as u128) << (32 * i);
        }
        Some(r)
    }

    pub fn bits(&self) -> u64 {
        match self.0.last() {
            None => 0,
            Some(&top) => (self.0.len() as u64 - 1) * 32 + (32 - top.leading_zeros() as u64),
        }
    }

    pub fn cmp(&self, o: &Nat) -> Ordering {
        if self.0.len() != o.0.len() {
            return self.0.len().cmp(&o.0.len());
        }
        for i in (0..self.0.len()).rev() {
            if self.0[i] != o.0[i] {
                return self.0[i].cmp(&o.0[i]);
            }
        }
        Ordering::Equal
    }

    pub fn add(&self, o: &Nat) -> Nat {
        let (a, b) = if self.0.len() >= o.0.len() { (self, o) } else { (o, self) };
        let mut r = Vec::with_capacity(a.0.len() + 1);
        let mut carry = 0u64;
        for i in 0..a.0.len() {
            let s = a.0[i] as u64 + if i < b.0.len() { b.0[i] as u64 } else { 0 } + carry;
            r.push(s as u32);
            carry = s >> 32;
        }
        if carry != 0 {
            r.push(carry as u32);
        }
        Nat(r)
    }

    /// self − o; self ≥ o.
    pub fn sub(&self, o: &Nat) -> Nat {
        let mut r = Vec::with_capacity(self.0.len());
        let mut borrow = 0i64;
        for i in 0..self.0.len() {
            let mut d = self.0[i] as i64 - borrow - if i < o.0.len() { o.0[i] as i64 } else { 0 };
            if d < 0 {
                d += 1 << 32;
                borrow = 1;
            } else {
                borrow = 0;
            }
            r.push(d as u32);
        }
        debug_assert!(borrow == 0);
        Nat(r).trim()
    }

    pub fn mul_small(&self, m: u32) -> Nat {
        if m == 0 || self.is_zero() {
            return Nat::zero();
        }
        let mut r = Vec::with_capacity(self.0.len() + 1);
        let mut carry = 0u64;
        for &d in &self.0 {
            let p = d as u64 * m as u64 + carry;
            r.push(p as u32);
            carry = p >> 32;
        }
        if carry != 0 {
            r.push(carry as u32);
        }
        Nat(r)
    }

    pub fn add_small(&self, m: u32) -> Nat {
        self.add(&Nat::from_u64(m as u64))
    }

    pub fn mul(&self, o: &Nat) -> Nat {
        if self.is_zero() || o.is_zero() {
            return Nat::zero();
        }
        if self.0.len() == 1 {
            return o.mul_small(self.0[0]);
        }
        if o.0.len() == 1 {
            return self.mul_small(o.0[0]);
        }
        if self.0.len() >= 48 && o.0.len() >= 48 {
            return karatsuba(self, o);
        }
        let mut r = vec![0u32; self.0.len() + o.0.len()];
        for (i, &a) in self.0.iter().enumerate() {
            if a == 0 {
                continue;
            }
            let mut carry = 0u64;
            for (j, &b) in o.0.iter().enumerate() {
                let t = a as u64 * b as u64 + r[i + j] as u64 + carry;
                r[i + j] = t as u32;
                carry = t >> 32;
            }
            let mut k = i + o.0.len();
            while carry != 0 {
                let t = r[k] as u64 + carry;
                r[k] = t as u32;
                carry = t >> 32;
                k += 1;
            }
        }
        Nat(r).trim()
    }

    pub fn shl_limbs(&self, n: usize) -> Nat {
        if self.is_zero() {
            return Nat::zero();
        }
        let mut v = vec![0u32; n];
        v.extend_from_slice(&self.0);
        Nat(v)
    }

    pub fn divmod_small(&self, d: u32) -> (Nat, u32) {
        let mut q = vec![0u32; self.0.len()];
        let mut rem = 0u64;
        for i in (0..self.0.len()).rev() {
            let cur = (rem << 32) | self.0[i] as u64;
            q[i] = (cur / d as u64) as u32;
            rem = cur % d as u64;
        }
        (Nat(q).trim(), rem as u32)
    }

    /// (частка, остача); d ≠ 0. Кнут, алгоритм D.
    pub fn divmod(&self, d: &Nat) -> (Nat, Nat) {
        assert!(!d.is_zero(), "ділення на нуль у Nat");
        if self.cmp(d) == Ordering::Less {
            return (Nat::zero(), self.clone());
        }
        if d.0.len() == 1 {
            let (q, r) = self.divmod_small(d.0[0]);
            return (q, Nat::from_u64(r as u64));
        }
        if let (Some(a), Some(b)) = (self.to_u128(), d.to_u128()) {
            return (Nat::from_u128(a / b), Nat::from_u128(a % b));
        }
        let s = d.0.last().unwrap().leading_zeros();
        let v = shl_bits(&d.0, s);
        let mut u = shl_bits(&self.0, s);
        u.push(0);
        let n = v.len();
        let m = u.len() - n - 1;
        let mut q = vec![0u32; m + 1];
        let vtop = v[n - 1] as u64;
        let vnext = v[n - 2] as u64;
        for j in (0..=m).rev() {
            let num = (u[j + n] as u64) << 32 | u[j + n - 1] as u64;
            let mut qhat = num / vtop;
            let mut rhat = num % vtop;
            while qhat >= 1 << 32 || qhat * vnext > ((rhat << 32) | u[j + n - 2] as u64) {
                qhat -= 1;
                rhat += vtop;
                if rhat >= 1 << 32 {
                    break;
                }
            }
            // u[j..j+n+1] -= qhat * v
            let mut borrow: i64 = 0;
            let mut carry: u64 = 0;
            for i in 0..n {
                let p = qhat * v[i] as u64 + carry;
                carry = p >> 32;
                let t = u[i + j] as i64 - borrow - (p & 0xFFFF_FFFF) as i64;
                u[i + j] = t as u32;
                borrow = if t < 0 { 1 } else { 0 };
            }
            let t = u[j + n] as i64 - borrow - carry as i64;
            u[j + n] = t as u32;
            if t < 0 {
                qhat -= 1;
                let mut c = 0u64;
                for i in 0..n {
                    let s2 = u[i + j] as u64 + v[i] as u64 + c;
                    u[i + j] = s2 as u32;
                    c = s2 >> 32;
                }
                u[j + n] = u[j + n].wrapping_add(c as u32);
            }
            q[j] = qhat as u32;
        }
        u.truncate(n);
        let r = shr_bits(&u, s);
        (Nat(q).trim(), Nat(r).trim())
    }

    pub fn pow10(n: u64) -> Nat {
        if n < 20 {
            return Nat::from_u64(10u64.pow(n as u32));
        }
        // 10^n = 5^n · 2^n; 5^n — множенням квадратами
        let mut result = Nat::from_u64(1);
        let mut base = Nat::from_u64(10);
        let mut e = n;
        while e > 0 {
            if e & 1 == 1 {
                result = result.mul(&base);
            }
            e >>= 1;
            if e > 0 {
                base = base.mul(&base);
            }
        }
        result
    }

    pub fn mul_pow10(&self, n: u64) -> Nat {
        if n == 0 || self.is_zero() {
            return self.clone();
        }
        if n <= 9 {
            return self.mul_small(10u32.pow(n as u32));
        }
        self.mul(&Nat::pow10(n))
    }

    /// Десятковий запис.
    pub fn to_dec(&self) -> String {
        if let Some(x) = self.to_u64() {
            return x.to_string();
        }
        if self.0.len() > 64 {
            return to_dec_dc(self);
        }
        let mut chunks = Vec::new();
        let mut cur = self.clone();
        while !cur.is_zero() {
            let (q, r) = cur.divmod_small(1_000_000_000);
            chunks.push(r);
            cur = q;
        }
        let mut s = chunks.last().unwrap().to_string();
        for c in chunks.iter().rev().skip(1) {
            s.push_str(&format!("{:09}", c));
        }
        s
    }

    /// Із рядка цифр 0–9 (непорожнього).
    pub fn from_dec(s: &str) -> Nat {
        let b = s.as_bytes();
        if b.len() <= 19 {
            let mut x = 0u64;
            for &c in b {
                x = x * 10 + (c - b'0') as u64;
            }
            return Nat::from_u64(x);
        }
        if b.len() > 2000 {
            let mid = b.len() / 2;
            let hi = Nat::from_dec(&s[..mid]);
            let lo = Nat::from_dec(&s[mid..]);
            return hi.mul_pow10((b.len() - mid) as u64).add(&lo);
        }
        let mut r = Nat::zero();
        let mut i = 0;
        while i < b.len() {
            let take = (b.len() - i).min(9);
            let mut chunk = 0u32;
            for &c in &b[i..i + take] {
                chunk = chunk * 10 + (c - b'0') as u32;
            }
            r = r.mul_small(10u32.pow(take as u32)).add_small(chunk);
            i += take;
        }
        r
    }

    /// Кількість десяткових цифр (у нуля — 1).
    pub fn ndigits(&self) -> u64 {
        if let Some(x) = self.to_u64() {
            if x == 0 {
                return 1;
            }
            return (x.ilog10() + 1) as u64;
        }
        // оцінка за бітами, уточнення порівнянням зі степенем 10
        let est = ((self.bits() - 1) as f64 * std::f64::consts::LOG10_2) as u64; // ≤ справжнього lg
        let mut d = est + 1;
        let mut p = Nat::pow10(d);
        while self.cmp(&p) != Ordering::Less {
            d += 1;
            p = p.mul_small(10);
        }
        d
    }

    /// Скільки нулів у кінці десяткового запису (у нуля — 0).
    pub fn trailing_zeros10(&self) -> u64 {
        if self.is_zero() {
            return 0;
        }
        if let Some(mut x) = self.to_u64() {
            let mut k = 0;
            while x % 10 == 0 {
                x /= 10;
                k += 1;
            }
            return k;
        }
        let s = self.to_dec();
        (s.len() - s.trim_end_matches('0').len()) as u64
    }

    pub fn is_odd(&self) -> bool {
        self.0.first().map_or(false, |d| d & 1 == 1)
    }
}

fn shl_bits(a: &[u32], s: u32) -> Vec<u32> {
    if s == 0 {
        return a.to_vec();
    }
    let mut r = Vec::with_capacity(a.len() + 1);
    let mut carry = 0u32;
    for &d in a {
        r.push(d << s | carry);
        carry = d >> (32 - s);
    }
    if carry != 0 {
        r.push(carry);
    }
    r
}

fn shr_bits(a: &[u32], s: u32) -> Vec<u32> {
    if s == 0 {
        return a.to_vec();
    }
    let mut r = vec![0u32; a.len()];
    for i in 0..a.len() {
        let hi = if i + 1 < a.len() { a[i + 1] << (32 - s) } else { 0 };
        r[i] = a[i] >> s | hi;
    }
    r
}

fn karatsuba(a: &Nat, b: &Nat) -> Nat {
    let h = a.0.len().max(b.0.len()) / 2;
    let split = |x: &Nat| -> (Nat, Nat) {
        if x.0.len() <= h {
            (x.clone(), Nat::zero())
        } else {
            (Nat(x.0[..h].to_vec()).trim(), Nat(x.0[h..].to_vec()))
        }
    };
    let (a0, a1) = split(a);
    let (b0, b1) = split(b);
    let z0 = a0.mul(&b0);
    let z2 = a1.mul(&b1);
    let z1 = a0.add(&a1).mul(&b0.add(&b1)).sub(&z0).sub(&z2);
    z0.add(&z1.shl_limbs(h)).add(&z2.shl_limbs(2 * h))
}

/// Десятковий запис великих чисел: поділ навпіл степенем 10 (швидше за квадратичний).
fn to_dec_dc(x: &Nat) -> String {
    let d = x.ndigits();
    let half = d / 2;
    let p = Nat::pow10(half);
    let (hi, lo) = x.divmod(&p);
    let hs = hi.to_dec();
    let ls = lo.to_dec();
    let mut s = hs;
    for _ in 0..(half as usize).saturating_sub(ls.len()) {
        s.push('0');
    }
    s.push_str(&ls);
    s
}
