#!/bin/sh
# 1.3, еталон
R=$(cd "$(dirname "$0")/../.." && pwd)
exec python3 "$R/interpreter/ngr.py" "$@"
