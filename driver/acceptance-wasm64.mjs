// wasm64 acceptance — SPEC §4.5 requires both wasm32 and wasm64, and §9.7 says
// both must pass the same acceptance. This runs the driver for both targets and
// asserts the results are genuinely different architectures.
//
// The load-bearing assertion is the reverse one: asking for wasm64 must produce
// a 64-bit module. A driver that ignored `target` would return wasm32 bytes for
// both, and every positive check (exports present, links, gap report) would
// still pass. So we read the memory type out of the binary.
//
// Pointer width is read by parsing the import section's limits flags: the
// memory64 proposal sets bit 0x04. Done in plain JS because a browser has no
// wasm-dis to shell out to.
//
// Usage: node driver/acceptance-wasm64.mjs
import { join, dirname } from 'path';
import { existsSync } from 'fs';
import { Toolchain } from './toolchain.mjs';

const ROOT = join(dirname(new URL(import.meta.url).pathname), '..');

let fails = 0, passCount = 0;
const check = (what, ok, detail = '') => {
  if (ok) passCount++; else fails++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${what}${detail ? ': ' + detail : ''}`);
};

/** Read the imported memory's limits flags. Bit 0x04 == memory64. */
function memoryType(bytes) {
  const b = Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes);
  let off = 8;                                    // magic + version
  while (off < b.length) {
    const id = b[off++];
    let size = 0, shift = 0, byte;
    do { byte = b[off++]; size |= (byte & 0x7f) << shift; shift += 7; } while (byte & 0x80);
    if (id === 2) {                               // import section
      let p = off;
      const leb = () => { let r = 0, s = 0, x; do { x = b[p++]; r |= (x & 0x7f) << s; s += 7; } while (x & 0x80); return r; };
      const n = leb();
      for (let i = 0; i < n; i++) {
        const ml = leb(); p += ml;
        const fl = leb(); p += fl;
        const kind = b[p++];
        if (kind === 0x02) {
          const flags = b[p++];
          return { is64: !!(flags & 0x04), flags };
        }
        if (kind === 0x00) leb();
        else if (kind === 0x01) { p++; leb(); leb(); }
        else if (kind === 0x03) { p += 2; }
        else if (kind === 0x04) { p++; leb(); }
      }
    }
    off += size;
  }
  return null;
}

const CLANG_REL = ['m1/build-exp-anchor/bin', 'm1/build-clang/bin']
  .find((c) => existsSync(join(ROOT, c, 'clang.js')));
const LLD_BIN = join(ROOT, 'm1/build-lld/bin');
const LLD_JS = existsSync(join(LLD_BIN, 'lld-wasm-only.js')) ? 'lld-wasm-only.js' : 'lld.js';

const SOURCE = `#include <string>
extern "C" __attribute__((visibility("default"))) int minifn(int x) {
  std::string s = "abc";
  return x + (int)s.size();
}
`;

const results = {};
for (const target of ['wasm32', 'wasm64']) {
  console.log(`\n== ${target} ==`);
  const tar = join(ROOT, `package/out/sysroot-${target}.tar`);
  const man = join(ROOT, `package/out/manifest-${target}.json`);
  if (!existsSync(tar)) {
    check(`${target}: sysroot bundle exists`, false, `run package/package-sysroot.sh ${target}`);
    continue;
  }
  const tc = new Toolchain({
    clangBin: join(ROOT, CLANG_REL), lldBin: LLD_BIN, lldJs: LLD_JS,
    bundle: { tarPath: tar, manifestPath: man },
    quiet: true,
  });
  const r = await tc.compile({
    source: SOURCE, target,
    abi: { exceptions: 'wasm-legacy', pthread: true, memory64: target === 'wasm64' },
  });
  check(`${target}: compile ok`, r.ok === true, r.ok ? '' : r.error);
  if (!r.ok) continue;

  const ex = WebAssembly.Module.exports(new WebAssembly.Module(r.moduleBytes)).map((e) => e.name);
  check(`${target}: exports minifn`, ex.includes('minifn'), ex.join(','));
  const mt = memoryType(r.moduleBytes);
  check(`${target}: has an imported memory`, !!mt);
  results[target] = { bytes: r.moduleBytes.length, is64: mt ? mt.is64 : null };
  console.log(`   ${r.moduleBytes.length} bytes, memory64=${mt ? mt.is64 : '?'}`);
}

// ------------------------------------------------------------- the discriminator
console.log('\n== the two targets must differ in pointer width ==');
if (results.wasm32 && results.wasm64) {
  check('wasm32 module is 32-bit', results.wasm32.is64 === false, `is64=${results.wasm32.is64}`);
  check('wasm64 module is genuinely 64-bit (not a silent downgrade)',
        results.wasm64.is64 === true,
        results.wasm64.is64 ? '' : 'asked for wasm64, got 32-bit memory — the target was ignored');
  check('the two modules differ', results.wasm32.is64 !== results.wasm64.is64);
}

// --------------------------------------------------------------- bad target
console.log('\n== unknown target is refused ==');
const tcAny = new Toolchain({
  clangBin: join(ROOT, CLANG_REL), lldBin: LLD_BIN, lldJs: LLD_JS,
  bundle: { tarPath: join(ROOT, 'package/out/sysroot-wasm32.tar') },
  quiet: true,
});
const bad = await tcAny.compile({ source: SOURCE, target: 'wasm128' });
check('target wasm128 refused', bad.ok === false, bad.ok ? 'ACCEPTED' : bad.error);

console.log('-- artifacts');
console.log(`ARTIFACT wasm64_acceptance_pass ${passCount}`);
if (results.wasm64) console.log(`ARTIFACT wasm64_module_bytes ${results.wasm64.bytes}`);
if (results.wasm32) console.log(`ARTIFACT wasm32_module_bytes ${results.wasm32.bytes}`);
console.log(`\n=== ${fails === 0 ? 'ALL PASS' : fails + ' FAILED'} ===`);
process.exitCode = fails === 0 ? 0 : 1;
