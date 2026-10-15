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
import { compileWith } from './compile-core.mjs';
import { symbolGap, EXCEPTION_MODES } from './abi.mjs';
export { symbolGap, EXCEPTION_MODES };
import { join, dirname } from 'path';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);

// ABI 拼装与缺口判定来自 driver/abi.mjs（与浏览器 worker 共用的唯一产地）。
// symbolGap 在 driver/abi.mjs（单一产地），这里 re-export 供旧调用方。
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
  }

  _log(...a) { if (!this.quiet) console.log(...a); }

  /**
   * Unpack the delivered sysroot bundle, verifying sha256 first (SPEC §9.10).
   * Throws on mismatch — a tampered asset must not load.
   */
  /**
   * Unpack one arch's sysroot bundle, verifying sha256 first (SPEC §9.10).
   *
   * Two shapes are accepted:
   *   { tarPath, manifestPath }              -- one tar, used for every target
   *   { tars: { wasm32: {...}, wasm64: {...} } }  -- per-arch tars, selected here
   *
   * The per-arch form exists because a wasm32 sysroot cannot link a wasm64
   * module: it has no lib/wasm64-emscripten/pic/crtbegin-mt.o, so the module
   * ends up without _emscripten_tls_init and a threaded host refuses it with
   * "tlsInitFunc is not a function" (issue #1). Selecting by target is the
   * driver's job so callers never have to know which tar they need.
   */
  _bundle(arch = 'wasm32') {
    this._bundleCache ||= new Map();
    if (this._bundleCache.has(arch)) return this._bundleCache.get(arch);
    if (!this.bundle) { this._bundleCache.set(arch, null); return null; }
    const spec = this.bundle.tars ? this.bundle.tars[arch] : this.bundle;
    if (!spec) { this._bundleCache.set(arch, null); return null; }
    const r = loadBundle({
      tarPath: spec.tarPath,
      manifestPath: spec.manifestPath,
      expectSha256: spec.expectSha256,
    });
    this._log(`[bundle:${arch}] verified sha256 ${r.sha256.slice(0, 16)}…, ${r.files.size} files, ${r.bytes} bytes`);
    this._bundleCache.set(arch, r.files);
    return r.files;
  }

  /** Stage the sysroot into a module's FS, from whichever source was configured. */
  async _stageSysroot(fs, arch = 'wasm32') {
    if (this.bundle) {
      // Prefer this arch's tar. If it is absent, fall back to any tar we do
      // have: include/ is arch-shared, so headers still stage and the refusal
      // (not a confusing link error) is what the caller sees.
      const files = this._bundle(arch) || this._bundle('wasm32')
        || (this.bundle.tars ? this._bundle(Object.keys(this.bundle.tars)[0]) : null);
      if (!files) throw new Error(`no sysroot bundle available for ${arch}`);
      const n = installBundle(fs, files, '');
      this._log(`[bundle] installed ${n} files into the memory FS`);
      return n;
    }
    const { stage } = await this._fs();
    let n = stage(fs, join(this.sysroot, 'include'), '/sysroot/include');
    n += stage(fs, join(this.sysroot, `lib/${arch}-emscripten/pic`),
               `/sysroot/lib/${arch}-emscripten/pic`);
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

  _hasCrt(arch = 'wasm32') {
    const rel = `sysroot/lib/${arch}-emscripten/pic/crtbegin-mt.o`;
    if (this.bundle) {
      const files = this._bundle(arch);
      // No tar for this arch at all, or one that lacks the crt: either way the
      // target cannot be linked properly. compile() turns this into a refusal.
      if (!files) return false;
      return files.has(rel);
    }
    return existsSync(join(this.sysroot, `lib/${arch}-emscripten/pic/crtbegin-mt.o`));
  }

  /** Which targets this Toolchain can actually link, given its sysroot source. */
  targetsAvailable() {
    return ['wasm32', 'wasm64'].filter((t) => this._hasCrt(t));
  }

  async clang() {
    if (this._clang) return this._clang;
    const factory = require(join(this.clangBin, this.clangJs));
    this._clang = await factory({
      print: () => {}, printErr: () => {}, noInitialRun: true,
    });
    // clang only reads headers; the arch-specific bit is pic/, which it never
    // touches. Stage headers once (from include/), which the bundle shares.
    await this._stageSysroot(this._clang.FS, 'wasm32');
    return this._clang;
  }

  async lld(arch = 'wasm32') {
    // A FRESH instance every call. Reusing one makes the second compile fail
    // with "wasm-ld (LLVM option parsing): Unknown command line argument
    // '-exception-model=wasm'" even for an identical argv: emscripten's lld
    // latches its feature set when it first parses -mllvm (measured in the
    // browser, and reproduced here with wasm32 then wasm64 on one instance).
    // The cached module is therefore never returned; keeping the factory warm
    // is what the require() cache already does.
    const factory = require(join(this.lldBin, this.lldJs));
    const errs = [];
    const mod = await factory({
      print: () => {}, printErr: (s2) => errs.push(String(s2).slice(0, 300)),
      noInitialRun: true,
      // lld is a generic driver; it dispatches on argv[0]. Without this it
      // prints "lld is a generic driver" and exits 1 (measured).
      thisProgram: 'wasm-ld',
    });
    mod.collected = errs;   // link failures report WHY, not just an exit code
    // Contract of this method (compile-core relies on it): the returned
    // instance already has the sysroot for the CURRENT target staged. A fresh
    // instance starts empty, so this is not optional -- omitting it makes every
    // link fail on a missing crt.
    await this._stageSysroot(mod.FS, arch);
    return mod;
  }

  /**
   * Compile + link one translation unit into an Emscripten side module.
   *
   * @param {object} req  see SPEC §7.4
   * @returns {Promise<{ok, moduleBytes?, error?, diagnostics, symbolGap?}>}
   */
  /**
   * Thin adapter over driver/compile-core.mjs (see that file for why the
   * pipeline is shared). This class supplies only what genuinely differs here:
   * a sysroot from a bundle or a host directory, and module instances obtained
   * via require().
   */
  async compile(req) {
    return compileWith({
      targetsAvailable: () => this.targetsAvailable(),
      clang: async () => {
        const m = await this.clang();
        m.collected = m.collected || [];
        return m;
      },
      lld: async (arch) => this.lld(arch),
      log: (t) => this._log(t),
    }, { ...req, hostBytes: this._hostBytes(req) });
  }

  _hostBytes(req) {
    if (req.hostBytes) return req.hostBytes;
    if (req.hostWasm) return readFileSync(req.hostWasm);
    return null;
  }}
