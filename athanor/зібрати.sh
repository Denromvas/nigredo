#!/bin/sh
# Збірка Атанора: rustup (якщо є) для цієї машини; бінарник — athanor/target/<ціль>/release/athanor.
# Термукс-rustc збирає під Android (повільний запуск у proot; libexpat/libsqlite3 Ubuntu через dlopen недоступні).
set -e
cd "$(dirname "$0")"
CARGO=cargo
[ -x "$HOME/.cargo/bin/cargo" ] && CARGO="$HOME/.cargo/bin/cargo"
TARGET=$($CARGO -vV 2>/dev/null | sed -n 's/^host: //p')
[ -n "$TARGET" ] || TARGET=$(rustc -vV | sed -n 's/^host: //p')
RUST_MIN_STACK=67108864 $CARGO build --release --target "$TARGET"
echo "athanor/target/$TARGET/release/athanor"
