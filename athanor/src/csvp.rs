//! CSV — як csv.reader(io.StringIO(text), strict=True) Python 3.13 (діалект excel): скінченний автомат з
//! Modules/_csv.c дослівно; рядки джерела — як у StringIO (ділення лише за \n, \n лишається в рядку).

#[derive(PartialEq, Clone, Copy)]
enum St {
    StartRecord,
    StartField,
    InField,
    InQuotedField,
    QuoteInQuotedField,
    EatCrnl,
}

const EOL: u32 = u32::MAX - 1;

struct P {
    st: St,
    field: String,
    field_len: usize,
    fields: Vec<String>,
    limit: usize,
}

impl P {
    fn save(&mut self) {
        self.fields.push(std::mem::take(&mut self.field));
        self.field_len = 0;
    }
    fn add(&mut self, c: char) -> Result<(), String> {
        if self.field_len >= self.limit {
            return Err(format!("field larger than field limit ({})", self.limit));
        }
        self.field.push(c);
        self.field_len += 1;
        Ok(())
    }
    fn ch(&mut self, c: u32) -> Result<(), String> {
        let is_nl = c == '\n' as u32 || c == '\r' as u32;
        let chr = || char::from_u32(c).unwrap();
        loop {
            match self.st {
                St::StartRecord => {
                    if c == EOL {
                        return Ok(());
                    }
                    if is_nl {
                        self.st = St::EatCrnl;
                        return Ok(());
                    }
                    self.st = St::StartField;
                    continue;
                }
                St::StartField => {
                    if is_nl || c == EOL {
                        self.save();
                        self.st = if c == EOL { St::StartRecord } else { St::EatCrnl };
                    } else if c == '"' as u32 {
                        self.st = St::InQuotedField;
                    } else if c == ',' as u32 {
                        self.save();
                    } else {
                        self.add(chr())?;
                        self.st = St::InField;
                    }
                    return Ok(());
                }
                St::InField => {
                    if is_nl || c == EOL {
                        self.save();
                        self.st = if c == EOL { St::StartRecord } else { St::EatCrnl };
                    } else if c == ',' as u32 {
                        self.save();
                        self.st = St::StartField;
                    } else {
                        self.add(chr())?;
                    }
                    return Ok(());
                }
                St::InQuotedField => {
                    if c == EOL {
                    } else if c == '"' as u32 {
                        self.st = St::QuoteInQuotedField;
                    } else {
                        self.add(chr())?;
                    }
                    return Ok(());
                }
                St::QuoteInQuotedField => {
                    if c == '"' as u32 {
                        self.add('"')?;
                        self.st = St::InQuotedField;
                    } else if c == ',' as u32 {
                        self.save();
                        self.st = St::StartField;
                    } else if is_nl || c == EOL {
                        self.save();
                        self.st = if c == EOL { St::StartRecord } else { St::EatCrnl };
                    } else {
                        return Err("',' expected after '\"'".into());
                    }
                    return Ok(());
                }
                St::EatCrnl => {
                    if is_nl {
                    } else if c == EOL {
                        self.st = St::StartRecord;
                    } else {
                        return Err("символ нового рядка посеред поля без лапок (рядки, розділені самим \\r?) — рядки CSV діліть \\n чи \\r\\n".into());
                    }
                    return Ok(());
                }
            }
        }
    }
}

/// Усі записи (порожній рядок джерела — порожній запис); Err — текст csv.Error.
pub fn read(text: &str, limit: usize) -> Result<Vec<Vec<String>>, String> {
    let mut lines = text.split_inclusive('\n');
    let mut out = Vec::new();
    let mut p = P { st: St::StartRecord, field: String::new(), field_len: 0, fields: Vec::new(), limit };
    loop {
        // один запис (може охоплювати кілька рядків джерела — у лапках)
        p.fields.clear();
        p.field.clear();
        p.field_len = 0;
        p.st = St::StartRecord;
        loop {
            let line = match lines.next() {
                None => {
                    if p.field_len != 0 || p.st == St::InQuotedField {
                        return Err("unexpected end of data".into());
                    }
                    return Ok(out);
                }
                Some(l) => l,
            };
            for c in line.chars() {
                p.ch(c as u32)?;
            }
            p.ch(EOL)?;
            if p.st == St::StartRecord {
                break;
            }
        }
        out.push(std::mem::take(&mut p.fields));
    }
}
