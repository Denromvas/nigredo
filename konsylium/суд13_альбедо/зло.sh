#!/bin/sh
# ../зло.sh МОДУЛЬ.rs ПРОГРАМА.ngr [прапорці господаря]: свій модуль під господарем. Один файл, без crate, збірка лише для wasm32.
set -eu
K=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$K/../.." && pwd)
[ $# -ge 2 ] || { echo '✗ ../зло.sh МОДУЛЬ.rs ПРОГРАМА.ngr [прапорці господаря]' >&2; exit 2; }
src=$1; prog=$2; shift 2
case "$src" in *.rs) ;; *) echo '✗ модуль — файл .rs' >&2; exit 2 ;; esac
out="${src%.rs}.wasm"
PATH="$HOME/.cargo/bin:$PATH" rustc --target wasm32-unknown-unknown --edition 2021 -O -C panic=abort --crate-type cdylib \
  -C link-args=--import-memory -o "$out" "$src"
NIGREDO_HOME="$K/власник" exec node "$ROOT/albedo/хост.mjs" "$@" "$out" "$prog"
