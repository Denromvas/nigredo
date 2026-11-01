#!/usr/bin/env bash
# ./run_waves.sh — суд 14 (вартість): сесії Claude по одній, Gemini поруч із першою. Учасник зі звітом пропускається.
# Прапор безпеки — стоп для цього судді: жодної автоматичної спроби знову. Інший обрив — ще одна спроба.
K=$(cd "$(dirname "$0")" && pwd)
export NIGREDO_HOME="$K/власник"
export GEMINI_ENV_FILE="${GEMINI_ENV_FILE:?задайте GEMINI_ENV_FILE — файл .env з ключем Gemini}"
/data/data/com.termux/files/usr/bin/termux-wake-lock 2>/dev/null
mkdir -p "$K/protokol"
member() {
  m=$1
  [ -s "$K/$m/звіт_раунд1.md" ] && { echo "$m: звіт уже є"; return; }
  P="Ти учасник консиліуму. Твоя роль — у CLAUDE.md цієї теки. Це СУД 14 про модель вартості мови Nigredo: межі кроків і розміру, звичайні програми, без атак. Прочитай ../ПРАВИЛА.md і ../ЗАВДАННЯ.md, зроби завдання й запиши звіт у звіт_раунд1.md за форматом із ПРАВИЛ."
  TOOLS="Read,Edit(./**),Write(./**),Glob,Grep,Bash(ngr:*),Bash(sha256sum:*),Bash(../ngr14.sh:*),Bash(../нгр14_еталон.sh:*),Bash(../міра.sh:*)"
  for a in 1 2; do
    L="$K/protokol/лог_${m}_р1_$a.txt"
    ( cd "$K/$m" && claude -p "$P" --allowedTools "$TOOLS" > "$L" 2>&1; echo "$m спроба $a exit $?" )
    [ -s "$K/$m/звіт_раунд1.md" ] && return
    if grep -q 'safeguards flagged' "$L"; then echo "$m: прапор безпеки, далі не пробуємо"; return; fi
    sleep 60
  done
}
gemini() {
  [ -s "$K/gemini/звіт_раунд1.md" ] && { echo "gemini: звіт уже є"; return; }
  ( cd "$K/gemini" && python3 -I gemini_member.py > "$K/protokol/лог_gemini_р1.txt" 2>&1; echo "gemini exit $?" )
}
if [ -n "$NO_GEMINI" ]; then member skeptyk; else gemini & member skeptyk & wait; fi
for m in praktyk movoznavets audytor novachok orkestrator; do member $m; done
/data/data/com.termux/files/usr/bin/termux-wake-unlock 2>/dev/null
echo "суд завершено"
