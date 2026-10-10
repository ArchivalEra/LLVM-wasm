#!/usr/bin/env python3
"""Re-link the EXISTING objects with different link-time flags.

Why this is the cheapest real experiment available: the whole point of ccache is
that we never pay for the same compile twice, but there is an even cheaper tier
than a ccache hit -- re-use the objects already on disk from a previous build and
change only what the *linker* sees (`-Oz`, `-flto`, emscripten `-s` settings).
Emscripten's link step runs the binaryen optimizer over the whole module, so the
post-link knobs are genuinely independent of the compile flags.

Two hard-won details, both measured (see m1/OPT-RESULTS.md §3):

  * ninja writes the link as `: && em++ ... -o bin/x.js-N && :`. The trailing
    `&& :` must be dropped or em++ reports `error: &&: No such file or directory`.
  * The inherited link line carries CMake's compile-time `-O` flags. emcc honours
    the LAST `-O`, so the baseline (`CMAKE_C_FLAGS=-O1` plus Release's `-O3`)
    actually links at **-O3**. Appending our own `-Oz` therefore overrides it,
    and we keep every other flag byte-identical to ninja -> the A/B is clean.

Usage:
  python3 m1/exp-relink.py --tool clang --name relink_oz --build m1/build-clang \\
      --emcc-flags "-Oz"
"""
import argparse
import os
import re
import shlex
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMSDK = os.environ.get("EMSDK", os.path.join(ROOT, "toolchain/emsdk"))
EM = os.path.join(EMSDK, "upstream/emscripten")


def nm_command(build, tool, out_js):
    """ninja's own link command, so we inherit the exact library list.

    `ninja -t commands <target>` prints every command in the target's closure
    (3124 of them here), so select the one that drives em++ to bin/<tool>.js.
    """
    r = subprocess.run(["ninja", "-t", "commands", f"bin/{tool}.js"],
                       cwd=build, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"FATAL: ninja -t commands failed: {r.stderr[-300:]}")
    pat = re.compile(r"em\+\+ .*-o bin/%s\.js([- ]|$)" % re.escape(tool))
    cands = [l for l in r.stdout.splitlines() if pat.search(l)]
    if not cands:
        sys.exit(f"FATAL: no em++ link command for bin/{tool}.js "
                 f"(saw {len(r.stdout.splitlines())} lines)")
    return cands[-1]


def link_argv(cmd, out_js):
    """ninja line -> argv with identical flags but a new -o target."""
    argv = shlex.split(cmd)
    while argv and argv[0] in (":", "&&"):
        argv = argv[1:]
    if "&&" in argv:
        argv = argv[:argv.index("&&")]
    i = argv.index("-o")
    argv[i + 1] = out_js
    return argv


def measure(label, path, quality):
    import brotli
    raw = os.path.getsize(path)
    br = len(brotli.compress(open(path, "rb").read(), quality=quality))
    print(f"ARTIFACT {label}_raw {raw}")
    print(f"ARTIFACT {label}_brotli {br}")
    print(f"  {label}: raw={raw:,} brotli-q{quality}={br:,}")
    return raw, br


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", default="clang")
    ap.add_argument("--name", required=True, help="config name for ARTIFACT keys")
    ap.add_argument("--build", required=True)
    ap.add_argument("--emcc-flags", "--emcc", dest="emcc_flags", default="",
                    help="extra link-time flags appended last")
    ap.add_argument("--brotli-quality", type=int, default=11)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    out_dir = os.path.join(ROOT, "m1/evidence/relink", args.name)
    os.makedirs(out_dir, exist_ok=True)
    out_js = os.path.join(out_dir, f"{args.tool}.js")

    argv = link_argv(nm_command(args.build, args.tool, out_js), out_js)
    argv += shlex.split(args.emcc_flags)
    print(f"== relink {args.tool} -> {args.name}")
    print(f"   inputs: {sum(1 for a in argv if a.endswith(('.o', '.a')))}  "
          f"extra: {args.emcc_flags or '(none)'}")
    if args.dry_run:
        print("DRY RUN:", " ".join(shlex.quote(x) for x in argv[-6:]))
        return

    env = dict(os.environ)
    env.setdefault("EM_CACHE", os.path.join(EM, "cache"))
    t0 = time.time()
    r = subprocess.run(argv, cwd=args.build, env=env,
                       capture_output=True, text=True)
    dt = time.time() - t0
    log = os.path.join(out_dir, "link.log")
    with open(log, "w") as f:
        f.write(f"# took {dt:.1f}s rc={r.returncode}\n")
        f.write(" ".join(shlex.quote(x) for x in argv) + "\n\n")
        f.write(r.stdout + r.stderr)
    if r.returncode != 0:
        print(f"FATAL: link failed after {dt:.0f}s; see {log}")
        print("\n".join((r.stdout + r.stderr).splitlines()[-15:]))
        sys.exit(2)

    # emcc names the wasm after the .js output: <name>.js -> <name>.wasm
    wasm = os.path.join(out_dir, os.path.basename(out_js)[:-3] + ".wasm")
    if not os.path.exists(wasm):
        sys.exit(f"FATAL: {wasm} missing after a successful link "
                 f"(emcc silently produced nothing?) see {log}")
    print(f"   linked in {dt:.0f}s")
    measure(f"{args.name}_{args.tool}", wasm, args.brotli_quality)
    print(f"   wasm: {wasm}")
    print(f"   js:   {out_js} ({os.path.getsize(out_js)} B)")


if __name__ == "__main__":
    main()
