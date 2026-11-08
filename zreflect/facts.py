#!/usr/bin/env python3
"""CLI for the facts ledger: measure once, write the ledger, render machine blocks, plus **the two guards**.

Usage
    python3 zreflect/facts.py                      # measure once and write FACTS.json (drops/rewrites are refused)
    python3 zreflect/facts.py --allow-drop         # allow drops this run (dropped keys are printed)
    python3 zreflect/facts.py                      # measure once (numeric facts + principle verdict commands)
    python3 zreflect/facts.py --accept-changes     # allow rewrites this run (old value -> new value is printed)
    python3 zreflect/facts.py --accept-changes=k1,k2  # accept only the listed keys; other rewrites still refused (issue #3 ①)
    python3 zreflect/facts.py --render-doc [file]  # write the machine block into a doc (default STATE.md)
    python3 zreflect/facts.py --check [file]       # does the block in the doc match the ledger
    python3 zreflect/facts.py --get key            # print only that key's value (consumer exit, issue #4 ④)
    python3 zreflect/facts.py show [key]           # print one fact
    python3 zreflect/facts.py --selftest           # self-proof: both guards must be able to go red

⚠️ **If it cannot be measured, do not write it** (better absent than fake). E.g. "latest
all-green regression" is only measurable on a machine with logs; without logs leave that
fact **empty** rather than writing 0 -- 0 is a number, and people will cite it as a result.
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gate  # noqa: E402
import guard  # noqa: E402
import knobs  # noqa: E402
import registry  # noqa: E402
from gate import (  # noqa: E402
    machine,  # noqa: E402
    main_selftest_or,
    module_meta,
    repo,
)
from i18n import M  # noqa: E402
from ledger import age_days, fact, facts_of, load, value_of  # noqa: E402
from render import BLOCK_BEGIN, BLOCK_END, render_block  # noqa: E402

REPO_REAL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_NAME = os.environ.get("REFLECT_FACTS", "FACTS.json")

def _out():
    """Ledger write path. **A function, not a module constant**: `repo()` reads
    `gate.GATE_REPO`, and fixtures change it -- stored as a module-level string the
    path would freeze at import time.
    Observed: after changing `gate.GATE_REPO`, the old `OUT` constant still held the
    original repo path (stale snapshot)."""
    return repo(LEDGER_NAME)
# ⚠️ **Not a module-level constant**: `REFLECT_DOC` is a name-type knob, hooks may
# change it mid-run (fixtures do). `doc.state_name()` reads it fresh every time --
# the single source.
# There used to be an import-time `DOC = os.environ.get(...)` snapshot here, which
# together with `doc.state_name()` formed **two sources** (the exact shape the
# snapshot gate catches).
def _doc():
    import doc  # noqa: PLC0415
    return doc.state_name()


# ══ Your part ══════════════════════════════════════════════════════════════════
_COUNT_CMD = "python3 zreflect/facts.py --count"


def count_files(root, suffix):
    """Number of files under `root` ending in `suffix` (skips `.git`)."""
    n = 0
    for _dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        n += sum(1 for f in filenames if f.endswith(suffix))
    return n


def count_lines(root, suffix):
    """**Total line count** of files under `root` ending in `suffix` (skips `.git`).

    Kept separate from `count_files` rather than one function with a mode flag:
    the two differ in *what they count* (files vs lines); merging them would give
    `cmd` an extra parameter -- and one more place to get it wrong.
    """
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for name in sorted(filenames):
            if not name.endswith(suffix):
                continue
            try:
                with open(os.path.join(dirpath, name), encoding="utf-8",
                          errors="replace") as fh:
                    total += sum(1 for _ in fh)
            except OSError:
                continue                # uncountable files are not counted -- better absent than fake
    return total


_AUTO_BLOCK = re.compile(r"^\s*<!--\s*(/?AUTO:[A-Z]+)\s*-->\s*$")


def _count_file_lines(path):
    """Lines **outside machine blocks** in one `.md` file. Unreadable => 0 (better absent than fake)."""
    total = 0
    in_block = False
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = _AUTO_BLOCK.match(line)
                if m:
                    in_block = not m.group(1).startswith("/")
                    continue
                if not in_block:
                    total += 1
    except OSError:
        return 0                    # unreadable files are not counted -- better absent than fake
    return total


def count_md_lines(root):
    """Lines **outside machine blocks** in `.md` files (cross-platform, pure Python).

    This is the **single implementation** of `md_lines` -- it used to be a
    `find | awk | wc` shell pipeline:
      - Windows has no `find` / `awk` / `wc` (the CI Windows leg would go red);
      - and shell quoting / escaping has its own dialect on each platform.
    The counting logic now lives here; `cmd` is down to "call this one line",
    still replayable verbatim.

    Excludes **all** machine blocks (not just FACTS): `AUTO:GATES` and `AUTO:RULES`
    are also render output; missing them => every render adds +47 lines,
    `check_facts_replay` goes permanently red, and the fix *looks like* "measure
    again" -- re-measuring only writes the new value into the ledger, and the next
    render shifts it again.

    ⚠️ **A marker must be on a line by itself to count as a block boundary** (`^...$`).
    The old awk version (`/<!-- AUTO:[A-Z]+ -->/{b=1; next}`) treated a marker merely
    *mentioned* in prose as a block start -- observed cost: `AGENTS.md` has a line
    saying "`STATE.md` pre-seeds the `<!-- AUTO:FACTS -->` / `<!-- AUTO:GATES -->`
    markers" (describing what `--init` does); from that line on, the **remaining 22
    lines of the file were all excluded**, while the ledger's `md_lines` stayed
    undercounted at 2663 -- no output line anywhere said it was wrong. This is the
    shape this repo hates most.

    The per-file block state machine is factored into `_count_file_lines`: it has its
    own "unreadable => 0" exit.
    """
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        total += sum(_count_file_lines(os.path.join(dirpath, name))
                     for name in sorted(filenames) if name.endswith(".md"))
    return total


def measure_example():
    """**Placeholder implementation -- replace it.** The system provides only the
    mechanism; only you know how to measure your inputs.

    What is measured here has nothing to do with "facts"; it exists so the repo runs
    out of the box. To go live, replace each `fact(value, replay_cmd, source)` with
    numbers you actually measured; especially the replay command -- it must
    **actually run**, otherwise the fact degenerates back into prose.
    """
    facts = {}
    n_py = 0
    n_md = 0
    lines_py = 0
    for root, _dirs, files in os.walk(gate.GATE_REPO):
        if "/.git" in root:
            continue
        for f in files:
            if f.endswith(".py"):
                n_py += 1
                try:
                    lines_py += sum(1 for _ in open(os.path.join(root, f), encoding="utf-8",
                                                    errors="replace"))
                except OSError:
                    pass                      # uncountable files are not counted -- better absent than fake
            elif f.endswith(".md"):
                n_md += 1
    # `cmd` always goes through `facts.py --count ...` (pure Python), never `find | wc`:
    # Windows has no `find` / `wc`, and shell quoting dialects differ per platform.
    # The example replay commands must be cross-platform too -- they are the
    # **template consumers copy**.
    py_files_cmd = "%s -files .py" % _COUNT_CMD
    md_files_cmd = "%s -files .md" % _COUNT_CMD
    facts["py_files"] = fact(n_py, py_files_cmd, "repo",
                             M("facts.note.example_fact"))
    facts["md_files"] = fact(n_md, md_files_cmd, "repo")
    # This one is deliberately above BARE_MIN (check_facts' bare-number threshold = 100)
    # so STATE.md can demonstrate "hand-copying this number gets caught by the gate".
    # Smaller numbers are everywhere; auditing them is all noise => not audited.
    facts["py_lines"] = fact(lines_py, "%s -lines .py" % _COUNT_CMD, "repo",
                             M("facts.note.bare_number_demo"))
    # ⑥ Block exclusion mode (issue #4 ⑥): md_lines counts lines **outside blocks** --
    # machine blocks are rendered into these docs; counting them => the value goes
    # stale on every render => the replay perpetually fails
    # (while check_facts compares "block <-> ledger", both go stale together => all green).
    # awk's FNR==1{b=0} is required: `find -exec {} +` feeds multiple files into the
    # same awk process; without the per-file reset, everything after the first
    # block-bearing file is skipped, while the output still "looks like a line count".
    # The begin marker matches render.py's output verbatim.
    # ⚠️ Exclude **all** machine blocks, not just FACTS: `AUTO:GATES` and `AUTO:RULES`
    # are also render output; missing them => every render adds +47 lines (observed:
    # 38 -> 59 after bootstrap), `check_facts_replay` goes permanently red, and the
    # fix *looks like* "measure again" -- re-measuring only writes 59 into the
    # ledger, and the next render shifts it again.
    # State-machine version: any `<!-- AUTO:* -->` enters a block, the matching end
    # marker leaves it.
    # `cmd` is down to "call this one line": the counting logic lives in
    # `count_md_lines()` (pure Python). Previously a `find | awk | wc` pipeline --
    # Windows has none of those three commands.
    md_lines_cmd = '%s -md' % _COUNT_CMD
    md_lines = count_md_lines(gate.GATE_REPO)
    # cwd=GATE_REPO: both the counting (os.walk(GATE_REPO)) and the replay (gates run
    # cmd verbatim at the repo root) anchor on GATE_REPO -- without cwd, a fixture
    # measures the *caller's* repo's lines, and the renamed-repo selftest goes red
    # (a regression caught by the cross-repo configurability selftest).
    facts["md_lines"] = fact(md_lines, md_lines_cmd, "repo",
                              M("facts.note.excludes_machine_block"))

    # Example: **if it cannot be measured, do not write it**. This fact exists only
    # when UPSTREAM_VERSION is set.
    v = os.environ.get("UPSTREAM_VERSION", "").strip()
    if v:
        facts["upstream_version"] = fact(v, "echo \"$UPSTREAM_VERSION\"", "env",
                                         M("facts.note.measure_or_omit"))
    return facts


# ══ No need to change anything below ═══════════════════════════════════════════
def _has_principles_doc():
    """Does this repo accept the suite's principles? -- The **declaration** lives in
    `doc.accepts_principles()`; this only forwards (the decision exists in one place)."""
    import doc  # noqa: PLC0415
    return doc.accepts_principles()


def _doc_names():
    """Names of docs that carry machine blocks (derived from `_block_homes`'s
    ownership mapping, not a hand-written list).

    ⚠️ **Must respect `REFLECT_NO_PRINCIPLES`** (#27②): `doc.accepts_principles()`
    honors the opt-out, but this used to return both docs unconditionally => a repo
    without a principles doc hit FATAL `doc_missing_check` on `--check`, and
    `gate._prepare(push)` hardcodes `facts.py --check` without doc names =>
    **pre-push always red** -- the same opt-out behaving differently in two places
    is exactly the "one rule, two sources" shape (observed downstream).
    """
    import doc  # noqa: PLC0415
    names = [_doc()]
    if _has_principles_doc():
        names.append(doc.PRINCIPLES)
    return tuple(names)


def _block_homes(ledger):
    """**Block <- doc** ownership (data, not ifs scattered through code).

        AUTO:FACTS -> STATE.md        ledger render, the **single source of the numbers**
        AUTO:GATES -> STATE.md        discovery-based roster render, the **single source of gate narration**
        AUTO:RULES -> PRINCIPLES.md   discipline table render, the **single source of the rules narration**

    Why the discipline block gets its own doc: discipline is "unchanging design
    rules", state is "what is true now", history is "what happened back then".
    Merged into one doc => `check_stale` can only scan the whole thing as live
    state, and any old number surfacing from history goes red.

    Returns ([(doc_name, [(begin, end, rendered), ...]), ...], error message).
    If the roster reconciliation fails (missing declaration / orphans / bad flags)
    => refuse to render -- the criteria have a single source.
    """
    gs, missing = registry.gates()
    probs = registry.problems(gs, missing)
    if probs:
        return None, M("facts.registry_mismatch", entries="\n  · ".join(probs))
    import doc  # noqa: PLC0415
    homes = [(_doc(), [(BLOCK_BEGIN, BLOCK_END, render_block(ledger)),
                       (registry.GATES_BEGIN, registry.GATES_END,
                        registry.render_gates(gs))])]
    # The principles block follows the same opt-out as `_doc_names()` (#27②): a repo
    # that does not adopt principles never touches PRINCIPLES.md, render or check --
    # if one place honors the opt-out and the other doesn't, it only half-works.
    if _has_principles_doc():
        homes.append((doc.PRINCIPLES,
                      [(doc.RULES_BEGIN, doc.RULES_END, doc.render_rules())]))
    return homes, None



def _read_doc(p, path_rel):
    """Read a doc. Returns `(text, rc)`; rc != 0 = FATAL already reported.

    ⚠️ **Unreadable != stale block**: invalid UTF-8 / permissions / a directory --
    all configuration accidents (FATAL rc=2). This used to do a bare
    `open().read()`, so one binary file made Python throw a raw
    `UnicodeDecodeError` and exit with **1** -- and rc=1 means "criterion red" in
    `registry --run`, a completely different fix (swap the file vs fix the content).
    """
    try:
        return open(p, encoding="utf-8").read(), 0
    except (OSError, UnicodeError) as e:
        print(machine().emit("fatal", M("facts.doc_unreadable",
                                        path=path_rel, error=e)),
              file=sys.stderr)
        return None, 2


def _own_blocks(path_rel, ledger):
    """The machine blocks **owned by** this doc. Returns `(blocks, rc)`; rc != 0 = must report.

    ⚠️ **No owner found => must report** (zero-trust guard), no silent-green
    `blocks=[]`. A doc not in the ownership table (say, an old user
    passing a custom name) has no blocks to validate; returning 0 there would be
    saying "no block is stale" -- a sentence that checked nothing.

    `write_doc` and `check_doc` each used to carry a copy of this (comments
    included), so any change had to be made twice -- exactly this repo's assumption
    that "two copies that must agree will eventually disagree".
    """
    homes, err = _block_homes(ledger)
    if err:
        print(machine().emit("fatal", err), file=sys.stderr)
        return None, 2
    # Validate only blocks **belonging to this doc**. Other blocks' markers live in
    # other docs -- not finding them here is normal (previously all blocks were
    # crammed into one doc: the discipline block's markers were not in STATE.md => reported).
    mine = [b for name, blocks in homes
            if name in (os.path.basename(path_rel), path_rel)
            for b in blocks]
    if mine:
        return mine, 0
    print(machine().emit("fatal",
                          M("facts.doc_has_no_home", path=path_rel,
                            known=", ".join(name for name, _ in homes))),
          file=sys.stderr)
    return None, 2


def _replace_blocks(text, blocks, path_rel):
    """Replace each block in place with new content. Returns `(new_text, rc)`.

    Both the begin and end markers must be present -- if missing, the doc has been
    damaged; **never silently append**: silent appending turns "stale block" into
    "two copies of the block", a much harder failure mode to diagnose.
    """
    new = text
    for begin, end, body in blocks:
        if begin not in new or end not in new:
            print(machine().emit("fatal",
                                  M("facts.markers_missing_render",
                                    path=path_rel, begin=begin, end=end)),
                  file=sys.stderr)
            return None, 2
        pre, _, rest = new.partition(begin)
        _, _, post = rest.partition(end)
        new = pre + body + post
    return new, 0


def _swallowed_marker_problems(new, blocks, path_rel):
    """Integrity guard before writing: the replacement must preserve the markers of
    **all** blocks.

    If a marker literal got written into the body (even inside inline code), the
    first-occurrence replacement swallows everything between the two blocks and
    makes other blocks vanish -- observed: a bullet quoting a marker literal wiped
    the whole facts block on one render. Ambiguity => refuse to write; a human fixes
    the doc first (a block's cmd quoting the begin literal is legitimate nesting --
    the `md_lines` awk criterion -- hence no pre-replacement count assertion).
    """
    out = []
    for begin, end, _ in blocks:
        if begin not in new or end not in new:
            out.append(M("facts.marker_swallowed_body",
                         path=path_rel, begin=begin))
    return out


def write_doc(path_rel, ledger):
    """Write the machine block into a doc (in-place replacement). No markers => error,
    **never silently append**.

    The three steps are each a named helper (read / replace / integrity guard): each
    has its own set of "refuse to write" exits; merged together, a reader must count
    returns to know what has already been checked.
    """
    p, blocks, text, rc = _prepare_render(path_rel, ledger)
    if rc:
        return rc
    new, rc = _replace_blocks(text, blocks, path_rel)
    if rc:
        return rc
    swallowed = _swallowed_marker_problems(new, blocks, path_rel)
    if swallowed:
        for x in swallowed:
            print(machine().emit("fatal", x), file=sys.stderr)
        return 2
    if new == text:
        print(M("facts.render_unchanged", path=path_rel))
        return 0
    rc = _write_or_fatal(p, new, path_rel)
    if rc:
        return rc
    print(M("facts.render_written", path=path_rel))
    return 0


def _prepare_render(path_rel, ledger):
    """Three preconditions: doc exists / block ownership checks out / doc is readable.
    Returns `(path, blocks, text, rc)`.

    Any failure returns a non-zero rc (FATAL already reported) -- "does the file
    exist / is the ownership right / can it be read" are three different
    configuration accidents with their own error codes.
    """
    p = gate.repo_path(path_rel)
    if not os.path.exists(p):
        print(machine().emit("fatal", M("facts.doc_missing_render", path=p)),
              file=sys.stderr)
        return p, None, None, 2
    blocks, rc = _own_blocks(path_rel, ledger)
    if rc:
        return p, None, None, rc
    text, rc = _read_doc(p, path_rel)
    return p, blocks, text, rc


def _write_or_fatal(p, new, path_rel):
    """Write to disk. Failure is an **environment accident** (FATAL rc=2), not a
    "stale block" (rc=1).

    The old `open(...).write(...)` turned this into a raw traceback + rc=1 -- the
    caller would go inspect block content while the real problem was an unwritable
    file. Read-only / disk full / permissions all belong to this class.
    """
    try:
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(new)
    except OSError as e:
        print(machine().emit("fatal", M("facts.doc_unwritable",
                                        path=path_rel, error=e)),
              file=sys.stderr)
        return 2
    return 0


def check_doc(path_rel, ledger):
    p = gate.repo_path(path_rel)
    if not os.path.exists(p):
        print(machine().emit("fatal", M("facts.doc_missing_check", path=p)), file=sys.stderr)
        return 2
    blocks, rc = _own_blocks(path_rel, ledger)
    if rc:
        return rc
    text, rc = _read_doc(p, path_rel)
    if rc:
        return rc
    for begin, end, body in blocks:
        if begin not in text or end not in text:
            print(machine().emit("fatal",
                                  M("facts.markers_missing_check",
                                    path=path_rel, begin=begin, end=end)),
                  file=sys.stderr)
            return 2
        cur = text.split(begin, 1)[1].split(end, 1)[0]
        fresh = body.split(begin, 1)[1].split(end, 1)[0]
        if cur != fresh:
            print(machine().emit("fatal",
                                  M("facts.block_stale",
                                    path=path_rel, begin=begin)),
                  file=sys.stderr)
            return 1
    print(M("facts.block_consistent", path=path_rel))
    return 0


def _age_human(entry):
    """Human wording for `measured_at` (issue #3 ②): today / N days ago / unrecorded."""
    d = age_days(entry)
    if d is None:
        return M("facts.age.unrecorded")
    if d < 1:
        return M("facts.age.today")
    return M("facts.age.days_ago", days=int(d))


def _measure():
    """Collection entry (issue #15 A1/C3): dispatch on the `REFLECT_MEASURE_MODULE` knob.

    - Knob unset / module import fails / fixture scenario (gate.GATE_REPO is not this
      repo) => fall back to `measure_example()` (placeholder) and **print a warning**
      -- observed downstream: running facts.py by hand without the knob => empty
      table plus the `--allow-drop` temptation (a scary FATAL in the OM repo about
      "24 facts would drop", whose real cause was just the missing knob). The
      fallback must be audible, never silent.
    - Knob set, import succeeds, and gate.GATE_REPO is the real repo => use the
      knob-designated measure().
    """
    mod_name = os.environ.get("REFLECT_MEASURE_MODULE", "").strip()
    if mod_name:
        try:
            _m = __import__(mod_name)
            fn = getattr(_m, "measure")   # noqa: B009 -- the module is a variable; the fixed attribute name is the contract
        except Exception as e:                            # noqa: BLE001
            # ⚠️ **Configured but unusable => FATAL**, no falling back to the placeholder.
            #
            # This used to print one `⚠ ...unusable` line and run `measure_example()`
            # anyway -- so the user **would believe their own repo was measured**,
            # while the ledger held the suite's own size (observed: module placed at
            # the repo root instead of `zreflect/` => ModuleNotFoundError => silent
            # fallback; STATE.md's `py_lines` said 15765 while the user's project had
            # 67 lines). "Configured but not effective" and "not configured" are two
            # different things: the former is a configuration accident and must be loud.
            print(machine().emit("fatal", M(
                "facts.measure_module_unusable", module=mod_name,
                error=repr(e), hint=M("facts.measure_module_where"))),
                file=sys.stderr)
            raise SystemExit(2) from e
        if os.path.abspath(gate.GATE_REPO) == os.path.abspath(REPO_REAL):
            return fn()
    else:
        # ⚠️ The warning is **repo-independent**: it used to print only when
        # "GATE_REPO is the suite's own repo", so **every downstream repo** (exactly
        # where this hint matters most) silently received "numbers about Einfacht"
        # (subagent acceptance observed: a fresh repo got `py_lines 13269` while its
        # own code was 67 lines -- STATE.md described nothing but the suite's size).
        print("⚠ %s" % M("facts.measure_placeholder_used"), file=sys.stderr)
        # Then one **specific** hint: does this repo have code of its own? If so, say
        # how to measure it.
        own = _own_code_hint()
        if own:
            print("  %s" % own, file=sys.stderr)
    return measure_example()


# Common shapes of "a repo with its own code" (directory names only, no content guessing).
_OWN_CODE_DIRS = ("src", "lib", "app", "pkg", "packages")


def _own_code_hint():
    """Does this repo look like it has its own code? If yes, return one **specific** hint.

    Called only when `REFLECT_MEASURE_MODULE` is unset -- the "you haven't told me
    what to measure" moment, and the only moment a hint is appropriate.
    """
    root = gate.GATE_REPO
    found = [d for d in _OWN_CODE_DIRS if os.path.isdir(os.path.join(root, d))]
    if not found:
        return None
    return str(M("facts.measure_own_code_hint", dirs=", ".join(found)))


def _carry_first_seen(facts, old):
    """Instrument lifecycle (issue #6 ①): keys whose value did not change keep the old
    `first_seen` (changed values / new keys get today stamped by `ledger.fact()`) --
    constancy detection (the pluggable gate `check_instruments.py`) depends on it.
    """
    for key, entry in facts.items():
        prior = old.get(key)
        fs = prior.get("first_seen") if isinstance(prior, dict) else None
        if fs and value_of(prior) == value_of(entry):
            entry["first_seen"] = fs


def _write_ledger_doc(out, facts):
    """Write the ledger to disk. Returns `(rc, error message or None)`."""
    import json  # noqa: PLC0415
    import time  # noqa: PLC0415
    doc = {"schema": 1, "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "_why": M("facts.ledger_why"),
           "facts": facts}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    return 0, None


def measure(argv):
    """Measure once and write the ledger. **Must take `argv`** -- both guards read it.

    ⚠️ Burned here before: `measure()` had no `argv` parameter while the guard tested
    `not in argv`. Because `and` short-circuits, that line was reached **only when a
    drop actually happened** => instead of "which facts dropped" the user got a
    NameError traceback; `--allow-drop` had never worked. The write being blocked was
    **incidental** (the exception fired before the write) -- that is not a guard,
    that is a fault. So this file passes argv explicitly; the guard's **decision**
    lives in `zreflect/guard.py` (decide(), with self-proof of the wiring), and this
    function only executes it.

    The three stages are each a named helper (measure / guard / write): merged, the
    "refuse" and "success" endings interleave, complexity 11.
    """
    facts = _measure()
    # Principles are facts in the same table as the numeric ones -- measured,
    # guarded, and replayed together.
    # "The only two things that must be measured" = STATE (these numbers) and
    # PRINCIPLE (these verdicts).
    #
    # ⚠️ Register principles only in repos **that have PRINCIPLES.md**: the
    # cross-repo fixture's temp dir lacks that doc; copying this repo's principles
    # into its ledger => every command runs in a foreign-repo context, all red
    # (observed). "Does this repo adopt these principles" is decided by **that
    # doc's existence** -- the same declaration `_block_homes` uses (block <- doc),
    # not a second decision mechanism.
    import doc  # noqa: PLC0415
    if _has_principles_doc():
        facts.update(doc.facts_of_rules())

    out = _out()
    # ⚠️ **The shape guard must run before writing**: `measure()` is user-written
    # code, and returning bare values (`{"deploys": 12}`) is the most natural style.
    # That kind of input used to **write the broken ledger first, then crash with a
    # traceback at print time**:
    #
    #     wrote FACTS.json (15 facts)          <- already on disk
    #     TypeError: 'int' object is not subscriptable
    #
    # leaving an entry without a `value` field in the ledger, while the user saw one
    # traceback line.
    rc = _shape_guard(facts)
    if rc:
        return rc
    old = facts_of(_read_or_exit(out)) if os.path.exists(out) else {}

    rc = _guarded_write(argv, old, facts)
    if rc:
        return rc
    _carry_first_seen(facts, old)
    rc, err = _write_ledger_doc(out, facts)
    if err:
        print(machine().emit("fatal", err), file=sys.stderr)
        return 2
    print(M("facts.measure_written",
            path=os.path.relpath(out, gate.GATE_REPO), count=len(facts)))
    for k, v in sorted(facts.items()):
        print("  %-20s %s (%s)" % (k, v["value"], _age_human(v)))
    return 0


def _shape_guard(facts):
    """Shape of `measure()`'s return value: every entry must have `ledger.fact()`'s shape.

    Compliant: `{"key": {"value": ..., "cmd": ..., "source": ...}}`.
    Non-compliant (most common): bare value `{"key": 12}`.

    ⚠️ **Checked before writing**. Bad shapes used to land on disk first and crash
    with a traceback at print time, leaving value-less entries in the ledger with a
    single `TypeError` line as the error. That is "half-written + no field name + no
    guidance" -- the worst possible shape.

    Three legitimate origins: `ledger.fact()` (normal), dicts already in the old
    ledger (the `--accept*` rewrite path), dicts merged via `facts_of(ledger)`. All
    carry a `value` key (or are already of the `{"value": ...}` shape), so the
    criterion is "has a `value` key".
    """
    bad = sorted(k for k, v in (facts or {}).items()
                 if not (isinstance(v, dict) and "value" in v))
    if not bad:
        return 0
    print(machine().emit("fatal", M(
        "facts.measure_bad_shape", count=len(bad),
        keys=", ".join(bad[:6]), hint=M("facts.measure_shape_hint"))),
        file=sys.stderr)
    return 2


def _guarded_write(argv, old, facts):
    """The two guards (drop / rewrite) plus the blind-write guard. Returns rc (0 = pass, 2 = refuse)."""
    verdict, problems, notes = guard.decide(old, facts,
                                            accepted=guard.accepted_keys(argv),
                                            allow_drop="--allow-drop" in argv)
    for x in notes["err"]:
        print(x, file=sys.stderr)
    for x in notes["out"]:
        print(x)
    if verdict == "refuse":
        for x in problems:
            print(machine().emit("fatal", x), file=sys.stderr)
        return 2
    # Blind-write guard (issue #20 ②): check the target before writing -- covered by
    # gitignore => FATAL; repo has an Einfacht.env but the knob is unset this run =>
    # warn (the two sources have diverged at this moment).
    fatal_w, warn_w = guard.write_target_problems(
        _out(), knob_set=bool(os.environ.get("REFLECT_FACTS", "").strip()))
    if warn_w:
        print("⚠ %s" % warn_w, file=sys.stderr)
    if fatal_w:
        print(machine().emit("fatal", fatal_w), file=sys.stderr)
        return 2
    return 0


def get_value(ledger, key):
    """Fetch a ledger value by key -- the **official read-only exit** for consumers in
    any language (issue #4 ④).

    Consumers (CI, test processes in other languages) must go through
    `facts.py --get KEY`, **never parse FACTS.json themselves**: the classic
    hand-written-parser trap is finding the substring `"value"` and grabbing what is
    between the quotes -- the same file is full of `"value": ...`, so you grab the
    value of a **different key**. This fetches the value completely.
    Key absent => (False, error message); present => (True, value).
    """
    f = facts_of(ledger)
    if key not in f:
        return False, M("facts.unknown_key", key=key,
                        existing=", ".join(sorted(f)) or M("facts.none"))
    return True, value_of(f[key])


def _read_or_exit(out):
    """Read the ledger; **a bad file becomes FATAL rc=2**, never a raw traceback.

    ⚠️ This is where the "broken config != red criterion" contract lands: if
    `ledger.Unreadable` bubbled to the top level, Python would print a traceback and
    exit **1** -- and `registry --run` records rc=1 as "criterion red". Observed: one
    bad JSON made `facts.py --check` print a traceback with rc=0, and the caller
    believed the check had run.
    """
    from ledger import Unreadable  # noqa: PLC0415
    try:
        return load(out)
    except Unreadable as e:
        cause = e.args[1] if len(e.args) > 1 else e
        print(machine().emit("fatal", M(
            "facts.ledger_unreadable",
            path=os.path.relpath(out, gate.GATE_REPO), error=cause)),
              file=sys.stderr)
        raise SystemExit(2) from e


def _load_or_empty():
    """Read the ledger; **a missing ledger yields an empty one** (used by `--accept*`).

    Why separate from `_load_or_die`: "manually registering the first fact" and
    "rendering/checking" are two different things -- the former **should be able to
    create the ledger in a fresh repo**, the latter has nothing to check without a
    ledger. Sharing one read path made `--accept` FATAL in fresh repos (observed).
    """
    out = _out()
    if not os.path.exists(out):
        return {"schema": 1, "facts": {}}
    return _read_or_exit(out)


def _load_or_die():
    """Read the ledger; **absent => an actionable hint**, not a raw traceback.
    Why a separate function: on a new repo's first run the ledger does not exist yet,
    and this script would raise a bare FileNotFoundError -- the smell of "hardcoded
    for this repo" (we always have FACTS.json here). The semantics stay fail-loud
    (an empty ledger still refuses to render); the error message just **names the
    next step**."""
    out = _out()
    if not os.path.exists(out):
        # issue #20 ② addendum 2: the old hint "run a measurement at the repo root
        # first" is exactly the action that wrote a stray file -- hint text is part
        # of the "default-value source" too, and must not teach people to step on the
        # rake. Now says "first check where REFLECT_FACTS points".
        print(machine().emit("fatal",
                              M("facts.no_ledger_yet",
                                name=os.path.basename(out),
                                path=os.path.relpath(out, gate.GATE_REPO))),
              file=sys.stderr)
        raise SystemExit(2)
    return _read_or_exit(out)


def main(argv):
    """Command dispatch. **Dispatch only** -- one `cmd_*` handler per command.

    ⚠️ This split is not just about complexity: previously 8 commands shared one
    function body, and `--accept-principles`'s `import doc as _doc` made `_doc` a
    local variable across **all of `main`** => `--render-doc` (no filename; one of
    AGENTS.md's primary commands) threw `UnboundLocalError` before reaching that
    line (see `retractions.json` R-004). Commands no longer share a scope => this
    class of cross-command name pollution disappears structurally.
    """
    kind = _classify(argv)
    if kind == "measure":
        return measure(argv)
    if kind == "help":
        print(_usage(), file=sys.stderr)
        return 0
    if kind == "unknown":
        print(_usage(), file=sys.stderr)
        print(machine().emit("fatal", M("facts.unknown_command",
                                       command=argv[0])), file=sys.stderr)
        return 2
    return _command_table()[argv[0]](argv)


def _classify(argv):
    """First arg -> `"measure"` / `"help"` / `"command"` / `"unknown"`. **Pure function**.

    To prove "an unknown command never falls back to measure", selftests used to call
    `main(["--bogus"])` directly -- but `main(["--accept-changes=k1"])` **really runs
    measure and writes to disk**, so `facts.py --selftest` would pollute the caller's
    `FACTS.json` (observed: the md5 changed while the README said "selftests ...
    never touch the real repo").

    Once the dispatch decision is a pure function, selftests test the **decision**,
    not the **execution** -- the "in the table / is a modifier" judgment still has a
    single source (`_classify`), but proving it no longer requires running the command.
    """
    if not argv:
        return "measure"
    first = argv[0]
    if first in ("--help", "-h", "help"):
        return "help"
    if first in _command_table():
        return "command"
    # ⚠️ `--allow-drop` / `--accept-changes[=keys]` are **modifiers of measure()**,
    # not commands -- they mean "a measure with no subcommand, but allowing a certain
    # class of write". Misclassifying them as unknown commands broke **the only exit
    # that advances the ledger** (observed: `--accept-changes` printed usage and
    # exited 2, and the usage it printed still listed it).
    if first.startswith(("--allow-drop", "--accept-changes")):
        return "measure"
    # ⚠️ **Unknown commands must not fall back to `measure()`**: that would "measure
    # once and write the ledger" -- `--help` / `--bogus` becomes a real write
    # (observed: `facts.py --help` in a half-set-up repo returned rc=0 and rewrote
    # FACTS.json). Nobody expects "asking for help writes a file".
    return "unknown"



# Command name -> handler. **The table lives outside the function**: dispatch itself
# is one line; adding a command = adding a function + one registration line.
# Deliberately a dict rather than an if-chain -- the latter adds a branch per
# command, complexity growing linearly with the command count (observed: 27).
# Command name -> handler. **The table is filled in at the end of the file** (handlers
# are defined in between), so it starts empty; `_command_table()` just gives "reading
# the table" a name, and keeps the "why a table, not an if-chain" explanation next to
# the reading site.
_COMMANDS: dict = {}


def _usage():
    """Usage text (`--help` / unknown command). **Goes through the language pack** --
    the same regime as every other text in the core.

    ⚠️ I once hardcoded English here, arguing "this is the only place a CLI is
    discovered, it shouldn't depend on a pack". That was wrong: it bypassed the hard
    invariant "the core speaks no language", and `check_i18n` only catches CJK, not
    English -- i.e. it slipped through a blind spot this repo itself declared. The
    front door for discovering commands is the **README** (three languages), not
    `--help`. A repo without a pack installed seeing `facts.usage` is the honest state.
    """
    return M("facts.usage")


def _command_table():
    """Command name -> handler.

    Why a table rather than an if-chain: an if-chain's complexity grows linearly
    with the command count (observed up to 27), and each command's body embeds dozens
    more lines, so "which commands exist" sank into 130 lines. The table turns that
    into one readable piece of data; handlers stay independent and individually
    testable.
    """
    return _COMMANDS


def cmd_render(argv):
    """The `--render` command."""
    sys.stdout.write(render_block(_load_or_die()) + "\n")
    return 0


def cmd_render_doc(argv):
    """The `--render-doc` command."""
    return write_doc(argv[1] if len(argv) > 1 else _doc(), _load_or_die())


def cmd_check(argv):
    """The `--check` command."""
    # No doc name given => check **every** doc carrying machine blocks (`_block_homes`
    # is the single source). "The only two things that must be measured" = STATE
    # (numbers) + PRINCIPLE (verdicts) -- both docs are on this surface; skipping one
    # makes that doc's "do not hand-edit" an empty threat.
    if len(argv) > 1:
        return check_doc(argv[1], _load_or_die())
    ledger = _load_or_die()
    rc = 0
    for name in _doc_names():
        r = check_doc(name, ledger)
        rc = rc or r
    return rc


def cmd_get(argv):
    """The `--get` command."""
    if len(argv) < 2:
        print(machine().emit("fatal", M("facts.get_needs_key")), file=sys.stderr)
        return 2
    ok, v = get_value(_load_or_die(), argv[1])
    if not ok:
        print(machine().emit("fatal", v), file=sys.stderr)
        return 2
    print(v)                       # print only the value itself: no explanation, no prefix
    return 0


def _init_skeleton(root, state):
    """Skeleton docs to generate: `{filename: body}`. **Pure data**, never touches disk."""
    import doc  # noqa: PLC0415
    import registry as _reg  # noqa: PLC0415
    return {
        state: (
            "# " + state + "\n\n"
            "> live state: only what is true **now**. Cite numbers by\n"
            "> key (double-bracket form), never hand-copy them.\n\n"
            "## Now\n\n"
            "<!-- write what is true NOW; cite numbers by key -->\n\n"
            + BLOCK_BEGIN + "\n" + BLOCK_END + "\n\n"
            + _reg.GATES_BEGIN + "\n" + _reg.GATES_END + "\n"),
        doc.PRINCIPLES: (
            "# PRINCIPLES\n\n"
            "> design rules that do not change. Each one is a **runnable\n"
            "> command**, replayed by `check_facts_replay` on every commit.\n\n"
            + doc.RULES_BEGIN + "\n" + doc.RULES_END + "\n"),
        "retractions.json": '{"schema": 1, "retractions": []}\n',
        "README.md": (
            "# " + os.path.basename(root) + "\n\n"
            "> the project's human-facing docs. `check_readme_sync` treats the\n"
            "> README trio as three copies of one assertion — if you add\n"
            "> `README.zh.md` / `README.de.md`, keep all three in step.\n"),
        "AGENTS.md": (
            "# AGENTS.md\n\n"
            "Routing only. Rules live in `zreflect/doc.py` (`RULES`);\n"
            "state lives in `" + state + "`; history is not tracked.\n\n"
            "```bash\n"
            "python3 zreflect/registry.py --run commit\n"
            "python3 zreflect/harness.py\n"
            "```\n"),
    }


def _create_missing(root, files):
    """Create missing files, **never overwrite existing ones**. Returns `(created, kept)`."""
    created, kept = [], []
    for name, body in files.items():
        p = os.path.join(root, name)
        if os.path.exists(p):
            kept.append(name)
            continue
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
        created.append(name)
    return created, kept


def _init_principles_into_ledger():
    """Principles must enter the ledger too -- otherwise the `[[RULES:...]]` citations
    in `PRINCIPLES.md` are all broken references in a fresh repo
    (observed: `facts.missing_key_cite(line=3)`)."""
    import doc  # noqa: PLC0415
    if not doc.accepts_principles():
        return
    import json as _json  # noqa: PLC0415
    out = _out()
    facts = dict(facts_of(_load_or_empty()))
    facts.update(doc.facts_of_rules())
    with open(out, "w", encoding="utf-8") as fh:
        _json.dump({"schema": 1, "_why": M("facts.ledger_why"),
                    "facts": facts}, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def _init_questions_dir(root):
    """The `questions/` directory plus one example open question.

    An empty directory is rejected by `check_questions`' zero-trust guard
    (`questions.guard_empty`) -- so we plant a **sample open question**: it doubles as
    the template for "how to write an open question".
    """
    # Delegates to the single source (it strips; the same criterion used to exist in
    # three copies, one without stripping -- observed: an empty string made
    # check_questions treat the repo root as the questions directory).
    qdir = knobs.questions_path(root)
    if not os.path.isdir(qdir):
        os.makedirs(qdir, exist_ok=True)
        print(str(M("facts.init_created", name="questions/")))
    if [n for n in os.listdir(qdir) if n.endswith(".md")]:
        return
    with open(os.path.join(qdir, "01-example.md"), "w", encoding="utf-8") as fh:
        fh.write(
            "# Example open question\n\n"
            "**Status:** ready-for-agent\n\n"
            "**Settling:** `python3 -c \"raise SystemExit(1)\"` "
            "— rc=0 settles A; rc=1 settles B\n\n"
            "Replace this with a real open question, or delete it\n"
            "once you have some.\n")


def _init_env_file(root, state):
    """Write an `Einfacht.env` **matching the docs actually generated**: the default
    knobs assume you already have six docs (STATE/AGENTS/PRINCIPLES/README x3), while
    a new repo only has the few just generated. Skipping this => every gate reports
    "cannot find README.zh.md".

    ⚠️ **If `reflect-hooks/Einfacht.env` already exists, do not create a second one.**
    The plugin (`einfacht-env.sh`) looks in the hooks dir first, then the repo root --
    with both present, **hooks read A while the README tells you to source B**, and
    the doc set `check_facts` scans forks. Observed: one repo had
    `REFLECT_MEASURE_MODULE=...` and `REFLECT_DOCS=STATE.md,README.md,maintaince.md`
    in `reflect-hooks/`, while `--init` wrote
    `REFLECT_DOCS=STATE.md,PRINCIPLES.md,AGENTS.md` at the repo root -- two criteria
    sets running at once, and `--init` said not one word about it.
    """
    import doc  # noqa: PLC0415
    env_path = os.path.join(root, "Einfacht.env")
    if os.path.exists(env_path):
        return
    hooks_env = os.path.join(root, "reflect-hooks", "Einfacht.env")
    if os.path.exists(hooks_env):
        # A carrier already exists (hooks read that one first) -- a second copy only forks.
        print(str(M("facts.init_env_exists_in_hooks")))
        return
    docs = ",".join(n for n in (state, doc.PRINCIPLES, "AGENTS.md")
                    if os.path.exists(os.path.join(root, n)))
    with open(env_path, "w", encoding="utf-8") as fh:
        fh.write("export REFLECT_DOC=%s\n" % state)
        fh.write("export REFLECT_DOCS=%s\n" % docs)
        fh.write("export REFLECT_READMES=README.md\n")
    print(str(M("facts.init_created", name="Einfacht.env")))


def cmd_count(argv):
    """`--count-files SUF` / `--count-lines SUF` / `--count-md`: the ledger's replay commands.

    Separate subcommands rather than inlined in `measure()`: a ledger `cmd` must be
    **replayable verbatim** (`check_facts_replay`), while `measure()` writes to disk
    -- a replayer must not trigger a write.

    All **pure Python**: `find | wc` does not exist on Windows, and `cmd` is the
    template consumers copy -- the template itself must be cross-platform.
    """
    rest = argv[1:]
    if rest == ["-md"]:
        print(count_md_lines(gate.GATE_REPO))
        return 0
    if len(rest) == 2 and rest[0] in ("-files", "-lines"):
        fn = count_files if rest[0] == "-files" else count_lines
        print(fn(gate.GATE_REPO, rest[1]))
        return 0
    print(M("facts.count_usage"), file=sys.stderr)
    return 2


def cmd_init(argv):
    """The `--init` command.

    **Fresh-repo bootstrap**: generate a qualified skeleton in one shot instead of
    making people guess marker names from the docs.

    ⚠️ This command is acceptance-driven (a subagent following `AGENTS.md` verbatim
    in a brand-new repo got stuck on `FATAL: facts.doc_missing_render` -- the docs
    say "create STATE.md" but never say it must contain `<!-- AUTO:FACTS -->` /
    `<!-- AUTO:GATES -->`, and those two strings lived only inside `render.py`'s
    source).

    It **does not overwrite** existing files (only fills gaps) and prints clearly
    what each step did.

    The four artifacts are each a named helper (skeleton / principles into ledger /
    questions dir / env file): merged into one function it was 103 lines of four
    unrelated side effects.
    """
    import doc  # noqa: PLC0415
    root = gate.GATE_REPO
    state = doc.state_name()
    created, kept = _create_missing(root, _init_skeleton(root, state))
    for name in created:
        print(str(M("facts.init_created", name=name)))
    for name in kept:
        print(str(M("facts.init_kept", name=name)))
    if not created:
        return 0
    _init_principles_into_ledger()
    _init_questions_dir(root)
    _init_env_file(root, state)
    print(str(M("facts.init_next")))
    return 0


def cmd_accept_principles(argv):
    """The `--accept-principles` command."""
    # The explicit exit for "principles enter the ledger". **Previously documented
    # only in a docstring, never implemented** (a phantom caught in review) -- yet it
    # is part of the user requirement: "other things can of course also be manually
    # registered as auditable".
    #
    # It writes the **principles' verdict commands** (`principle.*`), never touches
    # numeric facts; the write still passes the same guard (drops / rewrites must be
    # explicitly accepted).
    #
    # ⚠️ The alias must be `doc_mod`, **not `_doc`**: the `else _doc()` line at the
    # top of `main` calls the **module-level function** `_doc()`, and any
    # `import X as _doc` anywhere makes `_doc` a **local variable** for the whole
    # function body => `python3 zreflect/facts.py --render-doc` (no filename; one of
    # AGENTS.md's primary commands) throws `UnboundLocalError` before reaching here.
    # Observed: `ruff --select=F823` had been flagging it all along; no gate ran it.
    import doc as doc_mod  # noqa: PLC0415
    led = _load_or_empty()
    new = facts_of(led)
    new.update(doc_mod.facts_of_rules())
    return _write_ledger(led, new, argv, accept_all=True)


def cmd_accept(argv):
    """The `--accept` command."""
    # Manually register one fact: `--accept <key> <value> <cmd> <source>`
    # (the user's own measurement, without touching measure()). The value must be a
    # **bare value**.
    if len(argv) < 5:
        print(machine().emit("fatal", M("facts.accept_usage")), file=sys.stderr)
        return 2
    key, value = _arg(argv, 1), _arg(argv, 2)
    cmd, source = _arg(argv, 3), _arg(argv, 4)
    if not key or not cmd.strip():
        print(machine().emit("fatal", M("facts.accept_usage")), file=sys.stderr)
        return 2
    led = _load_or_empty()
    new = dict(facts_of(led))
    new[key] = fact(value, cmd, source)
    return _write_ledger(led, new, argv, accept_all=True)


def cmd_show(argv):
    """The `show` command."""
    led = _load_or_die()
    f = facts_of(led)
    keys = [argv[1]] if len(argv) > 1 else sorted(f)
    rc = 0
    for k in keys:
        if k not in f:
            print(M("facts.show_unknown_key", key=k,
                    existing=", ".join(sorted(f))), file=sys.stderr)
            rc = 1
            continue
        e = f[k] if isinstance(f[k], dict) else {"value": f[k]}
        print("%-20s %s" % (k, e.get("value")))
        print(M("facts.show.source", value=e.get("source", "?")))
        print(M("facts.show.cmd", value=e.get("cmd", "?")))
        if e.get("note"):
            print(M("facts.show.note", value=e["note"]))
    return rc


def _arg(argv, i):
    return argv[i] if len(argv) > i else ""


def _write_ledger(led, facts, argv, accept_all=False):
    """Write `facts` back to the ledger (through the same guard). `accept_all` => accept all rewrites this run."""
    out = _out()
    old = facts_of(led)
    accepted = None if accept_all else guard.accepted_keys(argv)
    verdict, problems, notes = guard.decide(old, facts, accepted=accepted,
                                            allow_drop="--allow-drop" in argv)
    for x in notes["err"]:
        print(x, file=sys.stderr)
    if verdict == "refuse":
        for x in problems:
            print(machine().emit("fatal", x), file=sys.stderr)
        return 2
    # ⚠️ **The same blind-write guard**: `measure()` checks the write target first
    # (covered by gitignore => FATAL; carrier present but knob unset => warn).
    # `--accept*` is the **second write path** -- without this check it could write
    # into a gitignored path with rc=0 (observed: with L.json in `.gitignore`,
    # `--accept` wrote anyway while `measure` FATALed). Both paths must pass the same
    # guard (C4).
    fatal_w, warn_w = guard.write_target_problems(
        out, knob_set=bool(os.environ.get("REFLECT_FACTS", "").strip()))
    if warn_w:
        print("⚠ %s" % warn_w, file=sys.stderr)
    if fatal_w:
        print(machine().emit("fatal", fatal_w), file=sys.stderr)
        return 2
    import json  # noqa: PLC0415
    import time  # noqa: PLC0415
    doc = {"schema": 1,
           "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "_why": M("facts.ledger_why"),
           "facts": facts}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(M("facts.measure_written",
            path=os.path.relpath(out, gate.GATE_REPO), count=len(facts)))
    return 0


def _tmp_doc(content, name="doc.md"):
    """A temp doc for selftests (tempfile + atexit cleanup -- it used to write a fixed
    /tmp path, not pid-unique, so two parallel selftests stomped on each other)."""
    import atexit  # noqa: PLC0415
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    d = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, d, True)
    p = os.path.join(d, name)
    open(p, "w", encoding="utf-8").write(content)
    return p


CASES = [
    # ③ Empty input must be reported (the guard's decision wiring is proven in
    #    zreflect/guard.py's selftest; the drop / rewrite pure functions live in
    #    ledger.py's selftest -- each in its own home)
    ("★ facts.check_doc_no_markers",
     lambda: check_doc(_tmp_doc("empty document\n"), {"facts": {"a": 1}}) == 2),
    ("★ facts.check_doc_file_missing",
     lambda: check_doc(os.path.join(_tmp_doc("", "x.md"), "..",
                                    "no_such_%d.md" % os.getpid()),
                       {"facts": {"a": 1}}) == 2),
    # ② Human-readable fact age (issue #3 ②)
    ("facts.age_unrecorded",
     lambda: _age_human({"value": 1}).code == "facts.age.unrecorded"),
    ("facts.age_today",
     lambda: _age_human({"measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}).code
     == "facts.age.today"),
    # ④ The official read-only exit (issue #4 ④)
    ("facts.get_dict_shape",
     lambda: get_value({"facts": {"n": {"value": 12, "cmd": "c"}}}, "n") == (True, 12)),
    ("facts.get_bare_shape",
     lambda: get_value({"facts": {"n": 7}}, "n") == (True, 7)),
    ("★ facts.get_unknown_key",
     lambda: get_value({"facts": {"n": 1}}, "zzz")[0] is False),
    # **Unknown commands must not fall back to measure** (observed: `facts.py --help`
    # once "measured once and wrote the ledger"). `measure` is a **real write** path
    # -- using it as a fallback means every mistyped command rewrites the ledger.
    ("★ facts.unknown_command_is_2", lambda: _unknown_cmd_rc() == 2),
    # Empty-input tier: `--help` is the onboarding surface; must be rc=0 and **must
    # not land on measure** (no ledger write).
    ("★ facts.help_is_not_a_measure",
     lambda: _help_rc() == 0 and not _is_unknown_cmd("--help")),
    # Converse: `--allow-drop` / `--accept-changes` are **measure modifiers**, not
    # commands. The guard above used to classify them as unknown => the only exit
    # that advances the ledger broke (observed).
    ("★ facts.measure_modifiers_route_to_measure",
     lambda: not _is_unknown_cmd("--accept-changes=k1")),
    # **Bootstrap end-to-end convergence**: `--init` -> measure -> two renders ->
    # registry all green.
    ("★ facts.fresh_repo_bootstraps_green", lambda: _fresh_bootstraps()),
    # **Real-project shape**: a repo with build.sh / src / an existing README must
    # also complete the run. There was a time when "any .sh in the repo => the whole
    # chain FATAL"; this is that regression's guard.
    ("★ facts.real_repo_shaped_bootstraps", lambda: _real_repo_shaped()),
    # **The opt-out also applies to --check / --render-doc** (#27②): a repo with
    # `REFLECT_NO_PRINCIPLES=1` must not be blocked by FATAL `doc_missing_check` --
    # the same opt-out behaved differently in doc.accepts_principles (honored) vs
    # _doc_names/_block_homes (formerly not), exactly the "one rule, two sources"
    # shape (downstream observed: pre-push always red).
    ("★ facts.no_principles_opt_out_respected", lambda: _opt_out_check_case()),
    # **A corrupt ledger is a configuration accident, not a red criterion**: must be
    # FATAL rc=2. Observed: a `{ broken` FACTS.json made `--check` print a traceback
    # with rc=0 (the caller believed the check ran), and made gates rc=1 (recorded as
    # "criterion red" in `registry --run` -- users would go fix gates instead of data).
    ("★ facts.corrupt_ledger_is_fatal_not_traceback",
     lambda: _corrupt_ledger_rc() == 2),
    ("★ ledger.corrupt_load_raises_typed",
     lambda: _corrupt_load_raises()),
    # **Environment accidents are always FATAL rc=2**: doc with invalid encoding /
    # unwritable / corrupt ledger -- what they share is "not a content problem".
    # All used to be raw tracebacks + rc=1, and rc=1 is recorded as "criterion red"
    # in `registry --run` (a completely different fix).
    ("★ facts.unwritable_doc_is_fatal",
     lambda: _unwritable_doc_rc() == 2),
]


# The command table is built at the **end of the file**: handlers are defined above,
# and the literals must wait until they exist (evaluating at the top = NameError --
# observed).
_COMMANDS.update({
    "--render": cmd_render,
    "--render-doc": cmd_render_doc,
    "--check": cmd_check,
    "--get": cmd_get,
    "--init": cmd_init,
    "--accept-principles": cmd_accept_principles,
    "--accept": cmd_accept,
    "show": cmd_show,
    "--count": cmd_count,
})


def _unknown_cmd_rc():
    """rc for an unknown command (`--definitely-not-a-command`)."""
    import contextlib  # noqa: PLC0415
    import io  # noqa: PLC0415
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        return main(["--definitely-not-a-command"])


def _help_rc():
    import contextlib  # noqa: PLC0415
    import io  # noqa: PLC0415
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        return main(["--help"])


def _is_unknown_cmd(first):
    """Would this first arg land on the "unknown command" branch? **Goes through the
    pure function `_classify`**.

    ⚠️ This used to call `main([first])` -- for `--accept-changes=k1` that **really
    runs measure and writes to disk**, so `facts.py --selftest` polluted the caller's
    `FACTS.json` (observed: the md5 changed, `--check` then went red, while the README
    said "selftests ... never touch the real repo"). Selftests must be **side-effect
    free**.

    Still not "a copied second judgment": `_classify` is exactly the function `main`
    dispatches with -- the assertion tests the **same logic**, just without executing
    its consequences.
    """
    return _classify([first]) == "unknown"


def _copy_suite_into(d):
    """Copy the suite files **within the platform roster** into fixture repo `d`
    (implementation of #30 direction B).

    ⚠️ Five fixtures used to each `copytree(zreflect/)` -- **the whole directory** --
    under the vendored form (`gate.tool_repo()` resolves to the host root, #30), the
    host's own wiring files (its own gates / measure module / extra language packs)
    got copied into the fresh repo too, while their inputs (specs/ etc.) did not =>
    measure drops facts => `guard.refuse_dropped` FATAL, structurally always-red
    bootstrap.

    The roster is **discovered**: platform modules = `registry.modules()`, gates =
    `registry.gates()` (derived from declaration lines), but the **anchor is the
    suite's own physical location** (`__file__`), not the current process's `zdir()`
    -- in vendored form `zdir()` resolves to the host's wiring directory, whose
    roster mixes in host-owned gates (they also carry `GATE` declarations, so
    discovery collects them); copying them into the fresh repo drags the host's
    criteria surface in (observed: 4 gates red). `facts.py` is a suite platform file;
    the directory it sits in is always the suite -- regardless of how the host wires
    itself.
    Language packs are copied per pack per `installed_langs()` (criterion = a .json
    pack file present).
    Host wiring files never belonged in a fresh repo's bootstrap.
    """
    import shutil  # noqa: PLC0415
    src_z = os.path.dirname(os.path.abspath(__file__))     # the suite itself, not anchored on zdir()
    dst_z = os.path.join(d, "zreflect")
    os.makedirs(dst_z)
    # The roster anchors on the suite dir too (explicit zdir passed -- discovery
    # unchanged, only the anchor moves to the suite's physical location)
    _gs, _missing = registry.gates(src_z)
    mods, _missing2 = registry.modules(src_z)
    roster = sorted({os.path.basename(g["file"]) for g in _gs}
                    | {os.path.basename(m["file"]) for m in mods})
    for rel in roster:
        src = os.path.join(src_z, rel)
        if os.path.isfile(src):
            shutil.copy(src, os.path.join(dst_z, rel))
    # Language packs: copied per pack (installed_langs' criterion is "a .json pack file exists")
    lang_src = os.path.join(src_z, "lang")
    if os.path.isdir(lang_src):
        for n in sorted(os.listdir(lang_src)):
            pkg = os.path.join(lang_src, n)
            if os.path.isdir(pkg) and any(x.endswith(".json")
                                          for x in os.listdir(pkg)):
                shutil.copytree(pkg, os.path.join(dst_z, "lang", n))
    hooks_src = os.path.join(os.path.dirname(src_z), "reflect-hooks")
    if os.path.isdir(hooks_src):
        shutil.copytree(hooks_src, os.path.join(d, "reflect-hooks"),
                        ignore=shutil.ignore_patterns(
                            "__pycache__", ".mypy_cache", "*.pyc"))
    ruff_conf = os.path.join(gate.tool_repo(), "ruff.toml")
    if os.path.isfile(ruff_conf):
        shutil.copy(ruff_conf, d)


def _corrupt_ledger_rc():
    """`--check`'s rc under a corrupt ledger (fixture repo; this repo's ledger untouched)."""
    import shutil  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    d = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "init", "-q", d], check=True, capture_output=True)
        _copy_suite_into(d)
        open(os.path.join(d, "FACTS.json"), "w", encoding="utf-8").write("{ broken")
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("REFLECT_")}
        p = subprocess.run(
            [sys.executable, os.path.join(d, "zreflect", "facts.py"), "--check"],
            cwd=d, env=env, capture_output=True, text=True, timeout=120,
                           encoding="utf-8", errors="replace")
        return p.returncode
    except Exception:                                    # noqa: BLE001
        return None
    finally:
        shutil.rmtree(d, True)


def _unwritable_doc_rc():
    """`--render-doc`'s rc on a read-only doc (needs a real write => must be FATAL 2)."""
    import shutil  # noqa: PLC0415
    import stat  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    d = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "init", "-q", d], check=True, capture_output=True)
        subprocess.run(["git", "-C", d, "config", "user.email", "a@b"], check=True)
        subprocess.run(["git", "-C", d, "config", "user.name", "a"], check=True)
        _copy_suite_into(d)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("REFLECT_")}
        env["GATE_REPO"] = d

        def run(*args):
            return subprocess.run([sys.executable, *args], cwd=d, env=env,
                                  capture_output=True, text=True, timeout=180,
                           encoding="utf-8", errors="replace")

        run("zreflect/facts.py", "--init")
        run("zreflect/facts.py", "--accept-changes")
        run("zreflect/facts.py", "--render-doc")
        # Make the doc need a write again: change one value in the ledger.
        run("zreflect/facts.py", "--accept", "probe", "9", "echo 9", "s")
        doc = os.path.join(d, "STATE.md")
        os.chmod(doc, stat.S_IRUSR)
        try:
            return run("zreflect/facts.py", "--render-doc").returncode
        finally:
            os.chmod(doc, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:                                    # noqa: BLE001
        return None
    finally:
        shutil.rmtree(d, True)


def _corrupt_load_raises():
    """`ledger.load` raises `Unreadable` on bad JSON (not a bare `JSONDecodeError`)."""
    import tempfile  # noqa: PLC0415

    from ledger import Unreadable  # noqa: PLC0415
    fd, path = tempfile.mkstemp()
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("{ broken")
        try:
            load(path)
        except Unreadable:
            return True
        except Exception:                                # noqa: BLE001
            return False
        return False
    finally:
        os.unlink(path)


def _env_from_envfile(d, base_env):
    """Parse `Einfacht.env` into environment variables (**cross-platform, no shell**).

    ⚠️ Used to be `shell=True` + `set -a; . ./Einfacht.env; set +a;` -- that is
    **POSIX sh syntax**. Windows' shell is cmd.exe, which does not understand it; so
    the env was never loaded => gates fell back to the default doc list =>
    `doc_has_no_home` (observed: CI's Windows leg, `facts` selftest 13 PASS / 1 FAIL).
    """
    out = dict(base_env)
    path = os.path.join(d, "Einfacht.env")
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    # **One single parser**: `check_envfile.parse_exports` (with quote stripping and
    # an optional export prefix). This spot used to hand-roll `startswith("export ")`
    # + `partition("=")`, **without stripping quotes** -- same env file, this side
    # parsed `'"STATE.md"'` (quoted) while the other side parsed `'STATE.md'`.
    # Observed: a fixture's knob value silently carried quotes => the criterion tested
    # a different environment, and reported nothing.
    import check_envfile  # noqa: PLC0415
    out.update(check_envfile.parse_exports(text))
    return out


def _bootstrap_steps():
    """Steps to run after `--init` (`(argv, whether to apply env)`)."""
    return [
        ([sys.executable, "zreflect/facts.py", "--accept-changes"], True),
        ([sys.executable, "zreflect/facts.py", "--render-doc"], True),
        ([sys.executable, "zreflect/facts.py", "--render-doc",
          "PRINCIPLES.md"], True),
        ([sys.executable, "zreflect/registry.py", "--run", "commit"], True),
    ]


def _real_repo_shaped():
    """A repo of the **real-project shape** completes bootstrap: `.sh` files + `src/` +
    an existing README.

    This case was bought with the "wire into a real project" acceptance: previously
    `shell_surface_problems()` scanned the whole `GATE_REPO`, so **any repo with a
    `build.sh`** got `--render-doc` FATAL, `--check` FATAL, red pre-commit, and no
    knob could let it through -- "all Python" is this repo's discipline for itself,
    not a requirement on every consumer.

    The fixture deliberately plants these three things (all the most common shapes of
    real projects):

      - `build.sh` / `deploy.sh` -- build scripts (these once killed the whole chain)
      - `src/app.py` -- its own code
      - `examples/bad.py` -- **its own code that would be red by suite standards**
        (bare CJK + unused import). This is the second discipline: "the suite audits
        only the suite" is not a promise written in a comment but something this
        fixture verifies every round -- if any of the three gates ever widens its
        scope back to the whole repo, this goes red on the spot (observed: before the
        interface was narrowed it reported 149 + 59 findings).
      - An existing `README.md` **without a machine block** -- `--init` prints
        `already exists, left alone`, so `check_readme_sync`'s single-entry path must work.
    """
    import shutil  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    d = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "init", "-q", d], check=True,
                       capture_output=True)
        _copy_suite_into(d)
        for name in ("build.sh", "deploy.sh"):
            with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                fh.write("#!/bin/sh\necho %s\n" % name)
        os.makedirs(os.path.join(d, "src"))
        with open(os.path.join(d, "src", "app.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("def f():\n    return 1\n")
        # **The consumer's own code, red by suite standards**: bare CJK (check_i18n's
        # first criterion) + unused import (ruff's F401) + module-level derivation
        # (snapshot). If any of the three gates widens its scope back to the whole
        # repo, `registry --run commit` goes red. "The suite audits only the suite"
        # thereby becomes a criterion truly exercised every round, not a comment.
        os.makedirs(os.path.join(d, "examples"))
        # ⚠️ The fixture source's Chinese text must be **codepoint-constructed** --
        # this very file is inside check_i18n's scan surface, so writing a Chinese
        # literal directly would be judged by it as "the core speaks human" (observed:
        # right after the first version was written, `i18n_cover.bare_text` went red
        # at facts.py:1363).
        bad_body = ("import os\n\n\ndef f():\n    print(%r)\n"
                    % "".join(chr(c) for c in (0x8FD9, 0x6761, 0x4E2D, 0x6587)))
        with open(os.path.join(d, "examples", "bad.py"), "w",
                  encoding="utf-8") as fh:
            fh.write(bad_body)
        with open(os.path.join(d, "README.md"), "w", encoding="utf-8") as fh:
            fh.write("# my project\n\nNo machine block here.\n")
        base = {k: v for k, v in os.environ.items()
                if not k.startswith("REFLECT_") and k != "GATE_REPO"}
        subprocess.run([sys.executable, "zreflect/facts.py", "--init"],
                       cwd=d, env=base, capture_output=True, text=True,
                       timeout=180,
                           encoding="utf-8", errors="replace")
        for argv in ([sys.executable, "zreflect/facts.py", "--accept-changes"],
                     [sys.executable, "zreflect/facts.py", "--render-doc"],
                     [sys.executable, "zreflect/facts.py", "--render-doc",
                      "PRINCIPLES.md"]):
            p = subprocess.run(argv, cwd=d, env=_env_from_envfile(d, base),
                               capture_output=True, text=True, timeout=180,
                           encoding="utf-8", errors="replace")
            if p.returncode != 0:
                return False
        p = subprocess.run([sys.executable, "zreflect/registry.py",
                            "--run", "commit"],
                           cwd=d, env=_env_from_envfile(d, base),
                           capture_output=True, text=True, timeout=180,
                           encoding="utf-8", errors="replace")
        return p.returncode == 0
    except Exception:                                    # noqa: BLE001
        return False
    finally:
        shutil.rmtree(d, True)


def _opt_out_check_case():
    """With `REFLECT_NO_PRINCIPLES=1`, `--check` must not ask `PRINCIPLES.md` for a block.

    ⚠️ Must use a fixture repo **without `PRINCIPLES.md`**: this repo always has that
    file, so the old "unconditionally check both" implementation would also be green
    here -- the criterion would be blind (observed: the subprocess runs the new code;
    patches do not cross processes). The fixture = the same copytree +
    `--init` as `_fresh_bootstraps`, with the init-created `PRINCIPLES.md` deleted
    (the shape of a real opt-out repo), then two assertions:

      - flag set => `--check` rc=0 and PRINCIPLES untouched (old behavior FATALs here);
      - flag unset => PRINCIPLES is checked => "file missing" is reported (default
        surface unchanged; the file simply is not there).
    """
    import shutil  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    d = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "init", "-q", d], check=True, capture_output=True)
        _copy_suite_into(d)
        base = {k: v for k, v in os.environ.items()
                if not k.startswith("REFLECT_") and k != "GATE_REPO"}
        subprocess.run([sys.executable, "zreflect/facts.py", "--init"],
                       cwd=d, env=base, capture_output=True, timeout=180)
        # Complete the bootstrap's measure and render (as in `_fresh_bootstraps`):
        # init generates an empty STATE.md block; without these two steps --check
        # would report block_stale -- that is the fixture not finishing the flow, not
        # the behavior under test.
        env_run = _env_from_envfile(d, base)
        for argv in ([sys.executable, "zreflect/facts.py", "--accept-changes"],
                     [sys.executable, "zreflect/facts.py", "--render-doc"]):
            subprocess.run(argv, cwd=d, env=env_run, capture_output=True,
                           timeout=180)
        os.remove(os.path.join(d, "PRINCIPLES.md"))
        env_opt = dict(base)
        env_opt["REFLECT_NO_PRINCIPLES"] = "1"
        p = subprocess.run([sys.executable, "zreflect/facts.py", "--check"],
                           cwd=d, env=env_opt, capture_output=True, text=True,
                           timeout=180, encoding="utf-8", errors="replace")
        return p.returncode == 0 and "PRINCIPLES" not in (p.stdout + p.stderr)
    except Exception:                                    # noqa: BLE001
        return False
    finally:
        shutil.rmtree(d, True)


def _fresh_bootstraps():
    """A brand-new repo: `--init` -> measure -> two renders -> `registry --run commit`
    all green.

    **End-to-end**: spawns subprocesses. Precisely because of that it catches the
    three defects that each look reasonable alone but together break bootstrap -- the
    env making harness go red on itself, md_lines counting the GATES+RULES blocks
    too, and `--accept-changes` treated as an unknown command.

    The three stages (prepare fixture / resolve env / run step by step) are each a
    helper: merged, complexity 12, and its own `check_lint` would judge it red on the
    spot (observed).
    """
    import shutil  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    d = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "init", "-q", d], check=True,
                       capture_output=True)
        _copy_suite_into(d)
        # ⚠️ Must clear `GATE_REPO` along with the rest: `harness` sets it to **this
        # repo** when running selftests, while the fixture here is another repo --
        # leave it in and the subprocesses will come back to check this repo.
        base = {k: v for k, v in os.environ.items()
                if not k.startswith("REFLECT_") and k != "GATE_REPO"}
        subprocess.run([sys.executable, "zreflect/facts.py", "--init"],
                       cwd=d, env=base, capture_output=True, text=True,
                       timeout=180,
                           encoding="utf-8", errors="replace")
        for argv, with_env in _bootstrap_steps():
            env = _env_from_envfile(d, base) if with_env else base
            p = subprocess.run(argv, cwd=d, env=env, capture_output=True,
                               text=True, timeout=180,
                           encoding="utf-8", errors="replace")
            if p.returncode != 0:
                return False
        return True
    except Exception:                                    # noqa: BLE001
        return False
    finally:
        shutil.rmtree(d, True)


MODULE = module_meta("ledger CLI", "measure / render / --get / the two guards", selftest=True)


if __name__ == "__main__":
    sys.exit(main_selftest_or(sys.argv[1:], M("gate.title.facts_cli"),
                              CASES, main))



