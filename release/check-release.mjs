// Consume the release bundle the way a downstream would (SPEC §12).
//
// The point is to prove the bundle is self-sufficient: nothing is read from the
// source tree, only from release/out. A downstream pins this repo by commit,
// reads manifest.json, fetches the assets it needs, verifies their sha256, and
// calls compile(). This does exactly that, and the sha256 check is exercised
// against the manifest rather than a hard-coded digest.
//
// Usage: node release/check-release.mjs [--bundle <dir>]
import { readFileSync, existsSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { createHash } from 'crypto';

const ROOT = join(dirname(new URL(import.meta.url).pathname), '..');
const args = process.argv.slice(2);
const bi = args.indexOf('--bundle');
const OUT = bi >= 0 ? args[bi + 1] : join(ROOT, 'release/out');

let fails = 0, passCount = 0;
const check = (what, ok, detail = '') => {
  if (ok) passCount++; else fails++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${what}${detail ? ': ' + detail : ''}`);
};

// ------------------------------------------------------------- the manifest
const manPath = join(OUT, 'manifest.json');
if (!existsSync(manPath)) {
  console.error(`FATAL: no manifest at ${manPath} — run release/make-release.sh`);
  process.exit(2);
}
const man = JSON.parse(readFileSync(manPath, 'utf8'));
console.log(`bundle: ${OUT}`);
console.log(`manifest: ${man.assets.length} assets, generated ${man.generated}`);

// ------------------------------------------------------------------ §2 shape
console.log('\n== SPEC §2: every asset carries name + bytes + sha256 + license ==');
const missing = man.assets.filter((a) => !a.name || !a.bytes || !a.sha256 || !a.license);
check('all assets have the four required fields', missing.length === 0,
      missing.length ? JSON.stringify(missing.map((a) => a.name)) : `${man.assets.length} assets`);

// the license split SPEC §2 insists on
const byName = Object.fromEntries(man.assets.map((a) => [a.name, a]));
// The lld asset names come from the manifest (they differ between the full and
// wasm-only builds); hard-coding them here is what made this check fail on a
// bundle that was in fact correct.
const LLD_WASM_NAME = man.assets.map((a) => a.name).find((n) => /^lld.*\.wasm$/.test(n));
const LLD_GLUE_NAME = man.assets.map((a) => a.name).find((n) => /^lld.*\.js$/.test(n));
check('clang.wasm is NOT AGPL (LLVM terms instead)',
      /LLVM-exception/.test(byName['clang.wasm']?.license || ''),
      byName['clang.wasm']?.license);
check('the lld wasm is NOT AGPL', /LLVM-exception/.test(byName[LLD_WASM_NAME]?.license || ''),
      `${LLD_WASM_NAME}: ${byName[LLD_WASM_NAME]?.license}`);
check('AGPL stays on this repo\'s own files',
      (byName['driver/toolchain.mjs']?.license || '').includes('AGPL'),
      byName['driver/toolchain.mjs']?.license);

// ------------------------------------------------------------------ §8 shape
console.log('\n== SPEC §8: toolchain + host-baseline version strings are recorded ==');
check('toolchain version string present', !!(man.toolchain && man.toolchain.emcc),
      (man.toolchain?.emcc || '').slice(0, 60));
check('host baseline records the four contract axes',
      !!(man.host_baseline && 'exceptions' in man.host_baseline
         && 'pthread' in man.host_baseline && 'memory64' in man.host_baseline
         && 'main_module' in man.host_baseline),
      JSON.stringify({ e: man.host_baseline?.exceptions, p: man.host_baseline?.pthread,
                       m: man.host_baseline?.memory64, mm: man.host_baseline?.main_module }));

// --------------------------------------------------- §9.10: verify, fail closed
console.log('\n== SPEC §9.10: load only what verifies ==');
function verified(name) {
  const a = byName[name];
  if (!a) throw new Error(`manifest has no asset ${name}`);
  const buf = readFileSync(join(OUT, name));
  if (buf.length !== a.bytes) throw new Error(`${name}: bytes ${buf.length} != manifest ${a.bytes}`);
  const h = createHash('sha256').update(buf).digest('hex');
  if (h !== a.sha256) throw new Error(`${name}: sha256 mismatch`);
  return buf;
}
for (const n of ['clang.wasm', LLD_WASM_NAME, 'sysroot-headers.tar']) {
  try { verified(n); check(`${n} verifies against manifest`, true); }
  catch (e) { check(`${n} verifies against manifest`, false, e.message); }
}

// ------------------------------------------------- compile straight from bundle
console.log('\n== consume: compile using only the bundle ==');
const { Toolchain } = await import(`file://${join(OUT, 'driver', 'toolchain.mjs')}`);
const tc = new Toolchain({
  clangBin: OUT, clangJs: 'clang.js',
  lldBin: OUT, lldJs: LLD_GLUE_NAME,
  bundle: { tarPath: join(OUT, 'sysroot-headers.tar'), manifestPath: manPath },
  quiet: true,
});
const SOURCE = `#include <string>
extern "C" __attribute__((visibility("default"))) int minifn(int x) {
  std::string s = "abc";
  return x + (int)s.size();
}
`;
const r = await tc.compile({
  source: SOURCE, target: 'wasm32',
  abi: { exceptions: man.host_baseline.exceptions, pthread: man.host_baseline.pthread },
});
check('compile() succeeds from the bundle alone', r.ok === true, r.ok ? '' : (r.error + ' ' + JSON.stringify(r.detail || [])));
if (r.ok) {
  const m = new WebAssembly.Module(r.moduleBytes);
  const ex = WebAssembly.Module.exports(m).map((e) => e.name);
  check('product exports minifn', ex.includes('minifn'), ex.join(','));
  check('product is relocatable (__memory_base imported)',
        WebAssembly.Module.imports(m).some((i) => i.name === '__memory_base'));
  console.log(`   ${r.moduleBytes.length} bytes`);
  mkdirSync(join(OUT, 'smoke'), { recursive: true });
}

// ------------------------------------------------------------- §6 budget
console.log('\n== SPEC §6: first-pull budget ==');
const fl = man.first_load;
check('first_load breakdown is recorded', !!fl && Array.isArray(fl.assets), JSON.stringify(fl?.assets));
if (fl) {
  const ok = fl.brotli_bytes <= 15_000_000;
  check(`first pull <= 15 MB (brotli)`, ok,
        `${fl.brotli_bytes.toLocaleString()} bytes (${(fl.brotli_bytes / 1e6).toFixed(2)} MB)`);
  console.log(`   total incl. lazy lld: ${(fl.plus_lld_brotli_bytes / 1e6).toFixed(2)} MB`);
}

console.log('-- artifacts');
console.log(`ARTIFACT release_acceptance_pass ${passCount}`);
console.log(`\n=== ${fails === 0 ? 'ALL PASS' : fails + ' FAILED'} ===`);
process.exitCode = fails === 0 ? 0 : 1;
