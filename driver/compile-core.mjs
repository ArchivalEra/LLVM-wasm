// The compile pipeline, once — the part that does NOT vary between the node
// driver and the browser worker.
//
// Why this module exists (codebase-design): two adapters implement compile()
// today, node (driver/toolchain.mjs) and browser (browser/worker.mjs), and they
// had already drifted — issue #1's guard ("refuse when the sysroot cannot serve
// the target") went into the node adapter and never reached the browser one, so
// a browser build against a wasm32-only sysroot still returned ok:true with a
// module missing _emscripten_tls_init. Same failure the issue was about, in the
// same browser path, one layer down. Sharing only the flag assembly (abi.mjs)
// was not enough: what drifted was the ORCHESTRATION.
//
// So this module owns: the precheck, the step order, the argv assembly, the
// per-compile lld lifecycle, and the gap check. The adapters own only what
// genuinely differs — where the sysroot comes from, how a module instance is
// obtained, and where the bytes go.
//
// Interface (deliberately four members; the runtime is injected, not created):
//
//   runtime.targetsAvailable(): string[]     which arches the sysroot serves
//   runtime.clang(): Promise<{FS, callMain}> clang, sysroot staged
//   runtime.lld(target): Promise<{FS, callMain}> a FRESH lld each call, with the
//                        sysroot for `target` already staged
//   runtime.log?(text)                       optional narration
//
// Everything else is implementation. Callers get a plain result object; this
// module performs no I/O of its own beyond what the runtime hands it.
import { compileArgv, linkArgv, symbolGap, EXCEPTION_MODES } from './abi.mjs';

const SOURCE_NAME = 'input.cc';
const OBJ = '/out/tu.o';
const MODULE = '/out/module.so';

/**
 * Compile one translation unit into an Emscripten side module.
 *
 * @param {object} runtime  see the interface above
 * @param {object} req      { source | files, target, abi, define, include, flags,
 *                            hostBytes }
 * @returns {Promise<{ok, moduleBytes?, error?, detail?, diagnostics, symbolGap?, stage?}>}
 */
export async function compileWith(runtime, req) {
  const diagnostics = [];
  const log = runtime.log || (() => {});

  // ---------------------------------------------------------------- validate
  const abi = { exceptions: 'wasm-legacy', pthread: true, memory64: false, ...(req.abi || {}) };
  if (!EXCEPTION_MODES.includes(abi.exceptions)) {
    return { ok: false, stage: 'validate',
             error: `abi.exceptions must be one of ${EXCEPTION_MODES.join('|')}, got ${abi.exceptions}`,
             diagnostics };
  }
  const target = req.target || 'wasm32';
  if (target !== 'wasm32' && target !== 'wasm64') {
    return { ok: false, stage: 'validate',
             error: `target must be wasm32 or wasm64, got ${target}`, diagnostics };
  }
  const files = req.files || (req.source ? { [SOURCE_NAME]: req.source } : null);
  if (!files || Object.keys(files).length === 0) {
    return { ok: false, stage: 'validate', error: 'compile() needs source or files', diagnostics };
  }

  // The precheck, in the ONE place both adapters pass through. Doing it after
  // the work is what let a TLS-less module out: linkArgv drops the crt when
  // hasCrt is false, so the product links "fine" and the host refuses it later.
  const available = runtime.targetsAvailable();
  if (!available.includes(target)) {
    return { ok: false, stage: 'precheck', diagnostics,
             error: `sysroot for ${target} is missing in this toolchain's sysroot source `
                  + `(available: ${available.join(', ') || 'none'}). Refusing rather than `
                  + `linking a module without the TLS init entry.` };
  }
  const triple = `${target}-unknown-emscripten`;

  // ----------------------------------------------------------------- compile
  const clang = await runtime.clang();
  clang.FS.mkdirTree('/src');
  clang.FS.mkdirTree('/out');
  for (const [name, text] of Object.entries(files)) clang.FS.writeFile(`/src/${name}`, text);

  const cc1 = compileArgv({
    triple, files: Object.keys(files)[0], abi,
    defines: req.define || [], includes: req.include || [], extra: req.flags || [],
  });
  log(`clang ${cc1.join(' ')}`);
  const rcC = clang.callMain(cc1);
  if (rcC !== 0) {
    return { ok: false, stage: 'compile', error: `clang exited ${rcC}`,
             detail: (clang.collected || []).slice(-8), diagnostics };
  }
  let obj;
  try { obj = clang.FS.readFile(OBJ); } catch { obj = null; }
  if (!obj || obj.length === 0) {
    return { ok: false, stage: 'compile', error: 'clang produced no object', diagnostics };
  }

  // -------------------------------------------------------------------- link
  // A FRESH lld every compile: emscripten's lld latches its feature set when it
  // first parses -mllvm, so a second callMain on one instance rejects an
  // identical argv (measured in both adapters).
  const lld = await runtime.lld(target);
  lld.FS.mkdirTree('/out');
  lld.FS.writeFile(OBJ, obj);

  const cmd = linkArgv({ target, abi, hasCrt: true, objPath: OBJ });
  log(`wasm-ld ${cmd.join(' ')}`);
  const rcL = lld.callMain(cmd);
  if (rcL !== 0) {
    return { ok: false, stage: 'link', error: `wasm-ld exited ${rcL}`,
             detail: (lld.collected || []).slice(-8), diagnostics };
  }
  let so;
  try { so = lld.FS.readFile(MODULE); } catch { so = null; }
  if (!so || so.length === 0) {
    return { ok: false, stage: 'link', error: 'wasm-ld produced no module', diagnostics };
  }

  // ------------------------------------------------------------- §5.4 gap
  const gap = symbolGap(so, req.hostBytes || null);
  return { ok: true, moduleBytes: so, diagnostics, symbolGap: gap, abi, target };
}

export { symbolGap, EXCEPTION_MODES };
