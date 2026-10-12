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
// Per-arch sysroots, read from the manifest rather than assumed. Issue #1 was
// exactly this assumption: the release shipped one (wasm32) tar while
// targets_built claimed both, and nothing in the acceptance ever opened the
// shipped tar, so a wasm64 request returned ok:true without the TLS entry.
const SYSROOTS = man.toolchain?.sysroots || {};
check('manifest declares a sysroot per built target',
      (man.toolchain?.targets_built || []).every((t) => !!SYSROOTS[t]),
      JSON.stringify(SYSROOTS));
for (const [arch, name] of Object.entries(SYSROOTS)) {
  check(`sysroot for ${arch} is present in the bundle (${name})`, existsSync(join(OUT, name)));
}
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
for (const n of ['clang.wasm', LLD_WASM_NAME, ...Object.values(SYSROOTS)]) {
  try { verified(n); check(`${n} verifies against manifest`, true); }
  catch (e) { check(`${n} verifies against manifest`, false, e.message); }
}

// Each shipped sysroot must actually carry ITS arch's crtbegin. This is the
// assertion whose absence let issue #1 through: the zips/ tar were "present and
// checksummed" while being the wrong arch for one of the two targets.
const { readTar } = await import(`file://${join(OUT, 'driver', 'tar-reader.mjs')}`);
for (const [arch, name] of Object.entries(SYSROOTS)) {
  try {
    const files = readTar(readFileSync(join(OUT, name)));
    const want = `sysroot/lib/${arch}-emscripten/pic/crtbegin-mt.o`;
    check(`${name} carries lib/${arch}-emscripten/pic/crtbegin-mt.o`, files.has(want),
          files.has(want) ? '' : `missing; it has ${[...files.keys()].filter((k) => k.includes('crtbegin')).join(',') || 'no crtbegin at all'}`);
  } catch (e) { check(`${name} unreadable`, false, e.message); }
}

// ------------------------------------------------- compile straight from bundle
console.log('\n== consume: compile using only the bundle ==');
const { Toolchain } = await import(`file://${join(OUT, 'driver', 'toolchain.mjs')}`);
const SOURCE = `#include <string>
extern "C" __attribute__((visibility("default"))) int minifn(int x) {
  std::string s = "abc";
  return x + (int)s.size();
}
`;

// The delivery shape a downstream actually uses: one bundle spec carrying both
// tars, letting the driver pick by target.
const tars = Object.fromEntries(Object.entries(SYSROOTS).map(([arch, name]) => [arch, {
  tarPath: join(OUT, name), manifestPath: manPath,
}]));
const tc = new Toolchain({
  clangBin: OUT, clangJs: 'clang.js',
  lldBin: OUT, lldJs: LLD_GLUE_NAME,
  bundle: { tars },
  quiet: true,
});

for (const [target, abi] of [
  ['wasm32', { exceptions: man.host_baseline.exceptions, pthread: man.host_baseline.pthread, memory64: false }],
  ['wasm64', { exceptions: man.host_baseline.exceptions, pthread: man.host_baseline.pthread, memory64: true }],
]) {
  if (!SYSROOTS[target]) { console.log(`   (no sysroot for ${target}; skipping)`); continue; }
  const r = await tc.compile({ source: SOURCE, target, abi });
  check(`compile(${target}) succeeds from the bundle alone`, r.ok === true,
        r.ok ? '' : (r.error + ' ' + JSON.stringify(r.detail || [])));
  if (!r.ok) continue;
  const m = new WebAssembly.Module(r.moduleBytes);
  const ex = WebAssembly.Module.exports(m).map((e) => e.name);
  check(`${target}: product exports minifn`, ex.includes('minifn'), ex.join(','));
  check(`${target}: product is relocatable (__memory_base imported)`,
        WebAssembly.Module.imports(m).some((i) => i.name === '__memory_base'));
  // The symbol whose absence is issue #1's whole symptom: without it a threaded
  // host refuses the module with "tlsInitFunc is not a function".
  check(`${target}: product exports _emscripten_tls_init (TLS entry present)`,
        ex.includes('_emscripten_tls_init'),
        ex.includes('_emscripten_tls_init') ? '' : 'missing — this is the issue #1 symptom');
  console.log(`   ${target}: ${r.moduleBytes.length} bytes`);
}
mkdirSync(join(OUT, 'smoke'), { recursive: true });

// ---------------------------------------------- the reverse assertion itself
console.log('\n== the refusal: a bundle without the target\'s sysroot must not claim ok ==');
const only32 = new Toolchain({
  clangBin: OUT, clangJs: 'clang.js', lldBin: OUT, lldJs: LLD_GLUE_NAME,
  bundle: { tarPath: join(OUT, SYSROOTS.wasm32 || 'sysroot-headers.tar'), manifestPath: manPath },
  quiet: true,
});
const rr = await only32.compile({ source: SOURCE, target: 'wasm64',
  abi: { exceptions: man.host_baseline.exceptions, pthread: true, memory64: true } });
check('wasm32-only bundle refuses target wasm64', rr.ok === false,
      rr.ok ? `IT RETURNED ok:true (${rr.moduleBytes.length} B) — silent degradation` : rr.error.slice(0, 90));
check('the refusal names the missing sysroot',
      !rr.ok && /sysroot for wasm64/i.test(rr.error), rr.error?.slice(0, 90));

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
// The bundle's own numbers, re-derived here from the manifest rather than
// copied out of the packaging log: this file is what the fact scanner reads,
// so what it prints is what the ledger will hold.
console.log(`ARTIFACT release_assets ${man.assets.length}`);
if (man.first_load) {
  console.log(`ARTIFACT release_first_load_brotli ${man.first_load.brotli_bytes}`);
  console.log(`ARTIFACT release_total_brotli ${man.first_load.plus_lld_brotli_bytes}`);
}
console.log(`ARTIFACT release_targets ${(man.toolchain?.targets_built || []).length}`);
console.log(`\n=== ${fails === 0 ? 'ALL PASS' : fails + ' FAILED'} ===`);
process.exitCode = fails === 0 ? 0 : 1;
