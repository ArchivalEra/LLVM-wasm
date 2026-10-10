#!/usr/bin/env bash
# M1 optimization experiment — "link-time only" sweep.
#
# Rationale: the full build in m1/build-clang already exists, so anything that
# only touches the FINAL wasm (binaryen passes, stripping, re-linking from the
# cached objects) costs seconds-to-minutes instead of a full rebuild. This
# isolates how much of the 71 MB is "post-link recoverable" before we spend
# build time on compile-config experiments.
#
# Usage: sh m1/exp-link-sweep.sh <name> <input.wasm>
#   e.g. sh m1/exp-link-sweep.sh baseline m1/build-clang/bin/clang.wasm
#
# Every variant is (a) measured raw + brotli, (b) written under
# m1/evidence/sweep/<name>/ so acceptance can be pointed at it later.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EMSDK="${EMSDK:-$ROOT/toolchain/emsdk}"
WASM_OPT="$EMSDK/upstream/bin/wasm-opt"
NAME="${1:?usage: exp-link-sweep.sh <name> <input.wasm>}"
IN="${2:?usage: exp-link-sweep.sh <name> <input.wasm>}"

OUT="$ROOT/m1/evidence/sweep/$NAME"
mkdir -p "$OUT"

# Feature flags: match the ones the baseline clang.wasm was emitted with
# (threads/bulk-memory/exceptions/mutable-globals/sign-ext/nontrapping).
# --enable-bulk-memory-opt is a Binaryen *optimization* (memory.copy) and is
# deliberately NOT set on the validate-only path, only offered as a variant.
FEATURES=(
  --enable-threads
  --enable-bulk-memory
  --enable-exception-handling
  --enable-mutable-globals
  --enable-sign-ext
  --enable-nontrapping-float-to-int
)

measure() {                       # measure <label> <file>
  local label="$1" f="$2"
  [ -f "$f" ] || { echo "SKIP  $label (missing)"; return; }
  local raw br
  raw=$(stat -c%s "$f")
  br=$(python3 -c "
import brotli,sys
sys.stdout.write(str(len(brotli.compress(open(sys.argv[1],'rb').read(), quality=11))))
" "$f" 2>/dev/null || echo 0)
  printf 'ARTIFACT %s_raw %s\n' "$label" "$raw"
  printf 'ARTIFACT %s_brotli %s\n' "$label" "$br"
  printf '  %-34s raw=%12s  brotli=%10s\n' "$label" "$raw" "$br"
}

echo "== link-time sweep on $IN (name=$NAME) =="
measure "${NAME}_asbuilt" "$IN"

run() {                           # run <label> <wasm-opt args...>
  local label="$1"; shift
  local f="$OUT/$label.wasm"
  local t0=$SECONDS
  if "$WASM_OPT" "$@" "$IN" -o "$f" > "$OUT/$label.log" 2>&1; then
    printf '  [%3ds] %s\n' "$((SECONDS - t0))" "$label"
    measure "${NAME}_$label" "$f"
  else
    echo "  FAILED $label (see $OUT/$label.log)"
    tail -3 "$OUT/$label.log" | sed 's/^/    /'
  fi
}

run "oz"                 "${FEATURES[@]}" -Oz
run "oz_converge"        "${FEATURES[@]}" -Oz --converge
run "oz_flatten"         "${FEATURES[@]}" -Oz --flatten
run "oz_bulkopt"         "${FEATURES[@]}" --enable-bulk-memory-opt -Oz
run "o4"                 "${FEATURES[@]}" -O4
run "o3_optlevel3"       "${FEATURES[@]}" -O3 -ol 3 -s 3
run "oz_optlevel3"       "${FEATURES[@]}" -Oz -ol 3 -s 3
run "oz_closedworld"     "${FEATURES[@]}" --closed-world -Oz

echo
echo "== sweep done; artifacts under $OUT =="
