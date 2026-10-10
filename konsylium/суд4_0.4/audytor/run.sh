#!/bin/bash
# Допоміжний: запускає кожен .ngr з аргументів, друкує вивід і код виходу.
for f in "$@"; do
  echo "=== $f"
  timeout 300 ngr "$f" 2>&1 | head -40
  echo "код ${PIPESTATUS[0]}"
done
