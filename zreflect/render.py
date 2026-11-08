#!/usr/bin/env python3
"""Render the ledger into a document's machine block -- **the single origin of
the numbers**.

The generator (`facts.py`) and the gate (`check_facts.py`) must share this one
function; otherwise the two sides' yardstick for "is the block right" forks:
the generator changes the layout, the gate still compares against the old
layout, and they disagree forever (or worse: both switch to lenient matching,
and they "agree" forever).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gate import module_meta  # noqa: E402
from i18n import M  # noqa: E402

BLOCK_BEGIN = "<!-- AUTO:FACTS -->"
BLOCK_END = "<!-- /AUTO:FACTS -->"

# PINNED: AUTO machine block fixed language (does not follow REFLECT_LANG) --
# it is written into STATE.md and reconciled byte-for-byte by `facts.py --check`;
# following the language would make "the same commit differ across environments"
# (non-convergent). check_i18n scans `PINNED:` markers and does **not** trust the
# name (trusting the name = the roster drifts).
PREAMBLE = [
    ("> This block is rendered by `zreflect/facts.py --render-doc` from"
    " `FACTS.json`; **do not edit by hand**"
    " (pre-commit recomputes and `git add`s it)."),
    ("> 'Measured numbers' in the prose are produced only here: to cite one, write"
    " `[[key]]`; never copy the number by hand."),
]


def _fmt(v):
    if isinstance(v, str) and len(v) == 64:
        return "`%s…`" % v[:16]
    return "**%s**" % (v if isinstance(v, str) else str(v))


def render_block(ledger):
    """Ledger -> machine block (including begin/end markers). **Pure function**:
    rendering the same ledger twice is byte-identical.

    PINNED: AUTO machine block fixed language (see the note above PREAMBLE).
    """
    from ledger import facts_of  # noqa: PLC0415

    f = facts_of(ledger)
    lines = [BLOCK_BEGIN] + list(PREAMBLE) + [""]
    if not f:
        # Zero-value guard: **an empty ledger must say so explicitly**; rendering
        # it as a quiet empty table is forbidden -- an empty table looks like
        # "all normal", while the fact is "not one entry was measured".
        lines += [("**The ledger is empty** -- not a single fact. Empty is not"
                   " \"pass\": first check whether measure() is broken."), ""]
    else:
        # The "measured at" column = the ledger's measured_at (a record of the
        # collection moment, a pure-function input -- do not render "a few days
        # ago": that changes with the wall clock and --check would never
        # converge. issue #3, item 2)
        lines += ["| key | value | measured at | replay cmd |", "|---|---|---|---|"]
        for k in sorted(f):
            e = f[k] if isinstance(f[k], dict) else {"value": f[k]}
            lines.append("| `%s` | %s | %s | `%s` |"
                         % (k, _fmt(e.get("value")), e.get("measured_at", "—"),
                            e.get("cmd", "?")))
        lines += ["", "%d facts." % len(f)]
    lines.append(BLOCK_END)
    return "\n".join(lines)


def body_of(block):
    """Extract the body inside the block (between the two markers), for the
    "block matches the ledger" comparison."""
    if BLOCK_BEGIN not in block:
        return ""
    return block.split(BLOCK_BEGIN, 1)[1].split(BLOCK_END, 1)[0]


def prose_of(doc_text):
    """The document's prose **outside blocks** (bare numbers are looked for in
    there).

    #14: strip **all** `<!-- AUTO:... -->...<!-- /AUTO:... -->` regions, not just
    the facts block's pair -- from Phase 3 on, documents carry two machine blocks
    (FACTS + GATES); stripping only FACTS would push the whole gate roster into
    the bare-number scan (the roster's `sha256` gets cut into 256, colliding with
    a ledger fact whose value happens to be 256 => false red; two downstreams hit
    it independently, and the upstream only escaped because its sample ledger had
    no 256 -- an accident that was mechanically bound to fire).
    """
    out, i = [], 0
    while True:
        b = doc_text.find("<!-- AUTO:", i)
        if b < 0:
            out.append(doc_text[i:])
            break
        out.append(doc_text[i:b])
        e = doc_text.find("-->", b + len("<!-- AUTO:"))
        end = doc_text.find("<!-- /AUTO:", e) if e >= 0 else -1
        if end < 0:                  # begin without end: treat as no block (marker checks have their own zero-value guard)
            out.append(doc_text[b:])
            break
        close = doc_text.find("-->", end)
        i = close + 3 if close >= 0 else len(doc_text)
    return "".join(out)


# -- self-verification --------------------------------------------------------
def _extra_lines(block):
    """Lines of the block body other than `PREAMBLE` and blank lines (what it
    "says" beyond the PINNED boilerplate)."""
    return [ln for ln in body_of(block).splitlines()
            if ln.strip() and ln not in PREAMBLE]


def _cases():
    full = {"facts": {"a": 4752, "s": {"value": "b" * 64, "cmd": "c"}}}
    # The header is taken from **the render output itself** (do not hand-copy
    # PINNED text -- each copy is one more origin that can drift)
    header = next(ln for ln in body_of(render_block(full)).splitlines()
                  if ln.startswith("|"))
    return [
        # (1) compliant input: nothing reported
        ("render.keys_in_block",
         lambda: all(k in render_block(full) for k in ("a", "s"))),
        ("render.raw_value", lambda: "**4752**" in render_block(full)),
        ("render.sha_truncated", lambda: "`" + "b" * 16 + "…`" in render_block(full)),
        ("render.block_pure",
         lambda: render_block(full) == render_block(full)),
        ("render.prose_only_outside_block",
         lambda: (lambda d: ("body" in prose_of(d) and "tail" in prose_of(d)
                             and header not in prose_of(d) and header in d))(
             "body\n" + render_block(full) + "\ntail")),
        ("render.prose_fallback_whole_doc",
         lambda: prose_of("a document without markers") == "a document without markers"),
        # #14: in a two-machine-block document the GATES block must be stripped
        # too (otherwise the roster's sha256 is read as a bare number)
        ("render.prose_strips_all_blocks",
         lambda: (lambda d: ("sha256" not in prose_of(d)
                             and "GATES_TABLE" not in prose_of(d)
                             and "body" in prose_of(d) and "tail" in prose_of(d)))(
             "body\n<!-- AUTO:FACTS -->\nFACTS_TABLE\n<!-- /AUTO:FACTS -->\n"
             "<!-- AUTO:GATES -->\n| x | sha256 |\n<!-- /AUTO:GATES -->\ntail")),
        ("render.prose_nested_begin_literal",
         lambda: (lambda d: "awk" not in prose_of(d) and "tail" in prose_of(d))(
             "head\n<!-- AUTO:FACTS -->\ncmd: awk '<!-- AUTO:FACTS -->'\n"
             "<!-- /AUTO:FACTS -->\ntail")),
        # (2) what must be reported is reported (at the render layer, "reported"
        # = the output must change; a constant is forbidden)
        ("★ render.block_not_constant",
         lambda: render_block(full) != render_block({"facts": {"a": 4752}})),
        # (3) empty input must be reported
        ("★ render.empty_ledger_says_so",
         # An empty ledger must **additionally state it** (a non-empty line beyond
         # PREAMBLE), and **must not** render a table.
         lambda: (lambda b: _extra_lines(b) != []
                  and not any(ln.lstrip().startswith("|")
                              for ln in body_of(b).splitlines()))(
             render_block({"facts": {}}))),
        ("★ render.empty_differs_from_full",
         lambda: render_block({"facts": {}}) != render_block(full)),
    ]


def _selftest():
    import os  # noqa: PLC0415
    import sys  # noqa: PLC0415
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from gate import activate_or_fatal, selftest  # noqa: PLC0415
    # Activation happens **before** the selftest: a package set but absent =>
    # FATAL rc 2 (previously this entry never activated, so
    # `REFLECT_LANG=de render.py --selftest` silently returned rc=0 for a
    # nonexistent package).
    rc = activate_or_fatal()
    if rc:
        return rc
    return selftest(M("gate.title.render"), _cases())


MODULE = module_meta("Machine block rendering", "the single origin of the numbers (pure functions)", selftest=True)


if __name__ == "__main__":
    import os  # noqa: PLC0415
    import sys  # noqa: PLC0415
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(_selftest())
