#!/usr/bin/env bash
# wasm64 end-to-end from the RELEASE BUNDLE into a real host (issue #1).
#
# The reported symptom: a wasm64 module built from the release bundle lacked
# _emscripten_tls_init and the host refused it with
# "TypeError: tlsInitFunc is not a function". Two separate gaps produced that:
#   1. the bundle shipped only the wasm32 sysroot while claiming both targets;
#   2. nothing between "compile returned ok" and "the host dlopens it" checked
#      that the TLS entry was present.
#
# This script closes the loop the way a downstream would: take the bundle, add
# the M0 fixture as a driver ({base}/inject), feed the resulting bundle to the
# release toolchain, and dlopen the product in the wasm64 host harness.
#
# ⚠️ Do NOT wrap the driver via `sed` on release/out/driver/toolchain.mjs —
# that file is re-copied by make-release.sh, so mutations vanish (measured: a
# first attempt did exactly this and reported a false failure).
#
# Usage: bash release/check-wasm64-e2e.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/release/out"
HOSTDIR="$ROOT/m0/build-wasm64"

[ -f "$OUT/manifest.json" ] || { echo "FATAL: run release/make-release.sh first"; exit 2; }
[ -f "$HOSTDIR/host.js" ] || { echo "FATAL: run 'bash m0/run-m0.sh' with ARCH=wasm64 first (needs the host harness)"; exit 2; }

echo "== [1] compile the M0 fixture for wasm64, from the bundle =="
node - "$ROOT" <<'JS'
import { readFileSync, writeFileSync } from 'fs';
const [ROOT] = process.argv.slice(2);
const { Toolchain } = await import(`file://${ROOT}/release/out/driver/toolchain.mjs`);
const man = JSON.parse(readFileSync(`${ROOT}/release/out/manifest.json`, 'utf8'));
const tars = Object.fromEntries(
  Object.entries(man.toolchain.sysroots).map(([arch, name]) => [arch, {
    tarPath: `${ROOT}/release/out/${name}`,
    manifestPath: `${ROOT}/release/out/manifest.json`,
  }]));
const tc = new Toolchain({
  clangBin: `${ROOT}/release/out`, clangJs: 'clang.js',
  lldBin: `${ROOT}/release/out`, lldJs: man.toolchain.lld_glue,
  bundle: { tars }, quiet: true,
});
const src = readFileSync(`${ROOT}/m0/side.cc`, 'utf8');
const r = await tc.compile({
  source: src, target: 'wasm64',
  abi: { exceptions: 'wasm-legacy', pthread: true, memory64: true },
});
if (!r.ok) { console.error(`FAIL: wasm64 compile: ${r.error}`); process.exit(1); }
const ex = WebAssembly.Module.exports(new WebAssembly.Module(r.moduleBytes)).map((e) => e.name);
if (!ex.includes('_emscripten_tls_init')) {
  console.error('FAIL: product lacks _emscripten_tls_init — this is issue #1\'s symptom');
  process.exit(1);
}
writeFileSync(`${ROOT}/m0/build-wasm64/minifn.so`, r.moduleBytes);
console.log(`   compiled ${r.moduleBytes.length} B, TLS entry present`);
console.log(`ARTIFACT wasm64_release_e2e_bytes ${r.moduleBytes.length}`);
JS

echo
echo "== [2] dlopen it in the real wasm64 host =="
node "$HOSTDIR/host.js" | tee /tmp/w64e2e.txt
grep -q "ALL PASS" /tmp/w64e2e.txt || { echo "FAIL: host suite did not pass"; exit 1; }
echo
echo "ARTIFACT wasm64_release_e2e_pass $(grep -c '^PASS' /tmp/w64e2e.txt)"
echo "== wasm64 from the release bundle: OK =="
