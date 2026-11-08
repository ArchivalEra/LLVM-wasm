#!/usr/bin/env python3
"""Message module: **the core is zero-language; language packs are optional** (issue #26).

Design premise (the user-specified scenario): after pulling the Einfacht suite,
the user **picks one language pack from a set of packs** -- English, Chinese, or
anything else. The core itself **does no language expression**; it emits message
codes with parameters. With no pack installed, it outputs a **structured,
readable, natural-language-free** form like `code(key=v)`.

In other words: **Chinese is not the source language**; Chinese is just one of
the optional packs. This removes two components of traditional i18n:

  · no "editing the Chinese copy forces retranslation" (there is no Chinese to
    edit; all languages are equal);
  · no fallback chain / draft states (a pack is either installed or not).

## interface

One value object + one entry point:

    Catalog.load(lang, tables=None) -> Catalog   # load a pack; absent/broken => MissingPack
    Catalog.null()                               # null pack (code + params only)
    M(code, **params) -> Message                 # the single construction point; uses the **current** Catalog

`Catalog` is an **immutable value**: a language name + that table. All rules
(the three-path conventions, the two pack shapes, broken packs must raise,
empty packs rejected, contract strings cannot be masqueraded) are locked inside
`Catalog.load` / `load_pack` -- callers and self-proof **cross the same seam**
(`Catalog`).

`M`'s signature and return shape are unchanged (`Message` is a `str` subclass
whose value is the rendered result, plus `.code` / `.params`), so every call
site needs **zero changes**.

## Why not module-level mutable state

This used to be a module-level mutable slot `_ACTIVE = [(lang, table)]`:
`activate()` wrote it, `M()` read it. Two concrete diseases:

  · **"who renders" had no scope** -- self-proof had to manually `bind()` in
    and out to restore, and forgetting polluted later cases;
  · **module objects split** -- when `i18n.py` runs as a script, `__main__` and
    `import i18n` are **two module objects** with one copy of state each
    (observed: en mode printed a bare code).

Now the scope is an explicit value (`bind(cat)` is pure scope), and the process
keeps a single `_DEFAULT` slot.

Contract literals (`OFF:` / `FATAL:` / `=== N PASS / M FAIL ===` / `PASS | ` /
`DOWN: `) **are literals at the emission point**, not data -- a language pack is
**structurally incapable** of producing them (`_validate`).

Honesty boundary: self-proof case labels are **id-ified** per user decision
(1C) -- self-proof output is machine-readable codes.
"""
from __future__ import annotations

import os
from types import MappingProxyType

# `machine` depends on the stdlib only => no cycle. Both the load-time criterion
# and the render-time sanitization come from it.
import machine  # noqa: E402


# ⚠️ **Lazy fetch**: this module is lazily imported by `gate`; a module-level
# reverse `import gate` would be circular. The values themselves are produced
# solely by `gate.zdir()` / `gate.tool_repo()` -- not computed again here.
def _tool_dir():
    import gate  # noqa: PLC0415
    return gate.zdir()


def _tool_repo_dir():
    import gate  # noqa: PLC0415
    return gate.tool_repo()
# The **built-in pack directory** used when `REFLECT_I18N` is unset (relative to
# the tool repo root).
BUILTIN_PACKS = "zreflect/lang"

# The criterion for contract prefixes now lives in **exactly one place**: the
# `machine.REJECT` table (judged line by line). There used to be a
# `_CONTRACT_SHAPES` here whose `^`-anchored `.match()` **judged only the first
# line** -- a language-pack value like `"ctx\nOFF: x"` was therefore accepted,
# and after rendering it became a standalone `OFF:` line that `run_phase`
# classified as `off` (observed: all ten line breaks hit). The same table is
# also shared by the producer (`gate.off`), the consumer (`gate.run_phase`) and
# shell consumers -- seven copies must drift (C4). See `zreflect/machine.py`.

# The CJK Unified Ideographs range. "Does this line contain Chinese" is the
# **criterion of the zero-language regime**, so it lives with the regime's owner
# (`check_i18n` and `harness` both take it from here instead of each writing a
# range constant -- C4).
CJK_LO, CJK_HI = 0x4E00, 0x9FFF


def han(text):
    """Contains CJK Unified Ideographs?"""
    return any(CJK_LO <= ord(c) <= CJK_HI for c in (text or ""))


_MAX_VALUE = 40            # max characters shown per value in the null pack (long commands must not flood the screen)


# ── Value objects ────────────────────────────────────────────────────────────

class MissingPack(Exception):
    """A language pack failed to load (missing / broken / illegal shape). The caller converts this to FATAL rc 2.

    **Carries `(code, params)` instead of an assembled sentence** (the hard
    requirement of issue #26: under `REFLECT_LANG=en`, nothing shown to the
    user may be Chinese).

    `str(e)` is **machine-readable** code shape; `e.code` / `e.params` are
    available to criteria.

    ## One exemption: **load-time** shape errors may render with this very pack

    `Catalog.load` has already read the merged table before `_validate` runs,
    so errors like "this value masquerades as a machine line" **do have a pack
    to consult** -- reporting the null shape (bare code) there is an unnecessary
    readability loss (caught in review: under `REFLECT_LANG=zh` this FATAL
    rendered as a bare code). Other errors (pack missing / broken shard)
    **genuinely** have no table to consult => keep using the null shape.
    """

    def __init__(self, code, **params):
        table = params.pop("_table", None)      # `_table` is not a message param
        self.code = code
        self.params = params
        super().__init__(_render(code, params, table))


class Catalog:
    """An **assembled language pack** (immutable value): `lang` is identity, `table` is data.

    `table=None` => null pack (zero-language core: outputs codes and params only).
    """

    __slots__ = ("lang", "table")

    def __init__(self, lang, table, _sealed=False):
        # ⚠️ `_sealed` is the **construction gate**: `Catalog` can only be built
        # by `null()` / `load()`, because `_validate` (the contract-string
        # defense) only runs inside `load()`. Previously a direct
        # `Catalog("xx", {"a.b": "OFF: masquerading"})` could bypass validation
        # and let a value masquerading as a machine line actually render
        # (observed). External construction is rejected outright.
        if not _sealed:
            raise TypeError(
                "Catalog can only be constructed by Catalog.null() / Catalog.load()"
                " (validation lives in load; bypassing it switches off the contract-string defense)")
        object.__setattr__(self, "lang", lang)
        object.__setattr__(self, "table", table)

    # Immutable: `Catalog` is a value; nobody may mutate its table -- doing so
    # would let "the same pack" render differently at different times, which is
    # exactly the nondeterminism this repo exists to eliminate.
    def __setattr__(self, name, value):
        raise AttributeError("Catalog is immutable")

    @classmethod
    def null(cls):
        """The null pack: no language, outputs `code(key=value)` only."""
        return cls(None, None, _sealed=True)

    @classmethod
    def load(cls, lang, tables=None):
        """Load a pack. `lang=None` => null pack; a name that fails to load => `MissingPack`.

        This is the **single assembly point** (fixture injection goes through
        `tables=`, zero file I/O).
        """
        if lang is None:
            return cls.null()
        if tables is not None:
            table = tables.get(lang)
            if table is None:
                raise MissingPack("i18n.injected_lang_absent", lang=lang)
        else:
            table = load_pack(lang)
            if not table:
                base = pack_dir()
                raise MissingPack("i18n.pack_absent", lang=lang,
                                  single=os.path.join(base, "%s.json" % lang),
                                  directory=os.path.join(base, lang))
        _validate(table, lang)
        # ⚠️ Store an **immutable copy**: `__slots__` + `__setattr__` only block
        # "swapping the reference"; they cannot block in-place dict mutation --
        # observed: `cat.table['locks.ok']='HAHA'` succeeded and every later
        # render was wrong. `Catalog` is a **value**; its data must be truly
        # immutable (`MappingProxyType` is a read-only view that neither copies
        # nor adds overhead).
        return cls(lang, MappingProxyType(dict(table)), _sealed=True)

    def render(self, code, params):
        """Render (code, params) into text; this table lacks the code => null shape.

        Degrading to the code is the **only honest** choice (inventing sentences
        is forbidden), but it **must** be caught by a gate:
        `knobs.pack_coverage_problems()` guarantees "every code used by the
        source exists in every installed pack". Degradation happens in exactly
        one place, the criterion lives outside -- division of labor with
        `_validate`.
        """
        return _render(code, params, self.table)

    def msg(self, code, **params):
        """Build a `Message` from this Catalog (the value is already rendered)."""
        return Message(code, params, self)


class Message(str):
    """A message. **The value is the rendered result**; `.code` / `.params` are identity and data.

    Being a str subclass is deliberate: existing consumers like
    `finish()` / `if problems` / `"  · " + p` / `len(...)` all keep working.
    """

    __slots__ = ("code", "params", "forged")

    def __new__(cls, code, params, catalog):
        # ⚠️ **Sanitize after rendering**: a clean template does not mean a clean
        # rendered result -- params (filenames, document lines, exception text)
        # are runtime data; 144 call sites feed them into templates as `%s`, and
        # 58 templates start with a placeholder (`%(name)s: …`). Observed: when a
        # file named `"evil\nOFF: gate not configured"` was scanned, the render
        # produced a forged `OFF:` line and `run_phase` classified the whole
        # gate as off.
        #
        # Load time **rejects** in the language pack; render time **only
        # sanitizes** -- crashing a half-finished gate because a filename
        # contains a newline turns something the author cannot control into an
        # incident.
        #
        # ⚠️ **Render exactly once**: `.forged` is computed in `__new__` and
        # attached to the instance; `__init__` only reads it. Previously both
        # methods each called `catalog.render()` + `machine.clean()` -- every
        # message rendered twice (caught in review).
        raw = catalog.render(code, params)
        text, forged = machine.clean(raw)
        obj = super().__new__(cls, text)
        obj.forged = forged
        return obj

    def __init__(self, code, params, catalog):
        self.code = code
        self.params = params


def _fmt_value(v):
    """How a parameter value is displayed inside the null pack.

    Uses `repr`: it **handles nested quotes automatically** (`find . -name
    '*.md'` renders as `"find . -name '*.md'"`); hand-assembling `'%s'`
    produces a malformed string when the value contains quotes (stepped on:
    `command='find . -name '*.md' | wc -l'`). Long values are truncated.
    """
    s = repr(v)
    if len(s) > _MAX_VALUE:
        s = s[:_MAX_VALUE - 1] + "…" + s[-1] if s[-1] in "\"'" else s[:_MAX_VALUE] + "…"
    return s


def _render(code, params, table):
    """Render (code, params) into text. `table=None` => null-pack shape.

    Null-pack format: `code(key='py_lines', actual=6180, expected=6014)`.
    **Parameter names must be complete English words** (`key`, not `k`;
    `actual`, not `got`) -- this is the null pack's only source of
    "readability": no sentences, but the names are self-explanatory.

    With no params, only the code is printed. **No installation hint** (that
    itself would be natural language, violating zero-language).
    """
    if table is not None and code in table:
        return table[code] % params
    if not params:
        return str(code)
    inner = ", ".join("%s=%s" % (k, _fmt_value(params[k]))
                      for k in sorted(params))
    return "%s(%s)" % (code, inner)


def _validate(table, lang):
    """Validate pack shape: values must not masquerade as machine lines (contract strings are structurally untranslatable).

    ⚠️ Judged **line by line** (`machine.reject`), not just the first line --
    a `^`-anchored `.match()` used to look only at line one, so `"ctx\\nOFF: x"`
    was accepted and, once rendered, became a standalone `OFF:` line (observed:
    all ten line breaks hit). A language pack is a **static** asset the author
    can fix by rephrasing => here we **reject loudly** (FATAL rc 2), unlike
    render output which is only sanitized.
    """
    if not isinstance(table, dict) or not table:
        raise MissingPack("i18n.pack_empty", lang=lang)
    for code, value in table.items():
        if not isinstance(value, str):
            raise MissingPack("i18n.value_not_string", lang=lang, key=code)
        hit = machine.reject(value)
        if hit:
            # This error copy lives in the **pack already installed in the
            # current process** (`_DEFAULT`), not in the table being validated
            # -- the latter can only contain the offending value. Render with
            # the current Catalog's table; fall back to the null shape if it
            # cannot be read (honest, no invention).
            cur = _DEFAULT[0].table if _DEFAULT else None
            raise MissingPack("i18n.value_masquerades_contract", _table=cur,
                              lang=lang, key=code, line=hit[0],
                              value=value[:40])


# ── Pack location and reading (the repo-wide single resolution point) ───────

def pack_dir():
    """Absolute path of the language pack directory -- the **repo-wide single resolution point**. Three conventions:

      · **`REFLECT_I18N` unset** => the suite's bundled built-in packs
        `BUILTIN_PACKS`, anchored at the **tool repo root** ("pull the suite
        and it works"; cross-repo fixtures depend on this -- anchored relative
        to GATE_REPO, every gate in the fixture raised MissingPack, observed
        0/15 all red).
      · **Relative path set** => relative to the **audited repo root**
        (`GATE_REPO`). Same convention as name-type knobs like `REFLECT_DOCS`
        -- only then does "a name relative to the repo root" written in the
        env file match.
      · **Absolute path set** => used as-is.
    """
    raw = os.environ.get("REFLECT_I18N", "").strip()
    if not raw:
        return os.path.join(_tool_repo_dir(), BUILTIN_PACKS)
    if os.path.isabs(raw):
        return raw
    # Lazy import: this module is lazily imported by `gate`; a module-level
    # reverse import would be circular.
    import gate  # noqa: PLC0415
    return os.path.join(gate.GATE_REPO, raw)


def _load_shards(base, lang):
    """`<lang>/*.json` shards (files split by namespace for parallel development; later ones override the same code).

    ⚠️ **Broken JSON must not be silently skipped**: there used to be an
    `except: continue`, so a broken shard only sent those codes back to bare
    codes while **rc stayed 0** -- "half-installed looked installed"
    (observed). Now broken shards / non-objects always raise `MissingPack`.
    """
    import json  # noqa: PLC0415
    d = os.path.join(base, lang)
    if not os.path.isdir(d):
        return {}
    table = {}
    for n in sorted(os.listdir(d)):
        if not n.endswith(".json"):
            continue
        p = os.path.join(d, n)
        try:
            with open(p, encoding="utf-8") as fh:
                part = json.load(fh)
        except (OSError, ValueError) as e:
            raise MissingPack("i18n.shard_unreadable", lang=lang,
                              path=p, error=e) from e
        if not isinstance(part, dict):
            raise MissingPack("i18n.shard_not_object", lang=lang, name=n)
        table.update(part)
    return table


def _load_single(base, lang):
    """`<lang>.json` single file (small repos / boilerplate). A broken file raises `MissingPack` the same way."""
    import json  # noqa: PLC0415
    single = os.path.join(base, "%s.json" % lang)
    if not os.path.exists(single):
        return {}
    try:
        with open(single, encoding="utf-8") as fh:
            part = json.load(fh)
    except (OSError, ValueError) as e:
        raise MissingPack("i18n.single_unreadable", lang=lang,
                          path=single, error=e) from e
    if not isinstance(part, dict):
        raise MissingPack("i18n.single_not_object", lang=lang, path=single)
    return part


def load_pack(lang):
    """Read a language pack's **merged table** (the same table `Catalog.load` sees).

    Both shapes are recognized, and **always merged**: `<lang>/*.json` shards +
    `<lang>.json` single file (the latter overrides the same code).

    The merge must mirror the real loader -- any reader that reads only one
    shard forks from the loader (stepped on: self-proof read per shard while a
    doc-endorsed single-file pack was judged red).

    Missing / empty => `{}` (no raise): self-proof assertions that "read the
    real pack" go red on the spot against an empty table. What is distinguished
    is "absent" vs "present but broken": the latter is a configuration incident
    and must be loud.

    The two shapes are one helper each (`_load_shards` / `_load_single`): each
    has its own error codes (`shard_*` / `single_*`); fused together, those two
    try/except blocks would make "which code belongs to which shape" something
    you can only learn by reading the code.
    """
    base = pack_dir()
    table = _load_shards(base, lang)
    table.update(_load_single(base, lang))
    return table


# ── Entry points: the current Catalog (process default) and scope ───────────

NULL = object()                 # sentinel for "explicitly ask for the null pack" (distinct from "not passed")
_DEFAULT = [Catalog.null()]     # process default (`activate` writes it; `bind` does not touch it)


def _resolve_lang(lang):
    """`lang` -> the effective language name (None = null pack). **The single vetting point**.

    `NULL` => explicit null (ignores the env var); `None` => falls back to
    `REFLECT_LANG`; a string => as-is. Both `bind()` and `activate()` go
    through here.
    """
    if lang is NULL:
        return None
    if lang is not None:
        return lang
    return os.environ.get("REFLECT_LANG", "").strip() or None


def _acquire(lang=None, tables=None):
    """`lang` -> an assembled `Catalog` (`NULL` / `None` can both mean the null pack)."""
    return Catalog.load(_resolve_lang(lang), tables)


def _current():
    """The currently effective Catalog (process default)."""
    return _DEFAULT[0]


def M(code, **params):
    """Build a message with the **current** Catalog. `code` must be a literal (the coverage gate rejects variable codes -- otherwise the catalog cannot be proven complete)."""
    return _current().msg(code, **params)


class _Bound:
    """`bind()`'s context: swaps the current Catalog and restores it on exiting the scope (reentrant)."""

    def __init__(self, catalog):
        self.catalog = catalog
        self.prev = None

    def __enter__(self):
        self.prev = _DEFAULT[0]
        _DEFAULT[0] = self.catalog
        return self.catalog

    def __exit__(self, *exc):
        _DEFAULT[0] = self.prev
        return False


def bind(catalog):
    """Install a Catalog (context manager, **pure scope**: writes no env, touches no default).

    `catalog` may be a `Catalog`, a language name, or the `NULL` sentinel:

        with bind("zh"): ...
        with bind(NULL): ...                                # explicit null (ignores the env var)
        with bind(Catalog.load("en", tables={...})): ...     # injection (zero file I/O)
    """
    if isinstance(catalog, Catalog):
        return _Bound(catalog)
    return _Bound(_acquire(catalog))


def activate(lang=None, tables=None):
    """Process-level default (called once by the CLI entry). Returns the effective language name (None = null pack).

    Difference from `bind()`: `bind` is **scope** (restored on enter/exit);
    `activate` is the **process default** (set once, no need for `with` at
    every site).

    `lang=NULL` means the same as in `bind`: the explicit null pack (ignores
    `REFLECT_LANG`). Pack absent / broken => `MissingPack` (converted to
    FATAL rc 2 by `gate.activate_or_fatal`).
    """
    cat = _acquire(lang, tables)
    _DEFAULT[0] = cat
    return cat.lang


# ── Self-proof ───────────────────────────────────────────────────────────────

def _raises(fn):
    """This call must raise MissingPack (used by negative assertions)."""
    try:
        fn()
    except (MissingPack, SystemExit):
        return True
    return False


def _scoped(catalog, fn):
    """Run fn inside the catalog's scope (restored on enter/exit)."""
    b = bind(catalog)
    b.__enter__()
    try:
        return fn()
    finally:
        b.__exit__(None, None, None)


def _as_null(fn):
    """Run fn inside an **explicit null** scope.

    ⚠️ Shape assertions must carry their own null scope: once the entry point
    `activate()` has set zh / en, cases that read `M(...)` directly all go red
    (observed: KeyError under `REFLECT_LANG=zh gates-selftest.sh`) -- an
    assertion that does not declare its scope degenerates into "tested by
    whatever environment it happens to run in".
    """
    return _scoped(NULL, fn)


def _construct_sealed():
    """Direct external construction of `Catalog` must be rejected (only null() / load() may build it)."""
    try:
        Catalog("xx", {"a.b": "OFF: masquerading"})
        return False          # it actually constructed = this case is red
    except TypeError:
        return True


def _cases_fixture():
    """Fixture (the setup section of the original `_cases`, moved verbatim)."""
    fake = {
        # Placeholder names must match the **real pack** (`key` / `actual` /
        # `expected`): abbreviating would make this self-proof endorse a naming
        # scheme the real pack does not use (observed KeyError).
        "replay.no_cmd": "`%(key)s` has no replay command",
        "replay.mismatch": "`%(key)s` replay != ledger: %(actual)s vs %(expected)s",
    }
    bad_shape = {"ok": "OFF: not configured"}          # masquerading as a machine line
    empty = {}

    en_cat = Catalog.load("en", {"en": fake})

    def with_en(fn):
        return _scoped(en_cat, fn)

    def said(**params):
        return _as_null(lambda: str(M("probe.code", **params)))

    return {'fake': fake, 'bad_shape': bad_shape, 'empty': empty, 'en_cat': en_cat, 'with_en': with_en, 'said': said}


def _cases_null(fx):
    """See `_cases()`: 7 cases in this group."""
    said = fx["said"]
    return [
    # ① Normal case does not report -- null-pack shape
    ("i18n.null_no_params",
     lambda: _as_null(lambda: str(M("gate.title.facts"))
                     == "gate.title.facts")),
    ("i18n.null_with_params",
     lambda: _as_null(lambda: str(M("replay.no_cmd", key="py_lines"))
                     == "replay.no_cmd(key='py_lines')")),
    ("i18n.null_params_sorted",
     lambda: _as_null(lambda: str(M("x", bb=2, aa=1)) == "x(aa=1, bb=2)")),
    # `repr` must handle nested quotes: hand-assembled `'%s'` produces a
    # malformed string when the value contains quotes.
    ("★ i18n.repr_quotes",
     lambda: (lambda s: s.count("'") >= 2 and s.startswith("probe.code("))(
         said(command="find . -name '*.md' | wc -l"))),
    ("i18n.null_long_value_truncated",
     lambda: len(said(cmd="f" * 200)) < 80),
    # The `NULL` sentinel means the same thing at all three entries: `bind` /
    # `resolve` / `activate`.
    ("★ i18n.null_sentinel_consistent", lambda: _null_consistent()),
    # ③ Empty input must report
    ("★ i18n.empty_code",
     lambda: _as_null(lambda: str(M("")) == "")),
    ]


def _cases_pack(fx):
    """See `_cases()`: 7 cases in this group."""
    bad_shape, empty, with_en = fx["bad_shape"], fx["empty"], fx["with_en"]
    return [
    ("i18n.pack_applied",
     lambda: with_en(lambda: str(M("replay.no_cmd", key="f.py"))
                     == "`f.py` has no replay command")),
    # ② The cases that must report, report
    ("★ i18n.pack_empty",
     lambda: _raises(lambda: _validate(empty, "xx"))),
    ("★ i18n.pack_masquerades_contract",
     lambda: _raises(lambda: _validate(bad_shape, "xx"))),
    # A missing pack must **report**, not silently fall back to Chinese.
    ("★ i18n.missing_pack_raises",
     lambda: _raises(lambda: Catalog.load("xx", {"zh": {}}))),
    # An empty pack is not "translated" (tier one of the zero-standby guard).
    ("★ i18n.empty_pack_rejected",
     lambda: _raises(lambda: Catalog.load("xx", {"xx": {}}))),
    # **A broken shard must raise on the spot**: silently skipping means those
    # messages degrade to bare codes while rc stays 0.
    ("★ i18n.broken_shard_raises",
     lambda: _broken_pack_raises()),
    # Machine criterion for `pack_dir`'s three conventions (the most visible
    # contract; it used to have zero self-proof).
    ("★ i18n.pack_dir_three_rules", lambda: _pack_dir_rules_ok()),
    ]


def _cases_catalog(fx):
    """See `_cases()`: 6 cases in this group."""
    fake = fx["fake"]
    return [
    ("i18n.message_is_str",
     lambda: (lambda m: (bool([m]), "  · " + m, len([m]))[0] is True)(M("a"))),
    # `.code` / `.params` are identity, independent of language. Must be built
    # under null (`Message` renders at construction: a fabricated code hitting
    # the real pack would KeyError).
    ("i18n.code_readable",
     lambda: _as_null(lambda: M("replay.no_cmd", key=1).code
                     == "replay.no_cmd")),
    ("i18n.params_readable",
     lambda: _as_null(lambda: M("replay.no_cmd", key="py_lines").params
                     == {"key": "py_lines"})),
    ("i18n.activate_sets_default",
     lambda: _activate_ok("en", {"en": fake})),
    # **`Catalog`'s data must be truly immutable**: `__slots__` + `__setattr__`
    # only block attribute assignment, not in-place dict mutation (observed:
    # `cat.table[...]=...` succeeded and every render was wrong).
    ("★ i18n.catalog_data_immutable", lambda: _catalog_immutable()),
    # **Construction gate**: `Catalog(…)` cannot be built externally -- that
    # would bypass `_validate` inside `load()` (the contract-string defense)
    # and let a translation masquerading as `OFF:` actually render (observed).
    ("★ i18n.catalog_construct_sealed", lambda: _construct_sealed()),
    ]


def _cases():
    """Assemble the 3 groups of fixture assertions. **Assembles only** -- the criteria live in the group functions."""
    fx = _cases_fixture()
    return (
    _cases_null(fx)
    + _cases_pack(fx)
    + _cases_catalog(fx)
    )


def _catalog_immutable():
    """`Catalog`'s table must not be mutable in place (both attribute assignment and dict writes must fail)."""
    cat = Catalog.load("en", {"en": {"a.b": "ok"}})
    try:
        cat.lang = "zh"
        return False                  # attribute assignment actually succeeded = this case is red
    except AttributeError:
        pass
    try:
        cat.table["a.b"] = "changed"
        return False                  # in-place dict write succeeded = this case is red
    except TypeError:
        pass
    return str(cat.msg("a.b")) == "ok"


def _activate_ok(lang, tables):
    """After `activate()`, does `M()` render from that pack (restored afterwards)."""
    prev = _DEFAULT[0]
    try:
        activate(lang, tables)
        return str(M("replay.no_cmd", key="f.py")) == "`f.py` has no replay command"
    finally:
        _DEFAULT[0] = prev


def _null_consistent():
    """The `NULL` sentinel means the same thing at all three entries: `bind` / `resolve` / `activate`.

    ⚠️ **Must set `REFLECT_LANG` before verifying**: previously this case was
    green even in the default (unset) environment while `resolve(NULL)`
    wrongly fell back to the env var -- the whitewashed shape of "tested by
    whatever environment it happens to run in" (observed: env unset -> True,
    env=zh -> False). The assertion builds the environment that **can make it
    red** itself, instead of waiting for the outside environment to oblige.
    """
    prev = _DEFAULT[0]
    saved_env = os.environ.get("REFLECT_LANG")
    try:
        # Build the condition "an env var exists" that can expose broken NULL logic
        os.environ["REFLECT_LANG"] = "zh"
        if _resolve_lang(NULL) is not None:
            return False
        with bind(NULL) as cat:
            if cat.lang is not None or cat.table is not None:
                return False
            if str(M("probe.code", key="x")) != "probe.code(key='x')":
                return False
        return activate(NULL) is None and _current().lang is None
    finally:
        _DEFAULT[0] = prev
        if saved_env is None:
            os.environ.pop("REFLECT_LANG", None)
        else:
            os.environ["REFLECT_LANG"] = saved_env


def _broken_pack_raises():
    """A broken shard must raise `MissingPack`, not be silently skipped (temp directory, deleted after use)."""
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    d = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(d, "xx"))
        with open(os.path.join(d, "xx", "bad.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("{ not json")
        prev = os.environ.get("REFLECT_I18N")
        os.environ["REFLECT_I18N"] = d
        try:
            try:
                load_pack("xx")
            except MissingPack:
                return True
            return False           # silently skipped = this assertion is red
        finally:
            if prev is None:
                os.environ.pop("REFLECT_I18N", None)
            else:
                os.environ["REFLECT_I18N"] = prev
    finally:
        shutil.rmtree(d, True)


def _pack_dir_rules_ok():
    """Verify `pack_dir()`'s three conventions one by one (each was a pit stepped on; do not verify just one)."""
    import gate  # noqa: PLC0415
    prev = os.environ.get("REFLECT_I18N")
    try:
        env = os.environ
        # ① Unset => the tool's bundled pack directory (cross-repo fixtures depend on it)
        env.pop("REFLECT_I18N", None)
        if not os.path.isdir(pack_dir()):
            return False
        # ② Absolute path => as-is (no prefix is ever joined)
        probe = os.path.abspath(os.sep)
        env["REFLECT_I18N"] = probe
        if pack_dir() != probe:
            return False
        # ③ Relative path => the **audited repo root**. The two repo roots must
        #    be **genuinely separated** for this to be verifiable: with
        #    GATE_REPO unset they hold the same value, so a wrong convention
        #    also passes (stepped on).
        env["REFLECT_I18N"] = "rel/probe"
        saved = gate.GATE_REPO
        gate.GATE_REPO = os.sep + "tmp-probe-repo"
        try:
            return pack_dir() == os.path.join(gate.GATE_REPO, "rel/probe")
        finally:
            gate.GATE_REPO = saved
    finally:
        if prev is None:
            os.environ.pop("REFLECT_I18N", None)
        else:
            os.environ["REFLECT_I18N"] = prev


def _selftest():
    import sys  # noqa: PLC0415

    from gate import main_selftest_or  # noqa: PLC0415

    def _run(argv):
        # Goes through M(): under `REFLECT_LANG=en` this must speak English too.
        print(M("i18n.module_banner"), file=sys.stderr)
        return 2
    return main_selftest_or(sys.argv[1:],
                            M("gate.title.i18n"), _cases, _run)


from gate import module_meta  # noqa: E402

MODULE = module_meta("i18n", "zero-language core + optional language packs (Catalog/M/bind/acquire)",
                     selftest=True)

if __name__ == "__main__":
    import sys  # noqa: PLC0415
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    # ⚠️ Cannot do `sys.exit(_selftest())` directly: when this file runs as a
    # **script**, this code is `__main__`, while the `import i18n` inside
    # `gate.activate_or_fatal` loads a **different module object** (a copy of
    # the same-named module). `_DEFAULT` is module-level state => activation is
    # set on the copy while rendering reads `__main__`'s => forever the null
    # pack. Delegating to the module copy makes both sides the same object.
    import i18n as _mod  # noqa: PLC0415
    sys.exit(_mod._selftest())
