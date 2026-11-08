#!/usr/bin/env python3
"""Machine-line protocol: the **single source of "which line is a machine line"** (C1 + C4).

This repo previously held **seven mutually unaware copies** of that
knowledge, so the same hole leaked once at each of seven places:

  - `gate.run_phase` used `ln.startswith("OFF:")`
  - `gate.finish` / `fatal` / `off` each assembled `"OFF: %s"` / `"FATAL: %s"`
  - `gate.selftest` printed `PASS | ` / `fail | ` / `note | ` / `=== N PASS / M FAIL ===`
  - `gates-selftest.sh` used `grep -E '^=== [0-9]+ PASS / [0-9]+ FAIL ===$'`
  - `reflect-hooks/*.sh` each printed their own `PASS | ` / `fail | `
  - `i18n._CONTRACT_SHAPES` used four `^`-anchored regexes **looking only at the value's first line**
  - a dozen gates directly did `print("FATAL: %s" % M(...))`

## The shape of the hole (measured, not inferred)

`i18n._validate`'s criterion was `shape.match(value)` -- `^`-anchored => it
judged only the **first line**. A language-pack value of
`"context\\nOFF: masquerading"` was therefore accepted; once rendered, the
`OFF:` stood as its own line, and `run_phase` classified it as `off`.

But the more frequently traveled channel is **parameters**: 144 call sites
fill runtime data (filenames, document lines, exception text) into templates
as `%s`, and 58 templates start with a placeholder (`%(name)s: ...` -- 34
`name`, 6 `path`, 6 `file`). Measured: scanning a file named
`"evil\\nOFF: gate not configured"` renders a forged machine line. **A
language pack is a static asset (changing it goes through code review); a
filename is not.**

`s.splitlines()` recognizes **10** separators (`\\n \\r \\x0b \\x0c \\x1c \\x1d
\\x1e \\x85 U+2028 U+2029`) and does not recognize `\\t \\xa0 \\u200b \\ufeff`.
The defense must use the **same** line-splitting semantics, otherwise the
defense and the consumers each count lines their own way.

## interface

One table + two directions:

    Row(kind, grammar, frame)          # declaration: what this line kind looks like, how to emit it
    ROWS                               # all declarations (including the human tier)
    scan(text) -> tuple[(lineno, kind, line, was-neutralised)]   # consume: are there machine lines in this output
    emit(kind, body) -> str            # produce: emit a machine line (**guaranteed** only line 1 is a machine line)
    clean(text) -> (text', tuple)      # neutralise: break up forged lines in a **rendered result**
    reject(value) -> first forged line | None   # load time: does a language-pack value contain a forged line (broad table)

The two channels have **deliberately different** policies:

  - **Language packs** (static; the author fixes one word) => `reject`
    **loudly refuses**, FATAL rc 2. Uses the **broad table**: any
    `^[A-Z][A-Z0-9_]*:` counts as a reserved prefix (`OFF:` / `FATAL:` /
    `HTTP: 500` / `DNS: failed` ... the author can rephrase; it is not worth
    loosening the other side for that).
  - **Rendered output** (dynamic; the filename cannot be changed) => `clean`
    **neutralises only, never refuses**. Uses the **narrow table**: it breaks
    only shapes consumers **actually parse** (`OFF:` / `FATAL:` / the four
    self-proof prefixes / the machine summary). Things like `HTTP: 500` are
    not machine lines and must not be rewritten without cause.

## Why neutralisation uses a `\\` prefix instead of an error

A half-finished gate crashing because a **filename** contains a newline turns
something the author cannot control into an incident. `\\` is the only
character consumers cannot undo: `strip()` eats leading spaces, and a regex
`^` does not stop anchoring because of `\\`. The cost is the user seeing a
`\\OFF: x` -- which is **intentionally visible**: "this line tried to
masquerade as a machine line; I held it down". `clean` also **reports back**
the neutralised lines to the caller.

## Why `human` is its own tier

`=== ` lines come in two kinds: the machine summary `=== N PASS / M FAIL ===`
(grepped by `gates-selftest.sh`) and the human-readable summary
`=== gate.title.facts selftest: 18 PASS / 0 fail ===` (translatable). The two
grammars are **mutually exclusive** (verified item by item), so banning
`^===` wholesale would be wrong -- it would ban the legitimate human-readable
lines.

## Honest boundaries

  - Under `REFLECT_LANG` the **human-readable summary line** varies
    (translation), so the `human` tier judges shape per line, not content;
    the machine summary line is an emit-site literal and does not vary with
    language.
  - The shell side still holds **one** machine-summary shape:
    `reflect-hooks/einfacht-env.sh` (it must be shell -- hooks `source` it to
    export variables). What guards it is **not** regex reconciliation but
    `harness.run_plugins()`: it actually runs that script and reports
    `harness.no_machine_summary(file=...)` if the summary line's shape is
    wrong (measured: break that line and it names the file).
    (There used to be a `summary_agrees_with_shell()` reconciler here;
    measured as overlapping harness's function with worse attribution, so it
    was deleted.)
"""
from __future__ import annotations

import re
from typing import NamedTuple

# Every separator `str.splitlines()` recognizes. **Do not hand-write a near-copy**
# -- missing one opens a seam between this module and its consumers (measured:
# `\x1c` and `U+2029` are both real line separators).
LINE_BREAKS = ("\r\n", "\n", "\r", "\x0b", "\x0c",
               "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")


class Row(NamedTuple):
    """One kind of machine line: `grammar` judges the **whole line**, `frame` is the emit template."""
    kind: str
    grammar: str
    frame: str


# ⚠️ **Order is priority**: `machine_summary` must be tried before
# `human_summary` -- otherwise `=== 3 PASS / 0 FAIL ===` gets swallowed first
# by human's looser grammar (both grammars **can** match that line; their
# mutual exclusion is guaranteed jointly by the negative lookahead in human
# and this ordering).
ROWS = (
    Row("off",            r"^OFF:",                                     "OFF: %s"),
    Row("fatal",          r"^FATAL:",                                   "FATAL: %s"),
    Row("skip",           r"^SKIP:",                                    "SKIP: %s"),
    Row("down",           r"^DOWN: ",                                   "DOWN: %s"),
    Row("pass",           r"^PASS \| ",                                 "PASS | %s"),
    Row("fail",           r"^fail \| ",                                 "fail | %s"),
    Row("note",           r"^note \| ",                                 "note | %s"),
    Row("machine_summary",
        r"^=== [0-9]+ PASS / [0-9]+ FAIL ===$",                         "=== %d PASS / %d FAIL ==="),
    Row("human_summary",
        r"^=== (?!(?:[0-9]+ PASS / [0-9]+ FAIL) ===$).* ===$",          "=== %s ==="),
)

_KIND = {r.kind for r in ROWS}
_BY_KIND = {r.kind: r for r in ROWS}
# Kinds that can be emitted by filling one `body` via `%s`. `machine_summary`
# needs two integers and goes through `emit_summary` -- two entry points,
# because the parameter shapes genuinely differ (cramming them into one would
# degenerate into a runtime guess of "is the parameter a str or a tuple").
_EMITTABLE = _KIND - {"machine_summary"}

# Narrow table: shapes consumers **actually** parse. Only these get broken up
# in rendered output. `HTTP: 500` / `DNS: failed` / `README: see docs` are not
# in it -- no consumer parses them, and rewriting user-visible text for them
# is gilding the lily.
_SHARP = re.compile(r"^(?:"
                    r"OFF:|FATAL:|SKIP:|DOWN: |PASS \| |fail \| |note \| "
                    r"|=== [0-9]+ PASS / [0-9]+ FAIL ===$"
                    r")")

# Broad table: language-pack load time. Any capitalized word + colon counts as
# a reserved prefix (including `HTTP:`). Rationale: a language pack is
# **static** -- the author just rephrases; loosening this would let prefixes
# like `WARN:` / `ACHTUNG:` that "some consumer might parse someday" slip into
# packs unnoticed.
_BROAD = re.compile(r"^[A-Z][A-Z0-9_]*:")

# Neutralisation prefix. `\` is not eaten by `strip()` and not un-anchored by any `^`.
GUARD = "\\"

# Multi-line values **allowed** in language packs (measured: the continuation
# lines of the 3 existing legitimate multi-line values are all indented with
# spaces). This is not a whitelist; it only explains why per-line judging does
# not kill them -- not one of their lines starts with a machine shape.


def _body(part):
    """One chunk of `splitlines(keepends=True)` -> the body with **at most one** trailing separator removed.

    ⚠️ Do not use `rstrip(...)`: that would also strip a `\\x0b` **legitimately
    contained** in the body.
    """
    for sep in LINE_BREAKS:
        if part.endswith(sep):
            return part[:-len(sep)]
    return part


def _is_sharp(line):
    """Is this **entire line** a machine line consumers parse? (narrow table, for rendered output)"""
    return bool(_SHARP.match(line))


def _is_broad(line):
    """Does this **entire line** fall under a reserved prefix? (broad table, for language-pack load time)"""
    return bool(_BROAD.match(line))


def is_summary(line):
    """Is this whole line the **machine summary** (`=== N PASS / M FAIL ===`)?

    **Single source**: `harness.py` and `reflect-hooks/gate.py` each used to
    hold a byte-identical copy of the regex
    (`^=== [0-9]+ PASS / [0-9]+ FAIL ===$`). Three copies would drift -- now
    they all ask here (the `machine_summary` grammar in `ROWS`).
    """
    return re.match(_BY_KIND["machine_summary"].grammar, line) is not None


def scan(text, keepends=False):
    """Return the machine lines in `text`: `[(lineno, kind, line body)]`.

    Line splitting uses the **same** semantics as `str.splitlines()`
    (`LINE_BREAKS` is exactly its separator set), so this module and
    `run_phase` / `grep` cannot disagree about "how many lines".

    `keepends=False` (default) => returned **line bodies carry no** trailing
    separator (callers print / compare them; a stray `\\n` only sets traps).
    `keepends=True` => separators kept (for reassembling the whole text).
    The two branches used to be reversed: the default path returned lines
    **with** separators.
    """
    out = []
    for i, part in enumerate((text or "").splitlines(keepends=True), 1):
        body = part if keepends else _body(part)
        kind = _kind_of(_body(part))
        if kind:
            out.append((i, kind, body))
    return tuple(out)


def _kind_of(line):
    """Which declared kind does this line belong to? Order is priority (see the comment above `ROWS`)."""
    for r in ROWS:
        if re.match(r.grammar, line):
            return r.kind
    return None


def emit(kind, body=""):
    """Emit one machine line. **Guarantees** that only the first line of the returned string is this `kind`; no other line is a machine line.

    This is the single source for the **producer** side: the prefix in `frame`
    is a literal, and nothing inside `body` may be allowed to forge another
    machine line.
    """
    if kind not in _EMITTABLE:
        raise KeyError("machine.emit_undeclared_kind(kind=%r, available=%r)"
                       % (kind, ", ".join(sorted(_EMITTABLE))))
    text = _BY_KIND[kind].frame % (body,)
    # Line 1 is the machine line we **want**; keep it. The extra lines the body
    # brought in get broken up as usual.
    cleaned, _hits = clean(text, preserve_first=True)
    return cleaned


def emit_summary(passed, failed):
    """The machine summary line (`=== N PASS / M FAIL ===`). The numbers must be integers."""
    if not isinstance(passed, int) or not isinstance(failed, int):
        raise TypeError("machine.emit_summary_needs_ints(passed=%r, failed=%r)"
                        % (passed, failed))
    return "=== %d PASS / %d FAIL ===" % (passed, failed)


def clean(text, kinds=None, preserve_first=False):
    """**Break up** forged machine lines in a rendered result. Returns `(neutralised text, neutralised lines)`.

    `kinds` can restrict which tiers get broken. By default every shape in the
    narrow table is broken -- the set consumers actually parse.

    `preserve_first=True`: the **first line is kept verbatim** (used by
    `emit` -- its first line is exactly "the machine line we want"; breaking
    it would void our own emitted command line). The remaining lines get
    broken as usual: forged lines smuggled in via the body may not take
    advantage of the moment to become rows.
    """
    parts = (text or "").splitlines(keepends=True)
    hits = []
    out = []
    for i, part in enumerate(parts, 1):
        body = _body(part)
        if not (preserve_first and i == 1) and _is_sharp(body):
            kind = _kind_of(body)
            if kinds is None or kind in kinds:
                out.append(GUARD + part)
                hits.append((i, kind, body))
                continue
        out.append(part)
    return "".join(out), tuple(hits)


def reject(value):
    """Load-time criterion for language-pack values: returns the **first** forged line `(lineno, line body)`, or None.

    Broad table: any whole line starting with a capitalized word + colon
    counts. **Per line**, not just the first -- that was exactly what used to
    be missed.

    ⚠️ This uses only the **two explicit tables** (`_BROAD` covers
    capitalized word + colon; `_SHARP` covers the narrow set consumers really
    parse), not "all kinds". Otherwise `human_summary` (`=== ... ===`,
    human-readable, translatable) would be misjudged as a forgery --
    masquerading as a human-readable summary is not a hole, since no consumer
    parses it; masquerading as a **machine** summary is (that one is in
    `_SHARP`).
    """
    for i, ln in enumerate((value or "").splitlines(), 1):
        if _is_broad(ln) or _is_sharp(ln):
            return i, ln
    return None


# ── Self-proof ────────────────────────────────────────────────────────────────

def _try_reject(value):
    """`reject` must flag this value (used for reverse assertions)."""
    return reject(value) is not None


def _clean_has_no_row(value):
    """After neutralisation, no line is any longer a machine line consumers can parse."""
    cleaned, _hits = clean(value)
    return not any(_is_sharp(ln) for ln in cleaned.splitlines())


def _emit_is_single_row(kind, body):
    """The string from `emit`: line 1 is this kind; the remaining lines are not machine lines of any kind."""
    text = emit_summary(1, 0) if kind == "machine_summary" else emit(kind, body)
    rows = scan(text, keepends=True)
    return (len(rows) == 1 and rows[0][0] == 1 and rows[0][1] == kind)


def _packs_have_no_forgery():
    """Run the broad table over every value and line of the **real packs** (not fixtures) -- before the fix this was green on `"x\\nOFF: y"`."""
    import i18n  # noqa: PLC0415
    import knobs  # noqa: PLC0415
    bad = []
    # **Discovery based** (`knobs.installed_langs()`), not a hand-written
    # ("zh","en","de") -- a hand-written roster silently skips newly installed
    # language packs (C4: a hand-written roster always drifts).
    for lang in sorted(knobs.installed_langs()):
        try:
            table = i18n.load_pack(lang)
        except Exception as e:                           # noqa: BLE001
            return [("load_failed", lang, e)]
        for code, value in sorted(table.items()):
            hit = reject(value)
            if hit:
                bad.append((lang, code, hit[0], hit[1][:40]))
    return bad


# All ten real line separators, one by one -- skipping one in verification leaves a seam
_BREAKS = [("\n", "LF"), ("\r", "CR"), ("\x0b", "VT"), ("\x0c", "FF"),
           ("\x1c", "FS"), ("\x1d", "GS"), ("\x1e", "RS"), ("\x85", "NEL"),
           ("\u2028", "LS"), ("\u2029", "PS")]


def _cases_clean():
    """1. Normal non-reports: legitimate content must not be collateral damage of neutralisation."""
    return [
        ("machine.clean_text_is_untouched",
         lambda: clean("all fine here")[0] == "all fine here"),
        # Legitimate multi-line: continuation lines indented, none starting
        # with a machine shape (the shape of the real packs)
        ("machine.legit_multiline_passes",
         lambda: reject("hint\n  set -a; . x; set +a") is None),
        # The body **mentioning** a contract string is legitimate content
        # (prose must be able to say "OFF: is not a failure")
        ("machine.body_mention_is_fine",
         lambda: reject("`OFF:` is not a failure") is None),
        # Human-readable summary lines must pass (they get translated)
        ("machine.human_summary_is_not_machine",
         lambda: reject("=== gate.title.facts selftest: 18 PASS / 0 fail ===")
         is None),
    ]


def _cases_forgery():
    """2. What must be reported gets reported: line separators / broad prefixes / note / machine summary -- four forgery classes."""
    # ⚠️ The inner lambda is bound by **immediate evaluation** of the outer
    # `(lambda sep: ...)(sep)`, not by late capture of the loop variable --
    # ruff's B023 is a false positive here (it only looks at closure shape,
    # not at whether the call is immediate). A named factory would be equally
    # correct, but it would make these 10 assertions inconsistent in shape
    # with the other assertions.
    per_sep = [("\u2605 machine.forgery_%s" % name,
                (lambda sep: lambda: _try_reject(
                    "ctx" + sep + "OFF: masquerading"))(sep))  # noqa: B023
               for sep, name in _BREAKS]
    return per_sep + [
        # Broad table: capitalized word + colon all count as reserved prefixes
        # (a language-pack author just rephrases)
        ("\u2605 machine.broad_prefix_reserved",
         lambda: _try_reject("HTTP: 500")),
        # `note | ` -- previously **completely** slipped through (absent from the shape table)
        ("\u2605 machine.note_prefix",
         lambda: _try_reject("note | delegated")),
        # A **forged** machine summary must be recognized (while human-readable summaries must not)
        ("\u2605 machine.machine_summary_is_machine",
         lambda: _try_reject("=== 9 PASS / 0 FAIL ===")),
    ]


def _cases_empty():
    """3. Empty input must be reported -- "empty" has three meanings here, pinned one by one."""
    return [
        #  - Emitting an empty **body**: the line remains (`OFF: `); it must
        #    not collapse into an empty string or lose the line
        ("\u2605 machine.empty_body_keeps_the_row",
         lambda: emit("off", "") == "OFF: "),
        #  - An empty language-pack value: `""` itself is not a forgery (that
        #    is "this message was never written", governed by `i18n._validate`'s
        #    `pack_empty`). The criterion must not treat it as a machine line.
        ("machine.empty_value_is_not_a_forgery",
         lambda: reject("") is None),
        #  - Scanning empty output: zero lines => zero machine lines
        #    (`run_phase` relies on this to judge ran rather than off)
        ("\u2605 machine.empty_scan_reports_nothing",
         lambda: scan("") == ()),
    ]


def _cases_scrub():
    """The neutralisation channel: parameter injection, idempotence, no collateral damage, inner separators."""
    return [
        # Parameter channel: a filename with an embedded newline => after
        # neutralisation consumers parse no machine line
        ("\u2605 machine.param_filename_neutralised",
         lambda: _clean_has_no_row("evil\nOFF: gate not configured.py")),
        ("\u2605 machine.off_concat_neutralised",
         lambda: _clean_has_no_row("OFF: a\nOFF: b: cfg")),
        # Neutralisation does **not** touch content outside the narrow table
        # (`HTTP: 500` is not a machine line and must not be rewritten)
        ("machine.narrow_does_not_touch_http",
         lambda: clean("HTTP: 500 upstream")[0] == "HTTP: 500 upstream"),
        # The `\` prefix survives strip / regex `^` (a space would be eaten by strip)
        ("\u2605 machine.guard_survives_strip",
         lambda: clean("OFF: x")[0].strip().startswith(GUARD)),
        # A legitimate \x0b inside the body must not be stripped away by rstrip along with the rest
        ("machine.keeps_inner_separator_bytes",
         lambda: clean("a\x0bOFF: x")[0] == "a\x0b" + GUARD + "OFF: x"),
        # Idempotence: neutralising already-neutralised text changes nothing
        ("machine.clean_is_idempotent",
         lambda: (lambda once: clean(once)[0] == once)(clean("OFF: x")[0])),
    ]


def _cases_emit():
    """Output guarantees: emit cannot create a second machine line; the summary line is exact; unknown kinds raise."""
    return [
        ("\u2605 machine.emit_single_row",
         lambda: _emit_is_single_row("fail", "x\nOFF: y")),
        ("\u2605 machine.emit_summary_exact",
         lambda: emit_summary(3, 0) == "=== 3 PASS / 0 FAIL ==="),
        ("\u2605 machine.emit_unknown_kind_raises",
         lambda: _emit_unknown_kind_raises()),
        # scan's line numbers and kinds must be accurate (consumers classify by them)
        ("machine.scan_reports_kind_and_line",
         lambda: scan("ok\nOFF: x\nok")[0][0] == 2
         and scan("ok\nOFF: x\nok")[0][1] == "off"),
    ]


def _cases():
    """Self-proof: every case is a **measured hole** or **measured legitimate content**.

    The five groups are each a named function (clean / forgery / empty input /
    neutralisation channel / output guarantees): in an 80-line flat list,
    "which class is this" was readable only from comment sectioning.
    """
    return (_cases_clean() + _cases_forgery() + _cases_empty()
            + _cases_scrub() + _cases_emit()
            + [("\u2605 machine.real_packs_have_no_forgery",
                lambda: _packs_have_no_forgery() == [])])


def _emit_unknown_kind_raises():
    try:
        emit("bogus", "x")
        return False
    except KeyError:
        return True


def _selftest():
    import sys  # noqa: PLC0415

    # ⚠️ Suspended **inside a function**: `gate` imports this module at top
    # level (consumers of the machine-line protocol need it), so a module-level
    # `from gate import ...` would be circular. Same reason as `i18n.py`.
    from gate import main_selftest_or  # noqa: PLC0415
    from i18n import M  # noqa: PLC0415

    def _run(argv):
        # This module has no CLI: it is a pure function library. Running it as
        # a plain program => say explicitly how to self-prove.
        print(M("machine.no_cli"), file=sys.stderr)
        return 0
    return main_selftest_or(sys.argv[1:], M("gate.title.machine"),
                            _cases, _run)


# ⚠️ The declaration line **must be this literal shape** (`MODULE = module_meta(...)`) --
# `registry.modules()` is an ast parse, it does not execute code; writing
# `MODULE = _declare()` or putting it inside an `if` branch means it never gets
# collected (measured: registry.real_modules_declared goes red on the spot).
# The circularity is solved by **lazy imports** (see the comment on `_selftest`
# above), not by rewriting the declaration shape.
from gate import module_meta  # noqa: E402

MODULE = module_meta(
    "machine-line protocol",
    "the single source of \"which line is a machine line\": one table + scan/emit/clean/reject "
    "(produce, consume, language-pack loading, rendered-output neutralisation -- four paths share the same table)",
    selftest=True)

if __name__ == "__main__":
    import os  # noqa: PLC0415
    import sys  # noqa: PLC0415
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import machine as _mod  # noqa: PLC0415
    sys.exit(_mod._selftest())

