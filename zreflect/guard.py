#!/usr/bin/env python3
"""Ledger write guard: dropped entries / changed values / per-key acceptance
-- the two silent failure modes of re-measurement are intercepted here.

  - **Drop** -- the input is gone => the fact **silently disappears**;
  - **Change** -- the input changed, or was measured wrong => the fact
    **silently becomes another number**. If gates only spot-check a few
    shas, then once an old value elsewhere is overwritten, **it can never be
    found out that it changed**.

It was split out of facts.py's measure() (Phase 4): the guard's **pure
functions** (`dropped_keys` / `changed_keys`, in ledger.py) always had
self-verification, but their **wiring path** (FATAL wording, exit code, the
explicit statement after letting something through) had no self-test -- this
repo's own scar: one guard, due to an undefined variable, never worked from
the day it landed, and it failed in the way "crashes only when it really
should have alarmed" (AGENTS.md hard-pit table). **Wiring is half of a
guard; it must have self-verification.**

interface (decision separated from execution -- the decision is
self-verifiable, execution belongs to measure()):

    decide(old_facts, new_facts, accepted=False, allow_drop=False)
        -> (verdict, problems, notes)

  - verdict = "write" | "refuse";
  - problems = the human-readable reason when refusing (measure prefixes
    FATAL and prints to stderr);
  - notes = {"err": [...], "out": [...]} -- when letting something through,
    **say explicitly** what was let through (allow-drop from --allow-drop
    goes to stderr, accepted changes from --accept-changes go to stdout,
    keeping the existing output streams).

The change guard compares only `value`, not cmd / source / note (those
describe "how to re-run"; editing them is normal doc maintenance --
otherwise the guard turns into noise, gets waved through wholesale, and is
dead). Per-key acceptance (issue #3 item 1): a bare `--accept-changes` flag
accepts all, `=k1,k2` accepts only the listed keys, an empty set accepts
none -- accepting all would wash genuinely broken measurements clean too.
"""
from __future__ import annotations

import os

import gate
from i18n import M
from ledger import changed_keys, dropped_keys, short_value


def _gitignored(path):
    """Is the path covered by .gitignore; non-git repo / git absent => None
    (undecidable, no guessing)."""
    import subprocess  # noqa: PLC0415
    try:
        r = subprocess.run(["git", "-C", gate.GATE_REPO, "check-ignore", "-q", path],
                           capture_output=True)
    except OSError:
        return None
    if r.returncode == 0:
        return True
    if r.returncode == 1:
        return False
    return None                     # rc=128 etc.: not a repo / git broken


def write_target_problems(path, knob_set, ignored=None, carrier_exists=None):
    """**Blind-write guard** (issue #20 item 2): check the target before
    writing to disk. Returns (fatal sentence, warn sentence).

    The disease of having two origins: `Einfacht.env` is only sourced in
    hook context (issue #8); on a manual bare run the **code defaults** take
    over -- if a default path happens to be covered by .gitignore, the write
    "succeeds" and nothing ever shouts (measured downstream: re-measurement
    kept "succeeding" while pre-commit read a different ledger, 40 minutes
    of debugging -- writing into an ignored location equals not writing).

    - Target gitignored => **FATAL** (version control cannot see it, hooks
      read the old ledger forever) -- context-independent, always checked
      (C3 discipline: a criterion's home does not move with context);
    - `ignored=None` (non-git repo / git absent, undecidable) => let it
      through but say so in one line (many fixture scenarios are non-git
      directories; do not block, but do not stay silent);
    - An Einfacht.env carrier exists in the repo while this process set no
      knob => **warn**: the carrier is there and this run did not use it --
      the two origins diverge at this moment, and the write target may
      differ from hook context.
      (The criterion is precise about "carrier exists": a bare run in a repo
      with no carrier is normal usage and warns not.)
    """
    fatal = warn = None
    ig = _gitignored(path) if ignored is None else ignored
    if ig is True:
        fatal = M("guard.write_target_gitignored", path=path)
    elif ig is None:
        warn = M("guard.write_target_no_git")
    if carrier_exists is None:
        carrier_exists = any(os.path.exists(os.path.join(d, "Einfacht.env"))
                             for d in (os.path.join(gate.GATE_REPO, "reflect-hooks"),
                                       gate.GATE_REPO))
    if carrier_exists and not knob_set and ig is not True:
        # Two warns may coexist (the earlier one being "non-git directory")
        # -- assembly belongs to the language pack: with a prefix use
        # `_after` (the template carries the separator), without it the bare
        # sentence.
        warn = (M("guard.write_target_env_carrier")
                if warn is None else
                M("guard.write_target_env_carrier_after", prefix=warn))
    return fatal, warn
from gate import module_meta


def accepted_keys(argv):
    """Parse `--accept-changes[=k1,k2]` (issue #3 item 1): bare flag => None
    (accept all); a key list => a set (empty string => empty set = accept
    none); not given => False (reject all, same as the old behavior)."""
    for a in argv or []:
        if a == "--accept-changes":
            return None
        if a.startswith("--accept-changes="):
            raw = a.split("=", 1)[1].strip()
            return {k.strip() for k in raw.split(",") if k.strip()}
    return False


def filter_accepted(changed, accepted):
    """The part of the change list **not yet accepted** (pure function: the
    selftest depends on that).

    `accepted=None` => accept all; `False` => reject all; a set => keep only
    the keys not listed.
    """
    if accepted is None:
        return []
    if accepted is False:
        return list(changed or [])
    return [c for c in (changed or []) if c[0] not in accepted]


def _drop_verdict(old_facts, new_facts, allow_drop, notes):
    """Guard one: dropped entries (keys vanished). Returns
    `(refusal problem list, whether refused)`."""
    dropped = dropped_keys(old_facts, new_facts)
    if not dropped:
        return [], False
    if not allow_drop:
        return [M("guard.refuse_dropped", count=len(dropped),
                  keys=", ".join(dropped)),
                M("guard.refuse_dropped_advice")], True
    notes["err"].append(M("guard.note_allow_drop", count=len(dropped),
                          keys=", ".join(dropped)))
    return [], False


def _change_verdict(old_facts, new_facts, accepted, notes):
    """Guard two: changed values (the value was swapped). Returns
    `(refusal problem list, whether refused)`."""
    changed = changed_keys(old_facts, new_facts)
    remaining = filter_accepted(changed, accepted)
    if remaining:
        problems = [M("guard.refuse_changed", count=len(remaining))]
        problems += [M("guard.changed_row", key=k, before=short_value(o),
                       after=short_value(n)) for k, o, n in remaining]
        if accepted:
            problems.append(M("guard.accepted_boundary",
                              accepted=len(changed) - len(remaining),
                              keys=", ".join(sorted(accepted))))
        problems.append(M("guard.refuse_changed_advice"))
        return problems, True
    if changed:
        notes["out"].append(M("guard.note_accept_changes", count=len(changed)))
        notes["out"] += [M("guard.changed_row", key=k, before=short_value(o),
                           after=short_value(n)) for k, o, n in changed]
    return [], False


def decide(old_facts, new_facts, accepted=False, allow_drop=False):
    """The **decision** for writing a re-measurement to disk (pure function:
    the selftest depends on that, printing forbidden).

    The two guards are separate named helpers: they judge **different**
    damage (keys vanishing vs values swapped), and their refusal messages
    differ entirely (one advises `--allow-drop`, the other
    `--accept-changes`). Jammed into one function, the two `return "refuse"`
    statements interleave with their notes side effects, and the reader must
    track "which notes have been written already".
    """
    notes = {"err": [], "out": []}
    problems, refused = _drop_verdict(old_facts, new_facts, allow_drop, notes)
    if refused:
        return "refuse", problems, notes
    problems, refused = _change_verdict(old_facts, new_facts, accepted, notes)
    if refused:
        return "refuse", problems, notes
    # Zero-value guard: not a single fact measured => not "no changes",
    # but "nothing was measured at all".
    if not new_facts:
        return "refuse", [M("guard.empty_ledger")], notes
    return "write", problems, notes


def _cases_fixture():
    """Fixture (the setup section of the original `_cases`, moved verbatim)."""
    old = {"a": {"value": 1}, "b": {"value": 2}}
    same = {"a": {"value": 1}, "b": {"value": 2}}
    new_val = {"a": {"value": 1}, "b": {"value": 9}}
    dropped = {"a": {"value": 1}}          # b dropped
    return {'old': old, 'same': same, 'new_val': new_val, 'dropped': dropped}


def _cases_decide(fx):
    """See `_cases()`: 10 cases in this group."""
    old, same, new_val, dropped = (fx["old"], fx["same"], fx["new_val"], fx["dropped"])
    return [
    # (1) Normal case: no report
    ("guard.decide_clean",
     lambda: decide(old, same) == ("write", [], {"err": [], "out": []})),
    ("guard.decide_added_key_not_a_change",
     lambda: decide(old, dict(same, c={"value": 3}))[0] == "write"),
    ("guard.decide_cmd_only_not_a_change",
     lambda: decide({"a": {"value": 1, "cmd": "old"}},
                    {"a": {"value": 1, "cmd": "new"}})[0] == "write"),
    # (2) What must be reported gets reported
    ("★ guard.refuse_dropped",
     lambda: (lambda v, p, n: v == "refuse"
              and p[0].code == "guard.refuse_dropped"
              and "b" in p[0].params["keys"])(*decide(old, dropped))),
    ("★ guard.note_allow_drop",
     lambda: (lambda v, p, n: v == "write"
              and n["err"][0].code == "guard.note_allow_drop"
              and n["err"][0].params["keys"] == "b"
              )(*decide(old, dropped, allow_drop=True))),
    ("★ guard.changed_row",
     lambda: (lambda v, p, n: v == "refuse"
              and any(x.code == "guard.changed_row"
                      and x.params["before"] == "2"
                      and x.params["after"] == "9" for x in p)
              )(*decide(old, new_val))),
    ("★ guard.note_accept_changes",
     lambda: (lambda v, p, n: v == "write"
              and any(x.code == "guard.note_accept_changes" for x in n["out"])
              )(*decide(old, new_val, accepted={"b"}))),
    ("★ guard.accept_changes_per_key",
     lambda: decide(old, new_val, accepted={"zzz"})[0] == "refuse"),
    ("★ guard.accepted_boundary",
     lambda: any(x.code == "guard.accepted_boundary" for x in decide(
         old, {"a": {"value": 8}, "b": {"value": 9}},
         accepted={"a"})[1])),
    ("★ guard.accept_changes_bare_flag",
     lambda: decide(old, new_val, accepted=None)[0] == "write"),
    ]


def _cases_keys(fx):
    """See `_cases()`: 6 cases in this group."""
    old, new_val = fx["old"], fx["new_val"]
    return [
    # Wiring parsing (the parsing semantics of issue #3 item 1, moved into
    # the guard's self-verification surface)
    ("guard.accepted_keys_bare",
     lambda: accepted_keys(["--accept-changes"]) is None),
    ("guard.accepted_keys_list",
     lambda: accepted_keys(["--accept-changes=a,b"]) == {"a", "b"}),
    ("guard.accepted_keys_absent",
     lambda: accepted_keys([]) is False),
    ("guard.accepted_keys_empty_set",
     lambda: accepted_keys(["--accept-changes="]) == set()),
    # (3) Empty input must be reported
    ("★ guard.empty_ledger",
     lambda: decide(old, {})[0] == "refuse"),
    ("★ guard.accepted_keys_empty_set_refuses",
     lambda: decide(old, new_val, accepted=set())[0] == "refuse"),
    ]


def _cases_write(fx):
    """See `_cases()`: 5 cases in this group."""
    return [
    # (2) Blind-write guard (issue #20 item 2)
    ("guard.write_target_clean",
     lambda: write_target_problems("/x/FACTS.json", knob_set=True,
                                   ignored=False, carrier_exists=False)
     == (None, None)),
    ("★ guard.write_target_gitignored",
     lambda: write_target_problems("/x/FACTS.json", knob_set=True,
                                   ignored=True)[0] is not None),
    ("★ guard.write_target_env_carrier",
     lambda: getattr(write_target_problems(
         "/x/FACTS.json", knob_set=False, ignored=False,
         carrier_exists=True)[1], "code", None)
     == "guard.write_target_env_carrier"),
    ("guard.write_target_no_git",
     lambda: getattr(write_target_problems(
         "/x/F.json", knob_set=True, ignored=None)[1],
         "code", None) == "guard.write_target_no_git"),
    ("guard.write_target_env_carrier_after",
     # When two warns coexist, the earlier one must not be lost (assembly
     # belongs to the language pack)
     lambda: getattr(write_target_problems(
         "/x/F.json", knob_set=False, ignored=None,
         carrier_exists=True)[1], "code", None)
     == "guard.write_target_env_carrier_after"),
    ]


def _cases():
    """Assemble the 3 fixture groups. **Assembly only** -- the criteria live
    in the per-group functions."""
    fx = _cases_fixture()
    return (
    _cases_decide(fx)
    + _cases_keys(fx)
    + _cases_write(fx)
    )


MODULE = module_meta("Ledger write guard",
                     "dropped entries / changed values / per-key acceptance (decision separated from execution)",
                     selftest=True)


if __name__ == "__main__":
    import os  # noqa: PLC0415
    import sys  # noqa: PLC0415
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from gate import main_selftest_or, module_meta  # noqa: PLC0415

    def _run(argv):
        print(M("guard.module_banner"), file=sys.stderr)
        return 2
    sys.exit(main_selftest_or(sys.argv[1:],
                              M("gate.title.guard"),
                              _cases, _run))
