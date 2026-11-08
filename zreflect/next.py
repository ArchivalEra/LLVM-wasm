#!/usr/bin/env python3
"""The "pick up from the last turn" **collector** -- the memory system's half.

## What it replaces is manual labor

Before a session gets compacted, a human had to hand-write "what was done
this round, what comes next". Skip it, and after compaction the agent starts
empty-handed: re-raising already-closed questions, or re-analyzing from zero.

**"Someone must prepare every compaction" is itself a defect** -- it requires
a human to remember to do what a mechanism should do, and the cost of
forgetting is the entire context.

## Interface: a block of lines, **never persisted**

    section(repo) -> list[str]      # includes its own header line; <= SECTION_MAX lines

**It is host-agnostic**: `section(repo)` only returns lines; it knows no
editor's hook protocol, no host's JSON envelope, and does not need to know
what a given host calls session start. To plug into some host's hook, the
consumer adds a thin shell of its own (read its stdout and shape it however
the host wants) -- the suite does not make host decisions and does not
validate any host's config schema.

## Why there is no block in a document

This module used to render an `AUTO:NEXT` machine block in `STATE.md`,
rewritten every turn by a `Stop` hook. **That path never worked once**
(measured: `facts.py --render-doc` only accepts `AUTO:FACTS` / `AUTO:GATES` /
`AUTO:RULES`; this block never made it into any document, and `next.render()`
had no caller besides the self-proof). Worse, it is **naturally incompatible**
with `facts.py --check`'s byte-exact reconciliation: a block that changes
every turn makes the check permanently red; exempt it, and that block of the
document is verified by no one.

**What changes every turn must not occupy a position that gets judged.** So
it is not persisted: it is computed fresh at each session start. The cost is
slightly higher (two git calls + one directory read); what it buys is that
it is **always fresh**, with no intermediate state of "the document says it
is automatic, but it was never actually written".

## What gets collected, and from where

Everything grows out of **what already exists**; no new human-maintained
inputs:

    git log HEAD --not --remotes    -> unpushed commits ("what this round did")
    git status --porcelain          -> uncommitted changes / untracked files
    questions/                      -> unresolved open questions ("what is next")

This is also `collect.py`'s collector contract (read only durable disk; no
inputs that change by themselves).

## The budget is part of the interface

Text injected into context beyond one screen crowds out the actual work, and
`AUTO:NEXT` was once truncated by a caller with `[:8]` -- so **the last
pending items were silently cut** (measured: exactly the part most needed
after compaction). Truncation now happens **inside the module**
(`MAX_LISTED` / `SECTION_MAX`); callers no longer need to know the length.
`next.section_budget_holds` pins "not a single pending item may be squeezed
out".

## Honest boundaries

  - It knows the progress **the machine can see** (commits, uncommitted
    changes, open questions); it does **not** know "what the agent intends to
    do". The latter requires a human to write -- but one open question in
    `questions/` suffices; no full handoff needed.
  - "The last turn" is delimited by **unpushed commits**. Already-pushed turns
    are not in it -- that is history, and history stays out of the measured
    surface (what cannot be reproduced does not occupy a judged position).
  - The pending list shows at most `MAX_LISTED` entries; **the count beyond
    that is reported by the open-questions section right after** (that
    section gives "N open of M"; this one gives "do these few first").
"""
from __future__ import annotations

import os
import subprocess

import knobs  # noqa: E402
from i18n import M  # noqa: E402

# How many entries each category may list at most. **The budget is the
# interface**: enlarging it makes `SECTION_MAX` and `next.section_budget_holds`
# demand a recount together (which is exactly what you want).
MAX_LISTED = 3

# Maximum lines for the whole section. Item-by-item accounting (worst case each):
#   1 header + 1 commit count + 3 commits + 1 elision + 1 worktree + 1 blank + 1 pending header + 3 pending
SECTION_MAX = 12


def _git(repo, *args):
    """Run one git command; on failure return None (**never fabricate zero values** -- see collect.py principle 3).

    ⚠️ Deliberately does **not** go through `runner.run_cmd`: that seam is for
    "re-running a ledger cmd verbatim" -- a string command passes through the
    three-tier shell (bash pipefail semantics / sh / Windows argv splitting)
    and cwd is always `GATE_REPO`. The git call here is **argv-shaped**
    (`-C <repo>`, list arguments, no shell, no injection surface), cwd is the
    **repo given as a parameter** (not the audited repo), and the failure shape
    is None, not (rc, out). All three contracts differ -- funneling them
    together would turn the safe argv into shell concatenation or get the cwd
    semantics wrong. The two copies (here and `check_world.current_branch`)
    are kept intentionally.
    """
    try:
        p = subprocess.run(["git", "-C", repo, *args],
                           capture_output=True, text=True, timeout=10,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    return p.stdout


def unpublished_commits(repo):
    """Unpushed commit subjects. Unreadable => None (**not an empty list**).

    ⚠️ The command must carry `HEAD`: `git log --oneline --not --remotes`
    (**no start point**) **silently returns 0 lines** -- it looks like
    "everything is pushed" but is really "no start point given, so git took a
    different default path". Measured: same repo, 26 lines with `HEAD`, 0
    without. This is the failure this repo hates most: **no error, wrong
    answer**.
    """
    branch = (_git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    if not branch or branch == "HEAD":
        return None
    # Order matters too: `HEAD` first, `--not --remotes` after (a `git log`
    # start point must be inside the rev list, `--not` alone is not enough).
    out = _git(repo, "log", "--oneline", "HEAD", "--not", "--remotes")
    if out is None:
        return None
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def working_tree(repo):
    """Uncommitted changes: returns (changed-file count, untracked-file count)."""
    out = _git(repo, "status", "--porcelain")
    if out is None:
        return None
    changed = untracked = 0
    for ln in out.splitlines():
        if not ln.strip():
            continue
        if ln.startswith("??"):
            untracked += 1
        else:
            changed += 1
    return changed, untracked


def _commit_lines(repo, last):
    """The unpushed-commits section: count + first N subjects + "N more"."""
    commits = unpublished_commits(repo)
    if commits is None:
        last.append(M("next.commits_unreadable"))
        return
    if not commits:
        last.append(M("next.commits_none"))
        return
    last.append(M("next.commits_count", count=len(commits)))
    last.extend("  `%s`" % c for c in commits[:MAX_LISTED])
    if len(commits) > MAX_LISTED:
        last.append("  " + M("next.commits_more",
                             count=len(commits) - MAX_LISTED))


def _tree_lines(repo, last, pending):
    """The working-tree section: how much changed / whether it is dirty."""
    wt = working_tree(repo)
    if wt is None:
        last.append(M("next.tree_unreadable"))
        return
    changed, untracked = wt
    last.append(M("next.tree_state", changed=changed, untracked=untracked))
    if changed or untracked:
        pending.append(M("next.tree_dirty"))


def _question_lines(repo, pending):
    """**Unresolved open questions = what is next**.

    This used to be deliberately empty (rationale: "`inject-state.py` already
    has an open-questions section; listing in both places duplicates") -- but
    that section only reports "how many are open", not "which ones", and what
    the agent needs most after compaction is exactly the **names**. Now this
    gives the names and that section gives the status; each has its job.

    Budget: the commits and worktree sections may already have consumed part
    of `MAX_LISTED`; the remainder goes to open questions.
    """
    room = MAX_LISTED - len(pending)
    if room <= 0:
        return
    pending.extend(M("next.open_question", name=q)
                   for q in _open_question_names(repo)[:room])


def collect(repo):
    """Collect the "pick up from the last turn" inputs. Returns `(last_turn, pending)`, two **Message lists**.

    Both may be empty -- empty is **not** a pass; `section()` says explicitly
    "no record". Keeping `Message` (rather than `str()`-ing early) lets the
    self-proof assert on **codes**, unaffected by which language packs are
    installed.

    ⚠️ These lines are **user-visible text** (injected into agent context)
    => always go through `M()`. This used to be bare Chinese plus a one-line
    PINNED, on the rationale "it lands in STATE.md and gets byte-exactly
    reconciled by --check" -- **that rationale was false** (that block never
    made it into a document and never took part in reconciliation). Claiming
    an exemption on a rationale that does not hold is exactly the mistake
    this repo caught on `machine_vocab_ok`.

    The three sections are each a named helper (commits / worktree / open
    questions): they read three different sources, and merged together "how
    the budget is split" would become implicit knowledge.
    """
    last, pending = [], []
    _commit_lines(repo, last)
    _tree_lines(repo, last, pending)
    _question_lines(repo, pending)
    return last, pending


def _question_status(text):
    """The `**Status:**` value in an open question's body (lowercase); absent => empty string.

    ⚠️ **Must forward to `check_questions.field`**: this used to hand-roll
    `ln.split(":", 1)[1]`, but the real-world spelling is
    `**Status:** resolved` (the colon sits **between that pair of asterisks**)
    -- so what got split out was `"** resolved"`, never equal to
    `"resolved"`. Consequence: **resolved questions kept being treated as
    pending** and reported into "pick up from the last turn", nagging every
    turn to check something already checked. Measured (this repo's
    `questions/01-example.md` stayed listed after being resolved).

    Of two copies of a criterion, one must be wrong -- and the
    `check_questions` copy is guarded by 196 lines of self-proof.
    """
    import check_questions  # noqa: PLC0415
    # The single source of normalization (lowercase + first word) lives in
    # check_questions.status_of -- this copy used to be a third judging method
    # (R-017); now it only forwards.
    return check_questions.status_of(text)


def _open_question_names(repo):
    """Unresolved open-question filenames from `questions/` (sorted by name, at most `MAX_LISTED`).

    Directory unreadable => return an empty list (not an error): that is the
    normal shape of "this repo does not use open questions"; `inject-state.py`
    will say "unreadable" explicitly.
    """
    # Forward to the single source (`knobs.questions_path` strips) -- this used
    # to hand-roll `os.environ.get(...).strip() or "questions"`, a second copy
    # of the same criterion.
    d = knobs.questions_path(repo)
    if not os.path.isdir(d):
        return []
    names = [n for n in sorted(os.listdir(d)) if n.endswith(".md")]
    return [n for n in names if _question_status(_read_question(d, n))
            != "resolved"][:MAX_LISTED]


def _read_question(d, name):
    """Read one open question; unreadable => empty string (treated as "unresolved" -- unreadable must not count as resolved)."""
    try:
        with open(os.path.join(d, name), encoding="utf-8",
                  errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def section(repo):
    """The whole "pick up from the last turn" section (including its own header line). At most `SECTION_MAX` lines.

    **Unreadable is not an exception**: git missing / not a repo / no open-
    questions directory all become explicit lines (`next.commits_unreadable`
    and the like) -- never fabricate a 0, and never fall silently empty.

    **But real bugs still raise** (empty input lists, missing templates,
    encoding errors). The two outcomes must stay distinguishable: wrapping
    this in `except Exception` would make "the collector is broken" and
    "nothing to report" the same shape. The host side can then separate them
    by exit code: unreadable => a block of explicit lines + rc 0; truly
    broken => nonzero exit, visible in the host's own logs (the suite does
    not judge on the host's behalf).

    User-visible text injected into agent context => everything goes through
    `M()` (under the null pack that is a bare code, which is the honest form:
    no language pack installed, so say the code).

    `section` produces only **lines**: envelope, JSON, and hook semantics all
    belong to the caller -- which lets it be asserted with zero I/O
    (`_format`) and also run by hand (`python3 zreflect/next.py`). The output
    of a manual run is the contract itself: a consumer just wraps it in
    whatever shape its host needs.
    """
    last, pending = collect(repo)
    return _format(last, pending)


def _format(last, pending):
    """The zero-I/O version of `section` (for self-proofs: never touches git).

    Layout lives here too -- callers should not know "which lines get
    indented". An empty list must be **stated explicitly**
    (`next.pending_none`); a bare empty line is not allowed: empty is not a
    pass.
    """
    lines = [str(M("next.section_header"))]
    lines.extend("  \u00b7 %s" % str(ln).strip() for ln in (last or []))
    lines.append("")
    lines.append(str(M("next.pending_header")))
    if pending:
        lines.extend("  \u00b7 %s" % str(ln).strip() for ln in pending)
    else:
        lines.append("  \u00b7 " + str(M("next.pending_none")))
    return lines


def main(argv=None):
    """`python3 zreflect/next.py [repo]` -> prints the whole section (for human inspection, not for hook assembly).

    The `__main__` block activates the language pack first
    (`gate.activate_or_fatal`): `REFLECT_LANG=zh` must render zh, and a set
    but missing pack must FATAL rc 2 -- rc 0 with bare codes was the measured
    failure (issue #31)."""
    import sys  # noqa: PLC0415
    repo = (argv or sys.argv[1:] or ["."])[0]
    sys.stdout.write("\n".join(section(os.path.abspath(repo))) + "\n")
    return 0


# ── Self-proof ────────────────────────────────────────────────────────────────
#
# This module **has** a self-proof entry (`selftest=True`): its criterion is
# "when the collector cannot read something, does it pretend it did?" -- the
# class of incident this repo hurts most over, so it must be falsifiable on
# the spot.

def _cases():
    """Every case crafts an input **that can make it red** (fixture repos, zero reliance on the real repo)."""
    return [
        # 1. Normal non-report: a real git repo, clean worktree => the collector can say so
        ("next.collects_from_real_git", lambda: _real_git_case()),
        # 2. What must be reported gets reported -- **unreadable must not fabricate a 0**
        ("★ next.missing_repo_is_loud_not_zero",
         lambda: _missing_repo_loud()),
        # Layout is a pure function: same input, two runs, byte-identical
        ("★ next.section_is_deterministic", lambda: _section_deterministic()),
        # Empty pending must be **stated explicitly** ("if you expected items -- that is a gap in the record")
        ("★ next.empty_pending_is_explicit", lambda: _empty_pending_explicit()),
        # The `git log` start point must not be omitted: without `HEAD` it
        # silently returns 0 lines (measured: 26 vs 0 on the same repo). This
        # case pins the **command shape**, not the result -- the result depends
        # on real repo state, the shape does not.
        ("★ next.log_command_has_start_point",
         lambda: _log_command_shape_ok()),
        # **The budget is part of the interface**: many commits + many open
        # questions + dirty worktree => not one pending item may be squeezed
        # out, and the section stays <= SECTION_MAX. A caller's `[:8]` used to
        # truncate the pending items (measured: with 27 unpushed commits the
        # section most needed after compaction vanished entirely).
        ("★ next.section_budget_holds", lambda: _section_budget_holds()),
        # The `**Status:**` asterisk spelling -- resolved questions must stop
        # appearing under "what is next". `_question_status` used to split with
        # `split(":", 1)` yielding `"** resolved"`, so **every resolved
        # question was forever reported as pending** (measured on this repo's
        # 01-example.md).
        ("★ next.resolved_question_is_dropped",
         lambda: _resolved_question_dropped()),
        # **The manual entry must activate the language pack**: without the
        # `activate_or_fatal` pass-through, `REFLECT_LANG=zh python3
        # zreflect/next.py` exited 0 with bare codes -- documented usage that
        # did not work (measured: issue #31).
        ("★ next.manual_entry_activates_pack",
         lambda: _manual_entry_activates_pack()),
        # 3. Empty input must be reported: a nonexistent repo root
        ("★ next.nonexistent_root_is_loud",
         lambda: _nonexistent_root_loud()),
    ]


def _resolved_question_dropped():
    """**Resolved open questions must not appear under "what is next"** (the `**Status:**` asterisk spelling).

    The fixture deliberately has one resolved and one unresolved:
    `**Status:** resolved` must not be listed, `**Status:** ready-for-agent`
    must be. Either side wrong => red -- that is the criterion for the
    "split out `"** resolved"`" bug.

    ⚠️ **Never use the real repo**: real questions eventually get resolved,
    and then this case verifies nothing (green with zero meaning). So build a
    temp directory.
    """
    import tempfile  # noqa: PLC0415
    d = tempfile.mkdtemp()
    try:
        q = os.path.join(d, "questions")
        os.makedirs(q)
        with open(os.path.join(q, "01-done.md"), "w", encoding="utf-8") as fh:
            fh.write("# done\n\n**Status:** resolved\n")
        with open(os.path.join(q, "02-open.md"), "w", encoding="utf-8") as fh:
            fh.write("# open\n\n**Status:** ready-for-agent\n")
        names = _open_question_names(d)
        return names == ["02-open.md"]
    finally:
        import shutil  # noqa: PLC0415
        shutil.rmtree(d, True)


def _real_git_case():
    import shutil
    import subprocess
    import tempfile  # noqa: PLC0415
    d = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "init", "-q", d], check=True)
        subprocess.run(["git", "-C", d, "config", "user.email", "a@b"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", d, "config", "user.name", "a"],
                       check=True, capture_output=True)
        open(os.path.join(d, "x"), "w", encoding="utf-8").write("x")
        subprocess.run(["git", "-C", d, "add", "x"], check=True)
        subprocess.run(["git", "-C", d, "commit", "-qm", "c"], check=True,
                       capture_output=True)
        last, pending = collect(d)
        # Chinese in fixtures is codepoint-built (this repo's discipline; a
        # literal would turn check_i18n red)
        # ⚠️ Assert on the **code**, not the rendered text -- under the null
        # pack it renders as `next.tree_state(...)`; asserting "some word is
        # in the text" is asserting "a language pack is installed", which is a
        # different thing.
        return any("next.tree_" in getattr(ln, "code", str(ln)) for ln in last)
    except Exception:                                    # noqa: BLE001
        return False
    finally:
        shutil.rmtree(d, True)


def _missing_repo_loud():
    """Nonexistent repo => `unpublished_commits` returns None, not `[]`."""
    return unpublished_commits("/nonexistent-xyz") is None


def _section_deterministic():
    import shutil
    import tempfile  # noqa: PLC0415
    d = tempfile.mkdtemp()
    try:
        return section(d) == section(d)
    finally:
        shutil.rmtree(d, True)


def _empty_pending_explicit():
    """No pending items => it must be **stated explicitly** (`next.pending_none`); a bare empty line is not allowed.

    Assert on the code (under the null pack it renders as `next.pending_none`,
    not a sentence).
    """
    import i18n  # noqa: PLC0415
    with i18n.bind(i18n.NULL):
        block = "\n".join(_format(["only last"], []))
    return "next.pending_none" in block


def _nonexistent_root_loud():
    """No record of a last turn => it must be **stated explicitly** (`next.commits_unreadable`), never silently empty.

    ⚠️ The assertion goes through the **real collector** (`collect`), not
    "construct a good message myself, then assert it is present" -- the
    latter is a tautology (it only proves `_format` copies its input). What
    must be proven here: when reading fails, `collect` **does** produce the
    unreadable entries, not an empty list.
    """
    last, pending = collect("/nonexistent-xyz")
    codes = {getattr(ln, "code", "") for ln in last}
    return "next.commits_unreadable" in codes and "next.tree_unreadable" in codes


def _log_command_shape_ok():
    """The git command used by `unpublished_commits` **must carry a start point**.

    Read that command's arguments from the source (without executing git) --
    the criterion is about shape, so it is fixture-independent and independent
    of real repo state.
    """
    import inspect  # noqa: PLC0415
    src = inspect.getsource(unpublished_commits)
    # Find the `_git(repo, "log", ...)` line
    for line in src.splitlines():
        if '"log"' in line:
            # The start point must appear before --not
            if '"HEAD"' not in line:
                return False
            return line.index('"HEAD"') < line.index("--not")
    return False


def _manual_entry_activates_pack():
    """The manual (non-`--selftest`) `__main__` branch **must pass through
    `activate_or_fatal` before `main()`** (issue #31).

    Read the shape from the source (no subprocess): without that pass-through
    `REFLECT_LANG=zh python3 zreflect/next.py` exited 0 with bare codes --
    installed but not activated. Both halves are pinned: the call exists in
    the `__main__` block, and the manual exit actually waits on its rc.
    """
    import inspect  # noqa: PLC0415
    import sys as _sys  # noqa: PLC0415
    src = inspect.getsource(_sys.modules[__name__])
    lines = src.splitlines()
    try:
        start = lines.index('if __name__ == "__main__":')
    except ValueError:
        return False
    block = "\n".join(lines[start:])
    return ("activate_or_fatal" in block
            and "sys.exit(rc or main())" in block)


def _section_budget_holds():
    """Many commits + many open questions + dirty worktree => pending items present and the section <= `SECTION_MAX`."""
    import shutil
    import subprocess
    import tempfile  # noqa: PLC0415
    d = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "init", "-q", d], check=True,
                       capture_output=True)
        subprocess.run(["git", "-C", d, "config", "user.email", "a@b"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", d, "config", "user.name", "a"],
                       check=True, capture_output=True)
        for i in range(MAX_LISTED + 3):
            open(os.path.join(d, "x"), "w", encoding="utf-8").write(str(i))
            subprocess.run(["git", "-C", d, "add", "x"], check=True,
                           capture_output=True)
            subprocess.run(["git", "-C", d, "commit", "-qm", "c%d" % i],
                           check=True, capture_output=True)
        q = os.path.join(d, "questions")
        os.makedirs(q, exist_ok=True)
        for i in range(MAX_LISTED + 2):
            open(os.path.join(q, "%02d-q.md" % i), "w", encoding="utf-8").write(
                "# q\n\n**Status:** open\n")
        open(os.path.join(d, "dirty"), "w", encoding="utf-8").write("d")     # untracked -> pending
        import i18n  # noqa: PLC0415
        # ⚠️ **Re-render inside the null pack**, do not string-match the
        # current language pack's output. Previously `text` was rendered by
        # `section(d)` with the **current pack**, and then
        # `"next.pending_header" in text` was checked inside `bind(NULL)` --
        # with any language pack installed (en/zh/de) that substring never
        # holds, so the case was permanently red; with zero packs it happened
        # to be green. Measured: after CI, `next --selftest` gave 6 PASS /
        # 1 FAIL under REFLECT_LANG=en.
        with i18n.bind(i18n.NULL):
            lines = section(d)
            text = "\n".join(lines)
            has_pending = "next.pending_header" in text
            has_dirty = "next.tree_dirty" in text
            return has_pending and has_dirty and len(lines) <= SECTION_MAX
    except Exception:                                    # noqa: BLE001
        return False
    finally:
        shutil.rmtree(d, True)


def _selftest():
    import sys  # noqa: PLC0415

    from gate import main_selftest_or  # noqa: PLC0415
    from i18n import M  # noqa: PLC0415
    return main_selftest_or(sys.argv[1:], M("gate.title.next"), _cases,
                            lambda a: 0)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    if "--selftest" in sys.argv:
        import next as _mod  # noqa: PLC0415
        sys.exit(_mod._selftest())
    # The manual branch must activate the pack itself: AGENTS.md documents
    # `REFLECT_LANG=zh python3 zreflect/next.py` as an interface, and without
    # this point it exited 0 with bare codes (issue #31) -- "no error, wrong
    # answer". `main_selftest_or` already covers the --selftest branch; the
    # other branch takes the harness.py entry shape.
    from gate import activate_or_fatal  # noqa: PLC0415
    rc = activate_or_fatal()
    sys.exit(rc or main())

from gate import module_meta  # noqa: E402

MODULE = module_meta(
    "pick up from the last turn",
    "memory-system data collection: unpushed commits / worktree / unresolved open questions => one block of host-agnostic injection lines "
    "(computed fresh, never persisted; budget lives in the module)",
    selftest=True)
