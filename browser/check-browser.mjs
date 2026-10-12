// Browser acceptance — SPEC §7.3 (Worker), §9.4 (EH in user code), §9.8 (pure client).
//
// What "real browser" adds over the node harness, and what this test proves:
//   · the glue actually runs under Chromium (V8), not just node's V8;
//   · SharedArrayBuffer exists (the server sends COOP/COEP) — required by the
//     pthread modules;
//   · the worker compiles and links a side module with no host filesystem;
//   · §9.4: the lean compiler still emits working EH for user code (the tag is
//     imported, so the module is dlopen-compatible with an EH host);
//   · §9.8: every network request the page makes is a same-origin GET of a
//     static asset. No POSTs, no source leaving the machine.
//
// The worker imports ../driver/abi.mjs (served from the repo root by the test
// server), so the flag assembly and the gap check keep a single source — the
// browser cannot drift from the node driver by construction.
//
// Usage: node browser/check-browser.mjs
import { chromium } from 'playwright-core';
import { createServer } from 'http';
import { readFileSync, existsSync, mkdirSync, writeFileSync, statSync } from 'fs';
import { join, dirname, extname, relative } from 'path';
import { createHash } from 'crypto';

const ROOT = join(dirname(new URL(import.meta.url).pathname), '..');

let fails = 0, passCount = 0;
const check = (what, ok, detail = '') => {
  if (ok) passCount++; else fails++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${what}${detail ? ': ' + detail : ''}`);
};

// ---------------------------------------------------------------- fixtures
// §9.1: one exported function + one std::string use.
const FIXTURE = `#include <string>
extern "C" __attribute__((visibility("default"))) int minifn(int x) {
  std::string s = "abc";
  return x + (int)s.size();
}
`;
// §9.4 (compile side): user code that throws — proves the lean compiler still
// emits EH. (The dlopen/host-catch half ran in node; the tag import here is the
// browser-side evidence.)
const EH_FIXTURE = `#include <stdexcept>
extern "C" __attribute__((visibility("default"))) int minithrow(int mode) {
  try {
    if (mode == 0) return 0;
    if (mode == 1) throw std::runtime_error("thrown-from-oct");
  } catch (const std::exception& e) { return 1; }
  return 0;
}
`;

// ---------------------------------------------------------------- server
const MIME = { '.html': 'text/html', '.mjs': 'text/javascript', '.js': 'text/javascript',
               '.wasm': 'application/wasm', '.json': 'application/json',
               '.tar': 'application/x-tar' };
const server = createServer((req, res) => {
  // COOP/COEP: pthread modules need SharedArrayBuffer, which browsers only
  // expose in a cross-origin-isolated context (measured: without these headers
  // crossOriginIsolated === false).
  res.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
  res.setHeader('Cross-Origin-Embedder-Policy', 'require-corp');
  const url = new URL(req.url, 'http://x');
  const p = join(ROOT, decodeURIComponent(url.pathname));
  if (!p.startsWith(ROOT) || !existsSync(p) || !statSync(p).isFile()) {
    res.writeHead(404); res.end(); return;
  }
  res.writeHead(200, { 'Content-Type': MIME[extname(p)] || 'application/octet-stream' });
  res.end(readFileSync(p));
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const port = server.address().port;
const base = `http://127.0.0.1:${port}`;

// ---------------------------------------------------------------- assets
const CLANG_REL = ['m1/build-exp-lean_nosjlj/bin', 'm1/build-exp-anchor/bin', 'm1/build-clang/bin']
  .find((c) => existsSync(join(ROOT, c, 'clang.js')));
const LLD_BIN = join(ROOT, 'm1/build-lld/bin');
const LLD_JS = existsSync(join(LLD_BIN, 'lld-wasm-only.js')) ? 'lld-wasm-only.js' : 'lld.js';
// ⚠️ The glue and the wasm must be a matched pair. lld-wasm-only.js expects
// lld-wasm-only.wasm; fetching lld.wasm instead makes instantiate fail with
// "Import #41 a.P: function import requires a callable" (measured) — the
// minimized import letters differ between the two builds, so the glue's
// wasmImports has the wrong names.
const LLD_WASM = LLD_JS.replace(/\.js$/, '.wasm');
const TAR = join(ROOT, 'package/out/sysroot-wasm32.tar');
if (!CLANG_REL) { console.error('FATAL: no clang build found under m1/'); process.exit(2); }
console.log(`clang: ${CLANG_REL}  lld: ${LLD_JS}  tar: ${relative(ROOT, TAR)}`);
const tarSha = createHash('sha256').update(readFileSync(TAR)).digest('hex');

mkdirSync(join(ROOT, 'browser', 'evidence'), { recursive: true });

// ---------------------------------------------------------------- browser
const exe = '/home/archivalera/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome';
const browser = await chromium.launch({ executablePath: exe, args: ['--no-sandbox'] });
const page = await browser.newPage();

const requests = [];
page.on('request', (r) => requests.push({ method: r.method(), url: r.url() }));
page.on('pageerror', (e) => {
  console.log('   page error:', e.message.slice(0, 160));
  if (e.stack) console.log('   stack:\n     ' + e.stack.split('\n').slice(0, 10).join('\n     '));
});

await page.goto(`${base}/browser/index.html`);
check('page loads', true);

const isolated = await page.evaluate(() => !!self.crossOriginIsolated
  && typeof SharedArrayBuffer === 'function');
check('crossOriginIsolated (SharedArrayBuffer available)', isolated);

await page.evaluate(async (init) => { await window.__init(init); }, {
  clangGlueUrl: `${base}/${CLANG_REL}/clang.js`,
  clangWasmUrl: `${base}/${CLANG_REL}/clang.wasm`,
  lldGlueUrl: `${base}/m1/build-lld/bin/${LLD_JS}`,
  lldWasmUrl: `${base}/m1/build-lld/bin/${LLD_WASM}`,
  sysrootTarUrl: `${base}/package/out/sysroot-wasm32.tar`,
  sysrootSha256: tarSha,
});

const artifacts = {};
for (const [key, source] of [['basic', FIXTURE], ['eh', EH_FIXTURE]]) {
  console.log(`\n== ${key} ==`);
  const r = await page.evaluate(async (source) => {
    const m = await window.__runCompile(source);
    return {
      ok: m.ok, error: m.error, detail: m.detail,
      bytes: m.moduleBytes ? m.moduleBytes.length : 0,
      full: m.moduleBytes ? Array.from(new Uint8Array(m.moduleBytes)) : null,
      gap: m.gap ? { needs: m.gap.needs, hostChecked: m.gap.hostChecked } : null,
    };
  }, source);
  check(`${key}: compile ok in browser`, r.ok === true, r.ok ? '' : r.error);
  if (!r.ok && r.detail && r.detail.length) {
    console.log('   tool said:');
    for (const d of r.detail) console.log('     ' + d);
  }
  if (!r.ok) {
    const wl = await page.evaluate(() => document.getElementById('log').textContent);
    console.log('   worker log tail:');
    for (const l of wl.trim().split('\n').slice(-6)) console.log('     ' + l);
  }
  if (!r.ok) continue;
  check(`${key}: module has bytes`, r.bytes > 0, `${r.bytes} B`);
  artifacts[key] = r.full;
  if (r.gap) check(`${key}: gap report present`, typeof r.gap.needs === 'number');
}

// the ABI checks run in Chromium itself
const exportsInBrowser = await page.evaluate((b) => {
  const m = new WebAssembly.Module(new Uint8Array(b));
  return WebAssembly.Module.exports(m).map((e) => e.name);
}, artifacts.basic);
check('browser: exports minifn', exportsInBrowser.includes('minifn'), exportsInBrowser.join(','));
check('browser: exports __wasm_call_ctors', exportsInBrowser.includes('__wasm_call_ctors'));

const ehTag = await page.evaluate((b) => {
  const m = new WebAssembly.Module(new Uint8Array(b));
  return WebAssembly.Module.imports(m).some((i) => i.kind === 'tag' && i.name === '__cpp_exception');
}, artifacts.eh);
check('browser: EH fixture imports __cpp_exception (§9.4)', ehTag === true,
      'the lean compiler still emits EH for user code');

// ---------------------------------------------------------------- §9.8
console.log('\n== §9.8 纯客户端 ==');
const posts = requests.filter((r) => r.method !== 'GET');
check('no non-GET requests (source cannot have left)', posts.length === 0,
      posts.length ? JSON.stringify(posts.slice(0, 3)) : `${requests.length} requests, all GETs`);
// blob: URLs are same-origin by construction (they are created in the page and
// name in-memory glue the page itself assembled). Loading glue through one is
// not traffic leaving the machine, so classify rather than fail on the prefix.
const OFF_ORIGIN = requests.filter((r) => !r.url.startsWith(base) && !r.url.startsWith('blob:'));
check('no requests leave the harness origin (blob: glue excluded)',
      OFF_ORIGIN.length === 0,
      OFF_ORIGIN.length ? JSON.stringify(OFF_ORIGIN.slice(0, 3))
                        : `${requests.length} requests; ${requests.filter((r) => r.url.startsWith('blob:')).length} are in-page blob: glue`);
// The compile payload travels by postMessage into the Worker, so no URL should
// ever carry source text. Check for source-shaped characters in the origin+path.
const sourcey = requests.filter((r) => /[;{}#]|#include|std::/.test(decodeURIComponent(r.url)));
check('no URL carries source payloads', sourcey.length === 0,
      sourcey.length ? JSON.stringify(sourcey.slice(0, 2)) : 'the compile payload never appears in a URL');

console.log('-- artifacts');
console.log(`ARTIFACT browser_acceptance_pass ${passCount}`);
for (const [k, v] of Object.entries(artifacts)) {
  console.log(`ARTIFACT browser_module_${k}_bytes ${v.length}`);
}

console.log(`\n=== ${fails === 0 ? 'ALL PASS' : fails + ' FAILED'} ===`);
await browser.close();
server.close();
process.exitCode = fails === 0 ? 0 : 1;
