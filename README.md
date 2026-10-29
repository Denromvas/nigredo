# Nigredo

> **English** · [Українська ↓](#українською)

**A programming language that AI agents write and read — a black box for people, with the key held by the owner.**
Before a program runs, the owner sees what it *may* do; afterwards, they can verify what it *did*.

**Try it in the browser:** [denromvas.github.io/nigredo](https://denromvas.github.io/nigredo/) — the real interpreter
(Pyodide): examples, the seal, the human translation, checks before running, the signed trace.

```
🜂 「poll the seers, keep confident answers」 【「оракул」】
← answers μ【「чи сіль тверда?」 「чи сірка горить?」】 λq
  🜁 「seer」 「ask the oracle」 【「оракул」】 🜔оракул q
» ρ ⚗answers 0.6
```

**Why a new language, if agents already write Python?** Because of one property Python cannot give inside
a process: a Nigredo program has **no ambient authority**. Its first line — the *seal* — declares the intent and
the complete list of permissions (folders, hosts, agents). The interpreter checks the seal against the owner's
permissions before running and checks every tool call at run time. An agent that receives a program from another
agent can decide whether to run it **by reading one line**.

- **Seal** — declared, statically checked, enforced capabilities; sub-agents get only a subset of their parent's.
- **Signed trace** — written by the interpreter, not the program; HMAC-chained; edits, insertions and truncation are
  detected. `ngr --повторити` replays a run from its trace without touching the world.
- **Confidence as semantics** — every value carries a confidence; nothing computed from (or under the control of)
  an uncertain value is more confident than it, including through selection and control flow.
- **Built for LLMs** — prefix notation with fixed arity (no stack to track), glyphs chosen by measuring tokenizers,
  errors before running with hints; about as many tokens as Python without the seal.
- **Fast to start, about CPython on data** — the native engine **Athanor** (Rust, no dependencies) starts in ~6 ms
  (CPython ~26 ms), so small agent tasks take about half the time; on longer computations it is faster than CPython on
  the measured loops and slower on a few shapes (see the table). It gives the same output and the same signed trace
  as the reference interpreter; what it cannot do it hands to the reference before acting, and every divergence
  found is treated as a bug.
- **Black box with a key** — no human keywords; the owner reads any program through `ngr --печатка` (what it may do),
  `ngr --розбір` (a translation) and the signed trace, and can grant extra rights to one exact program
  (`ngr --схвалити`: change a byte and the grant is gone).

## Measured against Python

Same tasks in both languages (`bench/`), models writing both from the same task (`bench/м2/`). Details and caveats —
[`bench/РЕЗУЛЬТАТИ.md`](bench/РЕЗУЛЬТАТИ.md), [`bench/м2/`](bench/м2/), [`bench/великі/`](bench/великі/).

| | Nigredo | Python |
|---|---|---|
| Agent tasks solved (12) | 12/12 | 12/12 |
| Program length, **with** the seal | 1.01× (author's); 0.89× (models' first-try programs) | 1× |
| Real bugs caught before running (14) | 9 | 3 with pyflakes |
| Models right on the first try, held-out tasks (3 runs × 10) | Sonnet 27/30, Haiku 21/30 | Sonnet 27/30, Haiku 23/30 |
| Speed, 12 small agent tasks (median wall time) | **0.44×** | 1× |
| Speed, 200k words / 200k-step loop / 25k-record JSON (CPU time) | **0.67× / 0.42× / 0.91×** | 1× |
| Speed, the loop through a named function / with `¿` in it (CPU time) | **0.35× / 0.47×** | 1× |
| Speed, exact decimals (Python: `Decimal`) / building strings / a `↻` loop with list state (CPU time) | **0.65× / 0.89× / 0.67×** | 1× |
| The owner knows what a program may do and did | seal, signed trace, replay, dry run | — |

Measured on a phone (Termux); Nigredo's numbers include its own trace and replay store. Small tasks are mostly
interpreter start-up; the two tasks that use the network are handed to the reference and are slower than Python;
the 200k-step loop is a shape Athanor has a fast path for; a `↻` loop that builds a new list every step was 1.7×
slower until 2026-10-27, now all eight large-data tasks are faster than Python. On a quiet phone the spread between runs is ~10–20 %;
on a loaded one (judges measured while other judges ran) absolute times were 1.4–2.8× higher for Athanor and
1.4–1.7× for the reference — the ratios above are from a quiet run.

**Which bugs are caught before running** (`bench/помилки/`: 14 real bugs and 4 that exist only in Nigredo's model):

| Class of bug | Python | + pyflakes | Nigredo |
|---|---|---|---|
| Unclosed string | ✓ | ✓ | ✓ |
| Typo in a name; a look-alike name (Cyrillic `х` for Latin `x`) | — | ✓ | ✓ |
| Wrong argument types: string + number, string < number, calling a number, indexing a list with a string | — | — | ✓ |
| Missing argument; division by a literal zero | — | — | ✓ |
| Typo in a dictionary key; a wrong type passed through a parameter; a computed zero; index out of range; a non-number parsed from text | — | — | — (only when running) |
| Writing outside the allowed folder; network without permission; reassigning a name | not a Python concept | | ✓ |

No bug in the set is caught by Python + pyflakes and missed by Nigredo; 5 of the 14 real ones are caught by neither.
On 10 correct programs (`bench/правильні/`) Nigredo raised no false alarm. A catastrophic regular expression is not
an error in Nigredo at all — its regex engine does not backtrack.

## Try it

```
sh athanor/зібрати.sh                                  # native engine (optional; Python ≥ 3.10 is enough)
ngr examples/ahent.ngr                                 # ngr = athanor/target/<host>/release/athanor or interpreter/ngr.py
ngr --печатка examples/fajly.ngr                       # what the program may do
ngr --розбір examples/chysla.ngr                       # translation for the owner
python3 interpreter/test.py                            # all tests (NGR_TEST_BIN=… — the same tests on Athanor)
claude mcp add nigredo -- python3 mcp/nigredo_mcp.py   # give it to any MCP-capable agent
```

The owner's permissions live in `~/.nigredo/дозволи.json`, e.g. `{"дозволено": ["оракул", "файл.читати:/home/me/data"]}`;
without it only toy tools are available. [`ДЛЯ_АГЕНТІВ.md`](ДЛЯ_АГЕНТІВ.md) — the cheat sheet with every glyph;
[`spec/SPEC.md`](spec/SPEC.md) — the specification (Ukrainian, like the language's own words).

Also in the repo: a text browser for agents written in Nigredo itself ([`браузер/`](браузер/)), the MCP server
([`mcp/`](mcp/)), syntax highlighting for VS Code ([`editors/vscode/`](editors/vscode/)).

## How it is checked

Every version is frozen and handed to a council of agent judges — separate Claude sessions in different roles
(Skeptic, Practitioner, Linguist, Security Auditor, Newcomer, Orchestrator) plus Gemini — who solve tasks and attack
the boundary; every finding becomes a negative test. Athanor is checked against the reference interpreter on every
program in the repo and on generated data (regex patterns, Unicode case, numbers, limits); the ninth court still
found divergences (final sigma, `\N{…}` in a pattern from data, the trace-size limit, SQLite steps, stack depth),
and its re-reviews found that SQLite still gave a program the clock and randomness without the rights — through a
column `DEFAULT`, then through the program's own trigger setting rowid 2⁶³−1, then through a leading `;` (the guard's
pre-compilation failed and the failure was ignored) and the `sqlite_sequence` table — plus a trace copy a program could
corrupt from a database folder of its seal, a crash on deep `☂`/`¿` and an `(?i)` that was not Python's — all fixed
with tests on both engines; the SQLite guard now fails closed. The fifth re-review confirmed the fixes 7:0, and 0.8 was
announced (2026-10-21). Its wishes are 0.8.1: names with letters that Unicode does not recommend for identifiers (UTS #39
Identifier_Status — `ƻ` ≈ 2, `ꜫ` ≈ 3) are errors as a class rather than by a list, an old database already at the rowid
limit gives a separate “precautionary refusal” in the trace instead of “denied”, and the seal check warns about a file
given where writing needs a folder. A short re-review (6:1) found that the new trace event could hide a real attempt:
now a refusal is precautionary only when neither the authorizer nor SQLite's own bytecode finds anything outside the
rights in the query, and Hebrew and Arabic are no longer allowed in names (a bidi viewer reorders prefix arguments). The
next re-review (6:1) found the same class left — an explicit rowid 2⁶³−1 on such a database, a quota the program set
for itself, and raw page writes through `sqlite_dbpage` — now the refusal is precautionary only when SQLite itself
would have to take a random rowid, an exhausted quota no longer hides an attempt, and `sqlite_dbpage` is refused. The
third short re-review (5:2) found that a query could call the interpreter's internal function that marks a refusal as
precautionary: now only the interpreter's own temporary triggers can call it; and the pre-check, the guard triggers and
the query itself now run in one write transaction, so another process can no longer change the schema in between. The
fourth (5:2 “A”) confirmed it; two judges found the database schema itself (a column `DEFAULT`) could still call that
function, so it now gets a fresh random name for every query, and the old name is a decoy that is always refused. The
fifth (5:2 “A”) confirmed that; two judges found the reference interpreter let a program read that random name
through SQLite's `sqlite_stmt` virtual table, so virtual tables are now an allowlist (`json_each`, `json_tree` and the
database's own tables), and the run, an exhausted quota and `--сухо` now share one pre-check. Network tools no longer
truncate silently: a response over 1 000 000 bytes (10⁶, not MiB), cut short or not UTF-8 is an error, and 30 s bounds
the whole request. The
sixth (7:0 “A”, with a condition) found the allowlist checked the name, not the `(schema, name)` pair SQLite actually
resolves — `temp.dbstat` read the internal module when a real table `dbstat` existed, and a schema-declared virtual
table on an internal module (`dbstat`, `sqlite_dbpage`) was reachable under its own name — so the allowlist now checks,
through the query plan, which table SQLite really opens; with that fix **0.8.1 was announced (2026-10-28)**. The
judges' wishes followed: a refusal now says whether the database schema *calls* the decoy or only *mentions* it (a
string, a comment, a column or table name), and `random()` is refused with the same text in all three modes. **0.9 (announced
2026-10-29):** modules from git
pinned by hash, `⊃ 「github.com/owner/repo@COMMIT/path.ngr#sha256=CONTENT」`: a module's identity is the sha256 of its
bytes (the address is only the author's words — GitHub serves fork commits under the original's name, and the store
keeps content by hash, not where it came from), only a separate `ngr --отримати` step touches the network, never a
run, and a module from the network only computes on what it is given (no permissions, printing, memory or program
arguments — checked before the run and again while it runs). Court 10 (7:0 «B») found no breach but untrue texts in the
owner's key; review 10b (4:2 «A») found more (whose words an error is), and the narrow confirmation 10c (2:0 «A») one more
(quotes in the trace summary) — all fixed with tests in both executors before the announcement. Before the first run of
someone else's program with network modules, agents run `ngr --отримати PROGRAM --звірити` (it asks the source whether
the address still serves the pinned content; a non-zero code means do not run). **In development — 0.10-dev**
(phase 6, the owner's decisions; proposal `spec/пропозиції/фаза6.md`):
- **OS lock.** A group of actions the seal does not ask for at all — network, processes, writing files — is closed by
  the **kernel** (seccomp), not only by the interpreter. Child processes inherit it. Some tools open more than their
  own group: `процес` and `бд.читати` also open writing (commands write `/dev/null`, SQLite its temporary files), and
  `python` opens processes (to start the bridge process). `ngr --перевірити-ізоляцію` shows whether this machine's
  kernel holds it.
- **Python bridge.** Only functions from the owner's list (`🜔python 「statistics.median」 【…】`), each in a separate
  process under the full OS lock and an audit watch (reading outside Python's own folders is refused and logged). Data
  only goes in and out. Whether a function is pure is the owner's call: one that runs arbitrary code can still read
  any file of the user.
- **Author signature.** Ed25519 with no dependencies, covering the seal and every module. The owner can grant rights by
  key (`"для_авторів"`).

Court 11 voted 7:0 «Б» (the kernel lock holds, the signature cannot be forged; quotas, texts and a few edge cases needed
fixing); re-review 11б gave 2 «А» and 5 narrow «Б» (no new breach; Atanor let full-width look-alikes of the signature
line through, and a module from an author key's write folder was accepted as a module). All fixed with tests; a narrow
confirmation (11в) comes next. The latest comparison report is
[`athanor/ЗВІРКА.md`](athanor/ЗВІРКА.md); history and protocols — [`konsylium/`](konsylium/).

**Honest limits:** Nigredo is a transparency and audit tool, **not an OS sandbox** — an agent with shell access can
bypass it entirely. Confidence is a conservative bound, not a probability. The language and both engines were written
by Claude (Anthropic) as an agent; the project owner is Denis Romaniuk. MIT license.

---

<a id="українською"></a>

# Nigredo (українською)

**Мова програмування, яку пишуть і читають ШІ-агенти, — чорний ящик для людей, але ключ у власника.** До запуску
власник бачить, що програма *може* зробити, а після — перевіряє, що вона *зробила*.

*Nigredo* — «почорніння», перша стадія алхімічного Великого Діла: розкласти, щоб зібрати заново.

```
🜂 「опитати провидців і лишити впевнені відповіді」 【「оракул」】
← відповіді μ【「чи сіль тверда?」 「чи сірка горить?」 「чи світ чорніє?」】 λq
  🜁 「провидець」 「спитати оракула」 【「оракул」】 🜔оракул q
← впевнені ⚗відповіді 0.6
» ρвпевнені
```

`ngr --розбір` перекладає це для людини:

```
ПЕЧАТКА — намір: «опитати провидців і лишити впевнені відповіді»; дозволи: оракул
відповіді ← список: для кожного q з [...] — субагент «провидець» (намір «спитати оракула»; дозволи: оракул) виконує:
  інструмент оракул(q)
впевнені ← з відповіді лишити впевнені щонайменше на 0.6
надрукувати довжина(впевнені)
```

## Чим вона відрізняється

- **Печатка.** Перший рядок кожної програми — намір і *повний* перелік дозволів (теки, хости, агенти).
  Інтерпретатор до запуску звіряє її з дозволами власника, а під час виконання — кожен виклик із правами
  агента, що його робить. У мові немає «довкілля»: доторкнутися до світу можна лише через інструмент із печатки.
- **Слід, який веде інтерпретатор, а не програма.** Завжди, у теці власника, підписаний HMAC і зчеплений;
  зміну, вставку чи обрізання виявляє `ngr --перевірити-слід`, а `ngr --повторити` відтворює запуск без дій у світі.
- **Впевненість як семантика.** Кожне значення несе впевненість ∈ [0, 1]; усе, що з нього обчислено, — не
  впевненіше за джерело (через дані, контейнери й керування). Підняти її можна лише явно, і це в сліді.
- **Делегування з підмножиною прав.** Субагент отримує не більше дозволів, ніж батько; значення незмінні.
- **Для моделей:** префіксний запис із фіксованою арністю (без стека в голові), гліфи обрано за вимірами
  токенізаторів, помилки — до запуску й з підказками.
- **Швидкий старт, на даних — близько CPython:** нативний виконавець **Атанор** (Rust, без залежностей) стартує за
  ~6 мс (CPython — ~26 мс), тож малі задачі агента вдвічі швидші; на довших обчисленнях — швидший за CPython на
  виміряних циклах і повільніший на окремих формах (таблиця нижче). Вивід і підписаний слід — ті самі, що в
  еталонного інтерпретатора; чого не вміє, віддає еталону ще до дії, а кожна знайдена розбіжність — вада.
- **Ключ у власника:** `ngr --печатка` (що програмі дозволено), `ngr --розбір` (переклад), підписаний слід; права
  саме одній програмі — `ngr --схвалити` (змінений байт — і схвалення не діє).

## Порівняння з Python

Ті самі задачі обома мовами (`bench/`), моделі пишуть обидва рішення з того самого завдання (`bench/м2/`). Подробиці й
застереження — [`bench/РЕЗУЛЬТАТИ.md`](bench/РЕЗУЛЬТАТИ.md), [`bench/м2/`](bench/м2/), [`bench/великі/`](bench/великі/).

| | Nigredo | Python |
|---|---|---|
| Розвʼязано задач агента (12) | 12/12 | 12/12 |
| Довжина програм **з** печаткою | 1,01× (автора); 0,89× (програми моделей з першої спроби) | 1× |
| Справжніх помилок спіймано до запуску (14) | 9 | 3 з pyflakes |
| Моделі правильно з першої спроби, відкладені задачі (3 прогони × 10) | Sonnet 27/30, Haiku 21/30 | Sonnet 27/30, Haiku 23/30 |
| Швидкість, 12 малих задач агента (медіана реального часу) | **0,44×** | 1× |
| Швидкість, 200 тис. слів / цикл на 200 тис. кроків / JSON на 25 тис. записів (процесорний час) | **0,67× / 0,42× / 0,91×** | 1× |
| Швидкість, той самий цикл через іменовану функцію / з `¿` у ній (процесорний час) | **0,35× / 0,47×** | 1× |
| Швидкість, точні дроби (у Python — `Decimal`) / складання рядків / цикл `↻` зі станом-списком (процесорний час) | **0,65× / 0,89× / 0,67×** | 1× |
| Власник знає, що програмі дозволено й що вона зробила | печатка, підписаний слід, повтор, сухий прогін | — |

Виміряно на телефоні (Termux); у числах Nigredo — і її власні слід та сховище повтору. Малі задачі — здебільшого
запуск інтерпретатора; дві задачі з мережею Атанор віддає еталону, і там він повільніший за Python; цикл на 200 тис.
кроків — форма зі швидкою доріжкою Атанора; `↻`, що щокроку будує новий список, до 2026-10-27 був у 1,7 раза
повільніший, тепер усі вісім задач на великих даних — швидші за Python. На спокійному телефоні розкид між прогонами — ~10–20 %; на навантаженому (судді
міряли, поки працювали інші) абсолютний час Атанора був у 1,4–2,8 раза більший, еталона — у 1,4–1,7: відношення
вище — зі спокійного прогону.

**Які помилки ловляться до запуску** (`bench/помилки/`: 14 справжніх і 4, що існують лише в моделі Nigredo):

| Клас помилки | Python | + pyflakes | Nigredo |
|---|---|---|---|
| Незакритий рядок | ✓ | ✓ | ✓ |
| Описка в імені; двійник імені (кирилична `х` замість латинської `x`) | — | ✓ | ✓ |
| Не ті типи аргументів: рядок + число, рядок < число, виклик числа, індекс списку рядком | — | — | ✓ |
| Бракує аргументу; ділення на буквальний нуль | — | — | ✓ |
| Описка в ключі словника; не той тип через параметр; обчислений нуль; індекс поза межами; не-число з тексту | — | — | — (лише під час роботи) |
| Запис поза дозволеною текою; мережа без дозволу; перепризначення імені | у Python такого поняття немає | | ✓ |

Помилки, яку Python + pyflakes ловить, а Nigredo — ні, у наборі немає; 5 із 14 справжніх не ловить жодна сторона. На
10 правильних програмах (`bench/правильні/`) хибних тривог Nigredo — 0. Катастрофічний регулярний вираз у Nigredo
взагалі не помилка: рушій регулярок без відкатів.

## Запуск

```
sh athanor/зібрати.sh                                  # нативний виконавець (за бажанням; досить Python ≥ 3.10)
ngr examples/ahent.ngr                                 # ngr = athanor/target/<ціль>/release/athanor або interpreter/ngr.py
ngr --печатка examples/fajly.ngr                       # що програмі дозволено
ngr --розбір examples/chysla.ngr                       # переклад для власника
python3 interpreter/test.py                            # усі тести (NGR_TEST_BIN=… — ті самі тести Атанором)
claude mcp add nigredo -- python3 mcp/nigredo_mcp.py   # дати мову будь-якому агентові з MCP
```

Дозволи власника — `~/.nigredo/дозволи.json`, наприклад `{"дозволено": ["оракул", "файл.читати:/home/я/дані"]}`; без нього
доступні лише іграшкові інструменти. [`ДЛЯ_АГЕНТІВ.md`](ДЛЯ_АГЕНТІВ.md) — памʼятка з усіма гліфами;
[`spec/SPEC.md`](spec/SPEC.md) — специфікація.

Ще в репозиторії: текстовий браузер для агентів, написаний самою Nigredo ([`браузер/`](браузер/)), MCP-сервер
([`mcp/`](mcp/)), підсвітка для VS Code ([`editors/vscode/`](editors/vscode/)).

## Як перевіряють

Кожну версію заморожують і віддають консиліуму агентів-суддів — окремим сесіям Claude з різними ролями (Скептик,
Практик, Мовознавець, Аудитор безпеки, Новачок, Оркестратор) і Gemini: вони розвʼязують задачі й атакують межу;
кожна знахідка стає негативним тестом. Атанор звіряють з еталонним інтерпретатором на всіх програмах репозиторію й
на згенерованих даних (шаблони регулярок, регістр Unicode, числа, межі); девʼятий суд однаково знайшов розбіжності
(кінцева сигма, `\N{…}` у шаблоні з даних, межа сліду, кроки SQLite, глибина стеку), а повторні огляди — що SQLite
досі давав програмі годинник і випадковість без прав (через `DEFAULT` стовпця, потім через власний тригер програми,
що ставить rowid 2⁶³−1, далі через `;` на початку запиту — попередня компіляція захисту падала, і це ковтали, — і
таблицю `sqlite_sequence`), копію сліду, яку програма могла зіпсувати з теки бази своєї печатки, аварію на глибоких
`☂`/`¿` і `(?i)`, не такий, як у Python, — усе виправлено з тестами обома виконавцями; захист SQLite тепер закритий за
замовчуванням. Пʼятий повторний огляд підтвердив виправлення 7:0, і 0.8 оголошено (2026-10-21). Його побажання — у
0.8.1: імена з літерами, яких Unicode не радить для ідентифікаторів (UTS #39 Identifier_Status — `ƻ` ≈ 2, `ꜫ` ≈ 3), —
помилка класом, а не списком; стара база, що вже на межі rowid, дає в сліді окрему «запобіжну відмову», а не
«заборонено»; перевірка печатки попереджає про файл там, де для запису потрібна тека. Короткий огляд (6:1) знайшов,
що нова подія сліду могла сховати справжню спробу: тепер відмова запобіжна, лише коли ні authorizer, ні байткод SQLite
не знайшли в запиті нічого поза правами; іврит і арабське в іменах — помилка (переглядач з bidi переставляє аргументи
префіксного запису). Наступний огляд (6:1) знайшов залишки того самого класу — явний rowid 2⁶³−1 на такій базі, квоту, яку
програма оголосила собі сама, і запис сирих сторінок через `sqlite_dbpage`: тепер відмова запобіжна, лише коли rowid
навмання взяв би сам SQLite, вичерпана квота спроби не ховає, а `sqlite_dbpage` — відмова. Третій короткий огляд (5:2)
знайшов, що запит міг сам покликати службову функцію інтерпретатора, яка позначає відмову запобіжною: тепер її кличуть
лише тимчасові тригери самого інтерпретатора; а попередня перевірка, тригери захисту й сам запит тепер ідуть в одній
транзакції запису, тож інший процес між ними схеми не змінить. Четвертий (5:2 «А») це підтвердив; двоє суддів знайшли,
що функцію ще могла покликати сама схема бази (`DEFAULT` стовпця), тож тепер вона щоразу має нову випадкову назву, а
стара назва — приманка, на яку завжди відмова. П'ятий (5:2 «А») це підтвердив; двоє суддів знайшли, що еталон давав
програмі прочитати цю випадкову назву через віртуальну таблицю SQLite `sqlite_stmt`, тож віртуальні таблиці тепер —
перелік дозволених (`json_each`, `json_tree` і таблиці самої бази), а запуск, вичерпана квота й `--сухо` мають один
попередній прохід. Мережа більше не обрізає мовчки: відповідь понад 1 000 000 байтів (10⁶, не МіБ), обірвана чи не
UTF-8 — помилка, а 30 с —
на весь запит. Шостий огляд (7:0 «А» з умовою) знайшов, що перелік звіряв назву, а не пару «схема.назва», яку
розвʼязує SQLite: `temp.dbstat` при справжній таблиці `dbstat` читав службовий модуль, а схемну віртуальну таблицю на
внутрішньому модулі (`dbstat`, `sqlite_dbpage`) можна було дістати під власною назвою — тож перелік тепер звіряє за
планом запиту, яку таблицю SQLite відкриває насправді; з цим виправленням **0.8.1 оголошено (2026-10-28)**. Слідом —
побажання суддів: відмова каже, чи схема бази приманку **кличе**, чи лише **згадує** (рядок, коментар, назва стовпця
чи таблиці), а `random()` має один текст відмови в усіх трьох режимах. **0.9 (оголошено 2026-10-29):** модулі з git, закріплені
хешем, `⊃ 「github.com/власник/репо@КОМІТ/шлях.ngr#sha256=ВМІСТ」`: тотожність модуля — sha256 його байтів (адреса —
лише слова автора: GitHub віддає за назвою оригіналу й коміти з форків, а сховище памʼятає вміст за хешем, а не звідки
його взято), у мережу ходить лише окремий крок `ngr --отримати`, а не запуск, і модуль з мережі лише обчислює над тим,
що йому передали (жодних дозволів, друку, памʼяті й аргументів програми — перевіряється до запуску й ще раз під час
нього). Суд 10 (7:0 «Б») зламу не знайшов, лише неправдиві тексти ключа власника; огляд 10б (4:2 «А») знайшов ще (чиї
слова в помилці), вузьке підтвердження 10в (2:0 «А») — ще одне (лапки в підсумку сліду): усе виправлено з тестами обома
виконавцями до оголошення. Перед першим запуском чужої програми з модулями з мережі агенти виконують `ngr --отримати
ПРОГРАМА --звірити` (питає джерело, чи віддає адреса закріплений вміст; код ≠ 0 — не запускати). **У розробці —
0.10-dev** (фаза 6, рішення власника; пропозиція `spec/пропозиції/фаза6.md`):
- **Замок ОС.** Групу дій, якої печатка не просить зовсім, — мережу, процеси, запис — закриває **ядро** (seccomp), а не
  лише інтерпретатор. Дочірні процеси його успадковують. Дехто відкриває більше за свою групу: `процес` і `бд.читати`
  — ще й запис (команди пишуть `/dev/null`, SQLite — тимчасові файли), `python` — процеси (запустити процес моста).
  `ngr --перевірити-ізоляцію` показує, чи тримає замок ядро цієї машини.
- **Міст до Python.** Лише функції за списком власника (`🜔python 「statistics.median」 【…】`), кожна в окремому
  процесі під повним замком ОС і стеженням (читати поза теками Python не дає, спроба — у сліді). Туди й назад — лише
  дані. Чи функція чиста — вирішує власник: функція, що виконує довільний код, прочитає будь-який файл користувача.
- **Підпис автора.** Ed25519 без залежностей, охоплює печатку й усі модулі. Власник може дати права за ключем
  («для_авторів»).

Суд 11 — 7:0 «Б» (ядро тримає, підпис не підробити; квоти, тексти й кілька країв треба було виправити), огляд 11б —
2 «А», 5 вузьких «Б» (нового зламу немає; Атанор пропускав повноширинних двійників рядка підпису, модуль з теки запису
ключа автора брався як модуль). Усе виправлено з тестами; далі — вузьке підтвердження 11в. Останній звіт звірки —
[`athanor/ЗВІРКА.md`](athanor/ЗВІРКА.md); історія й протоколи — [`konsylium/`](konsylium/).

**Чесно про межі:** Nigredo — інструмент прозорості й аудиту, **не пісочниця ОС**: агент із доступом до shell може
обійти її взагалі. Впевненість — консервативна оцінка, а не ймовірність. `оракул` — імітація для демонстрацій.

---

Мову, обидва виконавці, тести й тексти написав Claude (Anthropic) як агент, власник проєкту — Denis Romaniuk.
