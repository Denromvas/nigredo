#!/usr/bin/env bash
# ./run_round.sh 1|2 — раунд для всіх учасників-Claude паралельно
R=$1; K=$(cd "$(dirname "$0")" && pwd)
export NIGREDO_HOME="$K/власник"
PY="python3 /root/ai-agents/Nigredo/porivniannia/ngrpy.py"
MCPT="mcp__nigredo__nigredo_vykonaty,mcp__nigredo__nigredo_pechatka,mcp__nigredo__nigredo_rozbir,mcp__nigredo__nigredo_pamyatka,mcp__nigredo__nigredo_pereviryty_slid"
for m in skeptyk praktyk movoznavets audytor novachok orkestrator; do
  if [ "$R" = 1 ]; then
    P="Ти учасник консиліуму. Твоя роль — у CLAUDE.md цієї теки. Прочитай ../ПРАВИЛА.md і ../ЗАВДАННЯ.md і виконай РАУНД 1 повністю (А–Г, Ж, Д, Е) і збережи звіт_раунд1.md за шаблоном. Працюй самостійно, нічого не питай."
  else
    P="Ти учасник консиліуму. Твоя роль — у CLAUDE.md цієї теки. Це РАУНД 2: прочитай ../protokol/раунд1/ (тепер можна), виконай раунд 2 з ../ПРАВИЛА.md і збережи звіт_раунд2.md. Версія заморожена (перевір sha256 з ../ПРАВИЛА.md). Нічого не питай."
  fi
  if [ "$m" = novachok ]; then
    TOOLS="Read,Write,Edit,Glob,$MCPT"; EXTRA=(--mcp-config "$K/novachok/mcp.json" --strict-mcp-config)
  else
    TOOLS="Read,Write,Edit,Glob,Grep,Bash(ngr:*),Bash($PY:*)"; EXTRA=()
  fi
  ( cd "$K/$m" && claude -p "$P" --allowedTools "$TOOLS" "${EXTRA[@]}" > "$K/protokol/лог_${m}_р$R.txt" 2>&1; echo "$m exit $?" ) &
done
wait
