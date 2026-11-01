//! Альбедо, прототип М0 (spec/пропозиції/альбедо.md): ті самі файли ядра Атанора, зібрані у WebAssembly.
#![allow(dead_code, unused_imports, unused_variables)]
#[path = "../../athanor/src/ast.rs"]
mod ast;
#[path = "../../athanor/src/dec.rs"]
mod dec;
#[path = "../../athanor/src/int.rs"]
mod int;
#[path = "../../athanor/src/interp.rs"]
mod interp;
#[path = "../../athanor/src/json.rs"]
mod json;
#[path = "../../athanor/src/lang.rs"]
mod lang;
#[path = "../../athanor/src/lexer.rs"]
mod lexer;
#[path = "../../athanor/src/nat.rs"]
mod nat;
#[path = "../../athanor/src/oslock.rs"]
mod oslock;
#[path = "../../athanor/src/parser.rs"]
mod parser;
#[path = "../../athanor/src/pathx.rs"]
mod pathx;
#[path = "../../athanor/src/prims.rs"]
mod prims;
#[path = "../../athanor/src/prims2.rs"]
mod prims2;
#[path = "../../athanor/src/pyf.rs"]
mod pyf;
#[path = "../../athanor/src/csvp.rs"]
mod csvp;
#[path = "../../athanor/src/dates.rs"]
mod dates;
#[path = "../../athanor/src/rng.rs"]
mod rng;
#[path = "../../athanor/src/rx.rs"]
mod rx;
#[path = "../../athanor/src/schema.rs"]
mod schema;
#[path = "../../athanor/src/seal.rs"]
mod seal;
#[path = "../../athanor/src/sha.rs"]
mod sha;
#[path = "../../athanor/src/sort.rs"]
mod sort;
#[path = "../../athanor/src/sqlite.rs"]
mod sqlite;
#[path = "../../athanor/src/sys.rs"]
mod sys;
#[path = "../../athanor/src/tables.rs"]
mod tables;
#[path = "../../athanor/src/tools.rs"]
mod tools;
#[path = "../../athanor/src/trace.rs"]
mod trace;
#[path = "../../athanor/src/types.rs"]
mod types;
#[path = "../../athanor/src/uni.rs"]
mod uni;
#[path = "../../athanor/src/value.rs"]
mod value;
#[path = "../../athanor/src/xml.rs"]
mod xml;

use crate::json::J;
use crate::lexer::Back;
use std::io::Write;
use std::rc::Rc;

#[link(wasm_import_module = "ngr")]
extern "C" {
    fn out(p: *const u8, n: usize); // вивід програми (»)
    fn err(p: *const u8, n: usize); // помилка
    fn trace(p: *const u8, n: usize); // рядок сліду; ланцюжок і підпис — господаря
    fn body(p: *const u8, n: usize); // канонічний текст того самого запису (для підпису)
    fn store(p: *const u8, n: usize); // запис СЛІД.дані
    fn random(p: *mut u8, n: usize); // випадкові байти
}

/// Канонічний текст запису — господарю, разом із рядком: ключ HMAC лишається в нього (trace.rs).
pub fn trace_body(b: &str) {
    unsafe { body(b.as_ptr(), b.len()) }
}

struct Host(unsafe extern "C" fn(*const u8, usize));

impl Write for Host {
    fn write(&mut self, b: &[u8]) -> std::io::Result<usize> {
        unsafe { (self.0)(b.as_ptr(), b.len()) };
        Ok(b.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

fn glyph_ok(g: char) -> bool {
    !matches!(g, '‖')
}

#[no_mangle]
pub extern "C" fn ngr_alloc(n: usize) -> *mut u8 {
    let mut v: Vec<u8> = Vec::with_capacity(n);
    let p = v.as_mut_ptr();
    std::mem::forget(v);
    p
}

fn say(t: &str) {
    unsafe { err(t.as_ptr(), t.len()) }
}

/// Запуск програми. Конфіг — поля через нуль від господаря: шлях, тека, sha256, час, запуск, інтерпретатор, дозволи_власника, зерно,
/// кроки, розмір, межа сліду, тека власника, число аргументів, аргументи, далі — дозволено. Усе, що виходить з модуля, — через імпорти «ngr»: які дії
/// насправді відбудуться, вирішує господар, а не цей код.
#[no_mangle]
pub extern "C" fn ngr_run(c: *const u8, cn: usize, p: *const u8, n: usize) -> i32 {
    let cfg = String::from_utf8_lossy(unsafe { std::slice::from_raw_parts(c, cn) }).into_owned();
    let f: Vec<&str> = cfg.split('\0').collect();
    let src = String::from_utf8_lossy(unsafe { std::slice::from_raw_parts(p, n) }).into_owned();
    let (path, cwd, home) = (f[0].to_string(), f[1].to_string(), f[11].to_string());
    let num = |i: usize| f[i].parse::<i64>().unwrap_or(0);
    let nargs = num(12) as usize;
    let (args, allowed) = (&f[13..13 + nargs], &f[13 + nargs..]);
    // підпис автора перевіряє лише еталон: без нього програму не виконуємо, навіть як звичайну
    let lines: Vec<&str> = src.split('\n').collect();
    let last = if lines.last() == Some(&"") { lines.len().checked_sub(2) } else { lines.len().checked_sub(1) };
    if lines.iter().any(|l| l.trim_start_matches(' ').starts_with("※ підпис ed25519:")) || last.map_or(false, |i| lines[i].starts_with('※') && uni::sig_like(lines[i])) {
        say("альбедо: цього в модулі ще немає, програму не запущено (підпис автора)");
        return 120;
    }
    let parsed = (|| -> Result<ast::Node, Back> {
        let toks = lexer::lex(&src)?;
        lexer::check_twins(&toks)?;
        let mut p = parser::Parser::with(toks, tools::supported, glyph_ok, Some(cwd.clone()), None, vec![pathx::realpath(&path)], false, home.clone());
        let prog = p.program()?;
        if types::has_type_errors(&prog) {
            return lexer::back("помилки типів");
        }
        Ok(prog)
    })();
    let prog = match parsed {
        Ok(p) => p,
        Err(Back(why)) => {
            say(&format!("альбедо: цього в модулі ще немає, програму не запущено ({})", why));
            return 120; // той самий код, що в Атанора: чого не вміє ядро, Альбедо не вдає
        }
    };
    let tr = trace::Trace::new(vec![Box::new(Host(trace))], vec![Box::new(Host(store))], Vec::new(), num(10) as u64);
    let mut it = interp::Interp {
        trace: tr,
        rng: rng::Mt::seed(&int::Int::S(num(7))),
        argv: args.iter().map(|a| a.to_string()).collect(),
        protected: Default::default(),
        max_size: num(9) as u64,
        alloc: 0,
        steps_left: num(8),
        cwd: cwd.clone(),
        out: Box::new(Host(out)),
        memory: Default::default(),
        agent: "головний".into(),
        caps: Rc::new(Default::default()),
        seal_caps: Rc::new(Default::default()),
        pc: 1.0,
        halt_c: 1.0,
        mem_c: 1.0,
        try_stack: Vec::new(),
        world_c: 1.0,
        decided_c: 1.0,
        depth: 0,
        wdepth: 0,
        ends: 0,
        quota_stack: Vec::new(),
        quota_used: Default::default(),
        quota_seq: 0,
        owner_home: home,
        paths_seen: None,
        rp_cache: std::collections::HashMap::new(),
        denied: false,
        last_call: None,
        modules: Default::default(),
        prof: None,
        dry: None,
        db_unchecked: false,
        db_unverified: None,
        os_mode: None,
        write_shut: false,
    };
    let head = vec![
        ("версія".to_string(), J::s(lang::VERSION)),
        ("інтерпретатор".into(), J::s(f[5])),
        ("програма".into(), J::Str(uni::safe(f[0]))),
        ("sha256".into(), J::s(f[2])),
        ("аргументи".into(), J::Arr(args.iter().map(|a| J::s(a)).collect())),
        ("час".into(), J::s(f[3])),
        ("запуск".into(), J::s(f[4])),
        ("тека".into(), J::Str(uni::safe(f[1]))),
        ("дозволи_власника".into(), J::Str(uni::safe(f[6]))),
        ("дозволено".into(), J::Arr(allowed.iter().map(|a| J::s(a)).collect())),
        ("ліміти".into(), J::Obj(vec![("кроки".into(), J::Int(num(8))), ("розмір".into(), J::Int(num(9))), ("слід".into(), J::Int(num(10))), ("зерно".into(), J::Num(f[7].to_string()))])),
    ];
    if it.rec("початок", head).is_err() {
        return 4;
    }
    // квоти власника — на весь запуск (кілька на те саме — діє менша), як у main.rs; файли господар лічить ще й сам
    let mut oq: Vec<((String, String), u64)> = Vec::new();
    for a in allowed {
        if let Ok((base, Some(q))) = parser::split_quota(&parser::canon_perm(a)) {
            let (t, _, sc) = parser::partition(&base, ':');
            let key = (t.trim_matches(parser::py_ws).to_string(), sc.trim_matches(parser::py_ws).to_string());
            match oq.iter_mut().find(|(k, _)| *k == key) {
                Some((_, v)) => *v = (*v).min(q),
                None => oq.push((key, q)),
            }
        }
    }
    if !oq.is_empty() {
        it.quota_stack.push(Rc::new(interp::QuotaTable { who: "власник".into(), quotas: oq, tok: "власник".into() }));
    }
    let root = value::Env::new(0, None);
    let code = match it.eval(&prog, &root) {
        Ok(_) => {
            let steps = num(8) - it.steps_left;
            if it.rec("кінець", vec![("кроків".into(), J::Int(steps))]).is_err() {
                return 4;
            }
            0
        }
        Err(e) => {
            let text = uni::safe(&e.text());
            let _ = it.rec("помилка", vec![("повідомлення".into(), J::Str(text.clone()))]);
            say(&text);
            1
        }
    };
    let _ = it.out.flush();
    std::mem::forget(it);
    std::mem::forget(root);
    std::mem::forget(prog);
    code
}

/// Випадкові байти дає господар: назва службової функції сторожа бази має бути невгадною для запиту програми.
pub fn rand_hex(n: usize) -> String {
    let mut b = vec![0u8; n];
    unsafe { random(b.as_mut_ptr(), n) };
    b.iter().map(|x| format!("{:02x}", x)).collect()
}

// ОС-виклики ядра. dlopen знає лише SQLite й expat, зібрані в цей самий модуль (c/база.c): рядка «завантажити чужу бібліотеку» тут немає,
// тож замок ОС недоступний, а всі імпорти модуля й далі — лише «ngr».
use std::os::raw::{c_char, c_int, c_void};

extern "C" {
    fn ngr_sym(name: *const c_char) -> *mut c_void;
}

#[no_mangle]
pub extern "C" fn dlopen(f: *const c_char, _flag: c_int) -> *mut c_void {
    let name = unsafe { std::ffi::CStr::from_ptr(f) };
    if name.to_bytes().starts_with(b"libsqlite3") || name.to_bytes().starts_with(b"libexpat") {
        1 as *mut c_void
    } else {
        std::ptr::null_mut()
    }
}

#[no_mangle]
pub extern "C" fn dlsym(_h: *mut c_void, s: *const c_char) -> *mut c_void {
    unsafe { ngr_sym(s) }
}

// malloc для коду на C: той самий розподільник, що в ядра; розмір — у заголовку, бо free його не знає
use std::alloc::{alloc, dealloc, Layout};
const HEAD: usize = 16;

#[no_mangle]
pub unsafe extern "C" fn malloc(n: usize) -> *mut u8 {
    let Ok(l) = Layout::from_size_align(n + HEAD, HEAD) else { return std::ptr::null_mut() };
    let p = alloc(l);
    if p.is_null() {
        return p;
    }
    (p as *mut usize).write(n);
    p.add(HEAD)
}

#[no_mangle]
pub unsafe extern "C" fn free(p: *mut u8) {
    if !p.is_null() {
        let b = p.sub(HEAD);
        dealloc(b, Layout::from_size_align_unchecked((b as *mut usize).read() + HEAD, HEAD));
    }
}

#[no_mangle]
pub unsafe extern "C" fn realloc(p: *mut u8, n: usize) -> *mut u8 {
    if p.is_null() {
        return malloc(n);
    }
    let q = malloc(n);
    if !q.is_null() {
        let old = (p.sub(HEAD) as *mut usize).read();
        std::ptr::copy_nonoverlapping(p, q, old.min(n));
        free(p);
    }
    q
}
