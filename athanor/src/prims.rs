//! Гліфи з обчисленими аргументами — як nigredo.Interp.prim.
use crate::dec::{self, Dec, Round};
use crate::int::Int;
use crate::interp::*;
use crate::json::{self, LoadErr, P};
use crate::lang;
use crate::lexer::Pos;
use crate::pyf;
use crate::trace::trace_val;
use crate::uni;
use crate::value::*;
use std::cmp::Ordering;
use std::io::Write;
use std::rc::Rc;

fn n(it: &Interp, a: &[V], i: usize, g: char, pos: Pos) -> R<Val> {
    match &a[i].v {
        Val::Int(_) | Val::Dec(_) => Ok(a[i].v.clone()),
        Val::Float(f) => Ok(Val::Dec(Rc::new(Dec::parse(&pyf::repr(*f)).unwrap()))),
        _ => {
            let _ = it;
            ngr(format!("{}: очікувалося число, а не {} {}", g, kind(&a[i]), brief(&a[i], 40)), pos)
        }
    }
}

fn need_str(x: &V, g: &str, pos: Pos) -> R<Rc<PStr>> {
    match &x.v {
        Val::Str(s) => Ok(s.clone()),
        _ => ngr(format!("{}: очікувалося рядок, а не {} {}", g, kind(x), brief(x, 40)), pos),
    }
}

/// ✂ за одним символом. Частини ASCII-рядка — ASCII (довжина = байти), інакше символи лічимо раз; короткі повтори —
/// одне спільне значення (Interner); місце під список — рівно на кількість частин.
fn split_char(s: &PStr, ch: char, c: f64) -> Vec<V> {
    let ascii = s.ascii();
    let parts = if ch.is_ascii() { count_byte(s.s.as_bytes(), ch as u8) + 1 } else { s.s.matches(ch).count() + 1 };
    let mut out = Vec::with_capacity(parts);
    let mut cache = Interner::new();
    for p in s.s.split(ch) {
        let r = cache.get(p, || if ascii { p.len() } else { p.chars().count() });
        let n = r.nch as u64 + 1;
        out.push(V { v: Val::Str(r), c, s: c, n });
    }
    out
}

/// Скільки разів байт трапляється (по 8 байтів за крок).
fn count_byte(b: &[u8], x: u8) -> usize {
    const LO: u64 = 0x0101_0101_0101_0101;
    const HI: u64 = 0x8080_8080_8080_8080;
    let mut n = 0usize;
    let mut chunks = b.chunks_exact(8);
    for w in &mut chunks {
        let v = u64::from_le_bytes(w.try_into().unwrap()) ^ (LO * x as u64);
        // точна кількість нульових байтів: старший біт кожного байта, що був нулем
        let z = !(((v & !HI).wrapping_add(!HI)) | v) & HI;
        n += z.count_ones() as usize;
    }
    n + chunks.remainder().iter().filter(|&&y| y == x).count()
}

fn need_list(x: &V, g: &str, pos: Pos) -> R<Rc<List>> {
    match &x.v {
        Val::List(l) => Ok(l.clone()),
        _ => ngr(format!("{}: очікувалося список, а не {} {}", g, kind(x), brief(x, 40)), pos),
    }
}

fn need_dict(x: &V, g: &str, pos: Pos) -> R<Rc<Dict>> {
    match &x.v {
        Val::Dict(d) => Ok(d.clone()),
        _ => ngr(format!("{}: очікувалося словник, а не {} {}", g, kind(x), brief(x, 40)), pos),
    }
}

fn boolean(x: &V, g: char, pos: Pos) -> R<bool> {
    match x.v {
        Val::Bool(b) => Ok(b),
        _ => ngr(format!("{}: умова має бути ● або ○, а не {} {}", g, kind(x), brief(x, 40)), pos),
    }
}

fn is_zero(v: &Val) -> bool {
    match v {
        Val::Int(i) => i.is_zero(),
        Val::Dec(d) => d.is_zero(),
        _ => false,
    }
}

fn dec_ok(d: Dec, what: &str, pos: Pos) -> R<Dec> {
    if d.adjusted().unsigned_abs() > lang::DEC_EXP {
        return ngr(format!("{}: порядок числа понад {} цифр", what, lang::DEC_EXP), pos);
    }
    Ok(d)
}

fn int_idx(v: &Val) -> Option<i64> {
    match v {
        Val::Int(Int::S(i)) => Some(*i),
        Val::Int(Int::B(b)) => Some(if b.neg { i64::MIN } else { i64::MAX }),
        _ => None,
    }
}

/// Python-зріз [a:b] для довжини len.
fn slice_bounds(len: usize, a: Option<i64>, b: Option<i64>) -> (usize, usize) {
    let l = len as i64;
    let fix = |x: i64| -> i64 {
        if x < 0 {
            (x + l).max(0)
        } else {
            x.min(l)
        }
    };
    let s = a.map(fix).unwrap_or(0);
    let e = b.map(fix).unwrap_or(l);
    (s as usize, (e.max(s)) as usize)
}

pub fn prim(it: &mut Interp, g: char, a: &[V], pos: Pos) -> R<V> {
    match g {
        '＋' => {
            match (&a[0].v, &a[1].v) {
                (Val::Str(x), Val::Str(y)) => {
                    if a[0].n + a[1].n > it.max_size {
                        return fatal(format!("＋: значення завелике ({} > --розмір {})", a[0].n + a[1].n, it.max_size), Some(pos));
                    }
                    let mut s = String::with_capacity(x.s.len() + y.s.len());
                    s.push_str(&x.s);
                    s.push_str(&y.s);
                    return Ok(V::new(Val::Str(Rc::new(PStr::owned(s, x.nch + y.nch))), 1.0));
                }
                (Val::List(x), Val::List(y)) => {
                    if a[0].n + a[1].n > it.max_size {
                        return fatal(format!("＋: значення завелике ({} > --розмір {})", a[0].n + a[1].n, it.max_size), Some(pos));
                    }
                    let mut v = Vec::with_capacity(x.len() + y.len());
                    v.extend(x.iter().cloned());
                    v.extend(y.iter().cloned());
                    return Ok(V::list(v));
                }
                (Val::Str(_), _) | (_, Val::Str(_)) => {
                    return ngr(
                        format!("＋: рядок можна зʼєднати лише з рядком (для числа — σ): {} ＋ {}", brief(&a[0], 30), brief(&a[1], 30)),
                        pos,
                    )
                }
                _ => {}
            }
            let (x, y) = (n(it, a, 0, g, pos)?, n(it, a, 1, g, pos)?);
            Ok(V::new(exact_op('＋', &x, &y, g, pos)?, 1.0))
        }
        '－' => {
            let (x, y) = (n(it, a, 0, g, pos)?, n(it, a, 1, g, pos)?);
            Ok(V::new(exact_op('－', &x, &y, g, pos)?, 1.0))
        }
        '×' => {
            let (x, y) = (n(it, a, 0, g, pos)?, n(it, a, 1, g, pos)?);
            if let (Val::Int(p), Val::Int(q)) = (&x, &y) {
                if p.bit_length() + q.bit_length() > lang::MAX_INT_BITS {
                    return fatal(format!("×: число завелике (понад {} біт)", lang::MAX_INT_BITS), Some(pos));
                }
            }
            Ok(V::new(exact_op('×', &x, &y, g, pos)?, 1.0))
        }
        '÷' | '‰' => {
            let (x, y) = (n(it, a, 0, g, pos)?, n(it, a, 1, g, pos)?);
            if is_zero(&y) {
                return ngr(format!("{}: ділення на нуль", g), pos);
            }
            if g == '‰' {
                if let (Val::Int(p), Val::Int(q)) = (&x, &y) {
                    return Ok(V::int(p.divmod(q).1));
                }
                let ctx = dec::exact_ctx();
                let (dx, dy) = (to_dec(&x), to_dec(&y));
                let mut r = match dx.rem(&dy, &ctx) {
                    Ok(r) => r,
                    Err(s) if s == dec::INVALID => return ngr("‰: частка завелика для точної остачі (понад 60 цифр)", pos),
                    Err(s) => return dec_err(g, s, pos),
                };
                if !r.is_zero() && (r.neg) != (dy.neg && !dy.is_zero()) {
                    r = match r.add(&dy, &ctx) {
                        Ok(r) => r,
                        Err(s) => return dec_err(g, s, pos),
                    };
                }
                return Ok(V::dec(r));
            }
            if let (Val::Int(p), Val::Int(q)) = (&x, &y) {
                let (qq, rr) = p.divmod(q);
                if rr.is_zero() {
                    return Ok(V::int(qq));
                }
            }
            // суд 12: ціла частина частки й після неї 28 значущих цифр, разом не більше 60; e — порядок частки
            let (dx, dy) = (to_dec(&x), to_dec(&y));
            let mut ints = 0i64;
            if !dx.is_zero() {
                let mut e = dx.adjusted() - dy.adjusted();
                let sx = Dec { neg: false, coef: dx.coef.clone(), exp: dx.exp - e };
                let ay = Dec { neg: false, coef: dy.coef.clone(), exp: dy.exp };
                if sx.cmp(&ay) == std::cmp::Ordering::Less {
                    e -= 1;
                }
                ints = (e + 1).max(0);
            }
            if ints > 60 {
                return ngr("÷: ціла частина частки довша за 60 цифр — так ділиться лише націло", pos);
            }
            let mut ctx = dec::dec_ctx();
            ctx.prec = (28 + ints).min(60) as u64;
            match dx.div(&dy, &ctx) {
                Ok(d) => Ok(V::dec(d)),
                Err(s) => dec_err(g, s, pos),
            }
        }
        '⌊' => {
            let x = n(it, a, 0, g, pos)?;
            match x {
                Val::Int(i) => Ok(V::int(i)),
                Val::Dec(d) => {
                    let d = dec_ok((*d).clone(), "⌊", pos)?;
                    Ok(V::int(d.floor()))
                }
                _ => unreachable!(),
            }
        }
        '＝' => Ok(V::b(deep_eq(&a[0], &a[1])?)),
        '≠' => Ok(V::b(!deep_eq(&a[0], &a[1])?)),
        '‹' | '›' | '≤' | '≥' => {
            let ord = if let (Val::Str(x), Val::Str(y)) = (&a[0].v, &a[1].v) {
                crate::sort::str_cmp(&x.s, &y.s)          // той самий порядок рядків, що й ↑ ⇅ (суд 12)
            } else {
                let (x, y) = (n(it, a, 0, g, pos)?, n(it, a, 1, g, pos)?);
                num_cmp(&x, &y).unwrap()
            };
            Ok(V::b(match g {
                '‹' => ord == Ordering::Less,
                '›' => ord == Ordering::Greater,
                '≤' => ord != Ordering::Greater,
                _ => ord != Ordering::Less,
            }))
        }
        '¬' => Ok(V::b(!boolean(&a[0], g, pos)?)),
        '►' => it.call(&a[0], vec![a[1].clone()], pos),
        '▶' => it.call(&a[0], vec![a[1].clone(), a[2].clone()], pos),
        '☠' => ngr(show(&a[0], true)?, pos),
        '…' => {
            let (x, y) = (n(it, a, 0, g, pos)?, n(it, a, 1, g, pos)?);
            let (x, y) = match (x, y) {
                (Val::Int(x), Val::Int(y)) => (x, y),
                _ => return ngr("…: межі ряду мають бути цілими", pos),
            };
            let cnt = y.sub(&x).add(&Int::S(1));
            if cnt.cmp(&Int::S(it.max_size as i64)) == Ordering::Greater {
                return fatal(format!("…: ряд завеликий ({} > --розмір {})", cnt.to_string(), it.max_size), Some(pos));
            }
            let c = a[0].c.min(a[1].c);
            let mut v = Vec::new();
            if let Some(k) = cnt.to_i64() {
                if k > 0 {
                    v.reserve(k as usize);
                    let mut i = x.clone();
                    for _ in 0..k {
                        v.push(V::new(Val::Int(i.clone()), c));
                        i = i.add(&Int::S(1));
                    }
                }
            }
            Ok(V::listc(v, c))
        }
        'τ' => {
            let t = match &a[0].v {
                Val::Bool(_) => "●/○",
                Val::None => "∅",
                _ => kind(&a[0]),
            };
            Ok(V::strc(t.to_string(), a[0].s))
        }
        'ρ' => {
            let l = match &a[0].v {
                Val::Str(s) => s.nch,
                Val::List(l) => l.len(),
                Val::Dict(d) => d.len(),
                _ => return ngr(format!("ρ: довжина буває в рядка, списку чи словника, а не в {}", kind(&a[0])), pos),
            };
            Ok(V::new(Val::Int(Int::S(l as i64)), a[0].s))
        }
        '§' => {
            let el = match (&a[0].v, &a[1].v) {
                (Val::Dict(d), i) => {
                    let k = match i {
                        Val::Str(s) => s,
                        _ => return ngr("§: ключ словника — рядок", pos),
                    };
                    match d.get(&k.s) {
                        Some(e) => e.clone(),
                        None => V::none_c(a[0].s),
                    }
                }
                (Val::List(_), _) | (Val::Str(_), _) => {
                    let i = match &a[1].v {
                        Val::Int(i) => i.clone(),
                        _ => return ngr("§: індекс має бути цілим", pos),
                    };
                    let len = match &a[0].v {
                        Val::List(l) => l.len(),
                        Val::Str(s) => s.nch,
                        _ => 0,
                    };
                    let ii = int_idx(&Val::Int(i.clone())).unwrap();
                    if !(-(len as i64) <= ii && ii < len as i64) || matches!(i, Int::B(_)) {
                        return ngr(format!("§: індекс {} поза межами (довжина {})", i.to_string(), len), pos);
                    }
                    let k = if ii < 0 { (ii + len as i64) as usize } else { ii as usize };
                    match &a[0].v {
                        Val::List(l) => l[k].clone(),
                        Val::Str(s) => V::strc(s.char_at(k).to_string(), a[0].c),
                        _ => unreachable!(),
                    }
                }
                _ => return ngr(format!("§: очікувався список, рядок чи словник, а не {}", kind(&a[0])), pos),
            };
            let c = a[1].c.min(a[0].s);
            Ok(if c < el.c { capc(&el, c) } else { el })
        }
        '✎' => {
            let d = need_dict(&a[0], "✎", pos)?;
            let k = need_str(&a[1], "✎", pos)?;
            let mut nd = d.copy();
            nd.set(k, a[2].clone());
            Ok(V::new(Val::Dict(Rc::new(nd)), 1.0))
        }
        'κ' => {
            let d = need_dict(&a[0], "κ", pos)?;
            let s = a[0].s;
            Ok(V::listc(d.keys.iter().map(|k| V::new(Val::Str(k.clone()), s)).collect(), s))
        }
        'ε' => {
            let d = need_dict(&a[0], "ε", pos)?;
            let s = a[0].s;
            let pairs: Vec<V> = d.keys.iter().zip(&d.vals).map(|(k, e)| mk(vec![V::new(Val::Str(k.clone()), s), e.clone()], 1.0)).collect();
            Ok(mk(pairs, s))
        }
        '↺' => match &a[0].v {
            Val::List(l) => Ok(V::list(l.iter().rev().cloned().collect())),
            Val::Str(s) => Ok(V::str(s.s.chars().rev().collect())),
            _ => ngr(format!("↺: очікувався список або рядок, а не {}", kind(&a[0])), pos),
        },
        '↑' => {
            let lst = need_list(&a[0], "↑", pos)?;
            let mut kinds: Vec<&str> = lst.iter().map(kind).collect();
            kinds.sort();
            kinds.dedup();
            if !(kinds.iter().all(|k| *k == "число") || kinds.iter().all(|k| *k == "рядок")) {
                return ngr(format!("↑: сортувати можна лише самі числа або самі рядки, а тут {}", kinds.join(", ")), pos);
            }
            let order = crate::sort::sort_order(&lst, pos)?;
            Ok(V::listc(order.into_iter().map(|i| lst[i].clone()).collect(), a[0].c))
        }
        '✂' => {
            let s = need_str(&a[0], "✂", pos)?;
            let sep = need_str(&a[1], "✂", pos)?;
            let c = a[0].c.min(a[1].c);
            let mut sc = sep.s.chars();
            let parts: Vec<V> = if sep.s.is_empty() {
                uni::split_ws(&s.s).into_iter().map(|p| V::strc(p.to_string(), c)).collect()
            } else if let (Some(ch), None) = (sc.next(), sc.next()) {
                split_char(&s, ch, c)
            } else {
                s.s.split(&*sep.s).map(|p| V::strc(p.to_string(), c)).collect()
            };
            Ok(V::listc(parts, c))
        }
        '⁀' => {
            let lst = need_list(&a[0], "⁀", pos)?;
            let sep = need_str(&a[1], "⁀", pos)?;
            if a[0].n + sep.nch as u64 * lst.len() as u64 > it.max_size {
                return fatal(format!("⁀: значення завелике (> --розмір {})", it.max_size), Some(pos));
            }
            let mut out = String::new();
            for (i, e) in lst.iter().enumerate() {
                if i > 0 {
                    out.push_str(&sep.s);
                }
                out.push_str(&show(e, true)?);
            }
            Ok(V::str(out))
        }
        'σ' => {
            if a[0].n > it.max_size {
                return fatal(format!("σ: значення завелике (> --розмір {})", it.max_size), Some(pos));
            }
            Ok(V::str(show(&a[0], true)?))
        }
        'ν' => {
            let s0 = need_str(&a[0], "ν", pos)?;
            let s = uni::strip(&s0.s).trim_start_matches('\u{feff}');
            let s = s.replace('·', ".").replace('¯', "-");
            let odd = s.chars().find(|&c| uni::decimal(c).is_some() && !c.is_ascii_digit());
            if odd.is_some() || s.contains('_') {
                let tail = odd.map(|o| format!(" (тут {} U+{:04X})", uni::safe(&o.to_string()), o as u32)).unwrap_or_default();
                return ngr(format!("ν: «{}» — лише цифри 0–9{}", uni::safe(&s), tail), pos);
            }
            let t = uni::strip(&s);
            if let Some(i) = parse_py_int(t) {
                if i.bit_length() > lang::MAX_INT_BITS as u64 {          // суд 12: помилка, яку ловить ☂
                    return ngr(format!("ν: ціле понад {} біт", lang::MAX_INT_BITS), pos);
                }
                return Ok(V::int(i));
            }
            match Dec::parse(t) {
                Ok(d) => Ok(V::dec(dec_ok(d, "ν", pos)?)),
                Err(_) => ngr(format!("ν: «{}» не число", s), pos),
            }
        }
        'δ' => {
            let s = need_str(&a[0], "δ", pos)?;
            if s.s.starts_with('\u{feff}') {
                return ngr("δ: не JSON: на початку — BOM (U+FEFF); приберіть його: ⊢ рядок", pos);
            }
            match json::loads_unique(&s.s) {     // повтор ключа — помилка (суд 9б), як у еталона
                Ok(p) => match wrap(&p, a[0].c, 0) {
                    Ok(v) => Ok(v),
                    Err(WrapErr::Deep) => ngr(format!("δ: JSON вкладений надто глибоко (не глибше за {} рівнів)", lang::VALUE_MAX_DEPTH), pos),
                    Err(WrapErr::Surrogate) => ngr("δ: не JSON: у рядку неповний символ (сурогат)", pos),
                },
                Err(LoadErr::Syntax(m)) => ngr(format!("δ: не JSON: {}", json_uk(&m)), pos),
                Err(LoadErr::Constant(c)) => ngr(format!("δ: не JSON: «{}» — не число JSON", c), pos),
                Err(LoadErr::TooDeep) => ngr(format!("δ: JSON вкладений надто глибоко (не глибше за {} рівнів)", lang::VALUE_MAX_DEPTH), pos),
                Err(LoadErr::Ngr(m)) => ngr(m, pos),
            }
        }
        'Δ' => {
            if a[0].n > it.max_size {
                return fatal(format!("Δ: значення завелике (> --розмір {})", it.max_size), Some(pos));
            }
            match to_json(&a[0]) {
                Ok(t) => Ok(V::str(t)),
                Err(e) if !e.deep && !e.fatal && e.pos.is_none() => ngr(e.msg, pos),
                Err(e) => Err(e),
            }
        }
        '»' => {
            if a[0].n > it.max_size {
                return fatal(format!("»: значення завелике для друку (> --розмір {})", it.max_size), Some(pos));
            }
            let text = uni::visible(&show(&a[0], true)?, "\n\t", true);
            let agent = it.agent.clone();
            it.rec("вивід", vec![("агент".into(), crate::json::J::Str(agent)), ("текст".into(), trace_val(&V::str(text.clone()), true)?)])?;
            let ok = it.out.write_all(text.as_bytes()).and_then(|_| it.out.write_all(b"\n")).and_then(|_| it.out.flush());
            if let Err(e) = ok {
                if e.kind() == std::io::ErrorKind::BrokenPipe {
                    return Err(Box::new(E { msg: String::new(), pos: None, c: 1.0, wh: false, file: None, fatal: true, pipe: true, internal: false, deep: false }));
                }
                return fatal(format!("вивід: {}", e), Some(pos));
            }
            Ok(V::none())
        }
        '≈' => {
            let c = n(it, a, 1, g, pos)?;
            let ok = num_cmp(&c, &Val::Int(Int::S(0))) != Some(Ordering::Less) && num_cmp(&c, &Val::Int(Int::S(1))) != Some(Ordering::Greater);
            if !ok {
                return ngr("≈: впевненість має бути від 0 до 1", pos);
            }
            let cf = to_f64(&c);
            let agent = it.agent.clone();
            let tv = trace_val(&a[0], false)?;
            it.rec(
                "впевненість",
                vec![
                    ("агент".into(), crate::json::J::Str(agent)),
                    ("значення".into(), tv),
                    ("було".into(), crate::json::J::Float(a[0].c)),
                    ("стало".into(), crate::json::J::Float(cf)),
                ],
            )?;
            Ok(capc(&a[0], cf))
        }
        '±' => Ok(V::new(Val::Float(a[0].c), a[0].c.min(it.cpc()))),
        '⚗' => {
            let lst = need_list(&a[0], "⚗", pos)?;
            let t = to_f64(&n(it, a, 1, g, pos)?);
            let sc = lst.iter().fold(a[0].s.min(a[1].c).min(it.cpc()), |m, x| m.min(x.c));
            if !(0.0..=1.0).contains(&t) {
                return ngr("⚗: поріг має бути від 0 до 1", pos);
            }
            let mut kept = Vec::new();
            for x in lst.iter() {
                let ok = x.c >= t;
                let agent = it.agent.clone();
                it.rec(
                    "відсів",
                    vec![
                        ("агент".into(), crate::json::J::Str(agent)),
                        ("значення".into(), trace_val(x, false)?),
                        ("впевненість".into(), crate::json::J::Float(x.c)),
                        ("поріг".into(), crate::json::J::Float(t)),
                        ("рішення".into(), crate::json::J::s(if ok { "лишено" } else { "відкинуто" })),
                    ],
                )?;
                if ok {
                    kept.push(x.clone());
                }
            }
            Ok(mk(kept, sc))
        }
        '🜄' => {
            let key = need_str(&a[0], "🜄", pos)?;
            let kc = a[0].c.min(it.cpc());
            it.mem_c = it.mem_c.min(kc);
            let val = if kc < a[1].c { capc(&a[1], kc) } else { a[1].clone() };
            let shown = trace_val(&val, false)?; // спершу — чи можна записати в слід (суд 9: помилка ПІСЛЯ запису в памʼять)
            it.memory.insert(key.s.to_string(), val.clone());
            let agent = it.agent.clone();
            it.rec(
                "памʼять",
                vec![
                    ("агент".into(), crate::json::J::Str(agent)),
                    ("дія".into(), crate::json::J::s("запамʼятати")),
                    ("ключ".into(), crate::json::J::s(&key.s)),
                    ("значення".into(), shown),
                    ("впевненість".into(), crate::json::J::Float(val.c)),
                ],
            )?;
            Ok(V::none_c(it.cpc()))
        }
        '🜃' => {
            let key = need_str(&a[0], "🜃", pos)?;
            let res = it.memory.get(&*key.s).cloned().unwrap_or_else(V::none);
            let c = a[0].c.min(it.mem_c).min(it.cpc());
            let res = if c < res.c { capc(&res, c) } else { res };
            let agent = it.agent.clone();
            it.rec(
                "памʼять",
                vec![
                    ("агент".into(), crate::json::J::Str(agent)),
                    ("дія".into(), crate::json::J::s("пригадати")),
                    ("ключ".into(), crate::json::J::s(&key.s)),
                    ("значення".into(), trace_val(&res, false)?),
                    ("впевненість".into(), crate::json::J::Float(res.c)),
                ],
            )?;
            Ok(res)
        }
        '🜍' => {
            let r = it.call(&a[1], vec![a[0].clone()], pos)?;
            let ok = boolean(&r, g, pos)?;
            it.taint(r.c);
            let agent = it.agent.clone();
            it.rec(
                "перевірка",
                vec![
                    ("агент".into(), crate::json::J::Str(agent)),
                    ("значення".into(), trace_val(&a[0], false)?),
                    ("результат".into(), crate::json::J::s(if ok { "пройдена" } else { "НЕ пройдена" })),
                    ("впевненість".into(), crate::json::J::Float(r.c)),
                ],
            )?;
            if !ok {
                return ngr_c(format!("🜍: перевірку не пройдено для {}", brief(&a[0], 60)), pos, r.c.min(a[0].c).min(it.cpc()));
            }
            it.halt_c = it.halt_c.min(r.c);
            Ok(if r.c < a[0].c { capc(&a[0], r.c) } else { a[0].clone() })
        }
        '∋' => match &a[0].v {
            Val::Str(x) => {
                let y = need_str(&a[1], "∋", pos)?;
                Ok(V::b(x.s.contains(&*y.s)))
            }
            Val::List(l) => {
                for e in l.iter() {
                    if deep_eq(e, &a[1])? {
                        return Ok(V::b(true));
                    }
                }
                Ok(V::b(false))
            }
            Val::Dict(d) => {
                let y = need_str(&a[1], "∋", pos)?;
                Ok(V::b(d.find(&y.s).is_some()))
            }
            _ => ngr(format!("∋: очікувався рядок, список чи словник, а не {}", kind(&a[0])), pos),
        },
        '⇣' | '⇡' => {
            let x = need_str(&a[0], &g.to_string(), pos)?;
            Ok(V::str(if g == '⇣' { uni::lower(&x.s) } else { uni::upper(&x.s) }))
        }
        '⊏' => {
            let len = match &a[0].v {
                Val::Str(s) => s.nch,
                Val::List(l) => l.len(),
                _ => return ngr(format!("⊏: очікувався рядок чи список, а не {}", kind(&a[0])), pos),
            };
            let mut ends = [None, None];
            for (k, b) in [&a[1], &a[2]].iter().enumerate() {
                match &b.v {
                    Val::None => {}
                    Val::Int(i) => ends[k] = int_idx(&Val::Int(i.clone())),
                    _ => return ngr("⊏: межі — цілі числа (до ∅ — до кінця)", pos),
                }
            }
            let (s, e) = slice_bounds(len, ends[0], ends[1]);
            match &a[0].v {
                Val::Str(st) => Ok(V::str(st.slice(s, e).to_string())),
                Val::List(l) => Ok(V::list(l[s..e].to_vec())),
                _ => unreachable!(),
            }
        }
        '⊳' => match &a[0].v {
            Val::Str(x) => {
                let y = need_str(&a[1], "⊳", pos)?;
                Ok(V::i64(match x.s.find(&*y.s) {
                    Some(b) => x.char_index(b) as i64,
                    None => -1,
                }))
            }
            Val::List(l) => {
                for (i, e) in l.iter().enumerate() {
                    if deep_eq(e, &a[1])? {
                        return Ok(V::i64(i as i64));
                    }
                }
                Ok(V::i64(-1))
            }
            _ => ngr(format!("⊳: очікувався рядок чи список, а не {}", kind(&a[0])), pos),
        },
        '⇄' => {
            let src = need_str(&a[0], "⇄", pos)?;
            let old = need_str(&a[1], "⇄", pos)?;
            let new = need_str(&a[2], "⇄", pos)?;
            let mut oc = old.s.chars();
            let one = match (oc.next(), oc.next()) {
                (Some(ch), None) => Some(ch),
                _ => None,
            };
            let cnt = if old.s.is_empty() {
                src.nch as u64 + 1
            } else if let Some(ch) = one {
                src.s.matches(ch).count() as u64
            } else {
                src.s.matches(&*old.s).count() as u64
            };
            if let Some(ch) = one {
                if src.nch as u64 + cnt * new.nch as u64 > it.max_size {
                    return fatal(format!("⇄: значення завелике (> --розмір {})", it.max_size), Some(pos));
                }
                return Ok(V::str(src.s.replace(ch, &new.s)));
            }
            if src.nch as u64 + cnt * new.nch as u64 > it.max_size {
                return fatal(format!("⇄: значення завелике (> --розмір {})", it.max_size), Some(pos));
            }
            Ok(V::str(py_replace(&src.s, &old.s, &new.s)))
        }
        '⊢' => {
            let x = need_str(&a[0], "⊢", pos)?;
            // пробіли й усе невидиме за одним правилом мови (суд 12: досі лише BOM і ZWSP)
            Ok(V::str(x.s.trim_matches(|c: char| uni::isspace(c) || uni::invisible(c)).to_string()))
        }
        '≅' | '⌗' => {
            let x = n(it, a, 0, g, pos)?;
            let k = n(it, a, 1, g, pos)?;
            let k = match &k {
                Val::Int(Int::S(k)) if (0..=12).contains(k) => *k,
                _ => return ngr(format!("{}: кількість знаків — ціле від 0 до 12", g), pos),
            };
            let q = match to_dec(&x).quantize(-k, Round::HalfUp, &dec::wide_ctx()) {
                Ok(q) => q,
                Err(s) => return dec_err(g, s, pos),
            };
            if g == '⌗' {
                let q = if q.is_zero() { Dec { neg: false, ..q } } else { q };
                return Ok(V::str(q.to_fixed()));
            }
            if k == 0 {
                return Ok(V::int(q.trunc()));
            }
            Ok(V::dec(q))
        }
        '⌂' => Ok(V::list(it.argv.iter().map(|x| V::str(x.clone())).collect())),
        'χ' => match &a[0].v {
            Val::Str(s) => crate::xml::parse(it, &s.s, pos),
            Val::Dict(_) => Ok(V::str(crate::xml::write(it, &a[0], pos)?)),
            _ => ngr(format!("χ: очікувався рядок XML або елемент (словник), а не {}", kind(&a[0])), pos),
        },
        '↘' => {
            need_dict(&a[0], "↘", pos)?;
            let p = need_str(&a[1], "↘", pos)?;
            crate::xml::path(it, &a[0], &p.s, pos)
        }
        '✓' => {
            let mut errs = Vec::new();
            crate::schema::check(it, &a[0], &a[1], "", &mut errs, pos, 0)?;
            if !errs.is_empty() {
                let more = if errs.len() > 10 { format!(" … ще {}", errs.len() - 10) } else { String::new() };
                let shown: Vec<&str> = errs.iter().take(10).map(|e| e.as_str()).collect();
                return ngr(format!("✓: не відповідає схемі: {}{}", shown.join("; "), more), pos);
            }
            Ok(a[0].clone())
        }
        '◷' => {
            let tname = |v: &Val| -> &'static str {
                match v {
                    Val::Int(_) => "int",
                    Val::Dec(_) => "Decimal",
                    Val::Float(_) => "float",
                    Val::Bool(_) => "bool",
                    Val::None => "NoneType",
                    Val::List(_) => "list",
                    Val::Dict(_) => "dict",
                    Val::Fn(_) => "Fn",
                    Val::Str(_) => "str",
                }
            };
            let iso = |v: &Val| -> R<crate::dates::Dt> {
                match v {
                    Val::Str(s) => match crate::dates::iso(&s.s) {
                        Some(d) => Ok(d),
                        None => {
                            let t: String = uni::safe(&s.s).chars().take(40).collect();
                            if crate::dates::iso_syntax(&s.s) {
                                ngr(format!("◷: «{}» — запис ISO, але такої дати чи часу немає", t), pos)
                            } else {
                                ngr(format!("◷: «{}» — не дата ISO (2026-10-15 або 2026-10-15T09:30:00)", t), pos)
                            }
                        }
                    },
                    other => ngr(format!("◷: дата — рядок ISO (2026-10-15 або 2026-10-15T09:30:00), а не {}", tname(other)), pos),
                }
            };
            let da = iso(&a[0].v)?;
            let derr = |e: crate::dates::DateErr| -> R<V> {
                match e {
                    crate::dates::DateErr::Tz => ngr("◷: одна дата з часовим поясом, інша — без; додайте пояс до обох", pos),
                    crate::dates::DateErr::Range => ngr("◷: дата поза межами (рік 1–9999)", pos),
                    crate::dates::DateErr::Dec(s) => dec_err(g, s, pos),
                }
            };
            match &a[1].v {
                Val::Str(_) => {
                    let db = iso(&a[1].v)?;
                    match crate::dates::diff(&da, &db) {
                        Ok(v) => Ok(V::new(v, 1.0)),
                        Err(e) => derr(e),
                    }
                }
                Val::Int(_) | Val::Dec(_) | Val::Float(_) => {
                    let nn = to_dec(&a[1].v);
                    match crate::dates::add(&da, &nn) {
                        Ok(s) => Ok(V::str(s)),
                        Err(e) => derr(e),
                    }
                }
                _ => ngr("◷: другий аргумент — дата (рядок ISO) або кількість днів (число)", pos),
            }
        }
        '▦' => {
            let t0 = need_str(&a[0], "▦", pos)?;
            let text = t0.s.strip_prefix('\u{feff}').unwrap_or(&t0.s);
            let limit = text.chars().count().max(1);
            let rd = match crate::csvp::read(text, limit) {
                Ok(r) => r,
                Err(e) => return ngr(format!("▦: не CSV ({})", e), pos),
            };
            if rd.is_empty() {
                return Ok(V::list(Vec::new()));
            }
            let head = &rd[0];
            let mut uniq: Vec<&String> = head.iter().collect();
            uniq.sort();
            uniq.dedup();
            if uniq.len() != head.len() {
                return ngr(format!("▦: однакові заголовки ({}) — значення загубилися б", head.join(", ")), pos);
            }
            let keys: Vec<Rc<PStr>> = head.iter().map(|h| Rc::new(PStr::from(h))).collect();
            let mut out = Vec::new();
            for (i, r) in rd[1..].iter().enumerate() {
                if r.is_empty() {
                    continue;
                }
                if r.len() != head.len() {
                    return ngr(
                        format!("▦: рядок {} має {} полів, а заголовків {} — нічого не губимо мовчки", i + 2, r.len(), head.len()),
                        pos,
                    );
                }
                let mut d = Dict::new();
                for (k, x) in keys.iter().zip(r) {
                    d.set(k.clone(), V::str(x.clone()));
                }
                out.push(V::new(Val::Dict(Rc::new(d)), 1.0));
            }
            Ok(V::list(out))
        }
        '⌕' | '≋' => {
            let gs = g.to_string();
            let x = need_str(&a[0], &gs, pos)?;
            let pat = need_str(&a[1], &gs, pos)?;
            let r = match crate::rx::Rx::new(&pat.s) {
                Ok(r) => r,
                Err(crate::rx::RxErr::Re(e)) => {
                    return ngr(format!("{}: хибний шаблон: {}", g, crate::uni::in_words(&crate::lang::RE_ERRORS, &crate::rx::re_error_text(&e, &pat.s))), pos)
                }
                Err(crate::rx::RxErr::Rx(m)) => return ngr(format!("{}: {}", g, m), pos),
            };
            let text: Vec<char> = x.s.chars().collect();
            let max = it.max_size;
            let mut steps = it.steps_left;
            let mut pay = |k: i64| -> Result<(), String> {
                steps -= k;
                if steps < 0 {
                    return Err(String::new());
                }
                Ok(())
            };
            if g == '≋' {
                let tmpl: Vec<char> = need_str(&a[2], "≋", pos)?.s.chars().collect();
                let pieces = match r.template(&tmpl) {
                    Ok(p) => p,
                    Err(m) => return ngr(format!("≋: {}", m), pos),
                };
                let mut out = String::new();
                let mut last = 0usize;
                let mut total = 0u64;
                let mut fail: Option<Box<E>> = None;
                let res = r.finditer(&text, &mut pay, &mut |m| {
                    let groups = r.groups(&text, m);
                    let mut rep = String::new();
                    for p in &pieces {
                        match p {
                            crate::rx::Piece::Lit(s) => rep.push_str(s),
                            crate::rx::Piece::Group(k) => rep.push_str(groups[*k].as_deref().unwrap_or("")),
                        }
                    }
                    let s0 = m[0].unwrap();
                    let piece_len = (s0 - last.min(s0)) as u64 + rep.chars().count() as u64;
                    total += piece_len;
                    if total > max {
                        fail = Some(fatal::<()>(format!("≋: значення завелике (> --розмір {})", max), Some(pos)).unwrap_err());
                        return Err("x".into());
                    }
                    out.extend(text[last..s0].iter());
                    out.push_str(&rep);
                    last = m[1].unwrap();
                    Ok(())
                });
                it.steps_left = steps;
                if let Some(e) = fail {
                    return Err(e);
                }
                if let Err(m) = res {
                    if m.is_empty() {
                        return fatal("перевищено ліміт кроків (--кроки) у регулярному виразі", Some(pos));
                    }
                    return internal(m);
                }
                out.extend(text[last..].iter());
                return Ok(V::str(out));
            }
            let mut out: Vec<V> = Vec::new();
            let mut size = 0u64;
            let mut fail: Option<Box<E>> = None;
            let one = r.ngroups == 1;
            let res = r.finditer(&text, &mut pay, &mut |m| {
                let groups = r.groups(&text, m);
                if one {
                    let item = groups[0].clone().unwrap_or_default();
                    size += 1 + item.chars().count() as u64;
                    if size > max {
                        fail = Some(fatal::<()>(format!("⌕: значення завелике (> --розмір {})", max), Some(pos)).unwrap_err());
                        return Err("x".into());
                    }
                    out.push(V::str(item));
                } else {
                    let parts: Vec<String> = groups[1..].iter().map(|p| p.clone().unwrap_or_default()).collect();
                    size += 1 + parts.iter().map(|p| p.chars().count() as u64 + 1).sum::<u64>();
                    if size > max {
                        fail = Some(fatal::<()>(format!("⌕: значення завелике (> --розмір {})", max), Some(pos)).unwrap_err());
                        return Err("x".into());
                    }
                    out.push(V::list(parts.into_iter().map(V::str).collect()));
                }
                Ok(())
            });
            it.steps_left = steps;
            if let Some(e) = fail {
                return Err(e);
            }
            if let Err(m) = res {
                if m.is_empty() {
                    return fatal("перевищено ліміт кроків (--кроки) у регулярному виразі", Some(pos));
                }
                return internal(m);
            }
            Ok(V::list(out))
        }
        _ => crate::prims2::prim(it, g, a, pos),
    }
}

fn to_f64(v: &Val) -> f64 {
    match v {
        Val::Int(i) => i.to_f64(),
        Val::Dec(d) => d.to_f64(),
        Val::Float(f) => *f,
        _ => 0.0,
    }
}

/// str.replace як у Python (порожній «що» — між усіма символами).
pub fn py_replace(s: &str, old: &str, new: &str) -> String {
    if old.is_empty() {
        let mut out = String::with_capacity(s.len() + new.len() * (s.len() + 1));
        out.push_str(new);
        for c in s.chars() {
            out.push(c);
            out.push_str(new);
        }
        return out;
    }
    s.replace(old, new)
}

/// int(s) Python після strip: знак і цифри 0–9.
pub fn parse_py_int(t: &str) -> Option<Int> {
    let (neg, d) = if let Some(r) = t.strip_prefix('-') {
        (true, r)
    } else if let Some(r) = t.strip_prefix('+') {
        (false, r)
    } else {
        (false, t)
    };
    if d.is_empty() || !d.bytes().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let digits = d.trim_start_matches('0');
    Some(Int::from_dec(neg, if digits.is_empty() { "0" } else { digits }))
}

/// Мале число для Dec::small_exact: (знак, коефіцієнт, порядок) — як to_dec, без копії коефіцієнта.
#[inline]
fn small_dec(x: &Val) -> Option<(bool, u64, i64)> {
    match x {
        Val::Int(Int::S(i)) => Some((*i < 0, i.unsigned_abs(), 0)),
        Val::Dec(d) => Some((d.neg, d.coef.to_u64()?, d.exp)),
        _ => None,
    }
}

/// Точне ＋ － × з десятковими над малими — без довгої арифметики (None — загальний шлях).
pub fn small_exact(op: char, x: &Val, y: &Val) -> Option<Val> {
    Some(Val::Dec(Rc::new(Dec::small_exact(op, small_dec(x)?, small_dec(y)?)?)))
}

fn exact_op(op: char, x: &Val, y: &Val, g: char, pos: Pos) -> R<Val> {
    if let (Val::Int(a), Val::Int(b)) = (x, y) {
        return Ok(Val::Int(match op {
            '＋' => a.add(b),
            '－' => a.sub(b),
            _ => a.mul(b),
        }));
    }
    if let Some(r) = small_exact(op, x, y) {
        return Ok(r);
    }
    let (a, b) = (to_dec(x), to_dec(y));
    let ctx = dec::exact_ctx();
    let r = match op {
        '＋' => a.add(&b, &ctx),
        '－' => a.sub(&b, &ctx),
        _ => a.mul(&b, &ctx),
    };
    match r {
        Ok(d) => Ok(Val::Dec(Rc::new(d))),
        Err(s) if s == dec::INEXACT || s == dec::OVERFLOW || s == dec::UNDERFLOW => {
            ngr(format!("{}: точний результат довший за 60 значущих цифр — округліть (≅) або діліть (÷)", g), pos)
        }
        Err(s) => dec_err(g, s, pos),
    }
}

pub enum WrapErr {
    Deep,
    Surrogate,
}

/// wrap(p, c): дані JSON у значення мови (вкладеність — не глибше VALUE_MAX_DEPTH).
pub fn wrap(p: &P<'_>, c: f64, depth: u64) -> Result<V, WrapErr> {
    let (mut keys, mut strs) = (Interner::always(), Interner::new());
    wrap_c(p, c, depth, &mut keys, &mut strs)
}

fn wrap_c<'a>(p: &'a P<'_>, c: f64, depth: u64, keys: &mut Interner<'a>, strs: &mut Interner<'a>) -> Result<V, WrapErr> {
    match p {
        P::Null => Ok(V::none_c(c)),
        P::Bool(b) => Ok(V::new(Val::Bool(*b), c)),
        P::Int(s) => {
            if s.len() <= 18 {
                return Ok(V::new(Val::Int(Int::S(s.parse::<i64>().unwrap())), c));
            }
            let (neg, d) = if let Some(r) = s.strip_prefix('-') { (true, r) } else { (false, *s) };
            let d = d.trim_start_matches('0');
            Ok(V::new(Val::Int(Int::from_dec(neg, if d.is_empty() { "0" } else { d })), c))
        }
        P::Float(s) => Ok(V::new(Val::Dec(Rc::new(Dec::parse(s).unwrap())), c)),
        P::Str(s, sur) => {
            if *sur {
                return Err(WrapErr::Surrogate);
            }
            let r = strs.get(s, || s.chars().count());
            let n = r.nch as u64 + 1;
            Ok(V { v: Val::Str(r), c, s: c, n })
        }
        P::Arr(xs) => {
            if depth >= lang::VALUE_MAX_DEPTH {
                return Err(WrapErr::Deep);
            }
            let mut v = Vec::with_capacity(xs.len());
            for x in xs {
                v.push(wrap_c(x, c, depth + 1, keys, strs)?);
            }
            Ok(V::listc(v, c))
        }
        P::Obj(kv) => {
            if depth >= lang::VALUE_MAX_DEPTH {
                return Err(WrapErr::Deep);
            }
            // ключі вже без повторів (розбір лишає перше місце й останнє значення) — без пошуку
            let (mut ks, mut vs) = (Vec::with_capacity(kv.len()), Vec::with_capacity(kv.len()));
            for (k, ksur, x) in kv {
                if *ksur {
                    return Err(WrapErr::Surrogate);
                }
                ks.push(keys.get(k, || k.chars().count()));
                vs.push(wrap_c(x, c, depth + 1, keys, strs)?);
            }
            Ok(V::new(Val::Dict(Rc::new(Dict::from_unique(ks, vs))), c))
        }
    }
}

/// Помилка JSON словами (json_uk еталона; суд 9б: «Expecting value: line 1 column 1 (char 0)»).
pub fn json_uk(m: &str) -> String {
    const UK: [(&str, &str); 11] = [
        ("Expecting value", "очікувалося значення"),
        ("Extra data", "зайві дані після значення"),
        ("Expecting property name enclosed in double quotes", "очікувалася назва поля в подвійних лапках"),
        ("Expecting ':' delimiter", "очікувалася «:»"),
        ("Expecting ',' delimiter", "очікувалася «,»"),
        ("Unterminated string starting at", "незакритий рядок, що почався"),
        ("Invalid control character at", "керівний символ у рядку"),
        ("Invalid \\uXXXX escape", "хибне \\uXXXX"),
        ("Invalid \\escape", "хибне екранування"),
        ("Illegal trailing comma before end of object", "зайва кома перед кінцем обʼєкта"),
        ("Illegal trailing comma before end of array", "зайва кома перед кінцем масиву"),
    ];
    let mut s = m.to_string();
    for (en, uk) in UK {
        if let Some(rest) = s.strip_prefix(en) {
            s = format!("{}{}", uk, rest);
            break;
        }
    }
    // «line L column C (char N)» → «рядок L, стовпець C (символ N)»
    if let Some(i) = s.rfind("line ") {
        let tail = &s[i + 5..];
        let num = |t: &str| -> Option<(String, usize)> {
            let n = t.bytes().take_while(|b| b.is_ascii_digit()).count();
            if n == 0 { None } else { Some((t[..n].to_string(), n)) }
        };
        if let Some((l, a)) = num(tail) {
            if let Some(t2) = tail[a..].strip_prefix(" column ") {
                if let Some((c, b)) = num(t2) {
                    if let Some(t3) = t2[b..].strip_prefix(" (char ") {
                        if let Some((ch, k)) = num(t3) {
                            if &t3[k..] == ")" {
                                s = format!("{}рядок {}, стовпець {} (символ {})", &s[..i], l, c, ch);
                            }
                        }
                    }
                }
            }
        }
    }
    s
}
