# Cutting a release

```sh
bash release/make-release.sh            # assemble the bundle + manifest
node release/check-release.mjs          # consumer acceptance: opens the SHIPPED files
bash release/check-wasm64-e2e.sh        # wasm64: bundle -> real host dlopen

cd release/out && tar -czf ../llvm-wasm-bundle-vX.Y.Z.tar.gz . && cd ../..
gh release create vX.Y.Z \
  --title "vX.Y.Z — <one line>" \
  --notes-file /tmp/notes.md \
  release/llvm-wasm-bundle-vX.Y.Z.tar.gz release/out/manifest.json
```

Stage the notes in a file, never inline: the shell mangles backticks and `#`.

## Release notes convention

- **English only.** The repo's docs are Chinese; the releases are not.
- **Concise.** What changed, how it was verified, what is in the bundle. No narrative,
  no restating the repo's own rules.
- **The title and the first line of the body must not say the same thing.** GitHub
  renders them one above the other, so a repeat burns the only line a reader is
  guaranteed to see.
- **Name a limitation rather than hiding it** (see v0.1.0's note that its bundle
  carries only the wasm32 sysroot). A release that is wrong is kept and annotated;
  history is not rewritten.
- Verification claims carry the number and how to re-run them; the full record stays
  in the repo (`STATE.md`, `RESULTS.md`).

## What the numbers in the notes must be

Every byte count and pass count in a release note comes from the manifest or from a
suite's `ARTIFACT` line — not from memory. `release/check-release.mjs` prints the
bundle's own figures, so paste from there.
