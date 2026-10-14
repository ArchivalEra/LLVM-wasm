#!/usr/bin/env bash
# Package the sysroot subset the toolchain actually needs (SPEC §6).
#
# SPEC §6 says: ship only what §4.1/§4.2 actually read, not all of lib/ (582 MB
# of .a variants, none of which a side module links). This script measures the
# payload rather than guessing it, and emits a manifest with per-asset sha256
# (SPEC §2, §9.10).
#
# What goes in, and why:
#   include/            the whole header tree -- different sources pull different
#                       headers, so trimming by "what one fixture opened" would
#                       break the next user (measured: one 6-include fixture
#                       opened 680 headers).
#   pic/crtbegin-mt.o   the only pic/ member the §4.2 link line names. The other
#                       31 files in pic/ are .a archives (54 MB) that a side
#                       module does not link (SPEC §5.1).
#
# Usage: sh package/package-sysroot.sh [wasm32|wasm64]
#        SYSROOT_EXTRA_EXCLUDE="SDL GL GLES2 GLES3 X11 GLFW" sh package/package-sysroot.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EMSDK="${EMSDK:-$ROOT/toolchain/emsdk}"
SR="$EMSDK/upstream/emscripten/cache/sysroot"
ARCH="${1:-wasm32}"
OUT="$ROOT/package/out"
LIBDIR="lib/${ARCH}-emscripten"

case "$ARCH" in
  wasm32|wasm64) ;;
  *) echo "usage: $0 [wasm32|wasm64]"; exit 2 ;;
esac

[ -d "$SR/include" ] || { echo "FATAL: sysroot missing at $SR"; exit 2; }

# wasm64's sysroot is generated on demand (SPEC §6 measured note): a plain
# wasm64 compile creates it. Say so instead of silently shipping a wasm32 tree
# under a wasm64 name.
if [ "$ARCH" = wasm64 ] && [ ! -d "$SR/$LIBDIR" ]; then
  echo "FATAL: $SR/$LIBDIR does not exist."
  echo "       wasm64's sysroot is generated on demand -- run one wasm64 compile first:"
  echo "         $EMSDK/upstream/bin/clang --target=wasm64-unknown-emscripten \\"
  echo "           --sysroot=$SR -c /dev/null -o /dev/null   # (any wasm64 TU)"
  exit 2
fi

STAGE="$OUT/stage-$ARCH"
rm -rf "$STAGE"; mkdir -p "$STAGE/sysroot"

echo "== staging $ARCH =="
cp -a "$SR/include" "$STAGE/sysroot/include"

# optional trimming (off by default: a user's .oct may well include <GL/gl.h>)
if [ -n "${SYSROOT_EXTRA_EXCLUDE:-}" ]; then
  for d in $SYSROOT_EXTRA_EXCLUDE; do
    if [ -d "$STAGE/sysroot/include/$d" ]; then
      echo "   excluding include/$d (SYSROOT_EXTRA_EXCLUDE)"
      rm -rf "$STAGE/sysroot/include/$d"
    fi
  done
fi

mkdir -p "$STAGE/sysroot/$LIBDIR/pic"
CRT="$SR/$LIBDIR/pic/crtbegin-mt.o"
[ -f "$CRT" ] || { echo "FATAL: $CRT missing (run one compile of this target first)"; exit 2; }
cp -a "$CRT" "$STAGE/sysroot/$LIBDIR/pic/"

# ------------------------------------------------------------ licence notices
# The tar ships 1,578 files of which 442 carry no licence statement of their own
# (measured; libc++ headers have SPDX lines, emscripten's musl-derived headers
# mostly do not). MIT/NCSA require the notice to travel with the distribution,
# so a tar handed to a consumer without these files leaves the recipient unable
# to tell what the contents are licensed under. Three files fix it, and NOTICE
# says which part maps to which licence.
cp "$ROOT/LICENSE-LLVM.txt" "$STAGE/sysroot/LICENSE-LLVM.txt"
cp "$ROOT/LICENSE-EMSCRIPTEN.txt" "$STAGE/sysroot/LICENSE-EMSCRIPTEN.txt"
cat > "$STAGE/sysroot/NOTICE" <<'NOTICE'
This sysroot subset is derived from the Emscripten SDK.

  include/c++/v1/            libc++            Apache-2.0 WITH LLVM-exception
                             (most files carry an SPDX-License-Identifier line)
  include/ (the rest)        Emscripten / musl  MIT or University of Illinois/NCSA
  include/SDL/               SDL                zlib licence (see COPYING there)
  lib/<target>-emscripten/pic/crtbegin-mt.o
                             compiler-rt       Apache-2.0 WITH LLVM-exception

Full texts: LICENSE-LLVM.txt (LLVM), LICENSE-EMSCRIPTEN.txt (Emscripten).
Files without an inline notice are covered by the corresponding text above.
NOTICE


# ---------------------------------------------------------------- the archive
mkdir -p "$OUT"
TAR="$OUT/sysroot-$ARCH.tar"
tar -C "$STAGE" -cf "$TAR" sysroot
echo "   tar: $TAR ($(stat -c%s "$TAR") bytes)"

# ------------------------------------------------------- per-asset digest (2)
sha256sum "$TAR" > "$TAR.sha256"

# --------------------------------------------- manifest for the toolchain (2)
python3 - "$TAR" "$ARCH" "$SR" <<'PY'
import hashlib, json, os, subprocess, sys, time

tar, arch, sr = sys.argv[1], sys.argv[2], sys.argv[3]

def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as fh:
        for b in iter(lambda: fh.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()

def brotli_size(p):
    try:
        import brotli
        with open(p, 'rb') as fh:
            return len(brotli.compress(fh.read(), quality=11))
    except Exception:
        return None

# Count what actually went in (measured, not asserted).
n_headers = sum(len(fs) for _, _, fs in os.walk(os.path.join(os.path.dirname(tar), f'stage-{arch}', 'sysroot', 'include')))

emcc_ver = subprocess.run(
    [os.path.join(sr, '..', '..', 'emcc'), '--version'],
    capture_output=True, text=True).stdout.split('\n')[0] if os.path.exists(
    os.path.join(sr, '..', '..', 'emcc')) else 'unknown'

man = {
    "schema": 1,
    "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "_why": "SPEC 2/9.10: every asset carries bytes + sha256 so the loader can "
            "fail closed. Numbers here are measured at package time.",
    "toolchain": {
        "emcc": emcc_ver,
        "arch": arch,
        "llvm_target": f"{arch}-unknown-emscripten",
    },
    "assets": [
        {
            "name": os.path.basename(tar),
            "bytes": os.path.getsize(tar),
            "sha256": sha256(tar),
            "brotli_bytes": brotli_size(tar),
            "contains": {
                "headers": n_headers,
                "pic_objects": 1,
                "note": "include/ tree + pic/crtbegin-mt.o only; .a archives excluded (SPEC 5.1)",
            },
        },
    ],
}
out = os.path.join(os.path.dirname(tar), f'manifest-{arch}.json')
with open(out, 'w') as fh:
    json.dump(man, fh, indent=1, ensure_ascii=False)
    fh.write('\n')
print(f"   manifest: {out}")

a = man["assets"][0]
print(f"ARTIFACT sysroot_{arch}_tar {a['bytes']}")
print(f"ARTIFACT sysroot_{arch}_tar_sha256 {a['sha256']}")
if a["brotli_bytes"]:
    print(f"ARTIFACT sysroot_{arch}_tar_brotli {a['brotli_bytes']}")
print(f"ARTIFACT sysroot_{arch}_headers {n_headers}")
PY

echo "== done: $TAR =="
