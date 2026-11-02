This release declares licences. The manifest is now contract v1.1 (schema 3), which makes a licence declaration compulsory; every payload carries its own.

**Same toolchain as the previous build**

Same emsdk 6.0.12, same clang/lld, same sysroots, same driver, same 14 payloads, same 105 chunks -- `release/payloads.json` and every per-chunk sha256 are unchanged from the previous build of this toolchain.

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

**On v0.1.5 being gone**

v0.1.5 has been withdrawn. Schema 2 is legitimate when a payload genuinely
cannot state its licence -- the format exists so such resources can still
travel under the contract. v0.1.5 was not that case: its 14 payloads carry three
identifiable licences, including three licence texts inside the release itself,
and the manifest declared none of them (14 entries with no licence field, no
top-level licence). That is an incomplete declaration, not an honest silence.
Every payload byte is present in v0.1.6, so nothing is lost by the withdrawal.

Previously released tags v0.1.0-v0.1.4 use the pre-contract schema 1 format and are not converted: release history is not rewritten.
