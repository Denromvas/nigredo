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
| Speed, 200k words / 200k-step loop / 25k-record JSON (CPU time) | **0.64× / 0.47× / 0.88×** | 1× |
| Speed, the loop through a named function / with `¿` in it (CPU time) | **0.32× / 0.49×** | 1× |
| Speed, exact decimals (Python: `Decimal`) / building strings / a `↻` loop with list state (CPU time) | 0.97× / 1.04× / **1.73×** | 1× |
| The owner knows what a program may do and did | seal, signed trace, replay, dry run | — |

Measured on a phone (Termux); Nigredo's numbers include its own trace and replay store. Small tasks are mostly
interpreter start-up; the two tasks that use the network are handed to the reference and are slower than Python;
the 200k-step loop is a shape Athanor has a fast path for; exact decimals and string building are on par with Python,
and a `↻` loop that builds a new list every step is 1.7× slower. On a quiet phone the spread between runs is ~10–20 %;
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
latest comparison report is
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
| Швидкість, 200 тис. слів / цикл на 200 тис. кроків / JSON на 25 тис. записів (процесорний час) | **0,64× / 0,47× / 0,88×** | 1× |
| Швидкість, той самий цикл через іменовану функцію / з `¿` у ній (процесорний час) | **0,32× / 0,49×** | 1× |
| Швидкість, точні дроби (у Python — `Decimal`) / складання рядків / цикл `↻` зі станом-списком (процесорний час) | 0,97× / 1,04× / **1,73×** | 1× |
| Власник знає, що програмі дозволено й що вона зробила | печатка, підписаний слід, повтор, сухий прогін | — |

Виміряно на телефоні (Termux); у числах Nigredo — і її власні слід та сховище повтору. Малі задачі — здебільшого
запуск інтерпретатора; дві задачі з мережею Атанор віддає еталону, і там він повільніший за Python; цикл на 200 тис.
кроків — форма зі швидкою доріжкою Атанора; точні дроби й рядки — нарівні з Python, а `↻`, що щокроку будує новий
список, — у 1,7 раза повільніший. На спокійному телефоні розкид між прогонами — ~10–20 %; на навантаженому (судді
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
навмання взяв би сам SQLite, вичерпана квота спроби не ховає, а `sqlite_dbpage` — відмова. Останній звіт звірки —
[`athanor/ЗВІРКА.md`](athanor/ЗВІРКА.md); історія й протоколи — [`konsylium/`](konsylium/).

**Чесно про межі:** Nigredo — інструмент прозорості й аудиту, **не пісочниця ОС**: агент із доступом до shell може
обійти її взагалі. Впевненість — консервативна оцінка, а не ймовірність. `оракул` — імітація для демонстрацій.

---

Мову, обидва виконавці, тести й тексти написав Claude (Anthropic) як агент, власник проєкту — Denis Romaniuk.
