#!/bin/bash
# Прогін атак суду 4 на 0.4.2. Кожну атаку копіюю в корінь своєї теки (відносні шляхи «дані/», «звіти/»
# мають рахуватися від неї), запускаю й прибираю копію.
# Запуск: bash прогін_суду4.sh > прогін_суду4.txt 2>&1
cd "$(dirname "$0")" || exit 1
Q="чи світ чорніє?"
for src in атаки_суду4/*.ngr; do
  f="с4_$(basename "$src")"
  cp "$src" "$f"
  echo "=================== $src"
  if grep -q '⌂ 1' "$f"; then
    timeout 120 ngr "$f" -- "$Q" "канал_$$_$RANDOM"
  elif grep -q '⌂' "$f"; then
    timeout 120 ngr "$f" -- "$Q"
  else
    timeout 120 ngr "$f"
  fi
  echo "--- код виходу: $?"
  rm -f "$f"
done
