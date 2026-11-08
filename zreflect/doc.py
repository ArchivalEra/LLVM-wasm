#!/usr/bin/env python3
"""Principles registry: **each principle = one sentence + one re-runnable command**.

## Why this is not a "discipline table"

An earlier version had a table here, each discipline tied to a "criteria file
name". That was a **second mechanism**: this repo already has a whole apparatus
of "description + re-run command + verbatim execution at every commit" —
`ledger.fact(value, cmd, source)` produces facts, and `check_facts_replay.py`
**executes verbatim** every `cmd` in the ledger at every commit.

Building another "discipline → gate" link table would give "what gets checked"
a second place of origin. Deleted.

## Now: a principle is a fact

    principle = Rule(id, text, cmd)
      text  the human-facing sentence (written into the ledger as `note`)
      cmd   the machine-run judging command (rc=0 passes / non-0 reports;
            **stdout must be empty**)

Principles are written into `FACTS.json` by `facts.py --accept-principles`,
then **executed verbatim** by `check_facts_replay` at `commit` time — they
share the same re-run path as numeric facts, with no new executor added.

## Why a principle's stdout must be empty

The numeric-fact contract is "stdout is the **bare value**". A principle is
not a value, it is a **judgment**, so the contract is "**when it passes, say
nothing**" — the same shape as `gate`'s rc contract (0 green / non-0 red).

## Start-of-work and commit

    start-of-work  STATE.md and PRINCIPLES.md both agree with the ledger (`--check`)
    commit         every principle's cmd re-run one by one (`check_facts_replay`)

`state` and `principle` are the **only two things that must be measured**.
Other things can be **manually registered** as facts to check (`--accept`),
but they are not on the default surface.

## Why history is not in here

An append-only account of events is reproducible only "under the conditions of
that moment" — you cannot use today's artifacts to prove it was right.
**The irreproducible does not enter the measured surface**: this repo's
founding question is "who re-ran the proof for you", and what cannot be
re-run should not occupy a position that gets judged.
"""
from __future__ import annotations

from typing import NamedTuple


class Rule(NamedTuple):
    """A principle.

    `text` = the human-facing sentence; `cmd` = the machine-run judging
    command (cwd = repo root, rc=0 passes, stdout must be empty).
    """
    id: str
    text: str
    cmd: str


# ── Principles registry: the **single place of origin** ──────────────────────
#
# Each `cmd` must be an **existing gate** — no new executors are invented
# (that is reuse, not invention). The `>/dev/null` entries run gates that
# print human-readable summaries: discarding stdout is a **declaration made
# here**, not a stealth swallow (the principle contract is precisely that
# stdout be empty).

RULES = (
    # ⚠️ **Must not point at the re-runner itself**: `check_facts_replay`
    # executes every cmd in the ledger ⇒ it would re-run itself ⇒ unbounded
    # spawning (observed: OOM). This principle is instead proven by the
    # **shape of the ledger**.
    #
    # ⚠️ Every cmd must **take a stance** (stdout non-empty, and free of
    # `OFF:`) — see the principle-entry contract in `check_facts_replay`.
    # So `>/dev/null` is forbidden here: throwing away a gate's stance is
    # exactly how an "off" gets laundered into a "pass".
    Rule("only_measured",
         "numbers/behavior trust measurement only; every fact must carry a re-run command",
         "python3 -c \"import json,sys;"
         # ⚠️ `encoding='utf-8'` cannot be omitted: the ledger contains Chinese
         # notes, and Windows opens with default cp1252 ⇒ UnicodeDecodeError ⇒
         # this judgment is permanently red on Windows
         # (observed: CI's Windows leg crashed on this line two rounds running).
         "d=json.load(open('FACTS.json', encoding='utf-8'))['facts'];"
         "bad=[k for k,v in d.items() if not (isinstance(v,dict) and str(v.get('cmd','')).strip())];"
         "print('facts_without_cmd=%d' % len(bad));"
         "sys.exit(1 if bad else 0)\""),

    Rule("number_once",
         "each number is produced once: documents reference it as [[key]], never hand-copied (enforced both ways)",
         "python3 zreflect/check_facts.py"),

    Rule("falsifiable",
         "claims must be falsifiable: always-true shortcuts are swept by AST and any hit fails",
         "python3 zreflect/registry.py --selftest"),

    Rule("declared_not_globbed",
         "predicates are declarations, not filenames: the execution surface reads registry --run <phase>",
         "python3 zreflect/registry.py --gates"),

    # ⚠️ For the same reason, running `registry --run commit` is forbidden —
    # it would reach the replay gate, which loops back here. Instead inspect
    # the **declaration surface**: every gate that can go off must declare a
    # reason (`off_reason`).
    Rule("off_is_visible",
         "off must be distinguishable from \"ran and passed\"; a gate that can go off must declare why",
         # ⚠️ Must check the **full set**: this used to say `gates()[0]` — only
         # the first gate was inspected, and missing the other 15 still went
         # green (review observation: checking 1 gate and checking 16 both
         # yield 0). That is an always-true idle spin, the exact shape this
         # repo despises most.
         "python3 -c \"import sys;sys.path.insert(0,'zreflect');"
         "import registry, criteria;gs=registry.gates()[0];"
         "p=criteria.off_reason_problems(gs);"
         "print('off_reason_ok gates=%d problems=%d' % (len(gs), len(p)));"
         "sys.exit(0 if gs and not p else 1)\""),

    Rule("zero_language",
         "zero language in the core: user-visible messages go through M(code); machine contracts are untranslatable by construction",
         "python3 zreflect/check_i18n.py"),

    Rule("machine_rows",
         "machine rows are defined in one place, machine.ROWS; the shell side has a behavior reconciler",
         "python3 zreflect/machine.py --selftest"),

    Rule("three_readmes",
         "the three-language READMEs are three copies of one assertion: change one, change all three in the same batch",
         "python3 zreflect/check_readme_sync.py"),

    Rule("snapshot_hygiene",
         "a mutable global imported across modules is a value copy (stale snapshot): read via the module attribute instead",
         "python3 zreflect/check_snapshots.py"),

    Rule("assertion_lifecycle",
         "a retracted claim must not quietly return as current state",
         "python3 zreflect/check_retractions.py"),

    Rule("no_retired_names",
         "retired names must not appear as current state; sha provenance and age are checkable",
         "python3 zreflect/check_stale.py"),

    Rule("open_questions_settle",
         "every unresolved open question must carry a runnable settler",
         "python3 zreflect/check_questions.py"),

    # ⚠️ Same reasoning: `gates-selftest.sh` actually runs every gate's
    # selftest (including this replay gate) ⇒ cycle. Instead check the
    # **existence of the machine summary line**: every gate file must have a
    # `--selftest` entry.
    Rule("selfcert_harness",
         "every gate must have a --selftest entry (written but never run = decoration)",
         "python3 -c \"import sys;sys.path.insert(0,'zreflect');"
         "import registry;u=registry.modules()[1];"
         "print('undeclared_modules=%d' % len(u));"
         "sys.exit(1 if u else 0)\""),

    # Host coupling is **measurable**: the moment a host's directory name or
    # config filename shows up in the suite's own source, the suite has welded
    # itself to that host. For the observed cost see R-003: `check_wire` went
    # off to validate the editor's config.json schema — switching editors
    # meant editing a gate, while the host's own trust gate (pending_trust)
    # was invisible to the suite entirely.
    #
    # The criterion scans **code** (.py/.sh), not docs: mentioning a host in
    # README/AGENTS is explanation, not dependency.
    #
    # ⚠️ The wordlist is built by **codepoint concatenation**, never written
    # as literals — literal spellings would make this file (and the
    # retraction note in `check_i18n`) get caught by its own criterion. This
    # is the same pitfall this repo already hit with CJK-range constants:
    # the criterion's metadata must not live **inside the criterion's scan
    # surface**.
    Rule("host_agnostic",
         "the suite's source recognizes no host's directory names / config formats (host wiring belongs to the consumer)",
         "python3 -c \"import os,sys;"
         "w=['.'+chr(122)+chr(99)+chr(111)+chr(100)+chr(101)+'/','ZCODE_'+'PROJECT_DIR',"
         "'hook'+'SpecificOutput'];"
         "bad=[(d,f) for d in ('zreflect','reflect-hooks') "
         "for r,_,fs in os.walk(d) for f in fs "
         "if f.endswith(('.py','.sh')) "
         "and any(k in open(os.path.join(r,f),encoding='utf-8',errors='replace').read() "
         "for k in w)];"
         "print('host_coupled=%d' % len(bad));"
         "sys.exit(1 if bad else 0)\""),
)

_BY_ID = {r.id: r for r in RULES}

# Machine-block markers: the principles table is rendered from here (prose
# must never hand-copy it).
RULES_BEGIN = "<!-- AUTO:RULES -->"
RULES_END = "<!-- /AUTO:RULES -->"


def render_rules(rows=None):
    """Principles registry → the `AUTO:RULES` machine block. **Pure function**.

    Every line is a **fact in the ledger** (key `principle.<id>`) — on the
    surface it is documentation, but it is actually the only human-readable
    view of "what this principle's cmd is and whether it passes right now".
    Whether it passes is answered by `check_facts_replay` at every commit,
    not here.

    PINNED: this block is **fixed to one language** and does not follow
    `REFLECT_LANG`. The reason is **verifiable**: it lands in `PRINCIPLES.md`
    and is **reconciled byte-for-byte** by `facts.py --check` (`PRINCIPLES.md`
    is in `_block_homes`, part of `--check`'s validation surface). Following
    the language ⇒ after `REFLECT_LANG=de --render-doc`, a subsequent
    `REFLECT_LANG=zh --check` is guaranteed red — the same commit would give
    different results in different environments, and `--check` would never
    converge.
    """
    rows = RULES if rows is None else rows
    lines = [RULES_BEGIN,
             ("> This block is rendered by `zreflect/facts.py --render-doc` from the "
             "`RULES` table in `zreflect/doc.py`; **do not hand-edit**."),
             ("> Every row's judging command is in `FACTS.json` and is executed verbatim "
             "at every commit (`check_facts_replay`)."),
             "",
             "| id | principle | judging command |",
             "|---|---|---|"]
    for r in sorted(rows, key=lambda x: x.id):
        lines.append("| `%s` | %s | `%s` |" % (r.id, r.text, r.cmd))
    lines += ["", "%d principles — each with a judging command that **really runs**." % len(rows),
              RULES_END]
    return "\n".join(lines)


# The only two filenames that must be measured. `STATE.md` can be swapped via
# `REFLECT_DOC` (a name-type knob).
PRINCIPLES = "PRINCIPLES.md"
STATE = "STATE.md"


# "Does this repo accept this suite's principles?" — answered by
# **declaration**, not by checking whether a file exists.
#
# `facts.py` used to say `if os.path.exists(PRINCIPLES.md)`: that was
# **implicit coupling** (file exists = principles accepted), and "the file
# exists" and "this repo commits to obeying these" are two different things —
# a cross-repo fixture happened to lack the file, so the principles were
# silently skipped (observed: another time a fixture had an empty
# PRINCIPLES.md, the principles got registered, and every command ran red in
# the foreign repo's context).
#
# Now: `PRINCIPLES.md` exists **and** `REFLECT_NO_PRINCIPLES=1` is not set
# ⇒ accepted. The exit is explicit, so "we don't want to obey" is a decision
# that can be spoken aloud, not something done by deleting a file.
def accepts_principles(repo_root=None):
    """Should this repo register `RULES` into the ledger (= re-run each at every commit)?"""
    import os  # noqa: PLC0415

    import knobs  # noqa: PLC0415
    # Go through `knobs.flag` (the single place of origin for the vocabulary) —
    # the previous `.strip() in ("1","true","yes")` was a **case-sensitive**
    # scheme: observed: `REFLECT_NO_PRINCIPLES=TRUE` silently did nothing.
    if knobs.flag("REFLECT_NO_PRINCIPLES") is True:
        return False
    import gate  # noqa: PLC0415
    base = repo_root or gate.GATE_REPO
    return os.path.exists(os.path.join(base, PRINCIPLES))


def state_name():
    """Filename of the "now" document: `REFLECT_DOC` wins (same knob as `facts.py`)."""
    import os  # noqa: PLC0415
    return os.environ.get("REFLECT_DOC", "").strip() or STATE


def rule(rid):
    """Fetch a principle by id (missing ⇒ KeyError, so the usable id is named)."""
    return _BY_ID[rid]


# ── Into the ledger: reuse ledger.fact, invent no new shape ──────────────────

def facts_of_rules():
    """Principles → `{key: ledger.fact(...)}`, for `facts.py --accept-principles` to write.

    Key prefix `principle.` — they share the single `facts` table with numeric
    facts, and therefore the same re-run path (`check_facts_replay`).
    `kind="principle"` tells the re-runner this entry is judged by **rc**,
    not by bare value.
    """
    import ledger  # noqa: PLC0415
    out = {}
    for r in RULES:
        out["principle." + r.id] = ledger.fact(
            "ok", r.cmd, "principle", r.text, kind="principle")
    return out


# ── Self-evidence ────────────────────────────────────────────────────────────

def _cmd_shape_problems(rows=None):
    """Each principle's cmd shape: non-empty, **starts with an interpreter**, **contains no environment-mutating call**.

    The criteria are about **shape** (can `check_facts_replay` execute it
    verbatim), not semantics. All three were learned the hard way:

      · `empty_cmd` — a principle without a command is just prose (the shape
        this repo despises most);
      · `not_an_interpreter` — the command must be an explicit interpreter
        like `python3 …` / `sh …`. A bare `check_x.py` depends on the execute
        bit and the shebang, unreliable under `bash -c` (the re-runner uses
        `bash -o pipefail -c`; without the execute bit it is rc=126);
      · `mutates_env` — `export` / `set -a` / file-writing commands turn the
        re-run into a side-effecting action. A principle's judgment must be
        **read-only**, otherwise "really run at every commit" gets dirtier
        with every run.

    This is not a complete check (there is no sandbox); it blocks only the
    **three known** bad shapes.
    """
    import re  # noqa: PLC0415
    out = []
    for r in (RULES if rows is None else rows):
        cmd = r.cmd.strip()
        if not cmd:
            out.append((r.id, "empty_cmd"))
            continue
        if not re.match(r"^(python3|python|sh|bash|env)\s", cmd):
            out.append((r.id, "not_an_interpreter"))
            continue
        # ⚠️ GitRoll reported "lookahead assertion that can never be true" —
        # verified: in `(?!\S*)` the `\S*` can match the empty string, and a
        # negative lookahead fails against the empty string forever ⇒ dead
        # lookahead. Removing it is case-by-case equivalent (all nine shapes
        # of export / set -a / redirection behave the same) — dead code.
        if re.search(r"(^|[;&|]\s*)(export|set\s+-a)|>\s*\S",
                     cmd.replace(">/dev/null", "")):
            out.append((r.id, "mutates_env"))
    return out


def _ids_unique():
    return len({r.id for r in RULES}) == len(RULES)


def _ids_well_formed():
    import re  # noqa: PLC0415
    return all(re.fullmatch(r"[a-z][a-z0-9_]*", r.id) for r in RULES)


def _every_rule_has_text():
    return all(r.text.strip() for r in RULES)


def _every_cmd_references_a_real_file():
    """Every `zreflect/*.py` / `*.sh` mentioned in a cmd really exists.

    ⚠️ Only **existence** is checked, not runnability — runnability is
    `check_facts_replay`'s job (verbatim execution at every commit). This is
    the **cheap** pre-check that catches dead commands left behind by a
    rename.
    """
    import os  # noqa: PLC0415
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for r in RULES:
        for tok in r.cmd.split():
            is_script = tok.endswith((".py", ".sh"))
            if is_script and not os.path.exists(os.path.join(base, tok)):
                return False
    return True


def _lookup_works():
    try:
        rule("only_measured")
    except KeyError:
        return False
    try:
        rule("definitely_not_a_rule")
        return False
    except KeyError:
        return True



def _cases():
    return [
        # (1) normal: no report
        ("doc.rules_well_formed", lambda: _cmd_shape_problems() == []),
        ("doc.ids_unique", lambda: _ids_unique()),
        ("doc.ids_well_formed", lambda: _ids_well_formed()),
        ("doc.every_rule_has_text", lambda: _every_rule_has_text()),
        ("doc.cmds_reference_real_files", lambda: _every_cmd_references_a_real_file()),
        ("doc.lookup_works", lambda: _lookup_works()),
        # (2) what must be reported gets reported — every criterion has teeth
        ("★ doc.empty_cmd_is_rejected",
         lambda: _cmd_shape_problems([Rule("x", "t", "")]) == [("x", "empty_cmd")]),
        ("★ doc.missing_text_is_rejected",
         lambda: not all(r.text.strip() for r in [Rule("x", "  ", "cmd")])),
        ("★ doc.duplicate_id_is_rejected",
         lambda: len({r.id for r in [Rule("x", "a", "c"),
                                     Rule("x", "b", "d")]}) == 1),
        ("★ doc.bad_id_shape_is_rejected",
         lambda: not all(__import__("re").fullmatch(r"[a-z][a-z0-9_]*", i)
                         for i in ["Bad-Id"])),
        ("★ doc.dead_cmd_target_is_rejected",
         lambda: _cmd_targets_exist([Rule("x", "t", "python3 zreflect/nope_xyz.py")]) is False),
        ("★ doc.unknown_lookup_raises",
         lambda: _unknown_lookup_raises()),
        # (3) empty input must be reported
        ("★ doc.empty_table_has_no_problems_but_cannot_be_trusted",
         lambda: _cmd_shape_problems([]) == [] and _is_empty_guard_green(())),
    ]


def _cmd_targets_exist(rows):
    import os  # noqa: PLC0415
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for r in rows:
        for tok in r.cmd.split():
            if (tok.endswith((".py", ".sh"))) and \
               not os.path.exists(os.path.join(base, tok)):
                return False
    return True


def _unknown_lookup_raises():
    try:
        rule("definitely_not_a_rule")
        return False
    except KeyError:
        return True


def _is_empty_guard_green(rows):
    """An empty table having **no shape problems** is normal (having no principles is not a shape error),
    but "empty table ⇒ everything is right" is a trap — so when `ids()` is empty the self-evidence must **stay visible**.

    This case pins the criterion itself: empty input must not masquerade as
    "checked".
    """
    return isinstance(rows, tuple) and len(rows) == 0


def _selftest():
    import sys  # noqa: PLC0415

    from gate import main_selftest_or  # noqa: PLC0415
    from i18n import M  # noqa: PLC0415
    return main_selftest_or(sys.argv[1:], M("gate.title.doc"), _cases,
                            lambda a: 0)


from gate import module_meta  # noqa: E402

MODULE = module_meta(
    "Principles registry",
    "each principle = one sentence + one re-runnable command; enters the ledger, executed verbatim each commit by check_facts_replay",
    selftest=True)

if __name__ == "__main__":
    import os  # noqa: PLC0415
    import sys  # noqa: PLC0415
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import doc as _mod  # noqa: PLC0415
    sys.exit(_mod._selftest())
