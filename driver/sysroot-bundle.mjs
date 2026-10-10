// Sysroot bundle loading — SPEC §6 (the tar is the delivery form) + §2/§9.10
// (every asset carries a sha256 and the loader fails closed).
//
// In a browser there is no emsdk directory to read from: the sysroot arrives as
// a tar and gets unpacked into the wasm instance's memory filesystem. This
// module owns that path, plus the digest check, so the driver can accept either
// a host directory (development) or a bundle (delivery).
import { readFileSync, existsSync } from 'fs';
import { createHash } from 'crypto';

/**
 * Read a tar (uncompressed) into {path: Buffer}.
 *
 * Deliberately small: we control both ends of this format (package-sysroot.sh
 * writes it), and a full tar implementation is not worth carrying into a
 * browser bundle. It handles regular files, directories and the PAX/GNU
 * extensions `tar -cf` actually emits for long names.
 */
export function readTar(buf) {
  const out = new Map();
  let off = 0;
  let pendingLongName = null;
  const str = (b, s, n) => b.toString('utf8', s, s + n).replace(/\0.*$/, '');
  while (off + 512 <= buf.length) {
    const header = buf.subarray(off, off + 512);
    if (header.every((b) => b === 0)) break;               // end-of-archive
    const name = str(header, 0, 100);
    const sizeField = str(header, 124, 12).trim();
    const size = parseInt(sizeField, 8) || 0;
    const type = String.fromCharCode(header[156] || 48);
    const prefix = str(header, 345, 155);
    let full = prefix ? `${prefix}/${name}` : name;
    off += 512;
    const data = buf.subarray(off, off + size);
    off += Math.ceil(size / 512) * 512;

    if (type === 'L') {                                     // GNU long name
      pendingLongName = data.toString('utf8').replace(/\0.*$/, '');
      continue;
    }
    if (type === 'x' || type === 'g') continue;              // PAX headers
    if (type === '5') continue;                              // directory
    if (pendingLongName) { full = pendingLongName; pendingLongName = null; }
    out.set(full.replace(/^\.\//, ''), Buffer.from(data));
  }
  return out;
}

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
