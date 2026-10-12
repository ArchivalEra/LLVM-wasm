#!/usr/bin/env bash
# Build the emscripten *host* main module so a browser page can dlopen a side
# module the toolchain produced. This closes the loop SPEC §9.2–9.4 describe
# ("dlopen 成功 / 调用返回正确 / 异常跨边界"), which until now was only verified
# under node (m0/run-m0.sh) — the browser half stopped at "produces a valid
# side module".
#
# Differences from the M0 host build:
#   · -sMODULARIZE so the page can instantiate it and drive it (the M0 glue
#     runs main() at load and exports nothing);
#   · export FS and callMain, so the page can drop the compiled .so into the
#     module's filesystem and then run the host's own checks;
#   · the same flags M0 used, because the side module ABI is defined by them
#     (shared memory + wasm EH must match, per SPEC §4.5).
#
# Usage: bash browser/build-host.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EMSDK="${EMSDK:-$ROOT/toolchain/emsdk}"
EM="$EMSDK/upstream/emscripten"
OUT="$ROOT/browser/host"

mkdir -p "$OUT"
echo "== building the browser host module =="
"$EM/em++" -O2 \
  -fwasm-exceptions -pthread -sSHARED_MEMORY=1 \
  -sMAIN_MODULE=1 -sALLOW_MEMORY_GROWTH=1 \
  -sMODULARIZE=1 -sEXPORT_NAME=createHost \
  -sEXPORTED_RUNTIME_METHODS=FS,callMain \
  -sENVIRONMENT=web,worker \
  -o "$OUT/host.js" "$ROOT/m0/host.cc"

ls -la "$OUT/host.js" "$OUT/host.wasm"
printf 'ARTIFACT browser_host_wasm %s\n' "$(stat -c%s "$OUT/host.wasm")"
