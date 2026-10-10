#!/bin/bash
# запуск кількох програм з кодом виходу: bash r.sh файл.ngr [ще…]
for f in "$@"; do
  echo "=== $f"
  ngr "$f"
  echo "--- код виходу: $?"
done
