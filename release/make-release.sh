#!/usr/bin/env bash
# Build the release bundle and its manifest (SPEC §2 + §8).
#
# SPEC §2 lists the deliverables and requires manifest.json to carry, per asset:
# name, bytes, sha256, and **license**. §8 adds the toolchain version string and
# the host baseline version string (the host's is what the contract must match,
# so this records what we knew at packaging time and the loader checks the live
# host against it at compile time).
#
# Licenses are split, not chosen (SPEC §2): the LLVM-derived wasm binaries are
# Apache-2.0 WITH LLVM-exception; the emscripten-derived glue is MIT/NCSA; this
# repo's own scripts are AGPL-3.0. Putting AGPL on clang.wasm would hand the
# downstream a source-provision obligation for code that is not ours; putting
# Apache on our glue gives it away.
#
# Usage: bash release/make-release.sh [--skip-host]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/release/out"
EMSDK="${EMSDK:-$ROOT/toolchain/emsdk}"

# Artefacts. The optimized clang if the neighbour's build is present, else ours.
CLANG_BIN="$ROOT/m1/build-exp-lean_nosjlj/bin"
[ -f "$CLANG_BIN/clang.js" ] || CLANG_BIN="$ROOT/m1/build-clang/bin"
LLD_BIN="$ROOT/m1/build-lld/bin"
LLD_JS="lld-wasm-only.js"
[ -f "$LLD_BIN/$LLD_JS" ] || LLD_JS="lld.js"
LLD_WASM="${LLD_JS%.js}.wasm"
# Both arches ship (issue #1). A wasm32 sysroot cannot link a wasm64 module --
# it has no lib/wasm64-emscripten/pic/crtbegin-mt.o -- and the resulting module
# lacks _emscripten_tls_init, which a threaded host rejects with "tlsInitFunc is
# not a function". Shipping one tar and hoping the caller notices is how that
# reaches production.
SYSROOT32="$ROOT/package/out/sysroot-wasm32.tar"
SYSROOT64="$ROOT/package/out/sysroot-wasm64.tar"

for f in "$CLANG_BIN/clang.wasm" "$CLANG_BIN/clang.js" "$LLD_BIN/$LLD_WASM" "$LLD_BIN/$LLD_JS" "$SYSROOT32" "$SYSROOT64"; do
  [ -f "$f" ] || { echo "FATAL: missing artefact $f"; exit 2; }
done

rm -rf "$OUT"; mkdir -p "$OUT"

echo "== copying artefacts =="
cp "$CLANG_BIN/clang.wasm"      "$OUT/clang.wasm"
cp "$CLANG_BIN/clang.js"        "$OUT/clang.js"
# ⚠️ Copy under their real names, and have the manifest record those names. A
# bundle whose filenames disagree with its manifest is unusable: the consumer
# looks up what the manifest says (measured: MODULE_NOT_FOUND lld-wasm-only.js
# when we shipped the file as lld.js).
cp "$LLD_BIN/$LLD_WASM"         "$OUT/$LLD_WASM"
cp "$LLD_BIN/$LLD_JS"           "$OUT/$LLD_JS"
# wasm32 keeps the historical name; wasm64 gets an explicit suffix.
cp "$SYSROOT32"                 "$OUT/sysroot-headers.tar"
cp "$SYSROOT64"                 "$OUT/sysroot-headers.wasm64.tar"
# ⚠️ Keep the original filenames: toolchain.mjs imports ./sysroot-bundle.mjs and
# ./abi.mjs by relative path, so renaming on copy breaks the bundle (measured:
# ERR_MODULE_NOT_FOUND sysroot-bundle.mjs). A "driver-*" prefix reads nicer in a
# listing and costs a broken deliverable.
mkdir -p "$OUT/driver"
for m in toolchain abi tar-reader sysroot-bundle; do cp "$ROOT/driver/$m.mjs" "$OUT/driver/"; done
cp "$ROOT/LICENSE"              "$OUT/LICENSE"
cp "$ROOT/LICENSE-LLVM.txt"     "$OUT/LICENSE-LLVM.txt"
cp "$ROOT/LICENSE-EMSCRIPTEN.txt" "$OUT/LICENSE-EMSCRIPTEN.txt"

LLD_JS="$LLD_JS" LLD_WASM="$LLD_WASM" python3 - "$OUT" "$EMSDK" "$ROOT" <<'PY'
import hashlib, json, os, subprocess, sys, time

out, emsdk, root = sys.argv[1:4]
lld_js = os.environ['LLD_JS']
lld_wasm = os.environ['LLD_WASM']

def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as fh:
        for b in iter(lambda: fh.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()

def brotli_bytes(p):
    try:
        import brotli
        with open(p, 'rb') as fh:
            return len(brotli.compress(fh.read(), quality=11))
    except Exception:
        return None

def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, shell=True).stdout.strip()
    except Exception:
        return 'unknown'

# Licenses per asset, split as SPEC §2 requires.
LLVM = 'Apache-2.0 WITH LLVM-exception'
EMCC = 'MIT OR NCSA (Emscripten)'
OURS = 'AGPL-3.0-or-later (this repo)'

ASSETS = [
    ('clang.wasm', LLVM, 'C/C++ frontend, LLVM-derived wasm binary', True),
    (lld_wasm, LLVM, 'wasm-ld linker, LLVM-derived wasm binary', True),
    ('sysroot-headers.tar', 'mixed (see LICENSE-LLVM.txt, LICENSE-EMSCRIPTEN.txt)',
     'emscripten sysroot, wasm32: include/ + lib/wasm32-emscripten/pic/crtbegin-mt.o '
     '(SPEC §5.1, §6)', True),
    ('sysroot-headers.wasm64.tar', 'mixed (see LICENSE-LLVM.txt, LICENSE-EMSCRIPTEN.txt)',
     'emscripten sysroot, wasm64: include/ + lib/wasm64-emscripten/pic/crtbegin-mt.o. '
     'include/ is arch-shared, so this differs from the wasm32 tar only in the crt.',
     True),
    ('clang.js', EMCC, 'emscripten glue for clang.wasm', False),
    (lld_js, EMCC, 'emscripten glue for the lld wasm above', False),
    ('driver/toolchain.mjs', OURS, 'thin driver: compile() per SPEC §7.4/§7.5', False),
    ('driver/abi.mjs', OURS, 'ABI flag assembly + §5.4 gap check (shared with the browser worker)', False),
    ('driver/tar-reader.mjs', OURS, 'tar reader (shared with the browser worker)', False),
    ('driver/sysroot-bundle.mjs', OURS, 'bundle loading + sha256 fail-closed (SPEC §9.10)', False),
    ('LICENSE', OURS, 'this repo license', False),
    ('LICENSE-LLVM.txt', LLVM, 'LLVM upstream license text (verbatim)', False),
    ('LICENSE-EMSCRIPTEN.txt', EMCC, 'emscripten upstream license text (verbatim)', False),
]

emcc_ver = run(f'{emsdk}/upstream/emscripten/emcc --version | head -1')
clang_ver = run(f'{emsdk}/upstream/bin/clang --version | head -1')

man = {
    'schema': 1,
    'generated': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
    '_why': 'SPEC §2: per-asset name + bytes + sha256 + license. SPEC §8: toolchain '
            'and host-baseline version strings. The loader checks sha256 before use '
            'and fails closed (SPEC §9.10).',
    'toolchain': {
        'emcc': emcc_ver,
        'clang': clang_ver,
        'llvm_source_commit': '55ea1f4ebea23d0355d5cdb075f1e12f28ab82d0',
        'lld_glue': lld_js,
        'targets_built': ['wasm32', 'wasm64'],
        # One toolchain serves both: the same clang.wasm emits 64-bit objects
        # (memory limits flag 0x04 verified) and the same lld.wasm links them
        # with -mwasm64. What differs per arch is only the sysroot's pic/
        # subtree, which is why both tars ship and the driver selects by target.
        'sysroots': {
            'wasm32': 'sysroot-headers.tar',
            'wasm64': 'sysroot-headers.wasm64.tar',
        },
    },
    'host_baseline': {
        '_why': 'SPEC §8: the judgment is contract equality, not version-string '
                'equality. These are the four axes the loader must confirm against '
                'the live host; the version strings below are recorded, not enforced.',
        'exceptions': 'wasm-legacy',
        'pthread': True,
        'memory64': False,
        'main_module': 2,
        'recorded_at_packaging': {
            'emscripten': '6.0.12 (per the migration in flight downstream)',
            'note': 'downstream was migrating 5.0.7 -> 6.0.12; the toolchain was built '
                    'on 6.0.12 and its products dlopen in both (measured M0/M1).',
        },
    },
    'assets': [],
}

for name, lic, desc, brotli in ASSETS:
    p = os.path.join(out, name)
    e = {'name': name, 'bytes': os.path.getsize(p), 'sha256': sha256(p),
         'license': lic, 'description': desc}
    if brotli:
        b = brotli_bytes(p)
        if b:
            e['brotli_bytes'] = b
    man['assets'].append(e)

# first-load accounting, since §6's budget is stated for the first pull
# A host pulls ONE sysroot -- the one matching its arch -- so the budget counts
# one, not both. Recorded per arch so a wasm64 host can see its own number.
def fl_for(sysroot_name):
    names = ('clang.wasm', 'clang.js', sysroot_name)
    items = [a for a in man['assets'] if a['name'] in names]
    return {'assets': list(names),
            'brotli_bytes': sum(a.get('brotli_bytes') or a['bytes'] for a in items)}

man['first_load'] = {
    '_why': 'SPEC §6 budget: brotli <= 15 MB for the FIRST PULL; lld arrives on '
            'first link (lazy shard). A host pulls the sysroot for its own arch, '
            'so the number is per-arch.',
    **fl_for('sysroot-headers.tar'),
    'per_arch': {
        'wasm32': fl_for('sysroot-headers.tar')['brotli_bytes'],
        'wasm64': fl_for('sysroot-headers.wasm64.tar')['brotli_bytes'],
    },
}
lld = next(a for a in man['assets'] if a['name'].startswith('lld') and a['name'].endswith('.wasm'))
man['first_load']['plus_lld_brotli_bytes'] = man['first_load']['brotli_bytes'] + (lld.get('brotli_bytes') or lld['bytes'])

with open(os.path.join(out, 'manifest.json'), 'w') as fh:
    json.dump(man, fh, indent=1, ensure_ascii=False)
    fh.write('\n')

print(f"manifest: {os.path.join(out, 'manifest.json')}")
for a in man['assets']:
    br = f" brotli={a['brotli_bytes']}" if 'brotli_bytes' in a else ''
    print(f"  {a['name']:<28} {a['bytes']:>10}{br}  {a['license']}")
print()
print(f"ARTIFACT release_assets {len(man['assets'])}")
print(f"ARTIFACT release_clang_wasm {next(a for a in man['assets'] if a['name']=='clang.wasm')['bytes']}")
print(f"ARTIFACT release_lld_wasm {lld['bytes']}")
print(f"ARTIFACT release_first_load_brotli {man['first_load']['brotli_bytes']}")
print(f"ARTIFACT release_total_brotli {man['first_load']['plus_lld_brotli_bytes']}")
PY

# ------------------------------------------------- the content-list (seam record)
# One producer, two outputs: this derives the seam record from the manifest we
# just wrote, so no number in it is a second transcription. Committed at
# release/content-list.json (tracked); the bundle carries the same file so it
# travels with the bytes it describes.
node "$ROOT/release/make-content-list.mjs" "$OUT" "$OUT/content-list.json" \
  --pin "${CONTENT_LIST_PIN:-$(cd "$ROOT" && git describe --tags --always 2>/dev/null || echo unknown)}"
cp "$OUT/content-list.json" "$ROOT/release/content-list.json"

echo "== bundle at $OUT =="
ls -la "$OUT"
