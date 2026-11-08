#!/usr/bin/env python3
"""Contract and helpers for the fact collectors -- migrated from
Octave-Full-Wasm's `.githooks/handoff_facts.py`.

How `measure()` (facts.py) is written decides whether the numbers in the
ledger are **measured** or **invented**. Over there the collector was split
into its own module with the principles below in the file header, because
this module feeds two consumers (the generator that recomputes the machine
block + the gate that checks stale assertions) -- **both sides must use the
same reading**, otherwise the conventions fork and the gate is checking a
different set of numbers.

The principles (all paid for over there; collectors must obey them):

  1. **Read only persistent-disk artifacts**; run no services, touch no
     network. A pre-commit hook must not depend on "something is running".
  2. **Do not introduce inputs that change by themselves**: no "wall clock"
     and no HEAD sha inside the machine block -- otherwise `--check` never
     converges within the same commit. If you need time, use the **commit
     date**.
     (issue #4 item 5 continued: **a value that changes is not thereby
     barred from the ledger; you must first declare how it changes** --
     quantities that change on every run (random padding lengths, GREASE
     payloads, timestamp-like values) store **one real sampled
     measurement**, paired with a `*_stable` stability flag key pair (the
     consumer side has two tiers: the stable tier is judged verbatim, the
     unstable tier structurally), or with explicit `replay=False`;
     **bare storage is forbidden** -- bare storage keeps the replay gate red
     forever, until the whole gate gets muted with `REFLECT_REPLAY=off`,
     which is the real unsupervised state.)
  3. **Say so when you cannot read it**: artifact missing (different machine
     / disk not mounted) => `unavailable(what, why)`, and let the caller
     decide whether to warn or skip. **Never invent a number** -- 0 is a
     number, and it will be cited as a result.
  4. **Expensive measurements need a cache**: recover the previous
     measurement from the existing machine block (`prev_values`) and reuse
     it when the inputs are unchanged. Over there it saved "re-compressing
     36 MiB on every commit".
  5. **Inputs need a cheap landing place** (issue #6 item 2): after an
     artifact is produced, its inputs (source / tool / flags / environment)
     must have a readable record that **does not depend on re-running**,
     paired with a **cheap provenance invariant** (`witness`, issue #5)
     checked at every commit. Otherwise "the artifact did not change but the
     things that produce it did" is invisible.
     (`witness` is one instance of this principle; declarative invariants
     (issue #7, `check_invariants.py`) are another: the invariant file =
     the input landing place, the invariant gate = that landing place's
     cheap provenance invariant. Its strength ceiling = the text shape it
     matches -- a grep-type check cannot tell comments from code and proves
     "this text is still present", not "the code really uses it"; stronger
     guarantees are the job of `calibrate` (for artifact quantities) or
     `witness` (for provenance quantities).
     Layered builds have many such invariants: input file shas, compiler
     version + flags, environment variable snapshots, intermediate artifact
     architectures.)

Replay decidability (issue #2 item 1 -- a hard precondition beyond the five
principles): `cmd` is **not a comment**. `zreflect/check_facts_replay.py`
executes it verbatim at the repo root (bash + `pipefail`, so pipes no longer
swallow errors), and its stdout, stripped of leading/trailing whitespace,
must **equal** the ledger value -- so it may only print a **bare value**; "a
whole line containing the value" is human-readable but machine-undecidable.
Measurement methods that need a service or a built artifact are outside
replay: `fact(value, cmd, source, replay=False)` opts out explicitly, and
each repo's own higher-level gate takes over.
(issue #5: expensive facts must not land in the **never-rechecked** tier --
attach a cheap witness
`fact(value, cmd, source, replay=False, witness=..., witness_expect=...)`:
the value is not re-played verbatim, but the **provenance/context** ("the
tool/inputs that produced it are the ones I think they are") really runs at
every commit, with the same criterion as the bare-value contract. Both must
be given together; `ledger.fact()` errors on the spot at the incomplete
shape.)
"""
import re

from gate import (  # noqa: F401  (re-export convenience)
    fatal_exit,
    machine,  # noqa: E402
    module_meta,
    repo,
)
from i18n import M  # noqa: E402


def unavailable(what, why):
    """The honest shape of "could not read it". Callers (renderer/gates) must
    render it as an explicit statement, never treat it as 0.

    `what` (which thing was not read) is part of the **public signature**: it
    is a link in this honest-shape contract -- the caller names **who** could
    not be read, while the current return body only carries `why`. The
    signature being wider than the return body is **intentional**: downstream
    repos call by this signature; removing the parameter = breaking callers.
    """
    return {"ok": False, "why": why}


def parse_prev_values(doc_text, row_pattern, group_names):
    """Recover the previous measurement from the existing machine block (the
    general shape of principle 4).

    `row_pattern`: a line regex, with named groups `(?P<name>...)` marking
    the values to recover; `group_names`: tuple of group names to recover.
    Returns {row-lead key: {name: value}}.

    The returned values are **strings** -- whether something is a number is
    for the collector itself to interpret (it knows the convention). Typical
    use: fetch the previous (raw, gz) first, then skip the expensive
    measurement when inputs are unchanged.
    """
    out = {}
    if not doc_text:
        return out
    pat = re.compile(row_pattern)
    for m in pat.finditer(doc_text):
        key = m.group(1)
        rec = {}
        for name in group_names:
            try:
                rec[name] = m.group(name)
            except IndexError:
                # An unnamed group = misconfiguration; it must shout, never
                # silently take the wrong value.
                fatal_exit(M("collect.regex_missing_group", name=name))
        out[key] = rec
    return out


# The real meaning of `selftest=False`: **no `--selftest` entry point** (this
# module is pure contract + two helpers; bolting on a CLI entry would clash
# with its role of "being called by facts.measure").
# **That does not mean no self-verification**: `parse_prev_values` (named-group
# recovery / a missing group must shout) and `unavailable` (unreadable =
# ok False, inventing 0 forbidden) both have substantive assertions, living in
# `registry._cases()`. The description previously said "no independent
# selftest", which did not match the facts (round 25 alignment).
MODULE = module_meta(
    "Collector contract",
    "the five principles for measure() + helpers (no --selftest entry; "
    "self-verification lives in this module's `_cases`)",
    selftest=True)


# -- Self-verification (previously hosted in registry._cases) ---------------
#
# Criteria belong to the **module under test**: `parse_prev_values` /
# `unavailable` live here, so their self-verification should live here too.
# After moving it back, `selftest=True` is an honest declaration.

def _cases():
    def parse_ok():
        got = parse_prev_values("| a | 1 |\n| b | 2 |\n",
                                r"\| (?P<key>\w+) \| (?P<val>\d+) \|",
                                ("val",))
        return got == {"a": {"val": "1"}, "b": {"val": "2"}}

    def missing_group_shouts():
        try:
            parse_prev_values("| a | 1 |\n",
                              r"\| (?P<key>\w+) \| (?P<val>\d+) \|",
                              ("nope",))
            return False                # no shout = this case is red
        except SystemExit:
            return True

    def unavailable_shape():
        got = unavailable("x", "y")
        return got.get("ok") is False and "why" in got

    return [
        ("★ collect.parse_prev_values", parse_ok),
        ("★ collect.missing_group_shouts", missing_group_shouts),
        ("collect.unavailable_shape", unavailable_shape),
    ]


def _selftest():
    import sys  # noqa: PLC0415

    from gate import main_selftest_or  # noqa: PLC0415
    from i18n import M  # noqa: PLC0415
    return main_selftest_or(sys.argv[1:], M("gate.title.collect"),
                            _cases, lambda a: 0)


if __name__ == "__main__":
    import os  # noqa: PLC0415
    import sys  # noqa: PLC0415
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import collect as _mod  # noqa: PLC0415
    sys.exit(_mod._selftest())
