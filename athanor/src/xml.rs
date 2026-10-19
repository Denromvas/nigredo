//! XML χ ↘ — як nigredo.xml_parse / xml_write / xml_path. Розбір — та сама системна libexpat, що в pyexpat
//! (dlopen, ті самі виклики й порціювання: ті самі помилки й позиції); запис — як ElementTree.tostring.
use crate::interp::*;
use crate::lexer::Pos;
use crate::rx::Rx;
use crate::uni;
use crate::value::*;
use std::ffi::{c_char, c_int, c_long, c_void, CStr, CString};
use std::rc::Rc;

pub const XML_MAX_DEPTH: usize = 500;

extern "C" {
    fn dlopen(filename: *const c_char, flag: c_int) -> *mut c_void;
    fn dlsym(handle: *mut c_void, symbol: *const c_char) -> *mut c_void;
}

type StartH = extern "C" fn(*mut c_void, *const c_char, *mut *const c_char);
type EndH = extern "C" fn(*mut c_void, *const c_char);
type CharH = extern "C" fn(*mut c_void, *const c_char, c_int);
type DoctypeH = extern "C" fn(*mut c_void, *const c_char, *const c_char, *const c_char, c_int);
type EntityH = extern "C" fn(*mut c_void, *const c_char, c_int, *const c_char, c_int, *const c_char, *const c_char, *const c_char, *const c_char);

struct Expat {
    create: extern "C" fn(*const c_char, c_char) -> *mut c_void,
    free: extern "C" fn(*mut c_void),
    user: extern "C" fn(*mut c_void, *mut c_void),
    elem: extern "C" fn(*mut c_void, StartH, EndH),
    chars: extern "C" fn(*mut c_void, CharH),
    doctype: extern "C" fn(*mut c_void, DoctypeH),
    entity: extern "C" fn(*mut c_void, EntityH),
    encoding: extern "C" fn(*mut c_void, *const c_char) -> c_int,
    parse: extern "C" fn(*mut c_void, *const c_char, c_int, c_int) -> c_int,
    code: extern "C" fn(*mut c_void) -> c_int,
    msg: extern "C" fn(c_int) -> *const c_char,
    line: extern "C" fn(*mut c_void) -> c_long,
    col: extern "C" fn(*mut c_void) -> c_long,
    stop: extern "C" fn(*mut c_void, c_int) -> c_int,
}

fn load() -> Option<&'static Expat> {
    use std::sync::OnceLock;
    static E: OnceLock<Option<Expat>> = OnceLock::new();
    E.get_or_init(|| unsafe {
        let mut h = std::ptr::null_mut();
        for name in ["libexpat.so.1", "libexpat.so"] {
            let c = CString::new(name).unwrap();
            h = dlopen(c.as_ptr(), 2 /* RTLD_NOW */);
            if !h.is_null() {
                break;
            }
        }
        if h.is_null() {
            return None;
        }
        macro_rules! sym {
            ($n:expr) => {{
                let c = CString::new($n).unwrap();
                let p = dlsym(h, c.as_ptr());
                if p.is_null() {
                    return None;
                }
                std::mem::transmute(p)
            }};
        }
        Some(Expat {
            create: sym!("XML_ParserCreateNS"),
            free: sym!("XML_ParserFree"),
            user: sym!("XML_SetUserData"),
            elem: sym!("XML_SetElementHandler"),
            chars: sym!("XML_SetCharacterDataHandler"),
            doctype: sym!("XML_SetStartDoctypeDeclHandler"),
            entity: sym!("XML_SetEntityDeclHandler"),
            encoding: sym!("XML_SetEncoding"),
            parse: sym!("XML_Parse"),
            code: sym!("XML_GetErrorCode"),
            msg: sym!("XML_ErrorString"),
            line: sym!("XML_GetCurrentLineNumber"),
            col: sym!("XML_GetCurrentColumnNumber"),
            stop: sym!("XML_StopParser"),
        })
    })
    .as_ref()
}

/// Чи можна виконати χ сам (є libexpat).
pub fn available() -> bool {
    load().is_some()
}

struct Ctx<'a> {
    stack: Vec<(Dict, String, Vec<V>)>,
    top: Vec<V>,
    err: Option<Box<E>>,
    it: &'a mut Interp,
    pos: Pos,
    parser: *mut c_void,
    ex: &'static Expat,
}

fn local(name: &str) -> (String, Option<String>) {
    match name.rfind('}') {
        Some(i) => (name[i + 1..].to_string(), Some(name[..name.find('}').unwrap()].to_string())),
        None => (name.to_string(), None),
    }
}

unsafe fn cstr(p: *const c_char) -> String {
    CStr::from_ptr(p).to_string_lossy().into_owned()
}

extern "C" fn on_start(ud: *mut c_void, name: *const c_char, atts: *mut *const c_char) {
    let cx = unsafe { &mut *(ud as *mut Ctx) };
    if cx.err.is_some() {
        return;
    }
    let r = (|| -> R<()> {
        if cx.stack.len() >= XML_MAX_DEPTH {
            return ngr(format!("χ: вкладеність глибша за {}", XML_MAX_DEPTH), cx.pos);
        }
        cx.it.work(1, cx.pos)?;
        let (tag, ns) = local(&unsafe { cstr(name) });
        let mut attrs = Dict::new();
        let mut i = 0;
        loop {
            let k = unsafe { *atts.add(i) };
            if k.is_null() {
                break;
            }
            let v = unsafe { *atts.add(i + 1) };
            let nm = local(&unsafe { cstr(k) }).0;
            if attrs.find(&nm).is_some() {
                return ngr(
                    format!(
                        "χ: у «{}» два атрибути «{}» з різних просторів імен — назви атрибутів тут без простору, тож їх не розрізнити",
                        uni::safe(&tag),
                        uni::safe(&nm)
                    ),
                    cx.pos,
                );
            }
            attrs.set(Rc::new(PStr::new(nm)), V::str(unsafe { cstr(v) }));
            i += 2;
        }
        let mut d = Dict::new();
        d.set(Rc::new(PStr::from("тег")), V::str(tag));
        if let Some(ns) = ns {
            d.set(Rc::new(PStr::from("простір")), V::str(ns));
        }
        d.set(Rc::new(PStr::from("атрибути")), V::new(Val::Dict(Rc::new(attrs)), 1.0));
        cx.stack.push((d, String::new(), Vec::new()));
        Ok(())
    })();
    if let Err(e) = r {
        cx.err = Some(e);
        (cx.ex.stop)(cx.parser, 0);
    }
}

extern "C" fn on_end(ud: *mut c_void, _name: *const c_char) {
    let cx = unsafe { &mut *(ud as *mut Ctx) };
    if cx.err.is_some() {
        return;
    }
    let (mut d, text, kids) = cx.stack.pop().unwrap();
    d.set(Rc::new(PStr::from("текст")), V::str(uni::strip(&text).to_string()));
    d.set(Rc::new(PStr::from("діти")), V::list(kids));
    let v = V::new(Val::Dict(Rc::new(d)), 1.0);
    match cx.stack.last_mut() {
        Some(p) => p.2.push(v),
        None => cx.top.push(v),
    }
}

extern "C" fn on_chars(ud: *mut c_void, data: *const c_char, len: c_int) {
    let cx = unsafe { &mut *(ud as *mut Ctx) };
    if cx.err.is_some() {
        return;
    }
    if let Some(top) = cx.stack.last_mut() {
        let b = unsafe { std::slice::from_raw_parts(data as *const u8, len as usize) };
        top.1.push_str(&String::from_utf8_lossy(b));
    }
}

fn forbid(cx: &mut Ctx) {
    if cx.err.is_none() {
        cx.err = ngr::<()>("χ: DTD і сутності (<!DOCTYPE, <!ENTITY) заборонено — небезпечні (XXE, «мільярд сміхів»)", cx.pos).err();
        (cx.ex.stop)(cx.parser, 0);
    }
}

extern "C" fn on_doctype(ud: *mut c_void, _a: *const c_char, _b: *const c_char, _c: *const c_char, _d: c_int) {
    forbid(unsafe { &mut *(ud as *mut Ctx) });
}

extern "C" fn on_entity(ud: *mut c_void, _a: *const c_char, _b: c_int, _c: *const c_char, _d: c_int, _e: *const c_char,
                        _f: *const c_char, _g: *const c_char, _h: *const c_char) {
    forbid(unsafe { &mut *(ud as *mut Ctx) });
}

pub fn parse(it: &mut Interp, text: &str, pos: Pos) -> R<V> {
    let ex = load().expect("libexpat");
    it.work(text.chars().count() as u64, pos)?;
    let text = text.strip_prefix('\u{feff}').unwrap_or(text);
    let p = (ex.create)(std::ptr::null(), b'}' as c_char);
    let max = it.max_size;
    let mut cx = Ctx { stack: Vec::new(), top: Vec::new(), err: None, it, pos, parser: p, ex };
    (ex.user)(p, &mut cx as *mut Ctx as *mut c_void);
    (ex.doctype)(p, on_doctype);
    (ex.entity)(p, on_entity);
    (ex.elem)(p, on_start, on_end);
    (ex.chars)(p, on_chars);
    let enc = CString::new("utf-8").unwrap();
    (ex.encoding)(p, enc.as_ptr());
    let mut s = text.as_bytes();
    const CHUNK: usize = 1 << 20;
    let mut rc = 1;
    while s.len() > CHUNK {
        rc = (ex.parse)(p, s.as_ptr() as *const c_char, CHUNK as c_int, 0);
        if rc == 0 {
            break;
        }
        s = &s[CHUNK..];
    }
    if rc != 0 {
        rc = (ex.parse)(p, s.as_ptr() as *const c_char, s.len() as c_int, 1);
    }
    let result = if let Some(e) = cx.err.take() {
        Err(e)
    } else if rc == 0 {
        let code = (ex.code)(p);
        let msg = unsafe { cstr((ex.msg)(code)) };
        let (l, c) = ((ex.line)(p), (ex.col)(p));
        ngr(format!("χ: не XML ({}: рядок {}, стовпець {})", msg, l, c), pos)
    } else if cx.top.len() != 1 {
        ngr("χ: не XML (немає кореневого елемента)", pos)
    } else {
        let res = cx.top.pop().unwrap();
        if res.n > max {
            ngr(format!("χ: документ завеликий (понад --розмір {})", max), pos)
        } else {
            Ok(res)
        }
    };
    (ex.free)(p);
    result
}

// ---------------------------------------------------------------- запис

fn name_ok(name: &str) -> bool {
    let mut cs = name.chars();
    let first = match cs.next() {
        None => return false,
        Some(c) => c,
    };
    if name.contains(':') || !(uni::is_letter(first) || first == '_') {
        return false;
    }
    if !cs.all(|c| uni::isalnum(c) || "-._".contains(c) || matches!(uni::category(c), "Mn" | "Mc")) {
        return false;
    }
    // і таку, яку прийме сам розбирач χ
    let ex = match load() {
        Some(e) => e,
        None => return false,
    };
    let doc = format!("<{} {}=\"1\"/>", name, name);
    let p = (ex.create)(std::ptr::null(), b'}' as c_char);
    let enc = CString::new("utf-8").unwrap();
    (ex.encoding)(p, enc.as_ptr());
    let rc = (ex.parse)(p, doc.as_ptr() as *const c_char, doc.len() as c_int, 1);
    (ex.free)(p);
    rc != 0
}

fn char_bad(s: &str) -> Option<char> {
    s.chars().find(|&c| {
        let o = c as u32;
        (o < 0x20 && !"\t\n\r".contains(c)) || (0xD800..=0xDFFF).contains(&o) || o == 0xFFFE || o == 0xFFFF
    })
}

fn esc_cdata(s: &str, out: &mut String) {
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            c => out.push(c),
        }
    }
}

fn esc_attr(s: &str, out: &mut String) {
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\r' => out.push_str("&#13;"),
            '\n' => out.push_str("&#10;"),
            '\t' => out.push_str("&#09;"),
            c => out.push(c),
        }
    }
}

fn dget<'a>(d: &'a Dict, k: &str) -> Option<&'a V> {
    d.get(k)
}

pub fn write(it: &mut Interp, el: &V, pos: Pos) -> R<String> {
    let mut out = String::new();
    build(it, el, 1, None, pos, &mut out)?;
    Ok(out.replace('\u{ffff}', "&#13;"))
}

fn value(v: &V, what: &str, tag: &str, pos: Pos) -> R<String> {
    let s = show(v, true);
    if let Some(b) = char_bad(&s) {
        return ngr(format!("χ: {} елемента «{}» має символ U+{:04X}, якого не буває в XML", what, uni::safe(tag), b as u32), pos);
    }
    Ok(s)
}

fn build(it: &mut Interp, x: &V, depth: usize, parent_ns: Option<String>, pos: Pos, out: &mut String) -> R<()> {
    if depth > XML_MAX_DEPTH {
        return ngr(format!("χ: вкладеність глибша за {}", XML_MAX_DEPTH), pos);
    }
    it.step_pub(pos)?;
    let d = match &x.v {
        Val::Dict(d) if matches!(d.get("тег").map(|t| &t.v), Some(Val::Str(_))) => d.clone(),
        _ => return ngr("χ: елемент — словник із 「тег」 (рядок) і, за бажанням, 「атрибути」 「текст」 「діти」", pos),
    };
    let tag = match &d.get("тег").unwrap().v {
        Val::Str(s) => s.s.to_string(),
        _ => unreachable!(),
    };
    if !name_ok(&tag) {
        return ngr(
            format!("χ: «{}» — не назва тегу XML (літера чи _, далі літери, цифри, - . _; без префікса — простір ключем 「простір」)", uni::safe(&tag)),
            pos,
        );
    }
    let mut extra: Vec<&str> = d.keys.iter().map(|k| &*k.s).filter(|k| !["тег", "атрибути", "текст", "діти", "простір"].contains(k)).collect();
    extra.sort();
    extra.dedup();
    if !extra.is_empty() {
        let ks: Vec<String> = extra.iter().take(5).map(|k| uni::safe(k)).collect();
        return ngr(
            format!("χ: у елемента «{}» невідомі ключі {} (є: 「тег」 「атрибути」 「текст」 「діти」 「простір」)", uni::safe(&tag), ks.join(", ")),
            pos,
        );
    }
    let empty = Rc::new(Dict::new());
    let attrs = match dget(&d, "атрибути").map(|a| &a.v) {
        None => empty,
        Some(Val::Dict(a)) => a.clone(),
        Some(_) => return ngr(format!("χ: 「атрибути」 елемента «{}» — словник", uni::safe(&tag)), pos),
    };
    for k in &attrs.keys {
        if !name_ok(&k.s) || &*k.s == "xmlns" || k.s.starts_with("xmlns:") {
            return ngr(format!("χ: «{}» — не назва атрибута XML (у «{}»; простір — ключем 「простір」)", uni::safe(&k.s), uni::safe(&tag)), pos);
        }
    }
    let mut avals: Vec<(String, String)> = Vec::new();
    for (k, v) in attrs.keys.iter().zip(&attrs.vals) {
        avals.push((k.s.to_string(), value(v, &format!("атрибут «{}»", uni::safe(&k.s)), &tag, pos)?));
    }
    let ns = match dget(&d, "простір").map(|v| &v.v) {
        Some(Val::Str(s)) => Some(s.s.to_string()),
        _ => None,
    };
    if let Some(n) = &ns {
        if Some(n) != parent_ns.as_ref() {
            let v = value(&V::str(n.clone()), "простір", &tag, pos)?;
            match avals.iter_mut().find(|(k, _)| k == "xmlns") {
                Some(a) => a.1 = v,
                None => avals.push(("xmlns".into(), v)),
            }
        }
    }
    let text = match dget(&d, "текст") {
        None => None,
        Some(t) => match &t.v {
            Val::None => None,
            Val::Str(s) if s.s.is_empty() => None,
            _ => Some(value(t, "текст", &tag, pos)?.replace('\r', "\u{ffff}")),
        },
    };
    let kids = match dget(&d, "діти").map(|v| &v.v) {
        None => Rc::new(Vec::new()),
        Some(Val::List(l)) => l.clone(),
        Some(_) => return ngr(format!("χ: 「діти」 елемента «{}» — список", uni::safe(&tag)), pos),
    };
    out.push('<');
    out.push_str(&tag);
    for (k, v) in &avals {
        out.push(' ');
        out.push_str(k);
        out.push_str("=\"");
        esc_attr(v, out);
        out.push('"');
    }
    if text.as_deref().map_or(false, |t| !t.is_empty()) || !kids.is_empty() {
        out.push('>');
        if let Some(t) = &text {
            esc_cdata(t, out);
        }
        let pns = if ns.is_some() { ns.clone() } else { parent_ns };
        for k in kids.iter() {
            build(it, k, depth + 1, pns.clone(), pos, out)?;
        }
        out.push_str("</");
        out.push_str(&tag);
        out.push('>');
    } else {
        out.push_str(" />");
    }
    Ok(())
}

// ---------------------------------------------------------------- ↘ (XPath-підмножина)

const XPATH_HELP: &str = "є: a/b, //b, *, [n], [@атр='x'], [дитина='x'], …/@атр, //@атр, /a… від самого елемента; текст — §e 「текст」, батька й text() немає";
const NAME_RE: &str = r"(?:\*|[^\W\d][\w.\-]*(?::[^\W\d][\w.\-]*)?)";
const COND_RE: &str = r#"\[\s*(?:[0-9]+|@?[^\W\d][\w.\-]*(?::[^\W\d][\w.\-]*)?\s*=\s*(?:'[^']*'|"[^"]*"))\s*\]"#;

fn noop(_: i64) -> Result<(), String> {
    Ok(())
}

/// Збіг на всьому рядку: групи (None — група не брала участі) або None.
fn fullmatch(pat: &str, s: &str) -> Option<Vec<Option<String>>> {
    let r = Rx::new(&format!(r"\A(?:{})\Z", pat)).ok().expect("шаблон ↘");
    let t: Vec<char> = s.chars().collect();
    let m = r.search(&t, 0, &mut noop, None).ok()??;
    Some(r.groups(&t, &m))
}

fn rx_match(pat: &str, s: &str) -> Option<String> {
    let r = Rx::new(&format!(r"\A(?:{})", pat)).ok().expect("шаблон ↘");
    let t: Vec<char> = s.chars().collect();
    let m = r.search(&t, 0, &mut noop, None).ok()??;
    r.groups(&t, &m)[0].clone()
}

fn findall(pat: &str, s: &str) -> Vec<Vec<String>> {
    let r = Rx::new(pat).ok().expect("шаблон ↘");
    let t: Vec<char> = s.chars().collect();
    let mut out = Vec::new();
    let _ = r.finditer(&t, &mut noop, &mut |m| {
        let gs = r.groups(&t, m);
        out.push(gs.into_iter().map(|g| g.unwrap_or_default()).collect());
        Ok(())
    });
    out
}

fn strip_quoted(s: &str) -> String {
    let r = Rx::new(r#"'[^']*'|"[^"]*""#).ok().unwrap();
    let t: Vec<char> = s.chars().collect();
    let mut out = String::new();
    let mut last = 0;
    let _ = r.finditer(&t, &mut noop, &mut |m| {
        out.extend(t[last..m[0].unwrap()].iter());
        last = m[1].unwrap();
        Ok(())
    });
    out.extend(t[last..].iter());
    out
}

type Node = (Vec<usize>, V);

pub fn path(it: &mut Interp, root: &V, path: &str, pos: Pos) -> R<V> {
    if path.is_empty() {
        return ngr("↘: порожній шлях", pos);
    }
    let bad = |what: String| -> R<V> { ngr(format!("↘: {} — поза підмножиною XPath ({})", what, XPATH_HELP), pos) };
    let tok = fullmatch(
        &format!(r"((?:/|//)?)((?:{n}(?:{c})*)(?:(?:/|//){n}(?:{c})*)*)?(?:(^|/|//)@({n}))?", n = NAME_RE, c = COND_RE),
        path,
    );
    let only = fullmatch(&format!(r"(//|/)?@({})", NAME_RE), path);
    let (lead, body, attr_sep, attr): (String, String, Option<String>, Option<String>) = if let Some(o) = only {
        (String::new(), String::new(), Some(o[1].clone().unwrap_or_default()), o[2].clone())
    } else {
        match tok {
            Some(t) if !(t[2].is_none() && t[4].is_none()) => {
                (t[1].clone().unwrap_or_default(), t[2].clone().unwrap_or_default(), t[3].clone(), t[4].clone())
            }
            _ => return bad(format!("шлях «{}»", uni::safe(path))),
        }
    };
    if attr.as_deref() == Some("*") {
        return bad("@*".into());
    }
    if strip_quoted(path).contains(':') {
        return bad("префікс простору імен (a:b) — тут назви без простору; простір вузла — §e 「простір」".into());
    }
    let mut steps: Vec<(bool, String, Vec<String>)> = Vec::new();
    for g in findall(&format!(r"(^|/|//)({}(?:{})*)", NAME_RE, COND_RE), &body) {
        let (sep, step) = (&g[1], &g[2]);
        let nm = rx_match(NAME_RE, step).unwrap_or_default();
        let rest: String = step.chars().skip(nm.chars().count()).collect();
        let conds: Vec<String> = findall(COND_RE, &rest)
            .into_iter()
            .map(|g| {
                let c: Vec<char> = g[0].chars().collect();
                c[1..c.len() - 1].iter().collect()
            })
            .collect();
        steps.push((sep == "//", nm.rsplit(':').next().unwrap().to_string(), conds));
    }
    let absolute = lead == "/";
    if lead == "//" && !steps.is_empty() {
        steps[0].0 = true;
    }
    let check = |it: &mut Interp, e: &V| -> R<V> {
        it.step_pub(pos)?;
        let d = match &e.v {
            Val::Dict(d) if matches!(d.get("тег").map(|t| &t.v), Some(Val::Str(_))) => d,
            _ => return ngr("↘: вузол — не елемент (словник із 「тег」 — рядок)", pos),
        };
        for (key, tn) in [("атрибути", "словник"), ("діти", "список"), ("текст", "рядок")] {
            if let Some(v) = d.get(key) {
                let ok = match key {
                    "атрибути" => matches!(v.v, Val::Dict(_)),
                    "діти" => matches!(v.v, Val::List(_)),
                    _ => matches!(v.v, Val::Str(_)),
                };
                if !ok {
                    let tag = match &d.get("тег").unwrap().v {
                        Val::Str(s) => uni::safe(&s.s),
                        _ => String::new(),
                    };
                    return ngr(format!("↘: 「{}」 елемента «{}» — {}", key, tag, tn), pos);
                }
            }
        }
        Ok(e.clone())
    };
    fn dict(e: &V) -> &Dict {
        match &e.v {
            Val::Dict(d) => d,
            _ => unreachable!(),
        }
    }
    let kids = |it: &mut Interp, e: &V| -> R<Vec<V>> {
        match dict(e).get("діти") {
            Some(k) => match &k.v {
                Val::List(l) => {
                    let mut out = Vec::with_capacity(l.len());
                    for x in l.iter() {
                        out.push(check(it, x)?);
                    }
                    Ok(out)
                }
                _ => Ok(Vec::new()),
            },
            None => Ok(Vec::new()),
        }
    };
    let tag_of = |e: &V| -> String {
        match &dict(e).get("тег").unwrap().v {
            Val::Str(s) => s.s.to_string(),
            _ => String::new(),
        }
    };
    let text_of = |e: &V| -> String {
        match dict(e).get("текст").map(|t| &t.v) {
            Some(Val::Str(s)) => s.s.to_string(),
            _ => String::new(),
        }
    };
    let attr_get = |e: &V, name: &str| -> Option<V> {
        match dict(e).get("атрибути").map(|a| &a.v) {
            Some(Val::Dict(a)) => a.get(name).cloned(),
            _ => None,
        }
    };
    let below = |it: &mut Interp, n: &Node| -> R<Vec<Node>> {
        let ks = kids(it, &n.1)?;
        Ok(ks.into_iter().enumerate().map(|(i, k)| {
            let mut p = n.0.clone();
            p.push(i);
            (p, k)
        }).collect())
    };
    let self_or_below = |it: &mut Interp, nodes: &[Node]| -> R<Vec<Node>> {
        let mut seen: std::collections::HashSet<Vec<usize>> = std::collections::HashSet::new();
        let mut out = Vec::new();
        let mut stack: Vec<Node> = nodes.iter().rev().cloned().collect();
        while let Some(n) = stack.pop() {
            if seen.contains(&n.0) {
                continue;
            }
            seen.insert(n.0.clone());
            out.push(n.clone());
            let b = below(it, &n)?;
            stack.extend(b.into_iter().rev());
        }
        Ok(out)
    };
    let ok = |it: &mut Interp, e: &V, cond: &str, idx: usize| -> R<bool> {
        let cond = uni::strip(cond);
        if !cond.is_empty() && cond.bytes().all(|b| b.is_ascii_digit()) {
            return Ok(cond.trim_start_matches('0').parse::<usize>().unwrap_or(if cond.trim_start_matches('0').is_empty() { 0 } else { usize::MAX }) == idx);
        }
        let mm = fullmatch(r#"(@?)([^=\s]+)\s*=\s*(?:'([^']*)'|"([^"]*)")"#, cond).unwrap();
        let want = mm[3].clone().or_else(|| mm[4].clone()).unwrap_or_default();
        let name = mm[2].clone().unwrap_or_default();
        let name = name.rsplit(':').next().unwrap().to_string();
        if mm[1].as_deref() == Some("@") {
            return Ok(match attr_get(e, &name) {
                Some(v) => (match &v.v {
                    Val::Str(s) => s.s.to_string(),
                    _ => show(&v, true),
                }) == want,
                None => false,
            });
        }
        for k in kids(it, e)? {
            if tag_of(&k) == name && text_of(&k) == want {
                return Ok(true);
            }
        }
        Ok(false)
    };
    let root_c = check(it, root)?;
    let mut doc_d = Dict::new();
    doc_d.set(Rc::new(PStr::from("тег")), V::str(String::new()));
    doc_d.set(Rc::new(PStr::from("діти")), V::list(vec![root_c]));
    let doc: Node = (Vec::new(), V::new(Val::Dict(Rc::new(doc_d)), 1.0));
    let mut cur: Vec<Node> = if absolute || lead == "//" || (steps.is_empty() && attr_sep.as_deref() == Some("//")) {
        vec![doc]
    } else {
        vec![(vec![0], root.clone())]
    };
    for (anywhere, name, conds) in &steps {
        let parents = if *anywhere { self_or_below(it, &cur)? } else { cur.clone() };
        let mut nxt: Vec<Node> = Vec::new();
        for p in &parents {
            let mut sel: Vec<Node> = below(it, p)?.into_iter().filter(|k| name == "*" || tag_of(&k.1) == *name).collect();
            for c in conds {
                let mut keep = Vec::new();
                for (i, k) in sel.into_iter().enumerate() {
                    if ok(it, &k.1, c, i + 1)? {
                        keep.push(k);
                    }
                }
                sel = keep;
            }
            nxt.extend(sel);
        }
        // uniq: один вузол на позицію (останній), у порядку позицій
        let mut m: Vec<Node> = Vec::new();
        for n in nxt {
            match m.iter_mut().find(|x| x.0 == n.0) {
                Some(x) => *x = n,
                None => m.push(n),
            }
        }
        m.sort_by(|a, b| a.0.cmp(&b.0));
        cur = m;
    }
    if let Some(a) = attr {
        if attr_sep.as_deref() == Some("//") {
            cur = self_or_below(it, &cur)?;
        }
        let name = a.rsplit(':').next().unwrap().to_string();
        return Ok(V::list(cur.iter().filter_map(|(_, e)| attr_get(e, &name)).collect()));
    }
    Ok(V::list(cur.into_iter().map(|(_, e)| e).collect()))
}
