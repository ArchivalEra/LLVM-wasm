// Sysroot bundle loading — SPEC §6 (the tar is the delivery form) + §2/§9.10
// (every asset carries a sha256 and the loader fails closed).
//
// In a browser there is no emsdk directory to read from: the sysroot arrives as
// a tar and gets unpacked into the wasm instance's memory filesystem. This
// module owns that path, plus the digest check, so the driver can accept either
// a host directory (development) or a bundle (delivery).
import { readFileSync, existsSync } from 'fs';
import { createHash } from 'crypto';
import { readTar } from './tar-reader.mjs';

/**
 * Verify a bundle against its manifest entry, then unpack it.
 *
 * Fail-closed is the point (SPEC §9.10): a mismatch throws rather than warning,
 * because a tampered or truncated asset that still loads is the failure this
 * whole mechanism exists to prevent.
 */
export function loadBundle({ tarPath, manifestPath, assetName, expectSha256 }) {
  if (!existsSync(tarPath)) throw new Error(`sysroot tar missing: ${tarPath}`);
  const bytes = readFileSync(tarPath);

  let want = expectSha256;
  if (!want && manifestPath) {
    if (!existsSync(manifestPath)) throw new Error(`manifest missing: ${manifestPath}`);
    const man = JSON.parse(readFileSync(manifestPath, 'utf8'));
    const entry = man.assets.find((a) => a.name === assetName
      || a.name === tarPath.split('/').pop());
    if (!entry) throw new Error(`manifest has no asset for ${assetName || tarPath}`);
    want = entry.sha256;
    // bytes is a second, independent assertion in the same manifest
    if (entry.bytes != null && entry.bytes !== bytes.length) {
      throw new Error(`manifest bytes=${entry.bytes} but file is ${bytes.length} — refusing`);
    }
  }
  if (!want) throw new Error('no sha256 to check against (pass expectSha256 or a manifest)');

  const got = createHash('sha256').update(bytes).digest('hex');
  if (got !== want) {
    throw new Error(`sha256 mismatch — refusing to load.\n  expected ${want}\n  got      ${got}`);
  }

  const files = readTar(bytes);
  if (files.size === 0) throw new Error('bundle unpacked to zero files — refusing (zero-value guard)');
  return { files, sha256: got, bytes: bytes.length };
}

/**
 * Write an unpacked bundle into an emscripten FS, rooted at `prefix`.
 * Returns the number of files written.
 */
export function installBundle(fs, files, prefix = '') {
  let n = 0;
  for (const [rel, data] of files) {
    const dst = `${prefix}/${rel}`.replace(/\/+/g, '/');
    const dir = dst.slice(0, dst.lastIndexOf('/'));
    if (dir) fs.mkdirTree(dir);
    fs.writeFile(dst, data);
    n++;
  }
  return n;
}
