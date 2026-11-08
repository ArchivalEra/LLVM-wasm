#!/usr/bin/env python3
"""Declarative invariants gate (**pluggable module**, issue #7).

"Repo file must / must not contain a snippet" is encoded as **data** (a JSON
spec); the engine is generic and repo-agnostic. Spec file:

    { "checks": [
        { "path": "build/113/link-web.sh",
          "must_contain": ["ALLOW_TABLE_GROWTH=1"],
          "must_not_contain": ["-flto"],
          "why": "dlopen needs a growable function table; -flto is the falsified lever" } ] }

The engine only reads files -- **no builds, no containers, no network** -- so it
can run in pre-commit. Zero-value guards: empty checklist / a check without a
path / an unreadable file => all reported (never a silent pass). Requiring `why`
is deliberate: a check with no stated reason is one nobody dares to delete, and
it turns into a zombie.

**Boundary (stated openly in issue #7)**: this is a **grep-level** invariant --
it cannot tell comments from code (a snippet inside a comment still counts as
"present"). What it proves is "this text is still there", not "the code really
uses it". The strength ceiling of a declarative check is the shape of the text
it matches. For stronger guarantees, do not use grep: that is the job of
`calibrate` (measures the **artifact**) or `witness` (measures the **source**).
Orthogonal to `calibrate` (issue #6, item 1) -- keep them apart: one guards the
**measurement instruments**, the other guards **the repo files themselves**
(what recipes / source code should look like).

**Pluggable**: `REFLECT_INVARIANTS` unset => explicitly not enabled, exit 0
(repos that do not configure it are entirely unaffected; the discovery-based
roster still enrolls it, and the selftest still proves it can go red).
Connection to `collect.py` principle 5: the invariants file is the input
landing spot; the invariants gate is the cheap origin invariant for that spot.

Usage (run directly, cwd = repo root):
    python3 zreflect/check_invariants.py [--selftest]
Exit codes: 0 = green / 1 = problems found / 2 = config or environment broken
(a config failure is not a check failure).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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

INVARIANTS_RAW = os.environ.get("REFLECT_INVARIANTS", "").strip()


def _shape_problems(c):
    """Shape validation for one check entry: returns `(problem list, normalized
    fields or None)`.

    "Bad shape" and "content mismatch" are two different things: with a bad
    shape there is **no comparable snippet**, so we must exit early (otherwise
    `frag not in text` raises TypeError). Five guards crammed into the call site
    would be 5 consecutive `continue`s (complexity 14).
    """
    if not isinstance(c, dict):
        return [M("invariants.not_object", entry=c)], None
    path = str(c.get("path") or "").strip()
    why = str(c.get("why") or "").strip()
    mc, mnc = c.get("must_contain"), c.get("must_not_contain")
    if not path:
        return [M("invariants.missing_path", entry=c)], None
    out = [] if why else [M("invariants.missing_why", path=path)]
    crit = _criteria_problems(path, mc, mnc)
    if crit is not None:
        return out + crit, None
    return out, (path, why, mc or [], mnc or [])


def _criteria_problems(path, mc, mnc):
    """Shape validation for the criteria fields (must_contain / must_not_contain).

    Returns None = shape usable; returns a list = shape broken (caller exits
    early). The three bad shapes each get a guard (no criteria / not a list /
    element not a string), split out of `_shape_problems` -- what remains over
    there is "collect values field by field"; this one is "the criteria itself".
    """
    if not isinstance(mc, list) and not isinstance(mnc, list):
        return [M("invariants.no_criteria", path=path)]
    if (mc is not None and not isinstance(mc, list)) or \
            (mnc is not None and not isinstance(mnc, list)):
        return [M("invariants.not_string_list", path=path)]
    if any(not isinstance(x, str) for x in (mc or [])) or \
            any(not isinstance(x, str) for x in (mnc or [])):
        return [M("invariants.fragment_not_string", path=path)]
    return None


def _content_problems(path, why, mc, mnc, read):
    """Snippet comparison: every `must_contain` must be present, every
    `must_not_contain` must be absent."""
    try:
        text = read(path)
    except OSError:
        return [M("invariants.unreadable", path=path)]
    out = []
    for frag in mc:
        if frag not in text:
            # `DRIFT` is a machine-readable marker: the **literal stays at the
            # emission point** (as a parameter value); the language pack only
            # places it into the sentence -- a pack value must not start with
            # `^[A-Z][A-Z0-9_]*:` (otherwise a single translation could masquerade
            # as a machine contract line; see i18n._validate).
            out.append(M("invariants.drift_missing", marker="DRIFT",
                         path=path, fragment=frag, why=why))
    for frag in mnc:
        if frag in text:
            out.append(M("invariants.drift_forbidden", marker="DRIFT",
                         path=path, fragment=frag, why=why))
    return out


def problems(checks, read=None):
    """Pure function: return the problem list (empty = green). No printing during
    the selftest.

    `read(path) -> str` is injectable (a fake filesystem for the selftest -- if
    real files entered the selftest, the selftest would depend on the machine).
    The criterion is the **presence/absence** of a snippet (grep level; see the
    boundary in the module docstring).

    Each half is its own helper (shape / content): with a bad shape there is no
    comparable snippet, so an early exit is mandatory -- merged into one body,
    5 shape guards + 2 content guards = complexity 14.
    """
    if not checks:
        return [M("invariants.empty")]
    read = read or (lambda p: open(repo(p), encoding="utf-8").read())
    out = []
    for c in checks:
        shape_probs, spec = _shape_problems(c)
        out += shape_probs
        if spec is not None:
            out += _content_problems(*spec, read=read)
    return out


def run(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    name = INVARIANTS_RAW
    if not name:
        return off(M("invariants.off"))
    spec_path = repo(name)
    if not os.path.exists(spec_path):
        return fatal(M("invariants.spec_missing", name=name))
    spec, err = load_spec(spec_path)
    if err:
        return fatal(M("invariants.spec_broken", name=spec_path, error=err))
    checks = spec.get("checks") if isinstance(spec, dict) else None
    if not isinstance(checks, list):
        return fatal(M("invariants.bad_shape", path=spec_path))
    return finish(M("invariants.title"), problems(checks),
                  M("invariants.ok", count=len(checks)))


def _fake_read(files):
    """Fake filesystem: a filename not provided raises `FileNotFoundError` (the
    OSError of the real read path)."""
    def r(path):
        if path not in files:
            raise FileNotFoundError(path)
        return files[path]
    return r


def _cases_ok(read):
    """(1) Compliant input: nothing reported; presence/absence both as declared."""
    return [
        ("invariants.must_contain_present",
         lambda: problems([{"path": "a.sh", "why": "w",
                            "must_contain": ["ALLOW_TABLE_GROWTH=1"]}],
                         read=read) == []),
        ("invariants.must_not_contain_absent",
         lambda: problems([{"path": "a.sh", "why": "w",
                            "must_not_contain": ["-flto"]}],
                         read=read) == []),
        ("invariants.both_criteria_met",
         lambda: problems([{"path": "a.sh", "why": "w",
                            "must_contain": ["ALLOW_TABLE_GROWTH=1"],
                            "must_not_contain": ["-flto"]}],
                         read=read) == []),
    ]


def _cases_content(read):
    """(2) What must be reported is reported: content mismatch / unreadable."""
    return [
        ("\u2605 invariants.drift_missing",
         lambda: [x.code for x in problems(
             [{"path": "a.sh", "why": "w", "must_contain": ["-flto"]}],
             read=read)] == ["invariants.drift_missing"]),
        ("\u2605 invariants.drift_forbidden",
         lambda: [x.code for x in problems(
             [{"path": "a.sh", "why": "w",
               "must_not_contain": ["ALLOW_TABLE_GROWTH=1"]}],
             read=read)] == ["invariants.drift_forbidden"]),
        ("\u2605 invariants.unreadable",
         lambda: [x.code for x in problems(
             [{"path": "b.sh", "why": "w", "must_contain": ["x"]}],
             read=read)] == ["invariants.unreadable"]),
        # A missing why is reported **first** (it does not continue: the same
        # entry may also carry DRIFT, so both problems get reported)
        ("\u2605 invariants.missing_why",
         lambda: [x.code for x in problems(
             [{"path": "a.sh", "must_contain": ["x"]}],
             read=read)] == ["invariants.missing_why",
                             "invariants.drift_missing"]),
    ]


def _cases_shape(read):
    """(2) What must be reported is reported: broken spec shapes (five guards)."""
    return [
        ("\u2605 invariants.missing_path",
         lambda: [x.code for x in problems(
             [{"why": "w", "must_contain": ["x"]}],
             read=read)] == ["invariants.missing_path"]),
        ("\u2605 invariants.no_criteria",
         lambda: [x.code for x in problems(
             [{"path": "a.sh", "why": "w"}],
             read=read)] == ["invariants.no_criteria"]),
        ("\u2605 invariants.not_object",
         lambda: [x.code for x in problems(["not-a-dict"], read=read)
                  ] == ["invariants.not_object"]),
        ("\u2605 invariants.not_string_list",
         # one side a list, the other not (both sides non-list is no_criteria's case)
         lambda: [x.code for x in problems(
             [{"path": "a.sh", "why": "w", "must_contain": ["x"],
               "must_not_contain": "y"}],
             read=read)] == ["invariants.not_string_list"]),
        ("\u2605 invariants.fragment_not_string",
         lambda: [x.code for x in problems(
             [{"path": "a.sh", "why": "w", "must_contain": [1]}],
             read=read)] == ["invariants.fragment_not_string"]),
    ]


def _cases():
    read = _fake_read({"a.sh": "ALLOW_TABLE_GROWTH=1\n"
                              "SFLAGS=(-sMEMORY64=1)"})
    return (_cases_ok(read) + _cases_content(read) + _cases_shape(read)
            # (3) empty input must be reported
            + [("\u2605 invariants.empty",
                lambda: [x.code for x in problems([], read=read)]
                == ["invariants.empty"])])


GATE = meta("Invariants gate",
            "declarative invariants: repo files must / must not contain a snippet (grep level)",
            knobs=("REFLECT_INVARIANTS",),
            off_reason="repos that write no declarative invariants do not need it:"
                       " spec unset => explicitly not enabled (pluggable)")

if __name__ == "__main__":
    sys.exit(main_selftest_or(sys.argv[1:],
                              M("gate.title.invariants"),
                              _cases(), run))
