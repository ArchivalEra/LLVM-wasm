#!/usr/bin/env bash
# 把 COS-1（只含 wasm 驱动的 lld）挂进 LLVM 源码树。
#
# 幂等：可重复执行；`--revert` 撤销。改动只有两处，都是**追加**：
#   1. lld/CMakeLists.txt 末尾 include 一个 fragment（新增 lld-wasm-only 目标）
#   2. 可选：--drop-other-drivers 时把 COFF/ELF/MachO/MinGW 四个 add_subdirectory 注释掉，
#      让那四套实现根本不参与编译（否则它们仍会被别的目标编译，只是不被链接）。
#
# 用法:
#   sh m1/patch-lld-wasm-only.sh            # 只加目标（复用已有 build 目录最快）
#   sh m1/patch-lld-wasm-only.sh --revert
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${LLVM_SRC:-$ROOT/toolchain/llvm-project}"
CM="$SRC/lld/CMakeLists.txt"
FRAG="$ROOT/m1/lld-wasm-only/tools-lld-wasm-only.cmake"
MARK="# ==== M1 COS-1: lld-wasm-only (追加目标) ===="

[ -f "$CM" ] || { echo "FATAL: $CM 不存在"; exit 2; }

if [ "${1:-}" = "--revert" ]; then
  python3 - "$CM" "$MARK" <<'PY'
import sys
cm, mark = sys.argv[1], sys.argv[2]
s = open(cm).read()
if mark in s:
    s = s[:s.index(mark)].rstrip() + "\n"
    open(cm, "w").write(s)
    print("reverted", cm)
else:
    print("nothing to revert")
PY
  exit 0
fi

python3 - "$CM" "$FRAG" "$MARK" <<'PY'
import os, sys
cm, frag, mark = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(cm).read()
if mark in s:
    print("already patched")
    sys.exit(0)
s = s.rstrip() + f"""

{mark}
# 追加一个只含 wasm 驱动的 lld，用于量化「多平台驱动」「四套链接器实现」的体积代价。
include("{frag}")
"""
open(cm, "w").write(s)
print("patched", cm)
PY

echo "== 现在可以在已有 build 目录里直接 make 这个目标 =="
echo "   cd m1/build-lld && ninja lld-wasm-only"
