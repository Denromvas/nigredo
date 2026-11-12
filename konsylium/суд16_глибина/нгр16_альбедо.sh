#!/bin/sh
# 1.3, Альбедо: Атанор як модуль WASM під господарем
R=$(cd "$(dirname "$0")/../.." && pwd)
exec python3 "$R/albedo/ngr_альбедо.py" "$@"
