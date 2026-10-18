#!/usr/bin/env bash
# ./run.sh — суд 8в: один суддя (Аудитор); після обриву той самий виклик продовжує (звіт є — пропуск)
K=$(cd "$(dirname "$0")" && pwd)
export NIGREDO_HOME="$K/власник"
/data/data/com.termux/files/usr/bin/termux-wake-lock 2>/dev/null
( for i in $(seq 60); do python3 "$K/сервер.py" && break; sleep 10; done ) > "$K/protokol/сервер.out" 2>&1 & SRV=$!; disown $SRV
trap 'pkill -P $SRV 2>/dev/null; kill $SRV 2>/dev/null' EXIT
sleep 1
m=audytor
P1="Ти учасник консиліуму. Твоя роль — у CLAUDE.md цієї теки. Це КОРОТКЕ ПІДТВЕРДЖЕННЯ (суд 8в): прочитай ../ПРАВИЛА.md і ../ЗАВДАННЯ.md і виконай, збережи звіт_раунд1.md. Працюй самостійно, нічого не питай."
P2="Ти учасник консиліуму. Твоя роль — у CLAUDE.md цієї теки. Суд 8в, РАУНД 2: прочитай розділ «Раунд 2» у ../ПРАВИЛА.md і свій звіт_раунд1.md, виконай раунд 2, збережи звіт_раунд2.md. Нічого не питай."
R=${1:-1}; P3="Ти учасник консиліуму. Твоя роль — у CLAUDE.md цієї теки. Суд 8в, РАУНД 3: прочитай розділ «Раунд 3» у ../ПРАВИЛА.md і свій звіт_раунд2.md, виконай раунд 3, збережи звіт_раунд3.md. Нічого не питай."
case $R in 2) P="$P2";; 3) P="$P3";; *) P="$P1";; esac
TOOLS="Read,Edit(./**),Write(./**),Glob,Grep,Bash(ngr:*)"
for a in 1 2 3; do
  [ -s "$K/$m/звіт_раунд$R.md" ] && break
  ( cd "$K/$m" && claude -p "$P" --allowedTools "$TOOLS" > "$K/protokol/лог_${m}_р${R}_$a.txt" 2>&1; echo "$m спроба $a exit $?" )
  sleep 60
done
echo "суд 8в завершено"
