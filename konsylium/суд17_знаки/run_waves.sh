#!/usr/bin/env bash
# ./run_waves.sh [РАУНД] — суд 17 (знаки, 1.4): сесії Claude по одній, Gemini поруч із першою. Учасник зі
# звітом цього раунду пропускається. Прапор безпеки — стоп для цього судді: жодної автоматичної спроби знову. Інший обрив — ще одна спроба
R=${1:-1}
K=$(cd "$(dirname "$0")" && pwd)
export NIGREDO_HOME="$K/власник"
# ПК: еталон — на Python 3.13 з системною libsqlite3 (як в Атанора); системний python3 — 3.12
[ -x "$HOME/.nigredo/py313/bin/python3" ] && export PATH="$HOME/.nigredo/py313/bin:$PATH"
[ -n "$NO_GEMINI" ] || export GEMINI_ENV_FILE="${GEMINI_ENV_FILE:?задайте GEMINI_ENV_FILE — файл .env з ключем Gemini (або NO_GEMINI=1)}"
mkdir -p "$K/protokol"
# модель судді (Денис, 2026-11-14: окремі моделі — окремі ліміти й інший погляд): MODEL_<суддя>=opus|sonnet|haiku;
# без змінної — типова модель сесії
member() {
  m=$1
  eval "MODEL=\${MODEL_$m:-}"
  [ -s "$K/$m/звіт_раунд$R.md" ] && { echo "$m: звіт раунду $R уже є"; return; }
  if [ "$R" = 1 ]; then
    P="Ти учасник консиліуму. Твоя роль — у CLAUDE.md цієї теки. Це СУД 17 про три нові гліфи мови Nigredo (1.4): η — нормальна форма NFC, ω — код знака й знак за кодом, γ — категорія знака. Звичайна робота суду — програми з цими гліфами на трьох виконавцях і звірка з нормою Unicode; спроб вийти за печатку чи дозволи власника не треба. Прочитай ../ПРАВИЛА.md і ../ЗАВДАННЯ.md, виконай завдання у своїй теці й напиши звіт_раунд1.md за шаблоном ПРАВИЛ. Відповідай українською."
  else
    P="Ти учасник консиліуму. Твоя роль — у CLAUDE.md цієї теки. Це РАУНД 2 суду 17 про три нові гліфи мови Nigredo (1.4): η — нормальна форма NFC, ω — код знака й знак за кодом, γ — категорія знака. Звичайна робота суду — програми з цими гліфами на трьох виконавцях і звірка з нормою Unicode; спроб вийти за печатку чи дозволи власника не треба. Прочитай ../ПРАВИЛА.md (розділ «Раунд 2»: нова заморожена версія й хеші), свій звіт_раунд1.md, ../protokol/раунд1/ і ../protokol/ПІДСУМОК.md (тепер можна), виконай завдання раунду 2 у своїй теці й напиши звіт_раунд2.md. Нічого не питай. Відповідай українською."
  fi
  TOOLS="Read,Edit(./**),Glob,Grep,Bash(ngr:*),Bash(sha256sum:*),Bash(../ngr17.sh:*),Bash(../нгр17_еталон.sh:*),Bash(../нгр17_альбедо.sh:*),Bash(../міра.sh:*)"
  for a in 1 2; do
    L="$K/protokol/лог_${m}_р${R}_$a.txt"
    ( cd "$K/$m" && claude -p "$P${MODEL:+ У першому рядку звіту напиши: «Модель: $MODEL».}" ${MODEL:+--model "$MODEL"} --allowedTools "$TOOLS" > "$L" 2>&1; echo "$m раунд $R спроба $a exit $?" )
    [ -s "$K/$m/звіт_раунд$R.md" ] && return
    if grep -q 'safeguards flagged' "$L"; then echo "$m: прапор безпеки, далі не пробуємо"; return; fi
    if grep -q "hit your .*limit" "$L"; then echo "$m: ліміт сесій — зупинка, перезапустити пізніше тим самим"; return 2; fi
    sleep 60
  done
}
gemini() {
  [ -s "$K/gemini/звіт_раунд$R.md" ] && { echo "gemini: звіт раунду $R уже є"; return; }
  ( cd "$K/gemini" && python3 -I gemini_member.py "$R" > "$K/protokol/лог_gemini_р$R.txt" 2>&1; echo "gemini раунд $R exit $?" )
}
if [ -n "$NO_GEMINI" ]; then member skeptyk; S=$?; else gemini & member skeptyk; S=$?; wait; fi
[ "$S" = 2 ] && { echo "суд 17, раунд $R: зупинено на ліміті сесій"; exit 0; }
for m in praktyk movoznavets audytor novachok orkestrator; do member $m; [ $? = 2 ] && break; done
echo "суд 17, раунд $R, завершено"
