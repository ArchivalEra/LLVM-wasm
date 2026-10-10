// Fail-closed verification for the delivered sysroot bundle (SPEC §2 / §9.10).
//
// SPEC §9.10: "篡改任一资产字节 ⇒ 加载器**拒绝**（sha256 fail-closed）".
// A warning is not a refusal, so each case below asserts the REASON as well as
// the rejection.
//
// ⚠️ Why the reason matters: the first version of this test compared paths and
// passed because the manifest lookup failed on a name mismatch, not because the
// digest was checked. A rejection for the wrong reason is a gate pretending to
// pass. Every case here uses the same basename and an explicit digest, so the
// only possible cause is the digest itself -- and a control case proves the
// honest file still loads.
//
// Usage: node driver/check-fail-closed.mjs [--tar <f>] [--manifest <f>]
import { readFileSync, writeFileSync, copyFileSync, mkdirSync, existsSync } from 'fs';
import { join, dirname, basename } from 'path';
import { loadBundle } from './sysroot-bundle.mjs';

const ROOT = join(dirname(new URL(import.meta.url).pathname), '..');
const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : dflt;
};
const TAR = opt('--tar', join(ROOT, 'package/out/sysroot-wasm32.tar'));
const MAN = opt('--manifest', join(ROOT, 'package/out/manifest-wasm32.json'));

let fails = 0, passCount = 0;
const check = (what, ok, detail = '') => {
  if (ok) passCount++; else fails++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${what}${detail ? ': ' + detail : ''}`);
};

if (!existsSync(TAR) || !existsSync(MAN)) {
  console.error(`FATAL: need both ${TAR} and ${MAN} (run package/package-sysroot.sh first)`);
  process.exit(2);
}

const man = JSON.parse(readFileSync(MAN, 'utf8'));
const SHA = man.assets[0].sha256;
const WORK = '/tmp/llvm-wasm-failclosed';
mkdirSync(WORK, { recursive: true });
// same basename as the real asset ⇒ a name mismatch cannot be the cause
const workTar = join(WORK, basename(TAR));
const workMan = join(WORK, basename(MAN));
const honest = readFileSync(TAR);

// ---------------------------------------------------------------- 1. control
console.log('== control: the honest bundle loads ==');
try {
  const r = loadBundle({ tarPath: TAR, expectSha256: SHA });
  check('honest bundle loads', r.files.size > 0, `${r.files.size} files`);
} catch (e) { check('honest bundle loads', false, e.message); }

// ------------------------------------------------------------ 2. tampered byte
console.log('\n== tampered byte (same name, explicit digest) ==');
const tampered = Buffer.from(honest);
tampered[tampered.length - 700] ^= 0xff;
writeFileSync(workTar, tampered);
try {
  loadBundle({ tarPath: workTar, expectSha256: SHA });
  check('tampered bundle refused', false, 'IT LOADED — fail-closed is broken');
} catch (e) {
  const m = e.message.split('\n')[0];
  check('tampered bundle refused by digest', m.includes('sha256 mismatch'), m);
}

// --------------------------------------------------------------- 3. truncated
console.log('\n== truncated file ==');
writeFileSync(workTar, tampered.subarray(0, 1000));
try {
  loadBundle({ tarPath: workTar, expectSha256: SHA });
  check('truncated bundle refused', false, 'IT LOADED');
} catch (e) {
  const m = e.message.split('\n')[0];
  check('truncated bundle refused by digest', m.includes('sha256 mismatch'), m);
}

// --------------------------------------------------- 4. tampered, via manifest
console.log('\n== tampered byte, verified through the manifest ==');
copyFileSync(MAN, workMan);
writeFileSync(workTar, tampered);
try {
  loadBundle({ tarPath: workTar, manifestPath: workMan });
  check('manifest path also refuses tampering', false, 'IT LOADED');
} catch (e) {
  const m = e.message.split('\n')[0];
  check('manifest path also refuses tampering', m.includes('sha256 mismatch'), m);
}

// ------------------------------------------------------ 5. manifest bytes lie
console.log('\n== manifest whose byte count disagrees with the file ==');
const lyingMan = JSON.parse(JSON.stringify(man));
lyingMan.assets[0].bytes = honest.length + 1;
writeFileSync(workMan, JSON.stringify(lyingMan));
writeFileSync(workTar, honest);           // the file itself is honest
try {
  loadBundle({ tarPath: workTar, manifestPath: workMan });
  check('byte-count disagreement refused', false, 'IT LOADED');
} catch (e) {
  const m = e.message.split('\n')[0];
  check('byte-count disagreement refused', m.includes('bytes='), m);
}

// ---------------------------------------------------- 6. missing manifest file
console.log('\n== missing manifest must not silently skip the check ==');
try {
  loadBundle({ tarPath: workTar, manifestPath: join(WORK, 'no-such.json') });
  check('missing manifest refused', false, 'IT LOADED WITHOUT A CHECK');
} catch (e) {
  const m = e.message.split('\n')[0];
  check('missing manifest refused', m.includes('manifest missing'), m);
}

console.log('-- artifacts');
console.log(`ARTIFACT fail_closed_pass ${passCount}`);
console.log(`\n=== ${fails === 0 ? 'ALL PASS' : fails + ' FAILED'} ===`);
process.exitCode = fails === 0 ? 0 : 1;
