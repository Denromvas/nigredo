//! SQLite (бд.читати, бд.писати) — як nigredo._db: та сама системна libsqlite3, що в модулі sqlite3 Python (dlopen),
//! і ті самі кроки модуля _sqlite CPython 3.13: створення запиту (null, довжина, «одна інструкція»), прив'язка
//! параметрів, step/fetch у тому самому порядку, помилки — sqlite3_errmsg (NOMEM — MemoryError).
use crate::int::Int;
use crate::interp::*;
use crate::json::J;
use crate::lexer::Pos;
use crate::pathx;
use crate::rx::Rx;
use crate::uni;
use crate::value::*;
use std::ffi::{c_char, c_double, c_int, c_void, CStr, CString};
use std::rc::Rc;

extern "C" {
    fn dlopen(filename: *const c_char, flag: c_int) -> *mut c_void;
    fn dlsym(handle: *mut c_void, symbol: *const c_char) -> *mut c_void;
}

type AuthCb = extern "C" fn(*mut c_void, c_int, *const c_char, *const c_char, *const c_char, *const c_char) -> c_int;
type ProgCb = extern "C" fn(*mut c_void) -> c_int;

struct Lib {
    open_v2: extern "C" fn(*const c_char, *mut *mut c_void, c_int, *const c_char) -> c_int,
    close_v2: extern "C" fn(*mut c_void) -> c_int,
    busy_timeout: extern "C" fn(*mut c_void, c_int) -> c_int,
    limit: extern "C" fn(*mut c_void, c_int, c_int) -> c_int,
    prepare_v2: extern "C" fn(*mut c_void, *const c_char, c_int, *mut *mut c_void, *mut *const c_char) -> c_int,
    bind_int64: extern "C" fn(*mut c_void, c_int, i64) -> c_int,
    bind_text: extern "C" fn(*mut c_void, c_int, *const c_char, c_int, isize) -> c_int,
    bind_null: extern "C" fn(*mut c_void, c_int) -> c_int,
    bind_count: extern "C" fn(*mut c_void) -> c_int,
    step: extern "C" fn(*mut c_void) -> c_int,
    finalize: extern "C" fn(*mut c_void) -> c_int,
    column_count: extern "C" fn(*mut c_void) -> c_int,
    data_count: extern "C" fn(*mut c_void) -> c_int,
    column_name: extern "C" fn(*mut c_void, c_int) -> *const c_char,
    column_type: extern "C" fn(*mut c_void, c_int) -> c_int,
    column_int64: extern "C" fn(*mut c_void, c_int) -> i64,
    column_double: extern "C" fn(*mut c_void, c_int) -> c_double,
    column_text: extern "C" fn(*mut c_void, c_int) -> *const u8,
    column_bytes: extern "C" fn(*mut c_void, c_int) -> c_int,
    errmsg: extern "C" fn(*mut c_void) -> *const c_char,
    errcode: extern "C" fn(*mut c_void) -> c_int,
    errstr: extern "C" fn(c_int) -> *const c_char,
    set_authorizer: extern "C" fn(*mut c_void, Option<AuthCb>, *mut c_void) -> c_int,
    progress: extern "C" fn(*mut c_void, c_int, Option<ProgCb>, *mut c_void),
    total_changes: extern "C" fn(*mut c_void) -> i64,
}

fn load() -> Option<&'static Lib> {
    use std::sync::OnceLock;
    static L: OnceLock<Option<Lib>> = OnceLock::new();
    L.get_or_init(|| unsafe {
        let mut h = std::ptr::null_mut();
        for name in ["libsqlite3.so.0", "libsqlite3.so"] {
            let c = CString::new(name).unwrap();
            h = dlopen(c.as_ptr(), 2);
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
        Some(Lib {
            open_v2: sym!("sqlite3_open_v2"),
            close_v2: sym!("sqlite3_close_v2"),
            busy_timeout: sym!("sqlite3_busy_timeout"),
            limit: sym!("sqlite3_limit"),
            prepare_v2: sym!("sqlite3_prepare_v2"),
            bind_int64: sym!("sqlite3_bind_int64"),
            bind_text: sym!("sqlite3_bind_text"),
            bind_null: sym!("sqlite3_bind_null"),
            bind_count: sym!("sqlite3_bind_parameter_count"),
            step: sym!("sqlite3_step"),
            finalize: sym!("sqlite3_finalize"),
            column_count: sym!("sqlite3_column_count"),
            data_count: sym!("sqlite3_data_count"),
            column_name: sym!("sqlite3_column_name"),
            column_type: sym!("sqlite3_column_type"),
            column_int64: sym!("sqlite3_column_int64"),
            column_double: sym!("sqlite3_column_double"),
            column_text: sym!("sqlite3_column_text"),
            column_bytes: sym!("sqlite3_column_bytes"),
            errmsg: sym!("sqlite3_errmsg"),
            errcode: sym!("sqlite3_errcode"),
            errstr: sym!("sqlite3_errstr"),
            set_authorizer: sym!("sqlite3_set_authorizer"),
            progress: sym!("sqlite3_progress_handler"),
            total_changes: sym!("sqlite3_total_changes64"),
        })
    })
    .as_ref()
}

pub fn available() -> bool {
    load().is_some()
}

const SQLITE_ROW: c_int = 100;
const SQLITE_DONE: c_int = 101;
const SQLITE_NOMEM: c_int = 7;
const SQLITE_MISUSE: c_int = 21;
const OPEN_FLAGS: c_int = 0x2 | 0x4 | 0x40; // READWRITE | CREATE | URI

/// Виняток Python з модуля sqlite3 (чи інший), як його бачить nigredo._db.
enum PyErr {
    Sql(String),      // sqlite3.Error (і ProgrammingError, DataError) — текст
    Memory,           // MemoryError
    Other(String),    // інший виняток (OverflowError…) — у еталоні вада, код 4
}

unsafe fn cs(p: *const c_char) -> String {
    if p.is_null() {
        return String::new();
    }
    CStr::from_ptr(p).to_string_lossy().into_owned()
}

fn db_err(l: &Lib, db: *mut c_void) -> PyErr {
    let code = (l.errcode)(db);
    if code == SQLITE_NOMEM {
        return PyErr::Memory;
    }
    let m = unsafe { if code == SQLITE_MISUSE { cs((l.errstr)(code)) } else { cs((l.errmsg)(db)) } };
    PyErr::Sql(m)
}

/// lstrip_sql (_sqlite/statement.c): чи лишилось у хвості щось, крім пробілів і коментарів.
fn rest_has_sql(b: &[u8]) -> bool {
    let mut i = 0;
    while i < b.len() && b[i] != 0 {
        match b[i] {
            b' ' | b'\t' | 0x0c | b'\n' | b'\r' => i += 1,
            b'-' if b.get(i + 1) == Some(&b'-') => {
                i += 2;
                while i < b.len() && b[i] != 0 && b[i] != b'\n' {
                    i += 1;
                }
                if i >= b.len() || b[i] == 0 {
                    return false;
                }
            }
            b'/' if b.get(i + 1) == Some(&b'*') => {
                i += 2;
                while i < b.len() && b[i] != 0 && !(b[i] == b'*' && b.get(i + 1) == Some(&b'/')) {
                    i += 1;
                }
                if i >= b.len() || b[i] == 0 {
                    return false;
                }
                i += 2;
            }
            _ => return true,
        }
    }
    false
}

pub enum Arg {
    Int(Int),
    Text(String),
    Null,
}

struct Stmt {
    st: *mut c_void,
    rc: c_int,
    cols: Vec<String>,
}

/// con.execute(sql, args): підготувати, прив'язати, перший крок.
fn execute(l: &Lib, db: *mut c_void, sql: &str, args: &[Arg]) -> Result<Stmt, PyErr> {
    let max_len = (l.limit)(db, 1 /* SQL_LENGTH */, -1);
    if sql.len() as i64 > max_len as i64 {
        return Err(PyErr::Sql("query string is too large".into()));
    }
    if sql.contains('\0') {
        return Err(PyErr::Sql("the query contains a null character".into()));
    }
    let c = CString::new(sql).unwrap();
    let mut st: *mut c_void = std::ptr::null_mut();
    let mut tail: *const c_char = std::ptr::null();
    let rc = (l.prepare_v2)(db, c.as_ptr(), sql.len() as c_int + 1, &mut st, &mut tail);
    if rc != 0 {
        return Err(db_err(l, db));
    }
    let off = if tail.is_null() { sql.len() } else { (tail as usize) - (c.as_ptr() as usize) };
    if rest_has_sql(&sql.as_bytes()[off.min(sql.len())..]) {
        (l.finalize)(st);
        return Err(PyErr::Sql("You can only execute one statement at a time.".into()));
    }
    if st.is_null() {
        return Ok(Stmt { st, rc: SQLITE_DONE, cols: Vec::new() });
    }
    let need = (l.bind_count)(st) as usize;
    if need != args.len() {
        (l.finalize)(st);
        return Err(PyErr::Sql(format!(
            "Incorrect number of bindings supplied. The current statement uses {}, and there are {} supplied.",
            need,
            args.len()
        )));
    }
    for (i, a) in args.iter().enumerate() {
        let pos = i as c_int + 1;
        match a {
            Arg::Int(n) => match n.to_i64() {
                Some(v) => {
                    (l.bind_int64)(st, pos, v);
                }
                None => {
                    (l.finalize)(st);
                    return Err(PyErr::Other("OverflowError: Python int too large to convert to SQLite INTEGER".into()));
                }
            },
            Arg::Text(s) => {
                (l.bind_text)(st, pos, s.as_ptr() as *const c_char, s.len() as c_int, -1);
            }
            Arg::Null => {
                (l.bind_null)(st, pos);
            }
        }
    }
    let rc = (l.step)(st);
    if rc != SQLITE_DONE && rc != SQLITE_ROW {
        let e = db_err(l, db);
        (l.finalize)(st);
        return Err(e);
    }
    let n = (l.column_count)(st);
    let mut cols = Vec::new();
    for i in 0..n {
        cols.push(unsafe { cs((l.column_name)(st, i)) });
    }
    Ok(Stmt { st, rc, cols })
}

enum Cell {
    Null,
    Int(i64),
    Float(f64),
    Text(String),
    Blob,
}

/// _pysqlite_fetch_one_row: поточний рядок.
fn fetch_row(l: &Lib, st: *mut c_void) -> Result<Vec<Cell>, PyErr> {
    let n = (l.data_count)(st);
    let mut out = Vec::with_capacity(n as usize);
    for i in 0..n {
        let t = (l.column_type)(st, i);
        out.push(match t {
            5 => Cell::Null,
            1 => Cell::Int((l.column_int64)(st, i)),
            2 => Cell::Float((l.column_double)(st, i)),
            3 => {
                let p = (l.column_text)(st, i);
                let nb = (l.column_bytes)(st, i) as usize;
                let b = if p.is_null() { &[][..] } else { unsafe { std::slice::from_raw_parts(p, nb) } };
                match std::str::from_utf8(b) {
                    Ok(s) => Cell::Text(s.to_string()),
                    Err(_) => {
                        // «Could not decode…» — буфер 200 байтів, ASCII з заміною
                        let name = unsafe { CStr::from_ptr((l.column_name)(st, i)).to_bytes().to_vec() };
                        let upto = b.iter().position(|&x| x == 0).unwrap_or(b.len());
                        let mut msg = b"Could not decode to UTF-8 column '".to_vec();
                        msg.extend_from_slice(&name);
                        msg.extend_from_slice(b"' with text '");
                        msg.extend_from_slice(&b[..upto]);
                        msg.push(b'\'');
                        msg.truncate(198);
                        let s: String = msg.iter().map(|&c| if c < 0x80 { c as char } else { '\u{FFFD}' }).collect();
                        return Err(PyErr::Sql(s));
                    }
                }
            }
            _ => Cell::Blob,
        });
    }
    Ok(out)
}

struct AuthCtx {
    write: bool,
    clock_ok: bool, // годинник SQLite — лише з правом «час»
    rand_ok: bool,  // random()/randomblob() — лише з «жереб» без квоти (суд 9)
    why: Vec<String>,
}

const DB_CLOCK: [&str; 10] =
    ["date", "time", "datetime", "julianday", "unixepoch", "strftime", "timediff", "current_date", "current_time", "current_timestamp"];

fn auth_ctx(it: &Interp, write: bool) -> AuthCtx {
    let rand_ok = it.caps.has("жереб") && !it.quota_stack.iter().any(|q| q.quotas.iter().any(|((t, _), _)| t == "жереб"));
    AuthCtx { write, clock_ok: it.caps.has("час"), rand_ok, why: Vec::new() }
}

const INFO_PRAGMAS: [&str; 7] = ["table_info", "table_xinfo", "table_list", "index_list", "index_info", "index_xinfo", "foreign_key_list"];

fn action_name(a: c_int) -> String {
    let names: [(&str, c_int); 26] = [
        ("PRAGMA", 19), ("ATTACH", 24), ("DETACH", 25), ("TRANSACTION", 22), ("SAVEPOINT", 32), ("INSERT", 18),
        ("UPDATE", 23), ("DELETE", 9), ("CREATE_TABLE", 2), ("DROP_TABLE", 11), ("ALTER_TABLE", 26), ("CREATE_INDEX", 1),
        ("DROP_INDEX", 10), ("CREATE_TRIGGER", 7), ("DROP_TRIGGER", 16), ("CREATE_VIEW", 8), ("DROP_VIEW", 17),
        ("CREATE_VTABLE", 29), ("DROP_VTABLE", 30), ("ANALYZE", 28), ("REINDEX", 27), ("CREATE_TEMP_TABLE", 4),
        ("CREATE_TEMP_TRIGGER", 5), ("CREATE_TEMP_VIEW", 6), ("CREATE_TEMP_INDEX", 3), ("FUNCTION", 31),
    ];
    match names.iter().find(|x| x.1 == a) {
        Some((n, _)) => n.to_string(),
        None => format!("дія SQLite {}", a),
    }
}

extern "C" fn on_auth(ud: *mut c_void, action: c_int, a1: *const c_char, a2: *const c_char, _db: *const c_char,
                      view: *const c_char) -> c_int {
    let cx = unsafe { &mut *(ud as *mut AuthCtx) };
    let s = |p: *const c_char| -> Option<String> { if p.is_null() { None } else { Some(unsafe { cs(p) }) } };
    let (a1, a2, view) = (s(a1), s(a2), s(view));
    let f = uni::lower(a2.as_deref().unwrap_or(""));
    if action == 31 && f == "load_extension" {
        cx.why.push(format!("load_extension{}", view.map(|v| format!(" у тригері чи VIEW «{}»", v)).unwrap_or_default()));
        return 1;
    }
    if action == 31 && DB_CLOCK.contains(&f.as_str()) && !cx.clock_ok {
        cx.why.push(format!("годинник SQLite ({}) без права «час» — дати рахуйте в Nigredo (◷) чи дайте «час» у печатці", f));
        return 1;
    }
    if action == 31 && (f == "random" || f == "randomblob") && !cx.rand_ok {
        cx.why.push(format!("випадковість SQLite ({}) без права «жереб» (з квотою «жереб≤N» — лише 🜔жереб)", f));
        return 1;
    }
    let read = [20, 21, 31, 33];
    let write = [18, 23, 9, 2, 11, 26, 1, 10, 27, 8, 17, 7, 16];
    let ok = read.contains(&action) || (cx.write && write.contains(&action))
        || (action == 19 && INFO_PRAGMAS.contains(&uni::lower(a1.as_deref().unwrap_or("")).as_str()));
    if ok {
        return 0;
    }
    cx.why.push(action_name(action));
    1
}

struct ProgCtx {
    it: *mut Interp,
    deadline: std::time::Instant,
}

extern "C" fn on_progress(ud: *mut c_void) -> c_int {
    let cx = unsafe { &mut *(ud as *mut ProgCtx) };
    let it = unsafe { &mut *cx.it };
    // ~1000 інструкцій SQLite ≈ 10 кроків — детерміновано, як в еталона поза ‖ (‖ Атанор віддає еталону; суд 9)
    it.steps_left -= 10;
    (it.steps_left < 0 || std::time::Instant::now() > cx.deadline) as c_int
}

/// urllib.request.pathname2url (quote, безпечне «/»).
fn quote(p: &str) -> String {
    let mut out = String::new();
    for &b in p.as_bytes() {
        if b.is_ascii_alphanumeric() || b"_.-~/".contains(&b) {
            out.push(b as char);
        } else {
            out.push_str(&format!("%{:02X}", b));
        }
    }
    out
}

fn noop(_: i64) -> Result<(), String> {
    Ok(())
}

fn re_search(pat: &str, s: &str) -> bool {
    let r = Rx::new(pat).ok().expect("шаблон бд");
    let t: Vec<char> = s.chars().collect();
    matches!(r.search(&t, 0, &mut noop, None), Ok(Some(_)))
}

fn re_sub_quoted(s: &str) -> String {
    let r = Rx::new(r"'(?:[^']|'')*'").ok().unwrap();
    let t: Vec<char> = s.chars().collect();
    let mut out = String::new();
    let mut last = 0;
    let _ = r.finditer(&t, &mut noop, &mut |m| {
        out.extend(t[last..m[0].unwrap()].iter());
        out.push_str("''");
        last = m[1].unwrap();
        Ok(())
    });
    out.extend(t[last..].iter());
    out
}

fn deny(it: &mut Interp, tool: &str, path: &str, sql: &str, why: &str) -> R<()> {
    let agent = it.agent.clone();
    let q: String = uni::safe(sql).chars().take(500).collect();
    it.deny(vec![
        ("агент".into(), J::Str(agent)),
        ("назва".into(), J::s(tool)),
        ("шлях".into(), J::Str(uni::safe(path))),
        ("запит".into(), J::Str(q)),
        ("причина".into(), J::s(why)),
    ])
}

/// _db_static_ok: load_extension, VACUUM, бд.читати — лише запити.
fn static_ok(it: &mut Interp, pos: Pos, tool: &str, path: &str, sql: &str) -> R<()> {
    if re_search(r"(?i)\bload_extension\b", &re_sub_quoted(sql)) {
        deny(it, tool, path, sql, "load_extension")?;
        return ngr(format!("{}: load_extension заборонено (і в тригерах та VIEW)", tool), pos);
    }
    let gap = r"(?:\s+|/\*.*?\*/|--[^\n]*(?:\n|$))*";
    if re_search(&format!(r"(?is)\A(?:{})vacuum\b", gap), sql) {
        deny(it, tool, path, sql, "VACUUM")?;
        return ngr(format!("{}: VACUUM заборонено (VACUUM INTO пише файл поза текою з печатки)", tool), pos);
    }
    let r = Rx::new(&format!(r"(?is)\A(?:{g}\()*{g}(\w*){g}(?:main{g}\.{g})?(\w*)", g = gap)).ok().unwrap();
    let t: Vec<char> = sql.chars().collect();
    let m = r.search(&t, 0, &mut noop, None).ok().flatten().unwrap();
    let gs = r.groups(&t, &m);
    let first = uni::lower(gs[1].as_deref().unwrap_or(""));
    let second = uni::lower(gs[2].as_deref().unwrap_or(""));
    if tool == "бд.читати" && !matches!(first.as_str(), "select" | "with" | "values")
        && !(first == "pragma" && INFO_PRAGMAS.contains(&second.as_str()))
    {
        deny(it, tool, path, sql, "не запит на читання")?;
        let f: String = uni::safe(&first).chars().take(20).collect();
        return ngr(
            format!("{}: «{}» поза дозволеним — лише SELECT (WITH, VALUES) і довідкові PRAGMA (table_info …); для змін — бд.писати", tool, f),
            pos,
        );
    }
    Ok(())
}

const SQL_ERRORS: [(&str, &str); 10] = [
    ("Incorrect number of bindings", "кількість «?» у запиті не дорівнює кількості параметрів"),
    ("no such table", "немає такої таблиці"),
    ("no such column", "немає такого стовпця"),
    ("syntax error", "синтаксична помилка SQL"),
    ("UNIQUE constraint failed", "порушено унікальність"),
    ("NOT NULL constraint failed", "порожнє значення там, де заборонено"),
    ("database is locked", "база зайнята"),
    ("database or disk is full", "база досягла межі розміру"),
    ("string or blob too big", "значення більше за --розмір"),
    ("unable to open", "не вдалося відкрити базу"),
];

fn sql_err(m: &str) -> String {
    for (en, uk) in SQL_ERRORS {
        if m.contains(en) {
            return format!("{} ({})", uk, m);
        }
    }
    m.to_string()
}

fn open(l: &Lib, uri: &str) -> Result<*mut c_void, PyErr> {
    let c = CString::new(uri).unwrap();
    let mut db: *mut c_void = std::ptr::null_mut();
    let rc = (l.open_v2)(c.as_ptr(), &mut db, OPEN_FLAGS, std::ptr::null());
    if rc != 0 {
        let e = if db.is_null() { PyErr::Memory } else { db_err(l, db) };
        if !db.is_null() {
            (l.close_v2)(db);
        }
        return Err(e);
    }
    (l.busy_timeout)(db, 5000);
    Ok(db)
}

/// Простий запит без параметрів (PRAGMA): перший рядок, перший стовпець.
fn pragma(l: &Lib, db: *mut c_void, sql: &str) -> Result<Option<i64>, PyErr> {
    let s = execute(l, db, sql, &[])?;
    let v = if s.rc == SQLITE_ROW { Some((l.column_int64)(s.st, 0)) } else { None };
    if !s.st.is_null() {
        (l.finalize)(s.st);
    }
    Ok(v)
}

pub fn run(it: &mut Interp, tool: &str, args: &[V], pos: Pos, write: bool) -> R<V> {
    let l = load().expect("libsqlite3");
    let pv = match &args[0].v {
        Val::Str(s) => s.s.to_string(),
        _ => show(&args[0], true)?,
    };
    let real = it.path_ok(tool, &args[0].v, pos, write)?;
    let sql = match &args[1].v {
        Val::Str(s) => s.s.to_string(),
        _ => return ngr(format!("{}: запит має бути рядком", tool), pos),
    };
    let params = match &args[2].v {
        Val::List(l) => l.clone(),
        _ => return ngr(format!("{}: параметри — список (для ? у запиті), а не {}", tool, kind(&args[2])), pos),
    };
    let mut bound = Vec::new();
    for x in params.iter() {
        bound.push(match &x.v {
            Val::Bool(b) => Arg::Int(Int::S(*b as i64)),
            Val::Int(i) => match i.to_i64() {
                Some(_) => Arg::Int(i.clone()), // і −2⁶³ — INTEGER (суд 9: було текстом)
                _ => Arg::Text(i.to_string()), // поза INTEGER SQLite — текстом (як у еталона)
            },
            Val::None => Arg::Null,
            Val::Str(s) => Arg::Text(s.s.to_string()),
            Val::Dec(_) | Val::Float(_) => {
                let d = to_dec(&x.v);
                let t = d.trunc();
                let lim = Int::from_dec(false, "9223372036854775808");
                let small = t.cmp(&lim) == std::cmp::Ordering::Less && t.cmp(&lim.neg()) != std::cmp::Ordering::Less;
                if d.is_integral() && small {
                    Arg::Int(t)
                } else {
                    Arg::Text(match &x.v {
                        Val::Float(f) => crate::pyf::repr(*f),
                        _ => d.to_sci(),
                    })
                }
            }
            _ => return ngr(format!("{}: параметр — рядок, число, істинність чи ∅, а не {}", tool, kind(x)), pos),
        });
    }
    static_ok(it, pos, tool, &pv, &sql)?;
    if !write && !pathx::isfile(&real) {
        return ngr(format!("{}: немає такого файлу: {}", tool, pv), pos);
    }
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(30);
    let uri = format!("file:{}?mode={}", quote(&real), if write { "rwc" } else { "ro" });
    let db = match open(l, &uri) {
        Ok(db) => db,
        Err(PyErr::Sql(m)) => return ngr(format!("{}: {}: {}", tool, m, pv), pos),
        Err(PyErr::Memory) => return internal("MemoryError"),
        Err(PyErr::Other(m)) => return internal(m),
    };
    let mut auth = auth_ctx(it, write);
    let mut prog = ProgCtx { it: it as *mut Interp, deadline };
    let result = (|| -> R<V> {
        (l.limit)(db, 7, 0);
        (l.limit)(db, 0, (4 * it.max_size).min(i32::MAX as u64) as c_int);
        let setup = (|| -> Result<(), PyErr> {
            pragma(l, db, &format!("PRAGMA hard_heap_limit = {}", (64u64 << 20).max(32 * it.max_size)))?;
            if write {
                let page = pragma(l, db, "PRAGMA page_size")?.unwrap_or(4096);
                pragma(l, db, &format!("PRAGMA max_page_count = {}", 64 * 1024 * 1024 / page))?;
            }
            Ok(())
        })();
        if let Err(e) = setup {
            return internal(match e {
                PyErr::Sql(m) => format!("OperationalError: {}", m),
                PyErr::Memory => "MemoryError".into(),
                PyErr::Other(m) => m,
            });
        }
        (l.set_authorizer)(db, Some(on_auth), &mut auth as *mut AuthCtx as *mut c_void);
        (l.progress)(db, 1000, Some(on_progress), &mut prog as *mut ProgCtx as *mut c_void);
        let before = (l.total_changes)(db);
        let r = (|| -> Result<V, Result<PyErr, Box<E>>> {
            let st = execute(l, db, &sql, &bound).map_err(Ok)?;
            let fin = |s: &Stmt| {
                if !s.st.is_null() {
                    (l.finalize)(s.st);
                }
            };
            if write {
                let mut rc = st.rc;
                while rc == SQLITE_ROW {
                    if let Err(e) = fetch_row(l, st.st) {
                        fin(&st);
                        return Err(Ok(e));
                    }
                    rc = (l.step)(st.st);
                    if rc != SQLITE_ROW && rc != SQLITE_DONE {
                        let e = db_err(l, db);
                        fin(&st);
                        return Err(Ok(e));
                    }
                }
                fin(&st);
                return Ok(V::i64((l.total_changes)(db) - before));
            }
            let mut uniq = st.cols.clone();
            uniq.sort();
            uniq.dedup();
            if uniq.len() != st.cols.len() {
                fin(&st);
                return Err(Err(ngr::<()>(format!("{}: однакові назви стовпців ({}) — дайте різні через AS", tool, st.cols.join(", ")), pos)
                    .unwrap_err()));
            }
            let keys: Vec<Rc<PStr>> = st.cols.iter().map(|c| Rc::new(PStr::from(c))).collect();
            let mut rows = Vec::new();
            let mut size = 1u64;
            let mut rc = st.rc;
            while rc == SQLITE_ROW {
                let cells = match fetch_row(l, st.st) {
                    Ok(c) => c,
                    Err(e) => {
                        fin(&st);
                        return Err(Ok(e));
                    }
                };
                rc = (l.step)(st.st);
                if rc != SQLITE_ROW && rc != SQLITE_DONE {
                    let e = db_err(l, db);
                    fin(&st);
                    return Err(Ok(e));
                }
                let mut d = Dict::new();
                for (k, c) in keys.iter().zip(cells) {
                    let v = match c {
                        Cell::Null => V::none(),
                        Cell::Int(i) => V::i64(i),
                        Cell::Text(s) => V::str(s),
                        Cell::Blob => {
                            fin(&st);
                            return Err(Err(ngr::<()>(format!("{}: стовпець «{}» — двійкові дані; візьміть hex({})", tool, k.s, k.s), pos).unwrap_err()));
                        }
                        Cell::Float(f) => {
                            if !f.is_finite() {
                                fin(&st);
                                let t = if f.is_nan() { "nan" } else if f > 0.0 { "inf" } else { "-inf" };
                                return Err(Err(ngr::<()>(format!("{}: стовпець «{}» — не число ({}); SQLite переповнився", tool, k.s, t), pos).unwrap_err()));
                            }
                            V::dec(crate::dec::Dec::parse(&crate::pyf::repr(f)).unwrap())
                        }
                    };
                    d.set(k.clone(), v);
                }
                let row = V::new(Val::Dict(Rc::new(d)), 1.0);
                size += row.n;
                rows.push(row);
                if size > it.max_size {
                    fin(&st);
                    return Err(Err(ngr::<()>(format!("{}: відповідь завелика (понад --розмір {}); додайте LIMIT", tool, it.max_size), pos).unwrap_err()));
                }
            }
            fin(&st);
            Ok(V::list(rows))
        })();
        match r {
            Ok(v) => Ok(v),
            Err(Err(e)) => Err(e),
            Err(Ok(PyErr::Memory)) => ngr(format!("{}: запит перевищив межу памʼяті SQLite — зменште вибірку (LIMIT, менші значення)", tool), pos),
            Err(Ok(PyErr::Other(m))) => internal(m),
            Err(Ok(PyErr::Sql(m))) => {
                if it.steps_left < 0 {
                    return fatal("перевищено ліміт кроків (--кроки)", Some(pos));
                }
                if std::time::Instant::now() > deadline {
                    return ngr(format!("{}: запит довший за 30 с", tool), pos);
                }
                let denied = !auth.why.is_empty() || (!write && m.contains("may not be modified"));
                if denied {
                    deny(it, tool, &pv, &sql, "дія SQLite поза дозволеним")?;
                }
                let msg = if denied {
                    if auth.why.first().map_or(false, |w| ["load_", "годинник", "випадковість"].iter().any(|p| w.starts_with(p))) {
                        format!("заборонено: {}", auth.why[0])
                    } else {
                        format!(
                            "дія поза дозволеним (лише {}; без ATTACH, VACUUM; PRAGMA — лише довідкові: table_info …)",
                            if write { "SELECT, INSERT, UPDATE, DELETE, CREATE/DROP/ALTER" } else { "SELECT" }
                        )
                    }
                } else if m.contains("one statement at a time") {
                    "лише одна інструкція SQL за раз".into()
                } else {
                    sql_err(&m)
                };
                ngr(format!("{}: {}", tool, msg), pos)
            }
        }
    })();
    (l.close_v2)(db);
    result
}

/// _db_ok (права без дії, для вичерпаної квоти): шлях і authorizer на EXPLAIN.
pub fn rights(it: &mut Interp, tool: &str, args: &[V], pos: Pos, write: bool) -> R<()> {
    let l = load().expect("libsqlite3");
    let pv = match &args[0].v {
        Val::Str(s) => s.s.to_string(),
        _ => show(&args[0], true)?,
    };
    let real = it.path_ok(tool, &args[0].v, pos, write)?;
    let sql = match &args[1].v {
        Val::Str(s) => s.s.to_string(),
        _ => return ngr(format!("{}: запит має бути рядком", tool), pos),
    };
    static_ok(it, pos, tool, &pv, &sql)?;
    let mut auth = auth_ctx(it, write);
    let uri = if pathx::isfile(&real) { format!("file:{}?mode=ro", quote(&real)) } else { ":memory:".into() };
    let db = match open(l, &uri) {
        Ok(db) => db,
        Err(_) => return Ok(()),
    };
    (l.limit)(db, 7, 0);
    (l.set_authorizer)(db, Some(on_auth), &mut auth as *mut AuthCtx as *mut c_void);
    match execute(l, db, &format!("EXPLAIN {}", sql), &[]) {
        Ok(st) => {
            let mut rc = st.rc;
            while rc == SQLITE_ROW {
                rc = (l.step)(st.st);
            }
            if !st.st.is_null() {
                (l.finalize)(st.st);
            }
        }
        Err(PyErr::Sql(m)) => {
            if !write && m.contains("may not be modified") {
                auth.why.push("запис через бд.читати".into());
            }
        }
        Err(_) => {}
    }
    (l.close_v2)(db);
    if let Some(w) = auth.why.first().cloned() {
        deny(it, tool, &pv, &sql, "дія SQLite поза дозволеним")?;
        return ngr(format!("{}: дія поза дозволеним ({})", tool, w), pos);
    }
    Ok(())
}
