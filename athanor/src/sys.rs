//! Шов між ядром і світом. Нативно — звичайні виклики ОС; у WebAssembly (Альбедо) ті самі виклики йдуть до господаря, який
//! сам вирішує за печаткою: модуль лише просить (spec/пропозиції/альбедо.md §2). Більше ядро нічого в ОС не бере.

#[cfg(not(target_arch = "wasm32"))]
mod imp {
    use std::io::{Read, Result};

    pub fn read_limited(path: &str, cap: usize) -> Result<Vec<u8>> {
        let mut bytes = Vec::new();
        std::fs::File::open(path)?.take(cap as u64).read_to_end(&mut bytes)?;
        Ok(bytes)
    }

    pub fn read_all(path: &str) -> Result<Vec<u8>> {
        std::fs::read(path)
    }

    pub fn write_file(dir: &str, path: &str, bytes: &[u8]) -> Result<()> {
        std::fs::create_dir_all(dir).and_then(|_| std::fs::write(path, bytes))
    }

    pub fn list_dir(path: &str) -> Result<Vec<String>> {
        let mut names = Vec::new();
        for e in std::fs::read_dir(path)? {
            names.push(e?.file_name().to_string_lossy().into_owned());
        }
        Ok(names)
    }

    pub fn exists(p: &str) -> bool {
        std::fs::metadata(p).is_ok()
    }

    pub fn isdir(p: &str) -> bool {
        std::fs::metadata(p).map(|m| m.is_dir()).unwrap_or(false)
    }

    pub fn isfile(p: &str) -> bool {
        std::fs::metadata(p).map(|m| m.is_file()).unwrap_or(false)
    }

    pub fn now_secs() -> i64 {
        std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0)
    }
}

#[cfg(target_arch = "wasm32")]
mod imp {
    use std::io::{Error, Result};

    #[link(wasm_import_module = "ngr")]
    extern "C" {
        fn fs(op: i32, p: *const u8, n: usize, q: *const u8, m: usize) -> i64; // довжина відповіді чи −errno
        fn fs_take(dst: *mut u8);
        fn now() -> i64; // секунди UTC; без права «час» — −1
    }

    const READ: i32 = 1;
    const WRITE: i32 = 2;
    const LIST: i32 = 3;
    const KIND: i32 = 4;
    const REALPATH: i32 = 5;

    fn call(op: i32, a: &[u8], b: &[u8]) -> Result<Vec<u8>> {
        let n = unsafe { fs(op, a.as_ptr(), a.len(), b.as_ptr(), b.len()) };
        if n < 0 {
            return Err(Error::from_raw_os_error(-n as i32));
        }
        let mut v: Vec<u8> = vec![0; n as usize];
        unsafe { fs_take(v.as_mut_ptr()) };
        Ok(v)
    }

    pub fn read_limited(path: &str, cap: usize) -> Result<Vec<u8>> {
        call(READ, path.as_bytes(), &(cap as u64).to_le_bytes())
    }

    pub fn read_all(path: &str) -> Result<Vec<u8>> {
        read_limited(path, usize::MAX >> 1)
    }

    pub fn write_file(_dir: &str, path: &str, bytes: &[u8]) -> Result<()> {
        call(WRITE, path.as_bytes(), bytes).map(|_| ())
    }

    pub fn list_dir(path: &str) -> Result<Vec<String>> {
        let v = call(LIST, path.as_bytes(), &[])?;
        Ok(String::from_utf8_lossy(&v).split('\0').filter(|s| !s.is_empty()).map(String::from).collect())
    }

    fn kind(p: &str) -> u8 {
        call(KIND, p.as_bytes(), &[]).ok().and_then(|v| v.first().copied()).unwrap_or(0) // 0 — немає, 1 — файл, 2 — тека
    }

    pub fn exists(p: &str) -> bool {
        kind(p) != 0
    }

    pub fn isdir(p: &str) -> bool {
        kind(p) == 2
    }

    pub fn isfile(p: &str) -> bool {
        kind(p) == 1
    }

    pub fn realpath(p: &str) -> String {
        call(REALPATH, p.as_bytes(), &[]).ok().and_then(|v| String::from_utf8(v).ok()).unwrap_or_else(|| p.to_string())
    }

    pub fn now_secs() -> i64 {
        unsafe { now() }
    }
}

pub use imp::*;
