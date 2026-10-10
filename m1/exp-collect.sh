#!/usr/bin/env bash
# 等几个 relink 进程结束后，把定稿产物拷进 evidence/ 并量一遍（q9 快速筛 + q11 定稿）。
# 用法: bash m1/exp-collect.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EV="$ROOT/m1/evidence/relink"
mkdir -p "$EV"

# 1) 等所有 exp-relink 退出（最多 40 分钟）
for i in $(seq 1 240); do
  pgrep -f "exp-relink.py" >/dev/null || break
  sleep 10
done
echo "== relink 进程已退出（等了 ${i}0s）"

# 2) 把锚点产物从会被覆盖的 build 目录里拷出来留档
for spec in "anchor_asbuilt:$ROOT/m1/build-exp-anchor/bin/clang.wasm" \
            "anchor_oz:$EV/anchor_oz/clang.wasm" \
            "lld_oz:$EV/lld_oz/lld.wasm" \
            "lld_oz_lto:$EV/lld_oz_lto/lld.wasm"; do
  name="${spec%%:*}"; src="${spec#*:}"
  dst="$EV/$name.wasm"
  if [ -f "$src" ] && [ ! -f "$dst" ]; then
    cp "$src" "$dst" && echo "  留档 $name -> $dst ($(stat -c%s "$dst") B)"
  fi
done

# 3) 量 q9（快）——用于表格里所有行的横向比较
python3 - "$ROOT" <<'PY'
import brotli, gzip, os, sys, time
root = sys.argv[1]
targets = [
  ("baseline_clang", "m1/build-clang/bin/clang.wasm"),
  ("baseline_lld", "m1/build-lld/bin/lld.wasm"),
  ("anchor_clang", "m1/evidence/relink/anchor_asbuilt.wasm"),
  ("anchor_oz_clang", "m1/evidence/relink/anchor_oz.wasm"),
  ("wasmonly_lld", "m1/build-lld/bin/lld-wasm-only.wasm"),
  ("lld_oz", "m1/evidence/relink/lld_oz.wasm"),
  ("lld_oz_lto", "m1/evidence/relink/lld_oz_lto.wasm"),
]
for label, rel in targets:
    p = os.path.join(root, rel)
    if not os.path.exists(p):
        print(f"  SKIP {label} (missing {rel})"); continue
    d = open(p, "rb").read()
    t = time.time(); br9 = len(brotli.compress(d, quality=9))
    print(f"ARTIFACT {label}_raw {len(d)}")
    print(f"ARTIFACT {label}_gzip {len(gzip.compress(d,9))}")
    print(f"ARTIFACT {label}_brotli9 {br9}")
    print(f"  {label:18s} raw={len(d):>12,} gzip={len(gzip.compress(d,9)):>12,} brotli9={br9:>11,} ({time.time()-t:.0f}s)")
PY
echo "== collect done"
