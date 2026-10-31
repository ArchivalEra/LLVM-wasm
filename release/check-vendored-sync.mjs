#!/usr/bin/env node
// Is the vendored Einfacht layer still upstream's bytes?
//
// Why this exists (issue #3, user story 19): "zreflect/ is a copy of upstream
// at commit X" was, until now, a claim kept in someone's memory. Every sync
// was followed by a hand-written STATE line and nothing re-checked it, so
// "are we behind?" was unanswerable without redoing the diff by hand.
//
// The rule this repo keeps paying for: a claim about a copy can only be
// checked against the thing it copies. So this script fetches upstream and
// diffs the files themselves.
//
// Two modes:
//
//   --pin        print what this repo records (zreflect/VENDORED.json)
//   (default)    fetch upstream's pinned commit and diff, file by file
//
// The recorded pin also names the files that are EXPECTED to differ: the
// data layer (`measure_*.py`), our own env carrier (`Einfacht.env`), and the
// repo's own q: these are ours, not upstream's, and "differs" is not drift.
//
// Usage:
//   node release/check-vendored-sync.mjs
//   node release/check-vendored-sync.mjs --pin
import { spawnSync } from 'child_process';
import { createHash } from 'crypto';
import { readFileSync, readdirSync, existsSync } from 'fs';
import { join } from 'path';

const PIN_FILE = 'zreflect/VENDORED.json';
const args = process.argv.slice(2);

if (!existsSync(PIN_FILE)) {
  console.error(`FATAL: ${PIN_FILE} 不存在 —— 没有记录「同步的是哪个 commit」`);
  process.exit(2);
}
const pin = JSON.parse(readFileSync(PIN_FILE, 'utf8'));

if (args.includes('--pin')) {
  console.log(`${pin.repo}@${pin.commit}  (synced ${pin.synced})`);
  console.log(`local-only (ours, expected to differ): ${pin.local.join(', ')}`);
  process.exit(0);
}

let fails = 0, passCount = 0;
const check = (what, ok, detail = '') => {
  if (ok) passCount++; else fails++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${what}${detail ? ': ' + detail : ''}`);
};

// ------------------------------------------------- fetch the pinned commit
// Shallow fetch of one commit: fast, and does not require the whole history.
const tmp = `/tmp/vendored-sync-${process.pid}`;
spawnSync('rm', ['-rf', tmp]);
const clone = spawnSync('git', ['clone', '-q', '--depth', '1', '--branch',
  pin.commit, `https://github.com/${pin.repo}`, tmp], { encoding: 'utf8' });
if (clone.status !== 0) {
  // --branch only takes a branch/tag; fall back to init+fetch of the sha.
  spawnSync('sh', ['-c', `git init -q ${tmp} && cd ${tmp} && `
    + `git remote add origin https://github.com/${pin.repo} && `
    + `git fetch -q --depth 1 origin ${pin.commit} && git checkout -q FETCH_HEAD`],
    { encoding: 'utf8' });
}
if (!existsSync(join(tmp, 'zreflect'))) {
  console.error(`FATAL: 拉不到 ${pin.repo}@${pin.commit}（网络或 commit 不存在）`);
  process.exit(2);
}
console.log(`upstream: ${pin.repo}@${pin.commit}`);

// ----------------------------------------------------- diff the two layers
// Both sides are hashed the same way (sha256 of bytes), so "equal" means
// equal as files, not "looks similar". Only zreflect/*.py and
// reflect-hooks/* are compared: those are the two vendored surfaces.
const sha = (p) => createHash('sha256').update(readFileSync(p)).digest('hex');
const localOnly = new Set(pin.local);

const pairs = [];
for (const dir of ['zreflect', 'reflect-hooks']) {
  const upDir = join(tmp, dir);
  if (!existsSync(upDir)) continue;
  for (const f of readdirSync(upDir)) {
    if (f === '__pycache__') continue;
    if (dir === 'zreflect' && !f.endsWith('.py')) continue;
    pairs.push(`${dir}/${f}`);
  }
}

console.log('\n== every upstream file is present locally ==');
const missing = pairs.filter((rel) => !existsSync(rel));
check('no upstream file is missing locally', missing.length === 0,
      missing.length ? `missing: ${missing.join(', ')}` : `${pairs.length} files`);

console.log('\n== files expected to differ (ours, not upstream\'s) ==');
const diverged = [], expected = [];
for (const rel of pairs) {
  if (!existsSync(rel)) continue;
  const same = sha(rel) === sha(join(tmp, rel));
  if (same) continue;
  (localOnly.has(rel) ? expected : diverged).push(rel);
}
check(`the only differing files are the local ones declared in ${PIN_FILE}`,
      diverged.length === 0,
      diverged.length ? `UNEXPECTED drift: ${diverged.join(', ')}`
                      : `${expected.length} declared: ${expected.join(', ')}`);

console.log('\n== the declared local-only files actually exist ==');
const ghosts = [...localOnly].filter((rel) => !existsSync(rel));
check('no declared local-only file is a ghost', ghosts.length === 0,
      ghosts.length ? `declared but absent: ${ghosts.join(', ')}` : '');

console.log('\n== the data layer is not upstream\'s facts.py ==');
// The whole point of REFLECT_MEASURE_MODULE: facts.py is upstream's, the
// measurement lives elsewhere. If facts.py differs from upstream, someone
// forked the mechanism layer again -- the exact thing the sync removed.
const upFacts = join(tmp, 'zreflect/facts.py');
if (existsSync(upFacts) && existsSync('zreflect/facts.py')) {
  check('zreflect/facts.py is byte-identical to upstream', sha('zreflect/facts.py') === sha(upFacts),
        sha('zreflect/facts.py') === sha(upFacts) ? '' : 'mechanism layer was forked again');
}

spawnSync('rm', ['-rf', tmp]);

console.log(`\n=== ${fails === 0 ? 'ALL PASS' : fails + ' FAILED'} === (${passCount + fails})`);
console.log(`ARTIFACT vendored_sync_pass ${passCount}`);
process.exitCode = fails === 0 ? 0 : 1;