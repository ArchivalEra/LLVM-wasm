#!/usr/bin/env python3
"""Gate entry point: **meant to be called by other hook systems**; it never
takes over hook slots.

## Why "expose one entry" instead of `git config core.hooksPath`

`core.hooksPath` is git's **global override switch** -- once it is set, git
**stops looking at** `.git/hooks/` entirely. Measured: after setting it, the
script inside `.git/hooks/pre-commit` never ran once, while commits kept
succeeding with no message at all. So husky / lefthook / pre-commit (Python)
/ handwritten hooks are all **silently disabled** -- exactly the "deployed
does not mean running" state this repo exists to eliminate.

So this repo only **exposes one mouth**: any hook system can call this line
from its own hook. Hook locations, ordering, other tools -- all yours; we
provide the criteria and never take the seat.

    Usage (from any hook script):
        python3 <repo>/reflect-hooks/gate.py commit "$(git rev-parse --show-toplevel)"
        python3 <repo>/reflect-hooks/gate.py push   "$(git rev-parse --show-toplevel)"

    commit  re-render the machine block (and `git add`) + run every gate with
            runs_at="commit"
    push    verify only, modify nothing: the machine block must be fresh + all
            gates + trilingual READMEs in the same batch

    Exit codes: 0 = green; 1 = criterion red (reject); 2 = environment/config
    broken.

## Why Python instead of sh

This used to be `einfacht-gate.sh` (155 lines of shell with 26 `echo`s of
Chinese). Three diseases:

  1. **It bypassed the zero-language regime**: `check_i18n` is an AST scanner
     (it only reads `.py`), so it cannot see shell => "outputs Chinese with
     no language pack installed" lived here undetected for a long time.
  2. Portability: on Windows `sh` may not exist, and `$(...)` / `[ -f ]` each
     have their own dialects.
  3. pre-push's ref protocol is **text parsing** -- far clearer in Python
     than in shell.

## The old install style still works

Old users of `core.hooksPath reflect-hooks` invoke the `pre-commit` /
`pre-push` files in this directory; they are thin shells around this entry
(still present). Upgrade without breakage.
"""
from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(TOOL_REPO, "zreflect"))

from gate import activate_or_fatal, meta  # noqa: E402
from i18n import M  # noqa: E402

ZERO_SHA = "0" * 40
PHASES = ("commit", "push")


def _sh(cmd, stdin=None, env=None):
    """Run one command, return `(rc, merged output)`."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, input=stdin,
                           env=env,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as e:
        return 127, "gate: %r" % (e,)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _usage():
    print(str(M("hookgate.usage")), file=sys.stderr)
    return 0


def _load_env_plugin(tool_dir):
    """Pluggable add-on (issue #8): knobs `export`ed inside
    `einfacht-env.sh`.

    Warning: this is the **only** place that must keep a shell -- a shell's
    `export` can only be done by a shell. We carry it into the Python process
    by "running one shell and printing its environment": the plugin itself is
    still a shell file, but **it only exports and produces no copy at all**
    (no Chinese left to leak).
    """
    plugin = os.path.join(tool_dir, "einfacht-env.sh")
    if not os.path.isfile(plugin):
        return
    # Warning: the plugin must be told explicitly **where it itself lives**:
    # in `sh -c '...' sh <plugin>`, `$0` is `sh`, so a plugin deriving its
    # directory with `dirname $0` would derive `/` -- and then the
    # Einfacht.env in the hooks directory is **silently ignored** (measured:
    # `env -0` showed not a single REFLECT_*).
    env = dict(os.environ)
    env["EINFACHT_PLUGIN_DIR"] = tool_dir
    rc, out = _sh(["sh", "-c",
                   '. "$1" >/dev/null 2>&1; env -0', "sh", plugin], env=env)
    if rc != 0:
        return
    for chunk in out.split("\0"):
        if "=" not in chunk:
            continue
        k, v = chunk.split("=", 1)
        if k.startswith("REFLECT_"):
            os.environ[k] = v


def _refs_from_stdin():
    """git's pre-push ref protocol: each line is
    `<local ref> <local sha> <remote ref> <remote sha>`."""
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    except (OSError, ValueError):
        return []
    rows = []
    for ln in raw.splitlines():
        parts = ln.split()
        if len(parts) == 4:
            rows.append(tuple(parts))
    return rows


def _new_content_refs(repo, refs):
    """Filter the ref-protocol lines down to "branches actually publishing
    new content this time"; returns `[(lref, revs)]`."""
    out = []
    for lref, lsha, _rref, rsha in refs:
        if lref.startswith("refs/tags/"):
            continue                       # tags carry no new content
        if lsha == ZERO_SHA:
            continue                       # branch deletion
        if rsha == ZERO_SHA:
            rc, revs = _sh(["git", "-C", repo, "rev-list", lsha,
                            "--not", "--remotes"])
            revs = revs.strip() if rc == 0 else ""
        else:
            rc, _o = _sh(["git", "-C", repo, "rev-list", "%s..%s" % (rsha, lsha)])
            revs = "%s..%s" % (rsha, lsha) if rc == 0 else lsha
        out.append((lref, revs.strip()))
    return out


def _push_readmes_together(repo, refs):
    """pre-push third check: this push must update the trilingual READMEs in
    the same batch. Returns (ok, lines)."""
    import tempfile  # noqa: PLC0415
    lines = []
    refs_with_content = _new_content_refs(repo, refs)
    if not refs_with_content:
        lines.append(str(M("hookgate.push_nothing_to_check")))
        return True, lines
    checked = 0
    for lref, revs in refs_with_content:
        if not revs:
            lines.append(str(M("hookgate.ref_has_nothing", ref=lref)))
            checked += 1
            continue
        rc, log = _sh(["git", "-C", repo, "log", "--name-only",
                       "--pretty=format:", revs])
        changed = [ln for ln in (log or "").splitlines() if ln.strip()]
        fd, path = tempfile.mkstemp()
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("\n".join(changed) + "\n")
            rc, out = _sh([sys.executable,
                           os.path.join(repo, "zreflect", "check_readme_sync.py"),
                           "--changed", path])
            if rc != 0:
                lines.append(str(M("hookgate.push_readmes_not_together",
                                   ref=lref)))
                lines.extend(ln for ln in (out or "").splitlines()[:5])
                return False, lines
        finally:
            os.unlink(path)
        checked += 1
    lines.append(str(M("hookgate.push_readmes_ok", count=checked)))
    return True, lines


def _prepare(phase, repo, doc):
    """(1) The phase's setup step. Returns `(whether to reject)`.

    The two phases do **opposite** things, hence one named branch each:

      - commit -- re-render the machine block and `git add` (**render only,
        do not re-measure**; re-measuring is a human's job)
      - push   -- **touches no files, rewrites no history**: a stale block is
        an outright rejection
    """
    facts = os.path.join(repo, "zreflect", "facts.py")
    if phase == "commit":
        if os.path.isfile(os.path.join(repo, doc)):
            _sh([sys.executable, facts, "--render-doc", doc])
            _sh(["git", "-C", repo, "add", doc])
        return False
    rc, out = _sh([sys.executable, facts, "--check"])
    if rc == 0:
        return False
    print(str(M("hookgate.blocks_stale", detail=(out or "").strip()[:400])),
          file=sys.stderr)
    return True


def run(phase, repo, stdin_rows=None):
    """Run one phase. Returns rc. **Pure orchestration**: every judgment
    lives inside the commands it calls."""
    if phase not in PHASES:
        print(str(M("hookgate.unknown_phase", phase=phase)), file=sys.stderr)
        return 2
    if not os.path.isdir(repo):
        print(str(M("hookgate.repo_missing", repo=repo)), file=sys.stderr)
        return 2

    _load_env_plugin(HERE)
    doc = os.environ.get("REFLECT_DOC", "").strip() or "STATE.md"

    if _prepare(phase, repo, doc):
        return 1

    # (2) All gates: the single source of the execution surface (C1)
    rc, out = _sh([sys.executable, os.path.join(repo, "zreflect", "registry.py"),
                   "--run", "commit"])
    if rc != 0:
        print(out, file=sys.stderr)
        return 1

    if phase == "push":
        ok, lines = _push_readmes_together(repo, stdin_rows or [])
        for ln in lines:
            print(ln, file=sys.stderr)
        if not ok:
            return 1
    return 0


# -- Self-verification -------------------------------------------------------

def _cases():
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    def mk_repo(with_zreflect):
        d = tempfile.mkdtemp()
        _sh(["git", "init", "-q", d])
        if with_zreflect:
            os.makedirs(os.path.join(d, "zreflect"), exist_ok=True)
        return d

    def case(args):
        return _run_cli(list(args), quiet=True)

    return [
        # (1) Normal case: no report -- no args => print usage, exit 0
        # (asking for help is not an error)
        ("hookgate.no_args_prints_usage", lambda: case([]) == 0),
        # (2) What must be reported gets reported
        ("★ hookgate.unknown_phase_is_2", lambda: case(["bogus", "/tmp"]) == 2),
        ("★ hookgate.missing_repo_is_2",
         lambda: case(["commit", "/nonexistent-xyz"]) == 2),
        # (3) Empty input must be reported: phase given, repo root missing
        ("★ hookgate.missing_root_is_2", lambda: case(["commit"]) == 2),
        # (4) No zreflect in the repo => say outright "not a repo where the
        # suite is installed" (rc=2, not a silent 0)
        ("★ hookgate.no_zreflect_is_2", lambda: _no_zreflect_case(mk_repo,
                                                                  shutil)),
        # The summary-line criterion itself has teeth
        ("★ hookgate.summary_shape_can_red", lambda: _summary_shape_ok()),
        # Ref-protocol parsing: all-zero-sha deletion lines must be skipped
        ("★ hookgate.refs_skip_deletions", lambda: _refs_case()),
    ]


def _no_zreflect_case(mk_repo, shutil):
    d = mk_repo(False)
    try:
        return _run_cli(["commit", d], quiet=True) == 2
    finally:
        shutil.rmtree(d, True)


def _summary_shape_ok():
    """Criterion lives in `machine.is_summary()` (single source of truth; no
    per-file regex copies anymore)."""
    import machine  # noqa: PLC0415
    return machine.is_summary("=== 3 PASS / 0 FAIL ===") and \
        not machine.is_summary("=== 3 PASS / 0 fail ===")


def _refs_case():
    rows = [("refs/heads/main", ZERO_SHA, "refs/heads/main", ZERO_SHA)]
    got = _new_content_refs(".", rows)
    return got == []


def _run_cli(argv, quiet=False):
    """Walk the CLI dispatch once, return rc.

    `quiet=True` (**selftest only**): print nothing -- selftest output is the
    interface a human checks; if diagnostics flood it, there is nothing left
    to check (this repo's discipline: "pure functions stay quiet").
    Warning: it used to print during the selftest, so those lines landed
    **after** the machine summary line, and the harness taking "the last
    line as the summary" picked up an error message (measured).
    """
    def _say(code, **kw):
        if not quiet:
            print(str(M(code, **kw)), file=sys.stderr)

    if not argv:
        if not quiet:
            _usage()
        return 0
    rc = _validate(argv, _say)
    if rc is not None:
        return rc
    return run(argv[0], argv[1], _refs_from_stdin())


def _validate(argv, say):
    """Command-line shape validation. Returns rc (`None` = shape is legal,
    may proceed).

    The four checks are each an exit for "not worth continuing"; jamming
    them all into the call site made complexity 9 -- and they all judge the
    **same question** (can this invocation run), so they live in one
    function.
    """
    phase = argv[0]
    if phase not in PHASES:
        say("hookgate.unknown_phase", phase=phase)
        return 2
    if len(argv) < 2:
        say("hookgate.missing_root")
        return 2
    repo = argv[1]
    if not os.path.isdir(repo):
        say("hookgate.repo_missing", repo=repo)
        return 2
    if not os.path.isdir(os.path.join(repo, "zreflect")):
        say("hookgate.not_a_suite_repo", repo=repo)
        return 2
    return None


def _main(argv):
    if "--selftest" in argv:
        rc = activate_or_fatal()
        if rc:
            return rc
        from gate import selftest  # noqa: PLC0415
        return selftest(M("gate.title.hookgate"), _cases())
    rc = activate_or_fatal()
    if rc:
        return rc
    return _run_cli(argv)


GATE = meta("Hook entry",
            "the single mouth called by other hook systems: commit re-renders + "
            "runs gates; push verifies only + trilingual READMEs in one batch",
            knobs=("REFLECT_DOC",),
            runs_at="start-of-work",
            off_reason="the hook entry is invoked by git, not attached to the pre-commit phase")

if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
