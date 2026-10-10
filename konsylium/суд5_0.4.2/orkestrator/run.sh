#!/bin/bash
# запуск програм з виводом коду виходу: run.sh ФАЙЛ... (аргументи ngr — після «::»)
cd "$(dirname "$0")"
for f in "$@"; do
  echo "== ngr $f"
  ngr $f
  echo "[код $?]"
done
