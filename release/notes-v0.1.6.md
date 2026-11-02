No payload changed. This release upgrades the manifest to contract v1.1 (schema 3), which adds a licence declaration.

**Same bytes as v0.1.5**

Same emsdk 6.0.12, same clang/lld, same sysroots, same driver, same 14 payloads and the same 105 chunks -- `release/payloads.json` and every per-chunk sha256 are unchanged. If you already have v0.1.5's chunks, you have v0.1.6's payload bytes.

**What is new is the licence**

The release is not uniform, so it is declared per entry, not as one expression:

| Payload | Licence |
|---|---|
| `clang.wasm`, `lld-wasm-only.wasm`, `LICENSE-LLVM.txt` | `Apache-2.0 WITH LLVM-exception` |
| `clang.js`, `lld-wasm-only.js`, `LICENSE-EMSCRIPTEN.txt` | `MIT OR NCSA` |
| `sysroot-headers.tar`, `sysroot-headers.wasm64.tar` | `(Apache-2.0 WITH LLVM-exception) AND (MIT OR NCSA)` |
| `driver/*.mjs` (5), `LICENSE` | `AGPL-3.0-or-later` |

Top-level `license.id` is the three-way conjunction. A client's rule is one line: `entry.license ?? manifest.license.id`.

Two things worth stating because they were nearly wrong:

- `LICENSE-LLVM.txt` is Apache-2.0 **plus** the LLVM Exception section, not plain Apache-2.0; declaring it plain would drop the exception downstream.
- `LICENSE-EMSCRIPTEN.txt` says "MIT license and the University of Illinois/NCSA Open Source License" in its first paragraph. NCSA is a distinct SPDX identifier -- not BSD-3-Clause.

All four identifiers (plus `LLVM-exception`) are checked against the official SPDX list; `release/licenses.json` records the source.

**Verification**

- Generation, upgrade and checking all use the contract repo's tools (`make-manifest-v4.py`, `upgrade-manifest-license.py`, `check-release-v4.py`); this repo owns only the licence mapping as data.
- The upgrade asserts byte identity is untouched: only `schema`, `license` and `role` may change. If any payload name, size or hash moved, it refuses to write.
- `697 PASS / 0 FAIL` from the contract checker, schema 3, with `--base` reading every chunk off disk.
- The release contains exactly the manifest's asset set -- 105 chunks plus `manifest.json`, nothing else.

Previously released tags v0.1.0-v0.1.4 use the pre-contract schema 1 format and are not converted: release history is not rewritten.
