// Альбедо, прототип М0: господар. Модуль не має нічого, крім імпортів нижче.
import fs from 'node:fs';
const [wasmPath, prog, ...rest] = process.argv.slice(2);
const mod = new WebAssembly.Module(fs.readFileSync(wasmPath));
if (rest.includes('--імпорти')) {
  for (const i of WebAssembly.Module.imports(mod)) console.log(`${i.module}.${i.name}`);
  process.exit(0);
}
let mem;
const text = (p, n) => Buffer.from(mem.buffer, p, n).toString('utf8');
const none = () => 0;                 // ОС-виклики ядра: у модулі їх немає — відмова
const env = {};
for (const i of WebAssembly.Module.imports(mod)) if (i.module === 'env') env[i.name] = none;
const lines = [];
const inst = new WebAssembly.Instance(mod, { env, ngr: {
  out: (p, n) => { process.stdout.write(Buffer.from(mem.buffer, p, n)); },
  err: (p, n) => { process.stderr.write(text(p, n) + '\n'); },
  trace: (p, n) => { lines.push(text(p, n)); },
} });
mem = inst.exports.memory;
const src = fs.readFileSync(prog);
const p = inst.exports.ngr_alloc(src.length);
Buffer.from(mem.buffer, p, src.length).set(src);
const t = process.hrtime.bigint();
const code = inst.exports.ngr_run(p, src.length, 2000000000n);
if (rest.includes('--час')) process.stderr.write(`час: ${Number(process.hrtime.bigint() - t) / 1e6} мс, записів сліду: ${lines.length}\n`);
process.exit(code);
