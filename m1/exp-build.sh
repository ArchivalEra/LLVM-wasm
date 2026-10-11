#!/usr/bin/env bash
# M1 体积实验：参数化的构建脚本（主脚本 m1/build-clang-wasm.sh 保持不动，基线可复现）。
#
# 关键点（读这个比读 flag 列表重要）：
#   1. 主脚本写的是 `-O1`，但 CMAKE_BUILD_TYPE=Release 会在后面追加 `-O3 -DNDEBUG`，
#      所以**基线实际是 -O3 编译**，不是 -O1（见 m1/OPT-RESULTS.md §1）。实验里
#      用 CMAKE_BUILD_TYPE 控制优化档，避免这个隐藏覆盖。
#   2. ccache 走 EM_COMPILER_WRAPPER，跨配置复用 LLVM 的 2811 个目标文件：
#      只有真正因配置变化而不同的编译会 miss。用 `ccache -s` 看命中率。
#
# 用法:
#   sh m1/exp-build.sh <配置名> [cmake 额外参数...]
# 环境变量:
#   EXP_TOOLS=clang|lld|both   （默认 both）
#   EXP_JOBS=N                 （默认 nproc）
#   EXP_BUILD_TYPE=MinSizeRel|Release|RelWithDebInfo   （默认 MinSizeRel）
#   EXP_C_FLAGS / EXP_CXX_FLAGS / EXP_LINK_FLAGS        （覆盖默认）
#   EXP_OUT=dir                （默认 m1/build-exp-<配置名>）
#   EXP_NO_CCACHE=1            （关掉 ccache，用于对照）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EMSDK="${EMSDK:-$ROOT/toolchain/emsdk}"
EM="$EMSDK/upstream/emscripten"
SRC="$ROOT/toolchain/llvm-project"

NAME="${1:?用法: exp-build.sh <配置名> [cmake 参数...]}"; shift || true
TOOLS="${EXP_TOOLS:-both}"
JOBS="${EXP_JOBS:-$(nproc)}"
BUILD_TYPE="${EXP_BUILD_TYPE:-MinSizeRel}"
OUT="${EXP_OUT:-$ROOT/m1/build-exp-$NAME}"

[ -d "$SRC/llvm" ] || { echo "FATAL: LLVM 源码不在 $SRC"; exit 2; }
[ -x "$EM/emcc" ] || { echo "FATAL: emcc 不在 $EM"; exit 2; }

export PATH="$EM:$EMSDK/upstream/bin:$PATH"
export EM_CACHE="${EM_CACHE:-$EM/../emscripten/cache}"

# ccache 配置（本仓工具链目录，不入库）。
#
# ⚠️ 实测：emsdk 6.0.12 的 `EM_COMPILER_WRAPPER` 是**死的** —— emcc.py 里有
#    `if config.COMPILER_WRAPPER:` 的代码路径，但没有任何地方从环境变量赋值给
#    `config.COMPILER_WRAPPER`（它只认 ~/.emscripten 配置），所以设了也没用，
#    ccache 命中数恒为 0。能用的接法是 CMake 的 compiler launcher：
#    `-DCMAKE_CXX_COMPILER_LAUNCHER=ccache`（已验证：第二次编译 Hits=1）。
export CCACHE_CONFIGPATH="${CCACHE_CONFIGPATH:-$ROOT/toolchain/ccache/ccache.conf}"
export CCACHE_DIR="${CCACHE_DIR:-$ROOT/toolchain/ccache}"
LAUNCHER=()
if [ "${EXP_NO_CCACHE:-0}" != "1" ]; then
  LAUNCHER=(-DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache)
  command -v ccache >/dev/null || { echo "FATAL: ccache 不在 PATH"; exit 2; }
  echo "== ccache: $(ccache --version | head -1) dir=$CCACHE_DIR (via CMAKE_*_COMPILER_LAUNCHER)"
fi
export EMCC_SKIP_SANITY_CHECK=1

if [ -n "${EXP_C_FLAGS:-}" ];   then C_FLAGS="$EXP_C_FLAGS";   else C_FLAGS="-Os"; fi
if [ -n "${EXP_CXX_FLAGS:-}" ]; then CXX_FLAGS="$EXP_CXX_FLAGS"; else CXX_FLAGS="-Os -fwasm-exceptions"; fi
if [ -n "${EXP_LINK_FLAGS:-}" ]; then LINK_FLAGS="$EXP_LINK_FLAGS"; else
LINK_FLAGS="-sWASM=1 -sALLOW_MEMORY_GROWTH=1 -sSTACK_SIZE=5242880 -sEXIT_RUNTIME=0 \
-sINITIAL_MEMORY=268435456 -sFORCE_FILESYSTEM=1 -sEXCEPTION_STACK_TRACES=0 \
-sMODULARIZE=1 -sEXPORT_NAME=createToolChain \
-sEXPORTED_RUNTIME_METHODS=FS,callMain,ccall,cwrap,getValue,setValue -fwasm-exceptions"
fi

# 与主脚本一致的 LLVM 配置，只把优化档和可裁项参数化。
COMMON=(
  -G Ninja
  -DCMAKE_BUILD_TYPE="$BUILD_TYPE"
  -DLLVM_ENABLE_PROJECTS="clang;lld"
  -DLLVM_TARGETS_TO_BUILD=WebAssembly
  -DLLVM_TARGET_ARCH=wasm32
  -DLLVM_DEFAULT_TARGET_TRIPLE=wasm32-unknown-emscripten
  -DLLVM_ENABLE_THREADS=OFF
  -DLLVM_ENABLE_EH=ON
  -DLLVM_ENABLE_RTTI=ON
  -DLLVM_ENABLE_ASSERTIONS=OFF
  -DLLVM_ENABLE_ZLIB=OFF
  -DLLVM_ENABLE_ZSTD=OFF
  -DLLVM_ENABLE_LIBXML2=OFF
  -DLLVM_ENABLE_TERMINFO=OFF
  -DLLVM_ENABLE_LIBEDIT=OFF
  -DLLVM_INCLUDE_TESTS=OFF
  -DLLVM_INCLUDE_BENCHMARKS=OFF
  -DLLVM_INCLUDE_EXAMPLES=OFF
  -DLLVM_INCLUDE_DOCS=OFF
  -DLLVM_BUILD_TOOLS=ON
  -DLLVM_BUILD_UTILS=OFF
  -DCLANG_ENABLE_STATIC_ANALYZER=OFF
  -DCLANG_ENABLE_ARCMT=OFF
  -DCLANG_ENABLE_OBJC_ARC=OFF
  -DCLANG_ENABLE_FORMAT=OFF
  -DCLANG_ENABLE_BOOTSTRAP=OFF
  -DLIBCLANG_BUILD_STATIC=ON
  -DCMAKE_C_FLAGS="$C_FLAGS"
  -DCMAKE_CXX_FLAGS="$CXX_FLAGS"
  -DCMAKE_EXE_LINKER_FLAGS="$LINK_FLAGS"
  -DCMAKE_SHARED_LINKER_FLAGS="$LINK_FLAGS"
)

build_one() {                     # build_one <clang|lld>
  local name="$1"
  echo "== exp[$NAME]: cmake configure ($name, build_type=$BUILD_TYPE) =="
  mkdir -p "$OUT"; cd "$OUT"
  emcmake cmake "${COMMON[@]}" "${LAUNCHER[@]}" "$@" "$SRC/llvm" > "cmake-$name.log" 2>&1 \
    || { echo "FATAL: configure 失败"; tail -25 "cmake-$name.log"; return 2; }
  echo "   configure OK; ninja -j$JOBS $name"
  local t0=$SECONDS
  ninja -j"$JOBS" "$name" > "build-$name.log" 2>&1 \
    || { echo "FATAL: ninja 失败"; tail -40 "build-$name.log"; return 2; }
  echo "   build OK in $((SECONDS - t0))s"
}

case "$TOOLS" in
  clang) build_one clang "$@" ;;
  lld)   build_one lld   "$@" ;;
  both)  build_one clang "$@"; build_one lld "$@" ;;
  *) echo "bad EXP_TOOLS=$TOOLS"; exit 2 ;;
esac

# ---------------------------------------------------------- 机器可读产物行
# 与主脚本同一形状：facts.py / 结果表只需要 grep ARTIFACT。
#
# ⚠️ `gzip -9 -c <file>` 会把**文件名**写进 gzip 头（实测：同一个 48,069,274 B 的
#    wasm，在 A 路径量得 17,317,088、换到 B 路径量得 17,317,087 —— 差的就是名字长度）。
#    那意味着「同一个字节流」的 gzip 值会随**量它的路径**漂移，复跑必然对不上。
#    必须 `-n`（--no-name）去掉文件名与时间戳，量出来的才是内容本身的属性。
measure() {                       # measure <key> <wasm>
  local key="$1" wa="$2"
  [ -f "$wa" ] || return 0
  printf 'ARTIFACT %s_wasm %s\n' "$key" "$(stat -c%s "$wa")"
  printf 'ARTIFACT %s_wasm_gzip %s\n' "$key" "$(gzip -9 -nc "$wa" | wc -c)"
  local br
  br=$(python3 -c "
import brotli,sys
sys.stdout.write(str(len(brotli.compress(open(sys.argv[1],'rb').read(), quality=11))))
" "$wa" 2>/dev/null) && printf 'ARTIFACT %s_wasm_brotli %s\n' "$key" "$br"
}

echo "-- artifacts ($OUT)"
for tool in clang lld; do
  js="$OUT/bin/$tool.js"; wa="$OUT/bin/$tool.wasm"
  [ -e "$js" ] || continue
  printf 'ARTIFACT %s_%s_js %s\n' "$NAME" "$tool" "$(stat -Lc%s "$js")"
  measure "${NAME}_$tool" "$wa"
done
if [ "${EXP_NO_CCACHE:-0}" != "1" ]; then
  echo "-- ccache stats"; ccache -s | grep -E "Hits|Misses|Cacheable|Local storage|Cache size" | head -8
fi
