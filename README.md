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
- **Fast** — the native engine **Athanor** (Rust, no dependencies) is faster than CPython both on agent tasks and on
  large data, with the same output and the same signed trace as the reference interpreter.
- **Black box with a key** — no human keywords; the owner reads any program through `ngr --печатка` (what it may do),
  `ngr --розбір` (a translation) and the signed trace, and can grant extra rights to one exact program
  (`ngr --схвалити`: change a byte and the grant is gone).

## Measured against Python

Same tasks in both languages (`bench/`), models writing both from the same task (`bench/м2/`). Details and caveats —
[`bench/РЕЗУЛЬТАТИ.md`](bench/РЕЗУЛЬТАТИ.md), [`bench/м2/`](bench/м2/), [`bench/великі/`](bench/великі/).

| | Nigredo | Python |
|---|---|---|
| Agent tasks solved (12) | 12/12 | 12/12 |
| Program length, **with** the seal | 1.01× (author's); 0.88× (models' first-try programs) | 1× |
| Real bugs caught before running (14) | 9 | 3 with pyflakes |
| Models right on the first try, held-out tasks (3 runs × 10) | Sonnet 27/30, Haiku 21/30 | Sonnet 27/30, Haiku 23/30 |
| Speed, 12 small agent tasks (median time) | **0.49×** | 1× |
| Speed, large data: 200k words / 200k-step loop / 25k-record JSON | **0.73× / 0.57× / 0.86×** | 1× |
| The owner knows what a program may do and did | seal, signed trace, replay, dry run | — |

Speed is CPU time on a phone (Termux); Nigredo's numbers include its own trace and replay store.

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
program in the repo (~4900, 0 differences). History and protocols: [`konsylium/`](konsylium/).

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
- **Швидка:** нативний виконавець **Атанор** (Rust, без залежностей) швидший за CPython і на задачах агента, і на
  великих даних — з тим самим виводом і тим самим підписаним слідом, що й еталонний інтерпретатор.
- **Ключ у власника:** `ngr --печатка` (що програмі дозволено), `ngr --розбір` (переклад), підписаний слід; права
  саме одній програмі — `ngr --схвалити` (змінений байт — і схвалення не діє).

## Порівняння з Python

Ті самі задачі обома мовами (`bench/`), моделі пишуть обидва рішення з того самого завдання (`bench/м2/`). Подробиці й
застереження — [`bench/РЕЗУЛЬТАТИ.md`](bench/РЕЗУЛЬТАТИ.md), [`bench/м2/`](bench/м2/), [`bench/великі/`](bench/великі/).

| | Nigredo | Python |
|---|---|---|
| Розвʼязано задач агента (12) | 12/12 | 12/12 |
| Довжина програм **з** печаткою | 1,01× (автора); 0,88× (програми моделей з першої спроби) | 1× |
| Справжніх помилок спіймано до запуску (14) | 9 | 3 з pyflakes |
| Моделі правильно з першої спроби, відкладені задачі (3 прогони × 10) | Sonnet 27/30, Haiku 21/30 | Sonnet 27/30, Haiku 23/30 |
| Швидкість, 12 малих задач агента (медіана часу) | **0,49×** | 1× |
| Швидкість, великі дані: 200 тис. слів / цикл на 200 тис. кроків / JSON на 25 тис. записів | **0,73× / 0,57× / 0,86×** | 1× |
| Власник знає, що програмі дозволено й що вона зробила | печатка, підписаний слід, повтор, сухий прогін | — |

Швидкість — процесорний час на телефоні (Termux); у числах Nigredo — і її власні слід та сховище повтору.

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
кожна знахідка стає негативним тестом. Атанор звіряють з еталонним інтерпретатором на всіх програмах репозиторію
(~4900, розбіжностей 0). Історія й протоколи — [`konsylium/`](konsylium/).

**Чесно про межі:** Nigredo — інструмент прозорості й аудиту, **не пісочниця ОС**: агент із доступом до shell може
обійти її взагалі. Впевненість — консервативна оцінка, а не ймовірність. `оракул` — імітація для демонстрацій.

---

Мову, обидва виконавці, тести й тексти написав Claude (Anthropic) як агент, власник проєкту — Denis Romaniuk.
