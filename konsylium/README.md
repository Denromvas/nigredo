# Консиліум — як перевіряють Nigredo

> [English ↓](#english)

## Суди версій

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
| 0.8 заморожена (обидва виконавці — еталон і нативний Атанор; SQLite за замовчуванням закритий) → **0.8** | суд 9 — 7:0 «Б»; повторні огляди 9б (2 «А», 5 «Б»), 9в (2:5), 9г (3:4) → **9д — 7:0 «А»** | Розбіжності виконавців (кінцева сигма, `\N{…}` у шаблоні з даних, межа сліду, кроки SQLite, глибина стеку) і SQLite, що давав програмі годинник і випадковість без прав: через `DEFAULT` стовпця, тригер з rowid 2⁶³−1, `;` на початку запиту, `sqlite_sequence`. Усе виправлено з тестами обома виконавцями. |
| 0.8.1 (побажання 0.8) | шість оглядів: 0.8.1 (1:6), 0.8.1б (1:6), 0.8.1в (2:5), 0.8.1г (5:2), 0.8.1д (5:2) → **0.8.1е — 7:0 «А»** з умовою, закритою до оголошення | Загартовано сторожа SQLite: службова функція через `DEFAULT`, `CHECK`, `sqlite_stmt` і віртуальні таблиці; перелік таблиць — за планом запиту, а не за назвою; мережа без тихих втрат. |
| 0.9-dev (модулі з git за хешем) → **0.9** | суд 10 — 7:0 «Б»; огляд 10б — 4:2 «А»; вузьке підтвердження 10в — **2:0 «А»** | Зламу немає; неправдиві тексти ключа власника, прихований вхід `⌂` у «лише обчислює», чиї слова в помилці з модуля, лапки в підсумку сліду. Усе виправлено з тестами до оголошення. |
| 0.10-dev (замок ОС seccomp, міст до Python, підпис автора Ed25519) → **0.10** | суд 11 — 7:0 «Б»; огляд 11б — 2 «А», 5 «Б»; вузьке підтвердження 11в — **5:0 «А»** | Ядро тримає, підпис не підробити. Знайдено: квота `python:…≤N` не діяла, міст читав теку власника, код 4, точки малого порядку Ed25519, Атанор пропускав двійників рядка підпису (`ｅｄ２５５１９`), модуль з теки ключа автора брався як модуль, хибні тривоги на числах у коментарях. Усе виправлено з тестами й мутаціями до оголошення. |

Висновок третього суду: Nigredo краща за Python там, де агент **отримує чужу програму** й мусить вирішити,
чи її запускати, — для цього досить рядка печатки; у Python — лише читати весь код, і навіть тоді обхід можливий.

Засуджені версії — [`../архів/`](../архів/).

Починаючи з 0.8, після суду йдуть **повторні огляди**: судять ті самі ролі, і щоразу коротше — лише те, що змінилось,
і умови тих, хто голосував «Б». Версію оголошують, коли «А» дали всі, а побажання виправлено з тестами.

**Про шляхи.** Матеріали судів збережено дослівно: у програмах і звітах — абсолютні шляхи машини, де йшов суд
(`/root/ai-agents/Nigredo/…` — це корінь цього репозиторію). Їх не переписано свідомо: підписані програми, модулі,
закріплені sha256, й атаки саме на абсолютні шляхи залежать від точних байтів. Переписаний текст був би вже не тим,
що запускав суддя. Жива частина репозиторію — інтерпретатор, Атанор, тести, приклади, мірило, сайт — абсолютних шляхів
не має (крім сліду-зразка `tests/сумісність/`: слід записує теку, де його зроблено, а перевіряють його в іншій).

Як проходить суд: версію заморожують (хеш коміту й інтерпретатора), кожен суддя в окремій теці розвʼязує ті самі
завдання справжнім інтерпретатором, атакує межу (печатка → інструменти → файли) і пише звіт; у другому раунді судді
читають звіти одне одного й запускають чужі атаки. Кожна знахідка стає негативним тестом у `interpreter/test.py`, а
кожен новий захист — перевіркою мутацією (зламати захист — тест мусить упасти). Теки `суд*/` — протоколи, звіти й
розвʼязки всіх учасників.

<a id="english"></a>

## Judged by agents

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
| 0.8 frozen (both executors — the reference and native Atanor; SQLite closed by default) → **0.8** | court 9: 7:0 "fix first"; re-reviews 9b (2:5), 9c (2:5), 9d (3:4) → **9e: 7:0 A** | Executor divergences (final sigma, `\N{…}` in a pattern from data, the trace limit, SQLite steps, stack depth) and SQLite handing a program the clock and randomness without rights — via a column `DEFAULT`, a trigger with rowid 2⁶³−1, a leading `;`, `sqlite_sequence`. All fixed with tests in both executors |
| 0.8.1 (0.8 wishes) | six reviews: 0.8.1 (1:6), b (1:6), c (2:5), d (5:2), e (5:2) → **0.8.1f: 7:0 A** with a condition closed before the announcement | The SQLite guard hardened: internal functions via `DEFAULT`, `CHECK`, `sqlite_stmt` and virtual tables; tables listed by the query plan, not by name; no silent network losses |
| 0.9-dev (git modules pinned by hash) → **0.9** | court 10: 7:0 "fix first"; review 10b: 4:2 A; narrow confirmation 10c: **2:0 A** | No breach; untrue texts in the owner's key, a hidden input `⌂` in "only computes", whose words an error from a module is, quotes in the trace summary. All fixed with tests before the announcement |
| 0.10-dev (seccomp OS lock, Python bridge, Ed25519 author signature) → **0.10** | court 11: 7:0 "fix first"; review 11b: 2 A, 5 B; narrow confirmation 11c: **5:0 A** | The kernel lock holds, the signature can't be forged. Found: the `python:…≤N` quota didn't apply, the bridge could read the owner's folder, a crash code 4, small-order Ed25519 points, Atanor let full-width look-alikes of the signature line through (`ｅｄ２５５１９`), a module from an author key's write folder was accepted, false alarms on numbers in comments. All fixed with tests and mutation checks before the announcement |

Each `суд*/` folder holds the protocol, every participant's report and solutions; rejected versions are in [`../архів/`](../архів/).

Since 0.8 every court is followed by **re-reviews**: the same roles, shorter each time — only what changed and the
conditions of those who voted B. A version is announced when everyone votes A and the wishes are fixed with tests.

**About paths.** Court materials are kept verbatim: programs and reports contain absolute paths of the machine the court
ran on (`/root/ai-agents/Nigredo/…` is the root of this repository). They are deliberately not rewritten: signed
programs, modules pinned by sha256 and attacks on absolute paths depend on the exact bytes — a rewritten text would no
longer be what the judge ran. The living part of the repository (interpreter, Atanor, tests, examples, benchmark, site)
has no absolute paths (except the sample trace in `tests/сумісність/`: a trace records the folder it was made in, and it is
verified from another one).
