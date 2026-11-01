Same payloads as v0.1.4, now also published in the split form the static-distribution contract asks for. Nothing about the toolchain changed: same clang/lld bytes, same sysroots, same driver.

**Two forms under this tag, both kept**

- `llvm-wasm-bundle-v0.1.5.tar.gz` — the whole bundle, unchanged in shape. Its `manifest.json` lives *inside* the tarball; that is what the host's provision script reads, so it stays.
- `manifest.json` at the top level — the contract's schema 2 (14 entries, 105 flat assets, three codecs each). Chunks are ≤ 5 MiB and named without slashes.

They do not collide: one is inside the tarball, the other is a top-level asset.

**Why split**

EdgeOne slows down between 10 and 20 MB (measured upstream: 20.9 MB and 29.6 MB both fall to ~0.93 MB/s). This bundle was a single 34.7 MB download.

- zstd total **26,683,734 B** (vs 34,694,086) — 23% less
- gzip total 34,496,917 B
- identity total 122,967,501 B (fallback, not for first pull)
- largest chunk **5,242,880 B** — exactly at the contract's hard limit

**Client note, worth reading before you implement**

zstd chunks are **independent frames**. Concatenating them and calling a single-shot `decompress()` mismatches on every multi-chunk payload and passes on every single-chunk one — so the bug hides on small assets and only shows up on `clang.wasm`, `lld-wasm-only.wasm` and the two sysroot tars. Decode **per chunk, then concatenate**. The contract's rule 5 ("each chunk decodes independently") is right; this is the implementation detail that follows from it.

**Verification**

- Contract checker: `634 PASS / 0 FAIL` (`check-release-v4.py`, run twice).
- Independent pass, not using their checker: gzip 14/14 and zstd 14/14 — per-chunk sha256 *and* whole-entry sha256 after concatenation.
- Tarball form: `check-published.mjs --tar ... --freshness` — 20 PASS, byte-identical to HEAD.
- Every chunk's sha256, byte count and byte-boundary is in `manifest.json`; nothing needs to trust this note.

**Not in this release:** the repo-internal cleanup (vendored fact-system layer sync, lint remediation). It touches nothing that ships here.

**bundle_sha256:** `90f06147c10d64194e2f4924a85809d82ff995d39b7ea529e2cd0d4e554d0c44`
