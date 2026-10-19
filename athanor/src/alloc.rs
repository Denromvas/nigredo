//! Швидкий алокатор: класи розмірів до 1 КБ зі списками вільних блоків (системний malloc Android — Scudo —
//! коштує ~100–230 нс на блок, а виконавець створює значення й середовища на кожен виклик). Потік виконання
//! (власник) бере й повертає блоки без жодних атомарних операцій — свої списки; інші потоки (головний) — свої,
//! під замком. Блоки одного класу взаємозамінні, тож блок можна звільнити в будь-якому потоці. Більші блоки й
//! вирівнювання понад 16 — системному. Памʼять класів ОС не повертається (процес короткий).
use std::alloc::{GlobalAlloc, Layout, System};
use std::cell::UnsafeCell;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

const CLASSES: [usize; 20] = [16, 32, 48, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 448, 512, 640, 768, 896, 1024];
const MAX_SMALL: usize = 1024;
const SLAB: usize = 1 << 20;

struct Pool {
    free: [*mut u8; 20],
    bump: *mut u8,
    end: *mut u8,
}

impl Pool {
    const fn new() -> Pool {
        Pool { free: [std::ptr::null_mut(); 20], bump: std::ptr::null_mut(), end: std::ptr::null_mut() }
    }

    #[inline]
    unsafe fn take(&mut self, c: usize) -> *mut u8 {
        let head = self.free[c];
        if !head.is_null() {
            self.free[c] = *(head as *mut *mut u8);
            return head;
        }
        let sz = CLASSES[c];
        if self.bump.is_null() || (self.end as usize - self.bump as usize) < sz {
            let slab = System.alloc(Layout::from_size_align_unchecked(SLAB, 16));
            if slab.is_null() {
                return std::ptr::null_mut();
            }
            self.bump = slab;
            self.end = slab.add(SLAB);
        }
        let p = self.bump;
        self.bump = p.add(sz);
        p
    }

    #[inline]
    unsafe fn give(&mut self, c: usize, p: *mut u8) {
        *(p as *mut *mut u8) = self.free[c];
        self.free[c] = p;
    }
}

pub struct Fast {
    owner: AtomicUsize,
    mine: UnsafeCell<Pool>,
    lock: AtomicBool,
    others: UnsafeCell<Pool>,
}

unsafe impl Sync for Fast {}

#[inline(always)]
fn thread_ptr() -> usize {
    #[cfg(target_arch = "aarch64")]
    unsafe {
        let tp: usize;
        std::arch::asm!("mrs {}, tpidr_el0", out(reg) tp, options(nomem, nostack, preserves_flags));
        tp
    }
    #[cfg(target_arch = "x86_64")]
    unsafe {
        let tp: usize;
        std::arch::asm!("mov {}, fs:0", out(reg) tp, options(nostack, preserves_flags, readonly));
        tp
    }
    #[cfg(not(any(target_arch = "aarch64", target_arch = "x86_64")))]
    {
        0
    }
}

impl Fast {
    pub const fn new() -> Fast {
        Fast { owner: AtomicUsize::new(usize::MAX), mine: UnsafeCell::new(Pool::new()), lock: AtomicBool::new(false), others: UnsafeCell::new(Pool::new()) }
    }

    /// Поточний потік стає власником швидкого шляху (виклик — один раз, на початку потоку виконання).
    pub fn claim(&self) {
        let tp = thread_ptr();
        if tp != 0 {
            self.owner.store(tp, Ordering::Release);
        }
    }

    #[inline(always)]
    fn is_owner(&self) -> bool {
        let tp = thread_ptr();
        tp != 0 && self.owner.load(Ordering::Relaxed) == tp
    }

    fn lock(&self) {
        while self.lock.compare_exchange_weak(false, true, Ordering::Acquire, Ordering::Relaxed).is_err() {
            std::hint::spin_loop();
        }
    }

    fn unlock(&self) {
        self.lock.store(false, Ordering::Release);
    }
}

#[inline(always)]
fn class_of(size: usize) -> usize {
    if size <= 128 {
        (size.max(1) + 15) / 16 - 1
    } else {
        let mut i = 8;
        while CLASSES[i] < size {
            i += 1;
        }
        i
    }
}

unsafe impl GlobalAlloc for Fast {
    #[inline]
    unsafe fn alloc(&self, l: Layout) -> *mut u8 {
        if l.size() > MAX_SMALL || l.align() > 16 {
            return System.alloc(l);
        }
        let c = class_of(l.size());
        if self.is_owner() {
            return (*self.mine.get()).take(c);
        }
        self.lock();
        let p = (*self.others.get()).take(c);
        self.unlock();
        p
    }

    #[inline]
    unsafe fn dealloc(&self, p: *mut u8, l: Layout) {
        if l.size() > MAX_SMALL || l.align() > 16 {
            return System.dealloc(p, l);
        }
        let c = class_of(l.size());
        if self.is_owner() {
            return (*self.mine.get()).give(c, p);
        }
        self.lock();
        (*self.others.get()).give(c, p);
        self.unlock();
    }

    #[inline]
    unsafe fn realloc(&self, p: *mut u8, l: Layout, new_size: usize) -> *mut u8 {
        if l.align() <= 16 {
            if l.size() > MAX_SMALL && new_size > MAX_SMALL {
                return System.realloc(p, l, new_size);
            }
            if l.size() <= MAX_SMALL && new_size <= MAX_SMALL && class_of(l.size()) == class_of(new_size) {
                return p;
            }
        }
        let nl = Layout::from_size_align_unchecked(new_size, l.align());
        let np = self.alloc(nl);
        if !np.is_null() {
            std::ptr::copy_nonoverlapping(p, np, l.size().min(new_size));
            self.dealloc(p, l);
        }
        np
    }
}
