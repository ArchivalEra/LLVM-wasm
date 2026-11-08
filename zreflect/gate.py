#!/usr/bin/env python3
"""Gate platform: the rc contract + zero-trust guards + three-tier self-proof.

What it solves is **not** "having no checks" but **checks silently going green when
their input disappears**. Three real incidents:

  - Three sites all missing `VERSION` => the consistency gate reports "fully consistent";
  - The declared set is empty => the factory check reports `verdict: "ok"`;
  - A self-check script `0/0` => counted as "all passed".

So every checker must be able to answer two questions: **do I report when the input
is empty?** and **do I actually report what should be reported?**
`require_nonempty()` answers the first; `selftest()`'s three case classes answer the
second.

**The rc contract (this platform's interface, the repo-wide single source since
2026-10-07)**:

  - `off()`    => 0, not enabled (a pluggable gate's off state must **say so
    explicitly**, never silently);
  - `fatal()`  => 2, broken config / environment (knob points at something missing,
    bad JSON, malformed spec, the instrument itself is broken) -- a configuration
    failure != a check failure; merging it into 1 makes "found problems"
    indistinguishable from "the config is broken";
  - `finish()` => 1 (problems found) / 0 (green). Header first, problem lines after;
    **a single gate's problem lines all go to stderr** -- previously the 13 gates
    each hand-copied their own version and had drifted into two camps (mixed
    stdout/stderr, header order varying); this consolidates them into one.

  ⚠️ The rule above only binds **a single gate's own criterion output**. An
  **aggregator** (`registry --run <phase>`) prints a **run report** (what didn't run /
  what went red / what had broken config), not criteria -- it goes entirely to
  **stdout**; the reasoning is in `registry._main_run`'s comment. The two semantics
  differ; don't force the same convention onto both layers (conclusion of round 16).

Pure functions stay quiet during self-proof (printing belongs to run()/top level,
issue #1 ③).
"""
import ast
import json
import os
import sys

_AST_CACHE: dict = {}   # key: file path -> parsed AST (or None)

# Root of the repo under audit: defaults to this package's parent, overridable via
# GATE_REPO (test fixtures rely on it).
GATE_REPO = os.environ.get("GATE_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def repo(*parts):
    """Join an absolute path pointing into the audited repo."""
    return os.path.join(GATE_REPO, *parts)


def repo_path(path, root=None):
    """Anchor a relative path to `root` (default: the audited repo root); absolute
    paths pass through unchanged -- the single source.

    The expression `p if os.path.isabs(p) else os.path.join(root, p)` used to be
    copied verbatim five times across check_ab / check_locks / check_pins /
    check_facts / facts (plus a variant in `i18n.pack_dir`). The absolute/relative
    boundary criterion may exist in exactly one place: if "starts with / means the
    user's absolute path" drifts in even one copy, that gate will join the user's
    absolute spec path onto the repo root and then report "file not found".
    """
    root = GATE_REPO if root is None else root
    return path if os.path.isabs(path) else os.path.join(root, path)


def zdir():
    """The **tool's own** `zreflect/` directory -- the repo-wide single source.

    Purpose: "scan my own source" (discovery-based roster / phantom knobs / code
    coverage). This is a different thing from `GATE_REPO` (the **audited** repo
    root): in a cross-repo fixture `GATE_REPO` points at a temp directory while the
    tool's source still lives in the suite.

    ⚠️ Previously `knobs._zdir()` / `registry._zdir()` / assorted
    `dirname(abspath(__file__))` calls each computed it -- equal today (by
    coincidence); changing any one would split them. A location rule deserves one
    source.
    """
    return os.path.dirname(os.path.abspath(__file__))


def tool_repo():
    """The **tool repo** root (the parent of `zreflect/`) -- the repo-wide single source.

    `i18n.pack_dir()`'s "unset => use the suite's bundled packs" anchors here.
    """
    return os.path.dirname(zdir())


def machine():
    """Lazily fetch `machine` (the machine-line protocol).

    ⚠️ **Must not be a module-level `import machine`**: `machine` needs
    `from gate import module_meta` to declare itself (a registry adoption
    requirement), so a module-level import would be circular (observed ImportError).
    Same reason as `i18n.py`'s lazy import -- a cycle can only be broken by ordering
    "who goes first", not by each side grabbing a piece inside the loop.
    """
    import machine  # noqa: PLC0415
    return machine


def require_nonempty(name, seq, what=None):
    """Zero-trust guard: if collection received nothing => error, **never treat it as
    "clean"**.

    The most important line in this package. The root cause of nearly all "a gate
    pretended to pass" incidents is this guard missing: walking a nonexistent
    directory yields an empty set, then "no violations found" -- both statements are
    true, the conclusion is wrong.

    `what` = a name for the collected thing (defaults to the language pack's
    `gate.input_label`).
    """
    import i18n  # noqa: PLC0415
    if what is None:
        what = i18n.M("gate.input_label")
    items = list(seq)
    if not items:
        # `FATAL:` is a machine-contract prefix -- a literal at the **emission
        # point** (not in the language pack). `what` may be a caller-supplied
        # Message (e.g. `M("stale.scanned_docs")`): str() it flat first, otherwise
        # the null pack renders a nested `repr(Message)`.
        fatal_exit(i18n.M("gate.require_nonempty", name=name, what=str(what)))
    return items


def guard_nonempty(name, seq, what=None):
    """The rc-returning form of `require_nonempty`: empty => print FATAL, return 2;
    non-empty => None.

    For checkers that "run directly" (they want an exit code, not an exception).
    """
    try:
        require_nonempty(name, seq, what)
        return None
    except SystemExit as e:
        print("%s" % e, file=sys.stderr)
        return 2


def off(notice):
    """Not enabled: say so explicitly + exit 0.

    ⚠️ **off and "actually ran and passed" must be distinguishable** (C2): both have
    rc 0 (off is not a failure; hooks' `|| exit` should not treat it as red), but off
    prints a machine-readable `OFF: ...` marker line on stdout -- the executor
    (`gate.run_phase`) uses it to split gates into ran / off / failed instead of
    counting "didn't run" as green. off used to print only free text on stderr, so
    "all gates green" was in reality "N passed + M never ran", invisible (observed in
    this repo: 8 of 13 gates off -- the same shape as the fake green this repo exists
    to eliminate).
    """
    print(machine().emit("off", notice))
    _maybe_hint()
    return 0


def fatal(msg):
    """Broken config / environment: FATAL + exit 2."""
    print(machine().emit("fatal", msg), file=sys.stderr)
    return 2


def fatal_exit(msg):
    """The **exiting** form of `fatal` (for call sites that cannot `return 2`).

    ⚠️ **Must be `SystemExit(2)`, not `SystemExit(msg)`**: the latter is Python's
    "print and exit 1" convention -- it prints the letters `FATAL:` while the exit
    code is **1**. Callers (`registry._record`) classify by rc: 1 = criterion red /
    failed, 2 = broken config / fatal. Those four copies of
    `raise SystemExit(machine().emit("fatal", ...))` were all misaligned here:
    **configuration accidents reported as code problems**, the fix pointing at the
    wrong file.

    Observed: `gate.selftest('x', [])` printed `FATAL: gate.selftest_empty_cases`
    with rc 1.

    One function, four call sites (`require_nonempty` / `selftest` /
    `ledger._require_pairs` / `collect.parse_prev_values`) --
    previously four hand copies, all four wrong.
    """
    print(machine().emit("fatal", msg), file=sys.stderr)
    raise SystemExit(2)


def declares_itself(path):
    """Is this `.py` one of the **suite's own** files (a module-level `MODULE =` /
    `GATE =` declaration)?

    **Single source**: the judgment "is this part of the suite or the consumer's
    code" used to be scattered across gates (`registry.modules()` recognized
    platform modules by `MODULE`, `gates()` recognized gates by `GATE`), while
    `check_lint` / `check_i18n` / `check_snapshots` did **no** check at all and
    scanned the whole repo -- auditing the consumer's `examples/` and `scripts/` as
    if they were suite code.

    Observed cost: after one real project wired in, `registry --run commit` reported
    149 ruff findings, 59 i18n findings, 3 snapshot findings, **all pointing at that
    project's own files**. The user could neither fix nor understand them -- it was
    the suite's preferences imposed on someone else.

    Criterion: the module body contains a `MODULE = ...` or `GATE = ...` assignment.
    All 36 .py files in this repo **satisfy** it (verified before making it a
    criterion), so "scan only these" never misses the suite itself.
    """
    import ast  # noqa: PLC0415
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            tree = ast.parse(fh.read())
    except (OSError, SyntaxError):
        return False
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(t, ast.Name) and t.id in ("MODULE", "GATE")
               for t in node.targets):
            return True
    return False


def suite_sources(base):
    """`(relative name, text)` of `.py` files under `base` that **belong to the suite**.

    Difference from `py_sources`: collects only files where `declares_itself()` is
    true. A user's own `measure_*.py` placed in this directory (a data module, no
    declaration) does not count as suite code.
    """
    return [(rel, src) for rel, src in py_sources(base)
            if declares_itself(os.path.join(base, rel))]


def scanned_sources(base, configured=False):
    """Which `.py` files a gate should collect -- **two scopes, split on "was the knob
    explicitly configured"**.

    **Single source**: `check_i18n.sources_for` and `check_snapshots.collect` each
    wrote the same ternary once (`py_sources if configured else suite_sources`) --
    two wordings, one criterion: exactly the "two copies that must agree" shape this
    repo dreads.

      - **Unset** (default surface = the suite itself) => `suite_sources`: audit only
        files with declarations. When wired into a real project, the consumer's
        `examples/` / `scripts/` are not the core -- observed: one real project got
        149 ruff / 59 CJK / 3 snapshot findings, all in its own files.
      - **Set** (the user points and says "audit here") => `py_sources`: take
        everything. Narrowing would make `REFLECT_I18N_ROOT=<your dir>` report a
        `scan_empty_dir` FATAL (observed), i.e. breaking opt-in.
    """
    return py_sources(base) if configured else suite_sources(base)


def py_sources(base):
    """`(filename, text)` of all `.py` under the `base` directory; unreadable => skip.

    **Single source**: this `listdir` + `open(errors="replace")` block used to be
    written out in **three** places -- `knobs._py_sources`,
    `check_snapshots.collect`, and `check_i18n`'s collection loop. All call here now.

    Unreadable => that file is skipped (not a whole-directory failure): each caller
    judges emptiness itself -- "empty" means something different to each of them
    (phantom scan: "nothing suspicious"; `used_codes`: "no codes"; `envfile`: "the
    gate is broken").

    ⚠️ `base` must be passed explicitly: upstream defaults differ (the tool repo's
    `zreflect` vs the audited repo's `zreflect`); providing a default would hide that
    difference (observed).
    """
    import os  # noqa: PLC0415
    out = []
    if not os.path.isdir(base):
        return out
    # ⚠️ **Recursive**: previously only one `listdir` level, so a common layout like
    # `REFLECT_I18N_ROOT=src` reported "the scan surface is empty" -- while the
    # directory was not empty at all (observed: in a subagent's acceptance repo,
    # `src/mycli/cli.py` plainly held a line of Chinese and the criterion saw
    # nothing). Names are **paths relative to base**: otherwise `a/util.py` and
    # `b/util.py` overwrite each other and errors cannot say which one.
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in ("__pycache__", ".git"))
        for n in sorted(filenames):
            if not n.endswith(".py"):
                continue
            p = os.path.join(dirpath, n)
            # ⚠️ **Normalize to forward slashes**: three places compare this `rel`
            # as a **filename** (`check_i18n`'s `name == "i18n.py"`, `criteria`'s
            # `name == "gate.py"`, `knobs`' phantom scan). On Windows `relpath`
            # yields `zreflect\i18n.py` => those equality checks never fire, so
            # "file-level exemptions" fail wholesale on Windows (observed: CI's
            # Windows leg classified it the same way as unregistered shell text).
            rel = os.path.relpath(p, base).replace(os.sep, "/")
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    out.append((rel, fh.read()))
            except OSError:
                continue
    return out


def resolve_spec(argv, knob, default):
    """Spec name resolution: explicit `--spec` > knob > default name. Returns
    `(name, was_explicit)`.

    A pure function; three gates (ab / locks / pins) each used to carry a
    **verbatim-identical** copy differing only in their `DEFAULT_SPEC` constants --
    three copies destined to drift (C4). Those sites now just pass their own default
    name in.

    Explicitly specified (argv / knob) but the file is missing => the caller must
    FATAL (a configured-but-absent spec is in the "deployed != running" family;
    silently treating it as "not enabled" hides broken config);
    default name absent => not enabled, exit 0.
    """
    for i, a in enumerate(argv):
        if a == "--spec":
            return argv[i + 1], True
    k = (knob or "").strip()
    if k:
        return k, True
    return default, False


def load_spec(path):
    """Read a JSON spec, returning (spec, error message). Error message non-None => the
    caller calls `fatal()`.

    Returns the error instead of raising: the caller needs to weave its own knob
    name / path into its FATAL wording.
    """
    import i18n  # noqa: PLC0415
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, ValueError) as e:
        return None, i18n.M("gate.spec_unreadable", path=path, error=e)


def finish(name, problems, ok):
    """The problem loop + the OK line -- the single source of the rc contract
    (1 = problems found / 0 = green)."""
    import i18n  # noqa: PLC0415
    if problems:
        print(i18n.M("gate.problems_header",
                     name=name, count=len(problems)), file=sys.stderr)
        for p in problems:
            print("  · " + p, file=sys.stderr)
            # The **consumer** of `.forged`: rendering neutralized forged lines
            # (didn't reject them), but "neutralized" must be **visible** --
            # otherwise nobody ever learns a filename contained a newline and the
            # user sees only a strange `\OFF:`. Say it in one line; don't flood.
            forged = getattr(p, "forged", ())
            if forged:
                print("  " + i18n.M("gate.forged_row_neutralised",
                                    count=len(forged)), file=sys.stderr)
        _maybe_hint()
        return 1
    print(ok)
    _maybe_hint()
    return 0


def _env_hint_off():
    """Is `REFLECT_ENV_HINT` explicitly off -- goes through `knobs.flag` (the single
    source of the flag vocabulary).

    ⚠️ This used to be `.lower() == "off"`: a **second flag vocabulary** next to
    `doc.accepts_principles`'s `("1","true","yes")` (the latter case-sensitive;
    observed: `TRUE` didn't take effect). Now unified through `knobs.flag`.
    """
    import knobs  # noqa: PLC0415
    return knobs.flag("REFLECT_ENV_HINT") is False


def _maybe_hint():
    """Print the env hint to stderr (**never stdout** -- that stream carries the
    machine contract).

    `REFLECT_ENV_HINT=off` disables it entirely (the exit for repos that "don't like
    hints"; the hint itself is **human courtesy**, not a criterion).
    """
    if _env_hint_off():
        return
    h = env_hint()
    if h:
        print("ℹ %s" % h, file=sys.stderr)


def env_carrier():
    """The repo's Einfacht.env carrier path (hooks dir first, repo root second); none => None."""
    name = (os.environ.get("REFLECT_ENV_FILE", "Einfacht.env").strip()
            or "Einfacht.env")
    for d in (repo("reflect-hooks"), repo()):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def gate_knobs(module=None):
    """The caller module's declared `GATE = meta(..., knobs=...)` (unavailable => empty).

    Lets `env_hint()` avoid hand-writing knob names at every entry -- the declaration
    already holds one copy (single source).
    """
    import sys as _sys  # noqa: PLC0415
    mod = module if module is not None else _sys.modules.get("__main__")
    decl = getattr(mod, "GATE", None)
    if isinstance(decl, dict):
        return tuple(decl.get("knobs") or ())
    return ()


def env_hint(consumed=(), module=None):
    """**Human courtesy hint**: for env-fed entries, how to run when "env was provided
    but didn't take effect".

    `consumed` = the knob names this entry actually reads (e.g. `("REFLECT_FACTS",)`).
    Returns a one-line hint string, or None (no hint needed).

    When to hint (three classes, each only when **helpful** to the user):

      1. The repo **has** an Einfacht.env but this process **set none of the knobs**
         (none of `consumed` is in the environment) -- the classic bare manual run:
         `python3 zreflect/check_x.py` => criteria all fall back to default names,
         results may differ from the hook context, and **nothing tells the user**
         (issue #20② / #15 both tripped here).
      2. The repo **has** an Einfacht.env and current settings **disagree** with it?
         -- Not checked (judging requires comparing values, and values depend on
         shell semantics); only "is it set" is checked, keeping the criterion cheap
         and reliable.
      3. The repo **has no** Einfacht.env => **no hint** (bare runs are normal usage
         for such repos; a hint would just be noise -- this repo's lesson that "a
         gate with false positives eventually gets switched off entirely").

    The hint wording lives here (one place), and every entry calls it -- no more
    per-entry copies.
    """
    carrier = env_carrier()
    if not carrier:
        return None                      # repo without a carrier: bare runs are normal usage, don't nag
    if not consumed:
        consumed = gate_knobs(module)     # the declared knob list (zero hand-writing)
    if not consumed:
        return None
    # ⚠️ **"Knob is set" must not be silently accepted across the board** (#28): the
    # hook system relies on sourcing the carrier to put knobs into the environment
    # -- in a correctly wired repo "knobs are in the environment" is always true, so
    # the original fourth tier (carrier present but knobs unset => hint) was
    # unreachable in any normally wired repo.
    # Four-tier semantics (one carrier comparison; costs one file read):
    #   1. No carrier => silent (bare runs are normal usage)
    #   2. None of the consumed knobs set => **hint** (carrier present, but nobody
    #      sourced / exported)
    #   3. Knobs set and values **match** the carrier => carrier is in effect, silent
    #   4. Knobs set but values **differ** from the carrier (or the carrier doesn't
    #      mention them) => **hint** (manual exports can drift -- exactly the scene
    #      worth nagging about)
    import check_envfile  # noqa: PLC0415
    try:
        with open(carrier, encoding="utf-8", errors="replace") as fh:
            exported = check_envfile.parse_exports(fh.read())
    except OSError:
        exported = {}                    # carrier unreadable: treat as "not written" (record in guard)
    set_kv = {k: os.environ[k].strip() for k in consumed
              if os.environ.get(k, "").strip()}
    if not set_kv:
        # Tier 2: carrier present, but not a single knob set => the original hint scene
        rel = os.path.relpath(carrier, GATE_REPO)
        import i18n  # noqa: PLC0415
        return i18n.M("gate.env_hint", file=rel)
    if all(exported.get(k) == v for k, v in set_kv.items()):
        return None                      # Tier 3: carrier is in effect, silent
    # Tier 4: at least one knob manually exported and differing from the carrier
    # (or absent from it)
    rel = os.path.relpath(carrier, GATE_REPO)
    import i18n  # noqa: PLC0415
    return i18n.M("gate.env_hint", file=rel)


def meta(name, desc, knobs=(), name_dependent=False, runs_at="commit",
         off_reason=None):
    """Gate declaration line (registry's ast extraction target): name + one sentence +
    consumed knobs.

    Declaring is registering -- a hand-written roster drifts; only facts may be
    written here.

    - `name_dependent=True` marks gates whose "default input gets renamed by the
      rename selftest" (the batch that must go red in gates-selftest's cross-repo
      section): marked gates are caught from both ends -- the fixture demands they
      really go red, and registry.problems demands they really consume the renamed
      default name.
    - `runs_at` (C1) **declares the frequency positively**: `"commit"` (run on every
      commit; wired into hooks / CI) or `"start-of-work"` (run manually before
      starting work -- the doctor kind of "checks things that could be dead";
      hanging it on pre-commit is the wrong frequency). Previously frequency could
      only be expressed by the **accident of negative naming** ("the file isn't named
      check_"), and the executor's glob knew nothing of it => renaming would turn
      doctor into a per-commit probe of live processes with nothing to stop it. Now
      frequency is a field in the declaration and the executor (gate.run_phase)
      filters on it -- the name is no longer load-bearing.

    registry derives from these declarations: the execution list (filtered by
    runs_at), narration (AUTO:GATES), the red list, the selftest list. Names only
    serve the `check_*.py` file convention (descriptive); they carry no semantics.
    """
    return {"name": name, "desc": desc, "knobs": tuple(knobs),
            "name_dependent": bool(name_dependent),
            "runs_at": str(runs_at),
            # `off_reason` (round 12): **why** this gate would be not-enabled. Any
            # gate that can call `off()` must state it -- otherwise "off" has no
            # reason, and "a permanently off gate" is indistinguishable from "this
            # repo doesn't use that mechanism" (this repo really did have 8 of 13
            # gates off while "all green" hid it). The reason must be >= 8 chars
            # (same discipline as `PINNED:`).
            "off_reason": (None if off_reason is None else str(off_reason))}


def module_meta(name, desc, selftest=True):
    """Platform module declaration line (C5): registry's ast extraction target.

    Gates declare with `GATE = meta(...)`; **platform modules** (gate / runner /
    knobs / registry / guard / ledger / render / facts ...) declare their existence
    and "whether they owe a selftest" with `MODULE = module_meta(...)`. Previously
    "should have a selftest" could only be **guessed from text** (scanning for
    `_cases` literals) -- nobody asked when a module owed a selftest but had none;
    now it is a field in the declaration: `selftest=True` => registry demands it
    actually supports `--selftest` and is actually run.
    """
    return {"name": name, "desc": desc, "selftest": bool(selftest)}


def raises(fn):
    """"What should raise must raise" -- for reverse assertions. True means it did
    raise SystemExit."""
    try:
        fn()
    except SystemExit:
        return True
    return False



def _ast_for(fname):
    """Whole-file AST (cached by filename). Unreadable / unparseable => False (negative results are cached)."""
    import ast as _ast  # noqa: PLC0415
    import linecache  # noqa: PLC0415
    tree = _AST_CACHE.get((fname,))
    if tree is not None:
        return tree
    try:
        tree = _ast.parse("".join(linecache.getlines(fname)))
    except (OSError, SyntaxError):
        tree = False
    _AST_CACHE[(fname,)] = tree
    return tree


def _lambda_nodes(tree, lineno):
    """**All** Lambda nodes whose starting line == lineno (ascending by col_offset).

    ⚠️ Why a list rather than a single node: **one line can hold several lambdas**
    (`return [("a", lambda: ...), ("b", lambda: ...)]` all on one line) -- then the
    code objects share `co_firstlineno` and `co_positions()` only gives the outer
    position, so there is **no way to tell which one**. Taking the smallest
    col_offset would judge every other same-line assertion by the first one
    (observed: `lambda: 1 == 2` was dragged into always-true by a same-line
    `lambda: ... or True`).

    So return all candidates on the line; the caller scans **each** of them, and any
    always-true one reports -- "any assertion on the line is always-true" deserves to
    be caught anyway; over-reporting here is not a false positive.
    """
    import ast as _ast  # noqa: PLC0415
    nodes = [n for n in _ast.walk(tree)
             if isinstance(n, _ast.Lambda) and n.lineno == lineno]
    return sorted(nodes, key=lambda n: n.col_offset)


def _const_truthy(node):
    """Is this constant node always truthy (the right-operand shape of `or True` / `or 1`)?"""
    import ast as _ast  # noqa: PLC0415
    if not isinstance(node, _ast.Constant) or node.value is None:
        return False
    return node.value is not False and bool(node.value) is True


def _const_falsy(node):
    """Is this constant node always falsy (the right-operand shape of `and False` / `and 0`)?"""
    import ast as _ast  # noqa: PLC0415
    if not isinstance(node, _ast.Constant) or node.value is None:
        return False
    return node.value is False or node.value == 0


def _short_circuit_reason(node):
    """Does this AST node constitute an always-true short circuit => reason message; else None."""
    import ast as _ast  # noqa: PLC0415

    import i18n  # noqa: PLC0415
    if isinstance(node, _ast.BoolOp):
        if isinstance(node.op, _ast.Or) and any(
                _const_truthy(o) for o in node.values):
            return i18n.M("gate.never_falsifiable_or")
        if isinstance(node.op, _ast.And) and any(
                _const_falsy(o) for o in node.values):
            return i18n.M("gate.never_falsifiable_and")
    if isinstance(node, _ast.Compare) and len(node.comparators) == 1:
        left, right = node.left, node.comparators[0]
        # Exclude the **legitimate** purity check of calling a bare function twice
        # (`render_gates(gs) == render_gates(gs)` proves render determinism).
        if isinstance(left, _ast.Call) and isinstance(right, _ast.Call):
            return None
        if _ast.dump(left) == _ast.dump(right) and isinstance(
                node.ops[0], (_ast.Eq, _ast.LtE, _ast.GtE)):
            return i18n.M("gate.never_falsifiable_self_compare")
    return None


# Builtin whitelist: they **inline logic inside the lambda** rather than delegate --
# the generator/arguments are right there in the AST, so always-true detection can
# still scan them (classifying builtins as delegation would false-positive half the
# assertions; observed: 6 false positives).
_BUILTIN_OK = frozenset({
    "any", "all", "bool", "len", "sorted", "sum", "min", "max",
    "isinstance", "getattr", "hasattr", "str", "int", "set",
    "list", "tuple", "dict", "repr",
})


def _assertion_node(fn):
    """Locate the lambda AST node(s) for this assertion. Unlocatable => `[]` (no guessing)."""
    code = getattr(fn, "__code__", None)
    if code is None:
        return []                                        # not a Python function
    tree = _ast_for(code.co_filename)
    if not tree:
        return []                                        # unreadable / unparseable
    return _lambda_nodes(tree, code.co_firstlineno)


def _delegation_reason(nodes):
    """**Pure delegation** (the lambda body is a single non-builtin Call) => the
    assertion logic lives inside the called function, invisible to this criterion.

    ⚠️ This used to return None (indistinguishable from "scanned and clean"), so
    "extract into a helper" became a legitimate way to switch off always-true
    detection (observed: after a helper was changed to `return True`, the selftest
    went 26 PASS / 0 FAIL all green). It is now **declared explicitly as unaudited**
    -- the same discipline as "say so when unreadable".
    """
    import i18n  # noqa: PLC0415
    for node in nodes:
        if isinstance(node.body, ast.Call):
            f = node.body.func
            fname = getattr(f, "id", None) or getattr(f, "attr", None)
            if fname not in _BUILTIN_OK:
                return i18n.M("gate.never_falsifiable_delegated")
    return None


def _short_circuit_reason_of(nodes):
    """Scan for always-true short circuits: `or <truthy constant>` / `and <falsy
    constant>` / `x == x`."""
    for node in nodes:
        for n in ast.walk(node):
            reason = _short_circuit_reason(n)
            if reason:
                return reason
    return None


def never_falsifiable(fn):
    """**Always-true assertion detection** (issue #23): does this selftest case have
    falsification power?

    The incident observed downstream: an `or True` assertion was forever PASS in
    `--selftest` -- `gates-selftest` judges "returned 0 + printed a summary line", on
    which a real assertion and an always-true assertion are completely isomorphic.
    `AGENTS.md` discipline 4 says "assertions must be falsifiable", but there was no
    machine criterion for it.

    Criterion (AST; zero execution, zero side effects): **parse the whole file +
    locate** lambda nodes by co_firstlineno (not inspect.getsourcelines -- for a
    lambda inside a list it only gives the first line, reconstruction is fragile;
    observed blind three times). Once nodes are found, scan for always-true short
    circuits:

      - `or <truthy constant>` / `and <falsy constant>` -- the boolean is short-
        circuited by a constant, forever PASS/fail;
      - `x == x`-style self-comparison (**excluding** the legitimate purity check of
        calling a bare function twice).

    Returns a reason string (unfalsifiable) or None (looks like it has teeth).

    ## Three honest boundaries (documented gaps; do not treat as full coverage)

    1. **More subtle always-true forms are not caught** (same variable, different
       spelling). The static shape criterion only recognizes explicit short circuits
       and self-comparisons; the stronger guarantee is mutation testing (inject a
       breaker into every assertion) -- too costly; see the issue #23 discussion.
       This criterion's value: it turns several known unconscious spellings from
       "found in manual review" into "selftest goes red on the spot".
    2. **"Delegation" is only reported when the body is a** single `Call`** (see
       `_delegation_reason`). If the body is a `Compare`/`BoolOp` wrapping one
       helper call -- e.g. `lambda: _nf_catches("x") is not None` -- it **does not
       count as delegation**, and this criterion cannot see inside the helper.
       Observed: in round 22 I wrote `never_falsifiable`'s own selftest in that
       shape; the four assertions did have teeth semantically (mutation test
       RED-OK) but **formally** dodged the audit. Loosening the criterion would
       false-positive many "compound assertions", so the choice here is to **state
       the gap** rather than widen the net.
    3. **When the source file is unreadable, don't guess** (a lambda from `-c` has no
       `co_filename` => returns None). Selftest cases must live in real files --
       learned while adding `never_falsifiable`'s selftest in round 22 (testing it
       inside `python -c` always yields None).

    The three stages are each a named helper (locate / delegate / short-circuit):
    independent of each other; merged, 73 lines with the three "no guessing" exits
    scattered in the middle.
    """
    nodes = _assertion_node(fn)
    if not nodes:
        return None                                      # unlocatable => no guessing
    if len(nodes) > 1:
        # Several lambdas on one line: the code object cannot tell us which one
        # (same co_firstlineno, co_positions only gives the outer position).
        # **When unsure, don't guess** -- prefer under-reporting over false
        # positives (99% of this repo's assertions own their line).
        return None
    return _delegation_reason(nodes) or _short_circuit_reason_of(nodes)


def _is_delegated(why):
    """Is this `why` the "delegated assertion" criterion (rather than an always-true
    short circuit)?

    ⚠️ Must look at `.code`, never `str(why)`: `why` is a `Message` whose str value
    has already been rendered **in the current language** -- under `zh` it becomes
    Chinese, matching against the English code never hits, and a delegated assertion
    gets reported as an always-true short circuit (observed: `KeyError: 'label'`).
    """
    return getattr(why, "code", None) == "gate.never_falsifiable_delegated"


def _run_safely(label, fn):
    """Run the assertion body. Returns `(passed?, failure line or None)`. **Exceptions
    must not escape**.

    `SystemExit` is caught separately: selftest assertions like `raises(...)`
    deliberately raise -- that is the behavior under test, not a selftest failure;
    but if it truly leaks to this layer, the case was written wrong.
    """
    import i18n  # noqa: PLC0415
    try:
        return bool(fn()), None
    except SystemExit as e:
        return False, i18n.M("gate.case_unexpected_systemexit",
                             label=label, error=e)
    except Exception as e:                      # noqa: BLE001
        return False, i18n.M("gate.case_raised", label=label, error=e)


def _case_verdict(label, fn):
    """Run one case. Returns `(passed?, delegated?, failure line or None)`.

    ⚠️ **Always-true assertion detection** (issue #23): an `or True` assertion and a
    real assertion are isomorphic on the "returned 0 + printed a summary line"
    surface and must be judged separately.

    ⚠️ **"Delegated" is acceptable but must be visible**: the assertion body lives in
    a helper (scenarios building temp fixtures cannot inline it). Allowed, but
    printed as `note |` (machine-readable) and counted separately in the summary --
    never silently treated as clean (it used to return None, indistinguishable from
    "scanned and clean", so extracting a helper became a legitimate way to switch off
    always-true detection).

    ⚠️ **Delegated cases still run**: the delegated branch used to `return True`
    directly, so assertions delegated to helpers **never executed** and `False` was
    isomorphic to `True` (observed: after `_utf8_forced_case`'s fix was gutted it
    returned False, yet the selftest still reported "19 PASS / 0 FAIL"). "Acceptable
    but visible" means the always-true detection **cannot see its insides**, not
    "don't run it".

    The three stages (always-true judgment / delegated branch / normal execution) are
    each one place: after extracting "execution + exceptions", only dispatch remains.
    """
    import i18n  # noqa: PLC0415
    why = never_falsifiable(fn)
    if why and _is_delegated(why):
        passed, failure = _run_safely(label, fn)
        return passed, True, failure
    if why:
        # `fail | ` is the selftest machine-line prefix -- an emission-point literal,
        # not in the language pack
        return False, False, i18n.M("gate.case_unfalsifiable",
                                    label=label, why=why)
    passed, failure = _run_safely(label, fn)
    return passed, False, failure


def _print_banner(name, total, bad, delegated):
    """The summary's three lines: delegated count (listed separately) / human summary /
    machine summary line.

    ⚠️ Delegated is **listed separately** in the summary: it is not a failure, but it
    is also not "scanned and clean" -- silently counting it into PASS is the fake
    green this repo hates most.

    ⚠️ The machine summary line (issue #3 ③) is independent of the checker name and
    has a fixed format; runner/CI grep it directly. The `=== ` prefix and trailing
    ` ===` are emission-point literals (language pack values must not start with
    `^===`).
    """
    import i18n  # noqa: PLC0415
    if delegated:
        print(machine().emit("human_summary",
                           i18n.M("gate.selftest_delegated",
                                  name=name, count=delegated)))
    print(machine().emit("human_summary",
                       i18n.M("gate.selftest_summary",
                              name=name, passed=total - bad, failed=bad)))
    print(machine().emit_summary(total - bad, bad))


def _report_one(label, fn):
    """Run one case and **report its outcome on the spot**. Returns `(passed?,
    delegated?, failure line or None)`.

    The four outcomes each have an output path, but "how to report" and "whether to
    report" must stay separate:

      - delegated + passed  -> `note | ... | delegated`
      - delegated + failed  -> **`fail | ...`** (this used to `continue`, discarding
        the result entirely)
      - always-true / exception -> `fail | <reason>`
      - normal              -> `PASS | ...` or `fail | ...`
    """
    passed, was_delegated, failure = _case_verdict(label, fn)
    if was_delegated:
        print(machine().emit("note", "%s | delegated" % label))
        if not passed:
            print(machine().emit("fail", label))
        return passed, True, None
    if failure is not None:
        print(machine().emit("fail", failure))
        return False, False, failure
    # The pass line is `PASS | `, the failure line is `fail | ` -- two kinds, one table
    print(machine().emit("pass" if passed else "fail", label))
    return passed, False, None


def selftest(name, cases):
    """Run the three tiers of cases. Each case = (label, callable) -> bool.

    All three classes must be present:
      (1) normal runs don't report (positive control -- otherwise "always errors"
          can fool the selftest too)
      (2) what should report does report (reverse assertion -- otherwise this
          checker may be decoration)
      (3) empty input reports (zero-trust guard)

    The three layers are each a named helper (per-case verdict `_case_verdict` /
    per-case output `_report_one` / summary `_print_banner`): this function only
    accumulates counts.
    """
    import i18n  # noqa: PLC0415
    if not cases:
        # The 0/0 hole (the third incident recorded at the top of this file): a
        # selftest with an empty case list checks nothing, prints "0 PASS / 0 FAIL",
        # and exits green -- the runner's grep still accepts it. An empty list is a
        # shape error in writing the selftest; sound on the spot, never green.
        fatal_exit(i18n.M("gate.selftest_empty_cases", name=name))
    bad = delegated = 0
    for label, fn in cases:
        ok, was_delegated, _failure = _report_one(label, fn)
        delegated += 1 if was_delegated else 0
        bad += 0 if ok else 1
    _print_banner(name, len(cases), bad, delegated)
    return 1 if bad else 0


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8 (**mandatory on Windows**).

    Why: on Windows `sys.stdout.encoding` defaults to `cp1252` (the code page), while
    this repo prints **gate names and descriptions** (`GATE = meta("A/B gate", ...)`).
    Observed:

        UnicodeEncodeError: 'charmap' codec can't encode characters
                            in position 25-26: character maps to <undefined>

    -- one `registry.py --gates` could turn the CI Windows leg red wholesale, and it
    never reproduces on Linux (UTF-8 is the default there).

    ⚠️ Only done on streams that **really support reconfigure** (`io.StringIO` /
    redirected custom streams lack the method); on failure, skip silently -- this is
    not a criterion, it is environment adaptation. The side effect is **global**
    (it mutates `sys.stdout`), so it is only called at CLI entries:
    `activate_or_fatal` happens to be the mandatory pass-through for all of them.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            continue                # already closed / unsupported -- no guessing


def activate_or_fatal(lang=None):
    """The process-level language-pack activation point. Returns 0 on success; on
    assembly failure prints FATAL and returns 2.

    `lang` lets **one process** assemble a specific pack (unset = read
    `REFLECT_LANG`). Reason it exists: some entries serve consumers other than gates
    -- e.g. a consumer wraps a layer to feed some output to humans; that layer can
    name its own language while the suite's gates keep honoring only `REFLECT_LANG`.
    **"Affects only that one process" is therefore structural**, not dependent on
    someone remembering to behave; the suite gains no extra knob for it.

    **Must be called before `--selftest` dispatch** (issue #26 retrospective):
    `main_selftest_or` used to test `--selftest` before `activate()`, so
    `REFLECT_LANG=zh <gate> --selftest` rendered messages as bare codes via the null
    pack, while `REFLECT_LANG=de <gate> --selftest` **silently rc=0 on a nonexistent
    pack** -- directly contradicting "set but pack missing => FATAL rc 2, never a
    silent fallback" (observed: all four entries -- render / ledger / runner /
    registry -- were hit).

    It became a function so that **entries not going through `main_selftest_or`**
    (render/ledger's `_selftest()`, registry's `__main__`, gate's own `__main__`)
    need not each copy an activate+FATAL pair (registry had a copy; gate's own copy
    had no FATAL at all -- a bare traceback exiting 1).
    """
    import i18n  # noqa: PLC0415

    _force_utf8_streams()
    try:
        i18n.activate(lang)
    except Exception as e:                               # noqa: BLE001
        # On assembly failure the process still holds the previous-tier `Catalog`
        # (usually the null pack) => M() still renders (`MissingPack`'s `str()` is
        # itself a null-shaped code).
        print(machine().emit("fatal",
                           i18n.M("gate.pack_assembly_failed", error=e)),
              file=sys.stderr)
        return 2
    return 0


def main_selftest_or(args, name, cases, run):
    """`--selftest` runs the selftest; otherwise `run(args)`. Every checker ends with
    this.

    `cases` can be a list or a **factory callable** (selftests that need to build a
    temp fixture -- the ab/locks/pins style -- pass a function, invoked here).

    **This is the language pack's process-level activation point** (issue #26):
    `REFLECT_LANG` unset => null pack (the core speaks no language); set but the pack
    is missing => `MissingPack` => FATAL rc 2 (no "fall back if not installed").
    Every gate passes through here => one wiring, everyone benefits. Activation
    happens **before** the `--selftest` dispatch; reasoning in `activate_or_fatal`.
    """
    rc = activate_or_fatal()
    if rc:
        return rc
    if "--selftest" in args:
        return selftest(name, cases() if callable(cases) else cases)
    return run([a for a in args if a != "--selftest"])


def default_runner(f, repo_root=None):
    """The default runner: executes one gate file, returns `(rc, merged output)`.

    ⚠️ **stdout and stderr must be merged**: this repo's convention is "problem lines
    all on stderr", so a gate with rc=2 can have **empty** stdout (the reason is all
    on stderr). Returning only `p.stdout` => the aggregator gets (2, ""), knowing
    neither which file broke nor why (observed:
    `REFLECT_SNAPSHOT_ROOT=/nonexistent` => stdout='').
    """
    import subprocess  # noqa: PLC0415
    p = subprocess.run([sys.executable, f], capture_output=True, text=True,
                       cwd=repo_root or GATE_REPO,
                           encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _empty_result():
    """The initial shape of the aggregate result. `fail_out` keeps **each failed
    gate's raw output**.

    ⚠️ When the aggregator prints only filenames, users must re-run the gate
    themselves to learn why it went red (observed: the hook reported only
    `FAILED check_facts.py`, while running it directly showed
    `facts.bare_number_unaccounted(line=9, ...)`).
    """
    return {"ran": 0, "off": 0, "failed": 0, "fatal": 0, "error": 0,
            "off_list": [], "fail_list": [], "fatal_list": [], "error_list": [],
            "fail_out": {}}


def _record(res, f, rc, out):
    """Classify one gate into one of five tiers by rc and the `OFF:` marker.

    The five tiers are **non-overlapping fix categories**:

      rc=2   broken config / environment -> fix the config
      rc<0   killed by a signal
      rc>2   an uncontracted code was used -> broken at the executor level
      rc=1   criterion red               -> fix the problems
      rc=0 + `OFF:` marker           -> not enabled (not a pass)
      rc=0 clean                     -> ran and passed

    ⚠️ rc<0 / rc>2 are listed separately as `error`: they used to be lumped into
    `failed`, making "the gate reported a problem" indistinguishable from "the gate
    was SIGKILLed" (review observed rc=3 / rc=-9 both landing in failed).
    """
    if rc == 2:
        res["fatal"] += 1
        res["fatal_list"].append(f)
    elif rc < 0 or rc > 2:
        res["error"] += 1
        res["error_list"].append(f)
    elif rc != 0:
        res["failed"] += 1
        res["fail_list"].append(f)
        res["fail_out"][f] = out or ""
    elif any(kind == "off" for _i, kind, _ln in machine().scan(out)):
        res["off"] += 1
        res["off_list"].append(f)
    else:
        res["ran"] += 1


def run_phase(phase, gates, runner=None, repo_root=None):
    """Run a group of gates by phase and **aggregate ran / off / failed** (the
    executor side of C1+C2).

    This is the **single execution entry** for hooks / CI / runner -- replacing the
    `for g in zreflect/check_*.py` glob previously scattered across 6 sites.
    `gates` = registry-derived (file, runs_at) list (the caller filters by `phase`,
    or passes everything and this filters).

    Why aggregate three tiers instead of only reading rc: off and "ran and passed"
    both have rc 0; reading only rc counts "didn't run" as green (observed in this
    repo: 8 of 13 gates off). This reads the `OFF:` machine marker from the child
    process's stdout to list off separately, so "all green" always carries "N of them
    off (not checked)". `runner` is injectable (selftests use a fake executor).

    Returns `{ran, off, failed, fatal, off_list, fail_list, fatal_list}`.

    The classification logic lives in `_record` (five non-overlapping tiers; see its
    docstring): this function only filters and iterates.
    """
    run = runner or (lambda f: default_runner(f, repo_root))
    res = _empty_result()
    for item in gates:
        f = item["file"] if isinstance(item, dict) else item
        if isinstance(item, dict) and item.get("runs_at") not in (None, phase):
            continue
        rc, out = run(f)
        _record(res, f, rc, out)
    return res


# The **real meaning** of `selftest=False`: this module **has no `--selftest`
# entry** (it provides `selftest()` itself; bootstrapping both would collide).
# **This does not mean its logic has no self-proof** -- its logic lives in
# `registry._cases()`: `finish` / `meta` / `run_phase` / `default_runner` / `zdir` /
# `tool_repo` / `never_falsifiable` (via `_nf_catches`) all have substantive
# assertions. The description used to say only "provides selftest, doesn't consume
# it itself" -- which reads like "no selftest obligation", contradicting the facts
# (aligned in round 23).
MODULE = module_meta(
    "gate platform",
    "rc contract + zero-trust guards + three-tier self-proof + phase executor "
    "(no --selftest entry: bootstrapping would collide; "
    "logic self-proof lives in registry._cases)",
    selftest=False)


if __name__ == "__main__":
    import i18n  # noqa: PLC0415
    # This used to be a bare `i18n.activate()`: pack missing => MissingPack
    # **traceback rc=1** instead of the rc contract's FATAL rc=2 (observed). Goes
    # through the same activation entry now.
    rc = activate_or_fatal()
    if rc:
        sys.exit(rc)
    print(i18n.M("gate.platform_root", root=GATE_REPO))
    print(i18n.M("gate.platform_usage"))
    sys.exit(0)
