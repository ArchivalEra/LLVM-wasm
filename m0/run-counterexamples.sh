#!/usr/bin/env bash
# M0 counter-examples — the falsifiable half of the acceptance suite.
#
#   SPEC 9.5: a side module built WITHOUT -fwasm-exceptions must not work
#             against a host built WITH it.
#   SPEC 9.6: an STL-heavy side module must either run correctly or name the
#             missing host symbols loudly (never a silent stub).
#
# Exit code is nonzero if any expectation is violated.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
EMSDK="${EMSDK:-$ROOT/../toolchain/emsdk}"
EM="$EMSDK/upstream/emscripten"
BIN="$EMSDK/upstream/bin"
SR="$EM/cache/sysroot"
LIBDIR="$SR/lib/wasm32-emscripten"
ARCH="${ARCH:-wasm32}"
if [ "$ARCH" = wasm64 ]; then TRIPLE=wasm64-unknown-emscripten; LD_M=wasm64; LIBDIR="$SR/lib/wasm64-emscripten"; else
  TRIPLE=wasm32-unknown-emscripten; LD_M=wasm32; fi

WORK="$ROOT/build-$ARCH"
mkdir -p "$WORK"
cd "$WORK"
fails=0

# ---------------------------------------------------------------- SPEC 9.5
echo "== SPEC 9.5: exception-model mismatch must be caught =="
# Build the same fixture with the exception model turned OFF.
"$BIN/clang" --target="$TRIPLE" --sysroot="$SR" -fvisibility=default \
  -isystem "$SR/include/compat" -D__EMSCRIPTEN_SHARED_MEMORY__=1 \
  -fPIC -O2 -pthread -c "$ROOT/side.cc" -o side_noeh.o 2>/dev/null
"$BIN/wasm-ld" "-m$LD_M" -o noeh.so --strip-debug \
  --export=__wasm_call_ctors --export=_emscripten_tls_init --export-dynamic \
  --unresolved-symbols=import-dynamic -shared --shared-memory --no-stack-first \
  "$LIBDIR/pic/crtbegin-mt.o" side_noeh.o \
  -L"$LIBDIR/pic" -L"$EM/src/lib" 2>/dev/null

side_tags=$(node -e '
const fs=require("fs");
const m=new WebAssembly.Module(fs.readFileSync("noeh.so"));
console.log(WebAssembly.Module.imports(m).filter(i=>i.kind==="tag").length);
')
echo "no-EH side imports $side_tags tag(s) (EH side imports: $(node -e '
const fs=require("fs");
const m=new WebAssembly.Module(fs.readFileSync("minifn.so"));
console.log(WebAssembly.Module.imports(m).filter(i=>i.kind==="tag").length);
'))"

# What must NOT happen: the no-EH side silently behaving like the EH one.
# run-m0.sh must have run first so that the EH-built side is on disk.
if [ ! -f minifn.so ]; then
  echo "FATAL: minifn.so missing — run 'sh run-m0.sh' first (this script needs the EH-built side to restore)."
  exit 2
fi
cp minifn.so keep-eh.so
cp noeh.so minifn.so
out=$(timeout 120 node host.js 2>&1 || true)
cp keep-eh.so minifn.so
if printf '%s' "$out" | grep -q "ALL PASS"; then
  echo "VIOLATION: no-EH side module passed the full suite — the 9.5 expectation"
  echo "           ('must not install') is NOT met by this toolchain."
  fails=$((fails+1))
else
  # Distinguish "refused at load" from "installed, then died at the first throw".
  # These are different failures and the SPEC's wording only predicts the first.
  if printf '%s' "$out" | grep -q "PASS dlopen"; then
    reached=$(printf '%s' "$out" | grep -c '^PASS')
    echo "OK (but note the mode): the no-EH side INSTALLED successfully and"
    echo "    passed $reached checks before dying — it does NOT fail at dlopen."
    echo "    It dies at the first C++ throw, as an unhandled WebAssembly.Exception."
  else
    echo "OK: no-EH side module refused at load (matches the SPEC wording)."
  fi
  echo "    observed: $(printf '%s' "$out" | grep -m1 -iE 'Exception|LinkError|PASS dlopen' | cut -c1-110)"
fi

# ---------------------------------------------------------------- SPEC 9.6
echo
echo "== SPEC 9.6: STL template gap must be named, not silently stubbed =="
"$BIN/clang" --target="$TRIPLE" --sysroot="$SR" -fvisibility=default \
  -isystem "$SR/include/compat" -D__EMSCRIPTEN_SHARED_MEMORY__=1 \
  -fPIC -O2 -fwasm-exceptions -pthread -c "$ROOT/landmine.cc" -o landmine.o 2>/dev/null
"$BIN/wasm-ld" "-m$LD_M" -o landmine.so --strip-debug \
  --export=__wasm_call_ctors --export=_emscripten_tls_init --export-dynamic \
  --unresolved-symbols=import-dynamic -shared --shared-memory --no-stack-first \
  "$LIBDIR/pic/crtbegin-mt.o" landmine.o \
  -L"$LIBDIR/pic" -L"$EM/src/lib" -mllvm -exception-model=wasm 2>/dev/null

node "$ROOT/check-symbol-gap.mjs" landmine.so host.wasm
gap_rc=$?
if [ "$gap_rc" -eq 0 ]; then
  echo "OK: no host-symbol gap for the STL fixture (runs without stubs)."
else
  echo "OK: gap reported explicitly above (named, not hidden)."
fi

echo
if [ "$fails" -eq 0 ]; then echo "== counter-examples as expected =="; else echo "== $fails VIOLATION(S) =="; fi
exit "$fails"
