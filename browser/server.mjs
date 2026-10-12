#!/usr/bin/env node
// Static server with COOP/COEP — pthread/SharedArrayBuffer requires
// cross-origin isolation, so the harness is served with:
//   Cross-Origin-Opener-Policy: same-origin
//   Cross-Origin-Embedder-Policy: require-corp
// (measured: without them, crossOriginIsolated === false and
//  SharedArrayBuffer is undefined ⇒ the pthread modules cannot run.)
import { createServer } from 'http';
import { readFileSync, existsSync, statSync } from 'fs';
import { join, extname, dirname } from 'path';
import { fileURLToPath } from 'url';

const ROOT = dirname(fileURLToPath(import.meta.url));
const port = Number(process.env.PORT || 8123);

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript',
  '.mjs': 'text/javascript',
  '.wasm': 'application/wasm',
  '.json': 'application/json',
  '.tar': 'application/x-tar',
  '.css': 'text/css',
};

createServer((req, res) => {
  res.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
  res.setHeader('Cross-Origin-Embedder-Policy', 'require-corp');
  // the test also inspects this header server-side (see check-browser.mjs)
  res.setHeader('X-Isolated-Server', '1');

  const url = new URL(req.url, `http://${req.headers.host}`);
  let p = join(ROOT, decodeURIComponent(url.pathname));
  if (!p.startsWith(ROOT)) { res.writeHead(403); res.end(); return; }
  if (p.endsWith('/')) p += 'index.html';
  if (!existsSync(p) || !statSync(p).isFile()) { res.writeHead(404); res.end('404'); return; }
  res.writeHead(200, { 'Content-Type': MIME[extname(p)] || 'application/octet-stream' });
  res.end(readFileSync(p));
}).listen(port, () => console.log(`serving ${ROOT} on http://127.0.0.1:${port}`));
