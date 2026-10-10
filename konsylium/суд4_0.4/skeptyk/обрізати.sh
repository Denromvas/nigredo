#!/bin/bash
# обрізати слід $1 на кожному рядку й перевірити кожен варіант
f="$1"
total=$(wc -l < "$f")
for n in $(seq 1 $((total - 1))); do
  head -n "$n" "$f" > "звіти_обрізаний_$n.jsonl"
  printf '%s: ' "$n"
  ngr --перевірити-слід "звіти_обрізаний_$n.jsonl"
  rm -f "звіти_обрізаний_$n.jsonl"
done
