//! SHA-256 і HMAC-SHA256 (слід, печатка програми, оракул).
const K: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01,
    0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
    0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08,
    0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

pub struct Sha256 {
    h: [u32; 8],
    buf: Vec<u8>,
    len: u64,
}

impl Sha256 {
    pub fn new() -> Sha256 {
        Sha256 {
            h: [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19],
            buf: Vec::with_capacity(64),
            len: 0,
        }
    }

    fn block(&mut self, b: &[u8]) {
        self.blocks(b)
    }

    /// Кілька блоків по 64 байти поспіль (апаратно — одним викликом).
    fn blocks(&mut self, b: &[u8]) {
        #[cfg(target_arch = "aarch64")]
        {
            if std::arch::is_aarch64_feature_detected!("sha2") {
                unsafe { self.blocks_hw(b) };
                return;
            }
        }
        for c in b.chunks_exact(64) {
            self.block_sw(c);
        }
    }

    /// Апаратні інструкції SHA-256 (ARMv8 Crypto): усі блоки одним викликом — стан і сталі в регістрах.
    #[cfg(target_arch = "aarch64")]
    #[target_feature(enable = "sha2")]
    unsafe fn blocks_hw(&mut self, data: &[u8]) {
        use std::arch::aarch64::*;
        let mut abcd = vld1q_u32(self.h.as_ptr());
        let mut efgh = vld1q_u32(self.h.as_ptr().add(4));
        let k: [uint32x4_t; 16] = std::array::from_fn(|i| vld1q_u32(K.as_ptr().add(4 * i)));
        for b in data.chunks_exact(64) {
            let (abcd0, efgh0) = (abcd, efgh);
            let mut m0 = vreinterpretq_u32_u8(vrev32q_u8(vld1q_u8(b.as_ptr())));
            let mut m1 = vreinterpretq_u32_u8(vrev32q_u8(vld1q_u8(b.as_ptr().add(16))));
            let mut m2 = vreinterpretq_u32_u8(vrev32q_u8(vld1q_u8(b.as_ptr().add(32))));
            let mut m3 = vreinterpretq_u32_u8(vrev32q_u8(vld1q_u8(b.as_ptr().add(48))));
            macro_rules! round {
                ($m:expr, $k:expr) => {{
                    let wk = vaddq_u32($m, $k);
                    let t = abcd;
                    abcd = vsha256hq_u32(abcd, efgh, wk);
                    efgh = vsha256h2q_u32(efgh, t, wk);
                }};
            }
            for r in 0..3 {
                round!(m0, k[4 * r]);
                m0 = vsha256su1q_u32(vsha256su0q_u32(m0, m1), m2, m3);
                round!(m1, k[4 * r + 1]);
                m1 = vsha256su1q_u32(vsha256su0q_u32(m1, m2), m3, m0);
                round!(m2, k[4 * r + 2]);
                m2 = vsha256su1q_u32(vsha256su0q_u32(m2, m3), m0, m1);
                round!(m3, k[4 * r + 3]);
                m3 = vsha256su1q_u32(vsha256su0q_u32(m3, m0), m1, m2);
            }
            round!(m0, k[12]);
            round!(m1, k[13]);
            round!(m2, k[14]);
            round!(m3, k[15]);
            abcd = vaddq_u32(abcd, abcd0);
            efgh = vaddq_u32(efgh, efgh0);
        }
        vst1q_u32(self.h.as_mut_ptr(), abcd);
        vst1q_u32(self.h.as_mut_ptr().add(4), efgh);
    }

    fn block_sw(&mut self, b: &[u8]) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([b[4 * i], b[4 * i + 1], b[4 * i + 2], b[4 * i + 3]]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16].wrapping_add(s0).wrapping_add(w[i - 7]).wrapping_add(s1);
        }
        let mut v = self.h;
        for i in 0..64 {
            let s1 = v[4].rotate_right(6) ^ v[4].rotate_right(11) ^ v[4].rotate_right(25);
            let ch = (v[4] & v[5]) ^ (!v[4] & v[6]);
            let t1 = v[7].wrapping_add(s1).wrapping_add(ch).wrapping_add(K[i]).wrapping_add(w[i]);
            let s0 = v[0].rotate_right(2) ^ v[0].rotate_right(13) ^ v[0].rotate_right(22);
            let maj = (v[0] & v[1]) ^ (v[0] & v[2]) ^ (v[1] & v[2]);
            let t2 = s0.wrapping_add(maj);
            v[7] = v[6];
            v[6] = v[5];
            v[5] = v[4];
            v[4] = v[3].wrapping_add(t1);
            v[3] = v[2];
            v[2] = v[1];
            v[1] = v[0];
            v[0] = t1.wrapping_add(t2);
        }
        for i in 0..8 {
            self.h[i] = self.h[i].wrapping_add(v[i]);
        }
    }

    pub fn update(&mut self, data: &[u8]) {
        self.len += data.len() as u64;
        let mut d = data;
        if !self.buf.is_empty() {
            let take = (64 - self.buf.len()).min(d.len());
            self.buf.extend_from_slice(&d[..take]);
            d = &d[take..];
            if self.buf.len() == 64 {
                let b = std::mem::take(&mut self.buf);
                self.block(&b);
                self.buf = b;
                self.buf.clear();
            }
        }
        let full = d.len() / 64 * 64;
        if full > 0 {
            self.blocks(&d[..full]);
            d = &d[full..];
        }
        self.buf.extend_from_slice(d);
    }

    pub fn finish(mut self) -> [u8; 32] {
        let bits = self.len * 8;
        let mut pad = vec![0x80u8];
        while (self.buf.len() + pad.len()) % 64 != 56 {
            pad.push(0);
        }
        pad.extend_from_slice(&bits.to_be_bytes());
        let len = self.len;
        self.update(&pad);
        self.len = len;
        let mut out = [0u8; 32];
        for i in 0..8 {
            out[4 * i..4 * i + 4].copy_from_slice(&self.h[i].to_be_bytes());
        }
        out
    }
}

pub fn sha256(data: &[u8]) -> [u8; 32] {
    let mut s = Sha256::new();
    s.update(data);
    s.finish()
}

pub fn hex(b: &[u8]) -> String {
    let mut s = String::with_capacity(b.len() * 2);
    for x in b {
        s.push_str(&format!("{:02x}", x));
    }
    s
}

pub fn sha256_hex(data: &[u8]) -> String {
    hex(&sha256(data))
}

pub fn hmac_sha256(key: &[u8], msg: &[u8]) -> [u8; 32] {
    let mut k = [0u8; 64];
    if key.len() > 64 {
        k[..32].copy_from_slice(&sha256(key));
    } else {
        k[..key.len()].copy_from_slice(key);
    }
    let mut inner = Sha256::new();
    let ipad: Vec<u8> = k.iter().map(|b| b ^ 0x36).collect();
    inner.update(&ipad);
    inner.update(msg);
    let ih = inner.finish();
    let mut outer = Sha256::new();
    let opad: Vec<u8> = k.iter().map(|b| b ^ 0x5c).collect();
    outer.update(&opad);
    outer.update(&ih);
    outer.finish()
}
