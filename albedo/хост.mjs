// Альбедо, господар (spec/пропозиції/альбедо.md §2). Довірена база: модуль WASM нічого не може без цих функцій.
// Три правила: печатку читає господар, а не модуль; кожна дія перевіряється тут; ключ сліду лишається тут.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { Worker, isMainThread, workerData } from 'node:worker_threads';
import { fileURLToPath } from 'node:url';

// Два потоки: модуль — у своєму, цей лише стежить за строком: модуль, що крутиться вічно, себе не зупинить, а кроки рахує він сам.
const W = isMainThread ? null : workerData;
const args = (W ? W.argv : process.argv).slice(2);
const opt = (k, d) => { const i = args.indexOf(k); if (i < 0) return d; const v = args[i + 1]; args.splice(i, 2); return v; };
const flag = (k) => { const i = args.indexOf(k); if (i < 0) return false; args.splice(i, 1); return true; };
const extraTrace = opt('--слід', null), seed = opt('--зерно', '0'), steps = opt('--кроки', '10000000');
const size = opt('--розмір', '5000000'), tsize = opt('--слід-розмір', '50000000');
const deadline = Number(opt('--строк', '300')), memMb = Number(opt('--памʼять', '1024'));   // с, МБ: тримає господар, а не модуль
const showImports = flag('--імпорти'), showTime = flag('--час');
const [wasmPath, progPath] = args;
const wasmBytes = fs.readFileSync(wasmPath);
const mod = new WebAssembly.Module(wasmBytes);
if (showImports) { for (const i of WebAssembly.Module.imports(mod)) console.log(`${i.module}.${i.name}`); process.exit(0); }

const fail = (code, msg) => { fs.writeSync(2, msg + '\n'); process.exit(code); };
// памʼять дає господар і стелю ставить він: модуль зі своєю памʼяттю не запускається
const KNOWN = new Set(['env.memory', 'ngr.out', 'ngr.err', 'ngr.body', 'ngr.trace', 'ngr.store', 'ngr.fs', 'ngr.fs_take', 'ngr.now']);
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
const progDir = real(path.dirname(path.resolve(progPath)));
const wanted = seal.flatMap(parseGrant);

// ---- дозволи власника (М1: «дозволено» і «для_тек»; «для_програм» і «для_авторів» — ще ні, тобто вужче)
const ownerFile = path.join(HOME, 'дозволи.json');
let owner = {}, ownerSrc = `${ownerFile} (файлу немає)`;
if (fs.existsSync(ownerFile)) {
  const raw = fs.readFileSync(ownerFile); owner = JSON.parse(raw.toString('utf8'));
  ownerSrc = `${ownerFile} (sha256 ${sha256(raw).slice(0, 16)})`;
}
const allowed = [...(owner['дозволено'] ?? []), ...Object.entries(owner['для_тек'] ?? {}).filter(([d]) => real(d) === progDir).flatMap(([, v]) => v)];
const granted = allowed.flatMap(parseGrant);
const scopeOf = (s) => real(path.resolve(progDir, s));
const covered = (w) => granted.some((g) => g.tool === w.tool && (g.scope === '' || w.tool === 'жереб' || w.tool === 'оракул' || w.tool === 'час'
  || (w.scope !== '' && inside(scopeOf(w.scope), real(g.scope)))));
const missing = wanted.filter((w) => !covered(w));
if (missing.length) fail(3, `✗ печатка просить більше, ніж дозволив власник: ${missing.map((m) => m.tool + (m.scope ? ':' + m.scope : '')).join(', ')}`);

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
const progSha = sha256(srcBytes);
const mainTrace = W ? W.mainTrace : path.join(traces, `${stamp}-${progSha.slice(0, 8)}-${process.pid}.jsonl`);
const paths = [mainTrace, ...(extraTrace ? [path.resolve(extraTrace)] : [])];
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
const fileRoots = [...new Set([progDir, ...scopes('файл.читати'), ...scopes('файл.писати'), ...scopes('файл.список')])];
const forbidden = (p) => inside(p, real(HOME)) || paths.some((t) => p === real(t) || p === real(t + '.дані'));
const used = new Map();
function quotaOk(tool, p) {
  for (const w of wanted.filter((x) => x.tool === tool && x.quota !== null && (!x.scope || inside(p, scopeOf(x.scope))))) {
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
  if (!quotaOk(tool, p)) return deny(tool, p, 'понад квоту');
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
      const isModule = target.endsWith('.ngr') && inside(target, progDir);
      if (!isModule) { const r = permit('файл.читати', target, name); if (r) return BigInt(r); }
      const cap = Number(bytes(q, 8).readBigUInt64LE(0));
      const fd = fs.openSync(target, 'r');
      try { const size = Math.min(fs.fstatSync(fd).size, cap); const b = Buffer.alloc(size); fs.readSync(fd, b, 0, size, 0); return reply(b); } finally { fs.closeSync(fd); }
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
      hostRecord('ізоляція', { 'ядро': 'wasm', 'закрито': ['мережа', 'процеси', ...(scopes('файл.писати').length ? [] : ['запис'])], 'причина': null });
    }
  },
  store: (p, l) => { for (const fd of stores) fs.writeSync(fd, bytes(p, l)); },
  fs: (op, p, l, q, m) => fsCall(op, p, l, q, m),
  fs_take: (d) => { bytes(d, pending.length).set(pending); },
  now: () => (hasClock ? BigInt(Math.floor(Date.now() / 1000)) : -1n),
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
  `альбедо:${sha256(wasmBytes)}`, ownerSrc, seed, steps, size, tsize, real(HOME), ...allowed].join('\n'));
const put = (b) => { const a = inst.exports.ngr_alloc(b.length); bytes(a, b.length).set(b); return a; };
const cp = put(cfg), sp = put(srcBytes);
const t = process.hrtime.bigint();
const code = inst.exports.ngr_run(cp, cfg.length, sp, srcBytes.length);
if (showTime) fs.writeSync(2, `час: ${Number(process.hrtime.bigint() - t) / 1e6} мс, записів сліду: ${n}\n`);
process.exit(code);
}
