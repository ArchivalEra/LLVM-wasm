// check-symbol-gap.mjs — SPEC 5.4 / check-oct-host-symbols.mjs analogue.
// Compares a side module's `env` imports against a host module's exports and
// names every gap. No side effects; prints bare counts plus the missing list.
//
// Usage: node check-symbol-gap.mjs <side.wasm> <host.wasm>
import { readFileSync } from 'fs';

const INTERNAL = new Set([
  'memory', '__indirect_function_table', '__stack_pointer', '__memory_base',
  '__table_base', '__stack_high', '__heap_base', '__cpp_exception',
  '__c_longjmp', '__wasm_apply_data_relocs', '__dso_handle', '__tls_size',
  '__tls_align', '__set_stack_limits', '_emscripten_tls_init',
  '__wasm_init_tls', '__wasm_call_ctors',
]);

const [sidePath, hostPath] = process.argv.slice(2);
const side = new WebAssembly.Module(readFileSync(sidePath));
const host = new WebAssembly.Module(readFileSync(hostPath));

const sideImports = WebAssembly.Module.imports(side);
// A side module may both import and export a symbol (GOT self-reference).
// emscripten's resolveSymbol checks wasmImports -> localScope -> moduleExports,
// so the side's own exports are a legitimate resolution source. Not subtracting
// them produces false positives (measured: piecewise_construct).
const sideExports = new Set(WebAssembly.Module.exports(side).map((e) => e.name));
const envNeeded = sideImports
  .filter((i) => i.module === 'env' || i.module.startsWith('GOT.'))
  .map((i) => i.name)
  .filter((n) => !INTERNAL.has(n) && !sideExports.has(n));

const hostExports = new Set(WebAssembly.Module.exports(host).map((e) => e.name));
const hostTags = new Set(
  WebAssembly.Module.exports(host).filter((e) => e.kind === 'tag').map((e) => e.name),
);
const sideTags = sideImports.filter((i) => i.kind === 'tag').map((i) => i.name);

const missing = [...new Set(envNeeded)].filter((n) => !hostExports.has(n));
const missingTags = sideTags.filter((n) => !hostTags.has(n));

console.log(`side env imports: ${envNeeded.length}`);
console.log(`host exports: ${hostExports.size}`);
console.log(`host tag exports: ${hostTags.size} [${[...hostTags].join(', ')}]`);
console.log(`missing: ${missing.length}`);
for (const m of missing) console.log(`   MISSING ${m}`);
console.log(`missing tags: ${missingTags.length}`);
for (const m of missingTags) console.log(`   MISSING-TAG ${m}`);
process.exitCode = missing.length + missingTags.length > 0 ? 1 : 0;
