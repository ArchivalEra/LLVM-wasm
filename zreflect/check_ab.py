#!/usr/bin/env python3
"""A/B same-flags invariant gate (**pluggable module**; generalized from
Octave-Full-Wasm tickets 57/61).

When comparing the **declared surfaces** of two artifacts (build-product
identity cards, benchmark reports, any JSON), the only legal difference is the
**axis under test** itself. Any other key differing = a confounding variable
slipped into the A/B -- the conclusion is void. Real incident: an allocator A/B
first reported -39%; it later turned out the baseline carried runtime assertions
(the full `--diag` set) while the candidate only carried `NAMES=1` => retested
with same flags, the real difference was -27%. Had this gate existed before the
A/B, the -39% would never have entered the record.

Spec (`REFLECT_AB`, default `ab.json`; data, not code):

    { "pairs": [
        { "name": "allocator A/B",
          "a": "artifacts/base/octave.build.json",
          "b": "artifacts/cand/octave.build.json",
          "key": "declared",            # optional: dotted path into the JSON (default: whole file)
          "allow": ["malloc"],          # axis under test (the only key allowed to differ)
          "why": "...required..." } ] }

- A value difference on any key outside `allow` => report (confounding
  variable);
- keys inside `allow` **must simply exist in both** -- differing or equal both
  count; mere existence is the criterion, absence itself is not judged
  (absence semantics belong to the producer);
- an artifact that cannot be read => `SKIP:`, stated openly (a cross-machine
  reality, not a pass);
- empty `pairs` / an entry missing why => report (zero-value guard);
- `REFLECT_AB` unset => explicitly not enabled, exit 0; explicitly specified
  (--spec / knob) but the file missing => FATAL exit 2.

Usage (cwd = repo root): python3 zreflect/check_ab.py [--spec ab.json]
(Spec-name resolution: explicit --spec > `REFLECT_AB` knob > default `ab.json`.)
Exit codes: 0 = green or not enabled / 1 = problems found / 2 = broken config.
Selftest: --selftest (fixture-injected).
"""
from __future__ import annotations

import json
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
DEFAULT_SPEC = knobs.REGISTRY["REFLECT_AB"][1]


def resolve_spec(argv, knob=""):
    """See `gate.resolve_spec`: the implementation lives in one place; this only
    binds this gate's default name."""
    return gate.resolve_spec(argv, knob, DEFAULT_SPEC)


def _load(path):
    try:
        return json.load(open(path, encoding="utf-8")), None
    except (OSError, ValueError) as e:
        return None, str(e)


def _dig(obj, dotted):
    cur = obj
    for k in dotted.split("."):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur


def _pair_field_problems(pr):
    """A pair entry missing a required field (name / a / b / why) => report."""
    return [M("ab.pair_missing_field", field=f, entry=pr)
            for f in ("name", "a", "b", "why") if not pr.get(f)]


def _declared(obj, key):
    """Take the declared surface: empty key => the whole file; otherwise dig
    down the dotted path."""
    return _dig(obj, key) if key else obj


def _confound_problems(pr, key, da, db):
    """A value mismatch on any key outside the allow axis => confounding
    variable (A/B void)."""
    allow = set(pr.get("allow") or [])
    return [M("ab.confound", name=pr["name"],
              key=key or M("ab.root_label"), field=k,
              value_a=da.get(k), value_b=db.get(k))
            for k in sorted(set(da) | set(db))
            if k not in allow and da.get(k) != db.get(k)]


def _pair_problems(pr, root, loader):
    """One A/B pair comparison: fields / readability / declared-surface type /
    confounding variables. Returns (problems, skips)."""
    problems, skips = _pair_field_problems(pr), []
    if problems:
        # A missing required field ends it here (the a/b/key reads below would
        # raise KeyError -- the missing field is itself what this round
        # reports; do not let it become a crash).
        return problems, skips
    key = pr.get("key") or ""
    ra, ea = loader(gate.repo_path(pr["a"], root))
    rb, eb = loader(gate.repo_path(pr["b"], root))
    if ra is None or rb is None:
        skips.append(M("ab.artifact_unreadable", name=pr["name"],
                       error_a=ea or "", error_b=eb or ""))
        return problems, skips
    da, db = _declared(ra, key), _declared(rb, key)
    if not isinstance(da, dict) or not isinstance(db, dict):
        problems.append(M("ab.not_a_dict", name=pr["name"],
                          key=key or M("ab.root_label")))
        return problems, skips
    return problems + _confound_problems(pr, key, da, db), skips


def check(spec, root, loader=_load):
    """Pure logic (the selftest injects `loader`). Returns (problems, skips)."""
    pairs = spec.get("pairs") or []
    if not pairs:
        return [M("ab.empty")], []
    problems, skips = [], []
    for pr in pairs:
        probs, sks = _pair_problems(pr, root, loader)
        problems += probs
        skips += sks
    return problems, skips


def main(argv):
    spec_path, explicit = resolve_spec(argv, os.environ.get("REFLECT_AB", ""))
    path = gate.repo_path(spec_path)
    if not os.path.isfile(path):
        if explicit:
            return fatal(M("ab.explicit_spec_missing", name=spec_path))
        return off(M("ab.off", name=spec_path))
    spec, err = load_spec(path)
    if err:
        return fatal(M("ab.spec_broken", name=spec_path, error=err))
    problems, skips = check(spec, repo())
    for x in skips:
        print(machine().emit("skip", str(x)), file=sys.stderr)
    return finish(M("ab.title"), problems,
                  M("ab.ok", count=len(spec.get("pairs") or [])))


def _cases():
    import atexit  # noqa: PLC0415
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    d = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, d, True)

    def wf(rel, obj):
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(obj, open(p, "w", encoding="utf-8"))
        return rel
    spec = {"pairs": [
        {"name": "allocator A/B", "a": "a.json", "b": "b.json", "key": "declared",
         "allow": ["malloc"], "why": "axis under test = allocator"}]}
    # a/b: identical except malloc
    wf("a.json", {"declared": {"simd": True, "malloc": "mimalloc", "v128": 4752}})
    wf("b.json", {"declared": {"simd": True, "malloc": "dlmalloc", "v128": 4752}})
    wf("mut-a.json", {"declared": {"simd": True, "malloc": "mimalloc", "v128": 4752}})
    wf("mut-b.json", {"declared": {"simd": False, "malloc": "mimalloc", "v128": 4752}})
    wf("nokey.json", {"declared": "not-a-dict"})
    empty = {"pairs": []}
    confound_spec = {"pairs": [{"name": "m", "a": "mut-a.json", "b": "mut-b.json",
                                "key": "declared", "allow": ["malloc"], "why": "w"}]}
    return [
        ("ab.resolve_spec",
         lambda: resolve_spec(["--spec", "x.json"], "K.json") == ("x.json", True)
         and resolve_spec([], "K.json") == ("K.json", True)
         and resolve_spec([], "") == ("ab.json", False)
         and resolve_spec([], "  ") == ("ab.json", False)),
        # (1) compliant input: nothing reported
        ("ab.ok", lambda: check(spec, d)[0] == []),
        # (2) what must be reported is reported
        ("★ ab.confound",
         lambda: [p.code for p in check(confound_spec, d)[0]] == ["ab.confound"]),
        ("★ ab.artifact_unreadable",
         lambda: [p.code for p in check(
             {"pairs": [{"name": "x", "a": "nope-a.json", "b": "nope-b.json",
                         "why": "w"}]}, d)[1]] == ["ab.artifact_unreadable"]),
        ("★ ab.not_a_dict",
         lambda: [p.code for p in check(
             {"pairs": [{"name": "x", "a": "nokey.json", "b": "nokey.json",
                         "key": "declared", "why": "w"}]}, d)[0]] == ["ab.not_a_dict"]),
        ("★ ab.pair_missing_field",
         lambda: [p.code for p in check(
             {"pairs": [{"a": "a.json", "b": "b.json", "why": "w"}]}, d)[0]]
         == ["ab.pair_missing_field"]),
        # (3) empty input must be reported
        ("★ ab.empty",
         lambda: [p.code for p in check(empty, d)[0]] == ["ab.empty"]),
    ]


GATE = meta("A/B gate", "A/B same-flags invariant (a difference outside the allow axis = confounding variable, A/B void)",
            knobs=("REFLECT_AB",),
            off_reason="repos that run no A/B experiments do not need it: spec unset => explicitly not enabled")

if __name__ == "__main__":
    sys.exit(main_selftest_or(sys.argv[1:], "check_ab", _cases, main))
