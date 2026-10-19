//! Атанор — нативний виконавець Nigredo. Еталон мови — interpreter/nigredo.py: те, чого Атанор не вміє (або програму
//! з помилкою до запуску), він віддає еталону ще до будь-якої дії (exec того самого процесу з тими самими аргументами).
mod alloc;
mod ast;
mod dec;
mod int;
mod interp;
mod json;
mod lang;
mod lexer;
mod nat;
mod parser;
mod pathx;
mod prims;
mod prims2;
mod pyf;
mod rng;
mod sampler;
mod seal;
mod sha;
mod sort;
mod tables;
mod tools;
mod trace;
mod types;
mod uni;
mod value;

use crate::json::J;
use crate::lexer::Back;
use std::io::{BufRead, Write};
use std::os::unix::process::CommandExt;
use std::rc::Rc;

#[global_allocator]
static GLOBAL: alloc::Fast = alloc::Fast::new();

const SOURCE_SHA: &str = env!("ATHANOR_SOURCE_SHA");

/// Гліфи, які Атанор виконує сам (решта — еталон: XML, регулярки, дати, CSV, схеми, паралельні виклики).
fn glyph_ok(g: char) -> bool {
    !matches!(g, '‖' | 'χ' | '↘' | '⌕' | '≋' | '▦' | '✓' | '◷')
}

thread_local! {
    static BACK: std::cell::RefCell<Option<String>> = const { std::cell::RefCell::new(None) };
}

/// Віддати запуск еталону — з головного потоку (exec із потоку виконання в proot падає).
struct HandOver(String);

fn hand_over(why: &str) -> ! {
    std::panic::panic_any(HandOver(why.to_string()))
}

/// exec еталона: той самий процес, ті самі аргументи.
fn exec_reference(why: &str) -> ! {
    if std::env::var_os("ATHANOR_WHY").is_some() {
        eprintln!("атанор → еталон: {}", why);
    }
    if std::env::var_os("ATHANOR_NO_FALLBACK").is_some() {
        eprintln!("атанор: не виконую сам ({})", why);
        std::process::exit(120);
    }
    let py = reference_path();
    let args: Vec<std::ffi::OsString> = std::env::args_os().skip(1).collect();
    let err = std::process::Command::new("python3").arg(&py).args(&args).exec();
    eprintln!("✗ атанор: не вдалося запустити еталон python3 {}: {}", py, err);
    std::process::exit(4);
}

fn reference_path() -> String {
    if let Ok(p) = std::env::var("NIGREDO_PY") {
        return p;
    }
    // тека збірки (athanor/) → interpreter/ngr.py поруч; /proc/self/exe у proot показує не той файл
    let built = pathx::join(&pathx::dirname(env!("CARGO_MANIFEST_DIR")), "interpreter/ngr.py");
    if pathx::exists(&built) {
        return built;
    }
    let exe = std::env::args().next().unwrap_or_default();
    let real = pathx::realpath(&exe);
    pathx::join(&pathx::dirname(&pathx::dirname(&pathx::dirname(&pathx::dirname(&real)))), "interpreter/ngr.py")
}

struct Opts {
    trace: Option<String>,
    seed: String,
    steps: i64,
    size: u64,
    tsize: u64,
    dir: Option<String>,
    src: Option<String>,
    raw: Option<Vec<u8>>,
    path: Option<String>,
    args: Vec<String>,
}

fn parse_args() -> Result<Opts, String> {
    let mut o = Opts {
        trace: None,
        seed: "0".into(),
        steps: lang::DEFAULT_STEPS as i64,
        size: lang::MAX_SIZE,
        tsize: lang::MAX_TRACE,
        dir: None,
        src: None,
        raw: None,
        path: None,
        args: Vec::new(),
    };
    let mut raw: Vec<String> = Vec::new();
    for a in std::env::args_os().skip(1) {
        match a.into_string() {
            Ok(s) => raw.push(s),
            Err(_) => return Err("аргумент — не UTF-8".into()),
        }
    }
    let mut it = raw.into_iter();
    let int_arg = |v: Option<String>| -> Result<String, String> {
        let v = v.ok_or("бракує значення")?;
        let t = v.trim();
        let ok = !t.is_empty() && t.trim_start_matches(['-', '+']).bytes().all(|c| c.is_ascii_digit()) && t.len() < 18;
        if ok { Ok(t.to_string()) } else { Err("не ціле".into()) }
    };
    while let Some(a) = it.next() {
        match a.as_str() {
            "--" => {
                o.args = it.collect();
                break;
            }
            "--слід" => o.trace = Some(it.next().ok_or("бракує значення")?),
            "--зерно" => o.seed = int_arg(it.next())?,
            "--кроки" => o.steps = int_arg(it.next())?.parse().map_err(|_| "кроки")?,
            "--розмір" => {
                let v: i64 = int_arg(it.next())?.parse().map_err(|_| "розмір")?;
                if v < 0 {
                    return Err("розмір".into());
                }
                o.size = v as u64;
            }
            "--слід-розмір" => {
                let v: i64 = int_arg(it.next())?.parse().map_err(|_| "слід-розмір")?;
                if v < 0 {
                    return Err("слід-розмір".into());
                }
                o.tsize = v as u64;
            }
            "--тека" => o.dir = Some(pathx::realpath(&it.next().ok_or("бракує значення")?)),
            "-e" => {
                o.src = Some(it.next().ok_or("бракує значення")?);
                o.path = Some("<-e>".into());
            }
            x if x.starts_with('-') && x != "-" => return Err(format!("режим {} — еталон", x)),
            _ => {
                if o.src.is_some() {
                    return Err("зайвий аргумент".into());
                }
                let raw = std::fs::read(&a).map_err(|_| "файл")?;
                let src = String::from_utf8(raw.clone()).map_err(|_| "не UTF-8")?;
                o.src = Some(src);
                o.raw = Some(raw);
                o.path = Some(a);
            }
        }
    }
    if o.src.is_none() {
        return Err("немає програми".into());
    }
    Ok(o)
}

fn rand_hex(n: usize) -> String {
    let mut b = vec![0u8; n];
    if let Ok(mut f) = std::fs::File::open("/dev/urandom") {
        let _ = std::io::Read::read_exact(&mut f, &mut b);
    }
    sha::hex(&b)
}

fn owner_key(home: &str) -> std::io::Result<Vec<u8>> {
    use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt};
    std::fs::DirBuilder::new().recursive(true).mode(0o700).create(home)?;
    let path = pathx::join(home, "ключ");
    if !pathx::exists(&path) {
        let mut f = std::fs::OpenOptions::new().write(true).create_new(true).mode(0o600).open(&path)?;
        f.write_all(rand_hex(32).as_bytes())?;
    }
    let k = std::fs::read_to_string(&path)?;
    Ok(uni::strip(&k).as_bytes().to_vec())
}

fn run() -> i32 {
    GLOBAL.claim();
    let o = match parse_args() {
        Ok(o) => o,
        Err(why) => hand_over(&why),
    };
    let src = o.src.clone().unwrap();
    let path = o.path.clone().unwrap();
    let is_e = path == "<-e>";
    let (cwd, dir_rights) = if is_e {
        (o.dir.clone().unwrap_or_else(pathx::getcwd), o.dir.is_some())
    } else {
        (pathx::dirname(&pathx::abspath(&path)), true)
    };
    // розбір і перевірки до запуску: будь-що незвичне — еталон
    let parsed = (|| -> Result<(ast::Node, Rc<ast::Caps>), Back> {
        let toks = lexer::lex(&src)?;
        lexer::check_twins(&toks)?;
        let mut p = parser::Parser::new(toks, tools::supported, glyph_ok);
        let prog = p.program()?;
        if types::has_type_errors(&prog) {
            return lexer::back("помилки типів");
        }
        Ok((prog, p.seal_caps().unwrap_or_default()))
    })();
    let (prog, seal_caps) = match parsed {
        Ok(x) => x,
        Err(Back(why)) => hand_over(&why),
    };
    let home = seal::owner_home();
    let prog_real = if dir_rights { Some(pathx::realpath(if is_e { &cwd } else { &path })) } else { None };
    let allowed = match seal::load_allowlist(&home, if dir_rights { Some(&cwd) } else { None }, prog_real.as_deref()) {
        Ok(a) => a,
        Err(Back(why)) => hand_over(&why),
    };
    if let Err(Back(why)) = seal::load_allowlist(&home, None, None) {
        hand_over(&why);
    }
    match seal::program_ok(&prog, &seal_caps, &allowed, &cwd, &home) {
        Ok(true) => {}
        Ok(false) => hand_over("печатка поза дозволами власника"),
        Err(Back(why)) => hand_over(&why),
    }
    let sha = sha::sha256_hex(if is_e { src.as_bytes() } else { o.raw.as_deref().unwrap() });
    // сліди: перевірити все до створення файлів
    let mut extra: Option<String> = None;
    let extra_stderr = o.trace.as_deref() == Some("-");
    if let Some(t) = &o.trace {
        if t != "-" {
            let tp = pathx::realpath(t);
            let mut scopes = Vec::new();
            for (tool, ws) in &seal_caps.tools {
                if tool.starts_with("файл.") {
                    for w in ws {
                        scopes.push(pathx::realpath(&pathx::join(&cwd, w)));
                    }
                }
            }
            if pathx::inside(&tp, &home) || scopes.iter().any(|w| pathx::inside(&tp, w)) {
                hand_over("слід у теці власника чи печатки");
            }
            if pathx::exists(&tp) || pathx::exists(&format!("{}.дані", tp)) || !pathx::isdir(&pathx::dirname(&tp)) {
                hand_over("файл сліду вже існує чи теки немає");
            }
            extra = Some(tp);
        }
    }
    let key = match owner_key(&home) {
        Ok(k) => k,
        Err(_) => hand_over("ключ власника"),
    };
    {
        use std::os::unix::fs::DirBuilderExt;
        if std::fs::DirBuilder::new().recursive(true).mode(0o700).create(pathx::join(&home, "сліди")).is_err() {
            hand_over("тека слідів");
        }
    }
    let (y, mo, d, h, mi, s) = tools::utc_now();
    let stamp = format!("{:04}{:02}{:02}-{:02}{:02}{:02}", y, mo, d, h, mi, s);
    let main_trace = pathx::join(&pathx::join(&home, "сліди"), &format!("{}-{}-{}.jsonl", stamp, &sha[..8], std::process::id()));
    let mut paths = vec![main_trace.clone()];
    if let Some(x) = &extra {
        paths.push(x.clone());
    }
    let mut outs: Vec<Box<dyn Write>> = Vec::new();
    let mut stores: Vec<Box<dyn Write>> = Vec::new();
    for tp in &paths {
        match std::fs::OpenOptions::new().write(true).create_new(true).open(tp) {
            Ok(f) => outs.push(Box::new(f)),
            Err(e) => {
                eprintln!("✗ не вдалося створити слід: {}", e);
                return 3;
            }
        }
    }
    if extra_stderr {
        outs.push(Box::new(std::io::stderr()));
    }
    for tp in &paths {
        match std::fs::OpenOptions::new().write(true).create_new(true).open(format!("{}.дані", tp)) {
            Ok(f) => stores.push(Box::new(f)),
            Err(e) => {
                eprintln!("✗ не вдалося створити сховище значень сліду: {}", e);
                return 3;
            }
        }
    }
    let code = execute(&o, &prog, &src, &path, &cwd, &sha, &allowed, outs, stores, &paths, &home, key);
    if let Ok(f) = std::env::var("NIGREDO_TRACE_PATH_FILE") {
        if !f.is_empty() {
            let _ = std::fs::write(&f, &main_trace);
        }
    }
    code
}

#[allow(clippy::too_many_arguments)]
fn execute(
    o: &Opts,
    prog: &ast::Node,
    src: &str,
    path: &str,
    cwd: &str,
    sha: &str,
    allowed: &seal::Allowed,
    outs: Vec<Box<dyn Write>>,
    stores: Vec<Box<dyn Write>>,
    paths: &[String],
    home: &str,
    key: Vec<u8>,
) -> i32 {
    let tr = trace::Trace::new(outs, stores, key, o.tsize);
    let seed = int::Int::from_dec(o.seed.starts_with('-'), o.seed.trim_start_matches(['-', '+']).trim_start_matches('0'));
    let seed = if o.seed.trim_start_matches(['-', '+']).trim_start_matches('0').is_empty() { int::Int::S(0) } else { seed };
    let mut it = interp::Interp {
        trace: tr,
        rng: rng::Mt::seed(&seed),
        argv: o.args.clone(),
        protected: paths.to_vec(),
        max_size: o.size,
        alloc: 0,
        steps_left: o.steps,
        cwd: cwd.to_string(),
        out: Box::new(std::io::stdout()),
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
        ends: 0,
        quota_stack: Vec::new(),
        quota_used: Default::default(),
        quota_seq: 0,
        owner_home: home.to_string(),
        paths_seen: None,
        denied: false,
        prof: if std::env::var_os("ATHANOR_PROFILE").is_some() { Some(Default::default()) } else { None },
    };
    let mut head = vec![
        ("версія".to_string(), J::s(lang::VERSION)),
        ("інтерпретатор".into(), J::Str(format!("атанор:{}", SOURCE_SHA))),
        ("програма".into(), J::Str(uni::safe(path))),
        ("sha256".into(), J::s(sha)),
        ("аргументи".into(), J::Arr(o.args.iter().map(|a| J::s(a)).collect())),
        ("час".into(), J::Str(tools::iso_now())),
        ("запуск".into(), J::Str(rand_hex(6))),
        ("тека".into(), J::Str(uni::safe(cwd))),
        ("дозволи_власника".into(), J::Str(uni::safe(&allowed.source))),
        ("дозволено".into(), J::Arr(allowed.items.iter().map(|a| J::s(a)).collect())),
        (
            "ліміти".into(),
            J::Obj(vec![
                ("кроки".into(), J::Int(o.steps)),
                ("розмір".into(), J::Int(o.size as i64)),
                ("слід".into(), J::Int(o.tsize as i64)),
                ("зерно".into(), J::Num(o.seed.trim_start_matches('+').to_string())),
            ]),
        ),
    ];
    if path == "<-e>" {
        head.push(("код".into(), J::s(src)));
    }
    if it.rec("початок", head).is_err() {
        return 4;
    }
    // квоти власника — на весь запуск (кілька на те саме — діє менша)
    let mut oq: Vec<((String, String), u64)> = Vec::new();
    for (t, sc, q) in &allowed.quotas {
        match oq.iter_mut().find(|(k, _)| k.0 == *t && k.1 == *sc) {
            Some((_, v)) => *v = (*v).min(*q),
            None => oq.push(((t.clone(), sc.clone()), *q)),
        }
    }
    if !oq.is_empty() {
        it.quota_stack.push(Rc::new(interp::QuotaTable { who: "власник".into(), quotas: oq, tok: "власник".into() }));
    }
    let root = value::Env::new(0, None);
    let t_all = std::time::Instant::now();
    let result = it.eval(prog, &root);
    if let Some(p) = &it.prof {
        let mut v: Vec<_> = p.iter().collect();
        v.sort_by(|a, b| b.1 .1.cmp(&a.1 .1));
        eprintln!("профіль: усього {:?}", t_all.elapsed());
        for (k, (n, d)) in v.iter().take(25) {
            eprintln!("  {:10} {:8} разів {:?}", k, n, d);
        }
    }
    match result {
        Ok(_) => {
            let steps = o.steps - it.steps_left;
            if it.rec("кінець", vec![("кроків".into(), J::Int(steps))]).is_err() {
                return 4;
            }
            0
        }
        Err(e) if e.pipe => {
            if let Ok(f) = std::fs::OpenOptions::new().write(true).open("/dev/null") {
                use std::os::unix::io::AsRawFd;
                extern "C" {
                    fn dup2(a: i32, b: i32) -> i32;
                }
                unsafe {
                    dup2(f.as_raw_fd(), 1);
                }
            }
            let _ = it.rec("помилка", vec![("повідомлення".into(), J::s("вивід обірвано: читач закрив трубу"))]);
            1
        }
        Err(e) => {
            let text = uni::safe(&e.text());
            let _ = it.rec("помилка", vec![("повідомлення".into(), J::Str(text.clone()))]);
            eprintln!("{}", text);
            1
        }
    }
}

/// Проба для звірки з Python: рядок «операція аргументи…» → результат (athanor/проба.py).
fn probe() {
    use dec::*;
    let stdin = std::io::stdin();
    let mut out = std::io::BufWriter::new(std::io::stdout());
    for line in stdin.lock().lines() {
        let line = line.unwrap();
        let p: Vec<&str> = line.split(' ').collect();
        let d = |s: &str| Dec::parse(s).unwrap();
        let i = |s: &str| {
            let (neg, digits) = if let Some(r) = s.strip_prefix('-') { (true, r) } else { (false, s) };
            int::Int::from_dec(neg, digits)
        };
        let ctx = |s: &str| -> Ctx {
            match s {
                "exact" => exact_ctx(),
                "wide" => wide_ctx(),
                _ => {
                    let mut c = dec_ctx();
                    c.prec = s.parse().unwrap();
                    c
                }
            }
        };
        let res = |r: Result<Dec, u32>| match r {
            Ok(x) => x.to_sci(),
            Err(s) => format!("ERR:{}", signal_name(s)),
        };
        let r = match p[0] {
            "add" => res(d(p[2]).add(&d(p[3]), &ctx(p[1]))),
            "sub" => res(d(p[2]).sub(&d(p[3]), &ctx(p[1]))),
            "mul" => res(d(p[2]).mul(&d(p[3]), &ctx(p[1]))),
            "div" => res(d(p[2]).div(&d(p[3]), &ctx(p[1]))),
            "rem" => res(d(p[2]).rem(&d(p[3]), &ctx(p[1]))),
            "quant" => res(d(p[1]).quantize(-p[2].parse::<i64>().unwrap(), Round::HalfUp, &wide_ctx())),
            "fixed" => d(p[1]).to_fixed(),
            "sci" => d(p[1]).to_sci(),
            "floor" => d(p[1]).floor().to_string(),
            "trunc" => d(p[1]).trunc().to_string(),
            "integral" => d(p[1]).is_integral().to_string(),
            "adj" => d(p[1]).adjusted().to_string(),
            "cmp" => format!("{:?}", d(p[1]).cmp(&d(p[2]))),
            "parse" => match Dec::parse(p[1]) {
                Ok(x) => x.to_sci(),
                Err(true) => "NONFINITE".into(),
                Err(false) => "BAD".into(),
            },
            "iadd" => i(p[1]).add(&i(p[2])).to_string(),
            "isub" => i(p[1]).sub(&i(p[2])).to_string(),
            "imul" => i(p[1]).mul(&i(p[2])).to_string(),
            "idivmod" => {
                let (q, r) = i(p[1]).divmod(&i(p[2]));
                format!("{} {}", q.to_string(), r.to_string())
            }
            "icmp" => format!("{:?}", i(p[1]).cmp(&i(p[2]))),
            "ibits" => i(p[1]).bit_length().to_string(),
            "frepr" => pyf::repr(f64::from_bits(p[1].parse::<u64>().unwrap())),
            "fround" => pyf::repr(pyf::round(f64::from_bits(p[1].parse::<u64>().unwrap()), p[2].parse().unwrap())),
            "fdec" => Dec::from_f64(f64::from_bits(p[1].parse::<u64>().unwrap())).to_sci(),
            "dfloat" => pyf::repr(d(p[1]).to_f64()),
            "sha" => sha::sha256_hex(p[1].as_bytes()),
            "hmac" => sha::hex(&sha::hmac_sha256(p[1].as_bytes(), p[2].as_bytes())),
            _ => "?".into(),
        };
        writeln!(out, "{}", r).unwrap();
    }
}

fn main() {
    if std::env::args().nth(1).as_deref() == Some("--проба") {
        probe();
        return;
    }
    if std::env::args().nth(1).as_deref() == Some("--заміри") {
        GLOBAL.claim();
        let t = std::time::Instant::now();
        let mut v = Vec::with_capacity(200_000);
        let mut i = int::Int::S(1);
        for _ in 0..200_000 {
            v.push(value::V::new(value::Val::Int(i.clone()), 1.0));
            i = i.add(&int::Int::S(1));
        }
        eprintln!("200k V: {:?}", t.elapsed());
        let t = std::time::Instant::now();
        drop(v);
        eprintln!("drop: {:?}", t.elapsed());
        let t = std::time::Instant::now();
        let mut e = Vec::new();
        for _ in 0..200_000 {
            e.push(value::Env::new(1, None));
        }
        eprintln!("200k Env: {:?}", t.elapsed());
        let t = std::time::Instant::now();
        let mut b = Vec::new();
        for i in 0..200_000u64 {
            b.push(Box::new(i));
        }
        eprintln!("200k Box (утримано): {:?}", t.elapsed());
        let t = std::time::Instant::now();
        for i in 0..200_000u64 {
            let x = std::hint::black_box(Box::new(i));
            drop(x);
        }
        eprintln!("200k Box (одразу звільнено): {:?}", t.elapsed());
        let t = std::time::Instant::now();
        let mut r = Vec::new();
        for _ in 0..200_000 {
            r.push(std::rc::Rc::new(std::cell::RefCell::new(vec![value::V::none()])));
        }
        eprintln!("200k Rc<RefCell<Vec<V>>>: {:?}", t.elapsed());
        return;
    }
    // глибока рекурсія мови — у потоці з великим стеком (як у еталона)
    std::panic::set_hook(Box::new(|info| {
        if info.payload().downcast_ref::<HandOver>().is_none() {
            eprintln!("✗ внутрішня помилка Атанора: {}", info);
        }
    }));
    let sample = std::env::var("ATHANOR_SAMPLE").ok();
    if sample.is_some() {
        sampler::start();
    }
    let h = std::thread::Builder::new().stack_size(1 << 29).spawn(run).expect("потік");
    let code = match h.join() {
        Ok(c) => c,
        Err(p) => match p.downcast::<HandOver>() {
            Ok(h) => exec_reference(&h.0),
            Err(_) => 4,
        },
    };
    let _ = BACK.with(|b| b.borrow().clone());
    if let Some(p) = sample {
        sampler::finish(&p);
    }
    let _ = std::io::stdout().flush();
    std::process::exit(code);
}
