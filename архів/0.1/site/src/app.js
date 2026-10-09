'use strict';

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};
const calm = matchMedia('(prefers-reduced-motion: reduce)').matches;
const ALL = NGR.groups.flatMap((g) => g.glyphs.map((x) => x.g))
  .concat(Array.from('ᚠᚢᚦᚨᚱᚲᚷᚹᚺᚾᛁᛃᛇᛈᛉᛋᛏᛒᛖᛗᛚᛜᛞᛟ０１２３４５６７８９⟪⟫⌜⌟⟬⟭⸸'));
const pick = () => ALL[Math.floor(Math.random() * ALL.length)];

// --- кільце навколо чорного сонця
{
  const ring = $('orbit-text');
  ring.textContent = NGR.groups.flatMap((g) => g.glyphs.map((x) => x.g)).join('');
  ring.setAttribute('textLength', '512');
  ring.setAttribute('lengthAdjust', 'spacing');
}

// --- зразки
const code = $('code');
let current = 0;
let busy = false;

function render(i) {
  const ex = NGR.examples[i];
  current = i;
  $('file').textContent = ex.file;
  $('about').textContent = ex.about;
  $('out').textContent = ex.out;
  const gloss = new Map(ex.lines.map((l) => [l.no, l.gloss]));
  code.replaceChildren();
  ex.code.split('\n').forEach((line, k) => {
    const ln = el('span', 'ln');
    if (line.trimStart().startsWith('⸸')) ln.classList.add('comment');
    let inComment = false;
    for (const ch of Array.from(line)) {
      if (ch === '⸸') inComment = true;
      const s = el('span', 'c', ch);
      if (inComment) s.style.color = 'var(--dim)';
      ln.append(s);
    }
    if (!line) ln.textContent = ' ';
    code.append(ln);
    const g = gloss.get(k + 1);
    if (g) code.append(el('span', 'gloss', g.join(' · ')));
  });
  document.querySelectorAll('.tab').forEach((t, j) =>
    t.setAttribute('aria-selected', String(j === i)));
}

NGR.examples.forEach((ex, i) => {
  const t = el('button', 'tab', ex.title);
  t.setAttribute('role', 'tab');
  t.addEventListener('click', () => { if (!busy) { render(i); $('status').textContent = ''; } });
  $('tabs').append(t);
});
render(0);

// --- «спроба прочитати»: гліфи тікають з-під погляду
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const live = () => [...code.querySelectorAll('span.c')].filter((s) => s.textContent.trim());

async function tryRead() {
  if (busy) return;
  busy = true;
  $('read').disabled = true;
  const status = $('status');
  status.textContent = 'Читаю…';
  const spans = live();
  spans.forEach((s) => { s.dataset.o = s.textContent; });

  const until = Date.now() + 1100;
  while (Date.now() < until) {
    for (let k = 0; k < spans.length / 6; k++) {
      spans[Math.floor(Math.random() * spans.length)].textContent = pick();
    }
    await sleep(55);
  }
  status.textContent = 'Не вдалося. Цей код не для вас.';
  if (!calm) {
    spans.forEach((s) => {
      s.style.transitionDelay = `${Math.random() * 0.5}s`;
      s.style.transform = `translate(${(Math.random() - 0.5) * 80}px, ${120 + Math.random() * 260}px) rotate(${(Math.random() - 0.5) * 540}deg)`;
      s.classList.add('fall');
    });
    await sleep(2300);
  }
  spans.forEach((s) => {
    s.style.transitionDelay = `${Math.random() * 0.4}s`;
    s.style.transform = '';
    s.classList.remove('fall');
    s.textContent = s.dataset.o;
  });
  await sleep(calm ? 200 : 1500);
  spans.forEach((s) => { s.style.transitionDelay = ''; });
  status.textContent = 'Код знову на місці. Ключ — у власника ⚿';
  $('read').disabled = false;
  busy = false;
}
$('read').addEventListener('click', tryRead);

// дотик або курсор — гліф під ним спалахує чужим
function flicker(e) {
  if (busy) return;
  const s = document.elementFromPoint(e.clientX, e.clientY);
  if (!s || !s.classList.contains('c') || !s.textContent.trim() || s.dataset.hot) return;
  const original = s.textContent;
  s.dataset.hot = '1';
  s.textContent = pick();
  s.classList.add('hot');
  setTimeout(() => {
    s.textContent = original;
    s.classList.remove('hot');
    delete s.dataset.hot;
  }, 280);
}
code.addEventListener('pointermove', flicker);
code.addEventListener('pointerdown', flicker);

// --- ключ: переклад кожного рядка (вивід `nigredo.py --розбір`)
$('decode').addEventListener('click', () => {
  const on = code.classList.toggle('decoded');
  $('decode').setAttribute('aria-pressed', String(on));
  $('status').textContent = on
    ? 'Ключ прийнято. Під кожним рядком — його переклад з `--розбір`.'
    : '';
});

// --- алфавіт
for (const group of NGR.groups) {
  const box = el('div', 'group');
  box.append(el('h3', '', group.name));
  const cards = el('div', 'cards');
  for (const { g, m } of group.glyphs) {
    const c = el('button', 'card');
    c.setAttribute('aria-label', `${g} — ${m}`);
    c.append(el('span', 'face', g), el('span', 'back', m));
    c.addEventListener('click', () => {
      c.classList.add('open');
      clearTimeout(c._t);
      c._t = setTimeout(() => c.classList.remove('open'), 2600);
    });
    cards.append(c);
  }
  box.append(cards);
  $('groups').append(box);
}
for (const { g, m } of NGR.structure) {
  const row = el('div');
  row.append(el('span', 'glyph', g), el('span', '', m));
  $('structure').append(row);
}

// --- ключ власника
$('trace').textContent = NGR.examples.find((x) => x.trace).trace;
$('spec').textContent = NGR.spec;
