#!/usr/bin/env node
// Derive the content-list record (seam schema 2) from manifest.json.
//
// Why derived rather than hand-written: the inbound letter asks who owns the
// record, and the answer that cannot drift is "one producer, two outputs". This
// script reads the same in-memory manifest that make-release.sh just wrote, so
// the sha256 / bytes / licence in the record are the manifest's, not a second
// transcription of them. make-release.sh runs it right after writing manifest.
//
// Fields we do NOT invent: `form` is derived from the bytes (the letter's §2
// judgment 2: "供给方从字节派生，不是作者手写").
//
// `content` is `[]` on every entry here, and that is the host's ruling, not a
// gap: the schema says content means "which kinds of source a package holds"
// (m/src/oct) and that capability-layer entries (form:"tree") leave it empty,
// because forcing wasm/js into that enum turns the axis into a catch-all
// (2026-10-14, answering the content repo's mail/007). An earlier version of
// this script put ["wasm","module"] there and the host validator rejected all
// 13 entries -- the ruling postdates that guess.
//
// `url` is the DELIVERY path (site-relative, a request to whoever assembles the
// site); `upstream_url` is where the bytes live today, which is the release
// attachment. The schema accepts both in producer mode and only requires
// same-origin in --site mode, so nothing here pretends the bytes are already
// on the content host.
//
// Usage: node release/make-content-list.mjs <bundle-dir> <out.json> [--pin <ref>]
import { readFileSync, writeFileSync, existsSync } from 'fs';
import { join } from 'path';

const [bundleDir, outPath] = process.argv.slice(2);
const pinIdx = process.argv.indexOf('--pin');
const pin = pinIdx >= 0 ? process.argv[pinIdx + 1] : null;

if (!bundleDir || !outPath) {
  console.error('usage: node make-content-list.mjs <bundle-dir> <out.json> [--pin <ref>]');
  process.exit(2);
}
const manPath = join(bundleDir, 'manifest.json');
if (!existsSync(manPath)) { console.error(`FATAL: ${manPath} missing`); process.exit(2); }
const man = JSON.parse(readFileSync(manPath, 'utf8'));

// ------------------------------------------------------------------ form
// Derived from what the BYTES are, not from a preference. A .tar is checked by
// opening it (a mislabelled file would otherwise pass); the rest by kind.
function deriveForm(filePath, name) {
  if (name.endsWith('.tar')) {
    // tar magic sits at offset 257 ("ustar")
    const buf = readFileSync(filePath);
    const magic = buf.toString('latin1', 257, 262);
    if (magic.startsWith('ustar')) {
      // count regular-file entries to describe it honestly
      let off = 0, files = 0;
      while (off + 512 <= buf.length) {
        const hdr = buf.subarray(off, off + 512);
        if (hdr.every((b) => b === 0)) break;
        const size = parseInt(hdr.toString('utf8', 124, 136).replace(/\0.*$/, '').trim(), 8) || 0;
        const type = String.fromCharCode(hdr[156] || 48);
        if (type === '0' || type === '\0') files++;
        off += 512 + Math.ceil(size / 512) * 512;
      }
      return { form: 'tree', content: ['tree', `${files} regular files`], files };
    }
    return { form: 'file', content: ['archive', 'not a tar (magic missing)'] };
  }
  if (name.endsWith('.wasm')) {
    const buf = readFileSync(filePath, { length: 8 });
    const ok = buf[0] === 0x00 && buf[1] === 0x61 && buf[2] === 0x73 && buf[3] === 0x6d;
    return { form: 'file', content: ['wasm', ok ? 'module' : 'NOT a wasm module'] };
  }
  if (name.endsWith('.js')) return { form: 'js', content: ['emscripten glue'] };
  if (name.endsWith('.mjs')) return { form: 'file', content: ['javascript module'] };
  return { form: 'file', content: ['text'] };
}

// ------------------------------------------------------------------ entries
// One entry per asset, and here is the reasoning, because the letter's §2
// judgment says "capability layer = ONE form:tree entry" and one entry cannot
// hold these assets without losing something real:
//
//   a. licence is per file and comes in three classes here; one entry carries
//      one licence, so a single entry would have to lie about two of them;
//   b. sha256 is per file, and per-file is what lets a consumer pull ONE arch
//      and reuse the shared half (clang.wasm is byte-identical across arches;
//      as two opaque tars that reuse is invisible);
//   c. `form` is derived per asset (four different forms here), which the
//      single-entry shape flattens to "tree".
//
// The INTENT of that judgment -- a consumer has only one traversal, no special
// type for a "capability layer" -- is preserved: every entry below is an
// ordinary entry, all in one deps graph. See the reply, A2, for the alternative
// if the collector prefers one entry and is willing to take (a)-(c) on board.
const SITE_PREFIX = 'assets/llvm-wasm/';
// Where the bytes are RETRIEVABLE from today: the release bundle. Note this is
// one URL for all thirteen entries -- the individual files are not separate
// release assets, they live inside the bundle. Writing a per-file
// .../download/<tag>/<file> URL would look tidier and 404 (the release carries
// only llvm-wasm-bundle-<tag>.tar.gz and manifest.json). A record whose
// upstream_url does not resolve is the same class of error as a pin that names
// a release which does not exist.
const UPSTREAM_BUNDLE = process.env.CONTENT_UPSTREAM_BUNDLE
  || 'https://github.com/ArchivalEra/LLVM-wasm/releases/download/v0.1.2/llvm-wasm-bundle-v0.1.2.tar.gz';
const entries = [];
for (const a of man.assets) {
  const p = join(bundleDir, a.name);
  if (!existsSync(p)) { console.error(`FATAL: manifest lists ${a.name} but it is not in ${bundleDir}`); process.exit(2); }
  const { form } = deriveForm(p, a.name.split('/').pop());
  entries.push({
    // Keep the extension: clang.wasm and clang.js would otherwise both be
    // "llvm-wasm-clang", and a consumer looking an asset up by name would get
    // two answers (measured on the first run of this script).
    name: `llvm-wasm-${a.name.replace(/\//g, '-')}`,
    version: (man.toolchain.emcc.match(/\b(\d+\.\d+\.\d+)\b/) || [, 'unknown'])[1],
    // site-relative per schema 2; the collector places the bytes here
    url: SITE_PREFIX + a.name,
    sha256: a.sha256,
    size: a.bytes,
    form,
    content: [],              // capability layer: empty by the host's ruling
    license: a.license,       // per-entry, because our assets carry three classes
    // Where the bytes are TODAY: the bundle that contains them (same URL on
    // every entry -- see UPSTREAM_BUNDLE above). Separate from `url` (the
    // delivery path) so the record never claims the content host has them.
    upstream_url: UPSTREAM_BUNDLE,
    deps: [],
  });
}

// Which arch a consumer wants is the real atomic choice, so record it as data
// rather than leaving every consumer to match on file names.
const record = {
  schema: 2,
  // Lowercase: the validator matches producer ids against a lowercase table
  // and reports "期望 'llvm-wasm'，表里是 'LLVM-wasm'" otherwise (measured).
  producer: { id: 'llvm-wasm', pin: pin || man.toolchain.llvm_source_commit || 'unknown' },
  octave: '11.3.0',
  _why: 'Derived from release/out/manifest.json by release/make-content-list.mjs. '
      + 'Edit the manifest or the script, never this file.',
  variants: {
    _why: 'wasm32 and wasm64 differ in exactly one file (the sysroot tar). A consumer '
        + 'picks one variant; the rest of the entries are shared and de-duplicate by sha256.',
    wasm32: { sysroot: 'llvm-wasm-sysroot-headers.tar',
              note: 'include/ + lib/wasm32-emscripten/pic/crtbegin-mt.o' },
    wasm64: { sysroot: 'llvm-wasm-sysroot-headers.wasm64.tar',
              note: 'include/ + lib/wasm64-emscripten/pic/crtbegin-mt.o' },
  },
  first_load: {
    _why: 'The lld pair is needed to LINK, not to compile, so a client may defer it. '
        + 'This is a fetch-order hint, not an entry structure: there is no schema axis '
        + 'for "needed later" and we did not invent one.',
    brotli_bytes: man.first_load.brotli_bytes,
    plus_lld_brotli_bytes: man.first_load.plus_lld_brotli_bytes,
  },
  entries,
};

writeFileSync(outPath, JSON.stringify(record, null, 1) + '\n');
console.log(`content-list: ${outPath} (${entries.length} entries)`);
for (const e of entries) console.log(`  ${e.name.padEnd(34)} ${String(e.size).padStart(10)}  ${e.form.padEnd(5)} ${e.license.split(' (')[0]}`);
console.log(`\nARTIFACT content_list_entries ${entries.length}`);
