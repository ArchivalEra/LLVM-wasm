#!/usr/bin/env bash
# 首拉体积分解（SPEC §6 的预算口径是「brotli ≤ 15 MB（**首拉**）」，
# 而 OPT-RESULTS.md 前几版一直在比**总量** —— 这两个口径结论相反，所以单独立一个测量件）。
#
# 为什么要一个脚本而不是文档里写一行加法：
#   「首拉」是一个**派生量**（clang.wasm + clang.js 胶水 + sysroot tar），
#   派生量手算就没人能复跑。这里把它变成一次可复跑的量测，打 ARTIFACT 行。
#
# 口径说明（这一条决定结论，写清楚）：
#   · 首拉 = 第一次**能编译**所需的字节：clang.wasm + clang.js + sysroot 头文件 tar。
#   · lld.wasm **不计入首拉**：驱动里 lld 是懒加载的（driver/toolchain.mjs 的
#     `async lld()` 带 `if (this._lld) return this._lld`，只有链接时才 `require`），
#     SPEC §6 也明说「支持分片懒加载」。它在**首次链接**时才拉。
#   · 但「总量」= 首拉 + lld.wasm，也一并打出来 —— 两个口径都要有数字，
#     因为 SPEC 自己的表把三个资产**求和**成 13.07 MB 叫「合计」，
#     那句「≤ 15 MB（首拉）」到底管总量还是管首拉，是**需要委托人裁决**的。
#
# 用法: bash m1/exp-firstload.sh [clang 目录] [lld 目录]
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLANG_DIR="${1:-$ROOT/m1/build-exp-lean_nosjlj/bin}"
LLD_DIR="${2:-$ROOT/m1/build-lld/bin}"
SYSROOT_TAR="${SYSROOT_TAR:-$ROOT/package/out/sysroot-wasm32.tar}"

br() {  # br <file> -> brotli q11 字节（-n 口径：只量内容）
  [ -f "$1" ] || { echo 0; return; }
  python3 -c "
import brotli,sys
sys.stdout.write(str(len(brotli.compress(open(sys.argv[1],'rb').read(), quality=11))))
" "$1" 2>/dev/null || echo 0
}

# clang 的胶水在 emscripten 下叫 clang.js-24（clang.js 是指向它的符号链接）
CLANG_JS="$CLANG_DIR/clang.js-24"
[ -f "$CLANG_JS" ] || CLANG_JS="$CLANG_DIR/clang.js"

C_WASM=$(br "$CLANG_DIR/clang.wasm")
C_JS=$(br "$CLANG_JS")
L_WASM=$(br "$LLD_DIR/lld-wasm-only.wasm")
[ "$L_WASM" = "0" ] && L_WASM=$(br "$LLD_DIR/lld.wasm")
S_TAR=$(br "$SYSROOT_TAR")

printf 'ARTIFACT firstload_clang_wasm_brotli %s\n' "$C_WASM"
printf 'ARTIFACT firstload_clang_js_brotli %s\n'    "$C_JS"
printf 'ARTIFACT firstload_sysroot_tar_brotli %s\n' "$S_TAR"
printf 'ARTIFACT firstload_lld_wasm_brotli %s\n'    "$L_WASM"
printf 'ARTIFACT firstload_brotli %s\n' "$((C_WASM + C_JS + S_TAR))"
printf 'ARTIFACT firstload_plus_lld_brotli %s\n' "$((C_WASM + C_JS + S_TAR + L_WASM))"

echo "-- 首拉分解（brotli q11，-n 口径）"
printf '   clang.wasm            %12s\n' "$C_WASM"
printf '   clang.js 胶水         %12s\n' "$C_JS"
printf '   sysroot-wasm32.tar    %12s\n' "$S_TAR"
printf '   ── 首拉（只编不链）    %12s  = %s MB\n' "$((C_WASM + C_JS + S_TAR))" \
       "$(python3 -c "print(f'{$((C_WASM + C_JS + S_TAR))/1e6:.2f}')")"
printf '   lld.wasm（首次链接再拉）%11s\n' "$L_WASM"
printf '   ── 三资产总量         %12s  = %s MB\n' "$((C_WASM + C_JS + S_TAR + L_WASM))" \
       "$(python3 -c "print(f'{$((C_WASM + C_JS + S_TAR + L_WASM))/1e6:.2f}')")"
echo
BUDGET=${BUDGET:-15000000}
FL=$((C_WASM + C_JS + S_TAR)); TOT=$((FL + L_WASM))
python3 - "$FL" "$TOT" "$BUDGET" <<'PY'
import sys
fl, tot, budget = map(int, sys.argv[1:4])
print(f"   预算 {budget:,} B（15 MB）：")
print(f"     按「首拉」口径：{fl:,} B ⇒ {'PASS ✓ 余量 %d B' % (budget-fl) if fl<=budget else 'FAIL 超 %d B' % (fl-budget)}")
print(f"     按「总量」口径：{tot:,} B ⇒ {'PASS ✓' if tot<=budget else 'FAIL 超 %d B' % (tot-budget)}")
PY
