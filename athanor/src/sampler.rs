//! Вибірковий профайлер для розробки (ATHANOR_SAMPLE=файл): SIGPROF раз на 0,25 мс, PC з контексту сигналу —
//! у буфер; наприкінці адреси пишуться у файл (символи — athanor/профіль.py через nm). Лише aarch64 Linux.
use std::sync::atomic::{AtomicUsize, Ordering};

const N: usize = 1 << 20;
static mut PCS: [usize; N] = [0; N];
static COUNT: AtomicUsize = AtomicUsize::new(0);

#[repr(C)]
struct ItimerVal {
    iv_sec: i64,
    iv_usec: i64,
    v_sec: i64,
    v_usec: i64,
}

#[repr(C)]
struct SigAction {
    handler: usize,
    mask: [u64; 16],
    flags: i32,
    restorer: usize,
}

extern "C" {
    fn setitimer(which: i32, new: *const ItimerVal, old: *mut ItimerVal) -> i32;
    fn sigaction(sig: i32, act: *const SigAction, old: *mut SigAction) -> i32;
}

extern "C" fn on_prof(_sig: i32, _info: usize, uctx: *const u8) {
    #[cfg(target_arch = "aarch64")]
    unsafe {
        let pc = *(uctx.add(440) as *const usize);
        let i = COUNT.fetch_add(1, Ordering::Relaxed);
        if i < N {
            PCS[i] = pc;
        }
    }
}

pub fn start() {
    unsafe {
        let act = SigAction { handler: on_prof as usize, mask: [0; 16], flags: 4 /* SA_SIGINFO */ | 0x10000000 /* SA_RESTART */, restorer: 0 };
        sigaction(27 /* SIGPROF */, &act, std::ptr::null_mut());
        let t = ItimerVal { iv_sec: 0, iv_usec: 250, v_sec: 0, v_usec: 250 };
        setitimer(2 /* ITIMER_PROF */, &t, std::ptr::null_mut());
    }
}

pub fn finish(path: &str) {
    unsafe {
        let t = ItimerVal { iv_sec: 0, iv_usec: 0, v_sec: 0, v_usec: 0 };
        setitimer(2, &t, std::ptr::null_mut());
        let n = COUNT.load(Ordering::Relaxed).min(N);
        let mut s = String::new();
        for i in 0..n {
            s.push_str(&format!("{:x}\n", PCS[i]));
        }
        let _ = std::fs::write(path, s);
    }
}
