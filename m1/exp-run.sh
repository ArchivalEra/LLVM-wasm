#!/usr/bin/env bash
# M1 实验 runner：按名字跑一组配置，每个配置记 ARTIFACT 行到 m1/evidence/opt-<名字>.log。
#
# 为什么用脚本而不是一串手敲命令：每个实验的完整 flag 必须和数字一起留档
# （OPT-RESULTS.md 的表就是这么来的）。
#
# 用法: bash m1/exp-run.sh <配置名>
#   lean | lean_lto | opts | anchor | lld_only ...
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="${1:?用法: exp-run.sh <配置名>}"
LOG="$ROOT/m1/evidence/opt-$NAME.log"
mkdir -p "$ROOT/m1/evidence"

run() {                           # run <工具> <build_type> <cxx_flags> [extra cmake...]
  local tools="$1" bt="$2" cxx="$3"; shift 3
  echo "===== config=$NAME tools=$tools build_type=$bt"
  echo "# CXX_FLAGS: $cxx" >&2
  EXP_TOOLS="$tools" EXP_BUILD_TYPE="$bt" EXP_C_FLAGS="$cxx" EXP_CXX_FLAGS="$cxx" \
  EXP_OUT="$ROOT/m1/build-exp-$NAME" \
    bash "$ROOT/m1/exp-build.sh" "$NAME" "$@"
}

# run_lf：同上，但显式给链接期旗标。lean_nosjlj 需要它 —— 默认链接旗标里带的
# `-fwasm-exceptions` 与 `-fno-exceptions` 冲突，会把 emcc 推去选
# libclang_rt.builtins-legacysjlj（该变体没有 emscripten_longjmp），
# 于是链接期缺符号。机制与复核见 m1/OPT-REVIEW.md §1。
run_lf() {                        # run_lf <工具> <build_type> <cxx_flags> <link_flags> [cmake...]
  local tools="$1" bt="$2" cxx="$3" lf="$4"; shift 4
  echo "===== config=$NAME tools=$tools build_type=$bt (custom link flags)"
  echo "# CXX_FLAGS: $cxx" >&2
  echo "# LINK_FLAGS: $lf" >&2
  EXP_TOOLS="$tools" EXP_BUILD_TYPE="$bt" EXP_C_FLAGS="$cxx" EXP_CXX_FLAGS="$cxx" \
  EXP_LINK_FLAGS="$lf" EXP_OUT="$ROOT/m1/build-exp-$NAME" \
    bash "$ROOT/m1/exp-build.sh" "$NAME" "$@"
}

case "$NAME" in
  # 仅保留 WebAssembly 后端 + -Os（基线是 -O3）
  anchor)
    run clang MinSizeRel "-Os -fwasm-exceptions" ;;

  # 无 EH / 无 RTTI：C++ 异常与 typeinfo 全关（LLVM 官方支持这两个开关）。
  # 目的：量化「异常表 + landing pad + typeinfo」在 71 MB 里占多少。
  #
  # ⚠️ 这个配置**失败**，而且失败原因是**我方旗标自相矛盾**，不是"必须改 LLVM 源码"
  #    （上一轮我把根因写错了，复核见 m1/OPT-REVIEW.md §1）：
  #    这里的链接旗标默认带 `-fwasm-exceptions`，与编译期的 `-fno-exceptions`
  #    同时在场 ⇒ emcc 选中 libclang_rt.builtins-legacysjlj（无 emscripten_longjmp）
  #    ⇒ 链接期 undefined symbol。正解见下面的 lean_nosjlj。
  lean)
    run clang MinSizeRel \
      "-Os -fno-exceptions -fno-rtti -fno-unwind-tables -fno-asynchronous-unwind-tables -DLLVM_ENABLE_EH=OFF -DLLVM_ENABLE_RTTI=OFF" \
      -DLLVM_ENABLE_EH=OFF -DLLVM_ENABLE_RTTI=OFF ;;

  # lean 的**修正版**：去掉矛盾的 `-fwasm-exceptions`，且**不要**设 SUPPORT_LONGJMP。
  #
  # ⚠️ 这里有个反直觉的机制，两轮 agent 都猜反过，以实测为准（证据见
  #    m1/evidence/opt-lean_nosjlj.log 与 OPT-RESULTS.md §5.2）：
  #
  #    `-sSUPPORT_LONGJMP=wasm` 配上默认的 `WASM_LEGACY_EXCEPTIONS=true`，
  #    会让 emcc 的 builtins 变体选择走到 `Exceptions.WASM_LEGACY`
  #    （tools/system_libs.py:898 `get_default_variation`）⇒ 链接
  #    `libclang_rt.builtins-legacysjlj`，而该变体**没有** `emscripten_longjmp`
  #    （实测 `llvm-nm --defined-only`：只有 builtins / -mt / -ww 三个变体有）。
  #
  #    在 `-fno-exceptions` 下，`CrashRecoveryContext.cpp` 的 setjmp/longjmp
  #    正好展开成 `emscripten_longjmp` ⇒ 缺符号。
  #
  #    所以正解是**不设** SUPPORT_LONGJMP，让它留在默认的 `Exceptions.EMSCRIPTEN`
  #    ⇒ 选到 `libclang_rt.builtins.a`（有这个符号）。
  #    加 `-sSUPPORT_LONGJMP=wasm` 是把情况弄坏，不是修好。
  #
  # cmake 侧只能给 `-DLLVM_ENABLE_EH=OFF`：RTTI 必须留 ON（HandleLLVMOptions.cmake
  # 有硬判据「EH=ON 时 RTTI 必须 ON」），我们改在编译器层用 `-fno-rtti` 关。
  lean_nosjlj)
    run_lf clang MinSizeRel \
      "-Os -fno-exceptions -fno-rtti -fno-unwind-tables -fno-asynchronous-unwind-tables" \
      "-sWASM=1 -sALLOW_MEMORY_GROWTH=1 -sSTACK_SIZE=5242880 -sEXIT_RUNTIME=0 \
-sINITIAL_MEMORY=268435456 -sFORCE_FILESYSTEM=1 -sMODULARIZE=1 \
-sEXPORT_NAME=createToolChain \
-sEXPORTED_RUNTIME_METHODS=FS,callMain,ccall,cwrap,getValue,setValue" \
      -DLLVM_ENABLE_EH=OFF ;;

  # 只关 RTTI（保留异常）：-fno-rtti 在 LLVM 侧由 LLVM_ENABLE_RTTI 支持，
  # 不触碰 CrashRecoveryContext 的 longjmp 路径，是"能跑"的那一半。
  lean2)
    run clang MinSizeRel \
      "-Os -fno-rtti -fno-unwind-tables -fno-asynchronous-unwind-tables -fwasm-exceptions" \
      -DLLVM_ENABLE_RTTI=ON ;;   # LLVM 强制：EH=ON 时 RTTI 开关必须为 ON（cmake 会直接报错），
                                 # 但我们仍可在编译器层用 -fno-rtti 观察体积差别

  # 无 EH/RTTI + LTO（-flto 编 + 链接期 LTO，跨模块 DCE）
  lean_lto)
    run clang MinSizeRel \
      "-Os -flto -fno-exceptions -fno-rtti -fno-unwind-tables -fno-asynchronous-unwind-tables" \
      -DLLVM_ENABLE_EH=OFF -DLLVM_ENABLE_RTTI=OFF ;;

  # 只调 LLVM 自己的体积旋钮（保留 EH/RTTI，风险最低的"安全优化"组合）
  opts)
    run clang MinSizeRel \
      "-Oz -fwasm-exceptions -mllvm -inline-threshold=5 -mllvm -inlinehint-threshold=5 -mllvm -unroll-threshold=0" ;;

  # lld：只要 wasm 驱动（COS-1）。见 m1/lld-wasm-only/。
  lld_wasm)
    run lld MinSizeRel "-Os -fwasm-exceptions" ;;

  *) echo "unknown config: $NAME"; exit 2 ;;
esac

{
  echo "# config $NAME  ($(date -Is))"
  echo "# build_type/obj dir: $ROOT/m1/build-exp-$NAME"
} >> "$LOG"
