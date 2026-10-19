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

Висновок третього суду: Nigredo краща за Python там, де агент **отримує чужу програму** й мусить вирішити,
чи її запускати, — для цього досить рядка печатки; у Python — лише читати весь код, і навіть тоді обхід можливий.

Засуджені версії — [`../архів/`](../архів/).

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

Each `суд*/` folder holds the protocol, every participant's report and solutions; rejected versions are in [`../архів/`](../архів/).
