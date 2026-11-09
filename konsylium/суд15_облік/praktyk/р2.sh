#!/bin/sh
# р2.sh ПРОГРАМА [прапорці] [-- аргументи]: кроки, код, зупинка й кінець виводу в 1.1 (ngr), 1.2 Атанор, 1.2 еталон.
# ВИК=ат|ет|11 (через кому) — лише ці виконавці.
D=$(cd "$(dirname "$0")" && pwd)
T="$D/тимч/$$"
mkdir -p "$T"
P="$1"
shift
for X in 11 ат ет; do
  case ",${ВИК:-11,ат,ет}," in *",$X,"*) ;; *) continue ;; esac
  case $X in 11) C=ngr ;; ат) C="$D/../ngr15.sh" ;; ет) C="$D/../нгр15_еталон.sh" ;; esac
  t0=$(date +%s.%N)
  "$C" "$P" --слід - "$@" >"$T/$X.out" 2>"$T/$X.err"
  c=$?
  t1=$(date +%s.%N)
  k=$(grep -o '"кроків": [0-9]*' "$T/$X.err" | tail -1 | grep -o '[0-9]*$')
  i=$(grep -o '"інтерпретатор": "[^"]*"' "$T/$X.err" | head -1 | cut -d'"' -f4 | cut -c1-14)
  z=$(grep -v '^{' "$T/$X.err" | tail -3 | tr '\n' ' ' | cut -c1-220)
  o=$(tail -n 2 "$T/$X.out" | tr '\n' '|' | cut -c1-140)
  s=$(echo "$t1 - $t0" | bc)
  echo "$X [$i] код $c, кроків $k, ${s} с | $z| вивід: $o"
done
rm -rf "$T"
