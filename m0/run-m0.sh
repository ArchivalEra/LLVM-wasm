#!/usr/bin/env bash
# M0 runner — reproduces SPEC §4 end-to-end and the §9 acceptance suite.
#
# Hand-builds a side module with the raw clang frontend + wasm-ld (no emcc for
# the side module), builds an emscripten main module as the host, then dlopens
# the side module and exercises: symbol resolution, host callbacks, exception
# round-trips across the dlopen boundary, and STL template instantiations.
#
# Usage:  sh run-m0.sh          # wasm32
#         ARCH=wasm64 sh run-m0.sh
#
# Every printed PASS/FAIL line is the acceptance evidence. Exit code is nonzero
# if any check fails.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
EMSDK="${EMSDK:-$ROOT/../toolchain/emsdk}"
EM="$EMSDK/upstream/emscripten"
BIN="$EMSDK/upstream/bin"
SR="$EM/cache/sysroot"

ARCH="${ARCH:-wasm32}"
case "$ARCH" in
  wasm32) TRIPLE=wasm32-unknown-emscripten; LD_M=wasm32; LIBDIR="$SR/lib/wasm32-emscripten"; HOST_ARCH_FLAGS="" ;;
  wasm64) TRIPLE=wasm64-unknown-emscripten; LD_M=wasm64; LIBDIR="$SR/lib/wasm64-emscripten"; HOST_ARCH_FLAGS="-m64" ;;
  *) echo "unknown ARCH=$ARCH (want wasm32|wasm64)"; exit 2 ;;
esac

WORK="$ROOT/build-$ARCH"
rm -rf "$WORK"; mkdir -p "$WORK"
cd "$WORK"

echo "== M0 ($ARCH) =="
echo "-- toolchain"
"$BIN/clang" --version | head -1
"$EM/emcc" --version | head -1

# ---------------------------------------------------------------- side module
# SPEC 4.1 compile (verbatim, minus flags that do not exist in LLVM 24).
echo "-- [1] clang frontend (SPEC 4.1)"
"$BIN/clang" --target="$TRIPLE" --sysroot="$SR" -fvisibility=default \
  -isystem "$SR/include/compat" \
  -D__EMSCRIPTEN_SHARED_MEMORY__=1 \
  -fPIC -O2 -fwasm-exceptions -pthread \
  -c "$ROOT/side.cc" -o side.o

# SPEC 4.2 link. Two corrections against LLVM 24 (both measured, see RESULTS.md):
#   - `-mllvm -wasm-enable-eh` no longer exists (-wasm-enable-sjlj replaced it);
#     `-mllvm -exception-model=wasm` is what remains.
#   - `--experimental-pic` is accepted but ignored ("Legacy ... ignored").
echo "-- [2] wasm-ld (SPEC 4.2, LLVM-24 corrected)"
"$BIN/wasm-ld" "-m$LD_M" -o minifn.so --strip-debug \
  --export=__wasm_call_ctors \
  --export=_emscripten_tls_init \
  --export-dynamic \
  --unresolved-symbols=import-dynamic \
  -shared --shared-memory --no-stack-first \
  "$LIBDIR/pic/crtbegin-mt.o" side.o \
  -L"$LIBDIR/pic" -L"$EM/src/lib" \
  -mllvm -exception-model=wasm

# ------------------------------------------------------------------- the host
# MAIN_MODULE=1 (not 2): the DCE'd MAIN_MODULE=2 host exports no exception tag,
# so the side module cannot even be instantiated. See RESULTS.md finding F-3.
echo "-- [3] emscripten host main module (MAIN_MODULE=1)"
"$EM/em++" -O2 $HOST_ARCH_FLAGS -fwasm-exceptions -pthread -sSHARED_MEMORY=1 \
  -sMAIN_MODULE=1 -sALLOW_MEMORY_GROWTH=1 \
  -o host.js "$ROOT/host.cc"

# ------------------------------------------------------------------- run it
echo "-- [4] dlopen + call the side module"
node host.js

# --------------------------------------------------------- symbol gap report
echo "-- [5] symbol gap (SPEC 5.4)"
node "$ROOT/check-symbol-gap.mjs" minifn.so host.wasm

echo "== M0 ($ARCH) done =="
