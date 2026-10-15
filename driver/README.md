# driver/

The thin driver: source in, Emscripten side module out (SPEC §7.4/§7.5).

| Module | Role |
|---|---|
| `compile-core.mjs` | **The pipeline, once.** Validation, the sysroot precheck, step order, argv assembly, the fresh-lld-per-compile lifecycle, the gap check. Takes a runtime through four members (`targetsAvailable` / `clang` / `lld` / `log`) rather than creating one. |
| `toolchain.mjs` | The node adapter. Supplies a sysroot from a bundle or a host directory, and instances via `require`. |
| `abi.mjs` | ABI flag assembly and the §5.4 gap check, plus `memoryIs64`. Shared by both adapters and by the browser worker, so the flags have one source. |
| `sysroot-bundle.mjs` | Bundle loading with sha256 fail-closed (SPEC §9.10). |
| `tar-reader.mjs` | Minimal tar reader, used by the bundle loader and by the browser worker. |

`browser/worker.mjs` is the second adapter over `compile-core.mjs`. Two adapters
exist because the two environments genuinely differ (filesystem source, module
loading). They must not re-implement the pipeline: issue #1's precheck reached
one and not the other, and the failure came back. `check-compile-seam.mjs`
guards that structurally.

`acceptance-*.mjs` and `check-*.mjs` in this directory are the tests, not the
runtime; the release bundle ships the five modules above only.
