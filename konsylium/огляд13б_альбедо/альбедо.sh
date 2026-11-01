#!/bin/sh
# ../альбедо.sh ПРОГРАМА.ngr: звичайний запуск через модуль, власник суду
K=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$K/../.." && pwd)
NIGREDO_HOME="$K/власник" exec python3 "$ROOT/albedo/ngr_альбедо.py" "$@"
