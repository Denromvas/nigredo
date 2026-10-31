#!/usr/bin/env bash
# ./run_waves.sh 1|2 — суд 13 (Альбедо): сесії Claude по одній (памʼять телефона), Gemini — поруч із першою; учасник зі звітом
# пропускається, тож після обриву той самий виклик продовжує, а не починає наново.
R=$1; K=$(cd "$(dirname "$0")" && pwd)
export NIGREDO_HOME="$K/власник"
export GEMINI_ENV_FILE="${GEMINI_ENV_FILE:?задайте GEMINI_ENV_FILE — файл .env з ключем Gemini}"
REF="python3 /root/ai-agents/Nigredo/interpreter/ngr.py"
/data/data/com.termux/files/usr/bin/termux-wake-lock 2>/dev/null
mkdir -p "$K/protokol"
member() {
  m=$1
  [ -s "$K/$m/звіт_раунд$R.md" ] && { echo "$m: звіт уже є"; return; }
  if [ "$R" = 1 ]; then
    P="Ти учасник консиліуму. Твоя роль — у CLAUDE.md цієї теки. Це ТРИНАДЦЯТИЙ СУД — Альбедо, межа, що не залежить від чесності ядра: прочитай ../ПРАВИЛА.md, ../ЗАВДАННЯ.md і /root/ai-agents/Nigredo/spec/пропозиції/альбедо.md, виконай раунд 1 і збережи звіт_раунд1.md у цій теці. Працюй самостійно, нічого не питай."
  else
    P="Ти учасник консиліуму. Твоя роль — у CLAUDE.md цієї теки. Це РАУНД 2 тринадцятого суду: прочитай ../protokol/раунд1/ (тепер можна), виконай раунд 2 з ../ПРАВИЛА.md і збережи звіт_раунд2.md у цій теці. Версія заморожена (перевір sha256 з ../ПРАВИЛА.md). Нічого не питай."
  fi
  TOOLS="Read,Edit(./**),Glob,Grep,Bash(ngr:*),Bash($REF:*),Bash(ATHANOR_NO_FALLBACK=1 ngr:*),Bash(sha256sum:*),Bash(../зло.sh:*),Bash(../альбедо.sh:*)"
  for a in 1 2 3; do   # обрив (proot/Bun падає під навантаженням) — ще спроба; кожна спроба — свій лог
    ( cd "$K/$m" && claude -p "$P" --allowedTools "$TOOLS" > "$K/protokol/лог_${m}_р${R}_$a.txt" 2>&1; echo "$m спроба $a exit $?" )
    [ -s "$K/$m/звіт_раунд$R.md" ] && return
    sleep 60
  done
}
gemini() {
  [ -s "$K/gemini/звіт_раунд$R.md" ] && { echo "gemini: звіт уже є"; return; }
  ( cd "$K/gemini" && python3 -I gemini_member.py "$R" > "$K/protokol/лог_gemini_р$R.txt" 2>&1; echo "gemini exit $?" )
}
if [ -n "$NO_GEMINI" ]; then member skeptyk; else gemini & member skeptyk & wait; fi
for m in praktyk movoznavets audytor novachok orkestrator; do member $m; done
echo "раунд $R завершено"
