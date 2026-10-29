//! Замок ОС (фаза 6.1, spec/пропозиції/фаза6.md §1): групи дій, яких печатка не просить зовсім, закриває ядро
//! (seccomp-bpf). Те саме, що os_closed / os_filter / os_lock / isolation_probe еталона: таблиці — з gen_tables.py.

use crate::ast::Caps;
use crate::json::J;
use crate::lang;

/// Які групи закриває ядро: ті, жодного інструмента яких печатка не має.
pub fn closed(caps: &Caps) -> Vec<&'static str> {
    lang::OS_GROUPS
        .iter()
        .zip(lang::OS_OPENED_BY.iter())
        .filter(|(_, by)| !by.iter().any(|t| caps.get(t).is_some()))
        .map(|(g, _)| *g)
        .collect()
}

/// Програма seccomp-bpf — [(code, jt, jf, k)], як os_filter еталона.
pub fn filter(t: &lang::OsTable, closed: &[&str]) -> Vec<(u16, u8, u8, u32)> {
    const LD: u16 = 0x20;
    const JEQ: u16 = 0x15;
    const JGE: u16 = 0x35;
    const JSET: u16 = 0x45;
    const RET: u16 = 0x06;
    const ALLOW: u32 = 0x7FFF_0000;
    const KILL: u32 = 0x8000_0000;
    const ERRNO: u32 = 0x0005_0000;
    let mut p = vec![(LD, 0, 0, 4), (JEQ, 1, 0, t.audit), (RET, 0, 0, KILL), (LD, 0, 0, 0)];
    if t.x32 {
        p.push((JGE, 0, 1, 0x4000_0000));
        p.push((RET, 0, 0, KILL));
    }
    let mut deny: Vec<(u32, u32)> = t.always.iter().map(|&n| (n, 38)).collect();
    for (i, g) in lang::OS_GROUPS.iter().enumerate() {
        if closed.contains(g) {
            deny.extend(t.groups[i].iter().map(|&n| (n, 1)));
        }
    }
    let w = closed.contains(&"запис");
    if w {
        deny.extend(t.open2.iter().map(|&n| (n, 38)));
    }
    for (n, e) in deny {
        p.push((JEQ, 0, 1, n));
        p.push((RET, 0, 0, ERRNO | e));
    }
    if w {
        for &(n, a) in t.open {
            p.push((JEQ, 0, 4, n));
            p.push((LD, 0, 0, 16 + 8 * a));
            p.push((JSET, 0, 1, lang::OS_WRITE_FLAGS));
            p.push((RET, 0, 0, ERRNO | 1));
            p.push((RET, 0, 0, ALLOW));
        }
    }
    p.push((RET, 0, 0, ALLOW));
    p
}

extern "C" {
    fn prctl(option: i32, ...) -> i32;
    fn syscall(n: i64, ...) -> i64;
}

#[repr(C)]
struct Fprog {
    len: u16,
    filter: *const u8,
}

fn errno() -> i32 {
    std::io::Error::last_os_error().raw_os_error().unwrap_or(0)
}

fn none(why: String) -> Vec<(String, J)> {
    vec![("ядро".into(), J::s("немає")), ("причина".into(), J::Str(why)), ("закрито".into(), J::Arr(vec![]))]
}

/// Поставити замок на весь процес (TSYNC; успадковують і дочірні процеси) → поля події «ізоляція» (як в еталона).
pub fn lock(closed: &[&'static str]) -> Vec<(String, J)> {
    if closed.is_empty() {
        return vec![("ядро".into(), J::s("не потрібне")), ("закрито".into(), J::Arr(vec![]))];
    }
    if !cfg!(target_os = "linux") {
        return none("не Linux".into());
    }
    let arch = std::env::consts::ARCH;
    let t = match lang::OS_TABLES.iter().find(|t| t.arch == arch) {
        Some(t) => t,
        None => return none(format!("архітектура {} без таблиці замка", crate::uni::safe(arch))),
    };
    let prog = filter(t, closed);
    let mut raw = Vec::with_capacity(prog.len() * 8);
    for (c, jt, jf, k) in &prog {
        raw.extend_from_slice(&c.to_ne_bytes());
        raw.push(*jt);
        raw.push(*jf);
        raw.extend_from_slice(&k.to_ne_bytes());
    }
    let fp = Fprog { len: prog.len() as u16, filter: raw.as_ptr() };
    unsafe {
        if prctl(38, 1u64, 0u64, 0u64, 0u64) != 0 {
            // PR_SET_NO_NEW_PRIVS
            return none(format!("ядро відмовило (errno {})", errno()));
        }
        let mut r = syscall(t.seccomp, 1i64, 1i64, &fp as *const Fprog); // SET_MODE_FILTER, FILTER_FLAG_TSYNC
        if r != 0 {
            // без TSYNC фільтр ляже лише на цей потік: так — лише коли потік один (суд 11, Мовознавець)
            if std::fs::read_dir("/proc/self/task").map_or(0, |d| d.count()) != 1 {
                return none("TSYNC недоступний, а потоків більше одного — замок ліг би лише на один".into());
            }
            r = prctl(22, 2u64, &fp as *const Fprog as u64, 0u64, 0u64) as i64; // PR_SET_SECCOMP, MODE_FILTER
        }
        if r != 0 {
            return none(format!("ядро відмовило (errno {})", errno()));
        }
    }
    vec![("ядро".into(), J::s("seccomp")), ("закрито".into(), J::Arr(closed.iter().map(|g| J::s(g)).collect()))]
}

fn err_name(e: &std::io::Error) -> String {
    match e.raw_os_error() {
        Some(1) => "EPERM".into(),
        Some(n) => format!("errno {}", n),
        None => "дозволено".into(),
    }
}

/// Дитина проби: замок з усіма трьома групами, проби — рядками «ключ значення» у stdout (свій бінарник — свій протокол).
pub fn probe_child(dir: &str) -> i32 {
    let lk = lock(&lang::OS_GROUPS);
    let mut seccomp = false;
    for (k, v) in &lk {
        if let J::Str(s) = v {
            println!("{} {}", k, s);
            seccomp |= k == "ядро" && s == "seccomp";
        }
    }
    if seccomp {
        let net = match std::net::UdpSocket::bind("127.0.0.1:0") {
            Ok(_) => "дозволено".into(),
            Err(e) => err_name(&e),
        };
        println!("мережа {}", net);
        let wr = match std::fs::OpenOptions::new().write(true).create(true).open(format!("{}/спроба", dir)) {
            Ok(_) => "дозволено".into(),
            Err(e) => err_name(&e),
        };
        println!("запис {}", wr);
        let ex = match std::process::Command::new("/bin/sh").args(["-c", "exit 0"]).status() {
            Ok(_) => "дозволено".into(),
            Err(e) => err_name(&e),
        };
        println!("процеси {}", ex);
    }
    0
}

fn js(s: &str) -> String {
    crate::json::dumps(&J::s(s), false)
}

/// ngr --перевірити-ізоляцію: чи тримає ядро цієї машини замок — дочірній процес (цей самий бінарник) ставить замок і
/// пробує socket, запис файлу й exec. Код: 0 — тримає все, 1 — ні, 2 — замка немає. Вивід — як в еталона.
pub fn probe(as_json: bool) -> i32 {
    let dir = std::env::temp_dir().join(format!("ngr-ізоляція-{}", std::process::id()));
    let _ = std::fs::create_dir(&dir);
    let exe = std::env::current_exe().unwrap_or_else(|_| "/proc/self/exe".into());
    let out = std::process::Command::new(exe).arg("--перевірити-ізоляцію-дитина").arg(&dir).output();
    let _ = std::fs::remove_dir_all(&dir);
    let text = out.map(|o| String::from_utf8_lossy(&o.stdout).into_owned()).unwrap_or_default();
    let get = |k: &str| -> Option<String> {
        text.lines().find_map(|l| l.split_once(' ').filter(|(kk, _)| *kk == k).map(|(_, v)| v.to_string()))
    };
    let kernel = get("ядро");
    let why = get("причина");
    let held: Vec<(&str, String)> = if kernel.as_deref() == Some("seccomp") {
        lang::OS_GROUPS.iter().map(|g| (*g, get(g).unwrap_or_else(|| "дозволено".into()))).collect()
    } else {
        Vec::new()
    };
    let code = if held.is_empty() { 2 } else if held.iter().all(|(_, v)| v != "дозволено") { 0 } else { 1 };
    let arch = crate::uni::safe(std::env::consts::ARCH);
    if as_json {
        let opt = |x: &Option<String>| x.as_deref().map(js).unwrap_or_else(|| "null".into());
        let groups = if held.is_empty() {
            "{}".to_string()
        } else {
            format!("{{\n{}\n }}", held.iter().map(|(g, v)| format!("  {}: {}", js(g), js(v))).collect::<Vec<_>>().join(",\n"))
        };
        println!(
            "{{\n {}: {},\n {}: {},\n {}: {},\n {}: {},\n {}: {}\n}}",
            js("ядро"),
            opt(&kernel),
            js("причина"),
            opt(&why),
            js("архітектура"),
            js(&arch),
            js("групи"),
            groups,
            js("тримає"),
            if code == 0 { "true" } else { "false" }
        );
        return code;
    }
    if held.is_empty() {
        println!("✗ замка ОС на цій машині немає: {} — межі печатки тримає лише інтерпретатор", why.unwrap_or_else(|| "?".into()));
        return code;
    }
    println!(
        "замок ОС на цій машині: seccomp ({}) — {}",
        arch,
        if code == 0 { "ядро тримає всі три групи" } else { "ядро тримає НЕ все" }
    );
    for (g, v) in &held {
        let what = match *g {
            "мережа" => "socket()",
            "запис" => "відкрити файл на запис",
            _ => "exec /bin/sh",
        };
        let ok = v != "дозволено";
        println!(
            "  {} {}: {} → {}",
            if ok { "✓" } else { "✗" },
            g,
            what,
            if ok { format!("відмова ({})", v) } else { "ДОЗВОЛЕНО".into() }
        );
    }
    code
}
