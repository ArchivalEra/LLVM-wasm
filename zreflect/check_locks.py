#!/usr/bin/env python3
"""Locked-sources list gate (**pluggable module**; generalized from the
repo-architecture batch of Octave-Full-Wasm).

Not every upstream has a git-able official repo (netlib's old f2c/lapack,
freedesktop's glu, sourceforge's qrupdate...). For those, "pinning" must
fall back to a lock list of **URL + file + sha256**. This gate verifies that
list:

    { "locked": [
        { "name": "glpk", "version": "5.0",
          "url": "https://ftp.gnu.org/gnu/glpk/glpk-5.0.tar.gz",
          "file": "third_party/glpk-5.0.tar.gz",      # repo-root-relative or absolute
          "sha256": "..." },                           # required in file form; optional in dir form
        { "name": "lapack", "version": "3.4.2", "file": ".../lapack-3.4.2",
          "form": "dir", "optional": true } ] }

- File form: **sha256 is required and must match** (both missing and mismatched
  are reported -- that is the entire meaning of "pinning");
- dir form: existence only (a directory has no single-value hash; an entry
  with `optional: true` absent on this machine => SKIP, stated openly, not a
  pass -- cross-machine build repos need this escape hatch);
- empty `locked` / an entry missing name/url => report (zero-value guard; a
  lock entry with no reason is a zombie).

Orthogonal to `check_invariants` (#7): that one guards "what a file should
look like (text)", this one guards the **content fingerprint** of external
artifacts -- together they turn "upstream" from loose tarballs into checkable
facts.

**Boundary (stated openly)**: sha256 only proves "still those bytes", not
"those bytes are the right ones" -- the URL-to-version mapping is the list
author's claim; the gate does no network verification (re-fetching is the
build script's job).

Usage (cwd = repo root): python3 zreflect/check_locks.py [--spec upstream-lock.json]
(Spec-name resolution: explicit --spec > default `upstream-lock.json`; explicitly
specified but the file missing => FATAL 2.)
Exit codes: 0 = green or not enabled / 1 = problems / 2 = broken config.
Selftest: --selftest.
"""
from __future__ import annotations

import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gate  # noqa: E402
import knobs  # noqa: E402
import machine  # noqa: E402
from gate import (  # noqa: E402
    fatal,
    finish,
    load_spec,
    main_selftest_or,
    meta,
    off,
    repo,  # noqa: E402
)
from i18n import M  # noqa: E402

# Derived from the knob registry (single origin) -- a handwritten literal would
# drift from it (the most expensive class of debt in this repo).
DEFAULT_SPEC = knobs.REGISTRY["REFLECT_LOCKS"][1]


def resolve_spec(argv, knob=""):
    """See `gate.resolve_spec`: the implementation lives in one place; this only
    binds this gate's default name."""
    return gate.resolve_spec(argv, knob, DEFAULT_SPEC)


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


REQUIRED_FIELDS = ("name", "url", "file")


def _entry_missing_fields(entry):
    """The problem list for missing fields. **Any one missing => this entry is
    uncheckable** (you cannot hand None to the hasher)."""
    return [M("locks.entry_missing_field", field=f, entry=entry)
            for f in REQUIRED_FIELDS if not entry.get(f)]


def _check_one(entry, hasher, root):
    """Check one locked entry. Returns `(problem list, skip list)`."""
    missing = _entry_missing_fields(entry)
    if missing:
        return missing, []
    path = gate.repo_path(entry["file"], root)
    if not os.path.exists(path):
        if entry.get("optional"):
            return [], [M("locks.absent_optional", name=entry["name"])]
        return [M("locks.file_missing", name=entry["name"], path=path)], []
    want = entry.get("sha256")
    if not want:
        if (entry.get("form") or "file") == "dir":
            return [], []                     # dir form: existence only
        return [M("locks.no_sha256", name=entry["name"])], []
    got = hasher(path)
    if got != want:
        return [M("locks.sha_mismatch", name=entry["name"],
                  declared=want[:12], actual=got[:12])], []
    return [], []


def check(spec, hasher=_sha, root=None):
    """Pure logic (the selftest injects `hasher`). Returns (problems, skips).

    `root` = the anchor for resolving relative `file` paths (default: the repo
    under check; the selftest passes a fixture directory).

    The single-entry check is a named helper (`_check_one`): previously its
    `problems[-1].code` looked back at the previously appended entry to decide
    "this entry lacks fields" -- that was both fragile (anyone appending an
    entry in between breaks it) and pushed complexity to 12. Now a missing
    field is a **return value**, not context.
    """
    root = repo() if root is None else root
    locked = spec.get("locked") or spec.get("sources") or []
    if not locked:
        return [M("locks.empty")], []
    problems, skips = [], []
    for entry in locked:
        probs, sk = _check_one(entry, hasher, root)
        problems += probs
        skips += sk
    return problems, skips


def main(argv):
    spec_path, explicit = resolve_spec(argv, os.environ.get("REFLECT_LOCKS", ""))
    path = gate.repo_path(spec_path)
    if not os.path.isfile(path):
        if explicit:
            return fatal(M("locks.explicit_spec_missing", name=spec_path))
        return off(M("locks.off", name=spec_path))
    spec, err = load_spec(path)
    if err:
        return fatal(M("locks.spec_broken", name=spec_path, error=err))
    problems, skips = check(spec)
    for x in skips:
        print(machine().emit("skip", str(x)), file=sys.stderr)
    return finish(M("locks.title"), problems,
                  M("locks.ok", count=len(spec.get("locked")
                                         or spec.get("sources") or [])))


def _cases():
    import atexit  # noqa: PLC0415
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    d = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, d, True)
    payload = b"UPSTREAM-FIXTURE"
    good = hashlib.sha256(payload).hexdigest()
    open(os.path.join(d, "glpk.tar.gz"), "wb").write(payload)
    os.makedirs(os.path.join(d, "lapack-3.4.2"))
    # The fixture uses **absolute paths** (the engine resolves relative paths
    # against the repo root; the fixture tree lives in a temp dir)
    g = os.path.join(d, "glpk.tar.gz")
    lp = os.path.join(d, "lapack-3.4.2")
    spec = {"locked": [
        {"name": "glpk", "version": "5.0", "url": "u", "file": g, "sha256": good},
        {"name": "lapack", "version": "3.4.2", "url": "u", "file": lp, "form": "dir"},
        {"name": "mesa", "version": "x", "url": "u", "file": "nope.tar.xz", "optional": True},
    ]}
    bad_hash = {"locked": [{"name": "glpk", "version": "5.0", "url": "u",
                            "file": g, "sha256": "0" * 64}]}
    missing = {"locked": [{"name": "glpk", "version": "5.0", "url": "u", "file": "nope.tar.gz",
                           "sha256": good}]}
    no_sha = {"locked": [{"name": "glpk", "version": "5.0", "url": "u", "file": g}]}
    empty = {"locked": []}
    return [
        ("locks.resolve_spec",
         lambda: resolve_spec(["--spec", "x.json"], "K.json") == ("x.json", True)
         and resolve_spec([], "K.json") == ("K.json", True)
         and resolve_spec([]) == ("upstream-lock.json", False)),
        # (1) compliant input: nothing reported
        ("locks.ok",
         lambda: check(spec, root=d)[0] == [] and check(spec, root=d)[1] != []),
        # (2) what must be reported is reported
        ("★ locks.sha_mismatch",
         lambda: [p.code for p in check(bad_hash, root=d)[0]] == ["locks.sha_mismatch"]),
        ("★ locks.file_missing",
         lambda: [p.code for p in check(missing, root=d)[0]] == ["locks.file_missing"]),
        ("★ locks.no_sha256",
         lambda: [p.code for p in check(no_sha, root=d)[0]] == ["locks.no_sha256"]),
        # (3) empty input must be reported
        ("★ locks.empty",
         lambda: [p.code for p in check(empty, root=d)[0]] == ["locks.empty"]),
    ]


GATE = meta("Locked-sources gate", "locked-sources list (content fingerprints of URL + file + sha256)",
            knobs=("REFLECT_LOCKS",),
            off_reason="repos that do not pin upstream bytes do not need it: spec unset => explicitly not enabled")

if __name__ == "__main__":
    sys.exit(main_selftest_or(sys.argv[1:], M("gate.title.locks"), _cases, main))
