// Browser full-loop acceptance — SPEC §9.1–9.4 in a real browser, end to end:
//
//   worker: source --clang.wasm--> object --lld.wasm--> side module
//   page:   side module --dlopen in an emscripten host--> called, and its
//           exceptions cross the boundary
//
// The browser half previously stopped at "a valid side module was produced";
// the dlopen half ran under node. This is the first place both happen in
// Chromium, which is what §9.8's "pure client" claim actually needs.
//
// Usage: node browser/check-loop.mjs
import { chromium } from 'playwright-core';
import { createServer } from 'http';
import { readFileSync, existsSync, statSync, mkdirSync } from 'fs';
import { join, dirname, extname } from 'path';
import { createHash } from 'crypto';

const ROOT = join(dirname(new URL(import.meta.url).pathname), '..');

let fails = 0, passCount = 0;
const check = (what, ok, detail = '') => {
  if (ok) passCount++; else fails++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${what}${detail ? ': ' + detail : ''}`);
};

// M0's fixture: the side module calls back into the host (miniprobe), throws
// and catches (minithrow), and touches STL templates (ministl).
const SOURCE = `#include <string>
#include <map>
#include <sstream>
#include <stdexcept>
#include <cstdio>
extern "C" int host_det2(int a, int b, int c, int d);
extern "C" void host_error();

extern "C" __attribute__((visibility("default"))) int minifn(int x) {
  std::string s = "abc";
  return x + (int)s.size();
}
extern "C" __attribute__((visibility("default"))) int miniprobe(int a, int b, int c, int d) {
  return host_det2(a, b, c, d);
}
extern "C" __attribute__((visibility("default"))) int minithrow(int mode) {
  try {
    if (mode == 0) return 0;
    if (mode == 1) throw std::runtime_error("thrown-from-oct");
    if (mode == 2) host_error();
  } catch (const std::exception& e) {
    printf("caught:%s\\n", e.what());
    return 1;
  }
  return 0;
}
extern "C" __attribute__((visibility("default"))) const char* ministl(unsigned long v) {
  static std::string out;
  std::map<std::string, double> m; m["a"] = 1.5; m["b"] = 2.5;
  std::ostringstream os; os << v << ":" << m.size();
  out = os.str();
  return out.c_str();
}
`;

const MIME = { '.html': 'text/html', '.mjs': 'text/javascript', '.js': 'text/javascript',
               '.wasm': 'application/wasm', '.json': 'application/json',
               '.tar': 'application/x-tar' };
const server = createServer((req, res) => {
  res.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
  res.setHeader('Cross-Origin-Embedder-Policy', 'require-corp');
  const p = join(ROOT, decodeURIComponent(new URL(req.url, 'http://x').pathname));
  if (!p.startsWith(ROOT) || !existsSync(p) || !statSync(p).isFile()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'Content-Type': MIME[extname(p)] || 'application/octet-stream' });
  res.end(readFileSync(p));
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;

const CLANG_REL = ['m1/build-exp-lean_nosjlj/bin', 'm1/build-exp-anchor/bin', 'm1/build-clang/bin']
  .find((c) => existsSync(join(ROOT, c, 'clang.js')));
const LLD_BIN = join(ROOT, 'm1/build-lld/bin');
const LLD_JS = existsSync(join(LLD_BIN, 'lld-wasm-only.js')) ? 'lld-wasm-only.js' : 'lld.js';
const LLD_WASM = LLD_JS.replace(/\.js$/, '.wasm');
const tarSha = createHash('sha256')
  .update(readFileSync(join(ROOT, 'package/out/sysroot-wasm32.tar'))).digest('hex');

if (!existsSync(join(ROOT, 'browser/host/host.js'))) {
  console.error('FATAL: browser/host/host.js missing — run: bash browser/build-host.sh');
  process.exit(2);
}
console.log(`clang: ${CLANG_REL}  lld: ${LLD_JS}  host: browser/host/host.js`);

const exe = '/home/archivalera/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome';
const browser = await chromium.launch({ executablePath: exe, args: ['--no-sandbox'] });
const page = await browser.newPage();
page.on('pageerror', (e) => console.log('   page error:', e.message.slice(0, 140)));

const requests = [];
page.on('request', (r) => requests.push({ method: r.method(), url: r.url() }));

await page.goto(`${base}/browser/loop.html`);
check('loop page loads', true);

await page.evaluate(async (init) => { await window.__init(init); }, {
  clangGlueUrl: `${base}/${CLANG_REL}/clang.js`,
  clangWasmUrl: `${base}/${CLANG_REL}/clang.wasm`,
  lldGlueUrl: `${base}/m1/build-lld/bin/${LLD_JS}`,
  lldWasmUrl: `${base}/m1/build-lld/bin/${LLD_WASM}`,
  sysrootTarUrl: `${base}/package/out/sysroot-wasm32.tar`,
  sysrootSha256: tarSha,
});
check('worker ready (clang + lld + verified sysroot)', true);

// ---------------------------------------------------------- compile in worker
console.log('\n== worker: compile the M0 fixture ==');
const compiled = await page.evaluate(async (src) => {
  const m = await window.__compile(src, { abi: { exceptions: 'wasm-legacy', pthread: true } });
  return { ok: m.ok, error: m.error, bytes: m.moduleBytes ? Array.from(new Uint8Array(m.moduleBytes)) : null };
}, SOURCE);
check('worker compiled a side module', compiled.ok === true, compiled.ok ? '' : compiled.error);
if (!compiled.ok) { await browser.close(); server.close(); process.exit(1); }
console.log(`   ${compiled.bytes.length} bytes`);

// --------------------------------------------------- dlopen in the host page
console.log('\n== page: dlopen it in an emscripten host ==');
const ran = await page.evaluate(async ({ hostBase, soBytes }) => {
  try {
    const r = await window.__hostRun(hostBase, soBytes);
    return { rc: r.rc, lines: window.__lines.slice() };
  } catch (e) { return { error: String(e && e.message || e).slice(0, 300), lines: window.__lines.slice() }; }
}, { hostBase: `${base}/browser/host`, soBytes: compiled.bytes });

if (ran.error) {
  check('host ran', false, ran.error);
} else {
  const hostLines = ran.lines.filter((l) => l.startsWith('  [host]') || l.includes('PASS') || l.includes('FAIL'));
  for (const l of hostLines) console.log('   ' + l.trim());
  const text = ran.lines.join('\n');
  check('host exited 0', ran.rc === 0, `rc=${ran.rc}`);
  check('dlopen succeeded (in browser)', text.includes('PASS dlopen'));
  check('called a function in the side module', text.includes('PASS minifn(7): got=10'));
  check('side module called back into the host', text.includes('PASS miniprobe([2,3;1,4]): got=5'));
  check('side module threw and caught its own exception',
        text.includes('PASS minithrow(1): got=1'), 'caught:thrown-from-oct');
  check('exception thrown BY the host, caught in the side module',
        text.includes('PASS minithrow(2): got=1'), 'caught:octave-error-from-oct');
  check('STL templates across the boundary',
        text.includes('PASS ministl(42): got=42:2'));
  check('no failures from the host suite', !text.includes('FAIL '));
}

// ------------------------------------------------------------------- §9.8
console.log('\n== §9.8 纯客户端 ==');
const posts = requests.filter((r) => r.method !== 'GET');
check('no non-GET requests', posts.length === 0, `${requests.length} requests, all GETs`);
const off = requests.filter((r) => !r.url.startsWith(base) && !r.url.startsWith('blob:'));
check('nothing leaves the origin', off.length === 0, off.length ? JSON.stringify(off.slice(0, 2)) : 'all same-origin');

console.log('-- artifacts');
console.log(`ARTIFACT loop_acceptance_pass ${passCount}`);
console.log(`ARTIFACT loop_sidemodule_bytes ${compiled.bytes.length}`);
console.log(`\n=== ${fails === 0 ? 'ALL PASS' : fails + ' FAILED'} ===`);

mkdirSync(join(ROOT, 'browser/evidence'), { recursive: true });
await browser.close();
server.close();
process.exitCode = fails === 0 ? 0 : 1;
