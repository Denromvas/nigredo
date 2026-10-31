#!/bin/sh
# Альбедо: SQLite і expat за відомими sha256 + clang → c/дж/*.o; далі cargo. Чужі джерела в репозиторій не кладемо: це 10 МБ.
set -eu
cd "$(dirname "$0")"
V=3460100; R=2024; SUM=77823cb110929c2bcb0f5d48e4833b5c59a8a6e40cdea3936b99e199dbbe5784
D=c/дж; mkdir -p "$D"
if [ ! -f "$D/sqlite3.c" ]; then
  [ -f "$D/a.zip" ] || curl -sSL -o "$D/a.zip" "https://www.sqlite.org/$R/sqlite-amalgamation-$V.zip"
  echo "$SUM  $D/a.zip" | sha256sum -c - >/dev/null
  python3 -I -c "
import zipfile,sys
z=zipfile.ZipFile(sys.argv[1])
for n in ('sqlite3.c','sqlite3.h'):
    open(sys.argv[2]+'/'+n,'wb').write(z.read('sqlite-amalgamation-$V/'+n))" "$D/a.zip" "$D"
fi
EV=2.7.1; ESUM=0cce2e6e69b327fc607b8ff264f4b66bdf71ead55a87ffd5f3143f535f15cfa2
if [ ! -d "$D/expat" ]; then
  [ -f "$D/e.tgz" ] || curl -sSL -o "$D/e.tgz" "https://github.com/libexpat/libexpat/releases/download/R_2_7_1/expat-$EV.tar.gz"
  echo "$ESUM  $D/e.tgz" | sha256sum -c - >/dev/null
  python3 -I -c "
import os,sys,tarfile
t=tarfile.open(sys.argv[1])
for m in t.getmembers():
    if '/lib/' in m.name and m.isfile() and m.name.endswith(('.c','.h')):
        n=os.path.join(sys.argv[2],os.path.basename(m.name)); os.makedirs(sys.argv[2],exist_ok=True); open(n,'wb').write(t.extractfile(m).read())" "$D/e.tgz" "$D/expat"
fi
# ті самі значення опцій, що в звичного libsqlite3, де вони міняють результат; потоків, розширень і файлів для тимчасового тут немає
FLAGS="-DSQLITE_OS_OTHER=1 -DSQLITE_THREADSAFE=0 -DSQLITE_OMIT_LOAD_EXTENSION -DSQLITE_OMIT_LOCALTIME -DSQLITE_TEMP_STORE=3 -DSQLITE_MAX_MMAP_SIZE=0 -DSQLITE_DEFAULT_LOCKING_MODE=1
 -DSQLITE_DEFAULT_RECURSIVE_TRIGGERS=1 -DSQLITE_SECURE_DELETE -DSQLITE_SOUNDEX -DSQLITE_LIKE_DOESNT_MATCH_BLOBS -DSQLITE_ALLOW_ROWID_IN_VIEW
 -DSQLITE_ENABLE_MATH_FUNCTIONS -DSQLITE_ENABLE_FTS3 -DSQLITE_ENABLE_FTS3_PARENTHESIS -DSQLITE_ENABLE_FTS4 -DSQLITE_ENABLE_FTS5 -DSQLITE_ENABLE_RTREE
 -DSQLITE_ENABLE_COLUMN_METADATA -DSQLITE_ENABLE_DBSTAT_VTAB -DSQLITE_ENABLE_DBPAGE_VTAB -DSQLITE_ENABLE_STMTVTAB
 -DSQLITE_MAX_COLUMN=2000 -DSQLITE_MAX_VARIABLE_NUMBER=250000 -DSQLITE_MAX_FUNCTION_ARG=127 -DSQLITE_MAX_SCHEMA_RETRY=25 -DSQLITE_MAX_ATTACHED=10
 -DSQLITE_MAX_PAGE_COUNT=0xfffffffe -DHAVE_ISNAN=1 -DNDEBUG"
CC="clang --target=wasm32-unknown-unknown -O2 -nostdlibinc -Ic/include -I$D -I$D/expat -ffunction-sections -fdata-sections"
[ "$D/база.o" -nt c/база.c ] && [ "$D/база.o" -nt "$0" ] || $CC $FLAGS -c c/база.c -o "$D/база.o"
[ "$D/libc.o" -nt c/libc.c ] || $CC -c c/libc.c -o "$D/libc.o"
for f in xmlparse xmlrole xmltok; do [ "$D/$f.o" -nt "$0" ] || $CC -DNDEBUG -c "$D/expat/$f.c" -o "$D/$f.o"; done
# cargo не бачить обʼєктів на C: новіший за модуль обʼєкт — перелінкувати
W=target/wasm32-unknown-unknown/release/albedo.wasm
for o in "$D"/*.o; do [ "$W" -nt "$o" ] || touch src/lib.rs; done
CARGO=cargo
[ -x "$HOME/.cargo/bin/cargo" ] && CARGO="$HOME/.cargo/bin/cargo"
# обʼєкти — лише тут, а не в .cargo/config.toml: його успадковує зло/, де бази немає
PATH="$HOME/.cargo/bin:$PATH" $CARGO build --release --config 'target.wasm32-unknown-unknown.rustflags=["-C","link-arg=c/дж/база.o","-C","link-arg=c/дж/libc.o","-C","link-arg=c/дж/xmlparse.o","-C","link-arg=c/дж/xmlrole.o","-C","link-arg=c/дж/xmltok.o"]' "$@"
