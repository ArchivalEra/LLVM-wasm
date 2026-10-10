// Reverse assertion for the §5.4 gap check: a module that DOES have a gap must
// have it named.
//
// The positive path (no gap ⇒ "all clear") proves little on its own: a checker
// that always answers "no gaps" passes it. This fixture deliberately needs two
// symbols the real host lacks, so the checker has to say so, by name.
//
// One of the two is the gap SPEC 5.2 recorded as real:
//   std::basic_ostream<char>::operator<<(unsigned long)
// The other is invented here so the test does not depend on which STL
// instantiations that particular host happens to carry.
//
// Usage: node driver/check-gap-reverse.mjs [--host <host.wasm>]
import { join, dirname } from 'path';
import { existsSync } from 'fs';
import { Toolchain } from './toolchain.mjs';

const ROOT = join(dirname(new URL(import.meta.url).pathname), '..');
const DEFAULT_HOST = '/mnt/hdd/octave-wasm-build/siteWebGL/w64/octave.wasm';
const args = process.argv.slice(2);
const i = args.indexOf('--host');
const HOST = i >= 0 ? args[i + 1] : DEFAULT_HOST;

let fails = 0, passCount = 0;
const check = (what, ok, detail = '') => {
  if (ok) passCount++; else fails++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${what}${detail ? ': ' + detail : ''}`);
};

if (!existsSync(HOST)) {
  // A missing input must never read as "no gaps found".
  console.error(`FATAL: host not found: ${HOST}`);
  console.error('  this check needs a real host export surface; pass --host <file.wasm>');
  process.exit(2);
}

const CLANG_REL = ['m1/build-exp-anchor/bin', 'm1/build-clang/bin']
  .find((c) => existsSync(join(ROOT, c, 'clang.js')));
const LLD_BIN = join(ROOT, 'm1/build-lld/bin');
const LLD_JS = existsSync(join(LLD_BIN, 'lld-wasm-only.js')) ? 'lld-wasm-only.js' : 'lld.js';

const tc = new Toolchain({
  clangBin: join(ROOT, CLANG_REL),
  lldBin: LLD_BIN, lldJs: LLD_JS,
  sysroot: join(ROOT, 'toolchain/emsdk/upstream/emscripten/cache/sysroot'),
  quiet: true,
});

const INVENTED = 'host_symbol_that_does_not_exist';
const SPEC_GAP = '_ZNSt3__213basic_ostreamIcNS_11char_traitsIcEEElsEm'; // ostream<<unsigned long

const SOURCE = `
#include <map>
#include <string>
#include <sstream>
extern "C" int ${INVENTED}(int);
extern "C" __attribute__((visibility("default"))) int probe(unsigned long v) {
  std::map<std::string,double> m; m["a"]=1.0;
  std::ostringstream os; os << v << ":" << m.size();
  return (int)os.str().size() + ${INVENTED}(1);
}
`;

console.log(`host: ${HOST}`);
const r = await tc.compile({
  source: SOURCE,
  abi: { exceptions: 'wasm-legacy', pthread: true },
  hostWasm: HOST,
});

check('compile succeeded', r.ok === true, r.ok ? '' : r.error);
if (r.ok) {
  const g = r.symbolGap;
  console.log(`   needs ${g.needs} symbols; missing ${g.missingFunctions.length}`);
  for (const x of g.missingFunctions) console.log(`     MISSING ${x}`);

  check('host was actually checked', g.hostChecked === true);
  check('the invented missing symbol is named', g.missingFunctions.includes(INVENTED));
  // The SPEC 5.2 gap only counts if this host really lacks it; ask the host.
  const host = new WebAssembly.Module(
    (await import('fs')).readFileSync(HOST));
  const hostHasIt = WebAssembly.Module.exports(host).some((e) => e.name === SPEC_GAP);
  if (!hostHasIt) {
    check('the SPEC 5.2 gap is named too', g.missingFunctions.includes(SPEC_GAP),
          g.missingFunctions.includes(SPEC_GAP) ? '' : 'not reported');
  } else {
    console.log(`   (host exports ${SPEC_GAP}; skipping that half of the assertion)`);
  }
  check('the report is not empty (a checker answering "no gaps" would fail here)',
        g.missingFunctions.length > 0);
}

console.log('-- artifacts');
console.log(`ARTIFACT gap_reverse_pass ${passCount}`);
console.log(`\n=== ${fails === 0 ? 'ALL PASS' : fails + ' FAILED'} ===`);
process.exitCode = fails === 0 ? 0 : 1;
