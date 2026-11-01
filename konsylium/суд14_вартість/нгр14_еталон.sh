#!/bin/sh
# варіант Б, еталон
R=$(cd "$(dirname "$0")/../.." && pwd)
exec python3 "$R/interpreter/ngr.py" "$@"
