#!/bin/sh
# облік 1.2, еталон
R=$(cd "$(dirname "$0")/../.." && pwd)
exec python3 "$R/interpreter/ngr.py" "$@"
