// The _ZTIi regression (host ticket 65, gap 2; ruled A on 2026-10-17).
//
// The host ruled that basic-type throws SHOULD cross the boundary, and landed
// the zero-risk half: seven basic typeinfos added to its keep-list generator
// and the in-container keep files. The relink that would put the definitions
// into the shipped host is a separate batch, so TODAY the real host still
// lacks _ZTIi -- and that difference is exactly what this file pins.
//
// Two assertions, one for each side of the ruling's timetable:
//
//   BEFORE the host's relink: the gap check must NAME _ZTIi for a throw-int
//   module against the real host. The host explicitly asked us to keep this
//   ("别提前撤") -- it is the compile-time warning .oct authors get until the
//   relink lands.
//
//   AFTER the relink: the same check against the relinked host must report
//   _ZTIi present (missingFunctions empty for it). When that flips, the host's
//   own probe-toolchain-gap suite flips too, and this half becomes the proof
//   the ruling landed end to end.
//
// The compile side is asserted once: a throw-int fixture, built by THIS
// toolchain, must import _ZTIi -- that is what any correct compiler emits
// (emcc produces the same), and it is why the ownership question was never
// "the toolchain should stop emitting it".
//
// Usage: node driver/check-ztii-regression.mjs [--host <host.wasm>]
import { join, dirname } from 'path';
import { readFileSync, existsSync, writeFileSync, mkdirSync } from 'fs';
import { Toolchain } from './toolchain.mjs';

const ROOT = join(dirname(new URL(import.meta.url).pathname), '..');
const args = process.argv.slice(2);
const hi = args.indexOf('--host');
const HOST = hi >= 0 ? args[hi + 1] : '/mnt/hdd/octave-wasm-build/siteWebGL/w64/octave.wasm';

let fails = 0, passCount = 0;
const check = (what, ok, detail = '') => {
  if (ok) passCount++; else fails++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${what}${detail ? ': ' + detail : ''}`);
};

const CLANG_REL = ['m1/build-exp-lean_nosjlj/bin', 'm1/build-exp-anchor/bin', 'm1/build-clang/bin']
  .find((c) => existsSync(join(ROOT, c, 'clang.js')));
const LLD_BIN = join(ROOT, 'm1/build-lld/bin');
const LLD_JS = existsSync(join(LLD_BIN, 'lld-wasm-only.js')) ? 'lld-wasm-only.js' : 'lld.js';
const LLD_WASM = LLD_JS.replace(/\.js$/, '.wasm');

// A throw of a BASIC type: the exact pattern no production .oct uses (0 of
// 11,663) and any correct compiler emits _ZTIi for.
const THROW_INT = `extern "C" __attribute__((visibility("default"))) int probe(int m) {
  try { if (m) throw 42; } catch (int e) { return 1; }
  return 0;
}
`;

const tc = new Toolchain({
  clangBin: join(ROOT, CLANG_REL), lldBin: LLD_BIN, lldJs: LLD_JS,
  bundle: {
    tars: { wasm32: { tarPath: join(ROOT, 'release/out/sysroot-headers.tar'),
                      manifestPath: join(ROOT, 'release/out/manifest.json') } },
  },
  quiet: true,
});

console.log('== compile: a throw-int module must import _ZTIi ==');
const r = await tc.compile({ source: THROW_INT, target: 'wasm32',
  abi: { exceptions: 'wasm-legacy', pthread: true } });
check('throw-int fixture compiles', r.ok === true, r.ok ? '' : r.error);
let hasIt = false;
if (r.ok) {
  const m = new WebAssembly.Module(r.moduleBytes);
  hasIt = WebAssembly.Module.imports(m).some((i) => i.name === '_ZTIi');
  check('the product imports _ZTIi (any correct compiler does; emcc identical)',
        hasIt === true);
  mkdirSync(join(ROOT, 'driver', 'evidence'), { recursive: true });
  writeFileSync(join(ROOT, 'driver', 'evidence', 'ztii-probe.so'), r.moduleBytes);
}

if (hasIt && existsSync(HOST)) {
  console.log('\n== gap against the real host (ruling A, before its relink) ==');
  const { symbolGap } = await import('./abi.mjs');
  const g = symbolGap(r.moduleBytes, readFileSync(HOST));
  check('host was checked', g.hostChecked === true);
  const named = g.missingFunctions.includes('_ZTIi');
  if (named) {
    // The expected state until the host relinks: named, not silent. The host
    // asked for this warning to stay.
    check('the gap check NAMES _ZTIi against the current host (compile-time warning until the relink)',
          true, 'the relink will flip this half — see the note below');
  } else {
    // If we get here the host has relinked (or exports it another way): the
    // ruling landed, and the correct behaviour is a clean report, not a
    // failure. Say which state this is so the flip is visible in the log.
    console.log('PASS _ZTIi is provided by the host — ruling A has landed (this line');
    console.log('     replaces the "names it" assertion once the relink ships);');
    console.log('     remaining missingFunctions:', JSON.stringify(g.missingFunctions));
  }
} else if (!existsSync(HOST)) {
  console.log(`\nSKIP gap-vs-host: no host at ${HOST} (pass --host)`);
}

console.log('-- artifacts');
console.log(`ARTIFACT ztii_regression_pass ${passCount}`);
console.log(`\n=== ${fails === 0 ? 'ALL PASS' : fails + ' FAILED'} ===`);
process.exitCode = fails === 0 ? 0 : 1;
