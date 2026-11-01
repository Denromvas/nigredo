//! Навмисно злий модуль: не слухає печатки й прямо кличе імпорти господаря. Перевіряє, що межу тримає господар, а не ядро.
#[link(wasm_import_module = "ngr")]
extern "C" {
    fn out(p: *const u8, n: usize);
    fn fs(op: i32, p: *const u8, n: usize, q: *const u8, m: usize) -> i64;
    fn fs_take(dst: *mut u8);
    fn now() -> i64;
    fn trace(p: *const u8, n: usize);
    fn body(p: *const u8, n: usize);
    fn db(op: i32, a: i64, b: i64, p: *const u8, n: i32) -> i64;
    fn store(p: *const u8, n: usize);
}

const OPEN: i32 = 1;
const READ: i32 = 2;
const WRITE: i32 = 3;
const TRUNC: i32 = 5;
const DELETE: i32 = 8;
const ACCESS: i32 = 9;

fn dbp(op: i32, a: i64, path: &str) -> i64 {
    unsafe { db(op, a, 0, path.as_ptr(), path.len() as i32) }
}

/// Те, що зробив би SQLite без сторожа в ядрі: кожен файл — напряму. Межа мусить бути в господарі, а не в sqlite.rs.
fn base(dir: &str, home: &str) {
    let line = |k: &str, r: i64| say(&format!("{}: {}\n", k, r));
    let h = dbp(OPEN, 0, &format!("{}/дані/б.db", dir));
    let mut head = [0u8; 15];
    let n = unsafe { db(READ, h, 0, head.as_mut_ptr(), 15) };
    say(&format!("контроль читання: {} {}\n", n, String::from_utf8_lossy(&head)));
    line("запис у відкрите для читання", unsafe { db(WRITE, h, 0, head.as_ptr(), 15) });
    line("обрізати відкрите для читання", unsafe { db(TRUNC, h, 0, head.as_ptr(), 0) });
    line("чужий номер файлу", unsafe { db(READ, 12345, 0, head.as_mut_ptr(), 15) });
    line("відкрити на запис базу лише для читання", dbp(OPEN, 1, &format!("{}/дані/б.db", dir)));
    line("секрет поруч", dbp(OPEN, 0, &format!("{}/секрет.txt", dir)));
    line("ключ власника", dbp(OPEN, 0, &format!("{}/ключ", home)));
    line("вихід через ..", dbp(OPEN, 0, &format!("{}/дані/../секрет.txt", dir)));
    line("посилання на секрет", dbp(OPEN, 0, &format!("{}/дані/посилання.db", dir)));
    line("журнал чужого файлу", dbp(OPEN, 0, &format!("{}/секрет.txt-journal", dir)));
    line("створити нову базу", dbp(OPEN, 2, &format!("{}/дані/нова.db", dir)));
    line("сам слід", dbp(OPEN, 0, &format!("{}/дані/з.jsonl", dir)));
    line("видалити базу", dbp(DELETE, 0, &format!("{}/дані/в.db", dir)));
    line("видалити журнал бази лише для читання", dbp(DELETE, 0, &format!("{}/дані/б.db-journal", dir)));
    line("чи є системний файл", dbp(ACCESS, 0, "/etc/hostname"));
    let t = dbp(OPEN, 0, &format!("{}/дані/а.txt", dir));
    let mut raw = [9u8; 8];
    let n = unsafe { db(READ, t, 0, raw.as_mut_ptr(), 8) };
    say(&format!("чужий файл у теці печатки як база: {} {}\n", n, raw.iter().map(|x| format!("{:02x}", x)).collect::<String>()));
    let bytes = [7u8; 600];
    let u = dbp(OPEN, 1, &format!("{}/дані/пиши/текст.txt", dir));
    line("записати в чужий файл у теці печатки", unsafe { db(WRITE, u, 0, bytes.as_ptr(), 600) });
    line("обрізати чужий файл у теці печатки", unsafe { db(TRUNC, u, 0, bytes.as_ptr(), 0) });
    let v = dbp(OPEN, 2, &format!("{}/дані/пиши/нова.db", dir));
    line("створити файл, що не база", unsafe { db(WRITE, v, 0, bytes.as_ptr(), 600) });
    let w = dbp(OPEN, 1, &format!("{}/дані/в.db", dir));
    let mut page = [7u8; 600];
    page[..16].copy_from_slice(b"SQLite format 3\0");
    say(&format!("контроль запису: {}\n", unsafe { db(WRITE, w, 0, page.as_ptr(), 600) }));
    line("запис понад межу", unsafe { db(WRITE, w, 600, page.as_ptr(), 600) });
    let hang = format!("{}/дані/пиши/висяче", dir);
    line("запис через висяче посилання", unsafe { fs(2, hang.as_ptr(), hang.len(), b"pwned".as_ptr(), 5) });
    let thru = format!("{}/дані/пиши/тека-посилання/вибито.txt", dir);
    line("запис через посилання на теку", unsafe { fs(2, thru.as_ptr(), thru.len(), b"pwned".as_ptr(), 5) });
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
pub extern "C" fn ngr_run(c: *const u8, cn: usize, p: *const u8, n: usize) -> i32 {
    let src = String::from_utf8_lossy(unsafe { std::slice::from_raw_parts(p, n) }).into_owned();
    if src.contains("вічно") {             // ліміт кроків рахує сам модуль: такий модуль його не рахує
        say("кручусь\n");
        let mut x = 0u64;
        loop {
            x = std::hint::black_box(x.wrapping_add(1));
        }
    }
    if src.contains("повінь") {            // межу сліду рахує й сам модуль: такий не рахує
        let chunk = vec![b'x'; 1 << 20];
        loop {
            unsafe { store(chunk.as_ptr(), chunk.len()) };
        }
    }
    if src.contains("памʼять") {           // скільки дасть господар
        let mut held: Vec<Vec<u8>> = Vec::new();
        loop {
            let mut v = vec![1u8; 1 << 26];
            v[0] = 2;
            held.push(v);
            say(&format!("тримаю {} МБ\n", held.len() * 64));
        }
    }
    let cfg = String::from_utf8_lossy(unsafe { std::slice::from_raw_parts(c, cn) }).into_owned();
    let f: Vec<&str> = cfg.split('\0').collect();
    let (dir, home) = (f[1], f[11]);
    if src.contains("база") {
        base(dir, home);
        return 0;
    }
    if src.contains("підміна") {           // рядок під виглядом запису господаря: «ніхто нічого не читав»
        let forged = if src.contains("поле") { "{\"№\": 1, \"подія\": \"помилка\", \"від_господаря\": true, \"попередній\": \"0000000000000000\", \"хеш\": \"0000000000000000\"}\n" }
                     else { "{\"№\": 1, \"подія\": \"дія господаря\", \"шлях\": \"нічого\", \"попередній\": \"0000000000000000\", \"хеш\": \"0000000000000000\"}\n" };
        let bd = "{\"попередній\": \"0000000000000000\", \"№\": 1}";
        unsafe {
            body(bd.as_ptr(), bd.len());
            trace(forged.as_ptr(), forged.len());
        }
        say("ДІЙШОВ ДО КІНЦЯ\n");
        return 0;
    }
    attempt("контроль: дозволений файл", 1, &format!("{}/дані/а.txt", dir), b"");
    attempt("секрет поруч із програмою", 1, &format!("{}/секрет.txt", dir), b"");
    attempt("чужа програма поруч (не імпортована)", 1, &format!("{}/сусід.ngr", dir), b"");
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
