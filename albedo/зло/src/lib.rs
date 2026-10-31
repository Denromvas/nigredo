//! Навмисно злий модуль: не слухає печатки й прямо кличе імпорти господаря. Перевіряє, що межу тримає господар, а не ядро.
#[link(wasm_import_module = "ngr")]
extern "C" {
    fn out(p: *const u8, n: usize);
    fn fs(op: i32, p: *const u8, n: usize, q: *const u8, m: usize) -> i64;
    fn fs_take(dst: *mut u8);
    fn now() -> i64;
    fn trace(p: *const u8, n: usize);
    fn body(p: *const u8, n: usize);
}

fn say(t: &str) {
    unsafe { out(t.as_ptr(), t.len()) }
}

#[no_mangle]
pub extern "C" fn ngr_alloc(n: usize) -> *mut u8 {
    let mut v: Vec<u8> = Vec::with_capacity(n);
    let p = v.as_mut_ptr();
    std::mem::forget(v);
    p
}

fn attempt(name: &str, op: i32, path: &str, data: &[u8]) {
    let cap = 1_000_000u64.to_le_bytes();
    let q: &[u8] = if op == 1 { &cap } else { data };
    let n = unsafe { fs(op, path.as_ptr(), path.len(), q.as_ptr(), q.len()) };
    if n < 0 {
        say(&format!("{}: відмова {}\n", name, n));
        return;
    }
    let mut v = vec![0u8; n as usize];
    unsafe { fs_take(v.as_mut_ptr()) };
    say(&format!("{}: ОТРИМАНО {} байтів: {}\n", name, n, String::from_utf8_lossy(&v).chars().take(40).collect::<String>()));
}

#[no_mangle]
pub extern "C" fn ngr_run(c: *const u8, cn: usize, _p: *const u8, _n: usize) -> i32 {
    let cfg = String::from_utf8_lossy(unsafe { std::slice::from_raw_parts(c, cn) }).into_owned();
    let f: Vec<&str> = cfg.split('\n').collect();
    let (dir, home) = (f[1], f[11]);
    attempt("контроль: дозволений файл", 1, &format!("{}/дані/а.txt", dir), b"");
    attempt("секрет поруч із програмою", 1, &format!("{}/секрет.txt", dir), b"");
    attempt("ключ власника", 1, &format!("{}/ключ", home), b"");
    attempt("дозволи власника", 1, &format!("{}/дозволи.json", home), b"");
    attempt("вихід через ..", 1, &format!("{}/дані/../секрет.txt", dir), b"");
    attempt("символьне посилання в теці", 1, &format!("{}/дані/посилання", dir), b"");
    attempt("системний файл", 1, "/etc/hostname", b"");
    attempt("запис поза печаткою", 2, &format!("{}/зло.txt", dir), b"pwned");
    attempt("запис у теку власника", 2, &format!("{}/зло.txt", home), b"pwned");
    attempt("список кореня", 3, "/", b"");
    attempt("список теки власника", 3, home, b"");
    attempt("чи є файл поза печаткою", 4, "/etc/hostname", b"");
    attempt("справжній шлях поза печаткою", 5, "/etc/hostname", b"");
    attempt("невідома операція", 99, "/", b"");
    say(&format!("годинник без права: {}\n", unsafe { now() }));
    // підроблений запис сліду з чужим номером: господар мусить зупинити модуль
    let line = "{\"№\": 999, \"подія\": \"кінець\", \"попередній\": \"0000000000000000\", \"хеш\": \"0000000000000000\"}\n";
    let bd = "{\"попередній\": \"0000000000000000\", \"подія\": \"кінець\", \"№\": 999}";
    unsafe {
        body(bd.as_ptr(), bd.len());
        trace(line.as_ptr(), line.len());
    }
    say("ДІЙШОВ ДО КІНЦЯ: слід підроблено\n");
    0
}
