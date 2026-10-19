// Хеш джерел Атанора — у слід («інтерпретатор»: яким кодом зроблено запуск).
use std::io::Read;

fn main() {
    let mut files: Vec<_> = std::fs::read_dir("src").unwrap().map(|e| e.unwrap().path()).collect();
    files.sort();
    files.push("Cargo.toml".into());
    let mut all = Vec::new();
    for f in &files {
        println!("cargo:rerun-if-changed={}", f.display());
        let mut b = Vec::new();
        std::fs::File::open(f).unwrap().read_to_end(&mut b).unwrap();
        all.extend_from_slice(f.to_string_lossy().as_bytes());
        all.push(0);
        all.extend_from_slice(&b);
        all.push(0);
    }
    // FNV-1a ×4 (збірка без залежностей); це відбиток джерел, не підпис
    let mut out = String::new();
    for seed in 0..4u64 {
        let mut h: u64 = 0xcbf29ce484222325 ^ seed.wrapping_mul(0x9E3779B97F4A7C15);
        for &x in &all {
            h ^= x as u64;
            h = h.wrapping_mul(0x100000001b3);
        }
        out.push_str(&format!("{:016x}", h));
    }
    println!("cargo:rustc-env=ATHANOR_SOURCE_SHA={}", out);
}
