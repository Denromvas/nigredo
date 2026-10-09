#!/bin/bash
# ганяє кожен рядок файлу випадків як окрему програму (¶ = новий рядок)
dir=$(dirname "$(readlink -f "$1")")
while IFS= read -r c; do
  [ -z "$c" ] && continue
  printf '🜂 「т」 【】\n%s\n' "${c//¶/$'\n'}" > "$dir/т.ngr"
  out=$(timeout 60 ngr "$dir/т.ngr" 2>&1 | tr '\n' '⏎')
  echo "$c  →  $out"
done < "$1"
