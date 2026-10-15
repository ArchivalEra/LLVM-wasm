// Guard the compile seam (codebase-design).
//
// The defect this prevents: two adapters implemented the compile pipeline
// independently, and issue #1's precheck ("refuse when the sysroot cannot serve
// the target") reached the node adapter but never the browser one. Sharing the
// flag assembly was not enough — the ORCHESTRATION drifted, and the same
// failure (a module with no _emscripten_tls_init) came back one layer down, in
// the browser path, after it had been fixed and verified in node.
//
// A comment saying "keep these in step" would not hold. So this checks the
// structure instead:
//
//   1. compileWith (driver/compile-core.mjs) is the only place that assembles
//      the pipeline — neither adapter calls compileArgv/linkArgv itself;
//   2. both adapters go through it;
//   3. the precheck lives in the core, not in an adapter;
//   4. the core cannot be bypassed silently: removing it from an adapter turns
//      this red.
//
// Usage: node driver/check-compile-seam.mjs
import { readFileSync, existsSync } from 'fs';
import { join, dirname } from 'path';

const ROOT = join(dirname(new URL(import.meta.url).pathname), '..');
let fails = 0, passCount = 0;
const check = (what, ok, detail = '') => {
  if (ok) passCount++; else fails++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${what}${detail ? ': ' + detail : ''}`);
};

const read = (rel) => existsSync(join(ROOT, rel)) ? readFileSync(join(ROOT, rel), 'utf8') : null;

// Match CODE, not prose. The first version of this guard tested the raw text and
// passed while the browser adapter had stopped calling the core -- because a
// comment still mentioned it (measured). A guard that a comment can satisfy is
// not a guard.
const stripComments = (src) => (src || '')
  .replace(/\/\*[\s\S]*?\*\//g, '')      // block comments
  .replace(/(^|[^:])\/\/[^\n]*/g, '$1');  // line comments (not http://)

const core = read('driver/compile-core.mjs');
const nodeAdapter = read('driver/toolchain.mjs');
const browserAdapter = read('browser/worker.mjs');

check('the core exists', !!core);
check('both adapters exist', !!nodeAdapter && !!browserAdapter);

// ------------------------------------------------ the core owns the pipeline
console.log('\n== the pipeline has one home ==');
if (core) {
  check('the core assembles argv', /compileArgv\s*\(/.test(stripComments(core)) && /linkArgv\s*\(/.test(stripComments(core)));
  check('the core owns the precheck', /sysroot for \$\{target\} is missing/.test(core),
        'the refusal message lives here, so both adapters inherit it');
  check('the core exports compileWith', /export async function compileWith/.test(core));
}

// ---------------------------------------- adapters delegate, they do not redo
console.log('\n== adapters delegate ==');
for (const [name, src] of [['driver/toolchain.mjs', nodeAdapter], ['browser/worker.mjs', browserAdapter]]) {
  if (!src) continue;
  const code = stripComments(src);
  const callsCore = /compileWith\s*\(/.test(code);
  // an adapter that assembles argv itself has re-grown the duplicated pipeline
  const assemblesOwn = /compileArgv\s*\(|linkArgv\s*\(/.test(code);
  check(`${name} calls compileWith`, callsCore);
  check(`${name} does not assemble argv itself`, !assemblesOwn,
        assemblesOwn ? 'it re-implements the pipeline — that is the drift this guards' : '');
  // the precheck must NOT be duplicated in an adapter: two copies is how they
  // diverge (one gets fixed, the other does not)
  const ownsPrecheck = /sysroot for \$\{target\} is missing|Refusing rather than/.test(code);
  check(`${name} does not re-implement the precheck`, !ownsPrecheck,
        ownsPrecheck ? 'the precheck belongs in the core' : '');
}

// ----------------------------------- the invariant the core relies on
console.log('\n== the runtime contract the core depends on ==');
if (core && nodeAdapter) {
  check('the core asks the runtime which targets exist',
        /runtime\.targetsAvailable\(\)/.test(core));
  check('the core asks for a fresh lld per compile', /await runtime\.lld\(/.test(core));
  // lld() must stage the sysroot for the requested arch: a fresh instance
  // starts empty, so omitting this makes every link fail on a missing crt.
  const nodeStages = /async lld\(arch/.test(nodeAdapter) && /_stageSysroot\(mod\.FS, arch\)/.test(nodeAdapter);
  check('the node adapter stages the sysroot in lld() (fresh instance starts empty)',
        nodeStages, nodeStages ? '' : 'lld() must hand back an instance already carrying the sysroot');
  const browserStages = /installFiles\(mod\.FS, sysrootFiles\)/.test(browserAdapter || '');
  check('the browser adapter stages the sysroot in lld()', browserStages);
}

// ------------------------------------------- the invariant itself, executable
console.log('\n== the precheck actually refuses (not just present as text) ==');
const { compileWith } = await import(`file://${join(ROOT, 'driver/compile-core.mjs')}`);
const stub = {
  targetsAvailable: () => ['wasm32'],            // a wasm32-only sysroot
  clang: async () => { throw new Error('must not be reached'); },
  lld: async () => { throw new Error('must not be reached'); },
};
const r = await compileWith(stub, { source: 'int f(){return 0;}', target: 'wasm64' });
check('wasm64 against a wasm32-only runtime is refused', r.ok === false, r.ok ? 'IT RETURNED ok:true' : '');
check('the refusal names the missing sysroot', /sysroot for wasm64/i.test(r.error || ''), r.error?.slice(0, 70));
check('it refuses before touching clang or lld (no work done)', r.stage === 'precheck', `stage=${r.stage}`);

console.log('-- artifacts');
console.log(`ARTIFACT compile_seam_check_pass ${passCount}`);
console.log(`\n=== ${fails === 0 ? 'ALL PASS' : fails + ' FAILED'} ===`);
process.exitCode = fails === 0 ? 0 : 1;
