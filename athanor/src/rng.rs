//! random.Random(seed) Python: MT19937, init_by_array, getrandbits, randint.
use crate::int::Int;
use crate::nat::Nat;

pub struct Mt {
    mt: [u32; 624],
    i: usize,
}

impl Mt {
    fn init_genrand(s: u32) -> Mt {
        let mut mt = [0u32; 624];
        mt[0] = s;
        for i in 1..624 {
            mt[i] = 1812433253u32.wrapping_mul(mt[i - 1] ^ (mt[i - 1] >> 30)).wrapping_add(i as u32);
        }
        Mt { mt, i: 624 }
    }

    /// Як random.seed(n) для цілого n.
    pub fn seed(n: &Int) -> Mt {
        let (_, mag) = n.parts();
        let mut key: Vec<u32> = mag.0.clone();
        if key.is_empty() {
            key.push(0);
        }
        let mut m = Mt::init_genrand(19650218);
        let (mut i, mut j) = (1usize, 0usize);
        let len = key.len();
        let mut k = 624.max(len);
        while k > 0 {
            m.mt[i] = (m.mt[i] ^ (m.mt[i - 1] ^ (m.mt[i - 1] >> 30)).wrapping_mul(1664525))
                .wrapping_add(key[j])
                .wrapping_add(j as u32);
            i += 1;
            j += 1;
            if i >= 624 {
                m.mt[0] = m.mt[623];
                i = 1;
            }
            if j >= len {
                j = 0;
            }
            k -= 1;
        }
        k = 623;
        while k > 0 {
            m.mt[i] = (m.mt[i] ^ (m.mt[i - 1] ^ (m.mt[i - 1] >> 30)).wrapping_mul(1566083941)).wrapping_sub(i as u32);
            i += 1;
            if i >= 624 {
                m.mt[0] = m.mt[623];
                i = 1;
            }
            k -= 1;
        }
        m.mt[0] = 0x80000000;
        m.i = 624;
        m
    }

    pub fn next_u32(&mut self) -> u32 {
        if self.i >= 624 {
            for k in 0..624 {
                let y = (self.mt[k] & 0x80000000) | (self.mt[(k + 1) % 624] & 0x7fffffff);
                let mut v = self.mt[(k + 397) % 624] ^ (y >> 1);
                if y & 1 != 0 {
                    v ^= 0x9908b0df;
                }
                self.mt[k] = v;
            }
            self.i = 0;
        }
        let mut y = self.mt[self.i];
        self.i += 1;
        y ^= y >> 11;
        y ^= (y << 7) & 0x9d2c5680;
        y ^= (y << 15) & 0xefc60000;
        y ^= y >> 18;
        y
    }

    pub fn getrandbits(&mut self, k: u64) -> Nat {
        if k == 0 {
            return Nat::zero();
        }
        if k <= 32 {
            return Nat::from_u64((self.next_u32() >> (32 - k)) as u64);
        }
        let words = ((k - 1) / 32 + 1) as usize;
        let mut w = Vec::with_capacity(words);
        let mut kk = k as i64;
        for _ in 0..words {
            let mut r = self.next_u32();
            if kk < 32 {
                r >>= 32 - kk;
            }
            w.push(r);
            kk -= 32;
        }
        let mut n = Nat(w);
        while let Some(&0) = n.0.last() {
            n.0.pop();
        }
        n
    }

    /// randint(1, n) для n ≥ 1.
    pub fn randint1(&mut self, n: &Int) -> Int {
        let (_, mag) = n.parts();
        let k = mag.bits();
        loop {
            let r = self.getrandbits(k);
            if r.cmp(&mag) == std::cmp::Ordering::Less {
                return Int::from_big(false, r).add(&Int::S(1));
            }
        }
    }
}
