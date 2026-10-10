#!/usr/bin/env bash
# M1 — build clang (and lld) for the browser, i.e. as wasm runnable inside an
# emscripten runtime. SPEC §10 M1: "先求能跑，不优化体积".
#
# Strategy (SPEC §6 减重方向 + §7.5 薄驱动):
#   · only the WebAssembly target is enabled (no X86/ARM/... backends);
#   · clang only (no full driver extras we do not need) plus lld;
#   · build with emcc so the resulting binary is an emscripten module;
#   · -O1 for the first pass, no LTO, no wasm-opt yet.
#
# Usage:  sh m1/build-clang-wasm.sh [clang|lld|both]
#
# Everything it produces lands under m1/build-<name>/ and is NOT tracked
# (.gitignore); only the ARTIFACT line at the end is the measured record.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EMSDK="${EMSDK:-$ROOT/toolchain/emsdk}"
EM="$EMSDK/upstream/emscripten"
SRC="$ROOT/toolchain/llvm-project"
WHAT="${1:-clang}"

[ -d "$SRC/llvm" ] || { echo "FATAL: LLVM source missing at $SRC (see m1/README.md)"; exit 2; }
[ -x "$EM/emcc" ] || { echo "FATAL: emcc missing at $EM"; exit 2; }

export PATH="$EM:$EMSDK/upstream/bin:$PATH"
# emscripten wants a writable cache; keep it inside toolchain/ (untracked).
export EM_CACHE="${EM_CACHE:-$EMSDK/upstream/emscripten/cache}"

# ---------------------------------------------------------------- common flags
# Emscripten-side: a single-file build so the module is easy to load; exceptions
# on (the compiler itself uses them heavily).
# ⚠️ -s 旗标只对链接期有效。放进编译期会被 em++ 忽略并打
#    "linker setting ignored during compilation"（实测踩到：整个
#    FORCE_FILESYSTEM/NODERAWFS 都没生效 ⇒ 编出来的 clang 看不见文件系统，
#    连 `clang -c t.c` 都报 "no such file or directory"）。
COMPILE_FLAGS=(
  -fwasm-exceptions
)
LINK_FLAGS=(
  -sWASM=1
  -sALLOW_MEMORY_GROWTH=1
  -sSTACK_SIZE=5242880
  -sEXIT_RUNTIME=0
  -sINITIAL_MEMORY=268435456
  -sFORCE_FILESYSTEM=1
  -sEXCEPTION_STACK_TRACES=0
  # MODULARIZE: without it the glue runs main() at load and exports nothing,
  # so a host cannot call the compiler in-process (the whole point per §7.1).
  # Measured: the non-modular build has zero `module.exports`.
  -sMODULARIZE=1
  -sEXPORT_NAME=createToolChain
  -sEXPORTED_RUNTIME_METHODS=FS,callMain,ccall,cwrap,getValue,setValue
  -fwasm-exceptions
)

build() {                       # build <clang|lld> <outdir> <extra cmake args...>
  local name="$1"; shift
  local out="$1"; shift
  echo "== M1: building $name -> $out =="
  rm -rf "$out"; mkdir -p "$out"; cd "$out"

  emcmake cmake -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DLLVM_ENABLE_PROJECTS="clang;lld" \
    -DLLVM_TARGETS_TO_BUILD=WebAssembly \
    -DLLVM_TARGET_ARCH=wasm32 \
    -DLLVM_DEFAULT_TARGET_TRIPLE=wasm32-unknown-emscripten \
    -DLLVM_ENABLE_THREADS=OFF \
    -DLLVM_ENABLE_EH=ON \
    -DLLVM_ENABLE_RTTI=ON \
    -DLLVM_ENABLE_ASSERTIONS=OFF \
    -DLLVM_ENABLE_ZLIB=OFF \
    -DLLVM_ENABLE_ZSTD=OFF \
    -DLLVM_ENABLE_LIBXML2=OFF \
    -DLLVM_ENABLE_TERMINFO=OFF \
    -DLLVM_ENABLE_LIBEDIT=OFF \
    -DLLVM_INCLUDE_TESTS=OFF \
    -DLLVM_INCLUDE_BENCHMARKS=OFF \
    -DLLVM_INCLUDE_EXAMPLES=OFF \
    -DLLVM_INCLUDE_DOCS=OFF \
    -DLLVM_BUILD_TOOLS=ON \
    -DLLVM_BUILD_UTILS=OFF \
    -DCLANG_ENABLE_STATIC_ANALYZER=OFF \
    -DCLANG_ENABLE_ARCMT=OFF \
    -DCLANG_ENABLE_OBJC_ARC=OFF \
    -DCLANG_ENABLE_FORMAT=OFF \
    -DCLANG_ENABLE_BOOTSTRAP=OFF \
    -DLIBCLANG_BUILD_STATIC=ON \
    -DCMAKE_C_FLAGS="-O1" \
    -DCMAKE_CXX_FLAGS="-O1 ${COMPILE_FLAGS[*]}" \
    -DCMAKE_EXE_LINKER_FLAGS="${LINK_FLAGS[*]}" \
    -DCMAKE_SHARED_LINKER_FLAGS="${LINK_FLAGS[*]}" \
    "$@" \
    "$SRC/llvm" > cmake.log 2>&1 || { echo "FATAL: cmake configure failed"; tail -30 cmake.log; return 2; }
  echo "   configure OK"

  # target names under emscripten are the .js artifacts, not the tool names
  local target="clang"
  [ "$name" = "lld" ] && target="lld"
  ninja -j"$(nproc)" "$target" > build.log 2>&1 || {
    echo "FATAL: ninja failed"; tail -40 build.log; return 2; }
  echo "   build OK"

  # under emscripten the artifact is <tool>.js (a symlink to <tool>.js-N)
  local bin="bin/$target.js"
  [ -e "$bin" ] || { echo "FATAL: expected $out/$bin, not found"; ls bin/ 2>/dev/null | head; return 2; }
  ls -la "$bin" "bin/$target.wasm" 2>/dev/null
}

case "$WHAT" in
  clang) build clang "$ROOT/m1/build-clang" ;;
  lld)   build lld   "$ROOT/m1/build-lld" ;;
  both)  build clang "$ROOT/m1/build-clang"; build lld "$ROOT/m1/build-lld" ;;
  *)     echo "usage: $0 [clang|lld|both]"; exit 2 ;;
esac

# ---------------------------------------------------- machine-readable summary
# One ARTIFACT line per measured value; facts.py greps these (single producer).
for tool in clang lld; do
  js="$ROOT/m1/build-$tool/bin/$tool.js"
  wa="$ROOT/m1/build-$tool/bin/$tool.wasm"
  [ -e "$js" ] || continue
  printf 'ARTIFACT %s_js %s\n'        "$tool" "$(stat -Lc%s "$js")"
  if [ -f "$wa" ]; then
    printf 'ARTIFACT %s_wasm %s\n'      "$tool" "$(stat -c%s "$wa")"
    printf 'ARTIFACT %s_wasm_gzip %s\n' "$tool" "$(gzip -9 -c "$wa" | wc -c)"
    # brotli: no CLI in this environment; python's module is the same encoder.
    br=$(python3 -c "
import brotli,sys
sys.stdout.write(str(len(brotli.compress(open(sys.argv[1],'rb').read(), quality=11))))
" "$wa" 2>/dev/null) && printf 'ARTIFACT %s_wasm_brotli %s\n' "$tool" "$br"
  fi
done
