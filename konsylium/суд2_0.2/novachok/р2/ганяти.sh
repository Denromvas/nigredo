#!/bin/bash
# проганяє проби раунду 2: вивід, код, слід, перевірка сліду, печатка/розбір
cd "$(dirname "$(readlink -f "$0")")"
for f in "$@"; do
  b="${f%.ngr}"
  echo "===== $f"
  timeout 60 ngr --слід "$b.jsonl" "$f" 2>&1 | tail -6
  echo "код ${PIPESTATUS[0]}"
  echo "--- слід:"
  cut -c1-230 "$b.jsonl" 2>/dev/null
  echo "--- перевірка:"
  ngr --перевірити-слід "$b.jsonl" 2>&1 | tail -3
  echo "--- печатка:"
  ngr --печатка "$f" 2>&1
  echo "--- розбір:"
  ngr --розбір "$f" 2>&1
done
