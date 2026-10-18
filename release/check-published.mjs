#!/usr/bin/env node
// Read-back reconciliation: the PUBLISHED release vs the manifest it claims.
//
// Why this exists (host mail/044, our 013): v0.1.2 shipped without
// compile-core.mjs while the working tree already had it -- the fix commit
// landed 8 minutes AFTER the release was published, and every check I had read
// release/out/ (the working tree), so nothing compared the published artefact
// against what the record said. mail/007 then claimed "14 entries, because it
// is really in the bundle now" about a bundle that had 13. The general shape:
// a claim about a RELEASE can only be checked by reading the RELEASE.
//
// This script is deliberately two-mode:
//
//   --tar <file>   reconcile a tarball against the manifest INSIDE it
//   --tag <tag>    download the release's assets from GitHub and reconcile
//
// The second mode is the one that would have caught v0.1.2: it fetches what
// GitHub actually serves, not what the working tree says.
//
// Usage: node release/check-published.mjs --tag v0.1.3
//        node release/check-published.mjs --tar release/llvm-wasm-bundle-v0.1.3.tar.gz
import { spawnSync } from 'child_process';
import { readFileSync, writeFileSync, mkdtempSync, existsSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const args = process.argv.slice(2);
const opt = (name) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : null;
};
const TAG = opt('--tag');
const TAR = opt('--tar');
if (!TAG && !TAR) {
  console.error('usage: check-published.mjs --tag <tag> | --tar <bundle.tar.gz> [--freshness]');
  process.exit(2);
}

let fails = 0, passCount = 0;
const check = (what, ok, detail = '') => {
  if (ok) passCount++; else fails++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${what}${detail ? ': ' + detail : ''}`);
};

// ------------------------------------------------------------- obtain bytes
let tarPath = TAR;
const scratch = TAG ? mkdtempSync(join(tmpdir(), 'pubcheck-')) : null;
if (TAG) {
  const r = spawnSync('gh', ['release', 'download', TAG, '-R', 'ArchivalEra/LLVM-wasm',
    '-p', 'llvm-wasm-bundle-*.tar.gz', '-D', scratch, '--clobber'],
    { encoding: 'utf8' });
  if (r.status !== 0) {
    console.error(`FATAL: gh release download failed: ${(r.stderr || '').slice(0, 160)}`);
    process.exit(2);
  }
  const { readdirSync } = await import('fs');
  const got = readdirSync(scratch).filter((f) => f.endsWith('.tar.gz'));
  if (got.length !== 1) { console.error(`FATAL: expected one tarball, got ${got.length}`); process.exit(2); }
  tarPath = join(scratch, got[0]);
  console.log(`downloaded: ${got[0]}`);
}

// ------------------------------------------------- read the manifest from it
const manifestJson = spawnSync('sh', ['-c',
  `tar xzOf ${JSON.stringify(tarPath)} ./manifest.json`], { encoding: 'utf8' });
if (manifestJson.status !== 0 || !manifestJson.stdout.trim()) {
  console.error('FATAL: no manifest.json inside the bundle');
  process.exit(2);
}
const man = JSON.parse(manifestJson.stdout);
console.log(`bundle: ${tarPath}`);
console.log(`manifest: ${man.assets.length} assets, generated ${man.generated}`);

// ------------------------------------------- every manifest asset is in the tar
const listing = spawnSync('sh', ['-c', `tar tzf ${JSON.stringify(tarPath)}`], { encoding: 'utf8' });
const files = new Set(listing.stdout.split('\n').map((l) => l.replace(/^\.\//, '')).filter(Boolean));
console.log(`tar contains ${files.size} entries`);

console.log('\n== every manifest asset is present in the tar ==');
let absent = 0;
for (const a of man.assets) {
  const ok = files.has(a.name);
  if (!ok) absent++;
  check(`asset ${a.name}`, ok, ok ? '' : 'manifest lists it, tar lacks it');
}
check('no manifest asset is missing from the tar', absent === 0, `${absent} missing`);

// ------------------------------------------- (the v0.1.2 failure, made general)
// The specific failure was a driver file the CODE imports but the bundle
// lacked. General shape: every relative import inside the bundle's driver/
// must resolve within the bundle. This is the host's "imports-present" idea,
// checked on the published artefact.
console.log('\n== relative imports inside driver/ resolve within the bundle ==');
const importRe = /from\s+['"](\.[^'"]+)['"]/g;
let brokenImports = 0;
for (const f of files) {
  if (!f.startsWith('driver/') || !f.endsWith('.mjs')) continue;
  const src = spawnSync('sh', ['-c', `tar xzOf ${JSON.stringify(tarPath)} ./${f}`],
    { encoding: 'utf8' }).stdout;
  let m;
  while ((m = importRe.exec(src)) !== null) {
    // resolve ./x against the importing file's directory
    const base = f.split('/').slice(0, -1).join('/');
    const parts = (base ? base + '/' : '') + m[1];
    const norm = [];
    for (const p of parts.split('/')) {
      if (p === '.' || p === '') continue;
      if (p === '..') { norm.pop(); continue; }
      norm.push(p);
    }
    const target = norm.join('/');
    const candidates = [target, target + '.mjs', target + '/index.mjs'];
    const ok = candidates.some((c) => files.has(c));
    if (!ok) {
      brokenImports++;
      console.log(`   BROKEN: ${f} imports ${m[1]} (needs ${candidates[0]})`);
    }
  }
}
check('no broken relative imports inside the bundle', brokenImports === 0,
      brokenImports ? `${brokenImports} broken` : 'the v0.1.2 failure shape, checked on the published bytes');

// ------------------------------------------- the content-list agrees with the tar
console.log('\n== the content-list inside the bundle agrees ==');
const clJson = spawnSync('sh', ['-c',
  `tar xzOf ${JSON.stringify(tarPath)} ./content-list.json`], { encoding: 'utf8' });
if (clJson.status === 0 && clJson.stdout.trim()) {
  const cl = JSON.parse(clJson.stdout);
  const clNames = new Set(cl.entries.map((e) => e.url.replace(/^assets\/llvm-wasm\//, '')));
  const manNames = new Set(man.assets.map((a) => a.name));
  const onlyCl = [...clNames].filter((n) => !manNames.has(n));
  const onlyMan = [...manNames].filter((n) => !clNames.has(n));
  check('content-list entries == manifest assets (same set)',
        onlyCl.length === 0 && onlyMan.length === 0,
        onlyCl.length || onlyMan.length
          ? `only in content-list: ${onlyCl.join(',') || '-'}; only in manifest: ${onlyMan.join(',') || '-'}`
          : `${clNames.size} each`);
} else {
  check('content-list.json present in the bundle', false, 'not found');
}

// ------------------------------------------- the tar matches the repo's driver
// The v0.1.2 failure is one layer subtler than "manifest lists a file the tar
// lacks": the bundle was INTERNALLY consistent (13/13/13 -- its toolchain.mjs
// was the pre-fix version that did not import compile-core yet). What was
// stale was the whole bundle against the code. So internal consistency is not
// enough: the published driver set must equal the repo's driver set, and each
// file's bytes must match what HEAD ships. A release that serves last week's
// code, consistently, is still wrong.
console.log('\n== the bundle driver/ matches the repo driver/ (not just itself) ==');
const FRESH = args.includes('--freshness');
if (!TAG && !FRESH) {
  // tar mode may legitimately check an OLD release; only --tag (serving now)
  // demands freshness. Say so rather than silently skipping.
  console.log('   NOTE: tar mode checks internal consistency only; add --freshness');
  console.log('         to also demand bundle == repo HEAD (what --tag implies).');
} else {
  // The runtime set the release ships: everything EXCEPT the test scripts,
  // which make-release.sh copies then removes (acceptance-*, check-*).
  // Derived the same way (glob minus the same exclusions), never hand-listed --
  // this whole file exists because a hand-written list drifted once already.
  const repoFiles = spawnSync('sh', ['-c',
    'ls driver/*.mjs | grep -vE "(acceptance-|check-)"'], { encoding: 'utf8' });
  if (repoFiles.status !== 0 || !repoFiles.stdout.trim()) {
    check('repo driver/ readable', false, 'ls driver/*.mjs failed');
  } else {
    const repo = repoFiles.stdout.split('\n').map((l) => l.trim()).filter(Boolean).sort();
    const inTar = [...files].filter((f) => f.startsWith('driver/') && f.endsWith('.mjs')).sort();
    const missingInTar = repo.filter((f) => !inTar.includes(f));
    const extraInTar = inTar.filter((f) => !repo.includes(f));
    check('every repo driver .mjs is in the bundle', missingInTar.length === 0,
          missingInTar.length ? `missing: ${missingInTar.join(', ')}`
                              : `${repo.length} files`);
    check('no extra driver files beyond the repo', extraInTar.length === 0,
          extraInTar.length ? `extra: ${extraInTar.join(', ')}` : '');
    // byte-identical? a stale file with the same name is the same failure
    let stale = [];
    for (const f of repo) {
      if (!inTar.includes(f)) continue;
      const tarBytes = spawnSync('sh', ['-c', `tar xzOf ${JSON.stringify(tarPath)} ./${f}`],
        { encoding: 'buffer' }).stdout;
      let repoBytes;
      try { repoBytes = readFileSync(f); } catch { continue; }
      if (!tarBytes.equals(repoBytes)) stale.push(f);
    }
    check('driver files are byte-identical to the repo', stale.length === 0,
          stale.length ? `stale (differs from HEAD): ${stale.join(', ')}` : 'all match');
  }
}

// ------------------------------------------- the pin names this very tag (if --tag)
if (TAG) {
  console.log('\n== the record pins the tag being served ==');
  const pin = man.producer?.pin || '';
  // manifest doesn't carry producer; the content-list does
  const pinSrc = clJson.stdout.trim() ? JSON.parse(clJson.stdout).producer?.pin : '';
  check(`pin "${pinSrc}" names this tag`, pinSrc === `release:${TAG}`,
        pinSrc === `release:${TAG}` ? '' : `expected release:${TAG}`);
}

console.log('-- artifacts');
console.log(`ARTIFACT published_check_pass ${passCount}`);
console.log(`\n=== ${fails === 0 ? 'ALL PASS' : fails + ' FAILED'} ===`);
process.exitCode = fails === 0 ? 0 : 1;
