#!/bin/sh
# ../межа.sh: наявні проби автора, лише запуск
K=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$K/../.." && pwd)
exec python3 "$ROOT/albedo/перевірити.py"
