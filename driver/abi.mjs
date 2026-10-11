// ABI 单一产地 —— node 驱动与浏览器 worker **共用**这一份。
//
// 为什么这个文件必须没有任何 node 依赖：浏览器 worker 里 import 不到 fs/require。
// 旗标拼装（§4.1/§4.2）与缺口判定（§5.4）是"两边各写一份必然漂移"的那类东西
// （SPEC §4.5 的原话），所以它们的唯一家在这里，双方都从这里 import。
//
// 本文件的输入输出都是纯数据（Uint8Array / 字符串 / 数组），不做任何 I/O。

// ---------------------------------------------------------------- ABI contract
// SPEC §4.5: four axes, all from the caller. The toolchain must not guess.
export const EXCEPTION_MODES = Object.freeze([
  'none',            // no exception support at all
  'emscripten',      // JS-emulated exceptions (-sDISABLE_EXCEPTION_CATCHING=0)
  'wasm-legacy',     // -fwasm-exceptions with WASM_LEGACY_EXCEPTIONS (6.x default)
  'wasm-standard',   // -fwasm-exceptions with WASM_LEGACY_EXCEPTIONS=0
]);

export const TARGETS = Object.freeze(['wasm32', 'wasm64']);

export function compileFlagsFor(abi) {
  // Compile-side flags only. `-s` settings are emcc's, not clang's: handing a
  // bare clang `-sWASM_LEGACY_EXCEPTIONS=1` makes it exit 1 with no useful
  // message (measured). The exception mode is a codegen choice here; which wasm
  // EH flavour the linker pairs it with is decided in linkFlagsFor().
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

export function linkFlagsFor(abi) {
  const f = [];
  if (abi.pthread) f.push('--shared-memory');
  if (abi.exceptions === 'wasm-legacy' || abi.exceptions === 'wasm-standard') {
    f.push('-mllvm', '-exception-model=wasm');
  }
  return f;
}

// The flags LLVM 24 no longer accepts (SPEC §4.2's flag table, data not ifs).
export const REMOVED_LLVM24 = new Set(['-wasm-enable-eh']);

// ---------------------------------------------------------------- §5.4 gap
export const MECHANICAL = new Set([
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
 * hostBytes may be null: the report then says hostChecked=false rather than
 * fabricating "no gaps" (zero-value rule).
 */
export function symbolGap(sideBytes, hostBytes) {
  const side = new WebAssembly.Module(toU8(sideBytes));
  const imports = WebAssembly.Module.imports(side);
  const sideExports = new Set(WebAssembly.Module.exports(side).map((e) => e.name));

  const need = [...new Set(imports
    .filter((i) => i.module === 'env' || i.module.startsWith('GOT.'))
    .map((i) => i.name))]
    .filter((n) => !MECHANICAL.has(n) && !sideExports.has(n));

  const sideTags = imports.filter((i) => i.kind === 'tag').map((i) => i.name);

  if (!hostBytes) {
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

  const host = new WebAssembly.Module(toU8(hostBytes));
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

/**
 * Pointer-width discriminator: parse the import section and read the imported
 * memory's limits flags. The memory64 proposal sets bit 0x04.
 *
 * Why this exists: a driver that ignores its target parameter would hand back
 * wasm32 bytes for both arches, and every positive check would still pass. Pure
 * JS because a browser has no wasm-dis to shell out to.
 */
export function memoryIs64(bytes) {
  const b = toU8(bytes);
  let off = 8;                                    // magic + version
  while (off < b.length) {
    const id = b[off++];
    let size = 0, shift = 0, byte;
    do { byte = b[off++]; size |= (byte & 0x7f) << shift; shift += 7; } while (byte & 0x80);
    if (id === 2) {                               // import section
      let p = off;
      const leb = () => { let r = 0, s = 0, x; do { x = b[p++]; r |= (x & 0x7f) << s; s += 7; } while (x & 0x80); return r; };
      const n = leb();
      for (let i = 0; i < n; i++) {
        const ml = leb(); p += ml;
        const fl = leb(); p += fl;
        const kind = b[p++];
        if (kind === 0x02) {
          const flags = b[p++];
          return !!(flags & 0x04);
        }
        if (kind === 0x00) leb();
        else if (kind === 0x01) { p++; leb(); leb(); }
        else if (kind === 0x03) { p += 2; }
        else if (kind === 0x04) { p++; leb(); }
      }
    }
    off += size;
  }
  return null;
}

/** The §4.1 compile argv, verbatim per SPEC (minus flags LLVM 24 removed). */
export function compileArgv({ triple, files, abi, defines = [], includes = [], extra = [] }) {
  return [
    `--target=${triple}`,
    '--sysroot=/sysroot',
    '-isystem', '/sysroot/include/compat',
    '-fvisibility=default', '-fPIC', '-O2',
    ...compileFlagsFor(abi).filter((f) => !REMOVED_LLVM24.has(f)),
    ...defines.flatMap((d) => ['-D', d]),
    ...includes.flatMap((i) => ['-I', i]),
    ...extra,
    '-c', `/src/${files}`, '-o', '/out/tu.o',
  ];
}

/** The §4.2 link argv (the one that produced a working side module in M0/M1). */
export function linkArgv({ target, abi, hasCrt, objPath }) {
  return [
    `-m${target}`, '-o', '/out/module.so', '--strip-debug',
    '--export=__wasm_call_ctors',
    '--export=_emscripten_tls_init',
    '--export-dynamic',
    '--unresolved-symbols=import-dynamic',
    '-shared', '--no-stack-first',
    ...linkFlagsFor(abi),
    ...(hasCrt ? [`/sysroot/lib/${target}-emscripten/pic/crtbegin-mt.o`] : []),
    objPath,
    `-L/sysroot/lib/${target}-emscripten/pic`,
  ];
}

function toU8(x) {
  if (x instanceof Uint8Array) return x;
  if (typeof Buffer !== 'undefined' && Buffer.isBuffer(x)) return new Uint8Array(x);
  return new Uint8Array(x);
}
