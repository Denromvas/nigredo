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
const fail = (code, msg) => { fs.writeSync(2, msg + '\n'); process.exit(code); };
const opt = (k, d) => { const i = args.indexOf(k); if (i < 0) return d; if (i + 1 >= args.length) fail(2, `✗ ${k}: бракує значення`); const v = args[i + 1]; args.splice(i, 2); return v; };
const flag = (k) => { const i = args.indexOf(k); if (i < 0) return false; args.splice(i, 1); return true; };
// значення прапорців — лише цілі в межах: NaN вимкнув би межу мовчки
function intOpt(k, d, lo, hi) {
  const v = opt(k, null);
  if (v === null) return d;
  if (!/^[0-9]+$/.test(v) || Number(v) < lo || Number(v) > hi) fail(2, `✗ ${k}: ціле від ${lo} до ${hi}, а не «${v}»`);
  return Number(v);
}
const extraTrace = opt('--слід', null), seed = opt('--зерно', '0');
if (!/^[-+]?[0-9]+$/.test(seed)) fail(2, `✗ --зерно: ціле, а не «${seed}»`);
const steps = intOpt('--кроки', 10000000, 0, Number.MAX_SAFE_INTEGER), size = intOpt('--розмір', 5000000, 0, Number.MAX_SAFE_INTEGER);
const tsize = intOpt('--слід-розмір', 50000000, 0, Number.MAX_SAFE_INTEGER), dbLimit = intOpt('--бд-запис', 2 ** 30, 0, Number.MAX_SAFE_INTEGER);
const deadline = intOpt('--строк', 300, 1, 2000000), memMb = intOpt('--памʼять', 2048, 1, 4096);   // с, МБ: тримає господар, а не модуль
const showImports = flag('--імпорти'), showTime = flag('--час'), showReading = flag('--читання');
const sha256 = (b) => crypto.createHash('sha256').update(b).digest('hex');
const HOME = process.env.NIGREDO_HOME || path.join(process.env.HOME || '/', '.nigredo');
// як os.path.realpath, покомпонентно: посилання розгортаємо й тоді, коли його цілі немає (інакше запис через висяче посилання вийшов би
// за теку, хоч перевірка бачила шлях усередині), а «..» — після розгортання, як ОС. Чого немає, просто лишається як є.
function real(p) {
  let done = '/', parts = (p.startsWith('/') ? p : `${process.cwd()}/${p}`).split('/').filter((c) => c && c !== '.'), links = 0;
  while (parts.length) {
    const c = parts.shift();
    if (c === '..') { done = path.dirname(done); continue; }
    const next = path.join(done, c);
    let to;
    try { to = fs.readlinkSync(next); } catch { done = next; continue; }
    if (++links > 40) return path.join(next, ...parts);          // петля: далі не йдемо, відкриття скаже ELOOP
    if (to.startsWith('/')) done = '/';
    parts = [...to.split('/').filter((x) => x && x !== '.'), ...parts];
  }
  return done;
}
const inside = (p, base) => p === base || p.startsWith(base + '/');     // як в еталона: «/» покриває лише себе
const under = (base, s) => real(s.startsWith('/') ? s : `${base}/${s}`);   // без path.resolve: той згортає «..» ще до посилань

// ---- читання програми: це друга граматика мови й головний ризик задуму, тож лише те, що потрібно, і суворо. Токени — за правилами лексера: кінець рядка
// значущий, шаблон — зі стеком режимів, невідоме екранування лишається. Усе, чого тут не розпізнано як канонічну печатку, — відмова, а не власне тлумачення.
const NL = { nl: true };
function tokens(t) {
  const out = [], modes = [];
  out.comments = [];
  for (let i = 0; i < t.length;) {
    if (modes.at(-1) === 'текст') {
      while (i < t.length && t[i] !== '〕' && t[i] !== '{') i += t[i] === '\\' ? 2 : 1;
      if (i >= t.length) throw new Error('незакритий шаблон');
      if (t[i] === '〕') modes.pop(); else modes.push('дірка');
      i++;
      continue;
    }
    const c = t[i];
    if (modes.at(-1) === 'дірка' && c === '}') { modes.pop(); i++; }
    else if (modes.at(-1) === 'дірка' && (c === '\n' || c === '¦')) throw new Error('вираз у {…} шаблону — в одному рядку');
    else if (c === '〔') { modes.push('текст'); i++; }
    else if (c === '\n' || c === '¦') { out.push(NL); i++; }
    else if (c === ' ' || c === '\t' || (c === '\r' && t[i + 1] === '\n')) i++;
    else if (c === '\r') throw new Error('сам по собі \\r');
    else if (c === '※') { const from = i; while (i < t.length && t[i] !== '\n') i++; out.comments.push(t.slice(from, i)); }
    else if (c === '「') {
      let v = '';
      for (i++; ; i++) {
        if (i >= t.length) throw new Error('незакритий рядок');
        if (t[i] === '」') break;
        if (t[i] === '\\' && i + 1 < t.length) { i++; v += { n: '\n', t: '\t', '」': '」', '\\': '\\' }[t[i]] ?? `\\${t[i]}`; }
        else if (t[i] !== '\r' || t[i + 1] !== '\n') v += t[i];
      }
      i++;
      out.push({ str: v });
    } else { const g = String.fromCodePoint(t.codePointAt(i)); out.push(g); i += g.length; }
  }
  return out;
}
function readSeal(toks) {            // null — печатки немає; виняток — форма, якої господар не читає
  let i = 0;
  while (toks[i] === NL) i++;
  if (toks[i] !== '🜂') return null;
  i++;
  const ended = () => i >= toks.length || toks[i] === NL;
  if (ended()) return [];            // кінець рядка закінчує печатку: перелік на наступному рядку — вже не вона
  if (toks[i]?.str !== undefined) { i++; if (ended()) return []; }
  if (toks[i] !== '【') throw new Error('після наміру — перелік 【…】');
  const out = [];
  for (i++; toks[i] !== '】'; i++) {
    if (toks[i] === NL) continue;
    if (toks[i]?.str === undefined) throw new Error('у переліку дозволів — лише рядки');
    out.push(toks[i].str);
  }
  i++;
  if (!ended()) throw new Error('після переліку дозволів ще щось є');
  return out;
}
function importsOf(toks) {
  const out = [];
  toks.forEach((tok, i) => { if (tok === '⊃' && toks[i + 1]?.str !== undefined) out.push(toks[i + 1].str); });
  return out;
}
const SHORT = { читати: 'файл.читати', писати: 'файл.писати', список: 'файл.список', взяти: 'мережа.взяти', послати: 'мережа.послати' };
const canon = (e) => { const c = e.indexOf(':'), n = (c < 0 ? e : e.slice(0, c)).trim(); return SHORT[n] ? SHORT[n] + (c < 0 ? '' : e.slice(c)) : e; };
function splitQuota(e) {             // як split_quota: одна квота в кінці, не нуль
  const m = e.match(/^(.*?)\s*≤\s*([0-9]+)$/);
  if (!m) { if (e.includes('≤')) throw new Error('квота — «≤N» у кінці'); return [e, null]; }
  if (m[1].includes('≤')) throw new Error('одна квота — у кінці');
  if (/^0+$/.test(m[2])) throw new Error('квота ≤0');
  return [m[1], Number(m[2])];
}
function parseGrant(e) {             // «читати писати:дані≤3» → [{tool, scope, quota}]
  const [body, quota] = splitQuota(e), c = body.indexOf(':');
  return (c < 0 ? body : body.slice(0, c)).split(' ').map((n) => {
    const perm = canon(n + (c < 0 ? '' : body.slice(c))), k = perm.indexOf(':');
    return { tool: (k < 0 ? perm : perm.slice(0, k)).trim(), scope: k < 0 ? '' : perm.slice(k + 1).trim(), quota };
  });
}
const isRemote = (p) => p.includes('#') || p.includes('://') || p.startsWith('github.com/') || p.startsWith('raw.githubusercontent.com/');
function reading(text) {             // що господар вважає печаткою й імпортами: звіряється з еталоном на всьому корпусі (albedo/читання.py)
  const toks = tokens(text), seal = readSeal(toks);
  return { печатка: seal === null ? null : seal.flatMap(parseGrant), імпорти: importsOf(toks), підпис: toks.comments.some((c) => c.startsWith('※ підпис ed25519:')) };
}
if (showReading) {                   // службове для звірки читань: нічого не виконує. Шляхи — у stdin, відповідь — рядок JSON на кожен
  const out = fs.readFileSync(0, 'utf8').split('\n').filter(Boolean).map((f) => {
    try { return JSON.stringify(reading(fs.readFileSync(f, 'utf8'))); } catch (e) { return JSON.stringify({ відмова: e.message }); }
  });
  fs.writeSync(1, out.join('\n') + '\n');
  process.exit(0);
}
const [wasmPath, progPath] = args;
if (!wasmPath || !progPath) fail(2, '✗ хост.mjs [прапорці] МОДУЛЬ.wasm ПРОГРАМА.ngr [-- аргументи]');
let wasmBytes, mod, srcBytes;
try { wasmBytes = fs.readFileSync(wasmPath); mod = new WebAssembly.Module(wasmBytes); srcBytes = fs.readFileSync(progPath); }
catch (e) { fail(2, `✗ ${String(e.message ?? e).slice(0, 200)}`); }
if (showImports) { for (const i of WebAssembly.Module.imports(mod)) console.log(`${i.module}.${i.name}`); process.exit(0); }
// памʼять дає господар і стелю ставить він: модуль зі своєю памʼяттю не запускається
const KNOWN = new Set(['env.memory', 'ngr.out', 'ngr.err', 'ngr.body', 'ngr.trace', 'ngr.store', 'ngr.fs', 'ngr.fs_take', 'ngr.now', 'ngr.mono', 'ngr.random', 'ngr.db']);
const strange = WebAssembly.Module.imports(mod).filter((i) => !KNOWN.has(`${i.module}.${i.name}`));
if (strange.length) fail(4, `✗ модуль просить невідоме: ${strange.map((i) => `${i.module}.${i.name}`).join(', ')}`);
if (WebAssembly.Module.exports(mod).some((e) => e.kind === 'memory') || !WebAssembly.Module.imports(mod).some((i) => i.kind === 'memory')) fail(4, '✗ модуль має власну памʼять: її дає лише господар');
let src;
try { src = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(srcBytes); } catch { fail(2, '✗ програма не в UTF-8'); }
const LATER = 'альбедо: цього в модулі ще немає, програму не запущено';
let read;
try { read = reading(src); } catch (e) { fail(2, `✗ господар не читає цю програму: ${e.message}`); }
if (read.печатка === null) fail(2, '✗ програма має починатися з печатки 🜂');
// чого немає в ядрі, модуль і так відмовить; але права такої програми господар не порахує, тож відмова — до їх перевірки, а не «бракує прав»
if (read.підпис) fail(120, `${LATER} (рядок підпису)`);
if (read.імпорти.some(isRemote)) fail(120, `${LATER} (модуль з мережі)`);
const progDir = real(path.dirname(path.resolve(progPath)));
const progReal = real(progPath);
const wanted = read.печатка;
const sha256Prog = sha256(srcBytes);

// ---- дозволи власника: ті самі правила, що в seal.rs (read_allowlist, check_allowlist, program_ok). Вужче за них можна, ширше — вада.
const KIND = { оракул: '', жереб: '', час: '', 'файл.читати': 'тека', 'файл.писати': 'тека', 'файл.список': 'тека', 'бд.читати': 'тека', 'бд.писати': 'тека',
  'мережа.взяти': 'хост', 'мережа.послати': 'хост', процес: 'команда', агент: 'імʼя', python: 'функція' };
const WRITE_TOOLS = new Set(['файл.писати', 'бд.писати']);
const expand = (p) => (p === '~' || p.startsWith('~/') ? path.join(process.env.HOME || '/', p.slice(1)) : p);
function grantOf(e) {                 // запис власника: один інструмент, без скорочень
  const [body, quota] = splitQuota(canon(e)), c = body.indexOf(':');
  return { tool: (c < 0 ? body : body.slice(0, c)).trim(), scope: c < 0 ? '' : body.slice(c + 1).trim(), quota };
}
// JSON.parse мовчки бере останній із двох однакових ключів; еталон такий файл відкидає (loads_unique), і господар теж
function hasDuplicateKey(t) {
  const stack = [];
  for (let i = 0; i < t.length; i++) {
    const c = t[i];
    if (c === '{') stack.push(new Set());
    else if (c === '[') stack.push(null);
    else if (c === '}' || c === ']') stack.pop();
    else if (c === '"') {
      const from = i;
      for (i++; t[i] !== '"'; i++) if (t[i] === '\\') i++;
      let j = i + 1;
      while (' \t\r\n'.includes(t[j])) j++;
      if (t[j] === ':' && stack.at(-1)) {
        const k = JSON.parse(t.slice(from, i + 1));
        if (stack.at(-1).has(k)) return true;
        stack.at(-1).add(k);
      }
    }
  }
  return false;
}
const homeReal = real(HOME);
const ownerFile = path.join(HOME, 'дозволи.json');
let allowed = ['оракул', 'жереб', 'час'], ownerSrc = '(файлу власника немає: лише іграшкові інструменти)', writeEntries = [];
const moduleBytes = new Map();        // модуль читається раз: відбиток прав і текст для ядра — ті самі байти
if (fs.existsSync(ownerFile)) {
  const raw = fs.readFileSync(ownerFile);
  const badOwner = (why) => fail(3, `✗ дозволи власника (${ownerFile}): ${why}`);
  let owner, ownerText;
  try { ownerText = new TextDecoder('utf-8', { fatal: true }).decode(raw); owner = JSON.parse(ownerText); } catch { badOwner('не JSON у UTF-8'); }
  if (hasDuplicateKey(ownerText)) badOwner('той самий ключ двічі');
  const plain = (x) => x !== null && typeof x === 'object' && !Array.isArray(x);
  const strs = (x, what) => { if (!Array.isArray(x) || x.some((e) => typeof e !== 'string')) badOwner(`${what} — не список рядків`); return x; };
  if (!plain(owner)) badOwner('не словник');
  for (const k of ['для_тек', 'для_програм', 'для_авторів']) if (owner[k] !== undefined && !plain(owner[k])) badOwner(`${k} — не словник`);
  const mirrors = owner['джерела_модулів'];     // прав не дає, але файл, який еталон відкидає, не читаємо
  if (mirrors !== undefined && !(Array.isArray(mirrors) ? mirrors.length <= 1 && mirrors.every((h) => h === 'github.com')
    : plain(mirrors) && Object.entries(mirrors).every(([h, b]) => h === 'github.com' && typeof b === 'string'))) badOwner('джерела_модулів — не простої форми');
  ownerSrc = `${ownerFile} (sha256 ${sha256(raw).slice(0, 16)})`;
  allowed = strs(owner['дозволено'] ?? [], 'дозволено').map(canon);
  const perDir = Object.entries(owner['для_тек'] ?? {}).map(([k, v]) => [k, strs(v, 'для_тек')]);
  const perProg = new Map();
  for (const [k, v] of Object.entries(owner['для_програм'] ?? {})) {
    const h = k.trim().toLowerCase();
    if (perProg.has(h)) badOwner('для_програм: той самий відбиток двічі');
    perProg.set(h, strs(v, 'для_програм'));
  }
  const perAuth = Object.entries(owner['для_авторів'] ?? {}).map(([k, v]) => {
    if (!/^ed25519:[0-9a-f]{64}$/.test(k) || !plain(v) || (v['імʼя'] !== undefined && typeof v['імʼя'] !== 'string')
      || Object.keys(v).some((f) => f !== 'імʼя' && f !== 'дозволи')) badOwner('для_авторів — не простої форми');
    return strs(v['дозволи'], 'для_авторів');
  });
  let all;
  try { all = [...allowed, ...perDir.flatMap(([, v]) => v), ...[...perProg.values()].flat(), ...perAuth.flat()].map(grantOf); } catch (e) { badOwner(e.message); }
  writeEntries = all.filter((g) => WRITE_TOOLS.has(g.tool)).map((g) => g.scope).filter(Boolean).map(expand).filter((w) => w.startsWith('/'));
  // тека, куди можна писати програмам, не дає прав: програму там могла написати інша програма
  const selfWritten = writeEntries.some((w) => inside(progReal, real(w)));
  for (const [d, extra] of perDir) { const e = expand(d); if (e.startsWith('/') && inside(progDir, real(e)) && !selfWritten) allowed.push(...extra.map(canon)); }
  // відбиток для «для_програм» — як approval_of: з модулями це sha рядків «sha програми», «sha модуля»… (у порядку ⊃, вкладені одразу за своїм, повтор — двічі)
  const shas = [];
  const walk = (text, dir, stack) => { for (const p of importsOf(tokens(text))) {
    const t = under(dir, p);
    if (stack.includes(t) || !fs.statSync(t, { throwIfNoEntry: false })?.isFile()) continue;   // цикл чи не файл: відмовить ядро
    if (!moduleBytes.has(t)) moduleBytes.set(t, fs.readFileSync(t));
    shas.push(sha256(moduleBytes.get(t)));
    walk(moduleBytes.get(t).toString('utf8'), path.dirname(t), [...stack, t]);
  } };
  try { walk(src, progDir, [progReal]); } catch { /* модуль, якого не прочитати: розбір ядра скаже точніше */ }
  const approval = shas.length ? sha256(Buffer.from([sha256Prog, ...shas].join('\n'))) : sha256Prog;
  if (perProg.has(approval)) { allowed.push(...perProg.get(approval).map(canon)); ownerSrc += `; схвалено власником: програма ${approval.slice(0, 16)}…`; }
}
let granted;
try { granted = allowed.map(grantOf); } catch (e) { fail(3, `✗ дозволи власника: ${e.message}`); }
const scopeOf = (s) => under(progDir, s);                  // тека печатки: «~» тут не дім, а ім'я теки, як у мові; розгортаються лише записи власника
const ownerScope = (s) => under(progDir, expand(s));
function lacks(w) {
  const kind = KIND[w.tool], gs = granted.filter((g) => g.tool === w.tool);
  if (kind === undefined || !gs.length) return true;
  if (!w.scope) return false;
  if (kind === 'тека' && (inside(scopeOf(w.scope), homeReal) || inside(homeReal, scopeOf(w.scope)))) return true;
  return !gs.some((g) => g.scope && (kind === 'тека' ? expand(g.scope).startsWith('/') && inside(scopeOf(w.scope), real(expand(g.scope))) : g.scope === w.scope));
}
const missing = wanted.filter(lacks);
if (missing.length) fail(3, `✗ печатка просить більше, ніж дозволив власник: ${missing.map((m) => m.tool + (m.scope ? ':' + m.scope : '')).join(', ')}`);
// модуль — лише те, що справді імпортовано (перелік росте з кожним прочитаним модулем): відносний .ngr у теці програми, не в теці власника й не там, куди могла писати програма.
const writableDirs = [...granted.filter((g) => WRITE_TOOLS.has(g.tool)).map((g) => ownerScope(g.scope || '.')), ...writeEntries.map(real),
  ...wanted.filter((w) => WRITE_TOOLS.has(w.tool) && w.scope).map((w) => scopeOf(w.scope))];
const modulesSeen = new Set();
const learnImports = (text, dir) => { for (const p of importsOf(tokens(text))) if (p.endsWith('.ngr') && !p.startsWith('/') && !isRemote(p)) modulesSeen.add(under(dir, p)); };
learnImports(src, progDir);
const moduleOk = (t) => modulesSeen.has(t) && inside(t, progDir) && !inside(t, homeReal) && !writableDirs.some((w) => inside(t, w));
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
const paths = [mainTrace, ...(extraTrace && extraTrace !== '-' ? [path.resolve(extraTrace)] : [])];   // «--слід -» — копія в stderr, як в ngr
if (!W && process.env.NIGREDO_TRACE_PATH_FILE) fs.writeFileSync(process.env.NIGREDO_TRACE_PATH_FILE, mainTrace);
const openNew = (p) => { try { return fs.openSync(p, 'wx'); } catch (e) { return fail(3, `✗ не вдалося створити слід: ${e.message}`); } };
const fds = W ? W.fds : [...paths.map(openNew), ...(extraTrace === '-' ? [2] : [])];
const stores = W ? W.stores : paths.map((p) => openNew(p + '.дані'));
let prev = '0'.repeat(16), n = 0, fromModule = 0, pendingBody = null;   // номер у сліді веде господар: він теж пише записи
const ZERO = '"0000000000000000"';
const sign = (b) => crypto.createHmac('sha256', key).update(b).digest('hex').slice(0, 16);
const HOST_EVENTS = new Set(['дія господаря', 'господар відмовив', 'ізоляція']);
const early = [];                     // читання модулів іде до першого запису модуля, а першим у сліді має стояти «початок»
// межа сліду тут теж: чесне ядро зупиниться саме (текст і місце — його), а зіпсоване без цього заллє диск. Запас — на різницю в підрахунку
let traced = 0, overflowing = false;
function spend(size) {
  traced += size;
  if (traced <= Number(tsize) + (1 << 20) || overflowing) return;
  overflowing = true;
  const msg = `✗ слід перевищив ${tsize} байтів (--слід-розмір) — програму зупинено`;
  hostRecord('помилка', { 'повідомлення': msg, 'від_господаря': true });
  fail(1, msg);
}
function writeTrace(line, body, mod = true) {
  n++;
  if (mod) {
    fromModule++;
    const k = `"№": ${fromModule}`;
    if (!line.startsWith(`{${k}, `) || !body.includes(k)) fail(4, `✗ модуль порушив нумерацію сліду (очікував ${fromModule})`);
    // записи господаря пише лише господар: модуль, що видає себе за нього, зупиняється. Дивимось на розібраний запис, як і читач сліду, а не на місце в рядку
    let rec;
    try { rec = JSON.parse(line); } catch { fail(4, '✗ запис сліду — не JSON'); }
    if (HOST_EVENTS.has(rec['подія']) || Object.hasOwn(rec, 'від_господаря')) fail(4, '✗ модуль видав свій запис за запис господаря');
    // перший запис читають як паспорт запуску: що знає господар, те модуль не перекаже інакше. Решта полів (час, аргументи, ліміти) — його слова
    if (fromModule === 1 && (rec['подія'] !== 'початок' || rec.sha256 !== sha256Prog || rec['інтерпретатор'] !== `альбедо:${sha256(wasmBytes)}`
      || rec['тека'] !== progDir || rec['дозволи_власника'] !== ownerSrc)) fail(4, '✗ перший запис сліду не про цей запуск');
    line = line.replace(k, `"№": ${n}`); body = body.replace(k, `"№": ${n}`);
  }
  const fill = (t, field, v) => { const k = `"${field}": ${ZERO}`, i = t.lastIndexOf(k); if (i < 0) fail(4, '✗ запис сліду без заглушки'); return t.slice(0, i) + `"${field}": "${v}"` + t.slice(i + k.length); };
  const signed = fill(body, 'попередній', prev);
  const h = sign(Buffer.from(signed));
  const out = fill(fill(line, 'попередній', prev), 'хеш', h);
  prev = h;
  for (const fd of fds) fs.writeSync(fd, out);
  spend(Buffer.byteLength(out));
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
function quotaOk(tool, target) {     // печатка й власник на те саме — одна квота, менша
  const rules = new Map();
  for (const [x, at] of [...wanted.map((w) => [w, scopeOf]), ...granted.map((g) => [g, ownerScope])]) {
    if (x.tool !== tool || x.quota === null) continue;
    const s = x.scope ? at(x.scope) : '';
    if (!s || inside(target, s)) rules.set(s, Math.min(rules.get(s) ?? Infinity, x.quota));
  }
  for (const [s, q] of rules) if ((used.get(`${tool}:${s}`) ?? 0) >= q) return false;
  for (const s of rules.keys()) used.set(`${tool}:${s}`, (used.get(`${tool}:${s}`) ?? 0) + 1);
  return true;
}
// власний свідок дій: модуль може не записати, що читав, але не прибере цього запису. Значень тут немає — лише що, де й скільки байтів
// до першого запису ядра чесно лише одне — читання модулів під час розбору; воно чекає, а все інше пишеться одразу, де б не сталося
function witness(event, fields) { if (fromModule || fields['інструмент'] !== 'модуль') hostRecord(event, fields); else early.push([event, fields]); }
function did(tool, target, field, value) { witness('дія господаря', { 'інструмент': tool, 'шлях': target, [field]: value }); }
function deny(tool, p, why) { witness('господар відмовив', { 'інструмент': tool, 'шлях': p, 'причина': why }); return -13; }
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
const errnoOf = (e) => (typeof e.errno === 'number' && e.errno < 0 ? e.errno : -5);
// труба буває неблокувальною й заповненою: писати доти, доки не прийме все, інакше вивід обірветься посередині
const nap = new Int32Array(new SharedArrayBuffer(4));
function writeAll(fd, b) {
  for (let off = 0; off < b.length;) {
    try { off += fs.writeSync(fd, b, off, b.length - off); } catch (e) {
      if (e.code === 'EPIPE') { hostRecord('помилка', { 'повідомлення': 'вивід обірвано: читач закрив трубу' }); process.exit(1); }   // як ngr: читач пішов, це не падіння
      if (e.code !== 'EAGAIN') throw e;
      Atomics.wait(nap, 0, 0, 2);
    }
  }
}
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
        const known = isModule ? moduleBytes.get(target) : undefined;
        const size = Math.min(known ? known.length : fs.fstatSync(fd).size, cap), b = known ? known.subarray(0, size) : Buffer.alloc(size);
        if (!known) fs.readSync(fd, b, 0, size, 0);
        if (isModule) learnImports(b.toString('utf8'), path.dirname(target));
        did(isModule ? 'модуль' : 'файл.читати', target, 'байтів', size);
        return reply(b);
      } finally { fs.closeSync(fd); }
    }
    if (op === 2) {                         // писати: теку перевіряємо, як нативно
      const dir = real(path.dirname(name)), target = path.join(dir, path.basename(name));
      if (forbidden(target)) return BigInt(deny('файл.писати', name, 'тека власника або слід'));
      const r = permit('файл.писати', dir, name); if (r) return BigInt(r);
      if (fs.lstatSync(target, { throwIfNoEntry: false })?.isSymbolicLink()) return BigInt(deny('файл.писати', name, 'символьне посилання'));
      fs.mkdirSync(dir, { recursive: true });
      const { O_WRONLY, O_CREAT, O_TRUNC, O_NOFOLLOW } = fs.constants;   // і між перевіркою й записом посилання не підставити
      fs.writeFileSync(target, bytes(q, m), { flag: O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW, mode: 0o644 });
      did('файл.писати', target, 'байтів', m);
      return reply(Buffer.alloc(0));
    }
    if (op === 3) {                         // список
      const target = real(name);
      const r = permit('файл.список', target, name); if (r) return BigInt(r);
      const names = fs.readdirSync(target);
      did('файл.список', target, 'імен', names.length);
      return reply(Buffer.from(names.join('\0')));
    }
    if (op === 4) {                         // що це: лише всередині коренів печатки
      if (name === '/') return reply(Buffer.from([2]));   // корінь — не таємниця, а ядро саме так упізнає шлях поза печаткою
      const target = real(name);
      if (!fileRoots.some((b) => inside(target, b)) || forbidden(target)) return reply(Buffer.from([0]));
      const st = fs.statSync(target);
      return reply(Buffer.from([st.isDirectory() ? 2 : 1]));
    }
    if (op === 5) {                         // справжній шлях: поза коренями печатки не розкриваємо нічого
      const target = real(name);
      if (fileRoots.some((b) => inside(target, b))) return reply(Buffer.from(target));
      // посилання з теки печатки назовні: куди веде, не кажемо, але ядро мусить знати, що воно поза межею — і відмовить тим самим текстом
      return reply(Buffer.from(fileRoots.some((b) => inside(path.resolve(name), b)) ? '/поза-печаткою' : path.resolve(name)));
    }
    deny('файл', name, 'невідома операція');
    return -38n;
  } catch (e) { return op === 4 ? reply(Buffer.from([0])) : BigInt(errnoOf(e)); }
}
// ---- база: сам SQLite у модулі, а його файли — тут. Запит читає сторож у модулі; який файл узагалі доступний, вирішує цей перелік,
// тож ATTACH чужої бази чи запис під «бд.читати» впираються сюди, навіть якщо модуль вирізав сторожа.
const dbFiles = new Map(), dbOurs = new Set(); let dbNext = 1, dbSpent = 0;
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
      const foreign = dbForeign(fd, kind);
      if (!foreign && kind !== 'main') dbOurs.add(target);
      const h = dbOpened({ fd, write: mode > 0, kind, foreign, path: target, spent: 0 });
      did(tool, target, 'розмір_файлу', fs.fstatSync(fd).size);
      return BigInt(h);
    }
    if (op === DB_DELETE) {                 // лише журнал: стерти саму базу SQLite не потрібно ніколи
      const name = text(p, l), target = real(name);
      if (dbKind(target) === 'main' || !dbSees(target, dbWrite)) return BigInt(deny('бд.писати', name, 'видаляти можна лише журнал'));
      // заголовок свого журналу SQLite лишає нульовим до синхронізації, тож журнал цього запуску впізнаємо за відкриттям, а не за байтами
      const fd = fs.openSync(target, fs.constants.O_RDONLY);
      const foreign = dbForeign(fd, dbKind(target));
      fs.closeSync(fd);
      if (foreign && !dbOurs.has(target)) return BigInt(deny('бд.писати', name, 'файл із назвою журналу — не журнал'));
      fs.unlinkSync(target);
      dbOurs.delete(target);
      did('бд.писати', target, 'видалено', 1);
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
    if (!f) { deny('бд', '', 'чужий номер файлу'); return -9n; }
    if (f.fd === null) return op === DB_CLOSE ? (dbFiles.delete(Number(a)), 0n) : op === DB_READ || op === DB_SIZE ? 0n : BigInt(deny('бд.писати', '', 'файл відкрито лише для читання'));
    if (op === DB_READ) {
      if (!f.foreign) return BigInt(fs.readSync(f.fd, bytes(p, l), 0, l, Number(b)));
      const got = Math.max(0, Math.min(l, fs.fstatSync(f.fd).size - Number(b)));
      bytes(p, l).fill(0);
      return BigInt(got);
    }
    if (op === DB_SIZE) return BigInt(fs.fstatSync(f.fd).size);
    if (op === DB_CLOSE) {
      fs.closeSync(f.fd); dbFiles.delete(Number(a));
      if (f.spent) did('бд.писати', f.path, 'байтів', f.spent);
      return 0n;
    }
    if (!f.write) return BigInt(deny('бд.писати', '', 'файл відкрито лише для читання'));
    if (f.foreign) return BigInt(deny('бд.писати', '', 'файл — не база'));
    if (op === DB_WRITE) {
      if (f.kind === 'main' && b === 0n && !(l >= 16 && bytes(p, 16).equals(MAGIC.main))) return BigInt(deny('бд.писати', '', 'записане — не база'));
      if ((dbSpent += l) > dbLimit) return BigInt(deny('бд.писати', '', 'понад межу запису'));
      f.spent += l;
      return BigInt(fs.writeSync(f.fd, bytes(p, l), 0, l, Number(b)));
    }
    if (op === DB_TRUNC) {
      const grow = Math.max(0, Number(b) - fs.fstatSync(f.fd).size);
      if ((dbSpent += grow) > dbLimit) return BigInt(deny('бд.писати', '', 'понад межу запису'));
      f.spent += grow;
      fs.ftruncateSync(f.fd, Number(b));
      did('бд.писати', f.path, 'новий_розмір', Number(b));
      return 0n;
    }
    if (op === DB_SYNC) { fs.fsyncSync(f.fd); return 0n; }
    deny('бд', '', 'невідома операція');
    return -38n;
  } catch (e) { return op === DB_ACCESS ? 0n : BigInt(errnoOf(e)); }
}
const hasClock = wanted.some((w) => w.tool === 'час');
let isolated = false;
const imports = { ngr: {
  out: (p, l) => { writeAll(1, bytes(p, l)); },
  err: (p, l) => { writeAll(2, Buffer.from(text(p, l) + '\n')); },
  body: (p, l) => { pendingBody = text(p, l); },
  trace: (p, l) => {
    const line = text(p, l);
    if (pendingBody === null) fail(4, '✗ запис сліду без канонічного тексту');
    writeTrace(line, pendingBody); pendingBody = null;
    if (!isolated) {                 // межа — не печатка ядра, а цей перелік імпортів: запис не залежить від того, що скаже модуль
      isolated = true;
      hostRecord('ізоляція', { 'ядро': 'wasm', 'закрито': ['мережа', 'процеси', ...(scopes('файл.писати').length || dbWrite.length ? [] : ['запис'])], 'причина': null });
      for (const [e, f] of early.splice(0)) hostRecord(e, f);
    }
  },
  store: (p, l) => { for (const fd of stores) fs.writeSync(fd, bytes(p, l)); spend(l); },
  fs: (op, p, l, q, m) => fsCall(op, p, l, q, m),
  fs_take: (d) => { bytes(d, pending.length).set(pending); },
  now: () => (hasClock ? BigInt(Math.floor(Date.now() / 1000)) : -1n),
  mono: () => process.hrtime.bigint() / 1000000n,
  random: (p, l) => { crypto.randomFillSync(bytes(p, l)); },
  db: (op, a, b, p, l) => dbCall(op, a, b, p, l),
} };
if (isMainThread) {
  const worker = new Worker(fileURLToPath(import.meta.url), { argv: [], workerData: { argv: process.argv, fds, stores, mainTrace }, resourceLimits: { stackSizeMb: 1024 } });
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
  worker.on('error', (e) => {
    stopping = true;
    const why = String(e.message ?? e).slice(0, 200);
    finish(4, `✗ модуль упав: ${why}${why === 'unreachable' ? ` (можливо, замало --памʼять ${memMb} МБ: стек ядра сам займає 1 ГБ)` : ''}`);
  });
  worker.on('exit', (code) => { if (!stopping) { clearTimeout(timer); process.exit(code); } });
} else {
// скільки памʼяті просить модуль — з його ж секції імпортів (env.memory, найменше сторінок), а не з тексту LinkError: той
// у кожного рушія свій (Node 20 і 22 пишуть по-різному, ПК 2026-11-07). Ядро просить 1 ГБ стека (нативно 4 ГБ): без нього
// глибока рекурсія була б падінням, а не помилкою мови; сторінки беруться лише торкнуті. Решта росте до стелі господаря.
function memInitial(b) {
  let i = 8;
  const leb = () => { let r = 0, k = 1, x; do { x = b[i++]; r += (x & 127) * k; k *= 128; } while (x & 128); return r; };
  const name = () => { const n = leb(), t = b.subarray(i, i + n).toString('utf8'); i += n; return t; };
  while (i < b.length) {
    const id = b[i++], size = leb(), end = i + size;
    if (id !== 2) { i = end; continue; }
    for (let n = leb(); n > 0; n--) {
      const m = name(), f = name(), kind = b[i++];
      if (kind === 0) leb();
      else if (kind === 1) { i++; const fl = b[i++]; leb(); if (fl & 1) leb(); }
      else if (kind === 2) { const fl = b[i++], min = leb(); if (fl & 1) leb(); if (m === 'env' && f === 'memory') return min; }
      else if (kind === 3) i += 2;
      else if (kind === 4) { i++; leb(); }
      else break;
    }
    break;
  }
  return 0;
}
const maximum = memMb * 16, initial = memInitial(wasmBytes);
if (initial > maximum) fail(2, `✗ --памʼять ${memMb} МБ: модуль просить більше (стек ядра сам займає 1 ГБ)`);
const memory = new WebAssembly.Memory({ initial, maximum });
imports.env = { memory };
const inst = new WebAssembly.Instance(mod, imports);
mem = memory;
const cfg = Buffer.from([progPath, progDir, progSha, now.toISOString().slice(0, 19) + '+00:00', crypto.randomBytes(6).toString('hex'),
  `альбедо:${sha256(wasmBytes)}`, ownerSrc, seed, steps, size, tsize, real(HOME), String(progArgs.length), ...progArgs, ...allowed].join('\0'));
const put = (b) => { const a = inst.exports.ngr_alloc(b.length); bytes(a, b.length).set(b); return a; };
const cp = put(cfg), sp = put(srcBytes);
const t = process.hrtime.bigint();
const code = inst.exports.ngr_run(cp, cfg.length, sp, srcBytes.length);
for (const f of dbFiles.values()) if (f.spent) did('бд.писати', f.path, 'байтів', f.spent);   // модуль міг не закрити файл
if (showTime) fs.writeSync(2, `час: ${Number(process.hrtime.bigint() - t) / 1e6} мс, записів сліду: ${n}\n`);
if (code === 120 && n === 0) {           // нічого не виконано — нема й сліду; модуль узагалі нічого не встиг, тож і стирати нічого, крім порожніх файлів
  for (const p of paths) for (const f of [p, p + '.дані']) fs.rmSync(f, { force: true });
  process.exit(120);
}
for (const [e, f] of early.splice(0)) hostRecord(e, f);
if (code === 120) {                      // код каже модуль, а не господар: він нічого не стирає, бо модуль уже діяв
  const msg = '✗ модуль сказав «не виконую», хоч уже писав слід: слід лишається';
  hostRecord('помилка', { 'повідомлення': msg, 'від_господаря': true });
  fail(4, msg);
}
process.exit(code);
}
