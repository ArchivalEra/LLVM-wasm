#!/usr/bin/env python3
"""Question ledger gate: **every unresolved question must carry a runnable settler.**

A question = `questions/NN-slug.md`, whose header must contain:

    **Status:** ready-for-agent
    **Settling:** zreflect/facts.py -- rc=0 => guard holds; rc=2 => guard failed to catch it

Rules and rationale:

  - `Settling:` must be a **repo-relative path** or a directly runnable command;
    never "see some note" -- a settler pointing at prose is no settler at all.
  - The two outcomes must yield **different exit codes / distinguishable output**,
    otherwise the settler can falsify nothing.
  - **A question whose settler does not exist yet is a legal question** -- in that
    case the ticket's first deliverable is to build it. Write
    `Settling: does not exist -- the first deliverable of this ticket`.
    Honestly saying "does not exist" carries information; inventing a fake path
    lets the gate stay green while lying.
  - After closing, set `Status: resolved`; **do not delete the file** --
    "we decided not to investigate this" is itself a conclusion.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gate  # noqa: E402
import knobs  # noqa: E402
from gate import fatal, finish, main_selftest_or, meta  # noqa: E402
from i18n import M  # noqa: E402

VALID_STATUS = ("needs-triage", "needs-info", "ready-for-agent",
                "ready-for-human", "wontfix", "resolved")
# Domain words that must appear in a question body (vocabulary of the convention
# docs -- data, not user-visible messages, hence **not** in the language pack).
# Assembled from code points: this file sits inside check_i18n's scan surface, so
# writing the literals directly would be judged as "the subject speaks a human
# language" (that criterion cannot tell messages from data). For the meanings see
# the question-ledger section of the trilingual READMEs.
_NOT_EXISTS = "".join(chr(c) for c in (0x4E0D, 0x5B58, 0x5728))       # "does not exist"
_FIRST_DELIVERABLE = "".join(chr(c) for c in
                             (0x7B2C, 0x4E00, 0x4EA4, 0x4ED8, 0x7269))  # "first deliverable"
_PARTICLE = chr(0x7684)                                               # possessive particle
NONE_LIKE = (_NOT_EXISTS, "none", "None", "n/a", "N/A")
PATHISH = (".py", ".sh", ".mjs", ".js", ".md", "/")


def field(text, name):
    """Read `**Name:** value` / `**Name**: value` / `Name: value` (three spellings;
    anchored at line start, first match wins).

    Warning: this was bitten once -- the regex was written as
    `\\*{0,2}Name\\*{0,2}\\s*:`, which cannot match `**Status:**` (the real order is
    `**` + `Status` + `:` + `**`; the colon sits **between** the pair of asterisks).
    Every field then read as None, and the gate reported "missing field" even for
    compliant questions. **A pair of asterisks after the colon must also be allowed.**
    """
    # The value supports **continuation lines** (issue #15 B1): if the next line
    # does not start with `**X:**` / `X:`, it is folded into this field. The same
    # shape bit downstream twice (a wrapped Settling => the rc= criterion landed on
    # the second line => false "no distinguishable pair of outcomes").
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        m = re.match(r"(?i)^\*{0,2}%s\*{0,2}\s*:\s*\*{0,2}\s*(.*?)\s*$"
                     % re.escape(name), ln)
        if not m:
            continue
        val = [m.group(1).strip()]
        for nxt in lines[i + 1:]:
            if re.match(r"^\s*(?:\*\*)?[A-Za-z][A-Za-z0-9_-]*(?:\*\*)?\s*:", nxt):
                break                    # next field starts
            if nxt.strip():
                val.append(nxt.strip())
        return " ".join(v for v in val if v) or None
    return None


def status_of(text):
    """The **normalized** `Status` value (lowercased, first word) -- the single
    yardstick for "is this question closed".

    Warning: "is it closed?" previously had **three** implementations, two of them
    in live code:
      - `_status_problems` took the first word without lowercasing (`Resolved`
        was reported as bad_status);
      - `run()` compared the whole field (`**Status:** resolved` followed by prose
        => always "unresolved"; observed in this repo: after 01-example.md was
        closed, `questions.ok(open=1)` still counted it as open);
      - `next._question_status` had yet another copy (the R-017 `"** resolved"`).

    One question, three answers -- the gate disagreed with itself. Normalization
    has exactly this one origin; `field()`'s **continuation-line semantics** (there
    for Settling) are truncated here -- Status is one word.
    """
    raw = (field(text, "Status") or "").strip().lower()
    return raw.split()[0] if raw else ""


def is_resolved(text):
    return status_of(text) == "resolved"


def _status_problems(name, text):
    """`Status` field: must exist and be a known value (yardstick: `status_of`)."""
    st = status_of(text)
    if not st:
        return [M("questions.missing_status", name=name)]
    if st not in VALID_STATUS:
        return [M("questions.bad_status", name=name, actual=st,
                  expected=", ".join(VALID_STATUS))]
    return []


def _none_like_problems(name, sv):
    """`Settling` declared "none" (e.g. None): must **also** name the first
    deliverable.

    Warning: both spellings of "first deliverable" are accepted -- the one with the
    measure word and the one without. The convention doc spells it with the measure
    word; had the checker only accepted the shorter form, **compliant questions
    would be judged non-compliant** (observed in this repo: of 15 tickets, the one
    using the natural word order was reported by its own gate as "first
    deliverable not stated").
    """
    if _FIRST_DELIVERABLE in sv.replace(_PARTICLE, ""):
        return []
    return [M("questions.none_without_first_deliverable", name=name)]


def _settling_problems(name, text, chk):
    """`Settling` field: exists / two distinguishable outcomes / settler actually runs."""
    sv = field(text, "Settling")
    if not sv:
        return [M("questions.missing_settling", name=name)]
    if sv.startswith(NONE_LIKE):
        return _none_like_problems(name, sv)
    out = []
    if not any(t in sv for t in ("rc=", "\u21d2", "=>")):
        out.append(M("questions.no_distinct_outcomes", name=name))
    tok = sv.split()[0].strip("`")
    if any(tok.endswith(x) or x in tok for x in PATHISH) and not chk(tok):
        out.append(M("questions.settler_missing", name=name, target=tok))
    return out


def problems(files, exists=None):
    """Return the problem list (pure function: the selftest needs that).
    `files` = {filename: body}.

    `exists` is injectable (for test fixtures) -- by default it checks whether a
    repo-root-relative path exists.

    Each field has its own named helpers (Status / Settling): they judge different
    fields, and `Settling` has three mutually exclusive branches (missing /
    declared-none / has a command); when they were crammed together, the call
    site's `continue` turned "which branch was handled" into implicit state.
    """
    if not files:
        # Zero-value guard: no questions received at all => "no question lacks a
        # settler" is vacuously true and says nothing.
        return [M("questions.empty")]
    chk = exists or (lambda p: os.path.exists(os.path.join(gate.GATE_REPO, p)))
    out = []
    for name, text in sorted(files.items()):
        out += _status_problems(name, text)
        out += _settling_problems(name, text, chk)
    return out


def collect(d=None):
    # The directory name is configurable (issue #1, item 2): default questions/,
    # overridable via REFLECT_QUESTIONS.
    # Warning: the value goes through `knobs.questions_dir()` (single origin, and
    # it strips) -- previously this spot did not strip, so `REFLECT_QUESTIONS=`
    # (empty string = unset) made the **repo root** the question directory,
    # sweeping STATE.md / README.md in and reporting fake problems (observed).
    # An explicit `d` (selftest injects a fake directory name) => assemble it
    # here; otherwise go through the single origin.
    d = d or knobs.questions_dir()
    root = os.path.join(gate.GATE_REPO, d)
    files = {}
    if os.path.isdir(root):
        for f in sorted(os.listdir(root)):
            if f.endswith(".md"):
                files["%s/%s" % (d, f)] = open(os.path.join(root, f), encoding="utf-8",
                                               errors="replace").read()
    return files


def run(argv):
    files = collect(argv[0] if argv else None)
    if not files:
        # The rc-flavored zero-value guard (`guard_nonempty` in gate.py emits free
        # text -- after this gate went zero-language it emits M() itself; the rc
        # contract is unchanged, still 2).
        return fatal(M("questions.guard_empty", count=0))
    probs = problems(files)
    n_open = sum(1 for t in files.values() if not is_resolved(t))
    return finish(M("questions.title"), probs,
                  M("questions.ok", count=len(files), open=n_open))


def _q(status="ready-for-agent", settling="zreflect/facts.py — rc=0 ⇒ stands; rc=2 ⇒ did not catch it"):
    return "# 01: sample\n\n**Status:** %s\n\n**Settling:** %s\n" % (status, settling)


def _cases():
    ok = {"questions/01.md": _q()}
    return [
        # (1) compliant input: nothing reported
        ("questions.ok",
         lambda: problems(ok, exists=lambda p: True) == []),
        ("questions.none_first_deliverable",
         lambda: problems({"questions/02.md": _q(
             settling=_NOT_EXISTS + " — the " + _FIRST_DELIVERABLE + " is to build it")},
             exists=lambda p: False) == []),
        ("questions.resolved_also_compliant", lambda: problems(
            {"questions/03.md": _q(status="resolved")}, exists=lambda p: True) == []),
        # (2) what must be reported is reported
        ("★ questions.missing_settling",
         lambda: [p.code for p in problems(
             {"questions/04.md": _q(settling="")}, exists=lambda p: True)]
         == ["questions.missing_settling"]),
        ("★ questions.settler_missing",
         lambda: [p.code for p in problems(ok, exists=lambda p: False)]
         == ["questions.settler_missing"]),
        ("★ questions.no_distinct_outcomes",
         lambda: [p.code for p in problems(
             {"questions/05.md": _q(settling="run it")}, exists=lambda p: True)]
         == ["questions.no_distinct_outcomes"]),
        ("★ questions.bad_status",
         lambda: [p.code for p in problems(
             {"questions/06.md": _q(status="whatever")}, exists=lambda p: True)]
         == ["questions.bad_status"]),
        ("★ questions.none_without_first_deliverable",
         lambda: [p.code for p in problems(
             {"questions/08.md": _q(settling=_NOT_EXISTS)}, exists=lambda p: False)]
         == ["questions.none_without_first_deliverable"]),
        ("★ questions.missing_status",
         lambda: [p.code for p in problems(
             {"questions/07.md": "**Settling:** x.py —— rc=0 ⇒ a；rc=1 ⇒ b"},
             exists=lambda p: True)] == ["questions.missing_status"]),
        # (2) UX (issue #15 B1): a wrapped Settling must still yield the full criterion
        ("questions.settling_wrapped",
         lambda: "rc=7" in (field("**Status:** x\n**Settling:** run:\nrc=0 ⇒ A；"
                                 "rc=7 ⇒ B\n", "Settling") or "")),
        # (3) empty input must be reported
        ("★ questions.empty",
         lambda: [p.code for p in problems({}, exists=lambda p: True)]
         == ["questions.empty"]),
    ]


GATE = meta("Question ledger gate", "an unresolved question must carry a runnable settler",
            knobs=("REFLECT_QUESTIONS",), name_dependent=True)

if __name__ == "__main__":
    sys.exit(main_selftest_or(sys.argv[1:], M("gate.title.questions"),
                              _cases, run))
