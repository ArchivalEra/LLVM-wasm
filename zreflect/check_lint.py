#!/usr/bin/env python3
"""Static machine-check gate (**pluggable**): ruff's C901/F/E9/B, criteria in `ruff.toml`.

## What it replaces

The `_summary` of `gitroll-dispositions.json` once said:

    ruff --select=C901,F,E9,B --config lint.mccabe.max-complexity=15
    => All checks passed

**Measured reality: 159 errors** (134 F841 / 13 F401 / 4 C901). The reason was not
a changed scanner: that command had **never been executed by any gate** -- it was
run by hand exactly once and the conclusion was written into the ledger. This is
precisely the shape this repo exists to eliminate: an "all clear" paired with a
command nobody re-runs.

More concrete damage (see `retractions.json` R-004 / R-005):

  - `facts.py --render-doc` (one of AGENTS.md's headline commands) **crashed**
    with `UnboundLocalError` -- `ruff F823` had flagged it long before; nobody ran
    ruff.
  - The 134 `F841`s were mechanical debris of "unpack 7 variables, use 2", all
    left over from the previous round of "complexity-splitting" refactoring.

## Why `off` is acceptable

`ruff` is an **external tool**, not a dependency of this repo. A repo without it
installed should not go red over this gate -- so when ruff is absent the gate
says so explicitly (`OFF:`), and the execution surface lists it as its own
disposition instead of passing it off as a success. But **if installed, it must
pass**: in CI, after `pip install 'ruff==0.17.3'`, this gate really runs.

## Honesty boundaries

  - It runs the rule set **selected by this repo** in `ruff.toml` (C901/F/E9/B).
    ruff's full default set has 716 rules -- mostly style items; this repo
    explicitly declines that scoring game (see `accepted_rules` in
    `gitroll-dispositions.json`).
  - It does not parse ruff's output for a second opinion: rc != 0 = red, and its
    findings list is relayed verbatim. Any "filter by rule name" would become a
    second origin that drifts.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate  # noqa: E402
from gate import fatal, finish, main_selftest_or, meta, off  # noqa: E402
from i18n import M  # noqa: E402

CONFIG = "ruff.toml"


def suite_files(repo_root=None):
    """Paths of the **suite's own** `.py` files (those for which `declares_itself()`
    is true).

    Warning: this previously ran `ruff check .` -- the **whole repo**. When wired
    into a real project, the host's `examples/` / `scripts/` got audited as if
    they were the suite: observed on a real integration, `registry --run commit`
    reported **149** ruff findings, all pointing at the host's own files. The user
    could neither fix them all nor understand why someone else's suite was nitpicking
    their code.

    The criterion for "suite code" is a **declaration** (`MODULE = ...` /
    `GATE = ...`), not a directory name -- discovery-based, the same yardstick as
    `registry.modules()` / `gates()`.
    """
    root = repo_root or gate.GATE_REPO
    out = []
    for sub in ("zreflect", "reflect-hooks"):
        base = os.path.join(root, sub)
        if not os.path.isdir(base):
            continue
        for rel, _src in gate.py_sources(base):
            p = os.path.join(base, rel)
            if gate.declares_itself(p):
                out.append(os.path.join(sub, rel).replace(os.sep, "/"))
    return sorted(out)


def ruff_argv(files=None):
    """The argv for running ruff (`sys.executable -m ruff`: cross-platform and
    identical to the pip-installed one).

    With `files` given, only those are checked; without it, **the suite's own
    files** (not the whole repo).
    """
    targets = list(files) if files is not None else suite_files()
    if not targets:
        return [sys.executable, "-m", "ruff", "check",
                "--output-format=concise", "."]
    return [sys.executable, "-m", "ruff", "check", "--output-format=concise",
            *targets]


def _has_located_finding(out):
    """Whether ruff's output contains a **located finding line**
    (`path:line:col: CODE message`).

    Criterion: at least one line carrying both `.py:` and line-number-style
    colons -- that is what "a problem was found" means. A nonzero exit without
    any located line is a tool/config incident.
    """
    return any(".py:" in ln or '.py"' in ln
               for ln in (out or "").splitlines())


def problems(out, rc):
    """Pure function: ruff output + rc -> problem list (empty = clean). For the selftest.

    `rc` nonzero with empty output => **must be reported** (zero-value guard):
    that is the shape where "the tool is broken" and "no problems" are
    indistinguishable.
    """
    lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    if rc == 0:
        return []
    real = [ln for ln in lines if ln.startswith(("zreflect/", "reflect-hooks/"))
            or ":" in ln and ".py:" in ln]
    if not real:
        return [M("lint.no_output", return_code=rc,
                  detail=(lines[-1][:120] if lines else ""))]
    return [M("lint.finding", text=ln[:160]) for ln in real]


def run(argv=None):
    """Two "explicitly not enabled" paths and one "really runs" path.

    No `ruff.toml` => `off` (**not** fatal): that is the normal shape of "this
    repo did not select this rule set" -- a foreign repo into which only
    `zreflect/` was copied should not go red over this gate. But config present
    while the tool is missing => also `off` (external tool, not a repo
    dependency); config present, tool present, ruff errors out => **fatal**
    (a config incident must not stay silent).
    """
    conf = os.path.join(gate.GATE_REPO, CONFIG)
    if not os.path.isfile(conf):
        return off(M("lint.off_config", path=CONFIG))
    if shutil.which("ruff") is None:
        rc, _out = subprocess_ruff_probe()
        if rc != 0:
            return off(M("lint.off", module="ruff"))
    try:
        p = subprocess.run(ruff_argv(), cwd=gate.GATE_REPO,
                           capture_output=True, text=True, timeout=300,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as e:
        return fatal(M("lint.tool_broken", error=e))
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0 and not _has_located_finding(out):
        # Warning: **a nonzero exit with no located line is not a red criterion**:
        # ruff itself failed to start (broken `ruff.toml` syntax / unrecognized
        # flag / wrong version) -- a config incident, FATAL rc=2. Previously this
        # always went through `problems()`, becoming `lint.no_output` + rc=1, so
        # the caller would go fix code when the actual problem was the criteria
        # file itself.
        detail = [ln for ln in out.splitlines() if ln.strip()]
        return fatal(M("lint.config_broken", path=CONFIG,
                       detail=(detail[-1][:200] if detail else "")))
    probs = problems(out, p.returncode)
    return finish(M("lint.title"), probs, M("lint.ok", config=CONFIG))


def subprocess_ruff_probe():
    """When `ruff` is not on PATH, try `python -m ruff` (the pip-into-the-
    interpreter kind)."""
    try:
        p = subprocess.run([sys.executable, "-m", "ruff", "--version"],
                           capture_output=True, text=True, timeout=60,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# -- self-verification --------------------------------------------------------

def _cases():
    return [
        # (1) compliant input: nothing reported
        ("lint.clean_is_clean", lambda: problems("", 0) == []),
        # (2) what must be reported is reported
        ("★ lint.finding_is_reported",
         lambda: [p.code for p in problems(
             "zreflect/x.py:3:1: F841 Local variable `y` is unused", 1)]
         == ["lint.finding"]),
        # (3) empty input must be reported -- rc != 0 with **no located line at
        # all** (tool broken / bad flag)
        ("★ lint.silent_failure_is_loud",
         lambda: [p.code for p in problems("error: unrecognized argument", 2)]
         == ["lint.no_output"]),
        # Benign output is not falsely reported: rc=0 means clean, warnings
        # included (e.g. deprecation notices)
        ("lint.warning_with_rc0_is_clean",
         lambda: problems("warning: config deprecated", 0) == []),
        # **A config incident and a red criterion must be distinguishable**
        # (rc=2 vs rc=1): a located line => a problem was found; none => ruff
        # itself failed to start (broken `ruff.toml` syntax).
        ("\u2605 lint.located_finding_detected",
         lambda: _has_located_finding(
             "zreflect/x.py:3:1: F841 Local variable `y` is unused")),
        ("\u2605 lint.config_error_is_not_a_finding",
         lambda: not _has_located_finding(
             "key with no value, expected `=`")),
    ]


def _selftest():
    return main_selftest_or(sys.argv[1:], M("gate.title.lint"), _cases,
                            lambda a: 0)


def _activate_and_run():
    rc = gate.activate_or_fatal()
    return rc or run(sys.argv[1:])


GATE = meta("Static machine check",
            "ruff's C901/F/E9/B, criteria in ruff.toml -- the 'all clear' must be"
            " re-established by every commit, not handwritten into the ledger"
            " from a single manual run (R-004)",
            off_reason="ruff not installed on this machine (external tool, not a"
                       " repo dependency) => explicitly not enabled; CI pip-installs"
                       " it, and there the gate really runs")


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else _activate_and_run())
