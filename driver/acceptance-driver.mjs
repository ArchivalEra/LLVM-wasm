// Driver acceptance — SPEC §7.4/§7.5: does the thin driver actually work?
//
// The driver's job is to assemble §4.1/§4.2 for the caller and to run the §5.4
// gap check. So this test drives it the way a browser host would (a source
// string in, module bytes + a gap report out) and then verifies the product is
// a real side module.
//
// It also checks the §4.5 contract: a bad ABI value must be refused, and an
// unbuilt target must be refused rather than silently downgraded. Those are the
// reverse assertions -- without them the positive path proves little.
//
// Usage: node driver/acceptance-driver.mjs [--host <host.wasm>]
import { join, dirname } from 'path';
import { existsSync, writeFileSync, mkdirSync, readFileSync } from 'fs';
import { Toolchain, symbolGap, EXCEPTION_MODES } from './toolchain.mjs';

const ROOT = join(dirname(new URL(import.meta.url).pathname), '..');
const OUT = join(ROOT, 'driver', 'acceptance');

let fails = 0, passCount = 0;
const check = (what, ok, detail = '') => {
  if (ok) passCount++; else fails++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${what}${detail ? ': ' + detail : ''}`);
};

const args = process.argv.slice(2);
const hostIdx = args.indexOf('--host');
const hostWasm = hostIdx >= 0 ? args[hostIdx + 1] : null;

mkdirSync(OUT, { recursive: true });

// SPEC §9.1's minimal fixture: one exported function + one std::string use.
const SOURCE = `#include <string>
extern "C" __attribute__((visibility("default"))) int minifn(int x) {
  std::string s = "abc";
  return x + (int)s.size();
}
`;

// Use whichever build is available; the optimized one if the neighbour made it.
const CLANG_CANDS = ['m1/build-exp-anchor/bin', 'm1/build-clang/bin'];
const CLANG_REL = CLANG_CANDS.find((c) => existsSync(join(ROOT, c, 'clang.js'))) || CLANG_CANDS[0];
const CLANG_BIN = join(ROOT, CLANG_REL);
const LLD_BIN = join(ROOT, 'm1/build-lld/bin');
const LLD_JS = existsSync(join(LLD_BIN, 'lld-wasm-only.js'))
  ? 'lld-wasm-only.js' : 'lld.js';
const SYSROOT = join(ROOT, 'toolchain/emsdk/upstream/emscripten/cache/sysroot');

console.log(`clang:  ${CLANG_BIN}`);
console.log(`lld:    ${LLD_BIN} (${LLD_JS})`);

const tc = new Toolchain({
  clangBin: CLANG_BIN, lldBin: LLD_BIN, lldJs: LLD_JS, sysroot: SYSROOT, quiet: true,
});

// ============================================================ 1. the happy path
console.log('\n== [1] compile({source}) — the interface SPEC 7.4 asks for ==');
const r = await tc.compile({
  source: SOURCE,
  target: 'wasm32',
  abi: { exceptions: 'wasm-legacy', pthread: true, memory64: false },
  hostWasm: hostWasm && existsSync(hostWasm) ? hostWasm : undefined,
});

check('compile() reports ok', r.ok === true, r.ok ? '' : r.error);
if (r.ok) {
  check('moduleBytes returned', r.moduleBytes && r.moduleBytes.length > 0,
        r.moduleBytes ? `${r.moduleBytes.length} bytes` : 'none');
  writeFileSync(join(OUT, 'module.so'), r.moduleBytes);

  // ---------------------------------------------------- 2. product is real
  console.log('\n== [2] the product is a side module ==');
  const m = new WebAssembly.Module(r.moduleBytes);
  const ex = WebAssembly.Module.exports(m).map((e) => e.name);
  const im = WebAssembly.Module.imports(m);
  check('exports minifn', ex.includes('minifn'), ex.join(','));
  check('exports __wasm_call_ctors', ex.includes('__wasm_call_ctors'));
  check('exports _emscripten_tls_init', ex.includes('_emscripten_tls_init'));
  check('imports env.memory', im.some((i) => i.module === 'env' && i.name === 'memory'));
  check('relocatable (__memory_base)', im.some((i) => i.name === '__memory_base'));

  // ------------------------------------------------ 3. the §5.4 gap report
  console.log('\n== [3] symbolGap (SPEC 5.4) ==');
  check('gap report present', !!r.symbolGap);
  if (r.symbolGap) {
    const g = r.symbolGap;
    console.log(`   needs ${g.needs} symbols, ${g.needsTags} tags; hostChecked=${g.hostChecked}`);
    check('gap report exposes the three named fields',
          Array.isArray(g.missingFunctions) && Array.isArray(g.missingTags)
          && Array.isArray(g.sideSelfExported));
    if (g.hostChecked) {
      console.log(`   missing: ${g.missingFunctions.length} fns, ${g.missingTags.length} tags`);
      for (const x of g.missingFunctions) console.log(`     MISSING ${x}`);
    } else {
      // Zero-value guard: with no host we must NOT claim "no gaps".
      check('no host ⇒ hostChecked is false (does not claim zero gaps)', g.hostChecked === false);
    }
  }
}

// ============================================================ 4. reverse cases
console.log('\n== [4] reverse assertions (SPEC 4.5 contract) ==');
const badAbi = await tc.compile({ source: SOURCE, abi: { exceptions: 'nonsense' } });
check('unknown abi.exceptions is refused', badAbi.ok === false,
      badAbi.ok ? 'ACCEPTED A BAD ABI' : badAbi.error);

const badTarget = await tc.compile({ source: SOURCE, target: 'wasm64' });
check('unbuilt target wasm64 is refused (not silently wasm32)',
      badTarget.ok === false, badTarget.ok ? 'SILENTLY DOWNGRADED' : badTarget.error);

const noInput = await tc.compile({});
check('no source and no files is refused', noInput.ok === false,
      noInput.ok ? 'ACCEPTED EMPTY INPUT' : noInput.error);

// ============================================================ 5. unit: the gap
console.log('\n== [5] symbolGap is a pure function (no host ⇒ no false "all clear") ==');
if (existsSync(join(OUT, 'module.so'))) {
  const g2 = symbolGap(readFileSync(join(OUT, 'module.so')), null);
  check('returns needs count without a host', typeof g2.needs === 'number');
  check('does not fabricate missingFunctions without a host', g2.missingFunctions.length === 0
        && g2.hostChecked === false);
} else {
  check('skipped: no module to inspect (compile failed above)', false,
        'fix the compile failure first');
}

console.log('-- artifacts');
console.log(`ARTIFACT driver_acceptance_pass ${passCount}`);
if (existsSync(join(OUT, 'module.so'))) {
  console.log(`ARTIFACT driver_module_bytes ${readFileSync(join(OUT, 'module.so')).length}`);
}
console.log(`\n=== ${fails === 0 ? 'ALL PASS' : fails + ' FAILED'} ===`);
process.exitCode = fails === 0 ? 0 : 1;
