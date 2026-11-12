#!/bin/sh
# 1.3, Атанор: бінарник цієї гілки, де б вона не лежала
R=$(cd "$(dirname "$0")/../.." && pwd)
exec "$(ls -t "$R"/athanor/target/*/release/athanor | head -1)" "$@"
