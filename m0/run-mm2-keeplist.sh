#!/usr/bin/env bash
# F-3 / B4 evidence runner — the MAIN_MODULE=2 + keep-list path.
#
# Shows that:
#   1. A bare MM=2 host (only 3 exported functions) cannot even instantiate a
#      wasm-EH side module: the exception tag is not exported.
#   2. Exporting just the tag is not enough either (the rest of the side's
#      imports are still missing).
#   3. MM=2 + a keep-list generated from the side module's own imports (which
#      includes the tag) dlopens and passes the full suite.
#
# Step 3 is the one that matters: it shows the tag gap downstream is fixable
# with the existing gen-keep-list.sh pipeline, no MAIN_MODULE=1 needed.
#
# Usage: sh run-mm2-keeplist.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
EMSDK="${EMSDK:-$ROOT/../toolchain/emsdk}"
EM="$EMSDK/upstream/emscripten"
BIN="$EMSDK/upstream/bin"

M0="$ROOT/build-wasm32"
[ -f "$M0/minifn.so" ] || { echo "FATAL: run 'sh $ROOT/run-m0.sh' first."; exit 2; }

WORK="$ROOT/build-mm2"; rm -rf "$WORK"; mkdir -p "$WORK"; cd "$WORK"
cp "$M0/minifn.so" .

report() { # <label> <host.wasm>
  node -e '
const fs=require("fs");
const m=new WebAssembly.Module(fs.readFileSync(process.argv[2]));
const ex=WebAssembly.Module.exports(m);
const tags=ex.filter(e=>e.kind==="tag").map(e=>e.name);
console.log(process.argv[1]+": exports="+ex.length+" tags=["+tags.join(",")+"]");
' "$1" "$2"
}

# --- 1. bare MM=2, no keep-list -------------------------------------------
echo "== 1. MM=2 bare (only the 3 app functions exported) =="
"$EM/em++" -O2 -fwasm-exceptions -pthread -sSHARED_MEMORY=1 -sMAIN_MODULE=2 \
  -sALLOW_MEMORY_GROWTH=1 \
  -sEXPORTED_FUNCTIONS='["_host_det2","_host_error","_main"]' \
  -o bare.js "$ROOT/host.cc" 2>/dev/null
report "bare" bare.wasm
echo -n "   dlopen: "; timeout 120 node bare.js 2>&1 | grep -m1 -E 'PASS dlopen|FAIL dlopen' || true

# --- 2. MM=2 + only the tags exported -------------------------------------
echo
echo "== 2. MM=2 + tags exported, nothing else =="
"$EM/em++" -O2 -fwasm-exceptions -pthread -sSHARED_MEMORY=1 -sMAIN_MODULE=2 \
  -sALLOW_MEMORY_GROWTH=1 \
  -sEXPORTED_FUNCTIONS='["_host_det2","_host_error","_main"]' \
  -Wl,--export-if-defined=__cpp_exception -Wl,--export-if-defined=__c_longjmp \
  -o tagonly.js "$ROOT/host.cc" 2>/dev/null
report "tagonly" tagonly.wasm
echo -n "   dlopen: "; timeout 120 node tagonly.js 2>&1 | grep -m1 -E 'PASS dlopen|FAIL dlopen|TypeError' || true

# --- 3. MM=2 + keep-list from the side module's imports -------------------
echo
echo "== 3. MM=2 + keep-list built from the side module's IMPORT section =="
# Same pipeline as downstream gen-keep-list.sh (wasm-dis + regex + filter).
"$BIN/wasm-dis" minifn.so 2>/dev/null \
  | grep -oE '^ \(import "(env|GOT\.mem|GOT\.func)" "[^"]+"' \
  | sed -E 's/.*"([^"]+)"$/\1/' \
  | grep -vE '^(memory|__indirect_function_table|__stack_pointer|__memory_base|__table_base|emscripten_run_script|exit|__assert_fail)$' \
  | LC_ALL=C sort -u > keep.txt
echo "   keep-list: $(wc -l < keep.txt) symbols (tag included: $(grep -c '^__cpp_exception$' keep.txt))"
FLAGS=""
while read -r s; do FLAGS="$FLAGS -Wl,--export-if-defined=$s"; done < keep.txt
# shellcheck disable=SC2086
"$EM/em++" -O2 -fwasm-exceptions -pthread -sSHARED_MEMORY=1 -sMAIN_MODULE=2 \
  -sALLOW_MEMORY_GROWTH=1 \
  -sEXPORTED_FUNCTIONS='["_host_det2","_host_error","_main"]' \
  $FLAGS -o keeplist.js "$ROOT/host.cc" 2>/dev/null
report "keeplist" keeplist.wasm
echo "   --- full run ---"
timeout 180 node keeplist.js
