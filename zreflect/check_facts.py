#!/usr/bin/env python3
"""Facts gate: blocks in documents must agree with the ledger, prose must not contain bare numbers, citations must not point at nonexistent keys.

Three rules, each tied to a real incident:

  · Block disagrees with the ledger — someone hand-edited the block (or
    edited the ledger and forgot to re-render);
  · Bare numbers in prose — a number hand-copied into prose starts rotting
    the moment it is written (threshold configurable via `REFLECT_NAKED_MIN`;
    fenced code blocks / inline code are exempt — re-run commands in docs
    naturally contain numbers, and treating those as bare numbers is a false
    positive, issue #3 (4));
  · Citation of a nonexistent key — the key was renamed/deleted and the
    citation became, in place, an assertion with no provenance.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gate  # noqa: E402
from gate import fatal, finish, main_selftest_or, meta, repo  # noqa: E402
from i18n import M, load_pack  # noqa: E402
from knobs import a_pack_lang  # noqa: E402
from ledger import facts_of, load_or_fatal, value_of  # noqa: E402

# How prose cites a number: `[[key]]`. Deliberately a shape that cannot be
# natural language — so "is there a citation" is **decidable**, without
# regex-guessing at prose.
from living import (
    CITE_RE,  # noqa: E402
    DATED_RECORD,  # noqa: E402
)
from render import BLOCK_BEGIN, BLOCK_END, body_of, prose_of, render_block  # noqa: E402

BARE_MIN = 100   # default bare-number threshold: integers below it are not checked (1/2/3 are everywhere; checking them is all noise)
FENCE_RE = re.compile(r"^\s*```")
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


def _bare_min():
    """Bare-number threshold (issue #3 (4)): configurable via `REFLECT_NAKED_MIN`; bad value ⇒ default + warning."""
    raw = os.environ.get("REFLECT_NAKED_MIN", "").strip()
    if not raw:
        return BARE_MIN
    try:
        return int(raw)
    except ValueError:
        print("⚠ %s" % M("facts.bad_bare_min", value=raw, default=BARE_MIN),
              file=sys.stderr)
        return BARE_MIN


def _number_lines(doc_text):
    """Lines the bare-number criterion scans (issue #3 (4)): **fenced code blocks and inline code are exempt**.

    Returns [(line number, line with inline code stripped)]; line numbers keep
    the **original numbering** — diagnostics must line up with the
    human-readable document. The fence open/close lines themselves are not
    scanned.
    """
    prose = prose_of(doc_text)
    in_fence = False
    out = []
    for i, line in enumerate(prose.splitlines(), 1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        out.append((i, INLINE_CODE_RE.sub("", line)))
    return out



# Shape whitelist (issue #24): numbers in these shapes are **not**
# "hand-copied measured values" and must not be reported. If the reverse
# criterion (whitelist-style) did not exclude them, prose would instantly be
# flooded by version numbers/ports/dates and eventually be `--accept`ed away
# wholesale — worse than not checking at all (the repeatedly observed fate of
# this repo: "a gate with false positives eventually gets switched off
# entirely").
_SHAPE_PATTERNS = (
    r"\d+\.\d+(\.\d+)*",          # version strings 11.3.0 / 1.2
    r"[A-Za-z_]\w*\d+\w*",           # digits inside identifiers sha256 / utf8 / v128
    r"\d{4}-\d{2}-\d{2}",            # ISO dates
    r"\d{2}:\d{2}(:\d{2})?",         # times of day
    r"0x[0-9a-fA-F]+",                 # hex
    r"\d+%",                           # percentages
    r"\d+[KMG]i?B",                    # capacities 74MB / 32MiB
    r"[\w./-]+/\d+",                  # path segments /113/
    # Thousands separators (#27 (1)): `6,757,104` is **one number**. Without
    # this entry it gets split into the three fake tokens 6 / 757 / 104, and
    # the latter two get reported as "bare numbers without provenance" —
    # numbers that do not exist anywhere in the original text, so they cannot
    # be matched against the document during triage (downstream observed).
    r"\d{1,3}(,\d{3})+",
)


def _shape_exempt(token):
    """Does this number's **position** fall under the shape whitelist (version/identifier/date/path…)?"""
    return any(re.fullmatch(pat, token) for pat in _SHAPE_PATTERNS)


_SHA_NEAR = re.compile(r"sha|hash|checksum|fingerprint|commit", re.I)


def _known_values(facts):
    """The set of integer values that ever appeared in the ledger (the blacklist criterion "copied but not cited" is checked separately)."""
    known = set()
    for entry in facts.values():
        v = value_of(entry)
        if isinstance(v, int) and not isinstance(v, bool):
            known.add(v)
    return known


def _has_provenance(token, line):
    """Does `token` have provenance in `line` (already stripped of shape strings)?

    Any one hit suffices: shape whitelist / a bare sha with sha context /
    a `[[key]]` on the same line.
    """
    if _shape_exempt(token):
        return True
    # Bare sha: allowed only when the line has sha/hash/commit context (that
    # is check_stale's job; a contextless 8-digit number is a measured value,
    # not a sha — observed pitfall: 99887766 was wrongly allowed by the pure
    # hex whitelist).
    if (re.fullmatch(r"[0-9a-f]{7,64}", token)
            and _SHA_NEAR.search(line)):
        return True
    return bool(CITE_RE.search(line))    # a [[key]] on the same line ⇒ counts as citation-style provenance


def _unaccounted_numbers(facts, bare_min, nlines):
    """Reverse criterion (issue #24): numbers in prose with **no provenance** at or above the threshold.

    Previously only "a ledger value was hand-copied" was checked — a number
    that had **never entered the ledger** was unknown to the gate
    (`AGENTS.md` said "check_facts blocks bare numbers in prose", stated
    without reservation). Downstream observed: a v4 protocol document
    hand-copied 21 numbers and stayed all green; a human review found at
    least 3 of them wrong.

    Criterion (whitelist-style): scan the prose (outside fences/inline code,
    already stripped by `_number_lines`); every integer token ≥ bare_min must
    have one of these **provenances**, otherwise report:

      · immediately followed by `[[key]]` (same line) — citation-style
        provenance;
      · hits the shape whitelist (version string / identifier / date / path /
        bare sha / percentage / capacity);
      · the line carries an explicit provenance marker (`DATED_RECORD`-type
        deliverable name or a backtick sha);
      · the value **exactly equals** some ledger fact's value (the blacklist
        criterion already checks "copied but not cited" separately; not
        double-reported here).
    """
    known = _known_values(facts)
    out = []
    # First strip "shape strings" from the whole line (dates/times/versions/
    # capacities/percentages/paths/identifiers) — otherwise `2026-10-31`
    # yields the fake token `2026` (`-` is not in \w, and per-token matching
    # cannot prevent it; observed pitfall).
    strip_re = re.compile("|".join(_SHAPE_PATTERNS))
    for lineno, line in nlines:
        if DATED_RECORD.search(line):
            continue                     # a record line with explicit provenance is exempt as a whole (same scope as stale)
        line = strip_re.sub(" ", line)
        for token in re.findall(r"(?<![\w.])\d+(?![\w.])", line):
            try:
                val = int(token)
            except ValueError:
                continue
            if val < bare_min or val in known:
                continue
            if _has_provenance(token, line):
                continue
            out.append(M("facts.bare_number_unaccounted",
                         line=lineno, number=token))
    return out


def _cite_problems(prose, facts):
    """`[[key]]` citations in prose that point at nonexistent keys."""
    out = []
    for i, line in enumerate(prose.splitlines(), 1):
        for k in CITE_RE.findall(line):
            if k not in facts:
                out.append(M("facts.missing_key_cite", line=i, key=k))
    return out


def _copied_fact_problems(facts, nlines, bare_min):
    """Blacklist criterion: a ledger value hand-copied into prose without `[[key]]` on the same line."""
    out = []
    for k, entry in sorted(facts.items()):
        v = value_of(entry)
        if isinstance(v, bool) or not isinstance(v, int) or v < bare_min:
            continue
        for i, line in nlines:
            if str(v) in line and ("[[%s]]" % k) not in line:
                out.append(M("facts.copied_value", line=i, value=v, key=k))
    return out


def problems(ledger, doc_text, bare_min=None):
    """Return the problem list (pure function: self-evidence needs it). Empty list = pass.

    `bare_min` overrides the bare-number threshold (passed explicitly by the
    selftest); by default `REFLECT_NAKED_MIN` is read.
    """
    bm = _bare_min() if bare_min is None else bare_min
    f = facts_of(ledger)
    if not f:
        # Zero-value guard: an empty ledger is not "no violations", it is
        # "nothing was measured".
        return [M("facts.empty_ledger")]
    if BLOCK_BEGIN not in doc_text or BLOCK_END not in doc_text:
        return [M("facts.no_block_markers",
                  begin=BLOCK_BEGIN, end=BLOCK_END)]

    out = []
    if body_of(doc_text).strip() != body_of(render_block(ledger)).strip():
        out.append(M("facts.block_mismatch"))

    out += _cite_problems(prose_of(doc_text), f)

    nlines = _number_lines(doc_text)
    out += _copied_fact_problems(f, nlines, bm)
    # Reverse criterion (issue #24): numbers that never entered the ledger need provenance too.
    out += _unaccounted_numbers(f, bm, nlines)
    return out


def _docs_to_scan(argv):
    """The list of documents to scan.

    `argv[0]` given ⇒ scan only that one (explicit wins).
    Otherwise ⇒ **all of `REFLECT_DOCS`**, not just `REFLECT_DOC`.

    ⚠️ Previously only `REFLECT_DOC` was scanned (by default the single
    `STATE.md`), so bare numbers written into a README were **never caught** —
    even though the `REFLECT_DOCS` knob had existed all along, defaulting to
    six documents (STATE / AGENTS / PRINCIPLES / README×3). A repo's "living
    state documents" number six, and the criterion checked one: that is fake
    green (subagent acceptance observed: write 4242 into a README and
    `facts.ok(count=17)` still goes green).
    """
    if argv:
        return [argv[0]]
    raw = os.environ.get("REFLECT_DOCS", "").strip()
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    import knobs  # noqa: PLC0415
    return [x.strip() for x in knobs.REGISTRY["REFLECT_DOCS"][1].split(",")
            if x.strip()]


def run(argv):
    docs = _docs_to_scan(list(argv))
    facts_name = os.environ.get("REFLECT_FACTS", "FACTS.json")
    led_path = repo(facts_name)
    if not os.path.exists(led_path):
        return fatal(M("facts.ledger_missing", name=facts_name))
    led = load_or_fatal(led_path)
    probs = []
    scanned = 0
    for doc in docs:
        p = gate.repo_path(doc)
        if not os.path.exists(p):
            # A document named in the roster is absent ⇒ report (`REFLECT_DOCS`
            # is a declaration, not a suggestion). But an explicit `argv[0]`
            # keeps the original hard FATAL (that is the caller pointing at
            # the wrong path).
            if len(docs) == 1 and argv:
                return fatal(M("facts.doc_missing", path=p))
            probs.append(M("facts.doc_missing", path=p))
            continue
        scanned += 1
        text = open(p, encoding="utf-8").read()
        if BLOCK_BEGIN in text and BLOCK_END in text:
            # Documents with a machine block: full criteria (block agreement
            # + citations + bare numbers).
            probs += problems(led, text)
        else:
            # Documents without a machine block (README / AGENTS / PRINCIPLES
            # etc.): **only bare numbers and copied values are checked** — no
            # block is required, because the block belongs only to the
            # document `REFLECT_DOC` names (the `--render-doc` target).
            # ⚠️ Previously these documents were **not scanned at all**, so
            # bare numbers written into a README were never caught
            # (subagent acceptance observed: write 4242 into a README and
            # `facts.ok` still goes green).
            # ⚠️ Only the **blacklist** is checked (a ledger value hand-copied
            # without a citation), not "any bare number ≥ threshold" —
            # README / AGENTS naturally teem with technical numbers (HTTP
            # 404 / port 3000 / version numbers), and applying the living
            # state document's whitelist threshold would report 25 noise
            # items (observed). "Numbers that never entered the ledger need
            # provenance too" holds **only for the living state document
            # named by `REFLECT_DOC`**: the numbers there say "this is how it
            # is now", while a README says "how to use it".
            # ⚠️ **No `[[key]]` bad-citation check**: documents like the
            # README **teach users how to write** citations (`` [[key]] ``
            # itself appears in the explanation text), which is not a bad
            # citation. The bad-citation criterion applies only to the
            # living state document named by `REFLECT_DOC` — a
            # `[[nonexistent key]]` there really is a mis-point.
            probs += _copied_fact_problems(facts_of(led), _number_lines(text),
                                           _bare_min())
    return finish(M("facts.title"), probs,
                  M("facts.ok", count=len(facts_of(led)), docs=scanned))


LED = {"facts": {"count": {"value": 4752, "cmd": "c"}}}




def _cases_fixture():
    """Fixture: fake document prose + fake ledger + language-pack probe (the setup section of the old `_cases`, moved in verbatim)."""
    # The fixtures' document prose is **English** (it is scanned input, not
    # output of the core — a Chinese sample like "speed is 4752 times" would
    # make the zero-language gate treat the fixture as a message). The
    # criteria themselves are language-agnostic: bare numbers / citations /
    # the shape whitelist all look only at token shape.
    good = "no bare numbers here.\n" + render_block(LED)
    numberless = {"facts": {"n": {"value": 3, "cmd": "c"}}}
    fifty = {"facts": {"n": {"value": 50, "cmd": "c"}}}

    def codes(ledger, doc, **kw):
        return [p.code for p in problems(ledger, doc, **kw)]

    # Criteria of the kind "the diagnostic must say how to fix it" cannot be
    # verified against the null pack (the null pack only has code + params).
    # So read a **real shipped zh pack from disk** — injecting a fake table
    # only proves "the template I wrote renders the words I wrote" (circular
    # reasoning); reading the real pack turns "the migration lost no
    # semantics" into a falsifiable claim (the zh pack stores, by contract,
    # the verbatim removed text).
    # ⚠️ **Must not hard-code `zh`**: a downstream repo may install only one
    # pack (which is precisely the product's main scenario, "pick one from a
    # set of packs"). It used to hard-code zh, and under
    # `REFLECT_I18N=<a directory with only en>` this selftest went straight
    # red (observed: 17 PASS / 1 FAIL) — the criterion is "rendering
    # fidelity"; which language is irrelevant.
    # With no pack installed at all ⇒ these cases cannot exist (zero packs is
    # a **legal state**: the user picked no language), `a_pack_lang()` returns
    # None ⇒ the real-pack criteria below take the **conditional short
    # circuit** (vacuously true when absent; a pack being installed means it
    # must be complete — a broken pack still goes red, verified).
    pack_lang = a_pack_lang()
    real_pack = load_pack(pack_lang) if pack_lang else {}

    def pack_placeholders(code):
        """The set of placeholder names for a code in that pack (missing entry ⇒ empty set, assertion goes red on the spot)."""
        import re  # noqa: PLC0415
        return set(re.findall(r"%\((\w+)\)", real_pack.get(code, "")))

    return {'good': good, 'numberless': numberless, 'fifty': fifty, 'codes': codes, 'pack_lang': pack_lang, 'real_pack': real_pack, 'pack_placeholders': pack_placeholders}


def _cases_core(fx):
    """See `_cases()`: this group has 9 entries."""
    good, codes = fx["good"], fx["codes"]
    return [
    # (1) normal: no report
    ("facts.block_ok",
     lambda: problems(LED, good) == []),
    ("facts.live_cite_ok",
     lambda: problems(LED, "see [[count]]\n" + render_block(LED)) == []),
    # (2) what must be reported gets reported
    ("★ facts.block_mismatch",
     lambda: codes(LED, "x\n" + render_block({"facts": {}}))
     == ["facts.block_mismatch"]),
    ("★ facts.copied_value",
     lambda: codes(LED, "speed is 4752 times\n" + render_block(LED))
     == ["facts.copied_value"]),
    ("★ facts.missing_key_cite",
     lambda: codes(LED, "see [[nope]]\n" + render_block(LED))
     == ["facts.missing_key_cite"]),
    # (2) reverse criterion (issue #24): numbers that never entered the ledger need provenance too
    ("★ facts.bare_number_unaccounted",
     lambda: codes(LED, "measured 99887766 but not in ledger.\n"
                    + render_block(LED))
     == ["facts.bare_number_unaccounted"]
     and any("99887766" in str(p) for p in problems(
         LED, "measured 99887766 but not in ledger.\n" + render_block(LED))),
     ),
    ("facts.cite_counts_as_provenance",
     lambda: problems(LED, "see [[count]] = 99887766\n"
                      + render_block(LED)) == []),
    # (3) empty input must be reported
    ("★ facts.empty_ledger",
     lambda: codes({"facts": {}}, good) == ["facts.empty_ledger"]),
    ("★ facts.no_block_markers",
     lambda: codes(LED, "a document with no block at all")
     == ["facts.no_block_markers"]),
    ]


def _cases_naked(fx):
    """See `_cases()`: this group has 7 entries."""
    numberless, fifty, codes = fx["numberless"], fx["fifty"], fx["codes"]
    return [
    ("facts.small_int_exempt",
     lambda: problems(numberless, "there are 3\n"
                      + render_block(numberless)) == []),
    ("facts.shape_whitelist",
     lambda: problems(LED, "v11.3.0 and sha256 and 2026-10-31\n"
                      + render_block(LED)) == []),
    ("★ facts.bare_sha_needs_context",
     lambda: codes(LED, "just wrote 99887766\n" + render_block(LED))
     == ["facts.bare_number_unaccounted"]),
    # (4) bare-number criterion extensions (issue #3 (4))
    ("facts.fenced_exempt",
     lambda: problems(LED, "```\nspeed is 4752 times\n```\n"
                      + render_block(LED)) == []),
    ("facts.inline_code_exempt",
     lambda: problems(LED, "see `4752` times\n" + render_block(LED)) == []),
    ("facts.below_threshold_exempt",
     lambda: problems(fifty, "there are 50\n" + render_block(fifty)) == []),
    ("★ facts.threshold_knob",
     lambda: codes(fifty, "there are 50\n" + render_block(fifty), bare_min=10)
     == ["facts.copied_value"]
     and "50" in str(problems(fifty, "there are 50\n" + render_block(fifty),
                              bare_min=10)[0])),
    ]


def _cases_pack(fx):
    """See `_cases()`: this group has 1 entry."""
    pack_lang, pack_placeholders = fx["pack_lang"], fx["pack_placeholders"]
    return [
    ("facts.pack_entry_wired",
     # The real pack's "no provenance" entry must exist and must **accept the
     # exact two params this code actually sends** (delete the code / break a
     # placeholder name ⇒ this case goes red). The assertion uses only ASCII
     # anchors (code name + placeholder names) — Chinese anchors would turn
     # themselves into "natural language inside the core", exactly the shape
     # the zero-language gate exists to eliminate; whether the semantics
     # still say "how to fix" is covered by pack diff review.
     # **Conditional criterion**: a pack installed means it must be complete
     # (delete the entry / break a placeholder ⇒ this case goes red);
     # zero packs (legal state: the user installed no language) ⇒ nothing to
     # verify, vacuously true.
     # A real repo always has packs, so in a real environment this case is
     # always genuinely exercised.
     lambda: not pack_lang or
     pack_placeholders("facts.bare_number_unaccounted")
     == {"line", "number"}),
    ]


def _cases_misc(fx):
    """See `_cases()`: this group has 1 entry."""
    codes = fx["codes"]
    return [
    ("★ facts.bare_number_outside_fence",
     lambda: codes(LED, "```\n4752\n```\nspeed is 4752 times\n"
                    + render_block(LED)) == ["facts.copied_value"]),
    # Thousands separators (#27 (1)): `6,757,104` is **one number** — it must
    # not be split into the three fake tokens 6/757/104 (the 757 produced by
    # splitting does not exist in the original text, so triage cannot match
    # it against the document).
    # Normal: no report (a [[py_lines]] citation is present) + a false
    # positive must go red (after removing the citation the thousands number
    # itself still is not reported, but other bare numbers in the same
    # passage are — so this case only asserts "the thousands number never
    # appears").
    ("★ facts.thousands_separator_is_one_number",
     # Thousands separators (#27 (1)): `6,757,104` is **one number** and the
     # whole thing is stripped by the shape whitelist — it must not be split
     # into 6/757/104 (the 757 produced by splitting does not exist in the
     # original text). Forward: the thousands line yields no fake tokens;
     # reverse: the line's genuine bare number (99887766) must be reported,
     # and only it — proving what got stripped is "the entire thousands
     # number", not "the number chopped up and waved through".
     lambda: problems(LED, "release 6,757,104 B\n" + render_block(LED)) == []
     and codes(LED, "release 6,757,104 B and 99887766 measured\n"
               + render_block(LED)) == ["facts.bare_number_unaccounted"]
     and all("757" not in str(p) and "104" not in str(p)
             for p in problems(LED, "release 6,757,104 B and 99887766 measured\n"
                               + render_block(LED)))),
    ]


def _cases():
    """Assemble the four fixture groups. **Assembly only** — the criteria live in the group functions."""
    fx = _cases_fixture()
    return (
    _cases_core(fx)
    + _cases_naked(fx)
    + _cases_pack(fx)
    + _cases_misc(fx)
    )


GATE = meta("Facts gate", "block agreement / bare numbers / bad citations",
            knobs=("REFLECT_FACTS", "REFLECT_DOC", "REFLECT_NAKED_MIN"), name_dependent=True)

if __name__ == "__main__":
    sys.exit(main_selftest_or(sys.argv[1:], M("gate.title.facts"),
                              _cases, run))
