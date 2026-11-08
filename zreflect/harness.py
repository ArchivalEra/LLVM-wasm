#!/usr/bin/env python3
"""Gate selftest harness: **discovers** every gate and first proves it can go red.

## Why Python and not shell

This used to be `gates-selftest.sh` (287 lines of shell). What it did was
**pure orchestration**: walk the roster, run subprocesses, judge rc, judge
the machine summary line. Python does all three more naturally, and —

**the shell version bypassed this repo's zero-language regime wholesale**:
the 38 Chinese strings it `echo`ed were hardcoded literals, and `check_i18n`
is an AST scanner that only sees `.py`, so it never saw them. Thus
"outputs Chinese with no language pack installed" lived in that file
indefinitely, unintercepted (caught in review: it printed Chinese even with
`REFLECT_LANG` unset).

After the move to Python, all of its text goes through `M()`, under the
same regime as every other gate. **This also eliminated almost all of the
shell vocabulary copies** — only `einfacht-env.sh` remains (it must be
shell), and its summary-line shape is checked by actually running it in
`run_plugins()`.

## Why "discovery" and not a "roster"

A handwritten roster always drifts. Add a new checker and forget to
register it, and that checker becomes "a checker nobody watches" — while
the roster itself stays green and tells you everything is fine. So here it
is the other way around: **registration is discovered**, not remembered
(rosters are always derived from `registry`'s declaration lines).

## Four sections of duty (one-to-one with the original shell version)

    gates        discover and run every gate → must be able to red + must emit a machine summary line
    plugins      pluggable plugins (those in reflect-hooks/*.sh carrying the selftest marker + named specials)
    modules      platform modules' selftests (set difference: gates' selftests already ran in the gates section)
    configurable cross-repo configurability (renamed fixture all green + gates named under default names must red)

## Honest boundary

  · The plugins section runs **the user's** `.sh` — their output is not
    subject to the zero-language regime (user-made scripts are their own
    business); only their rc and machine summary line are judged here.
  · The `configurable` section builds a temporary fixture repo and runs real
    gates; it verifies "names aren't hardcoded", not "gate logic is right"
    (that's each gate's own selftest business).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from i18n import M  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Machine summary line: the criterion lives in `machine.is_summary()` (single
# source of truth). A byte-identical regex used to live here too — three
# copies would drift (there is another one in reflect-hooks/gate.py).

# Selftest advertisement marker: present = this file claims it can be proven
# via `--selftest`.
ADVERT = re.compile(r"(main_selftest_or|--selftest)")


def _run(argv, cwd=None, env=None):
    """Run one command, return `(rc, merged output)`. rc is the **real return
    code**, not piped."""
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                           env=env, timeout=600,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as e:
        return 127, "harness: %r" % (e,)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _tail(text, n=3):
    """Lines to relay on failure: **prefer** `fail |` / `FATAL:` lines; fall
    back to the last n lines only if none are found.

    ⚠️ This used to always take the last 3 lines — but a selftest's layout is
    "fail lines first, summary line last", so what got relayed was always the
    **summary** like "=== 28 PASS / 1 FAIL ===", with no way to see which case
    went red. Observed: CI's Windows leg reported only `28 PASS / 1 FAIL`,
    with no way to know which case — the whole section had to be re-run.
    """
    all_lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    notable = [ln for ln in all_lines
               if ln.lstrip().startswith(("fail |", "FATAL:"))]
    if notable:
        return notable[:n]
    return all_lines[-n:]


def _has_summary(text):
    import machine  # noqa: PLC0415
    return any(machine.is_summary(ln) for ln in (text or "").splitlines())


def _derive_listing(repo):
    """Derive the gate listing from `registry --all-runnable` (discovered, not transcribed)."""
    _rc, out = _run([sys.executable,
                     os.path.join(repo, "zreflect", "registry.py"),
                     "--all-runnable"], cwd=repo)
    return [ln.strip() for ln in (out or "").splitlines() if ln.strip()]


def _check_one_gate(repo, rel):
    """Run one gate's selftest. Returns `(passed?, list of output lines)`."""
    g = os.path.join(repo, rel)
    if not os.path.isfile(g):
        return False, [str(M("harness.missing_file", file=rel))]
    try:
        text = open(g, encoding="utf-8", errors="replace").read()
    except OSError:
        text = ""
    if not ADVERT.search(text):
        return False, [str(M("harness.no_selftest_entry", file=rel))]
    env = dict(os.environ)
    env["GATE_REPO"] = repo
    rc, out = _run([sys.executable, g, "--selftest"], cwd=repo, env=env)
    if rc != 0:
        return False, ([str(M("harness.selftest_failed", file=rel))]
                       + ["      " + ln for ln in _tail(out)])
    if not _has_summary(out):
        return False, [str(M("harness.no_machine_summary", file=rel))]
    last = _tail(out, 1)
    return True, [str(M("harness.gate_ok", file=rel,
                        summary=last[0] if last else ""))]


def run_gates(repo, listing=None):
    """Run a group of gates' selftests. Returns `(ok, n, bad, lines)`.

    `listing` is injectable (selftest uses a fake listing, no dependence on
    the real repo); None ⇒ derived from `registry`.
    """
    listing = _derive_listing(repo) if listing is None else listing
    n = bad = 0
    lines = []
    for rel in listing:
        passed, out = _check_one_gate(repo, rel)
        lines += out
        n += 1
        if not passed:
            bad += 1
    if n == 0:
        # Zero-value guard: not a single gate discovered ⇒ fail (empty input is not a pass).
        lines.append(str(M("harness.no_gates_found")))
        return False, n, bad + 1, lines
    if bad:
        lines.append(str(M("harness.some_failed", count=n, bad=bad)))
        return False, n, bad, lines
    lines.append(str(M("harness.all_can_red", count=n)))
    return True, n, bad, lines


def run_plugins(repo):
    """Pluggable plugins + named specials (roster derived from registry). Returns `(ok, lines)`."""
    _rc, out = _run([sys.executable, os.path.join(repo, "zreflect", "registry.py"),
                     "--plugins"], cwd=repo)
    names = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    lines = []
    bad = 0
    for p in names:
        ok, out_lines = _one_plugin(repo, p)
        lines += out_lines
        bad += 0 if ok else 1
    if not names:
        lines.append(str(M("harness.no_plugins")))
        return False, lines
    return bad == 0, lines


def _one_plugin(repo, p):
    """Run one plugin's selftest, return `(passed?, output lines)`. Each of the four failure modes is its own tier."""
    f = os.path.join(repo, p)
    if not os.path.isfile(f):
        return False, [str(M("harness.missing_file", file=p))]
    cmd = ["sh", f, "--selftest"] if p.endswith(".sh") else \
          [sys.executable, f, "--selftest"]
    rc, out = _run(cmd, cwd=repo)
    if rc != 0:
        return False, ([str(M("harness.selftest_failed", file=p))]
                       + ["      " + ln for ln in _tail(out)])
    if not _has_summary(out):
        return False, [str(M("harness.no_machine_summary", file=p))]
    last = _tail(out, 1)
    return True, [str(M("harness.gate_ok", file=p,
                        summary=last[0] if last else ""))]


def run_modules(repo):
    """Platform modules' selftests (set difference: gates' selftests already ran in `run_gates`)."""
    _rc, out = _run([sys.executable, os.path.join(repo, "zreflect", "registry.py"),
                     "--selftest-modules"], cwd=repo)
    mods = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    _rc, gout = _run([sys.executable, os.path.join(repo, "zreflect", "registry.py"),
                      "--all-runnable"], cwd=repo)
    gates = {ln.strip() for ln in (gout or "").splitlines() if ln.strip()}
    lines = []
    n = bad = 0
    for m in mods:
        if m in gates:
            continue                      # a gate's selftest belongs to the gates section
        n += 1
        f = os.path.join(repo, m)
        rc, out = _run([sys.executable, f, "--selftest"], cwd=repo)
        if rc != 0:
            lines.append(str(M("harness.selftest_failed", file=m)))
            for ln in _tail(out):
                lines.append("      " + ln)
            bad += 1
            continue
        if not _has_summary(out):
            lines.append(str(M("harness.no_machine_summary", file=m)))
            bad += 1
            continue
        last = _tail(out, 1)
        lines.append(str(M("harness.gate_ok", file=m,
                           summary=last[0] if last else "")))
    if n == 0:
        lines.append(str(M("harness.no_modules_found")))
        return False, lines
    return bad == 0, lines


def run_configurable(repo):
    """Cross-repo configurability: the fixture repo with every name swapped still all green; gates named under default names must red."""
    import registry  # noqa: PLC0415
    tmp = tempfile.mkdtemp()
    try:
        return _configurable_impl(repo, tmp, registry)
    finally:
        shutil.rmtree(tmp, True)


def _configurable_fixture(repo, tmp, registry):
    """Build a **qualified external repo**: all three doc sections present, carriers present under renamed names.

    Returns `(env, gates)` — `env` is the environment with renamed knobs,
    `gates` is the list to run.
    """
    fr = getattr(registry, "FIXTURE_RENAMES", {})
    fx_facts = fr.get("FACTS.json", "LEDGER.json")
    fx_doc = fr.get("STATE.md", "NOTES.md")

    open(os.path.join(tmp, "a.py"), "w", encoding="utf-8").write("x = 1\n")
    # Machine block markers must be **placed by hand once first** (block not
    # found ≠ block is correct).
    open(os.path.join(tmp, fx_doc), "w", encoding="utf-8").write(
        "# T\n\nrefs [[py_files]] [[md_files]].\n\n"
        "<!-- AUTO:FACTS -->\n<!-- /AUTO:FACTS -->\n"
        "<!-- AUTO:GATES -->\n<!-- /AUTO:GATES -->\n")
    open(os.path.join(tmp, "AGENTS.md"), "w", encoding="utf-8").write(
        "# AGENTS\n\nsee `zreflect/doc.py` (`doc.RULES`); state: `%s`.\n\n"
        "```bash\npython3 zreflect/registry.py --run commit\n```\n" % fx_doc)
    open(os.path.join(tmp, "RETRACT.json"), "w", encoding="utf-8").write('{"schema":1,"retractions":[]}\n')
    os.makedirs(os.path.join(tmp, "cases"), exist_ok=True)
    open(os.path.join(tmp, "cases", "02-y.md"), "w", encoding="utf-8").write(
        "# e2\n\n**Status:** ready-for-agent\n\n**Settling:** `python3 a.py` —— rc=0 A; rc=7 B\n")
    for f in ("R1", "R2", "R3"):
        open(os.path.join(tmp, f + ".md"), "w", encoding="utf-8").write(
            "# %s\n\n[R1](R1.md) [R2](R2.md) [R3](R3.md)\n" % f)

    env = dict(os.environ)
    env["GATE_REPO"] = tmp
    env.update({"REFLECT_FACTS": fx_facts, "REFLECT_DOC": fx_doc})
    _run([sys.executable, os.path.join(repo, "zreflect", "facts.py")], cwd=repo, env=env)
    _run([sys.executable, os.path.join(repo, "zreflect", "facts.py"),
          "--render-doc", fx_doc], cwd=repo, env=env)

    _rc, out = _run([sys.executable, os.path.join(repo, "zreflect", "registry.py"),
                     "--all-runnable"], cwd=repo)
    gates = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    env.update({"REFLECT_DOCS": "%s,AGENTS.md" % fx_doc,
                "REFLECT_RETRACTIONS": "RETRACT.json",
                "REFLECT_QUESTIONS": "cases",
                "REFLECT_READMES": "R1.md,R2.md,R3.md"})
    return env, gates


def _renamed_all_green(repo, gates, env):
    """After renaming, **every single** gate must be green. Returns `(ok, list of failures)`."""
    bad = []
    for rel in gates:
        rc, _o = _run([sys.executable, os.path.join(repo, rel)], cwd=repo, env=env)
        if rc != 0:
            bad.append(rel)
    return len(gates) - len(bad), bad


def _default_names_go_red(repo, gates, tmp):
    """Under default names, the gates named by `--red-need` **must go red**. Returns `(ok, the ones that didn't)`.

    ⚠️ The environment must be **clean**: give it only `GATE_REPO`, no renamed
    knobs — using the fixture's `env` means still running renamed, and this
    criterion can never hold (observed).
    """
    clean = {k: v for k, v in os.environ.items() if not k.startswith("REFLECT_")}
    clean["GATE_REPO"] = tmp
    red = set()
    for rel in gates:
        rc, _o = _run([sys.executable, os.path.join(repo, rel)], cwd=repo,
                      env=clean)
        if rc != 0:
            red.add(os.path.basename(rel))
    _rc, rout = _run([sys.executable, os.path.join(repo, "zreflect", "registry.py"),
                      "--red-need"], cwd=repo)
    # ⚠️ `--red-need`'s output is **one line with space-separated** names (not
    # one per line). Splitting by line would treat the whole string as one
    # name, so "it didn't go red" would always hit (observed).
    red_need = (rout or "").split()
    return red_need, [b for b in red_need if b not in red]


def _configurable_impl(repo, tmp, registry):
    """Cross-repo configurability: the fixture repo with every name swapped still all green; gates named under default names must red.

    Three sections (each a helper): `_configurable_fixture` /
    `_renamed_all_green` / `_default_names_go_red`. This function only
    orchestrates — 85 lines → 20.
    """
    env, gates = _configurable_fixture(repo, tmp, registry)
    lines = []
    if not gates:
        lines.append(str(M("harness.no_gates_in_fixture")))
        return False, lines

    ok, bad = _renamed_all_green(repo, gates, env)
    for rel in bad:
        lines.append(str(M("harness.rename_failed", file=rel)))

    red_need, not_red = _default_names_go_red(repo, gates, tmp)
    if not red_need:
        lines.append(str(M("harness.empty_red_list")))
        return False, lines
    for b in not_red:
        lines.append(str(M("harness.not_red_under_defaults", gate=b)))
        return False, lines

    if ok != len(gates):
        lines.append(str(M("harness.configurable_failed",
                           ok=ok, total=len(gates))))
        return False, lines
    lines.append(str(M("harness.configurable_ok",
                       ok=ok, total=len(gates),
                       red=", ".join(red_need))))
    return True, lines


# End-to-end zero-language probes: these entry points **all produce
# user-visible text**.
# With no language pack installed they must emit only codes — not one CJK
# character allowed.
# ⚠️ Probes only pick entry points that **don't put user data into the
# output**.
#
# `zreflect/next.py` can't be a probe: it lists the **subjects** of unpushed
# commits — commit subjects are natural language written by the author
# (Chinese), which is **user data**, emitted verbatim as parameter values
# beyond `%(count)s`. The zero-language regime governs **templates** (`M()`'s
# phrasing), not data.
# Making it a probe would turn "just wrote a commit message in Chinese" into
# a false red (observed: this very case was reddened by its own commit
# subject).
#
# Its templates are covered by `check_i18n`'s `null_pack_output_has_no_cjk`
# (that case **feeds fixed parameters only**, never touching git state) — so
# it hasn't left the criteria surface, it just got the right test method.
ZERO_LANG_PROBES: tuple = (
    ("zreflect/gate.py", []),
    # ⚠️ Probes clear all `REFLECT_*` (what's judged is exactly the "no
    # language pack requested" path), so the only eligible entry points are
    # ones that **neither consume configuration nor emit PINNED text**. Two
    # lessons from practice:
    #
    #   · `facts.py --check` — depends on `REFLECT_DOCS`/`REFLECT_DOC` to
    #     decide which docs to audit. With them cleared it uses the default
    #     roster, which doesn't match this repo's actual configuration ⇒
    #     permanently red, and that red has nothing to do with language.
    #   · `facts.py --render` — the output `PREAMBLE` is **fixed Chinese**
    #     (`PINNED:`: the machine block is audited byte-for-byte; following
    #     the language would make `--check` never converge) ⇒ permanent CJK
    #     leak report.
    #
    # `registry --red-need` is a pure filename list: zero configuration
    # dependency, zero natural language.
    ("zreflect/registry.py", ["--red-need"]),
    ("zreflect/knobs.py", ["--list"]),
)


def run_zero_language(repo):
    """**End-to-end** zero language: run real entry points with no language pack installed, assert zero Chinese in output.

    Why this case lives in the harness and not in `check_i18n`: `check_i18n`
    is a **static** AST scan (bare Chinese literals in source). It can't see
    "Chinese assembled at runtime", nor shell scripts. The observed incident
    was exactly that shape: clean source, injection emitting full Chinese
    (`inject_state` auto-picked the zh pack). A static criterion can never
    catch that.

    This one is a **behavioral** criterion: really run it, really look at the
    output.

    ⚠️ The environment **must** have no `REFLECT_LANG` — what's judged is
    exactly the "no language pack requested" path.
    """
    import i18n  # noqa: PLC0415
    lines = []
    bad = 0
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("REFLECT_")}
    env["GATE_REPO"] = repo
    for rel, extra in ZERO_LANG_PROBES:
        path = os.path.join(repo, rel)
        if not os.path.isfile(path):
            lines.append(str(M("harness.missing_file", file=rel)))
            bad += 1
            continue
        rc, out = _run([sys.executable, path] + extra, cwd=repo, env=env)
        if rc != 0:
            lines.append(str(M("harness.zero_lang_rc", file=rel, rc=rc)))
            bad += 1
            continue
        cjk_lines = [ln for ln in (out or "").splitlines() if i18n.han(ln)]
        if cjk_lines:
            lines.append(str(M("harness.zero_lang_leak",
                               file=rel, count=len(cjk_lines),
                               sample=cjk_lines[0][:60])))
            bad += 1
            continue
        lines.append(str(M("harness.zero_lang_ok", file=rel)))
    if not ZERO_LANG_PROBES:
        lines.append(str(M("harness.no_probes")))
        return False, lines
    return bad == 0, lines


def _section(heading, runner):
    """Run one section, print it, return that section's rc (0 = pass). main's loop body used to be repeated five times."""
    print(str(M(heading)))
    ok, *_, lines = runner()
    for ln in lines:
        print(ln)
    return 0 if ok else 1


def main(argv):
    repo = HERE
    if "--selftest" in argv:
        return _selftest()
    rc = _section("harness.heading", lambda: run_gates(repo))
    rc = rc or _section("harness.plugins_heading",
                        lambda: run_plugins(repo))
    rc = rc or _section("harness.modules_heading",
                        lambda: run_modules(repo))
    rc = rc or _section("harness.configurable_heading",
                        lambda: run_configurable(repo))
    # Last section: **end-to-end zero language** (must be zero Chinese with no pack installed).
    return rc or _section("harness.zero_lang_heading",
                          lambda: run_zero_language(repo))


# ── selftest ─────────────────────────────────────────────────────────────────

def _fixture(files, listing=None):
    """Build a fixture repo and run `run_gates`. Returns (ok, n, bad, lines)."""
    d = tempfile.mkdtemp()
    try:
        for rel, body in files.items():
            p = os.path.join(d, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w", encoding="utf-8").write(body)
        return run_gates(d, listing=listing)
    finally:
        shutil.rmtree(d, True)


GOOD_GATE = '''import sys
print("=== %d PASS / 0 FAIL ===")
sys.exit(0 if "--selftest" in sys.argv else 0)
'''


def _cases():
    return [
        # (1) healthy input reports nothing: advertises --selftest, emits a summary line, rc=0
        ("harness.good_gate_is_green",
         lambda: _fixture({"zreflect/check_ok.py": GOOD_GATE % 3,
                           }, listing=["zreflect/check_ok.py"])[0]),
        # (2) what should be reported must be reported
        ("★ harness.gate_without_selftest_entry_is_red",
         lambda: not _fixture({"zreflect/check_silent.py": "import sys\nsys.exit(0)\n"},
                              listing=["zreflect/check_silent.py"])[0]),
        ("★ harness.gate_that_cannot_go_red_is_red",
         lambda: not _fixture(
             {"zreflect/check_bad.py":
              'import sys\nprint("=== 1 PASS / 1 FAIL ===")\n'
              'sys.exit(1 if "--selftest" in sys.argv else 0)\n'},
             listing=["zreflect/check_bad.py"])[0]),
        ("★ harness.gate_without_summary_is_red",
         lambda: not _fixture(
             {"zreflect/check_nosummary.py": 'import sys\nsys.exit(0)\n'},
             listing=["zreflect/check_nosummary.py"])[0]),
        ("★ harness.missing_file_is_red",
         lambda: not _fixture({}, listing=["zreflect/check_gone.py"])[0]),
        # (3) empty input must be reported — zero-value guard
        ("★ harness.no_gates_at_all_is_red",
         lambda: not _fixture({}, listing=[])[0]),
        # The summary-line criterion itself has teeth (criterion lives in machine.is_summary)
        ("★ harness.summary_shape_can_red", lambda: _summary_shape_ok()),
    ]


def _summary_shape_ok():
    import machine  # noqa: PLC0415
    return machine.is_summary("=== 3 PASS / 0 FAIL ===") and \
        not machine.is_summary("=== 3 PASS / 0 fail ===")


def _selftest():
    from gate import selftest  # noqa: PLC0415
    return selftest(M("gate.title.harness"), _cases())


from gate import module_meta  # noqa: E402

MODULE = module_meta(
    "gate selftest harness",
    "discover and run every gate's --selftest (must be able to red + must emit a machine summary line) + plugins + platform modules + cross-repo configurability",
    selftest=True)

if __name__ == "__main__":
    from gate import activate_or_fatal  # noqa: PLC0415
    rc = activate_or_fatal()
    sys.exit(rc or main(sys.argv[1:]))
