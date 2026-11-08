#!/usr/bin/env python3
"""Retraction gate: **a retracted assertion may not quietly return as the
current state.**

Each entry in `retractions.json` = one retracted assertion:
  `text` the search snippet -- the assertion's signature fragment, matched
  verbatim against document lines · `why` what made it wrong · `evidence` how
  to replay the refutation · `fixed_in` where the corrected claim lives now

Criterion: the line in a living-state document that contains `text` **must
carry a correction marker**. This is the only mechanism that raises the alarm
when "a retracted sentence reappears" -- a measured cost: one corrected
assertion survived **in the same file**, and also had a copy in another
document. Prose relies on good intentions; this relies on a gate.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import knobs  # noqa: E402
from gate import fatal, finish, guard_nonempty, main_selftest_or, meta, repo  # noqa: E402
from i18n import M  # noqa: E402
from ledger import load_or_fatal  # noqa: E402
from living import HIST_MARK, living_lines  # noqa: E402

REQUIRED = ("id", "text", "why", "evidence", "fixed_in")
# **Not read at module level as a knob**: `knobs.docs_names()` is the single
# origin (the registry's default value).
# Warning: a handwritten five-document literal once lived here and drifted from
# the registry's six (it lacked PRINCIPLES.md).
HIST_SECS = tuple(s for s in os.environ.get("REFLECT_HISTORY_SECS", "").split(",") if s)


def _entry_field_problems(retractions):
    """Required fields of every retraction entry (one missing => the ledger
    entry cannot be trusted)."""
    return [M("retractions.entry_missing_field", field=fld, entry=r.get("id"))
            for r in retractions
            for fld in REQUIRED if not r.get(fld)]


def _resurfaced_problems(retractions, docs, hist):
    """Resurfacing: the living-state line containing `text` **must carry a
    correction marker**."""
    out = []
    for r in retractions:
        text = r.get("text") or ""
        if not text:
            continue
        for name, body in sorted(docs.items()):
            for i, line, is_living in living_lines(body or "", hist):
                if is_living and text in line and not HIST_MARK.search(line):
                    out.append(M("retractions.resurfaced", name=name, line=i,
                                 text=text, entry=r.get("id", "?")))
    return out


def problems(retractions, docs, hist_secs=None):
    """Return the problem list (pure function: the selftest needs that).
    `docs` = {filename: body}.

    Only **living state** is scanned (`zreflect/living.py`'s judgment):
    append-only history sections, once declared via `REFLECT_HISTORY_SECS`, are
    exempt -- their "as it was then" is not "as it is now"; comparing it against
    the present would only force people to destroy the record. Do resurfacings
    inside history sections **still need a marker**? No -- a history section is
    inherently a record of "then"; this exemption is the discipline migrated
    from Octave.

    Each of the two rules is its own named helper (field completeness /
    resurfacing): they scan different things (the ledger itself vs the
    documents); merging them only made the call site look shorter.
    """
    hist = HIST_SECS if hist_secs is None else hist_secs
    if retractions is None or "retractions" not in (retractions or {}):
        # Zero-value guard: with the structure itself wrong, "no violations"
        # is not even on the table.
        return [M("retractions.missing_key")]
    if not docs:
        # Zero-value guard: not one document scanned => "no resurfacing found"
        # is an empty claim.
        return [M("retractions.no_docs")]
    entries = [r for r in (retractions.get("retractions") or [])
               if isinstance(r, dict)]
    return _entry_field_problems(entries) + _resurfaced_problems(
        [r for r in entries if isinstance(r, dict)], docs, hist)


def scanned_docs():
    """The list of documents this gate scans (`knobs.docs_names()`, single
    origin)."""
    return knobs.docs_names()


def run(argv):
    # The name is configurable (issue #1, item 2): never hardcoded -- switching
    # repos means changing only the environment variable.
    rp = repo(os.environ.get("REFLECT_RETRACTIONS", "retractions.json"))
    if not os.path.exists(rp):
        return fatal(M("retractions.file_missing", name=rp))
    docs = {}
    for name in (argv or scanned_docs()):
        p = repo(name)
        if os.path.exists(p):
            docs[name] = open(p, encoding="utf-8", errors="replace").read()
    rc = guard_nonempty("check_retractions", docs, M("retractions.scanned_docs"))
    if rc:
        return rc
    led = load_or_fatal(rp)
    probs = problems(led, docs)
    n = len(led.get("retractions") or [])
    return finish(M("retractions.title"), probs,
                  M("retractions.ok", count=n, documents=len(docs)))


def _cases():
    ok_r = {"retractions": [{"id": "R-1", "text": "this thing is green",
                             "why": "actually red", "evidence": "run x",
                             "fixed_in": "doc y"}]}
    doc_ok = "(record) this thing is green — retracted, see R-1\n"
    return [
        # (1) compliant input: nothing reported
        ("retractions.marked",
         lambda: problems(ok_r, {"A.md": doc_ok}) == []),
        ("retractions.assertion_absent",
         lambda: problems(ok_r, {"A.md": "clean document\n"}) == []),
        ("retractions.no_retractions",
         lambda: problems({"retractions": []}, {"A.md": "x\n"}) == []),
        ("retractions.declared_history_section",
         lambda: problems(ok_r, {"A.md": "## 5 history\nthis thing is green.\n"},
                          hist_secs=("5",)) == []),
        # (2) what must be reported is reported
        ("★ retractions.resurfaced",
         lambda: [p.code for p in problems(
             ok_r, {"A.md": "this thing is green.\n"})] == ["retractions.resurfaced"]),
        ("★ retractions.resurfaced_undeclared_history",
         lambda: [p.code for p in problems(
             ok_r, {"A.md": "## 5 history\nthis thing is green.\n"}, hist_secs=())]
         == ["retractions.resurfaced"]),
        ("★ retractions.entry_missing_field",
         lambda: [p.code for p in problems(
             {"retractions": [{"id": "R-2", "text": "t", "why": "w", "fixed_in": "f"}]},
             {"A.md": "x\n"})] == ["retractions.entry_missing_field"]),
        # (3) empty input must be reported
        ("★ retractions.no_docs",
         lambda: [p.code for p in problems(ok_r, {})] == ["retractions.no_docs"]),
        ("★ retractions.missing_key",
         lambda: [p.code for p in problems({}, {"A.md": "x\n"})]
         == ["retractions.missing_key"]),
        ("★ retractions.missing_key_none",
         lambda: [p.code for p in problems(None, {"A.md": "x\n"})]
         == ["retractions.missing_key"]),
    ]


GATE = meta("Retraction-resurfacing check", "a retracted assertion may not quietly return as the current state",
            knobs=("REFLECT_RETRACTIONS", "REFLECT_DOCS", "REFLECT_HISTORY_SECS"), name_dependent=True)

if __name__ == "__main__":
    sys.exit(main_selftest_or(sys.argv[1:], "check_retractions", _cases, run))
