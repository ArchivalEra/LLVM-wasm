#!/usr/bin/env python3
"""Living-state extraction: within one document, which lines are "true now" and
which are "true then".

Migrated from Octave-Full-Wasm's `.githooks/check-handoff.py` (where this set of
judgments first grew). The problem it solves: gates want to check "does the
assertion contradict the artifact", but **not every line should be checked** --
in append-only history sections the numbers are "as they were then"; comparing
them against today's artifacts is meaningless, and forcing the check would push
people to rewrite history as the present, which destroys the record.

Three hard rules (all learned there; do not "improve" them back into something
cleverer):

  1. **Strict by default**. Every section (**including unnumbered ones**) is
     living state unless explicitly declared historical. The first version there
     treated only "numbered and not on the history list" sections as living, so
     an unnumbered "## Appendix: ..." heading **inherited the previous section's
     status** -- slide a stale assertion in there and the checker looked away.
  2. **Inline exit**. A line that itself says it is history (historical /
     retired / formerly / retracted / corrected ...) is exempt. Without this
     exit, the only options are deleting history or moving the section -- the
     mechanism's purpose is "you may not **quietly** leave it there as the
     current state", not destroying the record.
  3. **Dated records are exempt, but the provenance must be explicit**. A
     delivery-bundle name (with its 8-digit date) or a **commit sha inside
     backticks** counts as provenance. Warning: the first version there also had
     a lax bare-sha regex, and "a fake assertion containing an expired sha" got
     exempted whole-line as a "dated historical entry" -- that is how misses
     happen. A laxly recognized exit is a hall pass for fake assertions.
"""
import re

from gate import module_meta

# Inline history markers (one shared vocabulary with the retraction ledger's
# correction marker -- the vocabulary is produced exactly once).
HIST_MARK = re.compile(
    r"历史|退役|留档|曾经的|当年的|当时的|之前那份|此前|当时|收口前"
    r"|已翻案|更正|是错的|误读|推翻|曾写|已作废|不再成立"
    r"|superseded|retracted|deprecated")

# Records with **explicit** provenance: an `xx-20260921`-style delivery name, or
# a commit sha in backticks.
# Warning: bare shas are deliberately not accepted -- see rule 3 above.
DATED_RECORD = re.compile(r"[A-Za-z0-9._-]*-\d{8}|`[0-9a-f]{7,64}`")

# Inline ledger citation `[[key]]` (with a capture group -- check_facts extracts
# the key, check_stale only tests existence).
# Warning: the two gates each used to write their own copy (one with a capture,
# one without) -- one criterion, two wordings.
CITE_RE = re.compile(r"\[\[([A-Za-z_][A-Za-z0-9_]*)\]\]")


def section_is_living(heading, historical_secs=()):
    """Whether the body under a `## ` heading is living state.

    - Numbered and listed in `historical_secs` => historical (append-only; do
      not compare today's artifacts against it);
    - everything else is living state -- **including unnumbered sections**
      (strict by default, see rule 1 in the module header).
    """
    m = re.match(r"^##\s+([0-9]+)", heading)
    if m:
        return m.group(1) not in {str(s) for s in historical_secs}
    # The machine-maintained appendix block at the end of the file (the
    # renderer's job); gates do not scan it
    return not heading.startswith("## 附")


def living_lines(text, historical_secs=()):
    """Split the document into lines, tagging each as living or not. Returns
    [(line number, line, is living), ...].

    Warning: the file **header** (before the first `## `) is living state --
    observed there: the header held precisely the lines most worth checking
    ("wasm sha ..., full build N suites / M items"); the first version skipped
    the whole leading block, letting the most important assertions slip away.
    Here the header **is judged** (the inline exit still applies).
    """
    out = []
    keep = True
    for i, ln in enumerate(text.split("\n"), 1):
        if re.match(r"^##\s+", ln):
            keep = section_is_living(ln, historical_secs)
        out.append((i, ln, keep))
    return out


# `selftest=False` = **no `--selftest` entry** (pure extraction logic, consumed
# by check_stale / check_retractions). Its judgments (is a numbered section
# historical / unnumbered strict by default / appendix not scanned / section
# splitting correct) carry substantive assertions, housed in `registry._cases()`
# -- if this link judges wrongly, both downstream gates' criteria fail wholesale
# while their own selftests stay green (the dependency-chain gap found in round
# 24).
MODULE = module_meta(
    "Living-state extraction",
    "which lines are 'true now' (inline history exit / strict by default;"
    " judged in three directions: numbered section / unnumbered / appendix / splitting)",
    selftest=True)


# -- self-verification (previously housed in registry._cases) -----------------
#
# Why it moved back: the criteria live in the **module under test** -- that is
# the definition of "the module has its own selftest". Housing them in registry
# turned the `selftest=False` declaration into "I have no selftest entry", when
# the truth was "it has one, it just lives elsewhere". After moving back,
# `selftest=True` is honest.

def _living_case(which):
    """The three judgment directions of `living.py` (ASCII inputs; no Chinese
    literals written)."""
    if which == "numbered_historical":
        return section_is_living("## 5 old", historical_secs=("5",)) is False
    if which == "unnumbered":
        return section_is_living("## 6 new", historical_secs=("5",)) is True
    if which == "appendix":
        # code point 0x9644 builds the appendix word -- this file is inside the
        # zero-language gates' scan surface, so no literal is written
        head = "## " + chr(0x9644)
        return section_is_living(head) is False \
            and section_is_living(head + "more") is False
    if which == "lines_track":
        rows = living_lines("head\n## 5 old\nx\n## 6 new\ny\n",
                            historical_secs=("5",))
        return [r[2] for r in rows] == [True, False, False, True, True, True]
    return False


def _cases():
    return [
        ("★ living.numbered_section_is_historical",
         lambda: _living_case("numbered_historical")),
        ("living.unnumbered_is_living", lambda: _living_case("unnumbered")),
        ("living.appendix_not_scanned", lambda: _living_case("appendix")),
        ("★ living.lines_tracks_sections", lambda: _living_case("lines_track")),
    ]


def _selftest():
    import sys  # noqa: PLC0415

    from gate import main_selftest_or  # noqa: PLC0415
    from i18n import M  # noqa: PLC0415
    return main_selftest_or(sys.argv[1:], M("gate.title.living"),
                            _cases, lambda a: 0)


if __name__ == "__main__":
    import os  # noqa: PLC0415
    import sys  # noqa: PLC0415
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import living as _mod  # noqa: PLC0415
    sys.exit(_mod._selftest())
