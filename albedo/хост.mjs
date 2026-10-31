// Альбедо, господар (spec/пропозиції/альбедо.md §2). Довірена база: модуль WASM нічого не може без цих функцій.
// Три правила: печатку читає господар, а не модуль; кожна дія перевіряється тут; ключ сліду лишається тут.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { Worker, isMainThread, workerData } from 'node:worker_threads';
import { fileURLToPath } from 'node:url';

// Два потоки: модуль — у своєму, цей лише стежить за строком: модуль, що крутиться вічно, себе не зупинить, а кроки рахує він сам.
const W = isMainThread ? null : workerData;
const rawArgs = (W ? W.argv : process.argv).slice(2);
const dd = rawArgs.indexOf('--');          // що після «--», належить програмі: це не прапорці господаря
const args = dd < 0 ? rawArgs : rawArgs.slice(0, dd), progArgs = dd < 0 ? [] : rawArgs.slice(dd + 1);
const opt = (k, d) => { const i = args.indexOf(k); if (i < 0) return d; const v = args[i + 1]; args.splice(i, 2); return v; };
const flag = (k) => { const i = args.indexOf(k); if (i < 0) return false; args.splice(i, 1); return true; };
const extraTrace = opt('--слід', null), seed = opt('--зерно', '0'), steps = opt('--кроки', '10000000');
const size = opt('--розмір', '5000000'), tsize = opt('--слід-розмір', '50000000'), dbLimit = Number(opt('--бд-запис', String(2 ** 30)));
const deadline = Number(opt('--строк', '300')), memMb = Number(opt('--памʼять', '1024'));   // с, МБ: тримає господар, а не модуль
const showImports = flag('--імпорти'), showTime = flag('--час');
const [wasmPath, progPath] = args;
const wasmBytes = fs.readFileSync(wasmPath);
const mod = new WebAssembly.Module(wasmBytes);
if (showImports) { for (const i of WebAssembly.Module.imports(mod)) console.log(`${i.module}.${i.name}`); process.exit(0); }

const fail = (code, msg) => { fs.writeSync(2, msg + '\n'); process.exit(code); };
// памʼять дає господар і стелю ставить він: модуль зі своєю памʼяттю не запускається
const KNOWN = new Set(['env.memory', 'ngr.out', 'ngr.err', 'ngr.body', 'ngr.trace', 'ngr.store', 'ngr.fs', 'ngr.fs_take', 'ngr.now', 'ngr.mono', 'ngr.random', 'ngr.db']);
const strange = WebAssembly.Module.imports(mod).filter((i) => !KNOWN.has(`${i.module}.${i.name}`));
if (strange.length) fail(4, `✗ модуль просить невідоме: ${strange.map((i) => `${i.module}.${i.name}`).join(', ')}`);
if (WebAssembly.Module.exports(mod).some((e) => e.kind === 'memory') || !WebAssembly.Module.imports(mod).some((i) => i.kind === 'memory')) fail(4, '✗ модуль має власну памʼять: її дає лише господар');
const sha256 = (b) => crypto.createHash('sha256').update(b).digest('hex');
const HOME = process.env.NIGREDO_HOME || path.join(process.env.HOME || '/', '.nigredo');
const real = (p) => {                // як os.path.realpath: хвоста, якого немає, просто не торкаємось
  let cur = path.resolve(p), tail = [];
  for (;;) {
    try { return path.join(fs.realpathSync(cur), ...tail); }
    catch { const up = path.dirname(cur); if (up === cur) return path.resolve(p); tail.unshift(path.basename(cur)); cur = up; }
  }
};
const inside = (p, base) => p === base || p.startsWith(base.endsWith('/') ? base : base + '/');

// ---- печатка: читає господар сам, ядру не вірить
const srcBytes = fs.readFileSync(progPath);
const src = srcBytes.toString('utf8');
function readSeal(t) {
  let i = 0; const out = [];
  const skip = () => { for (;;) { while (' \t\r\n'.includes(t[i] ?? '.')) i++; if (t[i] === '※') { while (i < t.length && t[i] !== '\n') i++; } else return; } };
  const str = () => { let s = ''; i++; while (i < t.length && t[i] !== '」') { if (t[i] === '\\') { i++; s += { n: '\n', t: '\t' }[t[i]] ?? t[i]; } else s += t[i]; i++; } i++; return s; };
  skip();
  if (!t.startsWith('🜂', i)) return null;
  i += 2; skip();
  if (t[i] === '「') { str(); skip(); }
  if (t[i] === '【') { i++; for (;;) { skip(); if (t[i] !== '「') break; out.push(str()); } }
  return out;
}
const SHORT = { читати: 'файл.читати', писати: 'файл.писати', список: 'файл.список', взяти: 'мережа.взяти', послати: 'мережа.послати' };
function parseGrant(e) {            // «читати писати:дані≤3» → [{tool, scope, quota}]
  const q = e.match(/≤([0-9]+)$/); const body = q ? e.slice(0, q.index) : e;
  const c = body.indexOf(':'); const names = (c < 0 ? body : body.slice(0, c)).split(/\s+/).filter(Boolean);
  return names.map((n) => ({ tool: SHORT[n] ?? n, scope: c < 0 ? '' : body.slice(c + 1), quota: q ? Number(q[1]) : null }));
}
const seal = readSeal(src);
if (seal === null) fail(2, '✗ програма має починатися з печатки 🜂');
// чого немає в ядрі, модуль і так відмовить; але права такої програми господар не порахує, тож відмова — до їх перевірки, а не «бракує прав»
const importsOf = (t) => [...t.matchAll(/⊃\s*「([^」]*)」/g)].map((m) => m[1]);
if (/^ *※ підпис ed25519:/m.test(src)) fail(120, 'альбедо: не виконую сам (підпис автора — еталон)');
if (importsOf(src).some((p) => /#sha256=|:\/\/|^[a-z0-9.-]+\.[a-z]+\//.test(p))) fail(120, 'альбедо: не виконую сам (модуль з мережі — еталон)');
const progDir = real(path.dirname(path.resolve(progPath)));
const progReal = real(progPath);
const wanted = seal.flatMap(parseGrant);
const sha256Prog = sha256(srcBytes);

// ---- дозволи власника: ті самі правила, що в seal.rs (read_allowlist, check_allowlist, program_ok). Вужче за них можна, ширше — вада.
const KIND = { оракул: '', жереб: '', час: '', 'файл.читати': 'тека', 'файл.писати': 'тека', 'файл.список': 'тека', 'бд.читати': 'тека', 'бд.писати': 'тека',
  'мережа.взяти': 'хост', 'мережа.послати': 'хост', процес: 'команда', агент: 'імʼя', python: 'функція' };
const WRITE_TOOLS = new Set(['файл.писати', 'бд.писати']);
const expand = (p) => (p === '~' || p.startsWith('~/') ? path.join(process.env.HOME || '/', p.slice(1)) : p);
const canon = (e) => { const c = e.indexOf(':'), n = (c < 0 ? e : e.slice(0, c)).trim(); return SHORT[n] ? SHORT[n] + (c < 0 ? '' : e.slice(c)) : e; };
function grantOf(e) {                 // запис власника: один інструмент, без скорочень
  const m = canon(e).match(/^([^]*?)\s*≤\s*([0-9]+)$/), body = m ? m[1] : canon(e), c = body.indexOf(':');
  return { tool: (c < 0 ? body : body.slice(0, c)).trim(), scope: c < 0 ? '' : body.slice(c + 1).trim(), quota: m ? Number(m[2]) : null };
}
const homeReal = real(HOME);
const ownerFile = path.join(HOME, 'дозволи.json');
let allowed = ['оракул', 'жереб', 'час'], ownerSrc = '(файлу власника немає: лише іграшкові інструменти)', writeEntries = [];
if (fs.existsSync(ownerFile)) {
  const raw = fs.readFileSync(ownerFile);
  const owner = JSON.parse(raw.toString('utf8'));
  ownerSrc = `${ownerFile} (sha256 ${sha256(raw).slice(0, 16)})`;
  allowed = (owner['дозволено'] ?? []).map(canon);
  const perDir = Object.entries(owner['для_тек'] ?? {}), perProg = new Map(Object.entries(owner['для_програм'] ?? {}).map(([k, v]) => [k.trim().toLowerCase(), v]));
  const perAuth = Object.values(owner['для_авторів'] ?? {}).map((v) => v['дозволи'] ?? []);
  const all = [...allowed, ...perDir.flatMap(([, v]) => v), ...[...perProg.values()].flat(), ...perAuth.flat()].map(grantOf);
  writeEntries = all.filter((g) => WRITE_TOOLS.has(g.tool)).map((g) => g.scope).filter(Boolean).map(expand).filter((w) => w.startsWith('/'));
  // тека, куди можна писати програмам, не дає прав: програму там могла написати інша програма
  const selfWritten = writeEntries.some((w) => inside(progReal, real(w)));
  for (const [d, extra] of perDir) { const e = expand(d); if (e.startsWith('/') && inside(progDir, real(e)) && !selfWritten) allowed.push(...extra.map(canon)); }
  // відбиток для «для_програм» — як approval_of: з модулями це sha рядків «sha програми», «sha модуля»… (у порядку ⊃, вкладені одразу за своїм)
  const shas = [], seen = new Set();
  const walk = (text, dir) => { for (const p of importsOf(text)) {
    const t = real(path.resolve(dir, p));
    if (seen.has(t) || !fs.existsSync(t)) continue;
    seen.add(t);
    const b = fs.readFileSync(t);
    shas.push(sha256(b));
    walk(b.toString('utf8'), path.dirname(t));
  } };
  walk(src, progDir);
  const approval = shas.length ? sha256(Buffer.from([sha256Prog, ...shas].join('\n'))) : sha256Prog;
  if (perProg.has(approval)) { allowed.push(...perProg.get(approval).map(canon)); ownerSrc += `; схвалено власником: програма ${approval.slice(0, 16)}…`; }
}
const granted = allowed.map(grantOf);
const scopeOf = (s) => real(path.resolve(progDir, s));
function lacks(w) {
  const kind = KIND[w.tool], gs = granted.filter((g) => g.tool === w.tool);
  if (kind === undefined || !gs.length) return true;
  if (!w.scope) return false;
  if (kind === 'тека' && (inside(scopeOf(w.scope), homeReal) || inside(homeReal, scopeOf(w.scope)))) return true;
  return !gs.some((g) => g.scope && (kind === 'тека' ? expand(g.scope).startsWith('/') && inside(scopeOf(w.scope), real(expand(g.scope))) : g.scope === w.scope));
}
const missing = wanted.filter(lacks);
if (missing.length) fail(3, `✗ печатка просить більше, ніж дозволив власник: ${missing.map((m) => m.tool + (m.scope ? ':' + m.scope : '')).join(', ')}`);
// модуль — лише те, що справді імпортовано (перелік росте з кожним прочитаним модулем), і не з місця, куди могла писати програма
const writableDirs = [...writeEntries.map(real), ...wanted.filter((w) => WRITE_TOOLS.has(w.tool) && w.scope).map((w) => scopeOf(w.scope))];
const modulesSeen = new Set();
const learnImports = (text, dir) => { for (const p of importsOf(text)) modulesSeen.add(real(path.resolve(dir, p))); };
learnImports(src, progDir);
const moduleOk = (t) => modulesSeen.has(t) && inside(t, progDir) && !writableDirs.some((w) => inside(t, w));
for (const t of modulesSeen) if (inside(t, progDir) && !moduleOk(t)) fail(3, `✗ модуль лежить там, куди можна писати програмам: ${t}`);

// ---- слід: ланцюжок і HMAC тут; модуль дає текст запису із заглушками
const ownerKey = () => {
  fs.mkdirSync(HOME, { recursive: true, mode: 0o700 });
  const k = path.join(HOME, 'ключ');
  if (!fs.existsSync(k)) fs.writeFileSync(k, crypto.randomBytes(32).toString('hex'), { mode: 0o600, flag: 'wx' });
  return Buffer.from(fs.readFileSync(k, 'utf8').trim());
};
const key = ownerKey();
const traces = path.join(HOME, 'сліди');
fs.mkdirSync(traces, { recursive: true, mode: 0o700 });
const now = new Date();
const stamp = now.toISOString().replace(/[-:]/g, '').replace('T', '-').slice(0, 15);
const progSha = sha256Prog;
const mainTrace = W ? W.mainTrace : path.join(traces, `${stamp}-${progSha.slice(0, 8)}-${process.pid}.jsonl`);
const paths = [mainTrace, ...(extraTrace ? [path.resolve(extraTrace)] : [])];
if (!W && process.env.NIGREDO_TRACE_PATH_FILE) fs.writeFileSync(process.env.NIGREDO_TRACE_PATH_FILE, mainTrace);
const fds = W ? W.fds : paths.map((p) => fs.openSync(p, 'wx'));
const stores = W ? W.stores : paths.map((p) => fs.openSync(p + '.дані', 'wx'));
let prev = '0'.repeat(16), n = 0, fromModule = 0, pendingBody = null;   // номер у сліді веде господар: він теж пише записи
const ZERO = '"0000000000000000"';
const sign = (b) => crypto.createHmac('sha256', key).update(b).digest('hex').slice(0, 16);
function writeTrace(line, body, mod = true) {
  n++;
  if (mod) {
    fromModule++;
    const k = `"№": ${fromModule}`;
    if (!line.startsWith(`{${k}, `) || !body.includes(k)) fail(4, `✗ модуль порушив нумерацію сліду (очікував ${fromModule})`);
    line = line.replace(k, `"№": ${n}`); body = body.replace(k, `"№": ${n}`);
  }
  const fill = (t, field, v) => { const k = `"${field}": ${ZERO}`, i = t.lastIndexOf(k); if (i < 0) fail(4, '✗ запис сліду без заглушки'); return t.slice(0, i) + `"${field}": "${v}"` + t.slice(i + k.length); };
  const signed = fill(body, 'попередній', prev);
  const h = sign(Buffer.from(signed));
  const out = fill(fill(line, 'попередній', prev), 'хеш', h);
  prev = h;
  for (const fd of fds) fs.writeSync(fd, out);
}
// запис самого господаря: модуль його не підробить і не прибере — це власний свідок дій
function hostRecord(event, fields) {
  const rec = { '№': n + 1, 'подія': event, 'глибина': 0, ...fields, 'попередній': '0000000000000000' };
  const val = (v) => (Array.isArray(v) ? '[' + v.map(val).join(', ') + ']' : JSON.stringify(v));   // як json.dumps: «, » і «: »
  const dump = (o) => '{' + o.map(([k, v]) => `${JSON.stringify(k)}: ${val(v)}`).join(', ') + '}';
  const ents = Object.entries(rec);
  writeTrace(dump([...ents, ['хеш', '0000000000000000']]) + '\n', dump([...ents].sort(([a], [b]) => (a < b ? -1 : 1))), false);
}

// ---- інструменти: лише те, що в печатці, і лише тут
const scopes = (tool) => wanted.filter((w) => w.tool === tool).map((w) => w.scope ? scopeOf(w.scope) : null).filter(Boolean);
const dbRead = [...scopes('бд.читати'), ...scopes('бд.писати')], dbWrite = scopes('бд.писати');
const fileRoots = [...new Set([progDir, ...scopes('файл.читати'), ...scopes('файл.писати'), ...scopes('файл.список'), ...dbRead])];
const forbidden = (p) => inside(p, real(HOME)) || paths.some((t) => p === real(t) || p === real(t + '.дані'));
const used = new Map();
function quotaOk(tool, target) {
  for (const w of [...wanted, ...granted].filter((x) => x.tool === tool && x.quota !== null && (!x.scope || inside(target, scopeOf(x.scope))))) {
    const k = `${w.tool}:${w.scope}`, c = (used.get(k) ?? 0) + 1;
    if (c > w.quota) return false;
    used.set(k, c);
  }
  return true;
}
function deny(tool, p, why) { hostRecord('господар відмовив', { 'інструмент': tool, 'шлях': p, 'причина': why }); return -13; }
const permit = (tool, target, p) => {
  if (forbidden(target)) return deny(tool, p, 'тека власника або слід');
  if (!scopes(tool).some((s) => inside(target, s))) return deny(tool, p, 'поза печаткою');
  if (!quotaOk(tool, target)) return deny(tool, p, 'понад квоту');
  return 0;
};
let mem, pending = Buffer.alloc(0);
const bytes = (p, l) => Buffer.from(mem.buffer, p, l);
const text = (p, l) => bytes(p, l).toString('utf8');
const reply = (b) => { pending = b; return BigInt(b.length); };
const errnoOf = (e) => -(({ ENOENT: 2, EACCES: 13, EISDIR: 21, ENOTDIR: 20, ENOSPC: 28 })[e.code] ?? 5);
function fsCall(op, p, l, q, m) {
  const name = text(p, l);
  try {
    if (op === 1) {                         // читати
      const target = real(name);
      const isModule = moduleOk(target);
      if (!isModule) { const r = permit('файл.читати', target, name); if (r) return BigInt(r); }
      const cap = Number(bytes(q, 8).readBigUInt64LE(0));
      const fd = fs.openSync(target, 'r');
      try {
        const size = Math.min(fs.fstatSync(fd).size, cap), b = Buffer.alloc(size);
        fs.readSync(fd, b, 0, size, 0);
        if (isModule) learnImports(b.toString('utf8'), path.dirname(target));
        return reply(b);
      } finally { fs.closeSync(fd); }
    }
    if (op === 2) {                         // писати: теку перевіряємо, як нативно
      const dir = real(path.dirname(name)), target = path.join(dir, path.basename(name));
      const r = permit('файл.писати', dir, name); if (r) return BigInt(r);
      if (fs.existsSync(target) && fs.lstatSync(target).isSymbolicLink()) return BigInt(deny('файл.писати', name, 'символьне посилання'));
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(target, bytes(q, m));
      return reply(Buffer.alloc(0));
    }
    if (op === 3) {                         // список
      const target = real(name);
      const r = permit('файл.список', target, name); if (r) return BigInt(r);
      return reply(Buffer.from(fs.readdirSync(target).join('\0')));
    }
    if (op === 4) {                         // що це: лише всередині коренів печатки
      const target = real(name);
      if (!fileRoots.some((b) => inside(target, b)) || forbidden(target)) return reply(Buffer.from([0]));
      const st = fs.statSync(target);
      return reply(Buffer.from([st.isDirectory() ? 2 : 1]));
    }
    if (op === 5) {                         // справжній шлях: поза коренями печатки не розкриваємо нічого
      const target = real(name);
      return reply(Buffer.from(fileRoots.some((b) => inside(target, b)) ? target : path.resolve(name)));
    }
    return -38n;
  } catch (e) { return op === 4 ? reply(Buffer.from([0])) : BigInt(errnoOf(e)); }
}
// ---- база: сам SQLite у модулі, а його файли — тут. Запит читає сторож у модулі; який файл узагалі доступний, вирішує цей перелік,
// тож ATTACH чужої бази чи запис під «бд.читати» впираються сюди, навіть якщо модуль вирізав сторожа.
const dbFiles = new Map(); let dbNext = 1, dbSpent = 0;
const DB_OPEN = 1, DB_READ = 2, DB_WRITE = 3, DB_SIZE = 4, DB_TRUNC = 5, DB_SYNC = 6, DB_CLOSE = 7, DB_DELETE = 8, DB_ACCESS = 9;
const dbMain = (t) => t.replace(/-(journal|wal|shm)$/, '');
const dbSees = (t, roots) => !forbidden(t) && roots.some((r) => inside(dbMain(t), r));
// «бд.читати:дані» — право на бази, а не на всі файли теки: чужий файл модуль бачить нулями (SQLite скаже «file is not a database»,
// як нативно) і писати в нього не може. Інакше зіпсоване ядро читало б сирими байтами все, що лежить поруч із базою.
const MAGIC = { main: Buffer.from('SQLite format 3\0'), journal: Buffer.from('d9d505f920a163d7', 'hex'), wal: Buffer.from('377f06', 'hex') };
const dbKind = (t) => (t.endsWith('-wal') ? 'wal' : t.endsWith('-journal') ? 'journal' : 'main');
const dbForeign = (fd, kind) => {
  const m = MAGIC[kind], h = Buffer.alloc(m.length), n = fs.readSync(fd, h, 0, m.length, 0);
  return n > 0 && !h.equals(m);
};
const dbOpened = (f) => { dbFiles.set(dbNext, f); return dbNext++; };
function dbCall(op, a, b, p, l) {
  try {
    if (op === DB_OPEN) {
      const name = text(p, l), target = real(name), mode = Number(a), tool = mode ? 'бд.писати' : 'бд.читати';
      const kind = dbKind(target);
      if (kind === 'wal' && mode && !dbSees(target, dbWrite) && dbSees(target, dbRead)) {   // SQLite просить запис завжди; під «бд.читати» — читання
        const fd = fs.existsSync(target) ? fs.openSync(target, fs.constants.O_RDONLY) : null;
        return BigInt(dbOpened({ fd, write: false, kind, foreign: fd !== null && dbForeign(fd, kind) })) | (1n << 30n);
      }
      if (!dbSees(target, mode ? dbWrite : dbRead)) return BigInt(deny(tool, name, 'поза печаткою'));
      const { O_RDONLY, O_RDWR, O_CREAT, O_NOFOLLOW } = fs.constants;
      const fd = fs.openSync(target, mode ? O_RDWR | O_NOFOLLOW | (mode === 2 ? O_CREAT : 0) : O_RDONLY, 0o644);
      if (!fs.fstatSync(fd).isFile()) { fs.closeSync(fd); return -21n; }
      return BigInt(dbOpened({ fd, write: mode > 0, kind, foreign: dbForeign(fd, kind) }));
    }
    if (op === DB_DELETE) {                 // лише журнал: стерти саму базу SQLite не потрібно ніколи
      const name = text(p, l), target = real(name);
      if (dbKind(target) === 'main' || !dbSees(target, dbWrite)) return BigInt(deny('бд.писати', name, 'видаляти можна лише журнал'));
      fs.unlinkSync(target);
      return 0n;
    }
    if (op === DB_ACCESS) {                 // як unixAccess: порожній файл — наче немає
      const target = real(text(p, l));
      if (!dbSees(target, dbRead)) return 0n;
      const st = fs.statSync(target);
      if (a === 1n) fs.accessSync(target, fs.constants.W_OK);
      return !st.isFile() || st.size > 0 ? 1n : 0n;
    }
    const f = dbFiles.get(Number(a));
    if (!f) return -9n;
    if (f.fd === null) return op === DB_CLOSE ? (dbFiles.delete(Number(a)), 0n) : op === DB_READ || op === DB_SIZE ? 0n : BigInt(deny('бд.писати', '', 'файл відкрито лише для читання'));
    if (op === DB_READ) {
      if (!f.foreign) return BigInt(fs.readSync(f.fd, bytes(p, l), 0, l, Number(b)));
      const got = Math.max(0, Math.min(l, fs.fstatSync(f.fd).size - Number(b)));
      bytes(p, l).fill(0);
      return BigInt(got);
    }
    if (op === DB_SIZE) return BigInt(fs.fstatSync(f.fd).size);
    if (op === DB_CLOSE) { fs.closeSync(f.fd); dbFiles.delete(Number(a)); return 0n; }
    if (!f.write) return BigInt(deny('бд.писати', '', 'файл відкрито лише для читання'));
    if (f.foreign) return BigInt(deny('бд.писати', '', 'файл — не база'));
    if (op === DB_WRITE) {
      if (f.kind === 'main' && b === 0n && !(l >= 16 && bytes(p, 16).equals(MAGIC.main))) return BigInt(deny('бд.писати', '', 'записане — не база'));
      if ((dbSpent += l) > dbLimit) return BigInt(deny('бд.писати', '', 'понад межу запису'));
      return BigInt(fs.writeSync(f.fd, bytes(p, l), 0, l, Number(b)));
    }
    if (op === DB_TRUNC) { fs.ftruncateSync(f.fd, Number(b)); return 0n; }
    if (op === DB_SYNC) { fs.fsyncSync(f.fd); return 0n; }
    return -38n;
  } catch (e) { return op === DB_ACCESS ? 0n : BigInt(errnoOf(e)); }
}
const hasClock = wanted.some((w) => w.tool === 'час');
let isolated = false;
const imports = { ngr: {
  out: (p, l) => { fs.writeSync(1, bytes(p, l)); },
  err: (p, l) => { fs.writeSync(2, text(p, l) + '\n'); },
  body: (p, l) => { pendingBody = text(p, l); },
  trace: (p, l) => {
    const line = text(p, l);
    if (pendingBody === null) fail(4, '✗ запис сліду без канонічного тексту');
    writeTrace(line, pendingBody); pendingBody = null;
    if (!isolated && fromModule >= 1 && line.includes('"подія": "печатка"')) {   // межа — не печатка ядра, а цей перелік імпортів
      isolated = true;
      hostRecord('ізоляція', { 'ядро': 'wasm', 'закрито': ['мережа', 'процеси', ...(scopes('файл.писати').length || dbWrite.length ? [] : ['запис'])], 'причина': null });
    }
  },
  store: (p, l) => { for (const fd of stores) fs.writeSync(fd, bytes(p, l)); },
  fs: (op, p, l, q, m) => fsCall(op, p, l, q, m),
  fs_take: (d) => { bytes(d, pending.length).set(pending); },
  now: () => (hasClock ? BigInt(Math.floor(Date.now() / 1000)) : -1n),
  mono: () => process.hrtime.bigint() / 1000000n,
  random: (p, l) => { crypto.randomFillSync(bytes(p, l)); },
  db: (op, a, b, p, l) => dbCall(op, a, b, p, l),
} };
if (isMainThread) {
  const worker = new Worker(fileURLToPath(import.meta.url), { argv: [], workerData: { argv: process.argv, fds, stores, mainTrace }, resourceLimits: { stackSizeMb: 256 } });
  const finish = (code, msg) => {          // слід завершує цей потік: модуль уже нічого не допише
    clearTimeout(timer);
    const tail = fs.readFileSync(mainTrace, 'utf8').trimEnd().split('\n').pop();
    if (tail) { const r = JSON.parse(tail); n = r['№']; prev = r['хеш']; }
    hostRecord('помилка', { 'повідомлення': msg, 'від_господаря': true });
    fs.writeSync(2, msg + '\n');
    process.exit(code);
  };
  let stopping = false;
  const timer = setTimeout(() => { stopping = true; worker.terminate().then(() => finish(1, `✗ господар зупинив модуль: строк ${deadline} с (--строк)`)); }, deadline * 1000);
  worker.on('error', (e) => { stopping = true; finish(4, `✗ модуль упав: ${String(e.message ?? e).slice(0, 200)}`); });
  worker.on('exit', (code) => { if (!stopping) { clearTimeout(timer); process.exit(code); } });
} else {
const memory = new WebAssembly.Memory({ initial: 2048, maximum: Math.floor(memMb * 16) });
imports.env = { memory };
const inst = new WebAssembly.Instance(mod, imports);
mem = memory;
const cfg = Buffer.from([path.resolve(progPath), progDir, progSha, now.toISOString().slice(0, 19) + '+00:00', crypto.randomBytes(6).toString('hex'),
  `альбедо:${sha256(wasmBytes)}`, ownerSrc, seed, steps, size, tsize, real(HOME), String(progArgs.length), ...progArgs, ...allowed].join('\0'));
const put = (b) => { const a = inst.exports.ngr_alloc(b.length); bytes(a, b.length).set(b); return a; };
const cp = put(cfg), sp = put(srcBytes);
const t = process.hrtime.bigint();
const code = inst.exports.ngr_run(cp, cfg.length, sp, srcBytes.length);
if (showTime) fs.writeSync(2, `час: ${Number(process.hrtime.bigint() - t) / 1e6} мс, записів сліду: ${n}\n`);
if (code === 120) for (const p of paths) for (const f of [p, p + '.дані']) fs.rmSync(f, { force: true });   // нічого не виконано — нема й сліду
process.exit(code);
}
