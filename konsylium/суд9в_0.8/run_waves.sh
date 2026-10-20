#!/usr/bin/env bash
# ./run_waves.sh 1 — суд 9в (один раунд): сесії Claude по одній (памʼять телефона), Gemini — поруч із першою; учасник зі
# звітом пропускається, тож після обриву той самий виклик продовжує, а не починає наново.
R=$1; K=$(cd "$(dirname "$0")" && pwd)
export NIGREDO_HOME="$K/власник"
export GEMINI_ENV_FILE="${GEMINI_ENV_FILE:?задайте GEMINI_ENV_FILE — файл .env з ключем Gemini}"
REF="python3 /root/ai-agents/Nigredo/interpreter/ngr.py"
MCPT="mcp__nigredo__nigredo_vykonaty,mcp__nigredo__nigredo_pechatka,mcp__nigredo__nigredo_rozbir,mcp__nigredo__nigredo_pamyatka,mcp__nigredo__nigredo_pereviryty_slid,mcp__nigredo__nigredo_pereviryty,mcp__nigredo__nigredo_brauzer,mcp__nigredo__nigredo_testy,mcp__nigredo__nigredo_povtoryty,mcp__nigredo__nigredo_shvalyty"
/data/data/com.termux/files/usr/bin/termux-wake-lock 2>/dev/null
# сервер суду 127.0.0.1:28712; після обриву порт буває «зайнятим» мертвим сокетом — пробуємо, доки не стане
( for i in $(seq 60); do python3 "$K/сервер.py" && break; sleep 10; done ) > "$K/protokol/сервер.out" 2>&1 & SRV=$!; disown $SRV
trap 'pkill -P $SRV 2>/dev/null; kill $SRV 2>/dev/null' EXIT
sleep 1
member() {
  m=$1
  [ -s "$K/$m/звіт_раунд$R.md" ] && { echo "$m: звіт уже є"; return; }
  if [ "$R" = 1 ]; then
    P="Ти учасник консиліуму. Твоя роль — у CLAUDE.md цієї теки. Це СУД 9в — коротке підтвердження Nigredo 0.8 після виправлень суду 9б: прочитай ../ПРАВИЛА.md, ../ПІДСУМОК_суду9б.md і свій попередні_звіти/звіт_суду9б.md, виконай один раунд і збережи звіт_раунд1.md у цій теці. Працюй самостійно, нічого не питай."
  else
    P="Ти учасник консиліуму. Твоя роль — у CLAUDE.md цієї теки. Це РАУНД 2 девʼятого суду: прочитай ../protokol/раунд1/ (тепер можна), виконай раунд 2 з ../ПРАВИЛА.md і збережи звіт_раунд2.md у цій теці. Версія заморожена (перевір sha256 з ../ПРАВИЛА.md). Нічого не питай."
  fi
  if [ "$m" = novachok ]; then
    TOOLS="Read,Edit(./**),Glob,$MCPT"; EXTRA=(--mcp-config "$K/novachok/mcp.json" --strict-mcp-config)
  else
    TOOLS="Read,Edit(./**),Glob,Grep,Bash(ngr:*),Bash($REF:*),Bash(ATHANOR_WHY=1 ngr:*),Bash(ATHANOR_NO_FALLBACK=1 ngr:*),Bash(sha256sum:*)"; EXTRA=()
  fi
  for a in 1 2 3; do   # обрив (proot/Bun падає під навантаженням) — ще спроба; кожна спроба — свій лог
    ( cd "$K/$m" && claude -p "$P" --allowedTools "$TOOLS" "${EXTRA[@]}" > "$K/protokol/лог_${m}_р${R}_$a.txt" 2>&1; echo "$m спроба $a exit $?" )
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
