//! Схеми ✓ — як nigredo.check_schema / schema_leaf.
use crate::dec::Dec;
use crate::interp::*;
use crate::lexer::Pos;
use crate::uni;
use crate::value::*;
use std::cmp::Ordering;

const TYPES: [&str; 11] = ["число", "ціле", "рядок", "дата", "●/○", "істинність", "∅", "ніщо", "будь-що", "список", "словник"];
const BOUNDED: [&str; 5] = ["число", "ціле", "рядок", "список", "словник"];

struct Leaf {
    t: String,
    nullable: bool,
    bounds: Option<(Option<Dec>, Option<Dec>)>,
    enum_num: Option<Vec<Dec>>,
    enum_str: Option<Vec<String>>,
}

/// SCHEMA_NUM: [¯-]?[0-9]+(\.[0-9]+)?
fn schema_num(s: &str) -> bool {
    let s = s.strip_prefix('¯').or_else(|| s.strip_prefix('-')).unwrap_or(s);
    let (a, b) = match s.split_once('.') {
        Some((a, b)) => (a, Some(b)),
        None => (s, None),
    };
    !a.is_empty() && a.bytes().all(|c| c.is_ascii_digit()) && b.map_or(true, |b| !b.is_empty() && b.bytes().all(|c| c.is_ascii_digit()))
}

fn num_dec(s: &str) -> Dec {
    Dec::parse(&s.replace('¯', "-")).unwrap()
}

fn sorted_types() -> String {
    let mut t: Vec<&str> = TYPES.to_vec();
    t.sort();
    t.join(", ")
}

fn leaf(sv: &str) -> Result<Leaf, String> {
    let (t0, colon, rest) = crate::parser::partition(sv, ':');
    let nullable = t0.ends_with('?');
    let t = t0.trim_end_matches('?');
    if !TYPES.contains(&t) {
        return Err(format!("невідомий тип у схемі «{}» (є: {})", uni::safe(sv), sorted_types()));
    }
    let mut l = Leaf { t: t.to_string(), nullable, bounds: None, enum_num: None, enum_str: None };
    if !colon.is_empty() && rest.is_empty() {
        return Err(format!("«{}»: після «:» — межі (0..100, 1.., ..50) чи перелік (a|b)", uni::safe(sv)));
    }
    if !rest.is_empty() && !rest.contains('|') && rest.contains("..") {
        if !BOUNDED.contains(&t) {
            return Err(format!("межі «{}» — лише для {} (не {})", uni::safe(rest), BOUNDED.join(", "), t));
        }
        // fullmatch (NUM)?\.\.(NUM)? — перше «..», що дає збіг
        let mut found = None;
        let mut start = 0;
        while let Some(i) = rest[start..].find("..") {
            let i = start + i;
            let (g1, g2) = (&rest[..i], &rest[i + 2..]);
            if (g1.is_empty() || schema_num(g1)) && (g2.is_empty() || schema_num(g2)) {
                found = Some((g1, g2));
                break;
            }
            start = i + 1;
        }
        let (g1, g2) = match found {
            Some((a, b)) if !(a.is_empty() && b.is_empty()) => (a, b),
            _ => return Err(format!("межі «{}» — скінченні числа цифрами 0–9: 0..100, 1.., ..50, ¯5..5", uni::safe(rest))),
        };
        let lo = if g1.is_empty() { None } else { Some(num_dec(g1)) };
        let hi = if g2.is_empty() { None } else { Some(num_dec(g2)) };
        if let (Some(a), Some(b)) = (&lo, &hi) {
            if a.cmp(b) == Ordering::Greater {
                return Err(format!("межі «{}» навпаки — нижня більша за верхню", uni::safe(rest)));
            }
        }
        l.bounds = Some((lo, hi));
    } else if !rest.is_empty() {
        let alts: Vec<&str> = rest.split('|').collect();
        if alts.contains(&"") {
            return Err(format!(
                "перелік «{}» має порожню альтернативу (a||b, a|) — порожній рядок пишіть явно окремою перевіркою",
                uni::safe(rest)
            ));
        }
        if t == "число" || t == "ціле" {
            if !alts.iter().all(|a| schema_num(a)) {
                return Err(format!("перелік чисел «{}» — цифрами 0–9 (¯ для відʼємних)", uni::safe(rest)));
            }
            l.enum_num = Some(alts.iter().map(|a| num_dec(a)).collect());
        } else {
            l.enum_str = Some(alts.iter().map(|a| a.to_string()).collect());
        }
    }
    Ok(l)
}

fn num_as_dec(v: &Val) -> Option<Dec> {
    match v {
        Val::Int(i) => Some(Dec::from_int(i)),
        Val::Dec(d) => Some((**d).clone()),
        Val::Float(f) => Some(Dec::from_f64(*f)),
        _ => None,
    }
}

pub fn check(it: &mut Interp, x: &V, sch: &V, path: &str, errs: &mut Vec<String>, pos: Pos, depth: u32) -> R<()> {
    if depth > 200 {
        return ngr("✓: схема вкладена надто глибоко", pos);
    }
    it.work(64, pos)?;
    let where_ = if path.is_empty() { "значення".to_string() } else { path.to_string() };
    match &sch.v {
        Val::Str(sv) => {
            let l = match leaf(&sv.s) {
                Ok(l) => l,
                Err(e) => return ngr(format!("✓: {}", e), pos),
            };
            let rest = crate::parser::partition(&sv.s, ':').2.to_string();
            let v = &x.v;
            if matches!(v, Val::None) && (l.nullable || matches!(l.t.as_str(), "∅" | "ніщо" | "будь-що")) {
                return Ok(());
            }
            let mut ok = match l.t.as_str() {
                "число" => matches!(v, Val::Int(_) | Val::Dec(_) | Val::Float(_)),
                "ціле" => matches!(v, Val::Int(_)) || matches!(v, Val::Dec(d) if d.is_integral()),
                "рядок" | "дата" => matches!(v, Val::Str(_)),
                "●/○" | "істинність" => matches!(v, Val::Bool(_)),
                "∅" | "ніщо" => matches!(v, Val::None),
                "будь-що" => true,
                "список" => matches!(v, Val::List(_)),
                _ => matches!(v, Val::Dict(_)),
            };
            if l.t == "дата" && ok {
                if let Val::Str(s) = v {
                    ok = s.s.chars().count() == 10 && crate::dates::iso(&s.s).map_or(false, |d| d.date_only);
                }
            }
            if !ok {
                errs.push(format!("{}: очікувалося {}, а не {} {}", where_, sv.s, kind(x), brief(x, 30)));
                return Ok(());
            }
            if let Some((lo, hi)) = &l.bounds {
                let (n, is_len) = match v {
                    Val::Str(s) => (Val::Int(crate::int::Int::S(s.nch as i64)), true),
                    Val::List(xs) => (Val::Int(crate::int::Int::S(xs.len() as i64)), true),
                    Val::Dict(d) => (Val::Int(crate::int::Int::S(d.len() as i64)), true),
                    other => (other.clone(), false),
                };
                let nd = match num_as_dec(&n) {
                    Some(d) => d,
                    None => return ngr(format!("✓: межі «{}» — для числа, рядка чи списку", uni::safe(&rest)), pos),
                };
                let below = lo.as_ref().map_or(false, |lo| nd.cmp(lo) == Ordering::Less);
                let above = hi.as_ref().map_or(false, |hi| nd.cmp(hi) == Ordering::Greater);
                if below || above {
                    errs.push(format!("{}: {}{} поза {}", where_, if is_len { "довжина " } else { "" }, fmt_num(&n), rest));
                }
            } else if let Some(en) = &l.enum_num {
                let d = match v {
                    Val::Float(f) => Dec::parse(&crate::pyf::repr(*f)).unwrap(),
                    other => num_as_dec(other).unwrap(),
                };
                if !en.iter().any(|e| e.cmp(&d) == Ordering::Equal) {
                    errs.push(format!("{}: {} — не з переліку {}", where_, brief(x, 30), rest));
                }
            } else if let Some(en) = &l.enum_str {
                let s = show(x, true);
                if !en.contains(&s) {
                    errs.push(format!("{}: {} — не з переліку {}", where_, brief(x, 30), rest));
                }
            }
            Ok(())
        }
        Val::List(sl) => {
            let xs = match &x.v {
                Val::List(xs) => xs.clone(),
                _ => {
                    errs.push(format!("{}: очікувався список, а не {}", where_, kind(x)));
                    return Ok(());
                }
            };
            if sl.len() > 1 {
                return ngr("✓: схема списку — 【S】 (один елемент-схема) або 【】 (будь-який список)", pos);
            }
            if let Some(s0) = sl.first() {
                for (i, e) in xs.iter().enumerate() {
                    check(it, e, s0, &format!("{}[{}]", path, i), errs, pos, depth + 1)?;
                    if errs.len() > 50 {
                        return Ok(());
                    }
                }
            }
            Ok(())
        }
        Val::Dict(sd) => {
            let d = match &x.v {
                Val::Dict(d) => d.clone(),
                _ => {
                    errs.push(format!("{}: очікувався словник, а не {}", where_, kind(x)));
                    return Ok(());
                }
            };
            // поля: «k?» — необовʼязкове; той самий ключ двічі (k і k?) — діє останній
            let mut fields: Vec<(String, bool, V)> = Vec::new();
            for (k, s_) in sd.keys.iter().zip(&sd.vals) {
                if &*k.s == "…" {
                    continue;
                }
                let name = k.s.trim_end_matches('?').to_string();
                let opt = k.s.ends_with('?');
                match fields.iter_mut().find(|f| f.0 == name) {
                    Some(f) => {
                        f.1 = opt;
                        f.2 = s_.clone();
                    }
                    None => fields.push((name, opt, s_.clone())),
                }
            }
            it.work(64 * (fields.len() + d.len()) as u64, pos)?;
            for (k, opt, s_) in &fields {
                match d.get(k) {
                    Some(e) => {
                        let p = if path.is_empty() { k.clone() } else { format!("{}.{}", path, k) };
                        let e = e.clone();
                        check(it, &e, s_, &p, errs, pos, depth + 1)?;
                    }
                    None => {
                        if !opt {
                            errs.push(format!("{}{}: бракує поля", if path.is_empty() { String::new() } else { format!("{}.", path) }, k));
                        }
                    }
                }
            }
            let extra: Vec<usize> = (0..d.len()).filter(|&i| !fields.iter().any(|f| *f.0 == *d.keys[i].s)).collect();
            match sd.get("…") {
                None => {
                    if !extra.is_empty() {
                        let names: Vec<String> = extra.iter().take(5).map(|&i| uni::safe(&d.keys[i].s)).collect();
                        errs.push(format!("{}: зайві поля {} (дозволити — 「…」 「будь-що」)", where_, names.join(", ")));
                    }
                }
                Some(s_any) => {
                    let s_any = s_any.clone();
                    for i in extra {
                        let k = &d.keys[i].s;
                        let p = if path.is_empty() { k.to_string() } else { format!("{}.{}", path, k) };
                        let e = d.vals[i].clone();
                        check(it, &e, &s_any, &p, errs, pos, depth + 1)?;
                        if errs.len() > 50 {
                            return Ok(());
                        }
                    }
                }
            }
            Ok(())
        }
        _ => ngr(format!("✓: схема — рядок-тип, 【S】 або 『поле S …』, а не {}", kind(sch)), pos),
    }
}
