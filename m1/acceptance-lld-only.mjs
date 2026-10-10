// M1 验收（只查 lld 那一半）——给「换掉 lld 实现」的实验用。
//
// 为什么不复用 acceptance-full.mjs：那个脚本要先编译（clang 那步慢），而本脚本
// 要回答的问题只是「裁过的 lld 还能不能把同一个 hello.o 链成 ABI 正确的 side
// module」。输入固定用 m1/acceptance/hello.o，所以 lld 是唯一变量。
//
// 用法:
//   node m1/acceptance-lld-only.mjs                      # 基线 lld
//   M1_LLD_BIN=m1/build-lld/bin M1_LLD_JS=lld-wasm-only.js node m1/acceptance-lld-only.mjs
import { readFileSync, existsSync, readdirSync, writeFileSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const ROOT = dirname(new URL(import.meta.url).pathname);
const LLD_BIN = process.env.M1_LLD_BIN
  ? (process.env.M1_LLD_BIN.startsWith('/') ? process.env.M1_LLD_BIN : join(ROOT, '..', process.env.M1_LLD_BIN))
  : join(ROOT, 'build-lld', 'bin');
const LLD_JS = process.env.M1_LLD_JS || 'lld.js';
const SR = join(ROOT, '..', 'toolchain/emsdk/upstream/emscripten/cache/sysroot');
const OUT = join(ROOT, 'acceptance');

let fails = 0, passCount = 0;
const check = (what, ok, detail = '') => {
  if (ok) passCount++; else fails++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${what}${detail ? ': ' + detail : ''}`);
};

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

const OBJ = join(OUT, 'hello.o');
if (!existsSync(OBJ)) {
  console.error(`FATAL: ${OBJ} missing — run node m1/acceptance-full.mjs once first`);
  process.exit(2);
}
mkdirSync(OUT, { recursive: true });

console.log(`== lld-only acceptance: ${LLD_BIN}/${LLD_JS} ==`);
const createLld = require(join(LLD_BIN, LLD_JS));
const lldErr = [];
const lld = await createLld({ print: (x) => lldErr.push(x), printErr: (x) => lldErr.push(x),
                              noInitialRun: true, thisProgram: 'wasm-ld' });
stageTree(lld.FS, join(SR, 'include'), '/sysroot/include');
const pic = join(SR, 'lib/wasm32-emscripten/pic');
if (existsSync(pic)) stageTree(lld.FS, pic, '/sysroot/lib/wasm32-emscripten/pic');
lld.FS.mkdirTree('/src');
lld.FS.writeFile('/src/hello.o', readFileSync(OBJ));

const linkArgv = [
  '-mwasm32', '-o', '/src/minifn.so', '--strip-debug',
  '--export=__wasm_call_ctors', '--export=_emscripten_tls_init',
  '--export-dynamic', '--unresolved-symbols=import-dynamic',
  '-shared', '--shared-memory', '--no-stack-first',
  '/sysroot/lib/wasm32-emscripten/pic/crtbegin-mt.o', '/src/hello.o',
  '-L/sysroot/lib/wasm32-emscripten/pic',
  '-mllvm', '-exception-model=wasm',
];
const rc = lld.callMain(linkArgv);
if (rc !== 0) console.log('   wasm-ld said:\n' + lldErr.map((l) => '     ' + l).join('\n'));
check('wasm-ld exits 0', rc === 0, `rc=${rc}`);
let so = null;
try { so = lld.FS.readFile('/src/minifn.so'); } catch {}
check('minifn.so produced', !!so && so.length > 0, so ? `${so.length} bytes` : 'none');
if (so) {
  const tag = process.env.M1_TAG || 'lldonly';
  writeFileSync(join(OUT, `minifn-${tag}.so`), so);
  const m = new WebAssembly.Module(so);
  const exports = WebAssembly.Module.exports(m).map((e) => e.name);
  const envImports = WebAssembly.Module.imports(m).filter((i) => i.module === 'env').map((i) => i.name);
  check('exports minifn', exports.includes('minifn'), exports.join(','));
  check('exports __wasm_call_ctors', exports.includes('__wasm_call_ctors'));
  check('exports _emscripten_tls_init', exports.includes('_emscripten_tls_init'));
  check('imports env.memory (side module shape)', envImports.includes('memory'));
  check('imports __memory_base / __table_base (relocatable)',
        envImports.includes('__memory_base') && envImports.includes('__table_base'));
  check('binary carries the dylink section name', /dylink/.test(Buffer.from(so).toString('latin1')));
  console.log(`ARTIFACT m1_lldonly_sidemodule_bytes ${so.length}`);
}
console.log(`ARTIFACT m1_lldonly_acceptance_pass ${passCount}`);
console.log(`\n=== ${fails === 0 ? 'ALL PASS' : fails + ' FAILED'} ===`);
process.exitCode = fails === 0 ? 0 : 1;
