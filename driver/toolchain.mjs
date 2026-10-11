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
import {
  EXCEPTION_MODES, compileFlagsFor, linkFlagsFor, REMOVED_LLVM24,
  symbolGap, compileArgv, linkArgv,
} from './abi.mjs';
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
  async _stageSysroot(fs, arch = 'wasm32') {
    if (this.bundle) {
      const files = this._bundle();
      // The tar is rooted at "sysroot/...", so install straight into /sysroot.
      // It carries include/ (arch-shared) plus lib/<arch>-emscripten/pic.
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
    if (this.bundle) return this._bundle().has(rel);
    return existsSync(join(this.sysroot, `lib/${arch}-emscripten/pic/crtbegin-mt.o`));
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
    if (target !== 'wasm32' && target !== 'wasm64') {
      return { ok: false, error: `target must be wasm32 or wasm64, got ${target}`, diagnostics };
    }
    // A compiler is multi-target: the SAME clang.wasm emits wasm64 objects when
    // asked (measured: the object's memory is i64, not silently i32). Same for
    // wasm-ld, which takes -mwasm64. So "two arches" costs one toolchain, not
    // two -- what differs per arch is the sysroot's pic/ subtree.
    const triple = `${target}-unknown-emscripten`;
    const archLib = `/sysroot/lib/${target}-emscripten/pic`;
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
      `--target=${triple}`,
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
    this._arch = target;
    const lld = await this.lld();
    await this._stageSysroot(lld.FS, this._arch || 'wasm32');
    lld.FS.mkdirTree('/out');
    lld.FS.writeFile('/out/tu.o', obj);

    const crt = `${archLib}/crtbegin-mt.o`;
    const cmd = linkArgv({ target, abi, hasCrt: this._hasCrt(target), objPath: '/out/tu.o' });
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
