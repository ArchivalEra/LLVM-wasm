#!/usr/bin/env python3
"""Module-level snapshot gate (**pluggable module**, deepening round 5).

It guards a pit that was stepped on **three times**:

    from gate import GATE_REPO        # <- value copy, frozen at this moment
    ...
    gate.GATE_REPO = other_repo       # <- changed later; the copy above never knows
    subprocess.run(..., cwd=GATE_REPO)  # <- still using the old repo

`from X import CONST` in Python is a **value copy**, not a reference. If `CONST`
gets reassigned afterwards (`gate.GATE_REPO` is exactly that; any fixture may
reassign it), every copy becomes a **stale snapshot** -- and it fails silently:
no error, no exception, just quietly reading the wrong repo.

This repo actually hit it three times:

  1. `i18n.pack_dir()` resolved relative to GATE_REPO => in cross-repo fixtures
     the loader could not find the language packs (0/15 all red)
  2. `knobs.installed_langs()`, same class of bug
  3. `check_envfile`'s self-proof tried to change `os.environ["GATE_REPO"]` and
     found it had no effect (`repo()` reads a module-level variable, not an
     environment variable)

The third is the most typical: **the author assumed changing the environment
variable would suffice**, because "this value was fixed at import time" is
invisible. This gate turns that hidden coupling into something decidable.

## Criterion (AST, zero execution)

For every `from <local module> import <UPPER_NAME>` in `zreflect/*.py`:

  - if `<UPPER_NAME>` is a **module-level assignable name in the source module**
    (and not a function / constant data), and the importer **uses it on a live
    path** => report.

"Module-level assignable" means: the source module has a top-level
`NAME = ...` assignment, and the name is **not** frozen data (something like
`REGISTRY`, constructed once at import and never touched again).

Honest boundaries (**three, all explicitly written gaps**):

  1. A static criterion only sees "who imports a mutable global"; it **cannot
     tell** whether the reassignment ever actually happens at runtime. So what
     it reports is a **risk shape**, not an incident that occurred.
  2. **Class attributes are not reported**: `class C: OUT = repo(...)` freezes
     at import just the same, but the criterion only collects **module-level**
     `ast.Assign` / `ast.AnnAssign`. Trade-off rationale: a class attribute is
     "part of the class definition", read as `C.OUT`, and semantically less
     likely than a module-level constant to be treated as global config and
     spread around; moreover the real repo currently has no such pattern
     (verified: 0 occurrences in a scan). If one appears, add a criterion here
     rather than loosen it -- for now we **do not pretend to cover it**.
  3. Assignments made by modules **outside** the scan set (e.g. a script in
     `tools/` changing `gate.GATE_REPO`) are invisible. The scan surface is
     defined by `REFLECT_SNAPSHOT_ROOT`; that is the design boundary of a
     pluggable gate.

The fix is always the same: switch to `import gate` + `gate.GATE_REPO`
(read the attribute every time; do not copy).
"""
from __future__ import annotations

import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate  # noqa: E402
from gate import fatal, finish, main_selftest_or, meta  # noqa: E402
from i18n import M  # noqa: E402

# ⚠️ The default value is **not empty**: this gate guards the repo's own code
# (`zreflect/*.py`), so it should be on by default for every repo where
# Einfacht lands. Previously the default was empty => nobody configured the
# knob => in a live `registry --run commit` it was forever `off` (verified:
# configured in none of CI / hook / self-proof). "The gate exists, its
# self-proof is green, but it never runs" is exactly the fake green this repo
# exists to eliminate.
KNOB = "REFLECT_SNAPSHOT_ROOT"
# The default scan surface is no longer stored here: knob unset => anchor at
# `gate.zdir()` (the tool repo's own zreflect/, independent of cwd). There used
# to be a bare relative `DEFAULT_ROOT = "zreflect"`; once the criterion
# re-anchored to the tool repo it became a dead default (caught by
# knobs.dead_default) -- deleted. # ⚠️ **No more hand-written roster**. This used to be a hardcoded tuple of
# module names (`("gate", "knobs", ...)`), violating the AGENTS rule "a
# hand-written roster always drifts": of the 28 `zreflect/*.py` files in the
# repo only 12 were listed, and the other 16 (all `check_*.py`) were completely
# invisible to the criterion **as imported sources**. It is now **discovery
# based**: every `.py` in the scan surface is a candidate source module --
# the roster is the scan surface itself. (Third-party libraries are not
# mis-collected: only `from X import ...` with X inside the scan surface.)


def _module_level_assigns(tree):
    """Names assigned at module top level (`NAME = ...` / `NAME: T = ...`)."""
    out = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
    return out


def _aliases_of(trees, src_mod):
    """Aliases bound by `import <src_mod> as <alias>` in the scan surface (used by `_reassigned_elsewhere`)."""
    return {a.asname for tree in trees.values()
            for node in ast.walk(tree) if isinstance(node, ast.Import)
            for a in node.names if a.name == src_mod and a.asname}


def _import_aliases(trees):
    """`import <mod> as <alias>` => `{alias: mod}` (the alias also points at that module)."""
    aliases = {}
    for _m, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.asname:
                        aliases[a.asname] = a.name
    return aliases


def _assign_targets(node):
    """All targets written by an assignment-like node (`Assign` / `AnnAssign` / `AugAssign`)."""
    if isinstance(node, ast.Assign):
        return node.targets
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return [node.target]
    return []


def _attribute_mutations(tree, aliases):
    """Shape 1: `<src_mod>.<name> = ...` or `<alias>.<name> = ...`."""
    out = set()
    for node in ast.walk(tree):
        for t in _assign_targets(node):
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name):
                owner = t.value.id
                out.add((aliases.get(owner, owner), t.attr))
    return out


def _module_global_mutations(tree, module):
    """Shape 2: the module itself reassigns via `global NAME` (rewrite within the same module)."""
    globs = _globals_of(tree)
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AugAssign)):
            continue
        for t in _assign_targets(node):
            if isinstance(t, ast.Name) and t.id in globs:
                out.add((module, t.id))
    return out


def _mutated_globals(trees):
    """One-time index: which `(module, name)` pairs get assigned by others at runtime.

    ⚠️ Previously `_reassigned_elsewhere(trees, src_mod, name)` re-ran
    `ast.walk` over all modules **for every candidate name** -- 115 names x
    28 modules' ASTs => 6.3 seconds (measured: 97% of the gate's total 6.5s).
    Build the index once; lookups are O(1).

    The key shape of the criterion: not "how many times the source module
    itself assigns it" (`gate.GATE_REPO` is assigned once), but "**will others
    reassign it**" -- the self-proofs of `check_envfile` / `i18n` both do
    `gate.GATE_REPO = ...`. A constant assigned once and rewritten by nobody
    (`REGISTRY`) is not reported -- its semantics is "a data table", where
    copy and reference are indistinguishable.

    Each shape gets a named helper (cross-module attribute assignment /
    within-module global rewrite): merged into one function, the two nesting
    levels plus isinstance branches over three statement kinds pushed
    complexity to 15.
    """
    aliases = _import_aliases(trees)
    out = set()
    for module, tree in trees.items():
        out |= _attribute_mutations(tree, aliases)
        out |= _module_global_mutations(tree, module)
    return out


def _globals_of(tree):
    """All names covered by `global <name>` declarations in this module."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            out.update(node.names)
    return out


def _uses_global(tree, name):
    """Does this module declare `global <name>`? (name=None => any global at all)."""
    g = _globals_of(tree)
    return bool(g) if name is None else name in g


def _functions_reading(src_tree, name):
    """Top-level function names in `src_mod` that (transitively) read `name`.

    Derived snapshots often appear through a wrapper: `OUT = repo(LEDGER_NAME)`
    -- the expression text contains no `gate.GATE_REPO`, but the body of
    `repo()` does. Looking only one hop misses **two hops**: `def a(): return
    repo(x)` followed by `OUT = a()` (measured: []).
    So this computes a **closure**: repeatedly add "functions that call a known
    reader" to the reader set until a fixed point. At zreflect's scale of 28
    modules, a few rounds suffice.
    """
    defs = {}
    for node in src_tree.body:
        if isinstance(node, ast.FunctionDef):
            calls = {getattr(c.func, "id", None) or getattr(c.func, "attr", None)
                     for c in ast.walk(node) if isinstance(c, ast.Call)}
            reads = any(isinstance(n, ast.Name) and n.id == name
                        and isinstance(n.ctx, ast.Load)
                        for n in ast.walk(node))
            defs[node.name] = (reads, calls - {None})
    readers = {f for f, (reads, _c) in defs.items() if reads}
    changed = True
    while changed:
        changed = False
        for f, (_reads, calls) in defs.items():
            if f not in readers and (calls & readers):
                readers.add(f)
                changed = True
    return readers


def _calls_outside_lambda(node):
    """Call nodes inside `node` that are **not within a lambda body** (lambda bodies evaluate lazily).

    ⚠️ `node` **itself** must be counted: in `OUT = repo("L")` the `node.value`
    is itself a Call -- walking only children misses it (measured: derived
    detection completely dead).
    """
    out = []
    def walk(n):
        if isinstance(n, ast.Call):
            out.append(n)
        for child in ast.iter_child_nodes(n):
            if isinstance(child, ast.Lambda):
                continue            # skip the entire lambda body
            walk(child)
    walk(node)
    return out


def _call_graph(tree):
    """Per top-level function of this module: the set of bare function names it **calls** (built once, avoiding repeated ast.walk)."""
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        out[node.name] = {n.func.id for n in ast.walk(node)
                          if isinstance(n, ast.Call)
                          and isinstance(n.func, ast.Name)}
    return out


def _reaches(node, readers, graph):
    """Can this expression reach a function in `readers`, directly or via this module's top-level functions?

    ⚠️ Reachability uses the prebuilt call graph (`graph`) + an explicit stack:
    **no recursion, no repeated walk**. The previous version ran `ast.walk`
    over the whole function body per derived node and recursed -- mutually
    recursive functions hung it outright (measured: the real repo's 28 modules
    never returned within the 60s timeout).

    Two false-positive guards (both previously produced false reds, measured):
      - a same-named function defined in this module does not count as a
        reader of the source module (shadowing) -- it is still followed along
        the call graph (it may itself forward to repo)
      - attribute calls (`tools.repo(...)`) do not count --
        `getattr(...,"attr")` would match same-named functions of any module,
        which is not this module's repo
    """
    # ⚠️ **Do not enter lambda bodies**: calls inside
    # `CASES = [("label", lambda: check_doc(..., repo(...)))]` are **executed
    # lazily**, not evaluated at import, so nothing freezes. A previous version
    # scanned indiscriminately with `ast.walk`, counting the repo call inside
    # the lambda body => false positive on `facts.CASES` (measured).
    seen = set()
    stack = [n.func.id for n in _calls_outside_lambda(node)
             if isinstance(n.func, ast.Name)]
    while stack:
        fn = stack.pop()
        if fn in seen:
            continue
        seen.add(fn)
        if fn in graph:
            stack.extend(graph[fn])     # local function: keep following what it calls
        elif fn in readers:
            return True                 # a reader inside the source module
    return False


def _module_level_assigns_all(tree):
    """All assignment nodes at module top level (including attribute assignments in class bodies).

    All three shapes are accepted (previously only `ast.Assign` was; the other
    two were missed -- found in review):
      - `OUT = repo(...)`              plain assignment
      - `OUT: str = repo(...)`         annotated (AnnAssign)
      - `class C: OUT = repo(...)`     class attribute (also evaluated at import)
    """
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign) or (
                isinstance(node, ast.AnnAssign) and node.value is not None):
            nodes.append(node)
        elif isinstance(node, ast.ClassDef):
            nodes.extend(n for n in node.body
                         if isinstance(n, ast.Assign)
                         or (isinstance(n, ast.AnnAssign)
                             and n.value is not None))
    return nodes


def _target_names(node):
    """Target names of an assignment node (`Assign` has `.targets`, `AnnAssign` only `.target`)."""
    return [t.id for t in (getattr(node, "targets", None) or [node.target])
            if isinstance(t, ast.Name)]


def _module_level_derivations(tree, src_mod, name, readers=(), graph=None):
    """Does the module top level contain `OTHER = <expression mentioning src_mod.name>`? That is **the same class of snapshot**.

    Both spellings freeze at the moment of import:
        from gate import GATE_REPO      # value copy
        OUT = repo(LEDGER_NAME)        # repo() internally reads gate.GATE_REPO => frozen into a string

    Catching only the first misses the second -- and the second is the one
    actually present in this repo (`facts.py:35`; measured: after changing
    `gate.GATE_REPO`, `facts.OUT` still held the old path).
    """
    marker = "%s.%s" % (src_mod, name)
    hits = []
    for node in _module_level_assigns_all(tree):
        text = ast.unparse(node.value)
        hit = marker in text or (bool(readers)
                                 and _reaches(node.value, readers, graph))
        if hit:
            hits += _target_names(node)
    return hits


def _loaded_names(tree):
    """Set of all names **read** (Load) in this module (built once; serves `_used_in_module`).

    ⚠️ Previously `_used_in_module(tree, name)` ran `ast.walk` over the whole
    tree **per candidate name** -- at 28 modules x hundreds of names it
    degenerated into 10 million `ast.walk` calls (measured: cProfile 32s,
    `iter_child_nodes` called 20 million times). Caching as a set reduces it
    to one traversal; lookups are O(1).
    """
    return {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def _index(sources):
    """Build the index: ASTs / module-level assigns / names reassigned elsewhere / loaded names / call graph / reader sets.

    ⚠️ Everything is **precomputed**. Previously the double loop recomputed
    `ast.walk` over all modules for every `(module x name)` => O(M^2*N);
    measured: timeout 60s after 400+ calls. These quantities depend only on a
    single module (or a single `(src_mod, name)` pair), never on the caller.
    """
    trees = {}
    for mod, src in sources.items():
        try:
            trees[mod] = ast.parse(src)
        except SyntaxError:
            continue
    assigned = {mod: _module_level_assigns(tree) for mod, tree in trees.items()}
    mutated = _mutated_globals(trees)
    mutable = {(m, n) for m, names in assigned.items() for n in names
               if (m, n) in mutated}
    return {
        "trees": trees,
        "assigned": assigned,
        "mutable": mutable,
        "loaded": {mod: _loaded_names(tree) for mod, tree in trees.items()},
        "graph": {mod: _call_graph(tree) for mod, tree in trees.items()},
        "readers": {(m, n): _functions_reading(trees[m], n)
                    for (m, n) in mutable},
    }


def _derived_hits(ix, mod, tree, src_mod, names):
    """In one consumer module: names where a mutable global from `src_mod` is baked into a derived constant."""
    loaded = ix["loaded"][mod]
    graph = ix["graph"][mod]
    hits = []
    for name in sorted(names):
        if (src_mod, name) not in ix["mutable"]:
            continue
        readers = ix["readers"].get((src_mod, name), set())
        for derived in _module_level_derivations(tree, src_mod, name,
                                                 readers, graph):
            if derived in loaded:
                hits.append(M("snapshot.derived_copy",
                              file=mod + ".py", derived=derived,
                              source=src_mod, imported=name))
    return hits


def _derived_copy_problems(ix):
    """2. **Derived snapshots**: the module top level stores "an expression containing a mutable global" as a constant (freezes just like an import)."""
    out = []
    for mod, tree in sorted(ix["trees"].items()):
        for src_mod, names in sorted(ix["assigned"].items()):
            out += _derived_hits(ix, mod, tree, src_mod, names)
    return out


def _mutable_copy_problems(ix):
    """1. **Value snapshots**: `from <local module> import ALL_CAPS` where that global is reassigned elsewhere => the copy stays frozen at import time."""
    out = []
    for mod, tree in sorted(ix["trees"].items()):
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            for name in _frozen_imports(ix, mod, node):
                out.append(M("snapshot.mutable_copy",
                             file=mod + ".py", imported=name,
                             source=node.module))
    return out


def _frozen_imports(ix, mod, node):
    """Which names in this `from <src> import ...` are **value snapshots** (the copy freezes).

    The five guards are all "not worth reporting" exits, each for a different
    reason -- crammed at the call site they become 5 consecutive `continue`s
    (complexity 11). Extracted into a named function, the call site is one line.
    """
    src_mod = node.module
    if src_mod not in ix["trees"]:
        return []                       # not in the scan surface => not a local sibling module
    if src_mod not in ix["assigned"]:
        return []                       # source module outside the scan surface => do not guess
    loaded = ix["loaded"][mod]
    out = []
    for alias in node.names:
        name = alias.name
        if name != name.upper():
            continue                    # functions / classes / lowercase names are not "value snapshots"
        if name not in ix["assigned"][src_mod]:
            continue                    # the source module has no such module-level name
        if (src_mod, name) not in ix["mutable"]:
            continue                    # nobody reassigns it => the copy is safe
        if (alias.asname or name) not in loaded:
            continue                    # dead import; not reported
        out.append(name)
    return out


def problems(paths=None, sources=None):
    """Pure function: return the problem list (empty = no snapshot risk).

    `sources` accepts injected `{module name: source}` (for self-proof, zero
    file I/O).

    Orchestration only: the index is built once (`_index`), and each of the
    two detection passes reads it (`_mutable_copy_problems` /
    `_derived_copy_problems`). Previously both passes were jammed into one
    function with indexing interleaved -- to change one you had to read the
    other.
    """
    if sources is None:
        if paths is None:
            return [M("snapshot.empty_scan")]
        sources = {}
        for name, src in paths:
            sources[name[:-3] if name.endswith(".py") else name] = src
    if not sources:
        return [M("snapshot.empty_scan")]
    ix = _index(sources)
    return _derived_copy_problems(ix) + _mutable_copy_problems(ix)


def collect(root, configured=False):
    """Which `.py` files to collect -- see `gate.scanned_sources` (the single source of both policies)."""
    return gate.scanned_sources(root, configured)


def run(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # ⚠️ **`REFLECT_SNAPSHOT_ROOT` empty => scan the suite's own `zreflect/`**,
    # not "not enabled". (The README once stated this backwards: "empty => that
    # gate says out loud it is off" -- measured: with the knob empty it still
    # runs and reports `snapshot.ok` for the suite.)
    # Why designed this way: this gate guards "mutable globals imported across
    # modules", and the suite itself is the biggest victim (`gate.GATE_REPO`
    # is rewritten by several self-proofs), so the default surface is the
    # suite. To scan **your code**, set `REFLECT_SNAPSHOT_ROOT=<dir>`
    # explicitly.
    configured = os.environ.get(KNOB, "").strip()
    # ⚠️ **Unset => anchor at the tool repo** (`gate.zdir()`), not a bare
    # relative name -- the latter depends on cwd: correct when run from the
    # repo root, but elsewhere (harness / hook cwd is not guaranteed) it dies
    # with `scan_empty_dir` FATAL (measured: rc=2 after cd /tmp).
    # Explicitly set => relative to the **audited repo** (the user writes a
    # repo-root-relative name in the env file).
    root = gate.zdir() if not configured \
        else os.path.join(gate.GATE_REPO, configured)
    if not os.path.isdir(root):
        # knob points at a nonexistent directory => broken config (not "not enabled")
        return fatal(M("snapshot.scan_empty_dir", root=root))
    paths = collect(root, configured=bool(configured))
    if not paths:
        return fatal(M("snapshot.scan_empty_dir", root=root))
    return finish(M("snapshot.title"), problems(paths),
                  M("snapshot.ok", files=len(paths)))


ALIAS_GATE = 'GATE_REPO = "/repo"\n'
ALIAS_USER = 'import gate as g\ng.GATE_REPO = "/other"\n'
ALIAS_VICTIM = 'from gate import GATE_REPO\ndef f():\n    return GATE_REPO\n'
# A module that used to be absent from LOCAL_MODULES (`check_zzz`) as the **source module**
CHECK_AS_SOURCE = 'SHARED = "/x"\n'
CHECK_AS_VICTIM = ('import check_zzz\ncheck_zzz.SHARED = "/y"\n'
                   'from check_zzz import SHARED\ndef f():\n    return SHARED\n')

GATE_WITH_REPO = """
GATE_REPO = "/repo"
def repo(*parts):
    return os.path.join(GATE_REPO, *parts)
def set_repo(p):
    global GATE_REPO
    GATE_REPO = p
"""


def _fixtures():
    """Fixture sources (English: they are the **inputs** being audited, not the module's own output).

    ⚠️ Must be constructed **inside a function**, not as module-level
    constants: the gate scans exactly "expressions assigned at module top
    level", so module-level fixtures would be flagged by the gate itself as
    derived snapshots -- measured: after hoisting to module level it
    self-reported
    `snapshot.derived_copy(derived='fx["ok_style"]', source='gate')`.
    The criterion was right; the fixtures sat at the wrong layer.
    """
    return {
        "good": "GATE_REPO = \"/repo\"\nCONST = [1]\n",
        "good_user": "from gate import CONST\ndef f():\n    return CONST\n",
        "bad_gate": ("GATE_REPO = \"/repo\"\ndef set_repo(p):\n"
                     "    global GATE_REPO\n    GATE_REPO = p\n"),
        "bad_user": "from gate import GATE_REPO\ndef f():\n    return GATE_REPO\n",
        "ok_style": "import gate\ndef f():\n    return gate.GATE_REPO\n",
    }


def _cases_value_copy(fx):
    """1. Value copies: constants safe / attribute style safe / a copied mutable global must be reported."""
    return [
        ("snapshot.constant_copy_is_fine",
         lambda: problems(sources={"gate": fx["good"],
                                   "check_x": fx["good_user"]}) == []),
        ("snapshot.attribute_style_is_fine",
         lambda: problems(sources={"gate": fx["bad_gate"],
                                   "check_x": fx["ok_style"]}) == []),
        ("\u2605 snapshot.mutable_copy",
         lambda: [p.code for p in problems(
             sources={"gate": fx["bad_gate"], "check_x": fx["bad_user"]})
         ] == ["snapshot.mutable_copy"]),
        # dead imports are not reported (importing something unused is not a risk)
        ("snapshot.dead_import_not_reported",
         lambda: problems(sources={
             "gate": fx["bad_gate"],
             "check_x": "from gate import GATE_REPO\n"}) == []),
        # aliased module assignment (`import gate as g; g.GATE_REPO = ...`) --
        # another spelling of the same act as `gate.GATE_REPO = ...`;
        # previously missed (measured: [])
        ("\u2605 snapshot.mutable_copy_via_alias",
         lambda: [p.code for p in problems(sources={
             "gate": ALIAS_GATE, "usr": ALIAS_USER, "victim": ALIAS_VICTIM})
         ] == ["snapshot.mutable_copy"]),
        # discovery-based source modules: **any .py in the scan surface** can
        # be a source module, not just the 12 names on the old hand-written
        # roster (previously all 16 check_*.py were invisible)
        ("\u2605 snapshot.source_from_any_module",
         lambda: [p.code for p in problems(sources={
             "check_zzz": CHECK_AS_SOURCE, "victim": CHECK_AS_VICTIM})
         ] == ["snapshot.mutable_copy"]),
    ]


def _cases_derived():
    """2. Derived snapshots: the top level stores an expression that reaches a mutable global through a thin wrapper as a constant."""
    return [
        # `OUT = repo(NAME)`, whose repo() body reads GATE_REPO => frozen at import time
        ("\u2605 snapshot.derived_copy",
         lambda: [p.code for p in problems(sources={
             "gate": GATE_WITH_REPO,
             "facts": "OUT = repo('L.json')\nprint(OUT)\n"})
         ] == ["snapshot.derived_copy"]),
        # annotated derivation (`OUT: str = repo(...)`) -- previously only
        # `ast.Assign` was accepted, missing AnnAssign (review measured `[]`)
        ("\u2605 snapshot.derived_copy_annotated",
         lambda: [p.code for p in problems(sources={
             "gate": GATE_WITH_REPO,
             "facts": "OUT: str = repo('L.json')\nprint(OUT)\n"})
         ] == ["snapshot.derived_copy"]),
    ]


def _default_root_case():
    """The default scan surface anchors at the tool repo, independent of cwd.

    ⚠️ Previously, with the knob unset, a bare relative name `zreflect` was
    used -- correct when run from the repo root, but from elsewhere (harness /
    hook cwd is not guaranteed) it died with `scan_empty_dir` FATAL (measured:
    rc=2 after cd /tmp). This case **switches to a temp directory** before
    running the real gate, pinning "cwd is not a prerequisite".
    """
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    here = os.path.dirname(os.path.abspath(__file__))
    d = tempfile.mkdtemp()
    env = {k: v for k, v in os.environ.items() if k != KNOB}
    try:
        p = subprocess.run([sys.executable, os.path.join(here, __file__)],
                           cwd=d, env=env, capture_output=True, text=True,
                           timeout=120, encoding="utf-8", errors="replace")
        # ⚠️ Assert only the **rc**, never match output wording:
        # `snapshot.ok(...)` is a code; with a language pack installed it
        # renders as natural language (measured: this case went red under
        # REFLECT_LANG=en -- it was using the current language pack's wording
        # as the criterion, making the first version its own counterexample).
        return p.returncode == 0
    finally:
        import shutil  # noqa: PLC0415
        shutil.rmtree(d, True)


def _cases():
    """Three cases: value copies / derived snapshots / empty input.

    Groups 1 and 2 are each a named group (the fixture sources also moved up
    to module constants -- in the old 80-line function those triple-quoted
    strings made up nearly a third, interleaved with assertions).
    """
    return (_cases_value_copy(_fixtures()) + _cases_derived()
            + [("\u2605 snapshot.empty_scan",
                lambda: problems(sources={}) != []),
               ("★ snapshot.default_root_is_cwd_free",
                lambda: _default_root_case())])


GATE = meta("module-level snapshot gate",
            "a mutable global imported across modules is a value copy (stale snapshot): switch to importing the module and reading the attribute",
            knobs=("REFLECT_SNAPSHOT_ROOT",))

if __name__ == "__main__":
    sys.exit(main_selftest_or(sys.argv[1:],
                              M("gate.title.snapshot"), _cases(), run))
