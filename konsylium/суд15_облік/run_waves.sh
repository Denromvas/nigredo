#!/usr/bin/env bash
# ./run_waves.sh [РАУНД] — суд 15 (облік «робота»): сесії Claude по одній, Gemini поруч із першою. Учасник зі звітом
# цього раунду пропускається. Прапор безпеки — стоп для цього судді: жодної автоматичної спроби знову. Інший обрив — ще одна спроба.
R=${1:-1}
K=$(cd "$(dirname "$0")" && pwd)
export NIGREDO_HOME="$K/власник"
# ПК: еталон — на Python 3.13 з системною libsqlite3 (як в Атанора); системний python3 — 3.12
[ -x "$HOME/.nigredo/py313/bin/python3" ] && export PATH="$HOME/.nigredo/py313/bin:$PATH"
export GEMINI_ENV_FILE="${GEMINI_ENV_FILE:?задайте GEMINI_ENV_FILE — файл .env з ключем Gemini}"
mkdir -p "$K/protokol"
member() {
  m=$1
  [ -s "$K/$m/звіт_раунд$R.md" ] && { echo "$m: звіт раунду $R уже є"; return; }
  if [ "$R" = 1 ]; then
    P="Ти учасник консиліуму. Твоя роль — у CLAUDE.md цієї теки. Це СУД 15 про облік «робота» (1.2) мови Nigredo: межі кроків і розміру, звичайні програми, без атак. Прочитай ../ПРАВИЛА.md і ../ЗАВДАННЯ.md, зроби завдання й запиши звіт у звіт_раунд1.md за форматом із ПРАВИЛ."
  else
    P="Ти учасник консиліуму. Твоя роль — у CLAUDE.md цієї теки. Це РАУНД 2 суду 15 про облік «робота» (1.2) мови Nigredo: межі кроків і розміру, звичайні програми, без атак. Прочитай ../ПРАВИЛА.md (розділ «Раунд 2»: нова заморожена версія й хеші), свій звіт_раунд1.md, ../protokol/раунд1/ і ../protokol/ПІДСУМОК.md (тепер можна), зроби завдання раунду 2 й запиши звіт у звіт_раунд2.md. Нічого не питай."
  fi
  TOOLS="Read,Edit(./**),Glob,Grep,Bash(ngr:*),Bash(sha256sum:*),Bash(../ngr15.sh:*),Bash(../нгр15_еталон.sh:*),Bash(../міра.sh:*)"
  for a in 1 2; do
    L="$K/protokol/лог_${m}_р${R}_$a.txt"
    ( cd "$K/$m" && claude -p "$P" --allowedTools "$TOOLS" > "$L" 2>&1; echo "$m раунд $R спроба $a exit $?" )
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
if [ -n "$NO_GEMINI" ]; then member skeptyk; else gemini & member skeptyk & wait; fi
for m in praktyk movoznavets audytor novachok orkestrator; do member $m; [ $? = 2 ] && break; done
echo "суд, раунд $R, завершено"
