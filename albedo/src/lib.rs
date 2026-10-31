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
    !matches!(g, '‖' | 'χ' | '↘')
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

/// Запуск програми. Конфіг — рядки від господаря: шлях, тека, sha256, час, запуск, інтерпретатор, дозволи_власника, зерно,
/// кроки, розмір, межа сліду, тека власника, далі — дозволено. Усе, що виходить з модуля, — через імпорти «ngr»: які дії
/// насправді відбудуться, вирішує господар, а не цей код.
#[no_mangle]
pub extern "C" fn ngr_run(c: *const u8, cn: usize, p: *const u8, n: usize) -> i32 {
    let cfg = String::from_utf8_lossy(unsafe { std::slice::from_raw_parts(c, cn) }).into_owned();
    let f: Vec<&str> = cfg.split('\n').collect();
    let src = String::from_utf8_lossy(unsafe { std::slice::from_raw_parts(p, n) }).into_owned();
    let (path, cwd, home) = (f[0].to_string(), f[1].to_string(), f[11].to_string());
    let num = |i: usize| f[i].parse::<i64>().unwrap_or(0);
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
            say(&format!("не виконую сам: {}", why));
            return 2;
        }
    };
    let tr = trace::Trace::new(vec![Box::new(Host(trace))], vec![Box::new(Host(store))], Vec::new(), num(10) as u64);
    let mut it = interp::Interp {
        trace: tr,
        rng: rng::Mt::seed(&int::Int::S(num(7))),
        argv: Vec::new(),
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
        ("аргументи".into(), J::Arr(Vec::new())),
        ("час".into(), J::s(f[3])),
        ("запуск".into(), J::s(f[4])),
        ("тека".into(), J::Str(uni::safe(f[1]))),
        ("дозволи_власника".into(), J::Str(uni::safe(f[6]))),
        ("дозволено".into(), J::Arr(f[12..].iter().map(|a| J::s(a)).collect())),
        ("ліміти".into(), J::Obj(vec![("кроки".into(), J::Int(num(8))), ("розмір".into(), J::Int(num(9))), ("слід".into(), J::Int(num(10))), ("зерно".into(), J::Num(f[7].to_string()))])),
    ];
    if it.rec("початок", head).is_err() {
        return 4;
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

/// Випадкові байти дає ОС; у модулі їх немає — господар дасть імпортом (етап 1). Тут лише для назв службових функцій.
pub fn rand_hex(n: usize) -> String {
    "0".repeat(n * 2)
}

// ОС-виклики ядра: у модулі їх немає й не буде імпортом — лише заглушки, що кажуть «недоступно». Тож SQLite, XML і замок ОС
// тут недоступні (sqlite::load, xml::available — None), а перелік імпортів модуля — це лише «ngr».
use std::os::raw::{c_char, c_int, c_void};

#[no_mangle]
pub extern "C" fn dlopen(_f: *const c_char, _flag: c_int) -> *mut c_void {
    std::ptr::null_mut()
}

#[no_mangle]
pub extern "C" fn dlsym(_h: *mut c_void, _s: *const c_char) -> *mut c_void {
    std::ptr::null_mut()
}
