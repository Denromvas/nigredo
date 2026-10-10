# Nigredo

> **English** · [Українська ↓](#українською)

**A programming language for AI agents — and a black box for humans.** Agents write and read it; the human
owner always knows what a program *may* do before it runs and can verify what it *did* afterwards.

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
| 0.4.3 frozen → 0.4.4 (current) | **6:1 adopted** for the niche "delegation with seal and trace" (Gemini: experimental) | 300+ attempts on two frozen versions in a row: nobody acted outside the seal or got a false "✓". Findings were about the *signal*: U+2028 broke trace verification, invisible Unicode tags reached the receiving model, author text inside the seal report, homoglyphs beyond the table, the "survived, so the condition is known" channel. All fixed in 0.4.4 with negative tests (one visibility rule, UTS #39 skeletons, full output in the trace) |

Full protocols, every participant's report and solutions: [`konsylium/`](konsylium/).

### Try it

```
python3 interpreter/nigredo.py examples/ahent.ngr
python3 interpreter/nigredo.py --печатка examples/fajly.ngr     # what the program may do
python3 interpreter/nigredo.py --розбір examples/chysla.ngr     # translation for the owner
python3 interpreter/test.py                                    # examples + 73 attack/error tests + trace/MCP checks
claude mcp add nigredo -- python3 mcp/nigredo_mcp.py           # give it to any MCP-capable agent
```

A text browser for agents, written in Nigredo itself: `ngr браузер/браузер.ngr -- URL [N]` (page → title, text with
lynx-style `[N]` link markers, numbered absolute links; `N` follows link N; `пошук words` searches Wikipedia). The seal
names every host it may visit, a sub-agent with network-only rights fetches, invisible characters come out as `⟨U+…⟩`.
Over MCP it is the `nigredo_brauzer` tool.

Python ≥ 3.10, no dependencies. The language's own words (glyph names, errors, docs) are Ukrainian.

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

Python ≥ 3.10, без залежностей.

```
python3 interpreter/nigredo.py examples/ahent.ngr     # або ngr, якщо зробити симлінк
python3 interpreter/nigredo.py --печатка examples/fajly.ngr
python3 interpreter/nigredo.py --розбір examples/chysla.ngr
python3 interpreter/test.py                            # приклади, 73 перевірки помилок і атак, слід, MCP, памʼятка
```

Дозволи власника — `~/.nigredo/дозволи.json`, наприклад
`{"дозволено": ["оракул", "файл.читати:/home/я/дані"]}`. Без нього доступні лише іграшкові інструменти.

- [`ДЛЯ_АГЕНТІВ.md`](ДЛЯ_АГЕНТІВ.md) — памʼятка з усіма гліфами (генерується інтерпретатором).
- [`spec/SPEC.md`](spec/SPEC.md) — специфікація.

## Історія: суди

Мову створив ШІ-агент на прохання власника. Щоб оцінка не була лише думкою автора, її віддали на
**консиліум**: пʼять окремих сесій Claude з різними ролями (Скептик, Практик, Мовознавець, Аудитор
безпеки, Новачок, який вчиться лише з памʼятки) і Gemini як незалежна модель. Кожен розвʼязував ті самі
завдання справжнім інтерпретатором, потім усі обговорювали звіти одне одного.

| Версія | Вердикт | Що сталося |
|---|---|---|
| 0.1 — стекова, «шифр для людей» | 6:0 — непридатна як робоча | Практична користь 2/10; слід можна підробити; межа делегування проникна. Переписано з нуля. |
| 0.2 — печатка, префіксний запис | 6:0 — експериментальна | Писати легко (новачок 4/4 з памʼятки), але знайдено діри в гарантіях. |
| 0.3 | 7:0 — експериментальна; **Python-обгортку як заміну відкинуто 7:0** | Обгортку з тими самими гарантіями (`porivniannia/ngrpy.py`) зламали зсередини пʼятьма способами; межу Nigredo «печатка → інструменти → файли» — ніхто. Знайдено відмивання впевненості через вибір і обрізаний слід. |
| 0.4 → 0.4.2 | **5:2 «прийняти» для ніші «доручення з печаткою і слідом»** | Новачок вивчив мову лише через MCP і розвʼязав усе з першої спроби; атаки суду 3 закрито. |
| 0.4.2 заморожена → 0.4.3 | 7:0 «експериментальна», «близько до А» | На замороженій версії субагента підвищили через функцію батька (транзитивне делегування); виправлено в 0.4.3 з негативними тестами, просять повторний огляд. |
| 0.4.3 заморожена → 0.4.4 — поточна | **6:1 «А» — прийняти для ніші «доручення з печаткою і слідом»** (Gemini — «Б») | Понад 300 спроб на двох заморожених версіях поспіль: ні дії поза печаткою, ні хибного «✓». Знайдено вади сигналу: U+2028 ламав перевірку сліду, невидимі теги доходили до моделі-отримувача, текст автора у звіті печатки, двійники поза таблицею, канал «дожила — отже умова відома». Усе виправлено в 0.4.4 з негативними тестами. |

Висновок третього суду: Nigredo краща за Python там, де агент **отримує чужу програму** й мусить вирішити,
чи її запускати, — для цього досить рядка печатки; у Python — лише читати весь код, і навіть тоді обхід можливий.

Протоколи, звіти й розвʼязки всіх учасників — [`konsylium/`](konsylium/); засуджені версії — [`архів/`](архів/).

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
