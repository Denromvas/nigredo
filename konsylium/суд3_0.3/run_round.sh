#!/usr/bin/env bash
# ./run_round.sh 1|2 — раунд для всіх учасників-Claude паралельно
R=$1; K=$(cd "$(dirname "$0")" && pwd)
export NIGREDO_HOME="$K/власник"
PY="python3 /root/ai-agents/Nigredo/porivniannia/ngrpy.py"
for m in skeptyk praktyk movoznavets audytor novachok orkestrator; do
  if [ "$R" = 1 ]; then
    P="Ти учасник консиліуму. Твоя роль — у CLAUDE.md цієї теки. Прочитай ../ПРАВИЛА.md і ../ЗАВДАННЯ.md і виконай РАУНД 1 повністю: завдання А–Г обома мовами (Nigredo: ngr; ngrpy: $PY файл.py), атаки Д, чужі програми Е, і збережи звіт_раунд1.md за шаблоном. Працюй самостійно, нічого не питай."
  else
    P="Ти учасник консиліуму. Твоя роль — у CLAUDE.md цієї теки. Це РАУНД 2. Звіти першого раунду всіх учасників — у ../protokol/раунд1/ (тепер можна читати), твій — звіт_раунд1.md. Збережи звіт_раунд2.md за правилами раунду 2 з ../ПРАВИЛА.md. Нічого не питай."
  fi
  ( cd "$K/$m" && claude -p "$P" --allowedTools "Read,Write,Edit,Glob,Grep,Bash(ngr:*),Bash($PY:*)" > "$K/protokol/лог_${m}_р$R.txt" 2>&1; echo "$m exit $?" ) &
done
wait
