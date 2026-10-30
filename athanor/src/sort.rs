//! Сортування як sorted(…, key=sort_key) у Python 3.13: ключі — кортежі sort_key, алгоритм — listsort з CPython
//! (Objects/listobject.c v3.13.7: count_run, binarysort, powersort, gallop), тож і «ключі різних типів» (TypeError)
//! виникає рівно тоді, коли в еталоні.
use crate::interp::{ngr, R};
use crate::lexer::Pos;
use crate::uni;
use crate::value::*;
use std::cmp::Ordering;
use std::rc::Rc;

pub enum SK {
    Nil,                                 // (-2, 0) — ∅
    Bool(bool),                          // (-1, ●/○) — ● не число (суд 12)
    Num(Val),                            // (0, число)
    Str(Vec<(u32, char)>, Rc<PStr>),      // (1, [(порядок, символ)…], рядок)
    List(Vec<SK>),                       // (2, [ключі…])
}

fn ua_order(c: char) -> u32 {
    match crate::lang::UA_ORDER.chars().position(|x| x == c) {
        Some(i) => i as u32,
        None => 100 + c as u32,
    }
}

/// Ключ списку, глибшого за WALK, — deep() (як DeepValue в sort_key еталона); словник чи функція — Ok(Err(вид)),
/// як BadSortKey еталона (той самий обхід, тож і та сама перша з двох помилок).
pub fn sort_key(x: &V, d: usize) -> R<Result<SK, &'static str>> {
    Ok(Ok(match &x.v {
        Val::Str(s) => SK::Str(uni::casefold(&s.s).chars().map(|c| (ua_order(c), c)).collect(), s.clone()),
        Val::List(l) => {
            if d >= WALK {
                return deep();
            }
            let mut ks = Vec::with_capacity(l.len());
            for e in l.iter() {
                match sort_key(e, d + 1)? {
                    Ok(k) => ks.push(k),
                    Err(w) => return Ok(Err(w)),
                }
            }
            SK::List(ks)
        }
        Val::None => SK::Nil,
        Val::Bool(b) => SK::Bool(*b),
        Val::Int(_) | Val::Dec(_) | Val::Float(_) => SK::Num(x.v.clone()),
        Val::Dict(_) => return Ok(Err("словник")),
        _ => return Ok(Err("функція")),
    }))
}

fn tag(k: &SK) -> u8 {
    match k {
        SK::Nil => 0,
        SK::Bool(_) => 1,
        SK::Num(_) => 2,
        SK::Str(..) => 3,
        SK::List(_) => 4,
    }
}

/// Python == для другого елемента кортежу (0, v).
fn val_eq(a: &Val, b: &Val) -> bool {
    match (a, b) {
        (Val::None, Val::None) => true,
        (Val::Dict(x), Val::Dict(y)) => Rc::ptr_eq(x, y),
        (Val::Fn(x), Val::Fn(y)) => Rc::ptr_eq(x, y),
        (x, y) if is_num(x) && is_num(y) => num_cmp(x, y) == Some(Ordering::Equal),
        _ => false,
    }
}

fn eq(a: &SK, b: &SK) -> bool {
    match (a, b) {
        (SK::Nil, SK::Nil) => true,
        (SK::Bool(x), SK::Bool(y)) => x == y,
        (SK::Num(x), SK::Num(y)) => val_eq(x, y),
        (SK::Str(p, s), SK::Str(q, t)) => p == q && s.s == t.s,
        (SK::List(p), SK::List(q)) => p.len() == q.len() && p.iter().zip(q).all(|(x, y)| eq(x, y)),
        _ => false,
    }
}

/// a < b для кортежів sort_key; Err — TypeError.
pub fn lt(a: &SK, b: &SK) -> Result<bool, ()> {
    let (ta, tb) = (tag(a), tag(b));
    if ta != tb {
        return Ok(ta < tb);
    }
    match (a, b) {
        (SK::Str(p, s), SK::Str(q, t)) => {
            if p != q {
                return Ok(pairs_lt(p, q));
            }
            Ok(s.s < t.s)
        }
        (SK::List(p), SK::List(q)) => {
            for (x, y) in p.iter().zip(q) {
                if !eq(x, y) {
                    return lt(x, y);
                }
            }
            Ok(p.len() < q.len())
        }
        (SK::Bool(x), SK::Bool(y)) => Ok(!x & y),
        (SK::Num(x), SK::Num(y)) => Ok(!val_eq(x, y) && num_cmp(x, y) == Some(Ordering::Less)),
        (SK::Nil, SK::Nil) => Ok(false),
        _ => Err(()),
    }
}

/// Порядок рядків мови (‹ › ≤ ≥, як ↑ ⇅): casefold за українською абеткою, далі — за кодами (рівні — Equal).
pub fn str_cmp(x: &str, y: &str) -> Ordering {
    let p: Vec<(u32, char)> = uni::casefold(x).chars().map(|c| (ua_order(c), c)).collect();
    let q: Vec<(u32, char)> = uni::casefold(y).chars().map(|c| (ua_order(c), c)).collect();
    if p != q {
        return if pairs_lt(&p, &q) { Ordering::Less } else { Ordering::Greater };
    }
    x.cmp(y)
}

fn pairs_lt(p: &[(u32, char)], q: &[(u32, char)]) -> bool {
    for (x, y) in p.iter().zip(q) {
        if x != y {
            return x < y;
        }
    }
    p.len() < q.len()
}

/// Порядок індексів після стабільного сортування за sort_key (як sorted у Python); помилка ⇅ — ключі не порівняти.
pub fn sort_order(items: &[V], pos: Pos) -> R<Vec<usize>> {
    let mut keys: Vec<SK> = Vec::with_capacity(items.len());
    for x in items {
        match sort_key(x, 0)? {
            Ok(k) => keys.push(k),
            Err(w) => return ngr(format!("⇅: ключ — ∅, ●/○, число, рядок або список із них, а не {}", w), pos),
        }
    }
    match timsort(&keys) {
        Ok(o) => Ok(o),
        Err(()) => ngr("⇅: ключі мають бути одного типу (числа, рядки або списки з них — поелементно)", pos),
    }
}

const MIN_GALLOP: usize = 7;
const MAX_MINRUN: usize = 64;

struct Ms<'a> {
    keys: &'a [SK],
    min_gallop: usize,
    pending: Vec<(usize, usize, i32)>, // початок, довжина, power
    listlen: usize,
}

type Res<T> = Result<T, ()>;

impl<'a> Ms<'a> {
    #[inline]
    fn lt(&self, x: usize, y: usize) -> Res<bool> {
        lt(&self.keys[x], &self.keys[y])
    }

    fn binarysort(&self, a: &mut [usize], n: usize, ok: usize) -> Res<()> {
        let mut ok = if ok == 0 { 1 } else { ok };
        while ok < n {
            let (mut l, mut r) = (0usize, ok);
            let pivot = a[ok];
            loop {
                let m = (l + r) >> 1;
                if self.lt(pivot, a[m])? {
                    r = m;
                } else {
                    l = m + 1;
                }
                if l >= r {
                    break;
                }
            }
            let mut m = ok;
            while m > l {
                a[m] = a[m - 1];
                m -= 1;
            }
            a[l] = pivot;
            ok += 1;
        }
        Ok(())
    }

    fn count_run(&self, a: &mut [usize], nrem: usize) -> Res<usize> {
        let mut n = 1;
        while n < nrem {
            if self.lt(a[n], a[n - 1])? {
                break;
            }
            n += 1;
        }
        if n == nrem {
            return Ok(n);
        }
        if n > 1 {
            if self.lt(a[0], a[n - 1])? {
                return Ok(n);
            }
            a[..n].reverse();
        }
        n += 1;
        let mut neq = 0usize;
        while n < nrem {
            if self.lt(a[n], a[n - 1])? {
                if neq > 0 {
                    neq += 1;
                    a[n - neq..n].reverse();
                    neq = 0;
                }
            } else if self.lt(a[n - 1], a[n])? {
                break;
            } else {
                neq += 1;
            }
            n += 1;
        }
        if neq > 0 {
            neq += 1;
            a[n - neq..n].reverse();
        }
        a[..n].reverse();
        while n < nrem {
            if self.lt(a[n], a[n - 1])? {
                break;
            }
            n += 1;
        }
        Ok(n)
    }

    fn gallop_left(&self, key: usize, arr: &[usize], off: usize, n: usize, hint: usize) -> Res<usize> {
        let a = &arr[off..off + n];
        let (mut lastofs, mut ofs): (isize, isize) = (0, 1);
        let h = hint as isize;
        if self.lt(a[hint], key)? {
            let maxofs = (n - hint) as isize;
            while ofs < maxofs {
                if self.lt(a[(h + ofs) as usize], key)? {
                    lastofs = ofs;
                    ofs = (ofs << 1) + 1;
                } else {
                    break;
                }
            }
            if ofs > maxofs {
                ofs = maxofs;
            }
            lastofs += h;
            ofs += h;
        } else {
            let maxofs = h + 1;
            while ofs < maxofs {
                if self.lt(a[(h - ofs) as usize], key)? {
                    break;
                }
                lastofs = ofs;
                ofs = (ofs << 1) + 1;
            }
            if ofs > maxofs {
                ofs = maxofs;
            }
            let k = lastofs;
            lastofs = h - ofs;
            ofs = h - k;
        }
        lastofs += 1;
        while lastofs < ofs {
            let m = lastofs + ((ofs - lastofs) >> 1);
            if self.lt(a[m as usize], key)? {
                lastofs = m + 1;
            } else {
                ofs = m;
            }
        }
        Ok(ofs as usize)
    }

    fn gallop_right(&self, key: usize, arr: &[usize], off: usize, n: usize, hint: usize) -> Res<usize> {
        let a = &arr[off..off + n];
        let (mut lastofs, mut ofs): (isize, isize) = (0, 1);
        let h = hint as isize;
        if self.lt(key, a[hint])? {
            let maxofs = h + 1;
            while ofs < maxofs {
                if self.lt(key, a[(h - ofs) as usize])? {
                    lastofs = ofs;
                    ofs = (ofs << 1) + 1;
                } else {
                    break;
                }
            }
            if ofs > maxofs {
                ofs = maxofs;
            }
            let k = lastofs;
            lastofs = h - ofs;
            ofs = h - k;
        } else {
            let maxofs = (n - hint) as isize;
            while ofs < maxofs {
                if self.lt(key, a[(h + ofs) as usize])? {
                    break;
                }
                lastofs = ofs;
                ofs = (ofs << 1) + 1;
            }
            if ofs > maxofs {
                ofs = maxofs;
            }
            lastofs += h;
            ofs += h;
        }
        lastofs += 1;
        while lastofs < ofs {
            let m = lastofs + ((ofs - lastofs) >> 1);
            if self.lt(key, a[m as usize])? {
                ofs = m;
            } else {
                lastofs = m + 1;
            }
        }
        Ok(ofs as usize)
    }

    fn merge_lo(&mut self, a: &mut [usize], pa: usize, mut na: usize, pb: usize, mut nb: usize) -> Res<()> {
        let tmp: Vec<usize> = a[pa..pa + na].to_vec();
        let (mut dest, mut ia, mut ib) = (pa, 0usize, pb);
        a[dest] = a[ib];
        dest += 1;
        ib += 1;
        nb -= 1;
        let mut res: Res<()> = Ok(());
        'outer: {
            if nb == 0 {
                break 'outer;
            }
            if na == 1 {
                // CopyB
                a.copy_within(ib..ib + nb, dest);
                a[dest + nb] = tmp[ia];
                return Ok(());
            }
            let mut min_gallop = self.min_gallop;
            loop {
                let (mut acount, mut bcount) = (0usize, 0usize);
                loop {
                    match self.lt(a[ib], tmp[ia]) {
                        Err(()) => {
                            res = Err(());
                            break 'outer;
                        }
                        Ok(true) => {
                            a[dest] = a[ib];
                            dest += 1;
                            ib += 1;
                            bcount += 1;
                            acount = 0;
                            nb -= 1;
                            if nb == 0 {
                                break 'outer;
                            }
                            if bcount >= min_gallop {
                                break;
                            }
                        }
                        Ok(false) => {
                            a[dest] = tmp[ia];
                            dest += 1;
                            ia += 1;
                            acount += 1;
                            bcount = 0;
                            na -= 1;
                            if na == 1 {
                                a.copy_within(ib..ib + nb, dest);
                                a[dest + nb] = tmp[ia];
                                return Ok(());
                            }
                            if acount >= min_gallop {
                                break;
                            }
                        }
                    }
                }
                min_gallop += 1;
                loop {
                    min_gallop -= (min_gallop > 1) as usize;
                    self.min_gallop = min_gallop;
                    let k = match self.gallop_right(a[ib], &tmp, ia, na, 0) {
                        Ok(k) => k,
                        Err(()) => {
                            res = Err(());
                            break 'outer;
                        }
                    };
                    acount = k;
                    if k > 0 {
                        a[dest..dest + k].copy_from_slice(&tmp[ia..ia + k]);
                        dest += k;
                        ia += k;
                        na -= k;
                        if na == 1 {
                            a.copy_within(ib..ib + nb, dest);
                            a[dest + nb] = tmp[ia];
                            return Ok(());
                        }
                        if na == 0 {
                            break 'outer;
                        }
                    }
                    a[dest] = a[ib];
                    dest += 1;
                    ib += 1;
                    nb -= 1;
                    if nb == 0 {
                        break 'outer;
                    }
                    let key = tmp[ia];
                    let k = match self.gallop_left(key, a, ib, nb, 0) {
                        Ok(k) => k,
                        Err(()) => {
                            res = Err(());
                            break 'outer;
                        }
                    };
                    bcount = k;
                    if k > 0 {
                        a.copy_within(ib..ib + k, dest);
                        dest += k;
                        ib += k;
                        nb -= k;
                        if nb == 0 {
                            break 'outer;
                        }
                    }
                    a[dest] = tmp[ia];
                    dest += 1;
                    ia += 1;
                    na -= 1;
                    if na == 1 {
                        a.copy_within(ib..ib + nb, dest);
                        a[dest + nb] = tmp[ia];
                        return Ok(());
                    }
                    if !(acount >= MIN_GALLOP || bcount >= MIN_GALLOP) {
                        break;
                    }
                }
                min_gallop += 1;
                self.min_gallop = min_gallop;
            }
        }
        if na > 0 {
            a[dest..dest + na].copy_from_slice(&tmp[ia..ia + na]);
        }
        res
    }

    fn merge_hi(&mut self, a: &mut [usize], pa: usize, mut na: usize, pb: usize, mut nb: usize) -> Res<()> {
        let tmp: Vec<usize> = a[pb..pb + nb].to_vec();
        let mut dest = (pb + nb - 1) as isize;
        let basea = pa;
        let mut ib = nb as isize - 1;
        let mut ia = (pa + na) as isize - 1;
        a[dest as usize] = a[ia as usize];
        dest -= 1;
        ia -= 1;
        na -= 1;
        let mut res: Res<()> = Ok(());
        macro_rules! copy_a {
            () => {{
                // CopyA: nb == 1
                let s = (ia + 1 - na as isize) as usize;
                let d = (dest + 1 - na as isize) as usize;
                a.copy_within(s..s + na, d);
                dest -= na as isize;
                a[dest as usize] = tmp[ib as usize];
                return Ok(());
            }};
        }
        'outer: {
            if na == 0 {
                break 'outer;
            }
            if nb == 1 {
                copy_a!();
            }
            let mut min_gallop = self.min_gallop;
            loop {
                let (mut acount, mut bcount) = (0usize, 0usize);
                loop {
                    match self.lt(tmp[ib as usize], a[ia as usize]) {
                        Err(()) => {
                            res = Err(());
                            break 'outer;
                        }
                        Ok(true) => {
                            a[dest as usize] = a[ia as usize];
                            dest -= 1;
                            ia -= 1;
                            acount += 1;
                            bcount = 0;
                            na -= 1;
                            if na == 0 {
                                break 'outer;
                            }
                            if acount >= min_gallop {
                                break;
                            }
                        }
                        Ok(false) => {
                            a[dest as usize] = tmp[ib as usize];
                            dest -= 1;
                            ib -= 1;
                            bcount += 1;
                            acount = 0;
                            nb -= 1;
                            if nb == 1 {
                                copy_a!();
                            }
                            if bcount >= min_gallop {
                                break;
                            }
                        }
                    }
                }
                min_gallop += 1;
                loop {
                    min_gallop -= (min_gallop > 1) as usize;
                    self.min_gallop = min_gallop;
                    let k = match self.gallop_right(tmp[ib as usize], a, basea, na, na - 1) {
                        Ok(k) => na - k,
                        Err(()) => {
                            res = Err(());
                            break 'outer;
                        }
                    };
                    acount = k;
                    if k > 0 {
                        dest -= k as isize;
                        ia -= k as isize;
                        let s = (ia + 1) as usize;
                        a.copy_within(s..s + k, (dest + 1) as usize);
                        na -= k;
                        if na == 0 {
                            break 'outer;
                        }
                    }
                    a[dest as usize] = tmp[ib as usize];
                    dest -= 1;
                    ib -= 1;
                    nb -= 1;
                    if nb == 1 {
                        copy_a!();
                    }
                    let k = match self.gallop_left(a[ia as usize], &tmp, 0, nb, nb - 1) {
                        Ok(k) => nb - k,
                        Err(()) => {
                            res = Err(());
                            break 'outer;
                        }
                    };
                    bcount = k;
                    if k > 0 {
                        dest -= k as isize;
                        ib -= k as isize;
                        let s = (ib + 1) as usize;
                        let d = (dest + 1) as usize;
                        a[d..d + k].copy_from_slice(&tmp[s..s + k]);
                        nb -= k;
                        if nb == 1 {
                            copy_a!();
                        }
                        if nb == 0 {
                            break 'outer;
                        }
                    }
                    a[dest as usize] = a[ia as usize];
                    dest -= 1;
                    ia -= 1;
                    na -= 1;
                    if na == 0 {
                        break 'outer;
                    }
                    if !(acount >= MIN_GALLOP || bcount >= MIN_GALLOP) {
                        break;
                    }
                }
                min_gallop += 1;
                self.min_gallop = min_gallop;
            }
        }
        if nb > 0 {
            let d = (dest - (nb as isize - 1)) as usize;
            a[d..d + nb].copy_from_slice(&tmp[..nb]);
        }
        res
    }

    fn merge_at(&mut self, a: &mut [usize], i: usize) -> Res<()> {
        let (pa, na0, _) = self.pending[i];
        let (pb, nb0, _) = self.pending[i + 1];
        self.pending[i].1 = na0 + nb0;
        if i + 3 == self.pending.len() {
            self.pending[i + 1] = self.pending[i + 2];
        }
        self.pending.pop();
        let k = self.gallop_right(a[pb], a, pa, na0, 0)?;
        let pa = pa + k;
        let na = na0 - k;
        if na == 0 {
            return Ok(());
        }
        let nb = self.gallop_left(a[pa + na - 1], a, pb, nb0, nb0 - 1)?;
        if nb == 0 {
            return Ok(());
        }
        if na <= nb {
            self.merge_lo(a, pa, na, pb, nb)
        } else {
            self.merge_hi(a, pa, na, pb, nb)
        }
    }

    fn found_new_run(&mut self, a: &mut [usize], n2: usize) -> Res<()> {
        if let Some(&(s1, n1, _)) = self.pending.last() {
            let power = powerloop(s1, n1, n2, self.listlen);
            while self.pending.len() > 1 && self.pending[self.pending.len() - 2].2 > power {
                let i = self.pending.len() - 2;
                self.merge_at(a, i)?;
            }
            let l = self.pending.len();
            self.pending[l - 1].2 = power;
        }
        Ok(())
    }

    fn merge_force_collapse(&mut self, a: &mut [usize]) -> Res<()> {
        while self.pending.len() > 1 {
            let mut n = self.pending.len() - 2;
            if n > 0 && self.pending[n - 1].1 < self.pending[n + 1].1 {
                n -= 1;
            }
            self.merge_at(a, n)?;
        }
        Ok(())
    }
}

fn powerloop(s1: usize, n1: usize, n2: usize, n: usize) -> i32 {
    let mut result = 0;
    let mut a = 2 * s1 + n1;
    let mut b = a + n1 + n2;
    loop {
        result += 1;
        if a >= n {
            a -= n;
            b -= n;
        } else if b >= n {
            break;
        }
        a <<= 1;
        b <<= 1;
    }
    result
}

fn compute_minrun(mut n: usize) -> usize {
    let mut r = 0;
    while n >= MAX_MINRUN {
        r |= n & 1;
        n >>= 1;
    }
    n + r
}

pub fn timsort(keys: &[SK]) -> Result<Vec<usize>, ()> {
    let n = keys.len();
    let mut a: Vec<usize> = (0..n).collect();
    if n < 2 {
        return Ok(a);
    }
    let mut ms = Ms { keys, min_gallop: MIN_GALLOP, pending: Vec::new(), listlen: n };
    let minrun = compute_minrun(n);
    let (mut lo, mut nrem) = (0usize, n);
    loop {
        let mut run = ms.count_run(&mut a[lo..lo + nrem], nrem)?;
        if run < minrun {
            let force = if nrem <= minrun { nrem } else { minrun };
            ms.binarysort(&mut a[lo..lo + force], force, run)?;
            run = force;
        }
        ms.found_new_run(&mut a, run)?;
        ms.pending.push((lo, run, 0));
        lo += run;
        nrem -= run;
        if nrem == 0 {
            break;
        }
    }
    ms.merge_force_collapse(&mut a)?;
    Ok(a)
}
