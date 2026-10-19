# Nigredo

> **English** · [Українська ↓](#українською)

**A programming language for AI agents — and a black box for humans.** Agents write and read it; the human
owner always knows what a program *may* do before it runs and can verify what it *did* afterwards.

**Try it in the browser:** [denromvas.github.io/nigredo](https://denromvas.github.io/nigredo/) — the real interpreter
(Pyodide): examples, the seal, the human translation, checks before running, the signed trace, and the benchmark's
deliberate mistakes side by side with the same Python. / **Пісочниця в браузері** — те саме українською.

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
- **Signed trace** — written by the interpreter, not the program; HMAC-chained; edits, insertions and truncation are detected.
- **Confidence as semantics** — every value carries a confidence; nothing computed from (or under the control of)
  an uncertain value is more confident than it, including through selection and control flow (a pc label).
- **Built for LLMs** — prefix notation with fixed arity (no stack to track, errors before running),
  glyphs chosen by measuring tokenizers; about as many tokens as Python without the seal.
- **Black box by design** — no human keywords; the owner holds the key: `--печатка` (what a program may do), `--розбір` (translation), the signed trace.

### Judged by agents

Instead of the author grading their own work, every version went to a **council of agents**: separate Claude
sessions with different roles (Skeptic, Practitioner, Linguist, Security Auditor, Newcomer who learns only from the
cheat sheet, Orchestrator) plus Gemini as an independent model. Each solved the same tasks with the real
interpreter, attacked it, then debated the others' reports.

| Version | Verdict | What happened |
|---|---|---|
| 0.1 (stack-based) | 6:0 unfit | trace forgeable, delegation boundary leaky → rewritten from scratch |
| 0.2 (seal, prefix) | 6:0 experimental | easy to write (newcomer 4/4 from the cheat sheet), holes in guarantees |
| 0.3 | 7:0 experimental; **Python wrapper with the same guarantees rejected 7:0** | the wrapper was broken from inside in five ways; nobody crossed Nigredo's seal → tools → files boundary |
| 0.4 → 0.4.2 | **5:2 adopted for the niche "delegation with seal and trace"** | a newcomer learned it purely via MCP and solved everything first try; all council-3 attacks closed |
| 0.4.2 frozen → 0.4.3 | 7:0 experimental — "close to adopted" | on the frozen version the councillors escalated a sub-agent through a parent's function (transitive delegation); fixed in 0.4.3 with negative tests, re-review requested |
| 0.4.3 frozen → 0.4.4 | **6:1 adopted** for the niche "delegation with seal and trace" (Gemini: experimental) | 300+ attempts on two frozen versions in a row: nobody acted outside the seal or got a false "✓". Findings were about the *signal*: U+2028 broke trace verification, invisible Unicode tags reached the receiving model, author text inside the seal report, homoglyphs beyond the table, the "survived, so the condition is known" channel. All fixed in 0.4.4 with negative tests (one visibility rule, UTS #39 skeletons, full output in the trace) |
| 0.5 frozen (phase 1 of "better than Python for agents") → 0.6 | 7:0 "fix first" | Boundaries held again; new features leaked: module swap passed trace verification, a regex blacklist was bypassed 7 ways (now a linear-time regex engine with steps charged), decimals from data hung or crashed, and the benchmark was presented in Nigredo's favour. Honest numbers now: 1.64× Python's tokens **with** the seal, 9 vs 3 (Python + pyflakes) bugs caught before running, 0 false alarms |
| 0.6 frozen (phases 1b–3: SQLite, processes, parallel `‖`, replay, dry run) → 0.7 | 7:0 "fix first" (Gemini switched A → B after the others' runs) | Nobody acted outside the seal. Findings were about what the owner *sees*: replay and dry-run traces passed verification as real runs, network refusals weren't marked "forbidden", the human translation could be spoofed with quotes, `процес` passed the symlink target as argv[0] (busybox could turn `echo` into a shell). All fixed with tests and mutation checks |
| 0.7 frozen (XML, data contracts `✓`, quotas `≤N`, tests in the language) → 0.7 | 7:0 "fix first" (Gemini again A → B) | Nobody acted outside the seal; the new features leaked: XML writing let data inject elements, the XPath subset ignored step limits and double-counted nodes, a module's quota didn't apply, `--тести` passed a failed check caught by `☂`, and the README showed M2 "after" without "before". All fixed with negative tests from the judges' attacks; every new guard mutation-checked |
| 0.7-dev after court-8 fixes → **0.7** | court 8b: 6:1 "fix first" (Gemini A); court 8c (one judge, the Auditor, on all judges' attacks; 3 short rounds): B → B → **A** | All court-8 findings confirmed closed by runs; nobody acted outside the seal. Found on the fixes: an exhausted quota masked "forbidden", SQLite "forbidden" was read from error text, `--дозволи` and nested folder rules let code from a write folder get folder rights or become a module, crash code 4 from data (deep JSON, `]` in a path, URLs urllib can't parse). All fixed with tests; every guard mutation-checked |

Full protocols, every participant's report and solutions: [`konsylium/`](konsylium/).

### Measured against Python (honestly)

`bench/` runs the same tasks in both languages; `bench/м2/` asks models (Sonnet, Haiku) to write both from the same
task — Nigredo with its cheat sheet, Python with nothing extra. Numbers as of 2026-10-16 (speed — 2026-10-19):

| | Nigredo | Python | Note |
|---|---|---|---|
| Tasks solved (12 agent tasks) | 12/12 | 12/12 | |
| Program length, **with** the seal | 1.01× (author's 12 tasks); **0.88×** on models' own first-try programs for 20 tasks of `bench/м2` (36 pairs, one per task × model; only where both languages passed — the 4 pairs that drop out are all Haiku tasks where Nigredo failed, so the harder cases are missing; the cheat sheet advises short names, the Python prompt does not; 10 of the 20 tasks are the rerun after fixing the cheat sheet on them, so this is not a held-out set) | 1× | the seal costs ~13 tokens |
| Bugs caught before running (14 real ones) | 9 | 3 (with pyflakes), 1 (py_compile) | 0 false alarms on 10 correct programs; 5 classes Nigredo misses are listed |
| Models writing it right first try (hard set, 3 runs each) | Sonnet 29/30, Haiku 24/30 (first run: 24/30 and 24/30) | Sonnet 30/30, Haiku 26/30 (first run: 30, 27) | 10 tasks not in the cheat sheet. The rerun is on the **same** tasks after fixing a `⌕` defect and the cheat sheet that those misses exposed, so it is not a held-out measurement; ±1–2 of 30 is noise. Misses left are mostly prefix-notation arity. After a second try (the model sees the expected output): 30 and 29 vs 30 and 30 |
| Speed, small tasks (median) | **0.49×** (about 2× faster) | 1× | with the native engine Athanor (`athanor/`, Rust): ~6 ms of CPU to run a one-line program, signed trace included, against ~26 ms for Python's `print(1)`; the reference interpreter on Python is 2.2× slower |
| Speed, large data (200k words / 200k-step loop) | ~1.2× / ~1.1× slower | 1× | Athanor; the reference interpreter is ~8× / ~30× slower. `python3 bench/великі/міряти.py`, last run — `bench/великі/РЕЗУЛЬТАТИ.txt` (CPU time, phone, varies with load) |
| Owner knows what a program may do / did | seal + signed trace, replay, dry run | — | Python has no such mechanism inside the language |

### Try it

```
python3 interpreter/ngr.py examples/ahent.ngr
python3 interpreter/ngr.py --печатка examples/fajly.ngr     # what the program may do
python3 interpreter/ngr.py --розбір examples/chysla.ngr     # translation for the owner
python3 interpreter/test.py                                    # examples + 73 attack/error tests + trace/MCP checks
claude mcp add nigredo -- python3 mcp/nigredo_mcp.py           # give it to any MCP-capable agent
```

A text browser for agents, written in Nigredo itself: `ngr браузер/браузер.ngr -- URL [N]` (page → title, text with
lynx-style `[N]` link markers, numbered absolute links; `N` follows link N; `пошук words` searches Wikipedia). The seal
names every host it may visit, a sub-agent with network-only rights fetches, invisible characters come out as `⟨U+…⟩`.
Over MCP it is the `nigredo_brauzer` tool.

Python ≥ 3.10, no dependencies. **Athanor**, the native engine: `sh athanor/зібрати.sh` (Rust, std only), then run
`athanor/target/<host>/release/athanor` exactly like `ngr` — same output, same signed trace; whatever it does not
implement itself (network, processes, agents, `‖`, the checking/replay modes) it hands to the reference interpreter
before any action. Every change is checked against the reference on all ~4900 programs in the repo
(`python3 athanor/звірка.py`: 1961 run natively, 0 differences). The language's own words (glyph names, errors, docs) are Ukrainian.

**Honest limits:** Nigredo is a transparency and audit tool, **not an OS sandbox** — an agent with shell access can
bypass it entirely. Confidence is a conservative bound, not a probability. The interpreter and the language were
written by Claude (Anthropic) as an agent; the project owner is Denis Romaniuk. MIT license.

---

<a id="українською"></a>

# Nigredo (українською)

**Мова програмування для ШІ-агентів.** Її пишуть і читають агенти, а людина-власник завжди
бачить, що програма *може* зробити, і перевіряє, що вона *зробила*.

*Nigredo* — «почорніння», перша стадія алхімічного Великого Діла: розкласти, щоб зібрати заново.
Мову двічі засуджував консиліум агентів, і двічі її переписано; з 0.4 її судять на замороженій версії (історія нижче).

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
  зміну, вставку чи обрізання виявляє `ngr --перевірити-слід`.
- **Впевненість як семантика.** Кожне значення несе впевненість ∈ [0, 1]; усе, що з нього обчислено, — не
  впевненіше за джерело (через дані, контейнери й керування). Підняти її можна лише явно, і це в сліді.
- **Делегування з підмножиною прав.** Субагент отримує не більше дозволів, ніж батько; значення незмінні.
- **Для моделей:** префіксний запис із фіксованою арністю (без стека в голові, без тихих збоїв),
  гліфи обрано за вимірами токенізаторів, помилки — до запуску й з підказками.

## Запуск

Python ≥ 3.10, без залежностей. **Атанор** — нативний виконавець (`athanor/`, Rust без залежностей): `sh athanor/зібрати.sh`,
далі `athanor/target/<ціль>/release/athanor` — як `ngr`: той самий вивід і підписаний слід; чого сам не вміє (мережа,
процеси, агенти, `‖`, режими перевірки й повтору) — до будь-якої дії віддає еталонному інтерпретатору. Кожну зміну
звіряю з еталоном на всіх ~4900 програмах репозиторію (`python3 athanor/звірка.py`: 1961 виконано нативно, розбіжностей 0).

```
python3 interpreter/ngr.py examples/ahent.ngr     # або ngr, якщо зробити симлінк
python3 interpreter/ngr.py --печатка examples/fajly.ngr
python3 interpreter/ngr.py --розбір examples/chysla.ngr
python3 interpreter/test.py                            # приклади, 73 перевірки помилок і атак, слід, MCP, памʼятка
```

Дозволи власника — `~/.nigredo/дозволи.json`, наприклад
`{"дозволено": ["оракул", "файл.читати:/home/я/дані"]}`. Без нього доступні лише іграшкові інструменти.

- [`ДЛЯ_АГЕНТІВ.md`](ДЛЯ_АГЕНТІВ.md) — памʼятка з усіма гліфами (генерується інтерпретатором).
- [`spec/SPEC.md`](spec/SPEC.md) — специфікація.

## Історія: суди

Мову створив ШІ-агент на прохання власника. Щоб оцінка не була лише думкою автора, її віддали на
**консиліум**: шість окремих сесій Claude з різними ролями (Скептик, Практик, Мовознавець, Аудитор
безпеки, Новачок, який вчиться лише з памʼятки, Оркестратор, що приймає чужі програми) і Gemini як незалежна модель. Кожен розвʼязував ті самі
завдання справжнім інтерпретатором, потім усі обговорювали звіти одне одного.

| Версія | Вердикт | Що сталося |
|---|---|---|
| 0.1 — стекова, «шифр для людей» | 6:0 — непридатна як робоча | Практична користь 2/10; слід можна підробити; межа делегування проникна. Переписано з нуля. |
| 0.2 — печатка, префіксний запис | 6:0 — експериментальна | Писати легко (новачок 4/4 з памʼятки), але знайдено діри в гарантіях. |
| 0.3 | 7:0 — експериментальна; **Python-обгортку як заміну відкинуто 7:0** | Обгортку з тими самими гарантіями (`porivniannia/ngrpy.py`) зламали зсередини пʼятьма способами; межу Nigredo «печатка → інструменти → файли» — ніхто. Знайдено відмивання впевненості через вибір і обрізаний слід. |
| 0.4 → 0.4.2 | **5:2 «прийняти» для ніші «доручення з печаткою і слідом»** | Новачок вивчив мову лише через MCP і розвʼязав усе з першої спроби; атаки суду 3 закрито. |
| 0.4.2 заморожена → 0.4.3 | 7:0 «експериментальна», «близько до А» | На замороженій версії субагента підвищили через функцію батька (транзитивне делегування); виправлено в 0.4.3 з негативними тестами, просять повторний огляд. |
| 0.4.3 заморожена → 0.4.4 | **6:1 «А» — прийняти для ніші «доручення з печаткою і слідом»** (Gemini — «Б») | Понад 300 спроб на двох заморожених версіях поспіль: ні дії поза печаткою, ні хибного «✓». Знайдено вади сигналу: U+2028 ламав перевірку сліду, невидимі теги доходили до моделі-отримувача, текст автора у звіті печатки, двійники поза таблицею, канал «дожила — отже умова відома». Усе виправлено в 0.4.4 з негативними тестами. |
| 0.5 заморожена (фаза 1 «краща за Python для агентів») → 0.6 | 7:0 «спершу виправити» | Межі знову тримали; нове протекло: підміна модуля проходила перевірку сліду, чорний список ReDoS обійшли 7 способами (тепер рушій регулярок без відкатів, кроки — з ліміту), десяткові з даних вішали чи валили запуск, мірило подано вигідно для Nigredo. Чесні числа: 1,64× токенів Python **з** печаткою, 9 проти 3 (Python + pyflakes) помилок до запуску, 0 хибних тривог. |
| 0.6 заморожена (фази 1б–3: SQLite, процеси, паралельні `‖`, повтор, сухий прогін) → 0.7 | 7:0 «спершу виправити» (Gemini перейшов з А на Б після запусків інших) | Дії поза печаткою — жодної. Знайдене — про те, що *бачить* власник: сліди повтору й сухого прогону проходили перевірку як справжні, відмови мережі не позначалися «заборонено», переклад для людини обдурювали лапками, `процес` передавав ціль симлінка як argv[0] (на busybox `echo` міг стати оболонкою). Усе виправлено з тестами й мутаційною перевіркою. |
| 0.7 заморожена (XML, контракти `✓`, квоти `≤N`, тести мовою) → 0.7 | 7:0 «спершу виправити» (Gemini знову А → Б) | Дії поза печаткою — жодної; протекло нове: запис XML дозволяв даним вставити елементи, підмножина XPath не рахувала кроків і двоїла вузли, квота модуля не діяла, `--тести` зараховував провалену перевірку під `☂`, README подавав М2 «після» без «до». Усе виправлено з негативними тестами з атак суддів; кожен новий захист — мутаційна перевірка. |
| 0.7-dev після виправлень суду 8 → **0.7** | суд 8б: 6:1 «спершу виправити» (Gemini — А); суд 8в (один суддя — Аудитор — на атаках усіх; 3 короткі раунди): Б → Б → **А** | Усе знайдене в суді 8 закрито — судді перевірили запусками; дії поза печаткою — жодної. На виправленнях знайдено: вичерпана квота ховала «заборонено», SQLite «заборонено» бралося з тексту помилки, `--дозволи` і вкладені «для_тек» давали коду з теки запису права теки чи робили його модулем, код 4 від даних (глибокий JSON, `]` у шляху, адреси, яких не розбирає urllib). Усе виправлено з тестами; кожен захист — мутаційна перевірка. |

Висновок третього суду: Nigredo краща за Python там, де агент **отримує чужу програму** й мусить вирішити,
чи її запускати, — для цього досить рядка печатки; у Python — лише читати весь код, і навіть тоді обхід можливий.

Протоколи, звіти й розвʼязки всіх учасників — [`konsylium/`](konsylium/); засуджені версії — [`архів/`](архів/).

### Порівняння з Python — чесно

`bench/` виконує ті самі задачі обома мовами; `bench/м2/` просить моделі (Sonnet, Haiku) написати обидва рішення з того
самого завдання — Nigredo з памʼяткою, Python без нічого. Станом на 2026-10-16 (швидкість — 2026-10-19):

| | Nigredo | Python | Примітка |
|---|---|---|---|
| Розвʼязано (12 задач агента) | 12/12 | 12/12 | |
| Довжина програм **з** печаткою | 1,01× (12 задач автора); **0,88×** на програмах моделей з першої спроби для 20 задач `bench/м2` (36 пар — одна на задачу × модель; лише де обидві мови пройшли — 4 пари, що випали, усі з Haiku, де Nigredo впала, тож важчих випадків тут немає; памʼятка радить короткі імена, підказка Python — ні; 10 із 20 задач — повтор після правок памʼятки на них, тож це не відкладений набір) | 1× | печатка — ~13 токенів |
| Помилок спіймано до запуску (14 справжніх) | 9 | 3 (з pyflakes), 1 (py_compile) | 0 хибних тривог на 10 правильних програмах; 5 класів, яких Nigredo не ловить, перелічено |
| Моделі пишуть правильно з першої спроби (складний набір, по 3 прогони) | Sonnet 29/30, Haiku 24/30 (перший прогін: 24/30 і 24/30) | Sonnet 30/30, Haiku 26/30 (перший: 30, 27) | 10 задач поза памʼяткою. Повтор — на **тих самих** задачах після виправлення вади `⌕` і памʼятки, які ці промахи виявили, тож це не відкладений вимір; ±1–2 з 30 — шум. Решта промахів — переважно арність префіксного запису. З другої спроби (модель бачить очікуваний вивід): 30 і 29 проти 30 і 30 |
| Швидкість, малі задачі (медіана) | **0,49×** (приблизно вдвічі швидше) | 1× | з нативним виконавцем Атанор (`athanor/`, Rust): однорядкова програма разом із підписаним слідом — ~6 мс процесорного часу проти ~26 мс на `print(1)` у Python; еталонний інтерпретатор на Python — у 2,2× повільніше |
| Швидкість, великі дані (200 тис. слів / цикл на 200 тис. кроків) | у ~1,2× / ~1,1× повільніше | 1× | Атанор; еталон — у ~8× / ~30× повільніше. `python3 bench/великі/міряти.py`, останній прогін — `bench/великі/РЕЗУЛЬТАТИ.txt` (процесорний час на телефоні, залежить від навантаження) |
| Власник знає, що програмі дозволено й що вона зробила | печатка + підписаний слід, повтор, сухий прогін | — | у самій мові Python такого механізму немає |

## Браузер для агентів — на самій Nigredo

`браузер/браузер.ngr` — текстовий браузер, написаний мовою Nigredo поверх інструмента `мережа.взяти` (у інтерпретаторі
нового коду немає):

```
ngr браузер/браузер.ngr -- https://news.ycombinator.com/       # назва, текст із [N] перед посиланнями, список посилань
ngr браузер/браузер.ngr -- https://news.ycombinator.com/ 12    # перейти за посиланням 12
ngr браузер/браузер.ngr -- пошук alchemy nigredo                # пошук у Вікіпедії (пошук-uk — українській)
```

- Печатка перелічує **кожен** хост, куди браузер може піти; посилання на інший сайт — відмова з поясненням.
  Новий сайт — дописати хост у печатку, а власник — у свої дозволи.
- Сторінку бере субагент «читач», якому дозволено лише мережу; усе — у підписаному сліді.
- Скрипти, стилі, коментарі, `<nav>` вирізано; якщо є `<main>` — лише він. Невидимі символи сторінки — `⟨U+…⟩`.
- Чесно: JavaScript не виконується, переадресацій немає (`мережа.взяти` їх забороняє), сайти з капчею для ботів
  (DuckDuckGo тощо) не працюють, і браузер їх не обходить. Текст сторінки — слова її автора, не вказівки агентові.

## Для агентів: MCP

```
claude mcp add nigredo -- python3 /шлях/до/nigredo/mcp/nigredo_mcp.py
```

Інструменти `nigredo_vykonaty`, `nigredo_pechatka`, `nigredo_rozbir`, `nigredo_pereviryty_slid`, `nigredo_pamyatka` і
`nigredo_brauzer` (браузер вище: `url`, `link`, `search`, `lang`; хости — з його печатки, підсумок сліду — у відповіді);
стисла памʼятка (~2 тис. токенів) — прямо в описі інструмента, вивчати нічого не треба.

## Чорний ящик

Вимога творця: Nigredo лишається **чорним ящиком для людей** — код агентів не мусить бути зрозумілим людині.
Ключ від ящика — у власника: `--печатка`, `--розбір` і підписаний слід.

## Чесно про межі

- Nigredo — інструмент прозорості й аудиту, **не пісочниця**. Агент із доступом до shell може обійти
  Nigredo взагалі; від нього захищають права процесу, а не мова.
- `оракул` — імітація ненадійного джерела для демонстрацій, а не знання.
- Без печатки код займає приблизно стільки ж токенів, скільки Python; печатка додає фіксовану ціну.

---

Мову, інтерпретатор, тести й тексти написав Claude (Anthropic) як агент, власник проєкту — Denis Romaniuk.
