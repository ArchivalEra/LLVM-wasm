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

case "$NAME" in
  # 仅保留 WebAssembly 后端 + -Os（基线是 -O3）
  anchor)
    run clang MinSizeRel "-Os -fwasm-exceptions" ;;

  # 无 EH / 无 RTTI：C++ 异常与 typeinfo 全关（LLVM 官方支持这两个开关）。
  # 目的：量化「异常表 + landing pad + typeinfo」在 71 MB 里占多少。
  lean)
    run clang MinSizeRel \
      "-Os -fno-exceptions -fno-rtti -fno-unwind-tables -fno-asynchronous-unwind-tables -DLLVM_ENABLE_EH=OFF -DLLVM_ENABLE_RTTI=OFF" \
      -DLLVM_ENABLE_EH=OFF -DLLVM_ENABLE_RTTI=OFF ;;

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
