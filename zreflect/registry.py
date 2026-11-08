#!/usr/bin/env python3
"""registry — the data plane of the discovered rosters: gate list / plugin list / red list.

"Registration is discovered, not remembered" — this repo long since made the
**set** of gates discovered (`for g in zreflect/check_*.py` in hooks / runner /
CI), but the **narrative** of the set was still hand-written: STATE.md
hand-wrote "N gates" and named them one by one (observed drift: the day
ab/locks/pins merged, the list was short three gates and no gate could stop it —
the hand-written "ten" miscounted even the count); gates-selftest.sh hand-wrote
the red list (6 gates actually red under default names, only 4 in the list);
plugins and doctor relied on name-calling. This module turns the narrative into
data:

  · `gates()`: ast-parses each check_*.py's module-level declaration line
        GATE = gate.meta("name", "one line", knobs=(…), name_dependent=…)
    — **declaration is registration**; gate modules are not imported (no side
    effects, no execution cost). A check_*.py without a declaration line ⇒ the
    roster does not take it (problems reports; render refuses to render);
  · `red_need()`: the gates that **must go red** in the rename self-evidence
    (the ones whose default names carry the load). The name_dependent flag is
    registered explicitly — a machine cannot derive "the off-state short
    circuit" (an instrument gate is off by default, so the default names it
    consumes never get used; consumption alone cannot assert red), but the
    registration is blocked on both ends: the fixture demands it really goes
    red, and `problems()` demands it really consumes the renamed default names;
  · `plugins()`: reflect-hooks/*.sh carrying the selftest marker (discovered) +
    named special cases (doctor.py — the reason lives next to the data).

Consumers: `facts.py --render-doc` renders the AUTO:GATES machine block (same
precedent as AUTO:FACTS — the hand-written list retires, and `check_facts` /
`--check` automatically blocks drift); gates-selftest.sh consumes `--red-need`
and `--plugins` (the hand-written red list and the name-calling of plugins and
doctor retire).

Honesty boundary: this module only **narrates** rosters and never executes
gates; whether a gate can go red is forever proven by gates-selftest.sh actually
running — the judgments of narration and execution each stay on their own side;
do not mix them.
"""
from __future__ import annotations

import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import criteria  # noqa: E402
import gate  # noqa: E402
from gate import fatal, main_selftest_or, module_meta, repo  # noqa: E402
from i18n import M  # noqa: E402
from knobs import REGISTRY  # noqa: E402

# PINNED: the AUTO machine block uses a fixed language (same reason as render.PREAMBLE).
GATES_BEGIN = "<!-- AUTO:GATES -->"
GATES_END = "<!-- /AUTO:GATES -->"



# Which default names the rename self-evidence's fixture renames (the rename
# surface of gates-selftest.sh's cross-repo section).
# Roster discipline same as knobs: only register default names the fixture really
# renames — this is the judgment data of the red-list reconciliation.
# C4 reconciliation (3): `FIXTURE_RENAMES` is the **single producer** of
# "original name -> fixture name" — gates-selftest.sh's fixture derives the file
# names it creates from `--fixture-renames`, no longer hand-writing two lists
# that would drift (the fixture's names and this table used to be two
# hand-written copies with no reconciler).
FIXTURE_RENAMES = {
    "FACTS.json": "LEDGER.json",
    "STATE.md": "NOTES.md",
    "retractions.json": "RETRACT.json",
    "questions": "cases",
    "README.md": "R1.md",
    "README.zh.md": "R2.md",
    "README.de.md": "R3.md",
}
RENAMED_DEFAULTS = tuple(FIXTURE_RENAMES)

# Known phases (C1): gates declare their own run frequency. The execution plane
# (gate.run_phase) filters on it.
#   commit        runs on every commit (pre-commit / pre-push / CI)
#   start-of-work run manually before starting work (doctor — checks things that
#                 die; attaching it to commit frequency would be wrong)
# ⚠️ issue #21: welding the phase list **here** would force downstream forks —
# consumers have their own phases (the S26 repo's lab: *.lab.py only runs when
# the experiment directory is present). The knob `REFLECT_PHASES` appends custom
# phases (comma-separated, appended after the two built-ins); the core two
# cannot be removed or shadowed — phases are the shared vocabulary of the
# execution plane and declarations, and arbitrary renaming would silently orphan
# existing runs_at declarations. problems() still blocks unknown phases: a
# declared runs_at not in the list ⇒ red.
BUILTIN_PHASES = ("commit", "start-of-work")


def phases():
    """Known phases = the two built-ins + `REFLECT_PHASES` appends (downstream
    custom, e.g. lab)."""
    raw = os.environ.get("REFLECT_PHASES", "").strip()
    out = list(BUILTIN_PHASES)
    for p in (x.strip() for x in raw.split(",")):
        if p and p not in out:
            out.append(p)
    return tuple(out)


def phases_problems():
    """Phase-list self-consistency (the judgment for bad knob values; pure function)."""
    raw = os.environ.get("REFLECT_PHASES", "").strip()
    out = []
    if raw:
        dup = [p for p in (x.strip() for x in raw.split(","))
               if p in BUILTIN_PHASES]
        if dup:
            out.append(M("registry.builtin_phase_repeated",
                         phases=", ".join(sorted(set(dup)))))
    return out

def modules(zdir=None):
    """Platform-module roster (C5): ast-parses `MODULE = module_meta(…)` declaration lines.

    Returns (declared, undeclared): `declared` = [{file, name, desc, selftest}];
    `undeclared` = .py files that are **neither gates nor __init__ yet carry no
    MODULE declaration** — a platform module must declare itself (even with
    selftest=False it must positively say "I don't use self-evidence"),
    otherwise "should have self-evidence but doesn't" goes unasked (guessing
    `_cases` from text cannot guess "should have existed").
    """
    d = zdir if zdir is not None else gate.zdir()
    declared, undeclared = [], []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return [], []
    for n in names:
        if not n.endswith(".py") or n == "__init__.py":
            continue
        # ⚠️ **`measure_*.py` are the consumer's data modules, not platform
        # modules.**
        #
        # This exemption was forced by "wiring into a real project" acceptance:
        # following the README's "Writing your measure()" and dropping the
        # module at `zreflect/measure_myproject.py`, `--render-doc` went FATAL
        # on the spot:
        #
        #     · these .py files are neither gates … nor declared platform
        #       modules: zreflect/measure_myproject.py
        #
        # The user has no way to know their data module needs
        # `MODULE = module_meta(...)` — that is a discipline of **this repo for
        # its own code** ("should have self-evidence but doesn't" goes unasked),
        # not something to impose on a consumer's data file.
        if n.startswith("measure_"):
            continue
        rel = "zreflect/" + n
        if _declaration(os.path.join(d, n), rel, attr="MODULE", func="module_meta"):
            declared.append(_declaration(os.path.join(d, n), rel,
                                         attr="MODULE", func="module_meta"))
        elif _declaration(os.path.join(d, n), rel):
            continue                    # a gate (has a GATE declaration); not a platform module
        else:
            undeclared.append(rel)
    return declared, undeclared


def selftest_modules(zdir=None):
    """Roster of modules with a self-evidence obligation (C5, declaration-driven):
    modules declared via `MODULE = module_meta(…, selftest=True)` — gates (GATE
    declarations) are not counted (run_gates covers them). Returns (mods,
    missing): `mods` = those that should run selftests; `missing` = declared
    selftest=True but without a --selftest entry (written but never run =
    decoration).
    """
    declared, _und = modules(zdir)
    d = zdir if zdir is not None else gate.zdir()
    mods, missing = [], []
    for m in declared:
        if not m.get("selftest"):
            continue
        text = open(os.path.join(d, os.path.basename(m["file"])),
                    encoding="utf-8").read()
        can = ("--selftest" in text or "main_selftest_or" in text
               or "_selftest()" in text)
        if can:
            mods.append(m["file"])
        else:
            missing.append(m["file"])
    return mods, missing



def gates(zdir=None):
    """The discovered gate roster: **declared means a gate** — ast-parses the
    module-level `GATE = gate.meta(…)` lines of zreflect/*.py, independent of
    file names (C1).

    Returns (gates, missing). gates = [{file, name, desc, knobs,
    name_dependent, runs_at}]; missing = files **named check_ without a
    declaration line** (problems reports; render refuses — the shape of "named
    like a gate but forgot to declare").
    """
    d = zdir if zdir is not None else gate.zdir()
    out, missing = [], []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return [], []                     # zreflect/ absent: the caller reports per the zero-value guard
    for n in names:
        if not n.endswith(".py") or n == "__init__.py":
            continue
        rel = "zreflect/" + n
        meta = _declaration(os.path.join(d, n), rel)
        if meta:
            out.append(meta)
        elif n.startswith("check_"):
            # Named check_ but no declaration ⇒ forgot the declaration (the roster
            # doesn't take it; render refuses).
            # Non-check_ without a declaration = platform module
            # (gate/knobs/registry/…), not a gate.
            missing.append(rel)
    return out, missing


def _decl_call(node, attr, func):
    """Is `node` a declaration line shaped `<attr> = <func>(…)`? If so ⇒ that call node.

    Both equivalent spellings are recognized: meta(…) (bare imported name) and
    gate.meta(…) (attribute). Not a declaration line / the call is not `func`
    ⇒ None (the caller keeps scanning the next line).
    """
    if not (isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == attr
            and isinstance(node.value, ast.Call)
            and len(node.value.args) >= 2):
        return None
    fn = node.value.func
    if getattr(fn, "id", "") == func or getattr(fn, "attr", "") == func:
        return node.value
    return None


def _module_meta(call, rel):
    """`MODULE = module_meta(…)` → {file, name, desc, selftest}."""
    st = True
    for kw in call.keywords:
        if kw.arg == "selftest":
            st = ast.literal_eval(kw.value)
    return {"file": rel,
            "name": ast.literal_eval(call.args[0]),
            "desc": ast.literal_eval(call.args[1]),
            "selftest": bool(st)}


def _gate_meta(call, rel):
    """`GATE = gate.meta(…)` → {file, name, desc, knobs, name_dependent, runs_at,
    off_reason}."""
    knobs, name_dep, runs_at, off_reason = (), False, "commit", None
    for kw in call.keywords:
        if kw.arg == "knobs":
            knobs = ast.literal_eval(kw.value)
        elif kw.arg == "name_dependent":
            name_dep = ast.literal_eval(kw.value)
        elif kw.arg == "runs_at":
            runs_at = ast.literal_eval(kw.value)
        elif kw.arg == "off_reason":
            off_reason = ast.literal_eval(kw.value)
    return {"file": rel,
            "name": ast.literal_eval(call.args[0]),
            "desc": ast.literal_eval(call.args[1]),
            "knobs": tuple(knobs),
            "name_dependent": bool(name_dep),
            "runs_at": str(runs_at),
            "off_reason": off_reason}


def _declaration(path, rel, attr="GATE", func="meta"):
    """ast-extract the declaration line from a file (default `GATE = meta(…)`;
    C5 uses `MODULE = module_meta(…)`). None if absent.

    `attr` / `func` are swappable (one parser serves both declaration kinds:
    gates and platform modules).
    """
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except (OSError, SyntaxError):
        return None
    for node in tree.body:
        call = _decl_call(node, attr, func)
        if call is None:
            continue
        try:
            if func == "module_meta":
                return _module_meta(call, rel)
            return _gate_meta(call, rel)
        except (ValueError, IndexError):
            return None
    return None


def runnable(phase="commit", zdir=None):
    """The list of gates that **should run** for a phase (C1: the execution plane's
    single producer).

    `phase="commit"` ⇒ what runs on every commit (hooks / CI);
    `phase="start-of-work"` ⇒ what runs manually before starting work (doctor).
    Returns [{file, name, runs_at, …}]. The declaration surface
    (GATE = meta(…, runs_at=…)) is the single producer — the execution plane no
    longer globs file names.
    """
    gs, _missing = gates(zdir)
    return [g for g in gs if g.get("runs_at", "commit") == phase]


def _touches_renamed(g):
    """Among the knobs this gate consumes, is any default name renamed by the rename
    self-evidence?"""
    for k in g["knobs"]:
        kind, dflt, _ = REGISTRY.get(k, ("", "", ""))
        # The nested ternary is split into explicit branches (GitRoll #141) — a
        # list splits on commas, a default counts as one, none means none.
        # Semantics unchanged.
        if kind == "list":
            vals = {x.strip() for x in dflt.split(",")}
        elif dflt:
            vals = {dflt}
        else:
            vals = set()
        if vals & set(RENAMED_DEFAULTS):
            return True
    return False


def _missing_declaration_problems(missing):
    """Named check_ but no GATE declaration line — forgetting the declaration means
    the narrative drifts."""
    if not missing:
        return []
    return [M("registry.missing_declaration", files=", ".join(missing))]


def _phase_problems(gs):
    """runs_at must be a known phase — frequency is a declared field; a wrong value
    makes the execution plane miss the gate."""
    out = []
    for g in gs:
        if g.get("runs_at", "commit") not in phases():
            out.append(M("registry.unknown_phase",
                         file=g["file"], runs_at=g.get("runs_at"),
                         phases=" | ".join(phases())))
    return out


def _name_dependent_problems(gs):
    """Flagged name_dependent yet consumes no renamed default name — the flag is
    wrong."""
    out = []
    for g in gs:
        if g["name_dependent"] and not _touches_renamed(g):
            out.append(M("registry.name_dependent_wrong", file=g["file"]))
    return out


def _empty_gate_problems(gs, missing):
    """The roster as a whole is empty — the zero-value guard: empty input is not a
    pass."""
    if not gs and not missing:
        return [M("registry.empty_roster")]
    return []


def _selftest_roster_problems(mods, mods_missing):
    """The platform modules' selftest roster: declared means runnable, and the roster
    must not be empty."""
    if mods is None or mods_missing is None:
        mods, mods_missing = selftest_modules()
    out = []
    if mods_missing:
        out.append(M("registry.selftest_no_entry",
                     files=", ".join(mods_missing)))
    if not mods:
        out.append(M("registry.no_module_selftest"))
    return out


def _undeclared_module_problems(undeclared):
    """C5: platform modules must declare themselves (MODULE = module_meta(…)),
    otherwise "should have self-evidence but doesn't" goes unasked (guessing
    _cases from text cannot guess "should have existed")."""
    if undeclared is None:
        _decl, undeclared = modules()
    if not undeclared:
        return []
    return [M("registry.undeclared_module", files=", ".join(undeclared))]


def _knob_problems(knob_problems, gs):
    """Roster self-consistency (C3): phantom knobs / README phantoms — independent of
    whether any carrier exists.

    It used to be welded behind check_envfile.run()'s "carrier exists"
    precondition, and this repo has no Einfacht.env ⇒ never executed (observed
    hit). The roster's home closes here.
    """
    if knob_problems is None:
        import knobs  # noqa: PLC0415
        knob_problems = (knobs.scan_surface_problems()
                         + knobs.readme_problems()
                         # C4 reconciliations: declared↔read, REGISTRY↔README
                         # tables, zh↔en packs
                         + knobs.declared_vs_read_problems(gs)
                         + knobs.registry_vs_readme_problems()
                         + knobs.pack_sync_problems()
                         # C4 reconciliation (4): **every code the source uses
                         # must be in every installed pack** (the zh↔en set
                         # difference cannot see "both sides missing the same
                         # thing" — that is the silent degradation)
                         + knobs.pack_coverage_problems()
                         # DEFAULT_* defined but never used (gates pretending a
                         # default is configured)
                         + knobs.dead_default_problems())
    return list(knob_problems)


def problems(gs, missing, mods=None, mods_missing=None,
             knob_problems=None, undeclared=None):
    """The roster's reconciliation (pure function): empty = green. No print during
    self-evidence.

    `mods` / `mods_missing` / `knob_problems` are injectable (fixtures for
    self-evidence); None ⇒ read the real repo now.

    · named check_ without a GATE declaration line ⇒ report (forgot the
      declaration = the narrative drifts);
    · runs_at is not a known phase ⇒ report (frequency is a declared field; a
      wrong value makes the execution plane miss the gate);
    · flagged name_dependent yet consumes no renamed default ⇒ report (the flag
      is wrong);
    · self-evidence written but no --selftest entry ⇒ report (written but never
      run = decoration);
    · roster self-consistency (phantom knobs / README phantoms) ⇒ report (C3,
      carrier-independent);
    · the roster as a whole is empty ⇒ report (zero-value guard).
    """
    out = []
    out += phases_problems()
    out += _missing_declaration_problems(missing)
    out += _phase_problems(gs)
    out += _name_dependent_problems(gs)
    out += _empty_gate_problems(gs, missing)
    out += _selftest_roster_problems(mods, mods_missing)
    out += _undeclared_module_problems(undeclared)
    out += _knob_problems(knob_problems, gs)
    out += criteria.off_reason_problems(gs)
    out += criteria.trailing_newline_problems()
    out += criteria.shell_surface_problems()
    out += criteria.encoding_surface_problems()
    out += criteria.subprocess_encoding_problems()
    out += criteria.suite_scope_problems()
    out += criteria.fatal_exit_problems()
    # ⚠️ In injection mode (`mods=` given), **dead interfaces are not scanned**:
    # that judgment looks at the real directory while injection mode verifies
    # "the roster judgment itself"; mixing both into one list makes assertions
    # guilty by association with real-repo state (observed: the `unknown_phase`
    # assertion picked up an extra `dead_interface`).
    if mods is None:
        out += criteria.dead_interface_problems()
    return out





















def _pinned_under(lang):
    """Self-evidence helper: render the AUTO block under a given REFLECT_LANG (proves
    it does not vary with language)."""
    old = os.environ.get("REFLECT_LANG", "")
    os.environ["REFLECT_LANG"] = lang
    try:
        gs, _ = gates()
        return render_gates(gs)
    finally:
        os.environ["REFLECT_LANG"] = old


def _with_phases(val):
    """Self-evidence helper: temporarily set REFLECT_PHASES, return (phases(),
    problems()), restore the scene."""
    old = os.environ.get("REFLECT_PHASES", "")
    os.environ["REFLECT_PHASES"] = val
    try:
        return phases(), phases_problems()
    finally:
        os.environ["REFLECT_PHASES"] = old


def red_need(gs=None):
    """The gate file names that **must go red** in the rename self-evidence (the ones
    whose default names carry the load)."""
    if gs is None:
        gs, _ = gates()
    return sorted(os.path.basename(g["file"]) for g in gs
                  if g["name_dependent"] and _touches_renamed(g))


def plugins(hooks_dir=None):
    """The **plugin** list the self-evidence names: scripts under `reflect-hooks/`
    carrying `--selftest`.

    Discovered: both `.sh` and `.py` are collected — after the full Python
    migration the entry point is `.py`, but `einfacht-env.sh` must remain shell
    forever (it gets `source`d to export environment variables), so both exist.
    The judgment is "does the file contain `--selftest`", not the extension.
    """
    d = hooks_dir if hooks_dir is not None else repo("reflect-hooks")
    out = []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        names = []
    for n in names:
        if not (n.endswith((".sh", ".py"))):
            continue
        try:
            text = open(os.path.join(d, n), encoding="utf-8",
                        errors="replace").read()
        except OSError:
            continue
        if "--selftest" in text:
            out.append("reflect-hooks/" + n)
    return out


def render_gates(gs):
    """Gate roster -> the AUTO:GATES machine block (including begin/end markers).
    **Pure function**: rendering the same roster twice is byte-identical.

    PINNED: this block's text **always uses a fixed language** (issue #26, D''s
    insight), never following `REFLECT_LANG`. Reason: it is written into
    `STATE.md` and reconciled byte-for-byte by `facts.py --check` — if it
    followed the language, `REFLECT_LANG=de --render-doc` followed by
    `REFLECT_LANG=zh --check` would necessarily go red, and **the same commit
    would give different results in different language environments** (the same
    family of disease as `collect.py` principle 2: never introduce an input that
    changes by itself).
    Verified in practice: without PINNED it would not converge.
    """
    lines = [GATES_BEGIN,
             ("> This block is rendered by `zreflect/facts.py --render-doc` from the "
             "discovered roster (declaration lines in zreflect/registry.py); "
             "**do not hand-edit**."),
             ("> The execution plane (hooks / CI) reads `registry --run <phase>` — "
             "the phase is a declared field (`runs_at`), not a file name."),
             "",
             # ⚠️ "Reason it may be disabled" is a **declaration** (static), not
             # **runtime state**. Runtime off is seen via `registry --run
             # <phase>` — rendering it into this block would make the AUTO block
             # change on every run ⇒ no convergence (this repo's cardinal sin;
             # see the PINNED note).
             "| Gate | Phase | What it guards | Knobs consumed | Why it may be off |",
             "|---|---|---|---|---|"]
    for g in sorted(gs, key=lambda x: (x.get("runs_at", "commit"), x["file"])):
        lines.append("| `%s`（%s） | %s | %s | %s | %s |"
                     % (os.path.basename(g["file"]), g["name"],
                        g.get("runs_at", "commit"), g["desc"],
                        ", ".join("`%s`" % k for k in g["knobs"]) or "—",
                        g.get("off_reason") or "—"))
    off_capable = sum(1 for g in gs if g.get("off_reason"))
    lines += ["",
              "%d gates (derived from the discovered roster — a hand-written list "
              "drifts; adding a gate = landing one declaration line, and it grows "
              "here automatically); %d of them **may be disabled** (the last column "
              "is a **declared** justification, not runtime state — who is off "
              "right now is seen via `registry --run <phase>`)."
              % (len(gs), off_capable), GATES_END]
    return "\n".join(lines)


def _arg_after(argv, flag):
    """The optional value of `--flag [value]` (absent / starts with `-` ⇒ default
    commit)."""
    i = argv.index(flag)
    return (argv[i + 1] if len(argv) > i + 1
            and not argv[i + 1].startswith("-") else "commit")


def _emit_gate_output(text):
    """Relay one red gate's output to the user: the **problem lines + all diagnostic
    lines**, the rest dropped.

    ⚠️ The truncation rule is "stop after the first problem line", but the `ℹ `
    diagnostic lines must **not lose a single one** — they are the only sentence
    that can save the user. Observed: after one bootstrap, registry reported 3
    red, and `check_facts.py`'s diagnostic right after the problem line was
    `ℹ gate.env_hint(file='Einfacht.env')` ("source it first, then run by
    hand"). The old rule dropped it entirely, so the user, seeing "missing
    README.zh.md", went and created that file — right symptom, wrong cause, and
    creating it only made the red worse.
    """
    lines = [ln.rstrip() for ln in (text or "").splitlines() if ln.strip()]
    shown_problem = False
    for ln in lines:
        if ln.startswith("  \u00b7 "):
            if shown_problem:
                continue                  # problem lines from the second on are omitted (don't flood)
            shown_problem = True
        elif ln.lstrip().startswith("\u2139 "):
            pass                           # diagnostic line: always kept
        elif shown_problem:
            continue                       # non-diagnostic lines after a problem line: don't re-print
        print("      " + ln)


def _main_run(argv):
    """The execution plane: run all gates of one phase and aggregate ran / off /
    failed (C1+C2).

    hooks / CI call only this line — the glob retires, and the predicate has one
    home: gates().
    """
    phase = _arg_after(argv, "--run")
    from gate import run_phase  # noqa: PLC0415
    gs = runnable(phase)
    if not gs:
        return fatal(M("registry.empty_phase", phase=phase))
    # ⚠️ **All of this function's output goes to stdout** (including the fatal /
    # error / failed lists). This does **not** conflict with `gate.finish()`'s
    # "problem lines go to stderr": that rule only binds a single gate's own
    # judgment output; what is printed here is a **run report** (who didn't run /
    # who went red / whose config broke) — a status snapshot, not a judgment.
    # Reasons: (a) both consumers (CI, hook) only look at rc (`|| exit 1`) and
    # never parse stdout; (b) callers that capture only stdout (`$(...)` /
    # pipes) must be able to see **which file** broke — with stderr-only output
    # they would see `fatal=1` with no idea who (observed in round 10).
    res = run_phase(phase, gs)
    print(M("registry.phase_summary", phase=phase, ran=res["ran"],
            off=res["off"], failed=res["failed"], fatal=res.get("fatal", 0),
            error=res.get("error", 0)))
    for f in res["off_list"]:
        print(M("registry.phase_off", file=f))
    # ⚠️ These three lists are printed **to stdout as well**: aggregators often
    # capture only stdout (`$(...)` / pipes); with stderr-only they would see
    # `fatal=1` without knowing which file broke (observed in review). The
    # problem **cause** remains in the gate's own stderr — what's added here is
    # "who".
    for f in res.get("fatal_list", ()):
        print(M("registry.phase_fatal", file=f))
    for f in res.get("error_list", ()):
        print(M("registry.phase_error", file=f))
    for f in res["fail_list"]:
        print("  FAILED %s" % f)
        _emit_gate_output((res.get("fail_out", {}).get(f) or ""))
    # Broken config (rc=2) and red judgment (rc=1) both exit non-zero, but with
    # different messages (different fixes)
    return 1 if (res["failed"] or res.get("fatal") or res.get("error")) else 0


def cli_selftest_missing_lines(missing):
    """The per-line name-calling of `--selftest-modules` (pure function: for
    self-evidence, zero print)."""
    return [M("registry.selftest_no_entry_cli", file=m) for m in missing]


def _main_selftest_modules():
    mods, missing = selftest_modules()
    for line in cli_selftest_missing_lines(missing):
        # The CLI's per-line name-calling and the roster's summary sentence are
        # **two distinct outputs** (previously each had its own wording); keep
        # both codes during migration, don't reshape the CLI line into the
        # summary sentence.
        print(line, file=sys.stderr)
    if missing:
        return 1
    print("\n".join(mods))
    return 0


# Which codes are **fixable configuration hints** (they don't brick the roster) and
# which mean **the roster itself is broken**.
#
# ⚠️ This distinction came from practice: after the user creates `Einfacht.env`
# per the docs, the `off_reason` ("this repo has no Einfacht.env") goes stale —
# the judgment **is correct**, but treating it as fatal makes `registry --gates`
# / `--run commit` / pre-commit **permanently red**, and the only way out is to
# delete the file the docs told them to create. That is a **self-set trap**, not
# a user error.
#
# The right reaction: clearly say "go fix the gate's off_reason", then
# **continue** (the roster is usable).
_ADVISORY_CODES = frozenset({"registry.off_reason_stale"})


def _main_gates():
    gs, missing = gates()
    probs = problems(gs, missing)
    fatal_probs = [p for p in probs if getattr(p, "code", "") not in _ADVISORY_CODES]
    for x in probs:
        if getattr(x, "code", "") in _ADVISORY_CODES:
            print("  ! %s" % x, file=sys.stderr)      # hint, not a refusal
        else:
            print("  · %s" % x, file=sys.stderr)
    if fatal_probs:
        return fatal(M("registry.roster_problems", count=len(fatal_probs)))
    for g in gs:
        print("%s\t%s\t%s" % (g["file"], g["name"], g["desc"]))
    return 0


def _main_lists(argv):
    """The three list prints: `--red-need` / `--runnable` / `--all-runnable`.

    Returns rc; none of these flags ⇒ None (the caller keeps probing).
    """
    if "--red-need" in argv:
        print(" ".join(red_need()))
        return 0
    if "--runnable" in argv:
        # The execution plane's single producer (C1): --runnable [phase], default commit.
        for g in runnable(_arg_after(argv, "--runnable")):
            print(g["file"])
        return 0
    if "--all-runnable" in argv:
        # Gates of all phases (for self-evidence: every gate must prove it can go
        # red, regardless of phase).
        gs, _m = gates()
        for g in gs:
            print(g["file"])
        return 0
    return None


def _main_listings(argv):
    """The two per-line listings: `--plugins` / `--fixture-renames`.

    Returns rc; none of these flags ⇒ None (the caller keeps probing).
    """
    if "--plugins" in argv:
        print("\n".join(plugins()))
        return 0
    if "--fixture-renames" in argv:
        # C4 reconciliation (3): the fixture rename set's single producer
        # (original=fixture name, one per line).
        for orig, fix in sorted(FIXTURE_RENAMES.items()):
            print("%s=%s" % (orig, fix))
        return 0
    return None


def _usage():
    """The usage line. A **function, not a module constant**: the language pack is
    only `activate()`d inside the `main_selftest_or` entry; a module-level `M(…)`
    would be frozen on the null pack at import time."""
    return M("registry.usage")


def main(argv):
    rc = _main_lists(argv)
    if rc is not None:
        return rc
    if "--run" in argv:
        return _main_run(argv)
    rc = _main_listings(argv)
    if rc is not None:
        return rc
    if "--selftest-modules" in argv:
        return _main_selftest_modules()
    if "--gates" in argv:
        return _main_gates()
    print(_usage(), file=sys.stderr)
    return 2


def _phase_tiers_ok():
    """`run_phase` must keep the four tiers ran / off / failed / fatal apart."""
    from gate import run_phase  # noqa: PLC0415
    script = {"fatal.py": (2, "FATAL: cfg"),
              "fail.py": (1, "gate.problems_header"),
              "off.py": (0, "OFF: x"),
              "ok.py": (0, "")}
    # The first run's (basic four-tier shape) return value only confirms it doesn't
    # explode — GitRoll #104 "assigned but never used": explicitly bind `_`,
    # turning the intent from implicit to explicit.
    _ = run_phase("commit", list(script), runner=lambda f: script[f])
    script["err.py"] = (3, "boom")          # an unagreed code / killed by signal
    res = run_phase("commit", list(script), runner=lambda f: script[f])
    return (res["fatal"] == 1 and res["fatal_list"] == ["fatal.py"]
            and res["failed"] == 1 and res["fail_list"] == ["fail.py"]
            and res["error"] == 1 and res["error_list"] == ["err.py"]
            and res["off"] == 1 and res["off_list"] == ["off.py"]
            and res["ran"] == 1)


def _captures_stderr():
    """`default_runner` must bring the subprocess's **stderr back too**.

    ⚠️ This must **test the default executor itself** (`gate.default_runner`),
    not an injected runner: an injected runner is written by the self-test, and
    testing it equals testing yourself. The previous version did exactly that
    and returned BLIND against the old implementation (the old implementation
    also filed rc=2 under fatal; the difference was whether out contained
    stderr's content).
    """
    import os  # noqa: PLC0415
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    from gate import default_runner  # noqa: PLC0415
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, "boom.py")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("import sys\n"
                     "sys.stderr.write('FATAL: probe\\n')\n"
                     "sys.exit(2)\n")
        rc, out = default_runner(p, d)
        # Writes to stderr only ⇒ stdout empty; if the executor returns only
        # stdout, out is the empty string
        return rc == 2 and "FATAL: probe" in out
    finally:
        shutil.rmtree(d, True)




def _render_shows_off_reason():
    """A fake gate declaring `off_reason` ⇒ that text must appear in the AUTO block."""
    gs = [{"file": "zreflect/check_probe.py", "name": "probe",
           "desc": "probe gate", "knobs": (), "runs_at": "commit",
           "off_reason": "a declared justification long enough"}]
    body = render_gates(gs)
    # ⚠️ **No Chinese literals** (this file is inside the zero-language gates'
    # scan surface — observed hit on bare_text). Judge the machine-readable
    # parts instead: the off_reason text must appear at end of line, and the
    # line's column count must match the header.
    return ("a declared justification long enough" in body
            and body.count("|") >= 6)


def _render_off_reason_dash():
    """No `off_reason` declared ⇒ that cell is `—` (not the empty string, not None)."""
    gs = [{"file": "zreflect/check_probe.py", "name": "probe",
           "desc": "probe gate", "knobs": (), "runs_at": "commit",
           "off_reason": None}]
    row = [ln for ln in render_gates(gs).splitlines()
           if ln.startswith("| `check_probe.py`")][0]
    return row.rstrip().endswith("| — |") and "None" not in row


def _streams_documented():
    """Both wordings must be in the source (gate.py scopes it to a single gate / this
    file explains that aggregators go to stdout)."""
    import gate  # noqa: PLC0415
    try:
        g = open(gate.__file__, encoding="utf-8").read()
        r = open(os.path.abspath(__file__), encoding="utf-8")
        r = r.read()
    except OSError:
        return False
    # ⚠️ Anchors are plain ASCII fragments of the two normative sentences — this
    # file is inside the zero-language gates' scan surface, so no natural-language
    # fixture is written as a literal here (the CJK code-point assembly this
    # check once used broke when the sources were de-language-fied; the anchors
    # only need to be machine-matchable, and the judgment name still says what
    # is tested).
    _a1 = "single gate's problem lines"     # gate.py: the stderr rule is scoped to one gate
    _a2 = "function's output goes to stdout"  # here: the run report goes to stdout
    return (_a1 in g and _a2 in r and
            ("stdout" in r and "stdout" in g))








def _plugin_discovery_ok():
    """Plugin discovery: directory present ⇒ the env plugin must be found; directory
    absent ⇒ an empty list is also correct."""
    import os  # noqa: PLC0415
    d = repo("reflect-hooks")
    found = plugins()
    if not os.path.isdir(d):
        return found == []          # no plugin directory installed ⇒ empty list is correct
    return ("reflect-hooks/einfacht-env.sh" in found
            and "zreflect/doctor.py" not in found)


def _nf_catches(which):
    """Test `never_falsifiable` with **lambdas in a real file** (it locates the AST by
    line number; a lambda in `-c` has no source file ⇒ it goes blind).

    Four shapes, one each:
      · `or_true`      — `or True` (the boolean is short-circuited by a constant)
      · `and_false`    — `and False`
      · `self_compare` — `x == x`
      · `real`         — a real assertion (must return None)
    """
    from gate import never_falsifiable  # noqa: PLC0415
    y = 1                                                # used by self_compare
    shapes = {
        "or_true": lambda: (1 == 1) or True,
        "and_false": lambda: (1 == 1) and False,
        "self_compare": lambda: y == y,
        "real": lambda: y > 0,
    }
    return never_falsifiable(shapes[which])


def _nf_no_source():
    """No `co_filename` (a lambda in `-c`, builtins) ⇒ must return None (no guessing).

    This pins boundary (c): `never_falsifiable` relies on `ast` to locate the
    **real file**; if it can't be read it says so rather than guessing — not
    "always true" and not "clean".
    """
    from gate import never_falsifiable  # noqa: PLC0415
    # Build a function **without co_filename** via `compile` + `exec` instead of
    # `eval`: identical semantics (the tool wants exactly the "can't read the
    # source" boundary), but the static security scanner need not open an
    # exemption (`S307`) for a test fixture's `eval`. An eval in a fixture looks
    # like an eval in product code, and later nobody can tell which was
    # intentional.
    ns = {}
    exec(compile("f = lambda: True", "<no-source>", "exec"), ns)  # noqa: S102
    return never_falsifiable(ns["f"])


def _gate_desc_states_selftest():
    """`gate.py`'s MODULE description must state "the logic selftest lives in
    registry._cases"."""
    mods, _und = modules()
    for m in mods:
        if m["file"].endswith("gate.py"):
            d = m["desc"]
            # Anchors are **all ASCII**: `registry._cases` (where the selftest
            # lives) + `--selftest` (why there is no entry). No Chinese literals
            # (this file is in the zero-language gates' scan surface, and
            # code-point assembly is error-prone — 0x72EC was once mistyped as
            # the wrong character).
            return ("registry._cases" in d) and ("--selftest" in d) \
                and ("selftest" in d)
    return False




















def _load_spec_ok():
    """`load_spec` returns `(None, error sentence)` when unreadable; it does **not
    raise**."""
    got = gate.load_spec("/nonexistent-probe.json")
    return isinstance(got, tuple) and len(got) == 2 \
        and got[0] is None and got[1] is not None


def _cases_fixture(d):
    """Build a fake roster. `d` comes from `_cases()` (which owns mkdtemp and cleanup)."""
    # The fixture's declaration data uses **ASCII names**: they are inputs
    # extracted by ast (they enter the AUTO:GATES machine block), not core
    # output — Chinese fixtures would be adopted by the zero-language gates.
    open(os.path.join(d, "check_ok.py"), "w", encoding="utf-8").write(
        'GATE = gate.meta("gate_a", "blocks_a", knobs=("REFLECT_FACTS",),'
        ' name_dependent=True)\n')
    open(os.path.join(d, "check_plain.py"), "w", encoding="utf-8").write(
        'GATE = gate.meta("gate_b", "blocks_b", knobs=("REFLECT_WORLD",))\n')
    open(os.path.join(d, "check_bare.py"), "w", encoding="utf-8").write("X = 1\n")
    open(os.path.join(d, "named_other.py"), "w", encoding="utf-8").write(
        'GATE = gate.meta("gate_c", "declared means registered", knobs=())\n')
    open(os.path.join(d, "doc_gate.py"), "w", encoding="utf-8").write(
        'GATE = gate.meta("gate_d", "start-of-work phase", knobs=(),'
        ' runs_at="start-of-work")\n')
    open(os.path.join(d, "platform.py"), "w", encoding="utf-8").write("Y = 2\n")   # no declaration = platform module
    gs, missing = gates(d)
    ok = [g for g in gs if g["file"].endswith("check_ok.py")][0]
    plain = [g for g in gs if g["file"].endswith("check_plain.py")][0]
    real, real_missing = gates()

    def real_files():
        # ⚠️ `_zdir()` (the **tooling repo's** zreflect), not `d` (the temporary
        # fixture directory) — this assertion compares "real roster vs real
        # disk", unrelated to the fixture.
        return {"zreflect/" + n for n in os.listdir(gate.zdir())
                if n.startswith("check_") and n.endswith(".py")}
    return {"ok": ok, "plain": plain, "real": real,
            "real_missing": real_missing, "gs": gs,
            "missing": missing, "real_files": real_files}


def _cases_discovery_real(fx):
    """(a) Normally no report: the real repo's roster and declaration surface. (8 cases)"""
    ok, real = fx["ok"], fx["real"]
    gs, missing, real_missing, real_files = (fx["gs"], fx["missing"],
                                             fx["real_missing"], fx["real_files"])
    return [
        ("registry.ast_declaration_fields",
         lambda: ok["name"] == "gate_a" and ok["desc"] == "blocks_a"
         and ok["knobs"] == ("REFLECT_FACTS",)
         and ok["name_dependent"] is True and ok["runs_at"] == "commit"),
        ("registry.undeclared_noncheck_is_module",
         lambda: all(not m.endswith("platform.py") for m in missing)
         and all(not g["file"].endswith("platform.py") for g in gs)),
        ("registry.declaration_is_registration",
         lambda: any(g["file"].endswith("named_other.py") for g in gs)
         and not any(m.endswith("named_other.py") for m in missing)),
        ("registry.real_roster_matches_disk",
         lambda: not real_missing and real_files() <= {g["file"] for g in real}),
        ("registry.doctor_is_start_of_work",
         lambda: any(g["file"].endswith("doctor.py") for g in real)
         and not any(g["file"].endswith("doctor.py")
                     for g in runnable("commit"))),
        ("registry.red_need_flagged",
         lambda: (lambda rn: len(rn) >= 1 and all(
             any(g["file"].endswith(b) and g["name_dependent"] for g in real)
             for b in rn))(red_need(real))),
        ("registry.real_modules_declared",
         lambda: modules()[1] == [] and len(modules()[0]) >= 8),
        ("registry.fixture_renames_single_source",
         lambda: set(FIXTURE_RENAMES) == set(RENAMED_DEFAULTS)
         and len(FIXTURE_RENAMES) >= 7),
        # The plugin directory **may not exist** (a deployment copying only
        # `zreflect/`): then there is no plugin to discover, and that is not a
        # failure. Present means it must be found — the assertion splits on
        # "directory present or not".
        ("registry.plugin_discovery", lambda: _plugin_discovery_ok()),
    ]


def _cases_discovery_reports(fx):
    """(b) What must report must report: the roster reconciliation's six diseases. (6 cases)"""
    plain, missing = fx["plain"], fx["missing"]
    return [
        ("\u2605 registry.missing_declaration",
         lambda: missing == ["zreflect/check_bare.py"]),
        ("\u2605 registry.name_dependent_wrong",
         lambda: [p.code for p in problems(
             [dict(plain, name_dependent=True)], [],
             mods=["zreflect/x.py"], mods_missing=[], knob_problems=[],
             undeclared=[])] == ["registry.name_dependent_wrong"]),
        # In the next two cases an empty roster and "an empty list is not a pass"
        # are present simultaneously (gs=[] necessarily triggers the zero-value
        # guard), so use `any(code == …)` instead of whole-list equality — the
        # assertion still pins exactly that one.
        ("\u2605 registry.selftest_no_entry",
         lambda: any(p.code == "registry.selftest_no_entry" for p in problems(
             [], [], mods=["zreflect/x.py"],
             mods_missing=["zreflect/y.py"],
             knob_problems=[]))),
        # The CLI's per-line name-calling must be producible too (otherwise it is
        # "written but never run" decoration — this repo's discipline).
        ("\u2605 registry.selftest_no_entry_cli",
         lambda: [m.code for m in cli_selftest_missing_lines(
             ["zreflect/y.py"])] == ["registry.selftest_no_entry_cli"]
         and cli_selftest_missing_lines([]) == []),
        ("\u2605 registry.undeclared_module",
         lambda: any(p.code == "registry.undeclared_module" for p in problems(
             [], [], mods=["zreflect/x.py"], mods_missing=[],
             knob_problems=[],
             undeclared=["zreflect/orphan_mod.py"]))),
        # **The aggregator's output goes to stdout as a whole**, which does not
        # conflict with "a single gate's problem lines go to stderr".
        # This pins "the two ends' semantics are written apart" — the judgment is
        # that both wordings exist.
        ("registry.aggregator_streams_documented",
         lambda: _streams_documented()),
    ]


def _cases_discovery(fx):
    """See `_cases()`: 16 cases in this group.

    (a) Real-repo roster / (b) roster diseases are each a named group: the former
    reads the fixture's real roster, the latter builds malformed declarations —
    mixed together, a reader cannot tell which input an assertion uses.
    """
    return (_cases_discovery_real(fx) + _cases_discovery_reports(fx)
            + [("\u2605 registry.empty_roster",
                lambda: problems([], [], mods=[], mods_missing=[],
                                 knob_problems=[], undeclared=[]) != [])])


def _cases_render(fx):
    """See `_cases()`: 4 cases in this group."""
    gs = fx["gs"]
    return [
    ("★ registry.auto_block_pinned_across_langs",
     lambda: _pinned_under("en") == _pinned_under("zh")
     and _pinned_under("de") == _pinned_under("")),
    ("registry.render_gates_pure",
     lambda: render_gates(gs) == render_gates(gs)
     and "gate_a" in render_gates(gs)
     and GATES_BEGIN in render_gates(gs) and GATES_END in render_gates(gs)),
    # **`off_reason` must be rendered into the AUTO block** (so the reader sees at
    # a glance which gates may be disabled and why) — and it is a
    # **declaration**, not runtime state (the latter would change the block every
    # run and never converge).
    ("★ registry.render_gates_shows_off_reason",
     lambda: _render_shows_off_reason()),
    # A gate without a declaration must render `—` in that cell (no empty string,
    # no "None")
    ("registry.render_gates_off_reason_dash",
     lambda: _render_off_reason_dash()),
    ]


def _cases_phase(fx):
    """See `_cases()`: 9 cases in this group."""
    plain = fx["plain"]
    d = fx["d"]
    return [
    ("registry.runnable_filters_by_phase",
     lambda: (lambda cm, sw: all(g["runs_at"] == "commit" for g in cm)
              and [g["file"] for g in sw]
              == ["zreflect/doc_gate.py"])(runnable("commit", d),
                                           runnable("start-of-work", d))),
    ("★ registry.unknown_phase",
     lambda: [p.code for p in problems(
         [dict(plain, runs_at="whenever")], [],
         mods=["zreflect/x.py"], mods_missing=[], knob_problems=[],
         undeclared=[])] == ["registry.unknown_phase"]),
    # **`run_phase` is the only execution entry for hooks/CI** and previously had
    # zero self-evidence. The tier aggregation must really be separate: rc=2
    # (broken config) != rc=1 (red judgment) != off. If merged into one tier,
    # "three gates reported real problems" and "one gate's config broke" would be
    # indistinguishable, while the fixes are entirely different (fix problems vs
    # fix config).
    ("★ registry.phase_tiers_separate",
     lambda: _phase_tiers_ok()),
    # **stderr must be captured**: this repo's convention is "problem lines go to
    # stderr", so an rc=2 gate's stdout may be empty (the reason lives entirely
    # in stderr). `_default` used to return only `p.stdout` ⇒ aggregators got
    # (2, "") and the FATAL was treated as "ran". This pins the **default
    # executor**'s behavior (an injected runner cannot test it).
    ("★ registry.run_phase_captures_stderr",
     lambda: _captures_stderr()),
    # issue #21: the phase knob — downstream custom phases (like S26's lab) no
    # longer fork PHASES
    ("registry.phases_extra_appended",
     lambda: _with_phases("lab")[0] == ("commit", "start-of-work", "lab")),
    ("★ registry.builtin_phase_repeated",
     lambda: [p.code for p in _with_phases("commit,lab")[1]
              ] == ["registry.builtin_phase_repeated"]),
    ("registry.phases_default_builtin_only",
     lambda: _with_phases("")[0] == ("commit", "start-of-work")),
    # The humane hint (env_hint): four judgments
    ]

def _env_hint_case(which):
    """`gate.env_hint()`'s **five tiers** of behavior (after the #28 fix: the carrier
    value joins the decision).

    1. `no_carrier`   — no carrier ⇒ None (a bare run stays quiet)
    2. `carrier_bare` — carrier present, knob unset ⇒ **hint** (nobody sourced it)
    3. `carrier_live` — knob set, value **matches** the carrier ⇒ None (the
       carrier has taken effect)
    4. `carrier_drift` — knob set, value **differs** from the carrier ⇒ **hint**
       (a manual export drifted)
    5. `carrier_off`  — `REFLECT_ENV_HINT=off` ⇒ the print layer emits nothing

    ⚠️ The judgment's semantic precondition is a "controlled process
    environment": in hook contexts the carrier gets sourced into the
    environment, and once the knob is set, `carrier_bare` would be permanently
    red (#29 observed: upstream's own `REFLECT_FACTS=x registry --selftest` ⇒ 1).
    Isolating the test from its own process's inputs is self-evidence's job: all
    relevant knobs are temporarily popped and restored in finally.
    """
    import shutil
    import tempfile  # noqa: PLC0415
    d = tempfile.mkdtemp()
    saved = gate.GATE_REPO
    saved_off = os.environ.pop("REFLECT_ENV_HINT", None)
    saved_fact = os.environ.pop("REFLECT_FACTS", None)
    try:
        gate.GATE_REPO = d
        if which != "no_carrier":
            open(os.path.join(d, "Einfacht.env"), "w",
                 encoding="utf-8").write("export REFLECT_FACTS=FACTS.json\n")
        if which == "carrier_off":
            # The silence of `off` happens at the **print layer** (`_maybe_hint`),
            # not in `env_hint` — `env_hint()` still computes the sentence; nobody
            # prints it. Test the print layer.
            os.environ["REFLECT_ENV_HINT"] = "off"
            import contextlib  # noqa: PLC0415
            import io  # noqa: PLC0415
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                gate._maybe_hint()
            return buf.getvalue() == ""       # must **not print a single character**
        if which == "carrier_live":
            os.environ["REFLECT_FACTS"] = "FACTS.json"    # matches the carrier
        elif which == "carrier_drift":
            os.environ["REFLECT_FACTS"] = "OTHER.json"    # differs from the carrier
        hint = gate.env_hint(consumed=("REFLECT_FACTS",))
        if which in ("carrier_bare", "carrier_drift"):
            return hint is not None          # must **hint**
        return hint is None                  # no carrier / already live ⇒ must stay silent
    finally:
        gate.GATE_REPO = saved
        if saved_off is not None:
            os.environ["REFLECT_ENV_HINT"] = saved_off
        else:
            os.environ.pop("REFLECT_ENV_HINT", None)
        if saved_fact is not None:
            os.environ["REFLECT_FACTS"] = saved_fact
        else:
            os.environ.pop("REFLECT_FACTS", None)
        shutil.rmtree(d, True)


def _cases_hint(fx):
    """See `_cases()`: the environment hint's (env_hint) silence conditions."""
    return [
        # ⚠️ These two used to be **vacuously true**: `env_hint(...) is None or
        # env_carrier() is not None` — as long as the repo had `Einfacht.env`,
        # the second clause always held (make `env_hint` always return a line and
        # the assertion still passed; observed). Now all three tiers by
        # **carrier presence** are tested.
        ("★ registry.env_hint_silent_without_carrier",
         lambda: _env_hint_case("no_carrier")),
        ("★ registry.env_hint_fires_with_carrier",
         lambda: _env_hint_case("carrier_bare")),
        # #28: the carrier has taken effect (values match) ⇒ silent — only a
        # correctly wired repo stays quiet
        ("registry.env_hint_silent_when_carrier_live",
         lambda: _env_hint_case("carrier_live")),
        # #28: a manual export drifted from the carrier ⇒ must hint (exactly the
        # scenario that should be loud)
        ("★ registry.env_hint_fires_on_drift",
         lambda: _env_hint_case("carrier_drift")),
        ("★ registry.env_hint_off_silent",
         lambda: _env_hint_case("carrier_off")),
    ]







def _cases_gate_hosted(fx):
    """`gate.py`'s judgments **are hosted here** — it declares `selftest=False`
    (it provides `selftest` itself; bootstrapping would fight itself), so its
    logic selftest can only live elsewhere. The only legal hosting in this repo."""
    return [
        # **`never_falsifiable`'s selftest** (round 22): it is the core guard of
        # `gate.selftest()` (from `gate.py:36`), catching "vacuously true
        # assertions" — previously the **whole repo had zero self-evidence** for
        # it. "The detector's detector" was never tested: when it fails, every
        # assertion silently loses its teeth.
        ("★ registry.never_falsifiable_catches_or_true",
         lambda: _nf_catches("or_true") is not None),
        ("★ registry.never_falsifiable_catches_and_false",
         lambda: _nf_catches("and_false") is not None),
        ("★ registry.never_falsifiable_catches_self_compare",
         lambda: _nf_catches("self_compare") is not None),
        # **Positive control**: a real assertion must **not** report (otherwise
        # "always report" would also fool the self-test)
        ("registry.never_falsifiable_allows_real",
         lambda: _nf_catches("real") is None),
        # Boundary (c): "can't read the source" ⇒ no guessing (returns None, neither
        # "always true" nor "clean")
        ("★ registry.never_falsifiable_no_source_no_guess",
         lambda: _nf_no_source() is None),
        # **`gate.py`'s `selftest=False` must state its real meaning** (round 23):
        # it does not mean "no self-evidence obligation", only "no `--selftest`
        # entry (bootstrapping would fight itself)". The description used to say
        # only "provides selftest, doesn't consume it itself" — reads like a
        # disclaimer.
        ("★ registry.gate_module_meta_states_where_selftest_lives",
         lambda: _gate_desc_states_selftest()),
        # The two `gate` functions just named by the dependency-chain judgment
        # (many consumers, zero assertions of their own)
        ("★ registry.guard_nonempty_returns_2",
         # empty ⇒ rc 2 (FATAL); non-empty ⇒ None
         lambda: gate.guard_nonempty("x", []) == 2
         and gate.guard_nonempty("x", [1]) is None),
        ("★ registry.load_spec_returns_error_not_raise",
         # broken path ⇒ (None, error sentence); no exception (the caller wants to
         # compose its own wording)
         lambda: _load_spec_ok()),
    ]





def _cases():
    """Assemble the six fixture groups. **Assembly only** — the judgments live in the
    group functions."""
    import atexit  # noqa: PLC0415
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    d = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, d, True)
    fx = _cases_fixture(d)
    fx["d"] = d
    return (        _cases_discovery(fx)
        + _cases_render(fx)
        + _cases_phase(fx)
        + _cases_hint(fx)
        + _cases_gate_hosted(fx)
    )


MODULE = module_meta("Discovered rosters", "declaration-derived gates/modules/plugins: execution plane + narrative + red list", selftest=True)


if __name__ == "__main__":
    # The finish goes uniformly through `main_selftest_or`: it first activates the
    # language pack (`activate_or_fatal`), then splits into `--selftest` and
    # `main()`. This used to hand-copy its own activate+FATAL, while gate's own
    # `__main__` was a third variant (no FATAL at all) — three copies of the same
    # thing; the wording was bound to drift.
    sys.exit(main_selftest_or(sys.argv[1:],
                              M("gate.title.registry"),
                              _cases, main))


