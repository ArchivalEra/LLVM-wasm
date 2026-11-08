#!/usr/bin/env python3
"""Trilingual README sync gate: the language versions are three copies of the
same assertion -- touching them in separate batches is drift.

The front-page README has three language copies (by default `README.md`
English + `README.zh.md` + `README.de.md`, names in `REFLECT_READMES`).
Trilingualization introduces a new silent failure mode: **edit one copy,
leave the other two alone** => the three copies go from "one sentence" to
mutually contradictory assertions. The user's discipline (2026-10-01) is
deliberately strict: **every push must update all copies in the same batch**
-- this gate is that discipline's criterion and witness:

  - Default mode (what pre-commit / manual runs / gates-selftest run): the
    **structural criterion** -- every README declared by `REFLECT_READMES`
    must exist, be non-empty, and contain all the trio's file names (the
    language switcher must point at every language: a broken switcher is a
    broken entry point).
    A single-entry list (`REFLECT_READMES=maintaince.md`) => the cross-link
    criterion **degrades**: with only one language, "must point at every
    language" holds vacuously and self-reference is a degenerate requirement
    (issue #8) -- the cross-links are then not checked, with run() saying
    explicitly "not applicable" (same style as other gates declaring an off
    state); the exist / non-empty criteria still apply as usual;
  - `--changed <file|->`: the **push-set criterion** -- read the file paths
    changed in this push from a file (or `-` = stdin, one per line); **every
    README must be in the change set**, reporting one miss per missing copy.
    An empty change set => must report (empty is not a pass). pre-push and
    CI use this mode.
    Warning: the push-set criterion does **not** degrade: with a single
    entry, "every push must update it" remains a real criterion.

Zero-value guards: `REFLECT_READMES` empty => report (judging the "README
group" against an empty list is empty talk); push mode receiving an empty
change set => report.

Warning, the honest boundary: pre-push can be skipped with
`git push --no-verify` -- that is git's native escape and no hook can stop
it. So CI (`.github/workflows/readme-sync.yml`) runs **the same criterion**:
the local hook is the first pain, CI is the commitment's front line.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gate import (  # noqa: E402
    finish,
    machine,  # noqa: E402
    main_selftest_or,
    meta,
    repo,
)
from i18n import M  # noqa: E402


def lang_names():
    """The trilingual README list -- delegates to `knobs.readme_names()` (the
    single source of truth).

    Warning: this used to do its own `os.environ.get("REFLECT_READMES",
    READMES)` here: the **empty string did not fall back** --
    `REFLECT_READMES=` (empty = unset) returned `()`, and the downstream
    zero-value guard reported it as "judging the README group against an
    empty list"; while `knobs.readme_names()` under the same environment
    fell back to the registry correctly. Two criteria, forked empty-string
    semantics (measured).
    """
    import knobs  # noqa: PLC0415
    return tuple(knobs.readme_names())


def problems_structure(files, langs):
    """Structural criterion (pure function: the selftest depends on that).
    `files` = {name: body (unreadable => no key for it)}."""
    out = []
    if not langs:
        # Zero-value guard: an empty list => "all README group members are
        # present" is an undecidable sentence.
        return [M("readme.names_empty_structure")]
    # Single entry => cross-link criterion degrades (issue #8): with only one
    # language, "the switcher must point at every language" holds vacuously
    # and self-reference is a degenerate requirement. The exist / non-empty
    # criteria still apply as usual; cross-links are not checked (run()
    # states the degraded criterion is not applicable -- never pretend to
    # have checked).
    switcher_applies = len(langs) > 1
    for name in langs:
        if name not in files:
            out.append(M("readme.file_missing", name=name))
            continue
        body = files[name] or ""
        if not body.strip():
            out.append(M("readme.file_empty", name=name))
        if not switcher_applies:
            continue
        for other in langs:
            if other not in body:
                out.append(M("readme.switcher_incomplete",
                             name=name, expected=other))
    return out


def problems_push(changed, langs):
    """Push-set criterion (pure function). `changed` = the set of file paths
    changed in this push.

    **Conditional** (matching AGENTS' wording: "touch any one copy => this
    push's change set must contain all copies"):
      - no README touched at all => not applicable (pure code / pure docs
        commits should not be blocked)
      - at least one touched => all copies must be in the push set (one miss
        reported per missing copy)

    **Two list shapes, two criteria** (the distinction from doc lines 12/19):

      - **Multi-entry** (the default trilingual trio) => **conditional**:
        "touch any one copy => this push's change set must contain all
        copies". None touched => not applicable (pure code commits should
        not be blocked).
      - **Single-entry** (`REFLECT_READMES=maintaince.md`, the "use a living
        doc as the README" usage) => **unconditional**: "every push must
        update it". This is the stronger one -- a single-entry list has no
        "same batch" to speak of; its criterion is simply "must be present".

    Warning: this used to be unconditional for **multi-entry** too, so any
    commit not touching a README went red (consecutive CI reds: `0cef263`
    only changed `i18n.py` + the ledger). For multi-entry the documented
    form is conditional.
    """
    out = []
    if not langs:
        return [M("readme.names_empty_push")]
    if not changed:
        return [M("readme.changed_empty")]
    multi = len(langs) > 1
    # Multi-entry conditional form: none touched => not applicable
    if multi and not any(name in changed for name in langs):
        return []
    for name in langs:
        if name not in changed:
            out.append(M("readme.not_in_push", name=name))
    return out


def run(argv):
    langs = lang_names()
    if argv and argv[0] == "--changed":
        src = argv[1] if len(argv) > 1 else "-"
        if src == "-":
            lines = sys.stdin.read().splitlines()
        elif not os.path.exists(src):
            print(machine().emit("fatal", M("readme.changed_file_missing", name=src)),
                  file=sys.stderr)
            return 2
        else:
            lines = open(src, encoding="utf-8", errors="replace").read().splitlines()
        changed = {l.strip().strip('"') for l in lines if l.strip()}
        probs = problems_push(changed, langs)
        return finish(M("readme.title"), probs,
                      M("readme.ok_push", count=len(langs)))
    files = {}
    for name in langs:
        p = repo(name)
        if os.path.exists(p):
            files[name] = open(p, encoding="utf-8", errors="replace").read()
    if len(langs) == 1:
        # The degraded cross-link criterion must be said out loud (issue #8)
        # -- same style as other gates declaring themselves "off": with a
        # single entry the cross-links hold vacuously; never pretend to have
        # checked.
        print(M("readme.switcher_not_applicable", name=langs[0]),
              file=sys.stderr)
    probs = problems_structure(files, langs)
    if len(langs) == 1:
        return finish(M("readme.title"), probs,
                      M("readme.ok_single", name=langs[0]))
    return finish(M("readme.title"), probs,
                  M("readme.ok_structure", count=len(langs)))


LANGS = ("README.md", "README.zh.md", "README.de.md")


def _trio():
    return dict.fromkeys(LANGS, "x [%s](%s) [%s](%s) [%s](%s) x" % (LANGS * 2))


def _cases_structure():
    """(1) Structural criterion: cross-links (trio) / existence / non-emptiness
    (single entry)."""
    return [
        ("readme.trio_linked",
         lambda: problems_structure(_trio(), LANGS) == []),
        # (1) Normal case: no report (single entry: cross-link criterion
        # degrades, issue #8)
        ("readme.single_no_self_reference",
         lambda: problems_structure({"maintaince.md": "# rules\n\nno links here."},
                                    ("maintaince.md",)) == []),
        ("\u2605 readme.file_missing",
         lambda: [p.code for p in problems_structure(
             {k: v for k, v in _trio().items() if k != "README.de.md"}, LANGS)]
         == ["readme.file_missing"]),
        ("\u2605 readme.switcher_incomplete",
         lambda: [p.code for p in problems_structure(
             dict(_trio(), **{"README.md": "only [README.md](README.md) and "
                                            "[README.zh.md](README.zh.md)"}),
             LANGS)] == ["readme.switcher_incomplete"]),
        ("\u2605 readme.file_empty",
         lambda: "readme.file_empty" in [p.code for p in problems_structure(
             dict(_trio(), **{"README.zh.md": "   \n"}), LANGS)]),
        # Single entry: existence / non-emptiness do not degrade (issue #8)
        ("\u2605 readme.single_file_missing",
         lambda: [p.code for p in problems_structure({}, ("maintaince.md",))]
         == ["readme.file_missing"]),
        ("\u2605 readme.single_file_empty",
         lambda: "readme.file_empty" in [p.code for p in problems_structure(
             {"maintaince.md": "  \n"}, ("maintaince.md",))]),
        # (3) Empty input must be reported
        ("\u2605 readme.names_empty_structure",
         lambda: [p.code for p in problems_structure(_trio(), ())]
         == ["readme.names_empty_structure"]),
    ]


def _cases_push():
    """(2) Push-set criterion: trio conditional / single-entry unconditional."""
    return [
        ("readme.push_all_present",
         lambda: problems_push(set(LANGS) | {"code.py"}, LANGS) == []),
        ("readme.single_push_contains_it",
         lambda: problems_push({"maintaince.md", "a.py"}, ("maintaince.md",))
         == []),
        ("\u2605 readme.not_in_push",
         lambda: [p.code for p in problems_push(
             {"README.md", "README.zh.md", "zreflect/facts.py"}, LANGS)]
         == ["readme.not_in_push"]),
        # Single entry: the same-batch criterion does not degrade (issue #8)
        ("\u2605 readme.single_not_in_push",
         lambda: [p.code for p in problems_push({"other.md"}, ("maintaince.md",))]
         == ["readme.not_in_push"]),
        # **Multi-entry conditional**: no README touched at all => not
        # applicable (pure code commits should not be blocked).
        # This is the class that went red on CI at `0cef263` (only i18n.py +
        # the ledger changed) -- the doc specifies a conditional criterion
        # ("touch any one => all copies included"), not an unconditional one.
        ("readme.multi_untouched_is_not_in_scope",
         lambda: problems_push({"zreflect/x.py"},
                               ("README.md", "README.zh.md")) == []),
        # But **touch one and all copies must be included** (otherwise
        # making it conditional would just be letting water through)
        ("\u2605 readme.multi_partial_still_fires",
         lambda: [p.code for p in problems_push(
             {"README.md", "zreflect/x.py"}, ("README.md", "README.zh.md"))
         ] == ["readme.not_in_push"]),
        # (3) Empty input must be reported
        ("\u2605 readme.names_empty_push",
         lambda: [p.code for p in problems_push({"README.md"}, ())]
         == ["readme.names_empty_push"]),
        ("\u2605 readme.changed_empty",
         lambda: [p.code for p in problems_push(set(), LANGS)]
         == ["readme.changed_empty"]),
    ]


def _cases():
    """One group per criterion (structure / push set): they read different
    inputs and govern different things."""
    return _cases_structure() + _cases_push()


GATE = meta("Trilingual README gate",
            "language versions are three copies of one assertion: structural cross-links + same-batch on every push",
            knobs=("REFLECT_READMES",), name_dependent=True)

if __name__ == "__main__":
    sys.exit(main_selftest_or(sys.argv[1:], "check_readme_sync", _cases, run))
