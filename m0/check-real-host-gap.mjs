// Gap check against the REAL downstream host (SPEC 5.4 / 5.5).
//
// Answers the question that decides whether a toolchain-built side module can
// install on today's host at all: which symbols does it need that the host
// does not export?
//
// The host path is a downstream artifact (not owned by this repo). When it is
// absent the script says so and exits 2 -- it never reports "0 gaps" for a
// missing input (zero-value guard).
//
// Usage: node m0/check-real-host-gap.mjs <side.wasm> [host.wasm]
import { readFileSync, existsSync } from 'fs';

const DEFAULT_HOST = '/mnt/hdd/octave-wasm-build/siteWebGL/w64/octave.wasm';
const MECH = new Set(['memory', '__indirect_function_table', '__stack_pointer',
  '__memory_base', '__table_base', '__stack_high', '__heap_base']);

const sidePath = process.argv[2];
const hostPath = process.argv[3] || DEFAULT_HOST;
if (!sidePath || !existsSync(sidePath)) {
  console.error(`FATAL: side module not found: ${sidePath}`);
  process.exit(2);
}
if (!existsSync(hostPath)) {
  console.error(`FATAL: host not found: ${hostPath}`);
  console.error('  (downstream artifact; not owned by this repo -- pass a path)');
  process.exit(2);
}

const side = new WebAssembly.Module(readFileSync(sidePath));
const host = new WebAssembly.Module(readFileSync(hostPath));

const sideEx = new Set(WebAssembly.Module.exports(side).map((e) => e.name));
const hostEx = new Set(WebAssembly.Module.exports(host).map((e) => e.name));
const hostTags = new Set(WebAssembly.Module.exports(host)
  .filter((e) => e.kind === 'tag').map((e) => e.name));

const imp = WebAssembly.Module.imports(side);
const need = [...new Set(imp.filter((i) => i.module === 'env' || i.module.startsWith('GOT.'))
  .map((i) => i.name))].filter((n) => !MECH.has(n) && !sideEx.has(n));
const sideTags = imp.filter((i) => i.kind === 'tag').map((i) => i.name);

console.log(`side: ${sidePath}`);
console.log(`host: ${hostPath}`);
console.log(`side needs (minus self-exports): ${need.length}`);
console.log(`host exports: ${hostEx.size} (tags: ${hostTags.size})`);
console.log(`missing functions: ${need.filter((n) => !hostEx.has(n)).length}`);
for (const m of need.filter((n) => !hostEx.has(n))) console.log(`   MISSING ${m}`);
console.log(`missing tags: ${sideTags.filter((n) => !hostTags.has(n)).length}`);
for (const m of sideTags.filter((n) => !hostTags.has(n))) console.log(`   MISSING-TAG ${m}`);
