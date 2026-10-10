// M1 acceptance — drive the in-wasm clang through a *memory* filesystem.
//
// SPEC §7.2: "文件系统：emscripten 内存 FS（或 wasmfs）；源码/头/产物都在 FS 内流转".
// So the acceptance harness does exactly that: writes source + the needed
// sysroot subtrees into the module's FS, runs clang there, reads the product
// back out. The browser path is the same calls -- only where the bytes come
// from differs (a download instead of a local directory).
//
// This proves SPEC §10 M1 ("浏览器里编出 §9.1 的产物") for the compile step,
// without a browser.
//
// Usage: node m1/acceptance.mjs [--sysroot <dir>]
import { readFileSync, existsSync, readdirSync, statSync, mkdirSync, writeFileSync } from 'fs';
import { join, dirname, relative } from 'path';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const ROOT = dirname(new URL(import.meta.url).pathname);
const BIN = join(ROOT, 'build-clang', 'bin');
const SR = process.argv.includes('--sysroot')
  ? process.argv[process.argv.indexOf('--sysroot') + 1]
  : join(ROOT, '..', 'toolchain/emsdk/upstream/emscripten/cache/sysroot');

const CLANG_JS = join(BIN, 'clang.js');
if (!existsSync(CLANG_JS)) { console.error(`FATAL: ${CLANG_JS} missing`); process.exit(2); }

// ---------------------------------------------------------------- the fixture
const SOURCE = `#include <string>
extern "C" __attribute__((visibility("default"))) int minifn(int x) {
  std::string s = "abc";
  return x + (int)s.size();
}
`;

// ------------------------------------------------------------ fs staging plan
// Only the subtrees a C++ compile actually needs (SPEC §6: do not ship all of
// lib/). Mirrors the include search order emcc itself uses.
const STAGE = [
  'include/c++/v1',
  'include/compat',
  'include/fakesdl',
];

function stageTree(fs, hostPath, fsPath) {
  let n = 0;
  const walk = (src, dst) => {
    for (const e of readdirSync(src, { withFileTypes: true })) {
      const s = join(src, e.name), d = join(dst, e.name);
      if (e.isDirectory()) { fs.mkdirTree(d); walk(s, d); }
      else if (e.isFile()) { fs.writeFile(d, readFileSync(s)); n++; }
    }
  };
  fs.mkdirTree(fsPath);
  walk(hostPath, fsPath);
  return n;
}

// ------------------------------------------------------------------ the run
const ModuleFactory = require(CLANG_JS);
const mod = await ModuleFactory({
  // Keep clang quiet-ish; it is very chatty otherwise.
  print: (s) => process.stdout.write(s + '\n'),
  printErr: (s) => process.stderr.write(s + '\n'),
  noInitialRun: true,
  // clang's own argv; -cc1 is not needed here, the driver works.
  arguments: [],
});

const FS = mod.FS;
console.log(`clang.js loaded; FS ${FS ? 'available' : 'MISSING'}`);

FS.mkdirTree('/src');
FS.writeFile('/src/hello.cc', SOURCE);
let staged = 0;
for (const rel of STAGE) {
  const host = join(SR, rel);
  if (!existsSync(host)) { console.log(`   (skip, absent in this sysroot: ${rel})`); continue; }
  staged += stageTree(FS, host, `/sysroot/${rel}`);
}
// the C headers live at the sysroot root
staged += stageTree(FS, join(SR, 'include'), '/sysroot/include') - staged > 0 ? 0 : 0;
console.log(`staged ${staged} header files into the in-memory FS`);

const argv = [
  '--target=wasm32-unknown-emscripten',
  '--sysroot=/sysroot',
  '-isystem', '/sysroot/include/compat',
  '-fvisibility=default', '-fPIC', '-O1', '-fwasm-exceptions', '-pthread',
  '-c', '/src/hello.cc', '-o', '/src/hello.o',
];
console.log(`\n== running in-wasm clang: ${argv.join(' ')}`);
const rc = mod.callMain(argv);
console.log(`clang rc=${rc}`);

if (rc === 0 && existsSyncSafe(FS, '/src/hello.o')) {
  const obj = FS.readFile('/src/hello.o');
  console.log(`PASS: produced hello.o, ${obj.length} bytes`);
  writeFileSync(join(ROOT, 'acceptance', 'hello.o'), obj);
} else {
  console.log('FAIL: no object produced');
  process.exitCode = 1;
}

function existsSyncSafe(fs, p) {
  try { fs.stat(p); return true; } catch { return false; }
}
