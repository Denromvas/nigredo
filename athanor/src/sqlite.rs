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
type FnCb = extern "C" fn(*mut c_void, c_int, *mut *mut c_void);

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
    bind_double: extern "C" fn(*mut c_void, c_int, c_double) -> c_int,
    bind_blob: extern "C" fn(*mut c_void, c_int, *const c_void, c_int, isize) -> c_int,
    column_blob: extern "C" fn(*mut c_void, c_int) -> *const c_void,
    create_function: extern "C" fn(*mut c_void, *const c_char, c_int, c_int, *mut c_void, Option<FnCb>, *const c_void,
                                   *const c_void, *const c_void) -> c_int,
    user_data: extern "C" fn(*mut c_void) -> *mut c_void,
    value_type: extern "C" fn(*mut c_void) -> c_int,
    value_int64: extern "C" fn(*mut c_void) -> i64,
    value_double: extern "C" fn(*mut c_void) -> c_double,
    value_text: extern "C" fn(*mut c_void) -> *const u8,
    value_blob: extern "C" fn(*mut c_void) -> *const c_void,
    value_bytes: extern "C" fn(*mut c_void) -> c_int,
    result_error: extern "C" fn(*mut c_void, *const c_char, c_int),
    result_null: extern "C" fn(*mut c_void),
    result_int64: extern "C" fn(*mut c_void, i64),
    result_double: extern "C" fn(*mut c_void, c_double),
    result_text: extern "C" fn(*mut c_void, *const c_char, c_int, isize),
    result_blob: extern "C" fn(*mut c_void, *const c_void, c_int, isize),
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
            bind_double: sym!("sqlite3_bind_double"),
            bind_blob: sym!("sqlite3_bind_blob"),
            column_blob: sym!("sqlite3_column_blob"),
            create_function: sym!("sqlite3_create_function_v2"),
            user_data: sym!("sqlite3_user_data"),
            value_type: sym!("sqlite3_value_type"),
            value_int64: sym!("sqlite3_value_int64"),
            value_double: sym!("sqlite3_value_double"),
            value_text: sym!("sqlite3_value_text"),
            value_blob: sym!("sqlite3_value_blob"),
            value_bytes: sym!("sqlite3_value_bytes"),
            result_error: sym!("sqlite3_result_error"),
            result_null: sym!("sqlite3_result_null"),
            result_int64: sym!("sqlite3_result_int64"),
            result_double: sym!("sqlite3_result_double"),
            result_text: sym!("sqlite3_result_text"),
            result_blob: sym!("sqlite3_result_blob"),
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
    rand: bool, // «жереб» без квоти: лише з ним — INSERT і зміна rowid у системних таблицях (суд 9г)
    why: Vec<String>,
    careful: bool,      // перша відмова — сама від стану бази (ознакою, а не підрядком причини; огляд 0.8.1)
    doubt: Vec<String>, // db_doubts запиту: з ними запобіжна відмова не доводить, що запит у межах прав
}

fn auth_ctx(it: &Interp, write: bool) -> AuthCtx {
    AuthCtx { write, rand: db_rights(it).1, why: Vec::new(), careful: false, doubt: Vec::new() }
}

/// (годинник, жереб) SQLite: «час» і «жереб» без квоти (її не порахувати), як 🜔час і 🜔жереб (суд 9; «час≤N» — суд 9в).
fn db_rights(it: &Interp) -> (bool, bool) {
    let free = |cap: &str| it.caps.has(cap) && !it.quota_stack.iter().any(|q| q.quotas.iter().any(|((t, _), _)| t == cap));
    (free("час"), free("жереб"))
}

const DB_CLOCK: [&str; 7] = ["date", "time", "datetime", "julianday", "unixepoch", "strftime", "timediff"];
const DB_NOW: [&str; 3] = ["current_date", "current_time", "current_timestamp"];
const UDF_ERR: &[u8] = b"user-defined function raised exception\0";
const ROWID_MAX: i64 = i64::MAX; // після нього SQLite бере rowid навмання
const SCHEMA_TABLES: [&str; 4] = ["sqlite_master", "sqlite_schema", "sqlite_temp_master", "sqlite_temp_schema"]; // CREATE пише сюди
const ROWID_WHY: [&str; 4] = [
    "дійшла до rowid 2⁶³−1 — далі SQLite бере його навмання",
    "ховає rowid стовпцями rowid, _rowid_ і oid — запис у неї не перевірити",
    "— рядок отримав би rowid 2⁶³−1, а після нього SQLite бере rowid навмання",
    "підійшла до rowid 2⁶³−1 — рядки, які допише сюди сам SQLite, дійдуть до межі, а далі rowid навмання",
];
const ROWID_NEAR: i64 = ROWID_MAX - (1 << 32); // системна таблиця: за одну інструкцію SQLite допише рядків менше

/// Значення аргументу чи результату функції SQLite — як його бачить модуль sqlite3 Python.
enum SqlV {
    Null,
    Int(i64),
    Float(f64),
    Text(String),
    Blob(Vec<u8>),
}

/// Своя функція на зʼєднанні (_db_guard): 0 — дата з даних, 1 — CURRENT_*, 2 — random/randomblob, 3 — rowid.
struct FnCtx {
    name: &'static str,
    kind: u8,
    g: *mut Guard,
}

struct Guard {
    auth: *mut AuthCtx,
    helper: *mut c_void, // справжні функції SQLite — на окремому зʼєднанні без підмін
    fns: Vec<Box<FnCtx>>,
}

unsafe fn sql_value(l: &Lib, v: *mut c_void) -> Option<SqlV> {
    Some(match (l.value_type)(v) {
        1 => SqlV::Int((l.value_int64)(v)),
        2 => SqlV::Float((l.value_double)(v)),
        3 => {
            let p = (l.value_text)(v);
            let n = (l.value_bytes)(v) as usize;
            let b = if p.is_null() { &[][..] } else { std::slice::from_raw_parts(p, n) };
            SqlV::Text(String::from_utf8(b.to_vec()).ok()?) // Python: str — не UTF-8 → виняток
        }
        4 => {
            let p = (l.value_blob)(v) as *const u8;
            let n = (l.value_bytes)(v) as usize;
            SqlV::Blob(if p.is_null() { Vec::new() } else { std::slice::from_raw_parts(p, n).to_vec() })
        }
        _ => SqlV::Null,
    })
}

/// db_word: аргумент функції дат так, як його порівнює сам SQLite — байти до першого NUL, малі — лише ASCII.
fn db_word(x: &SqlV) -> Option<Vec<u8>> {
    let b = match x {
        SqlV::Text(s) => s.as_bytes(),
        SqlV::Blob(b) => &b[..],
        _ => return None,
    };
    let end = b.iter().position(|&c| c == 0).unwrap_or(b.len());
    Some(b[..end].to_ascii_lowercase())
}

fn refusal(f: &FnCtx, a: &[SqlV]) -> Option<String> {
    let name = f.name;
    match f.kind {
        0 => {
            let k = if name == "strftime" { 1 } else { 0 };
            let (times, mods): (&[SqlV], &[SqlV]) = if name == "timediff" {
                (a, &[])
            } else {
                (&a[k.min(a.len())..(k + 1).min(a.len())], &a[(k + 1).min(a.len())..])
            };
            let is = |x: &SqlV, ws: &[&[u8]]| db_word(x).map_or(false, |w| ws.contains(&&w[..]));
            let now = (times.is_empty() && name != "timediff")
                || times.iter().any(|x| is(x, &[b"now", b"subsec", b"subsecond"]))
                || mods.iter().any(|x| is(x, &[b"localtime", b"utc"]));
            now.then(|| format!("годинник SQLite ({} — поточний час чи часовий пояс) без права «час» (з квотою «час≤N» — лише 🜔час) — дати з даних рахуються, «зараз» — лише з «час» у печатці", name))
        }
        1 => Some(format!("годинник SQLite ({}) без права «час» (з квотою «час≤N» — лише 🜔час) — дати рахуйте в Nigredo (◷) чи дайте «час» у печатці", name)),
        2 => Some(format!("випадковість SQLite ({}) без права «жереб» (з квотою «жереб≤N» — лише 🜔жереб)", name)),
        _ => {
            let t = match a.first() {
                Some(SqlV::Text(t)) => uni::safe(t),
                _ => String::new(),
            };
            let k = match a.get(1) {
                Some(SqlV::Int(k)) => (*k).clamp(0, 2) as usize,
                _ => 0,
            };
            Some(format!("випадковість SQLite (таблиця «{}» {}) без права «жереб»", t, ROWID_WHY[k]))
        }
    }
}

/// Справжня функція SQLite на допоміжному зʼєднанні: helper.execute('SELECT f(?, …)', a).fetchone()[0].
fn builtin(l: &Lib, g: &mut Guard, name: &str, a: &[SqlV]) -> Option<SqlV> {
    if g.helper.is_null() {
        g.helper = open(l, ":memory:").ok()?;
    }
    let db = g.helper;
    let sql = format!("SELECT {}({})", name, vec!["?"; a.len()].join(", "));
    let c = CString::new(sql.clone()).ok()?;
    let mut st: *mut c_void = std::ptr::null_mut();
    if (l.prepare_v2)(db, c.as_ptr(), sql.len() as c_int + 1, &mut st, std::ptr::null_mut()) != 0 || st.is_null() {
        return None;
    }
    for (i, x) in a.iter().enumerate() {
        let p = i as c_int + 1;
        match x {
            SqlV::Null => (l.bind_null)(st, p),
            SqlV::Int(v) => (l.bind_int64)(st, p, *v),
            SqlV::Float(v) => (l.bind_double)(st, p, *v),
            SqlV::Text(s) => (l.bind_text)(st, p, s.as_ptr() as *const c_char, s.len() as c_int, -1),
            SqlV::Blob(b) => (l.bind_blob)(st, p, b.as_ptr() as *const c_void, b.len() as c_int, -1),
        };
    }
    let out = if (l.step)(st) == SQLITE_ROW {
        match (l.column_type)(st, 0) {
            1 => Some(SqlV::Int((l.column_int64)(st, 0))),
            2 => Some(SqlV::Float((l.column_double)(st, 0))),
            3 => {
                let p = (l.column_text)(st, 0);
                let n = (l.column_bytes)(st, 0) as usize;
                let b = if p.is_null() { &[][..] } else { unsafe { std::slice::from_raw_parts(p, n) } };
                String::from_utf8(b.to_vec()).ok().map(SqlV::Text)
            }
            4 => {
                let p = (l.column_blob)(st, 0) as *const u8;
                let n = (l.column_bytes)(st, 0) as usize;
                Some(SqlV::Blob(if p.is_null() { Vec::new() } else { unsafe { std::slice::from_raw_parts(p, n).to_vec() } }))
            }
            _ => Some(SqlV::Null),
        }
    } else {
        None
    };
    (l.finalize)(st);
    out
}

extern "C" fn on_fn(ctx: *mut c_void, argc: c_int, argv: *mut *mut c_void) {
    let l = load().expect("libsqlite3");
    let f = unsafe { &*((l.user_data)(ctx) as *const FnCtx) };
    let g = unsafe { &mut *f.g };
    let fail = || (l.result_error)(ctx, UDF_ERR.as_ptr() as *const c_char, -1);
    let args: Option<Vec<SqlV>> = (0..argc.max(0) as usize).map(|i| unsafe { sql_value(l, *argv.add(i)) }).collect();
    let Some(args) = args else { return fail() };
    if let Some(msg) = refusal(f, &args) {
        let a = unsafe { &mut *g.auth };
        // таблиця вже на межі, а rowid бере SQLite (k = 0) — стан бази, якщо це перша відмова
        if f.kind == 3 && matches!(args.get(1), Some(SqlV::Int(0))) && a.why.is_empty() {
            a.careful = true;
        }
        a.why.push(msg);
        return fail();
    }
    match builtin(l, g, f.name, &args) {
        Some(SqlV::Null) => (l.result_null)(ctx),
        Some(SqlV::Int(v)) => (l.result_int64)(ctx, v),
        Some(SqlV::Float(v)) => (l.result_double)(ctx, v),
        Some(SqlV::Text(s)) => (l.result_text)(ctx, s.as_ptr() as *const c_char, s.len() as c_int, -1),
        Some(SqlV::Blob(b)) => (l.result_blob)(ctx, b.as_ptr() as *const c_void, b.len() as c_int, -1),
        None => fail(),
    }
}

fn exec(l: &Lib, db: *mut c_void, sql: &str, args: &[Arg]) -> Result<Vec<String>, PyErr> {
    let st = execute(l, db, sql, args)?;
    let mut out = Vec::new();
    let mut rc = st.rc;
    while rc == SQLITE_ROW {
        let row = fetch_row(l, st.st);
        rc = (l.step)(st.st);
        let err = if rc != SQLITE_ROW && rc != SQLITE_DONE { Some(db_err(l, db)) } else { None };
        match (row, err) {
            (Ok(c), None) => {
                if let Some(Cell::Text(t)) = c.into_iter().next() {
                    out.push(t);
                }
            }
            (Err(e), _) | (_, Some(e)) => {
                (l.finalize)(st.st);
                return Err(e);
            }
        }
    }
    if !st.st.is_null() {
        (l.finalize)(st.st);
    }
    Ok(out)
}

/// Таблиці (INSERT, UPDATE), які authorizer бачить, поки SQLite компілює запит (і тіла тригерів); рішення — того самого
/// authorizer, без запису причин (дозвільний підключив би віртуальну таблицю, якої справжній не пустить).
struct Written {
    ins: Vec<String>,
    upd: Vec<String>,
    reads: Vec<String>, // читання таблиць pragma_* (таблиць-функцій PRAGMA)
    auth: AuthCtx,
}

extern "C" fn on_record(ud: *mut c_void, action: c_int, a1: *const c_char, a2: *const c_char, db: *const c_char,
                        src: *const c_char) -> c_int {
    let w = unsafe { &mut *(ud as *mut Written) };
    if (action == 18 || action == 23) && !a1.is_null() && !db.is_null() && unsafe { cs(db) } == "main" {
        let t = unsafe { cs(a1) };
        let v = if action == 18 { &mut w.ins } else { &mut w.upd };
        if !v.contains(&t) {
            v.push(t);
        }
    }
    if action == 20 && !a1.is_null() {
        let t = unsafe { cs(a1) };
        if uni::lower(&t).starts_with("pragma_") && !w.reads.contains(&t) {
            w.reads.push(t);
        }
    }
    on_auth(&mut w.auth as *mut AuthCtx as *mut c_void, action, a1, a2, db, src)
}

/// db_body: запит без того, що SQLite пропускає до першої інструкції — пропусків, коментарів і порожніх інструкцій «;»
/// («;INSERT …» SQLite виконує, а «EXPLAIN ;INSERT …» — синтаксична помилка; суд 9г).
fn db_body(sql: &str) -> &str {
    let b = sql.as_bytes();
    let (mut i, n) = (0, b.len());
    while i < n {
        if b" \t\n\x0c\r;".contains(&b[i]) {
            i += 1;
        } else if b[i..].starts_with(b"--") {
            i = b[i..].iter().position(|&c| c == b'\n').map_or(n, |j| i + j + 1);
        } else if b[i..].starts_with(b"/*") {
            i = b[i + 2..].windows(2).position(|w| w == b"*/").map_or(n, |j| i + 2 + j + 2);
        } else {
            break;
        }
    }
    &sql[i..]
}

/// db_explain: запит попереднього проходу — та сама інструкція без виконання (своє EXPLAIN — як його читає SQLite).
fn db_explain(sql: &str) -> String {
    let body = db_body(sql);
    let b = body.as_bytes();
    let own = b.len() >= 7 && b[..7].eq_ignore_ascii_case(b"explain")
        && !b.get(7).map_or(false, |&c| c >= 0x80 || c.is_ascii_alphanumeric() || c == b'_' || c == b'$');
    if own { body.to_string() } else { format!("EXPLAIN {}", body) }
}

extern "C" fn on_deny(ud: *mut c_void, _: c_int, _: *const c_char, _: *const c_char, _: *const c_char,
                      _: *const c_char) -> c_int {
    unsafe { *(ud as *mut bool) = true };
    1
}

/// db_compiles: чи SQLite скомпілює сам запит — компіляція з authorizer, що відмовляє на першій же дії. Помилка, коли
/// authorizer ще не питали, сталася до першої дії — так само й у справжньому виконанні: запит нічого не запише (суд 9д,
/// Оркестратор). Ознака — сам виклик authorizer, а не текст помилки («access … prohibited»; огляд 0.8.1).
fn compiles(l: &Lib, db: *mut c_void, sql: &str, args: &[Arg]) -> bool {
    let mut asked = false;
    (l.set_authorizer)(db, Some(on_deny), &mut asked as *mut bool as *mut c_void);
    let r = match execute(l, db, sql, args) {
        Ok(st) => {
            if !st.st.is_null() {
                (l.finalize)(st.st);
            }
            true
        }
        Err(PyErr::Sql(_)) => asked,
        Err(_) => true, // невідоме — як «компілюється»: захист на всіх таблицях
    };
    (l.set_authorizer)(db, None, std::ptr::null_mut());
    r
}

/// db_autoinc: таблиця з AUTOINCREMENT — після rowid 2⁶³−1 SQLite відмовляє (database or disk is full), а не бере
/// навмання: тригери rowid їй не потрібні (суд 9д, Практик). Ознака — MemMax у головній програмі вставки.
fn autoinc(l: &Lib, db: *mut c_void, t: &str) -> bool {
    let st = match execute(l, db, &format!("EXPLAIN INSERT INTO main.\"{}\" DEFAULT VALUES", t.replace('"', "\"\"")), &[]) {
        Ok(st) => st,
        Err(_) => return false,
    };
    let mut ops: Vec<(i64, String)> = Vec::new();
    let mut rc = st.rc;
    while rc == SQLITE_ROW {
        let op = (l.column_text)(st.st, 1);
        let op = if op.is_null() { String::new() } else { unsafe { cs(op as *const c_char) } };
        ops.push(((l.column_int64)(st.st, 0), op));
        rc = (l.step)(st.st);
    }
    (l.finalize)(st.st);
    if rc != SQLITE_DONE {
        return false; // як fetchall еталона: помилка посеред — не AUTOINCREMENT
    }
    for (i, (addr, op)) in ops.iter().enumerate() {
        if i > 0 && *addr <= ops[i - 1].0 {
            return false; // далі — підпрограми тригерів
        }
        if op == "MemMax" {
            return true;
        }
    }
    false
}

/// Рядки байткоду EXPLAIN: (опкод, p4) — як fetchall еталона (помилка посеред — помилка).
fn explain_ops(l: &Lib, db: *mut c_void, sql: &str, args: &[Arg]) -> Result<Vec<(String, Option<String>)>, PyErr> {
    let st = execute(l, db, sql, args)?;
    let wide = st.cols.len() > 5; // EXPLAIN QUERY PLAN — 4 стовпці
    let text = |i: c_int| -> Option<String> {
        if (l.column_type)(st.st, i) != 3 {
            return None;
        }
        let p = (l.column_text)(st.st, i);
        if p.is_null() { None } else { Some(unsafe { cs(p as *const c_char) }) }
    };
    let mut out = Vec::new();
    let mut rc = st.rc;
    while rc == SQLITE_ROW {
        if wide {
            out.push((text(1).unwrap_or_default(), text(5)));
        }
        rc = (l.step)(st.st);
    }
    let err = if rc != SQLITE_DONE && !st.st.is_null() { Some(db_err(l, db)) } else { None };
    if !st.st.is_null() {
        (l.finalize)(st.st);
    }
    match err {
        Some(e) => Err(e),
        None => Ok(out),
    }
}

/// Чи дає запит хоч один рядок.
fn has_row(l: &Lib, db: *mut c_void, sql: &str, args: &[Arg]) -> Result<bool, PyErr> {
    let s = execute(l, db, sql, args)?;
    let v = s.rc == SQLITE_ROW;
    if !s.st.is_null() {
        (l.finalize)(s.st);
    }
    Ok(v)
}

/// db_pragma_tables: таблиці-функції PRAGMA, яких authorizer не пустить (свою PRAGMA вони готують лише під час
/// виконання; огляд 0.8.1, Скептик). Своя таблиця з такою назвою — не PRAGMA.
fn pragma_tables(l: &Lib, db: *mut c_void, reads: &[String]) -> Result<Vec<String>, PyErr> {
    let mut names = reads.to_vec();
    names.sort();
    let mut out = Vec::new();
    for t in names {
        let low = uni::lower(&t);
        if low.starts_with("pragma_") && !INFO_PRAGMAS.contains(&&low[7..])
            && !has_row(l, db, "SELECT 1 FROM pragma_table_list WHERE name = ? COLLATE NOCASE", &[Arg::Text(t.clone())])?
        {
            out.push(t);
        }
    }
    Ok(out)
}

/// db_doubts: що в запиті могло б вийти за права лише під час виконання — за байткодом (Function/PureFunc) і читанням
/// таблиць-функцій PRAGMA; з таким запобіжна відмова не доводить, що запит у межах прав (огляд 0.8.1, Н-1 Скептика).
fn doubts(clock_ok: bool, rand_ok: bool, ops: &[(String, Option<String>)], reads: &[String]) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for (op, p4) in ops {
        let name = match p4 {
            Some(p) if op == "Function" || op == "PureFunc" => uni::lower(p.split('(').next().unwrap_or("")),
            _ => continue,
        };
        let why = if (name == "random" || name == "randomblob") && !rand_ok {
            format!("випадковість SQLite (у запиті — {}) без права «жереб»", name)
        } else if DB_NOW.contains(&name.as_str()) && !clock_ok {
            format!("годинник SQLite (у запиті — {}) без права «час»", name)
        } else if DB_CLOCK.contains(&name.as_str()) && !clock_ok {
            format!("годинник SQLite (у запиті — {}: «зараз» чи дата з даних — без виконання не перевірити) без права «час»", name)
        } else {
            continue;
        };
        if !out.contains(&why) {
            out.push(why);
        }
    }
    out.extend(reads.iter().map(|t| format!("PRAGMA (у запиті — таблиця-функція {})", uni::safe(t))));
    out
}

/// Що знає попередній прохід: таблиці, у які запит пише (і системні), відмови authorizer і сумніви (db_doubts).
struct Pass {
    ins: Vec<String>,
    upd: Vec<String>,
    system: Vec<String>,
    denied: Vec<String>,
    doubt: Vec<String>,
}

/// _db_written: таблиці main, у які запит може писати — і сам, і тригерами (EXPLAIN — без виконання); пише віртуальна
/// таблиця — то й тіньові (FTS5 бере rowid сам, своїми запитами). Не скомпілювався — то всі таблиці (суд 9г: захист
/// закритий, доки не доведено інше). Третє — системні таблиці, у які рядок допише сам SQLite: sqlite_schema — на CREATE,
/// sqlite_sequence — на INSERT у будь-яку таблицю (AUTOINCREMENT authorizer не показує). Відмовив authorizer — відмовить
/// і справжній: це одразу «заборонено», без тригерів і стану бази (огляд 0.8.1, Н-1 Скептика).
fn written(l: &Lib, db: *mut c_void, clock_ok: bool, sql: &str, args: &[Arg]) -> Result<Pass, PyErr> {
    let mut w = Written {
        ins: Vec::new(),
        upd: Vec::new(),
        reads: Vec::new(),
        auth: AuthCtx { write: true, rand: false, why: Vec::new(), careful: false, doubt: Vec::new() },
    };
    (l.set_authorizer)(db, Some(on_record), &mut w as *mut Written as *mut c_void);
    // помилку запиту покаже його виконання, а захист стане на всі таблиці
    let ops = explain_ops(l, db, &db_explain(sql), args);
    (l.set_authorizer)(db, None, std::ptr::null_mut());
    let failed = ops.is_err();
    let none = |denied: Vec<String>| Pass { ins: Vec::new(), upd: Vec::new(), system: Vec::new(), denied, doubt: Vec::new() };
    if !w.auth.why.is_empty() {
        return Ok(none(w.auth.why));
    }
    if failed && !compiles(l, db, sql, args) {
        return Ok(none(Vec::new())); // не скомпілюється й сам — нічого не запише
    }
    let doubt = match &ops {
        Err(_) => vec!["запит не перевірено до виконання (EXPLAIN не скомпілювався)".to_string()],
        Ok(ops) => doubts(clock_ok, false, ops, &pragma_tables(l, db, &w.reads)?),
    };
    let names = exec(l, db, r"SELECT name FROM pragma_table_list WHERE schema = 'main' AND wr = 0 AND name NOT LIKE 'sqlite\_%' ESCAPE '\' ORDER BY name", &[])?;
    let types = exec(l, db, r"SELECT type FROM pragma_table_list WHERE schema = 'main' AND wr = 0 AND name NOT LIKE 'sqlite\_%' ESCAPE '\' ORDER BY name", &[])?;
    let sys = exec(l, db, r"SELECT name FROM pragma_table_list WHERE schema = 'main' AND wr = 0 AND type = 'table' AND name LIKE 'sqlite\_%' ESCAPE '\' ORDER BY name", &[])?;
    let schema_t = |t: &str| SCHEMA_TABLES.contains(&uni::lower(t).as_str());
    let schema = failed || w.ins.iter().any(|t| schema_t(t));
    let seq = failed || w.ins.iter().any(|t| !schema_t(t));
    let system: Vec<String> = sys.into_iter()
        .filter(|t| if schema_t(t) { schema } else { seq && uni::lower(t) == "sqlite_sequence" }).collect();
    let kind = |t: &str| names.iter().position(|n| n == t).map(|i| types[i].as_str());
    if failed {
        w.ins = names.clone();
        w.upd = names.clone();
    } else if w.ins.iter().chain(w.upd.iter()).any(|t| kind(t) == Some("virtual")) {
        for (n, k) in names.iter().zip(types.iter()) {
            if k == "shadow" {
                for v in [&mut w.ins, &mut w.upd] {
                    if !v.contains(n) {
                        v.push(n.clone());
                    }
                }
            }
        }
    }
    let ok = |t: &String| matches!(kind(t), Some("table") | Some("shadow"));
    Ok(Pass { ins: w.ins.into_iter().filter(ok).collect(), upd: w.upd.into_iter().filter(ok).collect(), system,
              denied: Vec::new(), doubt })
}

/// _db_guard: без «час» — свої функції дат (дата з даних — як у SQLite; 'now', без часу, localtime/utc, CURRENT_* —
/// відмова), без «жереб» — random/randomblob, і жоден рядок не доходить до rowid 2⁶³−1 (тимчасові тригери в памʼяті,
/// лише на таблицях, у які запит пише; суд 9в) — відмова.
fn guard(l: &Lib, db: *mut c_void, it: &Interp, g: &mut Guard, write: bool, sql: &str, args: &[Arg]) -> Result<(), PyErr> {
    let (clock_ok, rand_ok) = db_rights(it);
    let gp = g as *mut Guard;
    let add = |name: &'static str, n: c_int, kind: u8, g: &mut Guard| -> Result<(), PyErr> {
        let f = Box::new(FnCtx { name, kind, g: gp });
        let c = CString::new(name).unwrap();
        let flags = if kind == 1 || kind == 2 { 1 } else { 1 | 0x800 }; // як у SQLite: CURRENT_* і random — недетерміновані (9б)
        let rc = (l.create_function)(db, c.as_ptr(), n, flags, &*f as *const FnCtx as *mut c_void, Some(on_fn),
                                     std::ptr::null(), std::ptr::null(), std::ptr::null());
        g.fns.push(f);
        if rc != 0 {
            return Err(PyErr::Sql("Error creating function".into()));
        }
        Ok(())
    };
    if !clock_ok {
        for n in DB_CLOCK {
            add(n, -1, 0, g)?;
        }
        for n in DB_NOW {
            add(n, 0, 1, g)?;
        }
    }
    if !rand_ok {
        add("random", 0, 2, g)?;
        add("randomblob", 1, 2, g)?;
        if write {
            exec(l, db, "PRAGMA temp_store = MEMORY", &[])?;
            add("ngr_rowid", 2, 3, g)?;
            let Pass { ins, upd, system, denied, doubt } = written(l, db, clock_ok, sql, args)?;
            let a = unsafe { &mut *g.auth };
            if !denied.is_empty() {
                // відмовив authorizer — так само відмовить і в запуску: одразу, без тригерів
                let first = denied[0].clone();
                a.why.extend(denied);
                return Err(PyErr::Sql(first));
            }
            a.doubt = doubt;
            for t in &system {
                // старий файл: системна таблиця біля межі, а рядки в неї пише сам SQLite (AUTOINCREMENT, CREATE) — і
                // кілька за одну інструкцію (суд 9г, перевірка виправлення)
                if pragma(l, db, &format!("SELECT max(rowid) > {} FROM main.\"{}\"", ROWID_NEAR, t.replace('"', "\"\"")))? == Some(1) {
                    let msg = format!("випадковість SQLite (системна таблиця «{}» {}) без права «жереб»", uni::safe(t), ROWID_WHY[3]);
                    if a.why.is_empty() {
                        a.careful = true;
                    }
                    a.why.push(msg.clone());
                    return Err(PyErr::Sql(msg));
                }
            }
            let mut all: Vec<&String> = ins.iter().chain(upd.iter()).collect();
            all.sort();
            all.dedup();
            for (i, t) in all.into_iter().enumerate() {
                if autoinc(l, db, t) {
                    continue;
                }
                let (q, lit) = (t.replace('"', "\"\""), t.replace('\'', "''"));
                let cols: Vec<String> = exec(l, db, "SELECT name FROM pragma_table_xinfo(?)", &[Arg::Text(t.clone())])?
                    .iter().map(|c| c.to_ascii_lowercase()).collect();
                let alias = ["rowid", "_rowid_", "oid"].into_iter().find(|a| !cols.iter().any(|c| c == a));
                let mut trig: Vec<(&str, String, u8)> = Vec::new();
                match (ins.contains(t), alias) {
                    (true, None) => trig.push(("BEFORE INSERT", "1".into(), 1)),
                    (true, Some(a)) => {
                        // таблиця вже на межі (старий файл), а rowid бере SQLite (NEW — −1); явний — можна
                        if pragma(l, db, &format!("SELECT max({}) = {} FROM main.\"{}\"", a, ROWID_MAX, q))? == Some(1) {
                            trig.push(("BEFORE INSERT", format!("NEW.{a} = -1 OR NEW.{a} IS NULL", a = a), 0));
                        }
                        trig.push(("AFTER INSERT", format!("NEW.{} = {}", a, ROWID_MAX), 2));
                    }
                    _ => {}
                }
                if let (true, Some(a)) = (upd.contains(t), alias) {
                    trig.push(("AFTER UPDATE", format!("NEW.{a} = {m} AND OLD.{a} IS NOT {m}", a = a, m = ROWID_MAX), 2));
                }
                for (j, (when, cond, k)) in trig.iter().enumerate() {
                    exec(l, db, &format!("CREATE TEMP TRIGGER \"ngr_rowid_{}_{}\" {} ON main.\"{}\" WHEN {} BEGIN SELECT ngr_rowid('{}', {}); END",
                                         i, j, when, q, cond, lit, k), &[])?;
                }
            }
        }
    }
    Ok(())
}

/// db_readonly: запис через бд.читати, який SQLite відкинув ще до authorizer — увесь текст «table ІМʼЯ may not be
/// modified»; частина тексту («no such table: …may not be modified») — описка, а не спроба (огляд 0.8.1).
fn readonly(m: &str) -> bool {
    let name = m.strip_prefix("table ").and_then(|r| r.strip_suffix(" may not be modified"));
    name.map_or(false, |n| !n.is_empty() && n.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_'))
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
    let t = uni::lower(a1.as_deref().unwrap_or(""));
    if !cx.rand && t.starts_with("sqlite_") && !SCHEMA_TABLES.contains(&t.as_str())
        && (action == 18 || (action == 23 && a2.as_deref() == Some("ROWID")))
    {
        cx.why.push(format!("випадковість SQLite (системна таблиця «{}»: INSERT і зміна rowid — лише з правом «жереб», бо з rowid 2⁶³−1 наступний рядок SQLite бере навмання)",
                            uni::safe(a1.as_deref().unwrap_or(""))));
        return 1;
    }
    let read = [20, 21, 31, 33];
    let write = [18, 23, 9, 2, 11, 26, 1, 10, 27, 8, 17, 7, 16];
    let ok = read.contains(&action) || (cx.write && write.contains(&action))
        || (action == 19 && INFO_PRAGMAS.contains(&uni::lower(a1.as_deref().unwrap_or("")).as_str()));
    if ok {
        return 0;
    }
    if cx.write && action == 14 && a1.as_deref().map_or(false, |t| t.starts_with("ngr_rowid_")) {
        return 0; // DROP TABLE прибирає й тимчасовий тригер guard на цій таблиці
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
    let body = db_body(sql); // після того, що SQLite пропускає («;VACUUM»; суд 9г)
    if re_search(&format!(r"(?is)\A(?:{})vacuum\b", gap), body) {
        deny(it, tool, path, sql, "VACUUM")?;
        return ngr(format!("{}: VACUUM заборонено (VACUUM INTO пише файл поза текою з печатки)", tool), pos);
    }
    let r = Rx::new(&format!(r"(?is)\A(?:{g}\()*{g}(\w*){g}(?:main{g}\.{g})?(\w*)", g = gap)).ok().unwrap();
    let t: Vec<char> = body.chars().collect();
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

fn sql_err(m: &str) -> String {
    crate::uni::in_words(&crate::lang::SQL_ERRORS, m)
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
    let mut grd = Guard { auth: &mut auth as *mut AuthCtx, helper: std::ptr::null_mut(), fns: Vec::new() };
    let mut prog = ProgCtx { it: it as *mut Interp, deadline };
    let result = (|| -> R<V> {
        (l.limit)(db, 7, 0);
        (l.limit)(db, 0, (4 * it.max_size).min(i32::MAX as u64) as c_int);
        let r = (|| -> Result<V, Result<PyErr, Box<E>>> {
            // page_size уже читає схему: файл — не база чи схема пошкоджена — помилка програми, а не код 4 (суд 9б)
            pragma(l, db, &format!("PRAGMA hard_heap_limit = {}", (64u64 << 20).max(32 * it.max_size))).map_err(Ok)?;
            if write {
                let page = pragma(l, db, "PRAGMA page_size").map_err(Ok)?.unwrap_or(4096);
                pragma(l, db, &format!("PRAGMA max_page_count = {}", 64 * 1024 * 1024 / page)).map_err(Ok)?;
            }
            guard(l, db, it, &mut grd, write, &sql, &bound).map_err(Ok)?; // до authorizer і лічби кроків: не запит програми
            (l.set_authorizer)(db, Some(on_auth), &mut auth as *mut AuthCtx as *mut c_void);
            (l.progress)(db, 1000, Some(on_progress), &mut prog as *mut ProgCtx as *mut c_void);
            let before = (l.total_changes)(db);
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
                // таблиця вже на межі чи системна біля неї — так у самій базі (суд 9д), — лише коли в запиті заборонених
                // дій не знайдено (огляд 0.8.1, Н-1 Скептика)
                let careful = auth.careful && auth.doubt.is_empty();
                if auth.careful && !auth.doubt.is_empty() {
                    let first = format!("{}; запит і не виконувався: {}", auth.doubt[0], auth.why[0]);
                    auth.why.insert(0, first);
                }
                let denied = !auth.why.is_empty() || (!write && readonly(&m));
                if careful {
                    let q: String = uni::safe(&sql).chars().take(500).collect();
                    let agent = it.agent.clone();
                    it.caution(vec![
                        ("агент".into(), J::Str(agent)),
                        ("назва".into(), J::s(tool)),
                        ("шлях".into(), J::Str(uni::safe(&pv))),
                        ("запит".into(), J::Str(q)),
                        ("причина".into(), J::Str(format!("стан бази: {}; запит не виконувався — authorizer і байткод SQLite заборонених дій у ньому не знайшли", auth.why[0]).chars().take(1000).collect())),
                    ])?;
                } else if denied {
                    let why = match auth.why.first() {
                        Some(w) => format!("дія SQLite поза дозволеним: {}", w),
                        None => "дія SQLite поза дозволеним".into(),
                    };
                    deny(it, tool, &pv, &sql, &why.chars().take(1000).collect::<String>())?;
                }
                let msg = if careful {
                    format!("запобіжна відмова (так у самій базі; запит не виконувався, а заборонених дій у ньому перевірка не знайшла): {}", auth.why[0])
                } else if denied {
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
    if !grd.helper.is_null() {
        (l.close_v2)(grd.helper);
    }
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
    let mut w = Written { ins: Vec::new(), upd: Vec::new(), reads: Vec::new(), auth: auth_ctx(it, write) };
    let uri = if pathx::isfile(&real) { format!("file:{}?mode=ro", quote(&real)) } else { ":memory:".into() };
    let db = match open(l, &uri) {
        Ok(db) => db,
        Err(_) => return Ok(()),
    };
    (l.limit)(db, 7, 0);
    (l.set_authorizer)(db, Some(on_record), &mut w as *mut Written as *mut c_void);
    match execute(l, db, &db_explain(&sql), &[]) { // «;PRAGMA …» — та сама відмова, що й у запуску (суд 9г)
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
            if !write && readonly(&m) {
                w.auth.why.push("запис через бд.читати".into());
            }
        }
        Err(_) => {}
    }
    // таблицю-функцію PRAGMA authorizer спитає лише в запуску (огляд 0.8.1, Скептик)
    (l.set_authorizer)(db, None, std::ptr::null_mut());
    if w.auth.why.is_empty() {
        if let Ok(ts) = pragma_tables(l, db, &w.reads) {
            w.auth.why.extend(ts.iter().map(|t| format!("PRAGMA {}", uni::safe(&uni::lower(&t[7..])))));
        }
    }
    (l.close_v2)(db);
    if let Some(why) = w.auth.why.first().cloned() {
        deny(it, tool, &pv, &sql, &format!("дія SQLite поза дозволеним: {}", why).chars().take(1000).collect::<String>())?;
        return ngr(format!("{}: дія поза дозволеним ({})", tool, why), pos);
    }
    Ok(())
}
