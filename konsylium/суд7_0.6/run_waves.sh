#!/usr/bin/env bash
# ./run_waves.sh 1|2 — раунд хвилями по 3 учасники (памʼять телефона); учасник зі звітом пропускається,
# тож після обриву той самий виклик продовжує, а не починає наново. Gemini — у першій хвилі.
R=$1; K=$(cd "$(dirname "$0")" && pwd)
export NIGREDO_HOME="$K/власник"
PY="python3 /root/ai-agents/Nigredo/porivniannia/ngrpy.py"
MCPT="mcp__nigredo__nigredo_vykonaty,mcp__nigredo__nigredo_pechatka,mcp__nigredo__nigredo_rozbir,mcp__nigredo__nigredo_pamyatka,mcp__nigredo__nigredo_pereviryty_slid,mcp__nigredo__nigredo_pereviryty,mcp__nigredo__nigredo_brauzer"
/data/data/com.termux/files/usr/bin/termux-wake-lock 2>/dev/null
python3 "$K/сервер.py" & SRV=$!; disown $SRV   # сервер суду 127.0.0.1:28707; disown — щоб wait хвиль не чекав на нього
trap 'kill $SRV 2>/dev/null' EXIT
sleep 1
member() {
  m=$1
  [ -s "$K/$m/звіт_раунд$R.md" ] && { echo "$m: звіт уже є"; return; }
  if [ "$R" = 1 ]; then
    P="Ти учасник консиліуму. Твоя роль — у CLAUDE.md цієї теки. Це СЬОМИЙ СУД: прочитай ../ПРАВИЛА.md і ../ЗАВДАННЯ.md і виконай РАУНД 1, збережи звіт_раунд1.md. Працюй самостійно, нічого не питай."
  else
    P="Ти учасник консиліуму. Твоя роль — у CLAUDE.md цієї теки. Це РАУНД 2: прочитай ../protokol/раунд1/ (тепер можна), виконай раунд 2 з ../ПРАВИЛА.md і збережи звіт_раунд2.md. Версія заморожена (перевір sha256 з ../ПРАВИЛА.md). Нічого не питай."
  fi
  if [ "$m" = novachok ]; then
    TOOLS="Read,Write,Edit,Glob,$MCPT"; EXTRA=(--mcp-config "$K/novachok/mcp.json" --strict-mcp-config)
  else
    TOOLS="Read,Write,Edit,Glob,Grep,Bash(ngr:*),Bash($PY:*)"; EXTRA=()
  fi
  ( cd "$K/$m" && claude -p "$P" --allowedTools "$TOOLS" "${EXTRA[@]}" > "$K/protokol/лог_${m}_р$R.txt" 2>&1; echo "$m exit $?" )
}
gemini() {
  [ -s "$K/gemini/звіт_раунд$R.md" ] && { echo "gemini: звіт уже є"; return; }
  ( cd "$K/gemini" && NIGREDO_HOME="$K/власник" python3 -I gemini_member.py "$R" > "$K/protokol/лог_gemini_р$R.txt" 2>&1; echo "gemini exit $?" )
}
gemini & member skeptyk & member praktyk & member movoznavets & wait
member audytor & member novachok & member orkestrator & wait
echo "раунд $R завершено"
