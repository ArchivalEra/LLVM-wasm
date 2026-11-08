#!/usr/bin/env python3
"""Language-coverage gate (**pluggable module**, issue #26): the mechanical guarantee that the core is truly zero-language.

It guards one **closed criterion** -- "the core must not contain user-visible natural language":

  - **messages** must be `M(<literal code>, **params)` -- a bare literal like
    `out.append("Chinese...")` is forbidden (that is "the core speaking prose",
    exactly what this rule exists to eliminate);
  - **self-proof case labels** are **id-ified** per user decision (1C) --
    no natural-language sentences;
  - **docstrings** are exempt (maintainer documentation, not output);
  - **language packs** may contain any natural language (optional data,
    not part of the core).

Why this criterion must exist (without it: "looks zero-language, actually
half-leaking"):

  Language packs are optional => a user may install only `en`. If the core
  still hides one hardcoded Chinese message, it shows Chinese on an en user's
  screen and **nothing reports it** -- precisely the silent degradation this
  repo exists to eliminate. This gate turns "core is zero-language" from a
  slogan into something decidable.

## It currently has four criterion families (round-16 review verdict: **do not split**)

  1. **Bare CJK** (`bare_text`) -- CJK string constants in output positions
  2. **PINNED declaration surface** -- functions/constants marked `PINNED:`
     are exempt as a whole (AUTO machine blocks must be language-fixed;
     following the language would never converge)
  3. **Fixture literals** (`fixture_literal`) -- Chinese inside `_cases()` is
     allowed only in **labels** and **docstrings**; fixture source must be
     codepoint-constructed (criterion added after the same mistake three times)
  4. **Messages must go through M()** -- the shape criteria of
     `_is_msg_call` / `_is_output_call`

**Why not split into four gates**: they share one `ast.parse(src)` and one
file traversal. Splitting = four duplicated parses and traversals, each of
which can drift independently (the most painful kind in this repo). The four
families **differ only in what counts as legal**, and that is already isolated
by their respective helpers (`_declares_pinned` / `_fixture_literal_problems`
/ `cjk`). Shared parsing is the real reason they cannot be split -- not
"they look like one class".

Honest boundary (an explicitly written gap): the criterion is **AST-level** --
it catches "a bare Chinese literal in an output position" but not "messages
written in English" (that is still a core language, though the core is now
CJK-free; catching it would need much heavier language detection, too
expensive). So this gate's strength = "zero CJK + messages must go through M()".
"""
from __future__ import annotations

import ast
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate  # noqa: E402
import machine  # noqa: E402
from gate import fatal, finish, main_selftest_or, meta, repo  # noqa: E402
from i18n import M  # noqa: E402

# When the knob is unset, scan **these** directories -- the suite's own Python.
#
# ⚠️ This list must **cover both halves of the suite** (criterion library +
# hook entry points): scanning only one half means "half the core is
# zero-language", while the other half keeps emitting bare Chinese.
#
# ⚠️ It must **not** include any host's directories -- that would weld the
# suite to one host's directory conventions. There really was such an entry
# here once (also scanning an editor-specific hooks directory); the full
# account of that coupling lives in `retractions.json` R-003 and
# `doc.RULES`'s `host_agnostic`. History is not kept in code comments: it
# should not be maintained there, and it would make `host_agnostic` scan
# itself (this file is part of its scan surface).
DEFAULT_ROOTS = ("zreflect", "reflect-hooks")
KNOB = "REFLECT_I18N_ROOT"


# Codepoint range of the CJK Unified Ideographs block (U+4E00-U+9FFF).
# **Codepoint constants, not literal characters**: writing the two endpoint
# characters as literals would make this gate scan its own source (they are
# exactly the range endpoints) --
# actually hit once (it reported two fake violations on the endpoint chars).
from i18n import CJK_LO, han  # noqa: E402

PINNED_MARK = "PINNED:"


def _declares_pinned(doc):
    """Does the docstring carry a `PINNED:` declaration **with a reason**?

    ⚠️ Only "`PINNED:` followed by a reason of at least 8 characters" counts:
    otherwise any function could exempt all of its Chinese by writing
    `PINNED:` in its docstring (measured: a plain `report_problem()` plus one
    line `PINNED: x` was fully exempt). An exemption must state "why this
    text cannot be translated" -- same discipline as the mandatory `why` in
    `REFLECT_INVARIANTS`.
    """
    if not doc or PINNED_MARK not in doc:
        return False
    idx = doc.index(PINNED_MARK)
    reason = doc[idx + len(PINNED_MARK):].strip()
    # The reason runs to the first sentence end / newline (one sentence suffices)
    for sep in ("\n", "。", ". "):
        cut = reason.find(sep)
        if cut != -1:
            reason = reason[:cut]
    return len(reason.strip()) >= 8


def _pinned_by_comment(src, node):
    """Does `PINNED:` appear **immediately above** the assignment (in the contiguous comment block before it)?

    Module-level constants have no docstring, so their declaration can only
    live in a comment. Look up only the immediately adjacent comment block
    (stop at a blank or non-comment line) -- never scan the whole file,
    avoiding "a single `PINNED:` anywhere in the file exempts everything".
    """
    lines = src.splitlines()
    i = node.lineno - 2                      # the line above (0-based)
    while i >= 0:
        line = lines[i].strip()
        if line.startswith("#"):
            if PINNED_MARK in line:
                return True
            i -= 1
            continue
        break                                # end of the comment block
    return False


# The "does it contain Chinese" criterion lives in `i18n.han()` (the owner of
# the zero-language regime); this only forwards -- two copies of a range
# constant would drift (C4).
cjk = han



def _is_msg_call(node):
    """`M(code, **params)` or `i18n.M(...)`."""
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return (isinstance(f, ast.Name) and f.id == "M") or \
           (isinstance(f, ast.Attribute) and f.attr == "M")


def _is_output_call(node):
    """Calls that produce user-visible text: append / print / off / fatal / finish."""
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    if isinstance(f, ast.Attribute) and f.attr == "append":
        return True
    return isinstance(f, ast.Name) and f.id in ("print", "off", "fatal", "finish")


def _docstring_node_id(node):
    """The id of the docstring constant within one scope node (None if absent)."""
    d = ast.get_docstring(node, clean=False)
    if not d:
        return None
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and n.value == d:
            return id(n)
    return None


def _doc_nodes(tree):
    """Docstring nodes (exemption surface 1: docstrings are not words to the user)."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            nid = _docstring_node_id(node)
            if nid is not None:
                out.add(nid)
    return out


def _msg_consts(tree):
    """Constant ids inside `M(...)` -- those are **legal positions** (a message going through M is the right thing)."""
    out = set()
    for node in ast.walk(tree):
        if _is_msg_call(node):
            for n in ast.walk(node):
                if isinstance(n, ast.Constant):
                    out.add(id(n))
    return out


# Roster of calls exempting shape 1: their arguments are **declaration data /
# matcher data**, not sentences shown to the user. ⚠️ Self-proof titles are
# **not** on it (user ruling: choosing English and emitting Chinese is not allowed).
_EXEMPT_CALLS = ("meta", "module_meta", "Rule", "compile",
                 "startswith", "endswith", "match", "search", "fullmatch", "find")


def _branch_constants(node):
    """Ids of all string constant nodes in `node`'s subtree (used by the exemption surfaces)."""
    return {id(n) for n in ast.walk(node) if isinstance(n, ast.Constant)}


def _exempt_call_args(tree):
    """1. Call arguments: `meta(...)` / `module_meta(...)` / `Rule(...)` / `re.compile(...)` and the like."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            fn = getattr(f, "id", "") or getattr(f, "attr", "")
            if fn in _EXEMPT_CALLS:
                out |= _branch_constants(node)
    return out


def _pinned_constants(tree, src):
    """2. The `PINNED:` declaration surface (AUTO machine blocks: language-fixed, reconciled byte by byte).

    Collected by **declaration**, not by name -- a hand-written roster always
    drifts (deepening round 8).
    """
    out = set()
    for node in ast.walk(tree):
        fn_pinned = (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and _declares_pinned(ast.get_docstring(node, clean=False)))
        assign_pinned = (isinstance(node, ast.Assign)
                         and _pinned_by_comment(src, node))
        if fn_pinned or assign_pinned:
            out |= _branch_constants(node)
    return out


def _exempt_ids(tree, name, src):
    """The **declared** exemption surfaces (not guessed). Each must state its why, or exemptions become the next drifting hand-written roster. The three parts are each a named function (see their docstrings).

    3. The language-pack loader's own errors (`i18n.py`): `MissingPack`'s
    text **cannot use M()** (circular dependency: M depends on the language
    pack, and it is raised precisely when the pack is broken). File-level
    exemption.
    """
    out = _exempt_call_args(tree) | _pinned_constants(tree, src)
    if name == "i18n.py":
        out |= {id(n) for n in ast.walk(tree) if isinstance(n, ast.Constant)}
    return out


def _bare_text_problems(name, tree, src):
    """**Bare natural language** in one source file (outside the four exemption classes and not an id-ified label)."""
    out = []
    doc_nodes = _doc_nodes(tree)
    msg_consts = _msg_consts(tree)
    exempt = _exempt_ids(tree, name, src)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        v = node.value
        if not cjk(v):
            continue
        if id(node) in doc_nodes or id(node) in msg_consts or id(node) in exempt:
            continue
        # User decision 1C: a label only needs to **start with a dotted id**;
        # a short Chinese gloss may follow.
        if re.match(r"^\s*(★\s*)?[a-z_][a-z0-9_]*(\.[a-z0-9_.]+)+", v):
            continue
        out.append(M("i18n_cover.bare_text",
                     file=name, lineno=node.lineno, text=v[:40]))
    return out

def _non_literal_code_problems(name, tree):
    """The first argument of `M(...)` must **not be computed** (conditional expression / concatenation / f-string / call).

    Why this deserves its own criterion: `i18n.M`'s docstring said from day
    one that "`code` must be a literal (the coverage gate will reject variable
    codes)" -- yet **no gate enforced it**. The measured cost: `check_envfile`
    contained `M("a" if is_dir else "b", ...)`; both codes really exist in the
    language pack and really do render for users, but `knobs.used_codes()`
    (a regex scanning literal `M("..."`) only catches the first => the other
    is **completely invisible** to `pack_coverage`. In the pack-integrity
    reconciliation that is a hole, not a violation -- a hole is worse than a
    violation, because no line of output ever says it exists.

    **Forwarding is not a violation**: thin shells like `_say(code)`,
    `_Semantic`'s deferred rendering, and probes that walk language packs for
    integrity self-proofs have codes that are literals **at their own call
    site** or **are keys of the pack itself**. Forcing them to contort in
    order to satisfy one shape criterion is putting the cart before the horse.
    So this catches only **expressions**: `IfExp` / `BinOp` / `JoinedStr` /
    `Call` / `Subscript` -- the class that is "assembled at runtime, not
    statically enumerable".

    **Honest boundary**: when the first argument is a `Name` / `Attribute`,
    it is **not checked**. It may be legitimate forwarding or a non-literal
    passed from elsewhere; statically the two are indistinguishable, and
    per-call-site type analysis is too expensive. This boundary is written
    here rather than pretending the criterion covers it.
    """
    computed = (ast.IfExp, ast.BinOp, ast.JoinedStr, ast.Call, ast.Subscript)
    out = []
    for node in ast.walk(tree):
        if not _is_msg_call(node) or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            continue
        if not isinstance(first, computed):
            continue                       # forwarding (see honest boundary)
        out.append(M("i18n_cover.code_not_literal",
                     file=name, lineno=node.lineno,
                     kind=type(first).__name__))
    return out


def problems(paths):
    """Pure function: return the problem list (empty = zero-language). `paths` = [(name, source text)].

    `paths` is injectable => self-proofs use fake sources, zero file I/O.

    Four parts (each a helper): `_doc_nodes` / `_msg_consts` / `_exempt_ids` /
    `_bare_text_problems`. This function only orchestrates -- 111 lines -> 15.
    """
    if not paths:
        return [M("i18n_cover.empty_scan")]
    out = []
    # ⚠️ **The filename itself** is also an attack surface: a file named
    # `evil\nOFF: x.py`, once its name is rendered into a message (as in
    # `i18n_cover.bare_text(file=...)`), forges a machine line. The criterion
    # uses the **same table** as `machine.LINE_BREAKS` (C4: do not write a
    # second, near-identical set of line breaks). This check did not exist at
    # all before -- measured: a .py with an embedded newline placed in the
    # scan surface still got `i18n_cover.ok(files=34)`.
    for name, _src in paths:
        if any(b in name for b in machine.LINE_BREAKS):
            out.append(M("i18n_cover.filename_has_line_break",
                         file=name.replace("\n", "\\n")[:60]))
    for name, src in paths:
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            out.append(M("i18n_cover.parse_error", file=name, error=e))
            continue
        out += _bare_text_problems(name, tree, src)
        out += _fixture_literal_problems(name, tree)
        out += _non_literal_code_problems(name, tree)
    return out


def _cases_scope(tree):
    """Self-proof scan scope: `_cases()` itself plus the **same-file top-level helpers it references**.

    ⚠️ The scope must cover helper functions: same-file helpers called by
    `_cases()` are also on the self-proof path (actually hit: a criterion
    anchor was written into `_streams_documented()`, invisible to this
    criterion => bare_text got reported by the main criterion while this one
    missed it).

    ⚠️ **PINNED functions do not count as fixture helpers**: `_cases()` calls
    `render_gates()` to test "rendering determinism", but that function's text
    is an AUTO machine block, **language-fixed by design** (already exempted
    by family 3). Pulling it into the fixture scan false-positives (measured:
    7 PINNED lines caught by `fixture_literal`). The exemption surfaces must
    respect one another.
    """
    fns = [n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef) and n.name == "_cases"]
    if not fns:
        return []
    fn = fns[0]
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    helpers = [n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name in called
               and not _declares_pinned(ast.get_docstring(n, clean=False))]
    return [fn] + helpers


def _docstring_nodes(bodies):
    """Exemption surface 1: docstring constant nodes (maintainer documentation, not output)."""
    out = set()
    for node in [n for b in bodies for n in ast.walk(b)]:
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            d = ast.get_docstring(node, clean=False)
            if not d:
                continue
            for n in ast.walk(node):
                if isinstance(n, ast.Constant) and n.value == d:
                    out.add(id(n))
                    break
    return out


def _label_nodes(bodies):
    """Exemption surface 2: self-proof labels (first element of a `(label, callable)` tuple)."""
    return {id(node.elts[0])
            for b in bodies for node in ast.walk(b)
            if isinstance(node, ast.Tuple) and len(node.elts) == 2
            and isinstance(node.elts[0], ast.Constant)}


def _fixture_literal_problems(name, tree):
    """**No Chinese source-code literals in self-proof fixtures** (they must be codepoint-constructed).

    Why this deserves its own criterion: I stepped on it **three times**
    (round 8 PINNED reason, round 9, round 13) -- every time the sequence was
    "write a Chinese fixture/assertion -> `check_i18n` reports bare_text ->
    only then notice this very file is inside its own scan surface". After
    the third time it had to become a machine criterion.

    Within `_cases()`, CJK string constants may appear in only two legal
    positions:
      - self-proof **labels** (first element of a `(label, callable)` tuple)
        -- per decision 1C, labels are id-shaped and may carry a Chinese
        gloss to aid skimming
      - **docstrings** -- maintainer documentation, not output
    Anything else (Chinese strings in fixture source samples / assertions)
    => report. Values produced by codepoint construction (`chr(CJK_LO)` /
    `_cj(n)`) are **not in the AST** and naturally never report -- that is
    the correct spelling.

    Each of the three steps is a helper (scope / the two exemption surfaces):
    merged together, the two independent node-collection loops plus the
    deciding loop pushed complexity to 13.
    """
    bodies = _cases_scope(tree)
    if not bodies:
        return []
    exempt = _docstring_nodes(bodies) | _label_nodes(bodies)
    return [M("i18n_cover.fixture_literal",
              file=name, lineno=node.lineno, text=node.value[:40])
            for b in bodies for node in ast.walk(b)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and cjk(node.value) and id(node) not in exempt]


def sources_for(d, configured=False):
    """Which `.py` files to collect -- see `gate.scanned_sources` (the single source of both policies).

    ⚠️ This used to re-implement that ternary inline, and
    `check_snapshots.collect` had its own copy -- the same criterion in two
    places. Now it only forwards.
    """
    return gate.scanned_sources(d, configured)


def run(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # ⚠️ The default scan root is **not empty**: this gate guards the
    # **suite's own** code, so with the knob unset it scans the **tool repo's**
    # `zreflect/`. Previously `DEFAULT_ROOT` was defined but **never used**,
    # nobody configured the knob => in a live `registry --run commit` it was
    # forever `off` -- "the gate exists, its self-proof is green, but it never
    # runs". Same disease as `check_snapshots`.
    #
    # Two policies (same pattern as `i18n.pack_dir()`; do not conflate them):
    #   - unset => the **tool repo's** `zreflect/` (travels with the suite;
    #     correct in cross-repo fixtures too)
    #   - set => a path relative to the **audited repo** (the "name relative
    #     to the repo root" written in the env file)
    # Collapsing them into one causes FATAL in cross-repo fixtures (measured:
    # with GATE_REPO=$tmp the zreflect/ scan finds nothing).
    configured = os.environ.get(KNOB, "").strip()
    roots = [configured] if configured else list(DEFAULT_ROOTS)
    paths = []
    for root in roots:
        if configured:
            d = repo(root)
        else:
            d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", root)
            d = os.path.abspath(d)
        found = sources_for(d, configured=bool(configured))
        if not found and configured:
            return fatal(M("i18n_cover.scan_empty_dir", root=root))
        paths.extend(found)
    if not paths:
        return fatal(M("i18n_cover.scan_empty_dir", root=", ".join(roots)))
    return finish(M("i18n_cover.title"), problems(paths),
                  M("i18n_cover.ok", files=len(paths)))


_PH = re.compile(r"%\(([A-Za-z_][A-Za-z0-9_]*)\)"
                 r"(?:[#0\-+ ]*)(?:\d+)?(?:\.\d+)?[hlL]?([diouxXeEfFgGcrsa])")


def _params_for(template):
    """Build parameters according to the template's **conversion specifiers**: `%d`/`%f` get numbers, the rest get strings.

    ⚠️ Always handing `"v"` explodes with a `TypeError` on `%(count)d`
    (measured).
    """
    return {m.group(1): (3 if m.group(2) in "dixXfFeEgG" else "v")
            for m in _PH.finditer(template)}


def _null_output_has_no_cjk():
    """Render every code **with no language pack installed** and assert the output contains zero CJK.

    The null pack only outputs `code(param=...)` -- this is the **behavioral**
    criterion for "no language pack requested => zero natural language". It
    enumerates **all** keys rather than hand-picking: a hand-picked roster
    missed a namespace added after one such miss (the injected templates were
    what got missed), and the missed part stayed green.

    ⚠️ Note it **cannot** prove "the templates contain no Chinese": the null
    pack never consults a table. That is covered by
    `_packs_match_their_language()` (render with packs installed + judge CJK
    per language).
    """
    import i18n  # noqa: PLC0415
    try:
        table = i18n.load_pack("en")
    except Exception:                                    # noqa: BLE001
        return False              # real pack unreadable => cannot prove; not a pass
    if not table:
        return False              # zero-value guard
    probes = 0
    with i18n.bind(i18n.NULL):
        for code in sorted(table):
            if cjk(str(i18n.M(code, **_params_for(table[code])))):
                return False
            probes += 1
    return probes == len(table)


def _packs_match_their_language():
    """Render **with packs installed**: no entry of en / de may contain CJK; zh's *prose* may.

    This is the real criterion for "do the templates themselves contain
    Chinese" -- the null pack cannot test it (the null pack never consults a
    table).

    Criterion per language: CJK in `en` / `de` output => that template was
    not translated (or was missed). `zh` may contain Chinese (that is its
    language). Verify only **installed** packs: if `de` is installed, verify
    `de`.

    Zero-value guard: at least one non-zh pack must get verified.
    """
    import i18n  # noqa: PLC0415
    import knobs  # noqa: PLC0415
    checked = 0
    # **Discovery based**: check every installed non-zh pack (not a hand-written
    # ("en","de") -- a new language pack must not be silently skipped). The zh
    # core is exempt (the zero-language regime allows zh only in language packs).
    for lang in sorted(knobs.installed_langs()):
        if lang == "zh":
            continue
        try:
            table = i18n.load_pack(lang)
        except Exception:                                # noqa: BLE001
            continue
        if not table:
            continue
        cat = i18n.Catalog.load(lang, {lang: table})
        with i18n.bind(cat):
            for code in sorted(table):
                if cjk(str(i18n.M(code, **_params_for(table[code])))):
                    return False
        checked += 1
    return checked >= 1




def _cj(n):
    """Build n CJK characters by codepoint (no Chinese literal in the source; real CJK after AST evaluation).

    ⚠️ Fixtures **must contain real Chinese** (otherwise the "what must be
    reported gets reported" case has no target), yet a literal would be swept
    up by this very gate (the gate sees values after AST evaluation).
    Codepoint construction is the only clean spelling -- same origin as the
    codepoint range used inside `cjk()`.
    """
    return "".join(chr(CJK_LO + i) for i in range(n))


def _cjk_src(doc):
    """Craft a snippet of source containing a CJK literal (the literal is codepoint-constructed; no Chinese appears in this file's source)."""
    return ('def render_world_block(w):\n'
            '    """%s"""\n'
            '    return "%s"\n') % (doc, chr(CJK_LO) * 2)


# Reasons are codepoint-constructed (no Chinese in this file's source --
# otherwise this file's own coverage gate would collect it)
PINNED_FN = _cjk_src("PINNED: " + chr(CJK_LO) * 10 + " pinned, byte-exact.")
PINNED_BARE = _cjk_src("PINNED: x")
# Three fixture-literal examples (values assembled from codepoints; no Chinese in this file's source)
_CJ4 = chr(CJK_LO) * 4
FIXTURE_BAD = ("def _cases():\n"
               "    SAMPLE = \"" + _CJ4 + "\"\n"
               "    return [(\"ok.label\", lambda: SAMPLE == SAMPLE)]\n")
FIXTURE_LABEL = ("def _cases():\n"
                 "    return [(\"ok.label" + _CJ4 + "\", lambda: True)]\n")
FIXTURE_HELPER = ("def _helper():\n"
                  "    return \"" + _CJ4 + "\"\n"
                  "\n"
                  "def _cases():\n"
                  "    return [(\"ok\", lambda: _helper() == \"x\")]\n")
FIXTURE_DOC = ("def _cases():\n"
               "    \"\"\"doc " + _CJ4 + "\"\"\"\n"
               "    return [(\"ok\", lambda: True)]\n")
BARE_FN = _cjk_src("ordinary renderer.")


def _fixtures():
    """Source samples for `_cases()` (Chinese is codepoint-constructed, never written as a literal)."""
    sample = _cj(4)
    return {
        "good": (
            '"""docstring may contain CJK (maintainer docs) - ' + sample + '"""\n'
            "from i18n import M\n"
            "\n"
            "def f(x):\n"
            "    out = []\n"
            "    out.append(M(\"replay.no_cmd\", key=x))\n"
            "    return out\n"),
        "bare": (
            "def f(x):\n"
            "    out = []\n"
            "    out.append(\"`%s` " + sample + "\" % x)  # CJK sample\n"
            "    return out\n"),
        "label": (
            "def _cases():\n"
            "    return [(\"" + sample + "\", lambda: True)]  # flagged\n"),
    }


def _cases_bare_text(fx):
    """1. Bare natural language: what must be reported gets reported."""
    return [
        ("i18n_cover.good_fixture",
         lambda: problems([("good.py", fx["good"])]) == []),
        ("★ i18n_cover.bare_text",
         lambda: [x.code for x in problems([("bare.py", fx["bare"])])
                  ] == ["i18n_cover.bare_text"]),
        ("★ i18n_cover.bare_text_in_label",
         lambda: [x.code for x in problems([("label.py", fx["label"])])
                  ] == ["i18n_cover.bare_text"]),
        ("★ i18n_cover.parse_error",
         lambda: [x.code for x in problems([("bad.py", "def (")])]
         == ["i18n_cover.parse_error"]),
    ]


def _cases_pinned():
    """2. PINNED collected by **declaration**, not by name (three-way: exempt / undeclared / impostor)."""
    return [
        ("i18n_cover.pinned_by_declaration",
         lambda: problems([("r.py", PINNED_FN)]) == []),
        ("★ i18n_cover.undeclared_pinned_still_fires",
         lambda: [p.code for p in problems([("r.py", BARE_FN)])
                  ] == ["i18n_cover.bare_text"]),
        ("★ i18n_cover.pinned_needs_reason",
         lambda: [p.code for p in problems([("r.py", PINNED_BARE)])]
         == ["i18n_cover.bare_text"]),
    ]


def _cases_fixture_literal():
    """3. No Chinese source-code literals in self-proof fixtures (I stepped on it three times: rounds 8/9/13)."""
    return [
        ("★ i18n_cover.fixture_literal",
         lambda: [p.code for p in problems([("t.py", FIXTURE_BAD)])
                  ] == ["i18n_cover.bare_text", "i18n_cover.fixture_literal"]),
        ("★ i18n_cover.fixture_literal_in_helper",
         lambda: "i18n_cover.fixture_literal" in
         [p.code for p in problems([("t.py", FIXTURE_HELPER)])]),
        ("i18n_cover.fixture_label_cjk_is_allowed",
         lambda: problems([("t.py", FIXTURE_LABEL)]) == []),
        ("i18n_cover.fixture_docstring_cjk_is_allowed",
         lambda: problems([("t.py", FIXTURE_DOC)]) == []),
    ]


def _cases_code_literal():
    """4. The code of `M(...)` must not be computed (otherwise pack integrity loses its hold on it)."""
    return [
        ("★ i18n_cover.computed_code_is_rejected",
         lambda: [p.code for p in problems(
             [("c.py", ("from i18n import M\n"
                       "def f(x):\n"
                       "    return M(\"probe.a\" if x else \"probe.b\")\n"))])
         ] == ["i18n_cover.code_not_literal"]),
        ("i18n_cover.literal_code_is_fine",
         lambda: problems([("c.py", ("from i18n import M\n"
                                     "def f():\n"
                                     "    return M(\"probe.a\")\n"))]) == []),
        ("i18n_cover.forwarded_code_is_fine",
         lambda: problems([("c.py", ("from i18n import M\n"
                                     "def _say(code, **kw):\n"
                                     "    return M(code, **kw)\n"))]) == []),
    ]


def _cases_end_to_end():
    """5. End-to-end + scan surface: runtime leaks the static criteria cannot catch."""
    return [
        ("★ i18n_cover.null_pack_output_has_no_cjk",
         lambda: _null_output_has_no_cjk()),
        ("★ i18n_cover.packs_match_their_language",
         lambda: _packs_match_their_language()),
        ("★ i18n_cover.cjk_detector_can_red",
         lambda: cjk(chr(0x4E2D)) and not cjk("ascii only")),
        ("★ i18n_cover.hooks_dir_is_scanned",
         lambda: "reflect-hooks" in DEFAULT_ROOTS
         and "zreflect" in DEFAULT_ROOTS),
    ]


def _cases_input_guards():
    """6. Input guards: the filename itself is an attack surface; empty input must be reported."""
    return [
        ("★ i18n_cover.filename_line_break",
         lambda: [p.code for p in problems(
             [("evil" + chr(0x0A) + "OFF: x.py", "x = 1\n")])]
         == ["i18n_cover.filename_has_line_break"]),
        ("i18n_cover.filename_clean_ok",
         lambda: problems([("normal.py", "x = 1\n")]) == []),
        ("★ i18n_cover.empty_scan", lambda: problems([]) != []),
    ]


def _cases():
    """Assemble the six fixture-assertion groups. **Assembly only** -- the criteria live in the group functions."""
    fx = _fixtures()
    return (_cases_bare_text(fx)
            + _cases_pinned()
            + _cases_fixture_literal()
            + _cases_code_literal()
            + _cases_end_to_end()
            + _cases_input_guards())


GATE = meta("language coverage gate",
            "the core is zero-language: user-visible text must go through M(code); language packs are optional",
            knobs=("REFLECT_I18N_ROOT",))

if __name__ == "__main__":
    sys.exit(main_selftest_or(sys.argv[1:],
                              M("gate.title.i18n_cover"), _cases(), run))
