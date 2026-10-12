// Browser worker — SPEC §7.3: "放 Web Worker（编译是重活；且避开主线程
// >8 MB 同步编译限制）"。§9.8: 纯客户端，源码不出机器。
//
// This worker is the browser twin of driver/toolchain.mjs. The ABI assembly
// and the gap check come from driver/abi.mjs -- the single source both sides
// import, because two copies of the flag logic is exactly how they drift.
//
// Protocol (postMessage):
//   in:  { type: 'init',  clangWasmUrl, lldWasmUrl, sysrootTarUrl,
//          sysrootSha256, manifestBytes? }
//   in:  { type: 'compile', source, target, abi }
//   out: { type: 'ready' }
//   out: { type: 'result', ok, moduleBytes?, error?, gap? }
//   out: { type: 'log', text }
import { compileArgv, linkArgv, symbolGap } from '../driver/abi.mjs';
import { readTar } from '../driver/tar-reader.mjs';

let LLD_ARGS = null;   // remembered from init so compile() can respawn lld
let lastErr = [];   // clang/lld stderr, so a failed stage says why
let clangMod = null;
let lldMod = null;
let sysrootFiles = null;

const post = (m) => self.postMessage(m);
const log = (text) => post({ type: 'log', text });

async function sha256Hex(buf) {
  const d = await crypto.subtle.digest('SHA-256', buf);
  return [...new Uint8Array(d)].map((x) => x.toString(16).padStart(2, '0')).join('');
}

// ------------------------------------------------------------ asset loading
async function instantiate(glueUrl, wasmUrl, importObject) {
  // We fetch the glue text and re-export its factory explicitly. Why: the glue
  // is UMD — under `import()` there is no `module`/`exports`, so all three UMD
  // branches miss and the module has NO exports ("factory is not a function",
  // measured). Appending `export default createToolChain` works because the
  // factory is a top-level var in the module scope. The .wasm bytes are passed
  // in as wasmBinary so the worker controls fetching (and §9.8's request log
  // stays explicable).
  const glueText = await (await fetch(glueUrl)).text();
  const wasmBytes = await (await fetch(wasmUrl)).arrayBuffer();
  log(`  ${glueUrl.split('/').pop()}: glue ${glueText.length} B, wasm ${wasmBytes.byteLength} B`);
  const wrapped = `${glueText}\nexport default createToolChain;`;
  const blob = URL.createObjectURL(new Blob([wrapped], { type: 'text/javascript' }));
  const mod = await import(blob);
  const factory = mod.default;

  return factory({
    ...(importObject || {}),
    wasmBinary: wasmBytes,
    printErr: (s) => { lastErr.push(String(s).slice(0, 300)); },
    locateFile: () => wasmUrl,
    // We instantiate ourselves rather than letting the glue do it.
    //
    // Why: under `import()` in a browser the glue's own path fails with
    // `LinkError: Import #41 "a" "P": function import requires a callable`,
    // even though the import object it is handed is complete —
    // `typeof a.P === 'function'` at that very moment, and calling
    // WebAssembly.instantiate(wasm, info) with that same object succeeds twice
    // in a row (both measured). The glue string-compiles and consults
    // Module.instantiateWasm first, so taking that hook sidesteps whatever it
    // does differently, and the resulting module is identical.
    instantiateWasm: (info, receive) => {
      // ⚠️ `receive` wants the INSTANCE, not the {module, instance} pair that
      // WebAssembly.instantiate resolves to. Passing the pair makes the glue
      // set wasmExports = undefined, and the next export lookup dies with
      // "Cannot read properties of undefined (reading '_')" (measured).
      WebAssembly.instantiate(wasmBytes, info).then(
        (r) => receive(r.instance),
        (e) => { throw e; },
      );
      return {};                       // tell the glue we handled it
    },
    noInitialRun: true,
  });
}

function installFiles(fs, files) {
  let n = 0;
  for (const [rel, data] of files) {
    const dst = `/${rel}`;
    const dir = dst.slice(0, dst.lastIndexOf('/'));
    if (dir) fs.mkdirTree(dir);
    fs.writeFile(dst, data);
    n++;
  }
  return n;
}

async function init(msg) {
  log('loading sysroot bundle…');
  const tarBuf = new Uint8Array(await (await fetch(msg.sysrootTarUrl)).arrayBuffer());
  const got = await sha256Hex(tarBuf);
  if (msg.sysrootSha256 && got !== msg.sysrootSha256) {
    // SPEC §9.10: fail closed. A tampered asset must not load.
    throw new Error(`sysroot sha256 mismatch — refusing.\n  expected ${msg.sysrootSha256}\n  got      ${got}`);
  }
  sysrootFiles = readTar(tarBuf);
  log(`sysroot verified (${got.slice(0, 16)}…), ${sysrootFiles.size} files`);

  log('instantiating clang.wasm…');
  try {
    clangMod = await instantiate(msg.clangGlueUrl, msg.clangWasmUrl);
  } catch (e) {
    log('CLANG INSTANTIATE THREW: ' + String(e && e.message).slice(0, 200));
    throw e;
  }
  log('clang instantiated; installing sysroot…');
  installFiles(clangMod.FS, sysrootFiles);
  log('clang ready');

  log('instantiating lld.wasm…');
  LLD_ARGS = { glue: msg.lldGlueUrl, wasm: msg.lldWasmUrl };
  lldMod = await instantiate(msg.lldGlueUrl, msg.lldWasmUrl, { thisProgram: 'wasm-ld' });
  installFiles(lldMod.FS, sysrootFiles);
  log('lld ready');
}

// ------------------------------------------------------------------ compile
async function compile(msg) {
  const abi = { exceptions: 'wasm-legacy', pthread: true, ...(msg.abi || {}) };
  const target = msg.target || 'wasm32';
  const triple = `${target}-unknown-emscripten`;

  clangMod.FS.mkdirTree('/src');
  clangMod.FS.mkdirTree('/out');
  clangMod.FS.writeFile('/src/input.cc', msg.source);

  // §4.1 — from driver/abi.mjs (single source, same as the node driver)
  const cc1 = compileArgv({
    triple, files: 'input.cc', abi,
    defines: msg.define || [], includes: msg.include || [], extra: msg.flags || [],
  });
  log(`clang ${cc1.join(' ')}`);
  lastErr = [];
  const rcC = clangMod.callMain(cc1);
  if (rcC !== 0) return { ok: false, error: `clang exited ${rcC}`, detail: lastErr.slice(-8) };
  let obj;
  try { obj = clangMod.FS.readFile('/out/tu.o'); } catch { obj = null; }
  if (!obj || obj.length === 0) return { ok: false, error: 'no object produced' };

  // §4.2
  // A FRESH lld instance per compile. Reusing one is what produced
  // "Unknown command line argument '-exception-model=wasm'" on the second
  // compile: emscripten's lld latches its feature set when it first parses
  // -mllvm, so the same argv is accepted once and rejected afterwards.
  lldMod = await instantiate(LLD_ARGS.glue, LLD_ARGS.wasm, { thisProgram: 'wasm-ld' });
  installFiles(lldMod.FS, sysrootFiles);       // a fresh instance starts empty
  lldMod.FS.mkdirTree('/out');
  lldMod.FS.writeFile('/out/tu.o', obj);
  const cmd = linkArgv({
    target, abi,
    hasCrt: sysrootFiles.has(`sysroot/lib/${target}-emscripten/pic/crtbegin-mt.o`),
    objPath: '/out/tu.o',
  });
  log(`wasm-ld ${cmd.join(' ')}`);
  lastErr = [];
  const rcL = lldMod.callMain(cmd);
  if (rcL !== 0) return { ok: false, error: `wasm-ld exited ${rcL}`, detail: lastErr.slice(-8) };
  let so;
  try { so = lldMod.FS.readFile('/out/module.so'); } catch { so = null; }
  if (!so || so.length === 0) return { ok: false, error: 'no module produced' };

  // §5.4 — same function the node driver uses
  const gap = msg.hostWasmBytes ? symbolGap(so, msg.hostWasmBytes) : symbolGap(so, null);
  return { ok: true, moduleBytes: so, gap };
}

// ----------------------------------------------------------------- dispatch
self.onmessage = async (e) => {
  const msg = e.data;
  try {
    if (msg.type === 'init') {
      await init(msg);
      post({ type: 'ready' });
    } else if (msg.type === 'compile') {
      const r = await compile(msg);
      // moduleBytes is a Uint8Array — structured-cloneable, no base64 needed
      post({ type: 'result', ...r });
    }
  } catch (err) {
    post({ type: 'result', ok: false, error: String(err && err.message || err) });
  }
};
