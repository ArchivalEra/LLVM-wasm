#!/usr/bin/env node
// Self-consistency check for the content-list record (seam schema 2).
//
// ⚠️ Scope: this is NOT "the port's validator" (that lives at the host,
// build/extra-content/, and is not built yet). It only checks that the record
// does not contradict ITSELF or the manifest it was derived from:
//
//   · every entry has the fields schema 2 requires;
//   · every file exists, at the stated size, with the stated sha256;
//   · the record's sha256s equal the manifest's (same producer, so a mismatch
//     means the derivation drifted);
//   · `form` matches what the bytes actually are (a .tar that is not a tar, a
//     .wasm that is not a wasm module);
//   · names are unique (a lookup by name must have one answer);
//   · the variant map points at entries that exist.
//
// Usage: node release/check-content-list.mjs [--bundle <dir>] [--record <file>]
import { readFileSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { createHash } from 'crypto';

const ROOT = join(dirname(new URL(import.meta.url).pathname), '..');
const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : dflt;
};
const BUNDLE = opt('--bundle', join(ROOT, 'release/out'));
const RECORD = opt('--record', join(ROOT, 'release/content-list.json'));

let fails = 0, passCount = 0;
const check = (what, ok, detail = '') => {
  if (ok) passCount++; else fails++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${what}${detail ? ': ' + detail : ''}`);
};

for (const f of [RECORD, join(BUNDLE, 'manifest.json')]) {
  if (!existsSync(f)) { console.error(`FATAL: ${f} missing — run release/make-release.sh`); process.exit(2); }
}
const rec = JSON.parse(readFileSync(RECORD, 'utf8'));
const man = JSON.parse(readFileSync(join(BUNDLE, 'manifest.json'), 'utf8'));
console.log(`record: ${RECORD}`);
console.log(`bundle: ${BUNDLE}`);

// ------------------------------------------------------------- schema 2 shape
console.log('\n== schema 2 required fields ==');
check('schema is 2', rec.schema === 2, String(rec.schema));
check('producer has id and pin', !!(rec.producer?.id && rec.producer?.pin),
      `${rec.producer?.id} @ ${rec.producer?.pin}`);
check('octave is present', typeof rec.octave === 'string', rec.octave);
check('entries is a non-empty array', Array.isArray(rec.entries) && rec.entries.length > 0,
      `${rec.entries.length} entries`);
const missing = rec.entries.filter((e) => !e.name || !e.version || !e.url || !e.sha256 || !e.form);
check('every entry has name/version/url/sha256/form', missing.length === 0,
      missing.length ? missing.map((e) => e.name || '(unnamed)').join(',') : 'all present');

// ------------------------------------------------------------- names are unique
console.log('\n== names identify one thing each ==');
const names = rec.entries.map((e) => e.name);
const dups = names.filter((n, i) => names.indexOf(n) !== i);
check('entry names are unique', dups.length === 0,
      dups.length ? `duplicated: ${[...new Set(dups)].join(',')}` : `${names.length} unique`);

// ---------------------------------------------- every file matches its record
console.log('\n== every entry matches the bytes ==');
const sha = (p) => createHash('sha256').update(readFileSync(p)).digest('hex');
for (const e of rec.entries) {
  // url is site-relative (assets/llvm-wasm/<bundle-relative path>). Strip the
  // site prefix and keep the REMAINDER -- for driver/*.mjs that includes the
  // subdirectory, which a leaf-name lookup loses (measured: 4 false failures).
  const rel = e.url.replace(/^assets\/llvm-wasm\//, '');
  const p = join(BUNDLE, rel);
  if (!existsSync(p)) { check(`${e.name}: file present`, false, `no ${rel} in bundle`); continue; }
  const buf = readFileSync(p);
  const sizeOk = e.size == null || buf.length === e.size;
  const shaOk = sha(p) === e.sha256;
  check(`${e.name}`, sizeOk && shaOk,
        sizeOk && shaOk ? `${buf.length} B` : `${sizeOk ? '' : `size ${buf.length} != ${e.size}; `}${shaOk ? '' : 'sha256 mismatch'}`);
}

// ------------------------------- the record and the manifest are one producer
console.log('\n== record and manifest agree (one producer) ==');
let mismatch = 0;
for (const e of rec.entries) {
  const rel = e.url.replace(/^assets\/llvm-wasm\//, '');
  const a = man.assets.find((x) => x.name === rel);
  if (!a) { mismatch++; console.log(`   ${e.name}: not in manifest`); continue; }
  if (a.sha256 !== e.sha256 || a.bytes !== e.size) {
    mismatch++; console.log(`   ${e.name}: manifest says ${a.bytes}/${a.sha256.slice(0, 12)}…, record says ${e.size}/${e.sha256.slice(0, 12)}…`);
  }
}
check('no entry contradicts the manifest', mismatch === 0, mismatch ? `${mismatch} mismatched` : `${rec.entries.length} checked`);

// ------------------------------------------------- form matches the real bytes
console.log('\n== form is derived from the bytes, not the name ==');
for (const e of rec.entries) {
  const rel = e.url.replace(/^assets\/llvm-wasm\//, '');
  const p = join(BUNDLE, rel);
  if (!existsSync(p)) continue;
  const buf = readFileSync(p);
  const leaf = rel.split('/').pop();
  if (leaf.endsWith('.tar')) {
    const ok = buf.toString('latin1', 257, 262).startsWith('ustar');
    check(`${e.name}: a real tar`, ok && e.form === 'tree',
          ok ? `form=tree` : `MAGIC MISSING but form=${e.form}`);
  } else if (leaf.endsWith('.wasm')) {
    const ok = buf[0] === 0x00 && buf[1] === 0x61 && buf[2] === 0x73 && buf[3] === 0x6d;
    check(`${e.name}: a real wasm module`, ok && e.form === 'file', ok ? 'form=file' : 'NOT a wasm module');
  }
}

// ------------------------------------------------------------- variants resolve
console.log('\n== variants point at entries that exist ==');
for (const [arch, v] of Object.entries(rec.variants || {})) {
  if (arch === '_why') continue;
  check(`variant ${arch} -> ${v.sysroot}`, names.includes(v.sysroot),
        names.includes(v.sysroot) ? '' : 'no such entry');
}

// ------------------------------------------------- the host's validator, if present
// The gap this closes: everything above checks the record against ITSELF and
// against the manifest, and all of it passed while the host's validator
// rejected all 13 entries (content enum + producer id). A self-check cannot
// see a contract it does not know about. This step runs the real thing when the
// host repo is on this machine, and says plainly when it is not -- it is not
// vendored here, because a copy would be a second producer of the same rules.
console.log('\n== the host validator (external contract) ==');
const HOST_VALIDATOR = process.env.CONTENT_VALIDATOR
  || '/mnt/hdd/zcode-projects/Octave-Full-Wasm/build/extra-content/validate-content-list.py';
if (!existsSync(HOST_VALIDATOR)) {
  console.log(`   SKIP: no validator at ${HOST_VALIDATOR}`);
  console.log("   (set CONTENT_VALIDATOR=<path>; this is the port's contract, not ours to copy)");
} else {
  const { spawnSync } = await import('child_process');
  for (const mode of [['--producer', 'llvm-wasm'], ['--site']]) {
    const r = spawnSync('python3', [HOST_VALIDATOR, '--list', RECORD, ...mode], { encoding: 'utf8' });
    const out = (r.stdout || '') + (r.stderr || '');
    const ok = r.status === 0;
    check(`host validator ${mode.join(' ')}`, ok,
          ok ? out.trim().split('\n').pop() : out.trim().split('\n').slice(0, 4).join(' | '));
  }
}

console.log('-- artifacts');
console.log(`ARTIFACT content_list_check_pass ${passCount}`);
console.log(`ARTIFACT content_list_entries_verified ${rec.entries.length}`);
console.log(`\n=== ${fails === 0 ? 'ALL PASS' : fails + ' FAILED'} ===`);
process.exitCode = fails === 0 ? 0 : 1;
