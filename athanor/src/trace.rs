//! Слід — як nigredo.Trace: JSONL, кожен запис підписано HMAC-SHA256 ключем власника і зчеплено з попереднім.
use crate::json::{dumps, J};
use crate::pyf;
use crate::sha;
use crate::uni;
use crate::value::{show, Val, V};
use std::collections::HashSet;
use std::io::Write;

pub struct Trace {
    pub outs: Vec<Box<dyn Write>>,
    pub stores: Vec<Box<dyn Write>>,
    key: Vec<u8>,
    prev: String,
    n: u64,
    kept: HashSet<String>,
    pub depth: i64,
    pub bytes: u64,
    pub limit: u64,
}

pub fn line_of(rec: &J) -> String {
    let line = dumps(rec, false);
    if line.contains(['\u{2028}', '\u{2029}', '\u{85}']) {
        line.replace('\u{2028}', "\\u2028").replace('\u{2029}', "\\u2029").replace('\u{85}', "\\u0085")
    } else {
        line
    }
}

/// trace_val: значення для сліду (невидиме — ⟨U+…⟩); довге — підсумком.
pub fn trace_val(x: &V, full: bool) -> crate::interp::R<J> {
    let s = uni::visible(&show(x, false)?, "\n\t", true);
    let n = s.chars().count();
    if full || n <= 4000 {
        return Ok(J::Str(s));
    }
    let start: String = s.chars().take(1000).collect();
    Ok(J::Obj(vec![
        ("підсумок".into(), J::Bool(true)),
        ("довжина".into(), J::Int(n as i64)),
        ("sha256".into(), J::Str(sha::sha256_hex(s.as_bytes()))),
        ("початок".into(), J::Str(start)),
    ]))
}

/// enc_v: точне кодування значення для сховища повтору.
pub fn enc_v(x: &V) -> J {
    let e = match &x.v {
        Val::Bool(b) => J::Bool(*b),
        Val::None => J::Null,
        Val::Str(s) => J::Str(s.s.to_string()),
        Val::Int(i) => J::Obj(vec![("ц".into(), J::Str(i.to_string()))]),
        Val::Dec(d) => J::Obj(vec![("д".into(), J::Str(d.to_sci()))]),
        Val::Float(f) => J::Obj(vec![("д".into(), J::Str(pyf::repr(*f)))]),
        Val::List(l) => J::Obj(vec![("л".into(), J::Arr(l.iter().map(enc_v).collect()))]),
        Val::Dict(d) => J::Obj(vec![(
            "с".into(),
            J::Arr(d.keys.iter().zip(&d.vals).map(|(k, v)| J::Arr(vec![J::Str(k.s.to_string()), enc_v(v)])).collect()),
        )]),
        Val::Fn(_) => J::Str("λ".into()),
    };
    if x.c == 1.0 && x.s == 1.0 {
        e
    } else {
        J::Obj(vec![("в".into(), J::Str(pyf::repr(x.c))), ("б".into(), J::Str(pyf::repr(x.s))), ("з".into(), e)])
    }
}

pub enum TraceErr {
    Fatal(String),
    Io(String),
}

impl Trace {
    pub fn new(outs: Vec<Box<dyn Write>>, stores: Vec<Box<dyn Write>>, key: Vec<u8>, limit: u64) -> Trace {
        Trace { outs, stores, key, prev: "0".repeat(16), n: 0, kept: HashSet::new(), depth: 0, bytes: 0, limit }
    }

    pub fn rec(&mut self, event: &str, data: Vec<(String, J)>) -> Result<(), TraceErr> {
        if self.bytes > self.limit && !matches!(event, "помилка" | "кінець" | "відмова") {
            return Err(TraceErr::Fatal(format!("слід перевищив {} байтів (--слід-розмір) — програму зупинено", self.limit)));
        }
        self.n += 1;
        let mut kv: Vec<(String, J)> = Vec::with_capacity(data.len() + 4);
        kv.push(("№".into(), J::Int(self.n as i64)));
        kv.push(("подія".into(), J::s(event)));
        kv.push(("глибина".into(), J::Int(self.depth)));
        for (k, v) in data {
            match kv.iter().position(|(x, _)| *x == k) {
                Some(i) => kv[i].1 = v,
                None => kv.push((k, v)),
            }
        }
        kv.push(("попередній".into(), J::Str(self.prev.clone())));
        let mut rec = J::Obj(kv);
        let body = dumps(&rec, true);
        let h = sha::hex(&sha::hmac_sha256(&self.key, body.as_bytes()))[..16].to_string();
        if let J::Obj(kv) = &mut rec {
            kv.push(("хеш".into(), J::Str(h.clone())));
        }
        self.prev = h;
        let line = line_of(&rec) + "\n";
        self.bytes += line.len() as u64;
        for o in self.outs.iter_mut() {
            o.write_all(line.as_bytes()).map_err(|e| TraceErr::Io(e.to_string()))?;
            o.flush().map_err(|e| TraceErr::Io(e.to_string()))?;
        }
        Ok(())
    }

    /// keep: точне значення — у сховище (раз на вміст); повертає sha256 для запису в слід.
    pub fn keep(&mut self, x: &V) -> Result<String, TraceErr> {
        let e = enc_v(x);
        let h = sha::sha256_hex(dumps(&e, true).as_bytes());
        if !self.kept.contains(&h) && !self.stores.is_empty() {
            self.kept.insert(h.clone());
            let line = dumps(&J::Obj(vec![("sha256".into(), J::Str(h.clone())), ("значення".into(), e)]), false) + "\n";
            self.bytes += line.len() as u64;
            if self.bytes > self.limit {
                return Err(TraceErr::Fatal(format!("слід перевищив {} байтів (--слід-розмір) — програму зупинено", self.limit)));
            }
            for o in self.stores.iter_mut() {
                o.write_all(line.as_bytes()).map_err(|e| TraceErr::Io(e.to_string()))?;
                o.flush().map_err(|e| TraceErr::Io(e.to_string()))?;
            }
        }
        Ok(h)
    }
}
