// Thin driver — SPEC §7.4/§7.5. Turns "source → side module" into one call.
//
// SPEC §7.5 says: write a thin driver that assembles the §4.1/§4.2 command
// lines yourself; do NOT port the clang driver or emcc.py, because their whole
// job (guess flags, spawn subprocesses) is unavailable in a browser.
//
// What this module owns:
//   · the §4.1 compile line and the §4.2 link line, with the flags that LLVM 24
//     removed already dropped and the ones that drift exposed as parameters;
//   · a memory filesystem (SPEC §7.2) — source, sysroot and products all live
//     inside the wasm instance, so the browser path needs no host files;
//   · the §5.4 gap check (subtract the side's own exports, list tags apart),
//     because "links fine, fails at first call" is the failure mode the spec
//     keeps warning about;
//   · §4.5: the ABI is a parameter, never a built-in flag table.
//
// It does NOT own: fetching assets, sha256 verification, the Worker boundary
// (SPEC §7.3) or packaging. Callers supply those.
import { readFileSync, existsSync, readdirSync } from 'fs';
import { loadBundle, installBundle } from './sysroot-bundle.mjs';
import { join, dirname } from 'path';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);

// ---------------------------------------------------------------- ABI contract
// SPEC §4.5: four axes, all from the caller. The toolchain must not guess.
export const EXCEPTION_MODES = Object.freeze([
  'none',            // no exception support at all
  'emscripten',      // JS-emulated exceptions (-sDISABLE_EXCEPTION_CATCHING=0)
  'wasm-legacy',     // -fwasm-exceptions with WASM_LEGACY_EXCEPTIONS (6.x default)
  'wasm-standard',   // -fwasm-exceptions with WASM_LEGACY_EXCEPTIONS=0
]);

function compileFlagsFor(abi) {
  // Compile-side flags only. `-s` settings are emcc's, not clang's: handing a
  // bare clang `-sWASM_LEGACY_EXCEPTIONS=1` makes it exit 1 with no useful
  // message (measured). The exception mode is a *codegen* choice here
  // (-fwasm-exceptions or not); which wasm EH flavour the linker pairs it with
  // is decided in linkFlagsFor().
  const f = [];
  switch (abi.exceptions) {
    case 'none': f.push('-fno-exceptions'); break;
    case 'emscripten': break;              // emulated EH needs no codegen flag
    case 'wasm-legacy':
    case 'wasm-standard': f.push('-fwasm-exceptions'); break;
    default: throw new Error(`unknown abi.exceptions: ${abi.exceptions}`);
  }
  if (abi.pthread) f.push('-pthread');
  return f;
}

function linkFlagsFor(abi) {
  const f = [];
  if (abi.pthread) f.push('--shared-memory');
  // The tag name follows the exception mode; see §5.5.
  if (abi.exceptions === 'wasm-legacy' || abi.exceptions === 'wasm-standard') {
    f.push('-mllvm', '-exception-model=wasm');
  }
  return f;
}

// The flags LLVM 24 no longer accepts. Kept as data, not scattered conditionals,
// so a version probe can extend it (SPEC §4.2's flag table).
const REMOVED_LLVM24 = new Set(['-wasm-enable-eh']);

// ------------------------------------------------------------ symbol gap (5.4)
const MECHANICAL = new Set([
  'memory', '__indirect_function_table', '__stack_pointer', '__memory_base',
  '__table_base', '__stack_high', '__heap_base', '__cpp_exception',
  '__c_longjmp', '__wasm_apply_data_relocs', '__dso_handle', '__tls_size',
  '__tls_align', '__set_stack_limits', '_emscripten_tls_init',
  '__wasm_init_tls', '__wasm_call_ctors',
]);

/**
 * SPEC §5.4: which symbols does this side module need that the host lacks?
 *
 * The side's own exports are subtracted because `--export-dynamic` makes a side
 * module both import and export the same symbol (GOT self-reference), and
 * emscripten's resolveSymbol consults moduleExports. Skipping that subtraction
 * reports false gaps (measured: 2 vs 1 on the spec's own fixture).
 *
 * Returns bare data; printing is the caller's business.
 */
export function symbolGap(sideBytes, hostBytes) {
  const side = new WebAssembly.Module(sideBytes);
  const imports = WebAssembly.Module.imports(side);
  const sideExports = new Set(WebAssembly.Module.exports(side).map((e) => e.name));

  const need = [...new Set(imports
    .filter((i) => i.module === 'env' || i.module.startsWith('GOT.'))
    .map((i) => i.name))]
    .filter((n) => !MECHANICAL.has(n) && !sideExports.has(n));

  const sideTags = imports.filter((i) => i.kind === 'tag').map((i) => i.name);

  if (!hostBytes) {
    // No host given: we can still say what the module needs, but not what is
    // missing. Saying "0 missing" here would be the zero-value lie.
    return {
      ok: true,
      hostChecked: false,
      needs: need.length,
      needsTags: sideTags.length,
      missingFunctions: [],
      missingTags: [],
      sideSelfExported: [...sideExports].filter((n) => imports.some((i) => i.name === n)),
    };
  }

  const host = new WebAssembly.Module(hostBytes);
  const hostExports = new Set(WebAssembly.Module.exports(host).map((e) => e.name));
  const hostTags = new Set(WebAssembly.Module.exports(host)
    .filter((e) => e.kind === 'tag').map((e) => e.name));

  return {
    ok: true,
    hostChecked: true,
    needs: need.length,
    needsTags: sideTags.length,
    missingFunctions: need.filter((n) => !hostExports.has(n)),
    missingTags: sideTags.filter((n) => !hostTags.has(n)),
    sideSelfExported: [...sideExports].filter((n) => imports.some((i) => i.name === n)),
  };
}

// ------------------------------------------------------------------ the driver
export class Toolchain {
  /**
   * @param {object} opts
   * @param {string} opts.clangBin  directory holding clang.js + clang.wasm
   * @param {string} opts.lldBin    directory holding lld.js + lld.wasm
   * @param {string} [opts.clangJs] clang glue filename
   * @param {string} [opts.lldJs]   lld glue filename (e.g. 'lld-wasm-only.js')
   * @param {string} opts.sysroot   host directory of the emscripten sysroot
   * @param {boolean} [opts.quiet]
   */
  constructor(opts) {
    this.clangBin = opts.clangBin;
    this.lldBin = opts.lldBin;
    this.clangJs = opts.clangJs || 'clang.js';
    this.lldJs = opts.lldJs || 'lld.js';
    this.sysroot = opts.sysroot;             // dev path: an emsdk sysroot dir
    this.bundle = opts.bundle || null;       // delivery path: {tarPath, manifestPath}
    if (!this.sysroot && !this.bundle) {
      throw new Error('Toolchain needs either sysroot (directory) or bundle ({tarPath, manifestPath})');
    }
    this._bundleFiles = null;
    this.quiet = !!opts.quiet;
    this._clang = null;
    this._lld = null;
  }

  _log(...a) { if (!this.quiet) console.log(...a); }

  /**
   * Unpack the delivered sysroot bundle, verifying sha256 first (SPEC §9.10).
   * Throws on mismatch — a tampered asset must not load.
   */
  _bundle() {
    if (this._bundleFiles) return this._bundleFiles;
    if (!this.bundle) return null;
    const r = loadBundle({
      tarPath: this.bundle.tarPath,
      manifestPath: this.bundle.manifestPath,
      expectSha256: this.bundle.expectSha256,
    });
    this._log(`[bundle] verified sha256 ${r.sha256.slice(0, 16)}…, ${r.files.size} files, ${r.bytes} bytes`);
    this._bundleFiles = r.files;
    return r.files;
  }

  /** Stage the sysroot into a module's FS, from whichever source was configured. */
  _stageSysroot(fs) {
    if (this.bundle) {
      const files = this._bundle();
      // The tar is rooted at "sysroot/...", so install straight into /sysroot.
      const n = installBundle(fs, files, '');
      this._log(`[bundle] installed ${n} files into the memory FS`);
      return n;
    }
    const { stage } = this._fs();
    let n = stage(fs, join(this.sysroot, 'include'), '/sysroot/include');
    n += stage(fs, join(this.sysroot, 'lib/wasm32-emscripten/pic'),
               '/sysroot/lib/wasm32-emscripten/pic');
    return n;
  }

  async _fs() {
    // Stage only what §4.1/§4.2 actually read (SPEC §6: never ship all of lib/).
    const staged = [];
    const stage = (fs, hostPath, fsPath) => {
      if (!existsSync(hostPath)) return 0;
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
      staged.push(`${fsPath} (${n})`);
      return n;
    };
    return { stage, staged };
  }

  _hasCrt() {
    if (this.bundle) {
      return this._bundle().has('sysroot/lib/wasm32-emscripten/pic/crtbegin-mt.o');
    }
    return existsSync(join(this.sysroot, 'lib/wasm32-emscripten/pic/crtbegin-mt.o'));
  }

  async clang() {
    if (this._clang) return this._clang;
    const factory = require(join(this.clangBin, this.clangJs));
    this._clang = await factory({
      print: () => {}, printErr: () => {}, noInitialRun: true,
    });
    this._stageSysroot(this._clang.FS);
    return this._clang;
  }

  async lld() {
    if (this._lld) return this._lld;
    const factory = require(join(this.lldBin, this.lldJs));
    this._lld = await factory({
      print: () => {}, printErr: () => {}, noInitialRun: true,
      // lld is a generic driver; it dispatches on argv[0]. Without this it
      // prints "lld is a generic driver" and exits 1 (measured).
      thisProgram: 'wasm-ld',
    });
    return this._lld;
  }

  /**
   * Compile + link one translation unit into an Emscripten side module.
   *
   * @param {object} req  see SPEC §7.4
   * @returns {Promise<{ok, moduleBytes?, error?, diagnostics, symbolGap?}>}
   */
  async compile(req) {
    const diagnostics = [];
    const abi = { exceptions: 'wasm-legacy', pthread: true, memory64: false, ...(req.abi || {}) };
    if (!EXCEPTION_MODES.includes(abi.exceptions)) {
      return { ok: false, error: `abi.exceptions must be one of ${EXCEPTION_MODES.join('|')}`, diagnostics };
    }
    const target = req.target || 'wasm32';
    if (target === 'wasm64') {
      // SPEC §4.5 requires both, but M1 built only the wasm32 sysroot. Refuse
      // loudly rather than silently producing a wasm32 module.
      return { ok: false, error: 'target wasm64 not built yet (M4); refusing rather than mislabelling', diagnostics };
    }
    const files = req.files || (req.source ? { 'input.cc': req.source } : null);
    if (!files || Object.keys(files).length === 0) {
      return { ok: false, error: 'compile() needs source or files', diagnostics };
    }

    const clang = await this.clang();
    const FS = clang.FS;
    FS.mkdirTree('/src');
    FS.mkdirTree('/out');
    for (const [name, text] of Object.entries(files)) {
      FS.writeFile(`/src/${name}`, text);
    }

    // ---- §4.1 compile
    const cc1 = [
      '--target=wasm32-unknown-emscripten',
      '--sysroot=/sysroot',
      '-isystem', '/sysroot/include/compat',
      '-fvisibility=default', '-fPIC', '-O2',
      ...compileFlagsFor(abi).filter((f) => !REMOVED_LLVM24.has(f)),
      ...(req.define || []).flatMap((d) => ['-D', d]),
      ...(req.include || []).flatMap((i) => ['-I', i]),
      ...(req.flags || []),
      '-c', `/src/${Object.keys(files)[0]}`, '-o', '/out/tu.o',
    ];
    this._log(`[compile] ${cc1.join(' ')}`);
    const rcC = clang.callMain(cc1);
    if (rcC !== 0) {
      return { ok: false, error: `clang exited ${rcC}`, diagnostics, stage: 'compile' };
    }
    let obj;
    try { obj = FS.readFile('/out/tu.o'); } catch { /* fall through */ }
    if (!obj || obj.length === 0) {
      return { ok: false, error: 'clang produced no object', diagnostics, stage: 'compile' };
    }

    // ---- §4.2 link
    const lld = await this.lld();
    this._stageSysroot(lld.FS);
    lld.FS.mkdirTree('/out');
    lld.FS.writeFile('/out/tu.o', obj);

    const crt = '/sysroot/lib/wasm32-emscripten/pic/crtbegin-mt.o';
    const cmd = [
      '-mwasm32', '-o', '/out/module.so', '--strip-debug',
      '--export=__wasm_call_ctors',
      '--export=_emscripten_tls_init',
      '--export-dynamic',
      '--unresolved-symbols=import-dynamic',
      '-shared', '--no-stack-first',
      ...linkFlagsFor(abi),
      ...(this._hasCrt() ? [crt] : []),
      '/out/tu.o',
      '-L/sysroot/lib/wasm32-emscripten/pic',
    ];
    this._log(`[link] ${cmd.join(' ')}`);
    const rcL = lld.callMain(cmd);
    if (rcL !== 0) {
      return { ok: false, error: `wasm-ld exited ${rcL}`, diagnostics, stage: 'link' };
    }
    let so;
    try { so = lld.FS.readFile('/out/module.so'); } catch { /* fall through */ }
    if (!so || so.length === 0) {
      return { ok: false, error: 'wasm-ld produced no module', diagnostics, stage: 'link' };
    }

    // ---- §5.4 gap check against whatever host surface the caller supplied
    let hostBytes;
    if (req.hostWasm) {
      hostBytes = Buffer.isBuffer(req.hostWasm) ? req.hostWasm : readFileSync(req.hostWasm);
    }
    const gap = symbolGap(so, hostBytes);

    return {
      ok: true,
      moduleBytes: Buffer.from(so),
      diagnostics,
      symbolGap: gap,
      abi,
      target,
    };
  }
}
