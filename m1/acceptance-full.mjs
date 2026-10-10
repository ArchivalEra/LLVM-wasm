// M1 full acceptance — compile AND link a side module, entirely inside wasm.
//
// This is SPEC §10 M1's real gate: "浏览器里编出 §9.1 的产物". Two in-wasm
// modules cooperate through an in-memory filesystem (SPEC §7.2):
//
//   clang.wasm  --compile--> hello.o
//   lld.wasm (wasm-ld) --link--> minifn.so   (an Emscripten side module)
//
// The product is then checked structurally for the side-module ABI markers
// (dylink.0, GOT imports) so a linker that emits a plain executable cannot
// pass by accident.
//
// Usage: node m1/acceptance-full.mjs
import { readFileSync, existsSync, readdirSync, writeFileSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const ROOT = dirname(new URL(import.meta.url).pathname);
// 默认跑 M1 基线产物。体积实验要复核「降了体积还能不能编」时，用环境变量把
// 两个模块指到实验产物上，例如：
//   M1_CLANG_BIN=m1/build-exp-anchor/bin M1_LLD_BIN=m1/build-exp-anchor/bin \
//   M1_LLD_JS=lld-wasm-only.js node m1/acceptance-full.mjs
const BIN = process.env.M1_CLANG_BIN
  ? (process.env.M1_CLANG_BIN.startsWith('/') ? process.env.M1_CLANG_BIN : join(ROOT, '..', process.env.M1_CLANG_BIN))
  : join(ROOT, 'build-clang', 'bin');
const LLD_BIN = process.env.M1_LLD_BIN
  ? (process.env.M1_LLD_BIN.startsWith('/') ? process.env.M1_LLD_BIN : join(ROOT, '..', process.env.M1_LLD_BIN))
  : join(ROOT, 'build-lld', 'bin');
const LLD_JS = process.env.M1_LLD_JS || 'lld.js';
const CLANG_JS = process.env.M1_CLANG_JS || 'clang.js';
const SR = join(ROOT, '..', 'toolchain/emsdk/upstream/emscripten/cache/sysroot');
const OUT = join(ROOT, 'acceptance');

const SOURCE = `#include <string>
extern "C" __attribute__((visibility("default"))) int minifn(int x) {
  std::string s = "abc";
  return x + (int)s.size();
}
`;

let fails = 0;
let passCount = 0;
const check = (what, ok, detail = '') => {
  if (ok) passCount++; else fails++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${what}${detail ? ': ' + detail : ''}`);
};

// ------------------------------------------------------------- fs staging
function stageTree(fs, hostPath, fsPath) {
  let n = 0;
  const walk = (src, dst) => {
    for (const e of readdirSync(src, { withFileTypes: true })) {
      const s = join(src, e.name), d = join(dst, e.name);
      if (e.isDirectory()) { fs.mkdirTree(d); walk(s, d); }
      else if (e.isFile()) { try { fs.writeFile(d, readFileSync(s)); n++; } catch {} }
    }
  };
  fs.mkdirTree(fsPath);
  walk(hostPath, fsPath);
  return n;
}

function stageSysroot(fs) {
  let n = stageTree(fs, join(SR, 'include'), '/sysroot/include');
  // pic/crtbegin-mt.o is what SPEC 4.2 links against; it may not exist until
  // emcc has generated it.
  const pic = join(SR, 'lib/wasm32-emscripten/pic');
  if (existsSync(pic)) n += stageTree(fs, pic, '/sysroot/lib/wasm32-emscripten/pic');
  return n;
}

mkdirSync(OUT, { recursive: true });

// ============================================================ 1. compile
console.log(`== [1] clang.wasm: compile ==  (${BIN})`);
const createClang = require(join(BIN, CLANG_JS));
const clang = await createClang({ print: () => {}, printErr: () => {}, noInitialRun: true });
clang.FS.mkdirTree('/src');
clang.FS.writeFile('/src/hello.cc', SOURCE);
const staged = stageSysroot(clang.FS);
console.log(`   staged ${staged} sysroot files`);

const rc1 = clang.callMain([
  '--target=wasm32-unknown-emscripten', '--sysroot=/sysroot',
  '-isystem', '/sysroot/include/compat',
  '-fvisibility=default', '-fPIC', '-O2', '-fwasm-exceptions', '-pthread',
  '-c', '/src/hello.cc', '-o', '/src/hello.o',
]);
check('clang exits 0', rc1 === 0, `rc=${rc1}`);
let obj = null;
try { obj = clang.FS.readFile('/src/hello.o'); } catch {}
check('hello.o produced', !!obj && obj.length > 0, obj ? `${obj.length} bytes` : 'none');
if (obj) writeFileSync(join(OUT, 'hello.o'), obj);

// ============================================================ 2. link
console.log(`\n== [2] lld.wasm (wasm-ld): link ==  (${LLD_BIN}/${LLD_JS})`);
const createLld = require(join(LLD_BIN, LLD_JS));
const lldErr = [];
const lld = await createLld({ print: (x) => lldErr.push(x), printErr: (x) => lldErr.push(x), noInitialRun: true, thisProgram: 'wasm-ld' });
const staged2 = stageSysroot(lld.FS);
console.log(`   staged ${staged2} sysroot files`);
// each module has its own FS instance; /src must exist here too
lld.FS.mkdirTree('/src');
lld.FS.writeFile('/src/hello.o', obj);

// SPEC 4.2 verbatim, minus the flags LLVM 24 removed.
const linkArgv = [
  '-mwasm32', '-o', '/src/minifn.so', '--strip-debug',
  '--export=__wasm_call_ctors', '--export=_emscripten_tls_init',
  '--export-dynamic', '--unresolved-symbols=import-dynamic',
  '-shared', '--shared-memory', '--no-stack-first',
  '/sysroot/lib/wasm32-emscripten/pic/crtbegin-mt.o', '/src/hello.o',
  '-L/sysroot/lib/wasm32-emscripten/pic',
  '-mllvm', '-exception-model=wasm',
];
console.log(`   argv: ${linkArgv.join(' ')}`);
const rc2 = lld.callMain(linkArgv);
if (rc2 !== 0) console.log('   wasm-ld said:\n' + lldErr.map((l) => '     ' + l).join('\n'));
check('wasm-ld exits 0', rc2 === 0, `rc=${rc2}`);
let so = null;
try { so = lld.FS.readFile('/src/minifn.so'); } catch {}
check('minifn.so produced', !!so && so.length > 0, so ? `${so.length} bytes` : 'none');

// ============================================================ 3. ABI check
if (so) {
  writeFileSync(join(OUT, 'minifn.so'), so);
  console.log('\n== [3] side-module ABI check ==');
  const m = new WebAssembly.Module(so);
  const exports = WebAssembly.Module.exports(m).map((e) => e.name);
  const imports = WebAssembly.Module.imports(m);
  const envImports = imports.filter((i) => i.module === 'env').map((i) => i.name);
  check('exports minifn', exports.includes('minifn'), exports.join(','));
  check('exports __wasm_call_ctors', exports.includes('__wasm_call_ctors'));
  check('exports _emscripten_tls_init', exports.includes('_emscripten_tls_init'));
  check('imports env.memory (side module shape)', envImports.includes('memory'));
  check('imports __memory_base / __table_base (relocatable)',
        envImports.includes('__memory_base') && envImports.includes('__table_base'));
  // NOT every side module has GOT entries: they appear only when the code takes
  // the address of a symbol that lives in another module. The minimal fixture
  // (one std::string, no host calls) legitimately has none -- M0's fixture,
  // which calls a host function, has 12. So report rather than assert.
  const got = imports.filter((i) => i.module.startsWith('GOT.')).length;
  console.log(`   GOT imports: ${got} (0 is legitimate for a fixture with no cross-module symbol addresses)`);
  const dylink = /dylink/.test(Buffer.from(so).toString('latin1'));
  check('binary carries the dylink section name', dylink);
  console.log(`   exports: ${exports.join(', ')}`);
  console.log(`   env imports: ${envImports.length}`);
}

// --------------------------------------------------- machine-readable summary
// Same convention as the M0 runners: facts.py greps these, so the numbers have
// one producer and no doc hand-copies them.
console.log('-- artifacts');
console.log(`ARTIFACT m1_acceptance_pass ${passCount}`);
if (so) console.log(`ARTIFACT m1_sidemodule_bytes ${so.length}`);

console.log(`\n=== ${fails === 0 ? 'ALL PASS' : fails + ' FAILED'} ===`);
process.exitCode = fails === 0 ? 0 : 1;
