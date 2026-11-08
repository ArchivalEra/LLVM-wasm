#!/usr/bin/env python3
"""Knob registry (the **single roster** of REFLECT_*): register once, derive everywhere.

The "knob" concept previously had no module: reads were scattered across gates,
declarations lived as docstring prose, judgment data sat in check_envfile's
FILE_KNOBS, and the roster was found by scanning all text — the scanner explicitly
said "mentions in docstrings count too", so **phantom knobs** like REFLECT_AB /
REFLECT_PINS that only existed in documentation made it onto the roster, passed
the typo check, and were **silently ineffective** when a user actually exported
them (Phase 0 already turned them into real implementations). Three modules each
held a mutually inconsistent version of "what the knobs are" — the shallow-seam
disease exactly.

This module collapses that into one interface: **registered = exists**. Name,
kind, default, one-line semantics, all registration-based; check_envfile's
judgment reads from here; a REFLECT_* token appearing in the scan surface but
absent from the roster = phantom / typo ⇒ report (a docstring mention doesn't
count, registration does); REFLECT_* names appearing in the three-language
READMEs ⊆ roster (reverse assertion, executed by envfile's self-evidence).

Kinds — envfile uses them to decide whether to check existence:

  file    value is a filename relative to the repo root (existence is checked;
          empty default = not configured means not enabled)
  list    comma-separated list of filenames (each checked)
  dir     value is a directory name relative to the repo root
  number  a number (seconds / days / thresholds; empty default = that rule
          explicitly says not enabled)
  flag    enumerated switch (e.g. off)
  value   arbitrary string (overrides / names / numbered lists)

⚠️ Roster discipline: **only register knobs that are actually read via
`os.environ.get`**. Saving a seat for a "might use someday" name = manufacturing
your own phantoms — the phantom-knob shape lesson: docs promised it, code doesn't
read it, the user configures it and it silently does nothing. Not even examples
here spell out concrete unregistered names (the scan reconciliation would report
the example as a phantom — the reconciliation ignores context, which is exactly
its strength).
"""
from __future__ import annotations

import os
import re
import sys

import gate  # noqa: E402
from gate import module_meta  # noqa: E402
from i18n import NULL, Catalog, M, bind, load_pack, pack_dir  # noqa: E402


class _Semantic(str):
    """A knob's one-line semantics (third item of `REGISTRY`): **lazily rendered**
    user-visible text.

    `REGISTRY` is built at import time, while language packs are only
    `activate()`d inside the entry `main_selftest_or` — calling `M(...)` directly
    here would render at construction time and be **permanently stuck on the
    null pack** (observed shape: a zh user sees the code instead of the
    semantics). So we store the code and re-render per the **current** language
    at `__str__` time (consumers only format it via `%(entry)s`; see
    check_envfile's file_missing / dir_missing messages).
    """

    __slots__ = ("code",)

    def __new__(cls, code):
        obj = str.__new__(cls, code)
        obj.code = code
        return obj

    def __str__(self):
        return str(M(self.code))


# name -> (kind, default, one-line semantics). Default = the fallback name each
# consumer uses when the knob is unset.
# Semantics follow core zero-language (issue #26): codes go into language packs,
# the core never contains natural language.
REGISTRY = {
    "REFLECT_FACTS": ("file", "FACTS.json",
                      _Semantic("knobs.sem.reflect_facts")),
    "REFLECT_DOC": ("file", "STATE.md",
                    _Semantic("knobs.sem.reflect_doc")),
    "REFLECT_DOCS": ("list", "STATE.md,AGENTS.md,PRINCIPLES.md,README.md,README.zh.md,README.de.md",
                     _Semantic("knobs.sem.reflect_docs")),
    "REFLECT_HISTORY_SECS": ("value", "",
                             _Semantic("knobs.sem.reflect_history_secs")),
    "REFLECT_RETIRED": ("value", "",
                        _Semantic("knobs.sem.reflect_retired")),
    "REFLECT_NAKED_MIN": ("number", "100",
                          _Semantic("knobs.sem.reflect_naked_min")),
    "REFLECT_STALE_DAYS": ("number", "",
                           _Semantic("knobs.sem.reflect_stale_days")),
    "REFLECT_REPLAY": ("flag", "",
                       _Semantic("knobs.sem.reflect_replay")),
    "REFLECT_REPLAY_TIMEOUT": ("number", "10",
                               _Semantic("knobs.sem.reflect_replay_timeout")),
    "REFLECT_READMES": ("list", "README.md,README.zh.md,README.de.md",
                        _Semantic("knobs.sem.reflect_readmes")),
    "REFLECT_RETRACTIONS": ("file", "retractions.json",
                            _Semantic("knobs.sem.reflect_retractions")),
    "REFLECT_QUESTIONS": ("dir", "questions",
                          _Semantic("knobs.sem.reflect_questions")),
    "REFLECT_ENV_FILE": ("value", "Einfacht.env",
                         _Semantic("knobs.sem.reflect_env_file")),
    "REFLECT_ENV_HINT": ("flag", "",
                         _Semantic("knobs.sem.reflect_env_hint")),
    "REFLECT_INVARIANTS": ("file", "",
                           _Semantic("knobs.sem.reflect_invariants")),
    "REFLECT_INSTRUMENTS": ("file", "",
                            _Semantic("knobs.sem.reflect_instruments")),
    "REFLECT_INSTRUMENT_DAYS": ("number", "",
                                _Semantic("knobs.sem.reflect_instrument_days")),
    "REFLECT_DOCTOR": ("file", "doctor.json",
                       _Semantic("knobs.sem.reflect_doctor")),
    "REFLECT_DOCTOR_TIMEOUT": ("number", "2",
                               _Semantic("knobs.sem.reflect_doctor_timeout")),
    "REFLECT_WORLD": ("file", "world.json",
                      _Semantic("knobs.sem.reflect_world")),
    "REFLECT_WORLD_LINE": ("value", "",
                           _Semantic("knobs.sem.reflect_world_line")),
    "REFLECT_AB": ("file", "ab.json",
                   _Semantic("knobs.sem.reflect_ab")),
    "REFLECT_PINS": ("file", "pins.json",
                     _Semantic("knobs.sem.reflect_pins")),
    "REFLECT_LOCKS": ("file", "upstream-lock.json",
                      _Semantic("knobs.sem.reflect_locks")),
    "REFLECT_MEASURE_MODULE": ("value", "",
                               _Semantic("knobs.sem.reflect_measure_module")),
    "REFLECT_PHASES": ("value", "",
                       _Semantic("knobs.sem.reflect_phases")),
    # Explicitly opt out of this suite's principles (for repos that don't want
    # to run those judgment commands on every commit).
    "REFLECT_NO_PRINCIPLES": ("flag", "",
                              _Semantic("knobs.sem.reflect_no_principles")),
    "REFLECT_LANG": ("value", "",
                     _Semantic("knobs.sem.reflect_lang")),
    "REFLECT_I18N": ("dir", "",
                     _Semantic("knobs.sem.reflect_i18n")),
    "REFLECT_I18N_ROOT": ("dir", "",
                          _Semantic("knobs.sem.reflect_i18n_root")),
    "REFLECT_SNAPSHOT_ROOT": ("dir", "",
                              _Semantic("knobs.sem.reflect_snapshot_root")),
}

KINDS = ("file", "list", "dir", "number", "flag", "value")


def knobs_table(rows=None):
    """The **human-readable table** of the knob roster (`--list` output). **Pure function**.

    Semantics go through `_Semantic` (`str()` renders per the current language
    pack); with no language pack installed the output is a code like
    `knobs.sem.<name>` — the honest "no language pack installed".
    """
    rows = REGISTRY if rows is None else rows
    lines = ["| knob | kind | default | meaning |", "|---|---|---|---|"]
    for name in sorted(rows):
        kind, default, sem = rows[name]
        lines.append("| `%s` | %s | %s | %s |"
                     % (name, kind, default or "—", sem))
    return "\n".join(lines)

# Placeholder tokens (`%(name)s`) — self-evidence reconciles whether the zh / en
# placeholder names agree.
_PLACEHOLDER_RE = re.compile(r"%\((\w+)\)")

# Knob token: REFLECT_ + uppercase. The **left boundary is required** — without
# it, the retraction example text (a `ZCODE_`-prefixed token) gets cut mid-token
# into a fake token, and the three-language README reconciliation reports one
# false positive per language (observed hit). ⚠️ This file **never spells out**
# that fake token literal.
_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])REFLECT_[A-Z0-9_]+")


def _py_sources(base):
    """See `gate.py_sources`: one implementation only (this keeps just the module name)."""
    import gate  # noqa: PLC0415
    return gate.py_sources(base)


def scan_surface_problems(py_dir=None):
    """REFLECT_* tokens that appear in the scan surface (zreflect/*.py) but are
    absent from the roster.

    **Roster self-consistency**, independent of whether any carrier
    (Einfacht.env) exists — it belongs to the "roster" itself (C3): this
    judgment used to be welded behind check_envfile.run()'s "carrier exists"
    precondition, and since this repo has no Einfacht.env, the phantom guard
    never executed (observed hit). `py_dir` is injectable (fake source tree for
    self-evidence).
    """
    d = py_dir if py_dir is not None else gate.zdir()
    toks = set()
    for _name, text in _py_sources(d):
        toks.update(_TOKEN_RE.findall(text))
    out = []
    for tok in sorted(toks):
        if tok not in REGISTRY:
            out.append(M("knobs.phantom_token", token=tok))
    return out


def readme_names():
    """The list of three-language READMEs (`REFLECT_READMES`; default is the one
    registered in `REGISTRY`).

    ⚠️ Two reconcilers previously each wrote the same "parse env var + default
    literal" block, so the default list had **three** producers (two literals +
    one REGISTRY entry) — exactly the shape "a number is produced once" is meant
    to eliminate. Now only `REGISTRY` remains.
    """
    raw = os.environ.get("REFLECT_READMES", "").strip()
    if not raw:
        raw = REGISTRY["REFLECT_READMES"][1]      # default from the registry
    return [s.strip() for s in raw.split(",") if s.strip()]


def docs_names():
    """The list of live state documents (`REFLECT_DOCS`; default is the one
    registered in `REGISTRY`).

    ⚠️ Same disease as `readme_names()`, and it had **already drifted**:
    `check_stale` and `check_retractions` each hard-coded a **five-doc** literal
    default while the registry had **six** (plus `PRINCIPLES.md`). Observed:
    with the knob unset, neither gate's `DOCS` contained `PRINCIPLES.md` — so
    "the single producer of the rules" was never in their scan surface, and
    retraction text or stale assertions written in the principles document would
    never be seen by those two gates.

    The cure for "two copies that must agree" is one producer, not fixing both copies.
    """
    raw = os.environ.get("REFLECT_DOCS", "").strip()
    if not raw:
        raw = REGISTRY["REFLECT_DOCS"][1]         # default from the registry
    return [s.strip() for s in raw.split(",") if s.strip()]


FLAG_TRUTHY = ("1", "true", "yes", "on")
FLAG_FALSY = ("0", "false", "no", "off")


def flag(name):
    """Read a flag-kind knob; returns three states: `True` (on) / `False` (off) /
    `None` (unset).

    ⚠️ The flag **vocabulary** previously existed twice with different case
    handling:
      · `gate._maybe_hint` / `check_facts_replay` used `.lower() == "off"`
        (case-insensitive, only recognizing `off`);
      · `doc.accepts_principles` used `.strip() in ("1", "true", "yes")`
        (**case-sensitive** — observed: `REFLECT_NO_PRINCIPLES=TRUE` silently
        did nothing; the user thought principle replay was off but it kept
        running).
    Both were registered in `REGISTRY` as `kind="flag"`, yet nobody defined
    "what a flag is".

    Three states, not two: `None` = unset (the caller applies its own default),
    which is a different decision from "explicitly off", and callers often need
    to distinguish (the off state must be **stated explicitly**; silence = fake
    green).
    """
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return None                   # unset (including empty string) => caller default
    if raw in FLAG_TRUTHY:
        return True
    if raw in FLAG_FALSY:
        return False
    return None                       # unrecognized word => let the caller decide


def questions_dir(repo_root=None):
    """The open-questions directory name (`REFLECT_QUESTIONS`; default is the
    registry's `questions`).

    ⚠️ **Must `.strip()`**: `REFLECT_QUESTIONS=` (set to the empty string) is a
    common form of "unset" — `export X=$MAYBE_UNSET` in git hooks does exactly
    that. `check_questions.collect` previously used `os.environ.get(...)`
    without stripping; the empty string resolved through
    `os.path.join(repo_root, "")` to **the repo root itself**, pulling
    `STATE.md` / `README.md` / `AGENTS.md` all in as open questions and
    reporting a pile of false `questions.missing_status` problems (observed).

    The other two consumers of the same value (`facts._init_questions_dir` /
    `next._open_question_names`) already stripped — three copies of the
    judgment, one wrong.
    """
    raw = os.environ.get("REFLECT_QUESTIONS", "").strip()
    return raw or REGISTRY["REFLECT_QUESTIONS"][1]


def questions_path(repo_root=None):
    """The **absolute path** of the open-questions directory (relative to the audited repo)."""
    root = repo_root or gate.GATE_REPO
    return os.path.join(root, questions_dir())


def _text_of(name, files=None):
    """Read a file's text. Returns `None` = absent / unreadable (**not the empty
    string**).

    If `files` is given, use it (self-evidence injects a fake filesystem);
    otherwise read from `gate.GATE_REPO`. "Missing" and "empty file" collapse to
    None here — callers skip in both cases, because "not in the list" and "the
    file is empty" mean the same in these three reconcilers (nothing to compare).
    """
    if files is not None:
        return files.get(name)
    p = os.path.join(gate.GATE_REPO, name)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def readme_problems(files=None):
    """REFLECT_* names that appear in the three-language READMEs (the
    REFLECT_READMES list) but are absent from the roster (documentation-side
    phantom defense). `files` injects a fake filesystem (for self-evidence)."""
    out = []
    for name in readme_names():
        text = _text_of(name, files)
        if text is None:
            continue
        for tok in sorted(set(_TOKEN_RE.findall(text))):
            if tok not in REGISTRY:
                out.append(M("knobs.readme_phantom", file=name, token=tok))
    return out




def declared_vs_read_problems(gates, sources=None):
    """C4 reconciliation (1): knobs a gate **declares** it consumes ⊆ the knobs it
    **actually reads**.

    The declaration lives in `GATE = meta(…, knobs=(…))`; the actual read in
    `os.environ.get("REFLECT_…")` in the source (a knob name must appear as a
    literal somewhere in the source — otherwise it could not read that env
    var). Nothing compared the two before — the AUTO:GATES table could list
    knobs the gate never reads (declaration vs implementation mismatch,
    silent).

    `gates` = the result of registry.gates() (with file / knobs).
    `sources` is injectable (`{file: source text}`) — that **seam did not
    exist** before; it read `gate.GATE_REPO` directly, so this judgment had
    **zero self-evidence cases**: a guard never once proven red since landing
    (a hard violation of AGENTS rule 4). Only with the seam can the reverse
    assertion test it.
    """
    out = []
    for g in gates:
        declared = set(g.get("knobs") or ())
        if not declared:
            continue
        text = _text_of(g["file"], sources)
        if text is None:
            continue
        read = set(_TOKEN_RE.findall(text))
        ghost = sorted(k for k in declared if k not in read)
        if ghost:
            out.append(M("knobs.declared_not_read",
                         file=g["file"], knobs=", ".join(ghost)))
    return out


def registry_vs_readme_problems(tables=None, names=None):
    """C4 reconciliation (2): knobs in the roster ⊆ the config tables of the
    three-language READMEs.

    `knobs.REGISTRY` and the README config tables are two copies of the "knob
    list"; previously only one direction was checked (README ⊆ REGISTRY, see
    readme_problems). This checks the reverse: every registered knob must have a
    config row in the three-language READMEs — otherwise a new knob gets
    registered and nobody knows how to configure it (documentation gap,
    silent).

    `tables` is injectable (fake READMEs for self-evidence); `names` is
    injectable (a **pinned list** for self-evidence).

    ⚠️ The `names` seam is necessary, not convenient: without it the list comes
    from `readme_names()` — which reads `REFLECT_READMES`. So **the self-test's
    outcome depended on whatever environment the machine ran it with**: `--init`
    writes `REFLECT_READMES=README.md` for a single-README repo, and after
    sourcing that this self-test went from 3 red to 1 red and `harness` went red
    on the spot. Observed: in a freshly bootstrapped repo, `registry --run
    commit` and `harness` **could not both be green** — a deadlock. A judgment
    must not read the environment to decide how many rounds it runs.
    """
    out = []
    for name in (readme_names() if names is None else names):
        text = _text_of(name, tables)
        if text is None:
            continue
        missing = _missing_rows(text)
        if missing:
            out.append(M("knobs.readme_missing_rows",
                         file=name, knobs=", ".join(missing)))
    return out


_README_ROW = re.compile(r"\|\s*`(REFLECT_[A-Z0-9_]+)`\s*\|")


def _missing_rows(text):
    """Which registered knobs are missing from the config table. **Empty table ⇒
    empty** (not a config-table shape; no false positive)."""
    have = set(_README_ROW.findall(text))
    if not have:
        return []
    return sorted(k for k in REGISTRY if k not in have)


# ── Self-evidence: shape guards on the roster itself (a broken registry = broken
# judgment data for every consumer) ──────────────────────────────────────────────

def _load_semantic_tables(langs):
    """Load each installed pack. Broken / empty pack ⇒ `{}` (semantic completeness
    cannot be proven; not allowed to go green)."""
    tables = {}
    for lang in langs:
        try:
            tables[lang] = load_pack(lang)
        except Exception:                                # noqa: BLE001
            return {}
    # Zero-value guard: no pack installed at all ⇒ not "complete", just not installed
    if not tables or not any(tables.values()):
        return {}
    return tables


def _all_packs_have_codes(tables, codes):
    """(a) Every pack must contain **all** semantic codes (a dropped entry ⇒ users
    there see a bare code)."""
    return all(all(c in table for c in codes)
               for table in tables.values())


def _all_packs_render_text(tables):
    """Every pack actually renders sentences (not falling back to codes)."""
    for lang in sorted(tables):
        with bind(Catalog.load(lang, {lang: tables[lang]})):
            if any(str(w) == w.code for _k, _d, w in REGISTRY.values()
                   if isinstance(w, _Semantic)):
                return False
    return True


def _semantic_packs_intact(langs=None):
    """**Every installed language pack** must contain all knob semantics, with
    placeholder names matching the reference side, and actually render sentences
    under its own pack (not falling back to bare codes).

    This is the **falsifiable** evidence for `_Semantic`'s lazy rendering: if an
    entry went missing while semantics moved from the core into packs, this goes
    red on the spot (rather than waiting for someone to spot a bare code like
    `knobs.sem.reflect_facts`).

    `langs=None` ⇒ use `installed_langs()` (same discovery basis as the
    reconcilers).
    ⚠️ It previously hard-coded `zh` / `en`: when a downstream repo installs
    exactly one pack (**the product's main scenario**: "pick one from a pile of
    packs"), this self-test went straight red (observed: a zh-only pack
    directory ⇒ 16 PASS / 1 FAIL) — the product was fine, the judgment was too
    narrow.

    The four segments are each a named helper (load / code set / placeholders /
    rendering): when four "must not go green" exits are crowded mid-function, a
    reader has to count returns before claiming which checks already ran.
    """
    langs = installed_langs() if langs is None else list(langs)
    codes = [w.code for _k, _d, w in REGISTRY.values()
             if isinstance(w, _Semantic)]
    if not codes:
        return False                        # semantics all gone = roster broken; not green
    tables = _load_semantic_tables(langs)
    if not tables:
        return False
    if not _all_packs_have_codes(tables, codes):
        return False
    # (b) Placeholder-name consistency **goes through the same reconciler**
    # (the same judgment as `pack_sync_problems`: write the loop twice and the
    # rules will drift — C4).
    if pack_sync_problems(discovery=lambda: sorted(tables),
                          loader=lambda l: tables[l]):
        return False
    return _all_packs_render_text(tables)


def _discovery_sees_planted_lang():
    """Plant a half-broken language into the real pack directory; default discovery
    must see it.

    Uses a temporary `REFLECT_I18N` (base pack + planted half-broken pack) —
    never touches the real repo's lang/.

    ⚠️ The planted language name **must differ from the base pack's**: it used to
    hard-code planting `de` while the base was `a_pack_lang()`; once the real
    repo installed `de` (sorted() makes `de` the base), the planted half-broken
    pack would **overwrite** the base pack ⇒ this self-test false-rotted after
    German was installed (observed).
    """
    import json  # noqa: PLC0415
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    # The base pack is the **first installed one**, not a hard-coded zh: with a
    # single pack installed (the product's main scenario), hard-coding zh makes
    # this self-test false-red (observed en-only ⇒ 16 PASS / 1 FAIL).
    base = a_pack_lang()
    if not base:
        # Zero packs is a **legal state** (the user-requested zero-language
        # default) ⇒ there is no base pack to plant against and this test's
        # condition holds vacuously. The real repo always has packs, so in the
        # real environment this test always genuinely exercises something.
        return True
    zh = load_pack(base)
    if not zh:
        return False
    d = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(d, base), exist_ok=True)
        with open(os.path.join(d, base, "all.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(zh, fh, ensure_ascii=False)
        # Plant a **half-broken** fake language: only half the keys — if
        # discovery misses it, the reconciliation under-reports.
        # Named `probe-lang`, which can **never** collide with a real language
        # (`de`/`en`/`zh`…).
        planted = "probe-lang"
        os.makedirs(os.path.join(d, planted), exist_ok=True)
        half = dict(list(zh.items())[: len(zh) // 2])
        with open(os.path.join(d, planted, "all.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(half, fh, ensure_ascii=False)
        prev = os.environ.get("REFLECT_I18N")
        os.environ["REFLECT_I18N"] = d
        try:
            got = installed_langs()
            probs = pack_sync_problems()       # default discovery
            return planted in got and probs != []
        finally:
            if prev is None:
                os.environ.pop("REFLECT_I18N", None)
            else:
                os.environ["REFLECT_I18N"] = prev
    finally:
        shutil.rmtree(d, True)


def _looks_like_pack(path):
    """Does this json **look like** a language pack by content? (the single-file
    shape's judgment)

    A language pack's signature: keys are `x.y`-shaped codes, values are strings
    (usually with `%(…)` placeholders). A json that is not a language pack
    (config / notes / metadata) must not be mistaken for a language.
    """
    import json  # noqa: PLC0415
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return False        # a broken file is not a language pack (load_pack reports broken packs per installed language)
    if not isinstance(data, dict) or not data:
        return False
    dotted = sum(1 for k in data if isinstance(k, str) and "." in k)
    return dotted >= max(1, len(data) // 2)


def installed_langs():
    """Which languages are actually installed in the pack directory (**discovered**,
    never a written list).

    C4's "a hand-written roster always drifts" applies here too: `langs=("zh",
    "en")` was hard-coded before, so adding a `de/` (half-installed, missing
    keys) under `zreflect/lang/` went **completely unseen** by the reconcilers —
    "installed but never reconciled" is exactly the class of silence this repo
    exists to eliminate. Now it scans the directory.

    **The judgment is not "the directory exists" but "there really are .json
    pack files in there"**: earlier it collected by directory name, so a
    `straynotes/` directory or a stray `extra.json` in the pack root would be
    taken for a language, inventing "missing keys" and rotting the roster red
    (observed). A language pack's judgment is "has a pack file".
    """
    base = pack_dir()
    out = set()
    try:
        for n in sorted(os.listdir(base)):
            p = os.path.join(base, n)
            if os.path.isdir(p) and any(x.endswith(".json")
                                        for x in os.listdir(p)):
                out.add(n)
            # ⚠️ The single-file shape (`<lang>.json`) looks identical to "any
            # json in the pack root" — collecting by filename alone would take
            # `config.json` for a `config` language and invent missing keys
            # (observed). A language pack's judgment is **content**: code-shaped
            # keys (`x.y`) or placeholder values.
            elif n.endswith(".json") and _looks_like_pack(p):
                out.add(n[:-len(".json")])
    except OSError as e:
        # ⚠️ **Never fabricate a 0** (AGENTS discipline 7: if it can't be read,
        # say so; never invent). This used to `return []`, collapsing "broken
        # permissions / unreadable directory" and "no packs installed" into the
        # same false value ⇒ reconcilers all green, roster all green — the worst
        # member of the "deployed ≠ running" family (observed: a chmod 000 pack
        # directory gave pack_sync_problems() == []).
        raise PacksUnreadable(str(e)) from e
    return sorted(out)


class PacksUnreadable(RuntimeError):
    """The pack directory itself is unreadable (permissions / I-O). **Distinct
    from "no packs installed"**: the latter is legal, the former is an incident."""



def dead_default_problems(py_dir=None):
    """C4 reconciliation (5): `DEFAULT_*` constants that are **defined but never used**
    in gates / modules.

    Why this deserves a judgment: `check_i18n` once had `DEFAULT_ROOT =
    "zreflect"` while `run()` only read the env var and **never used it** — so
    this repo's most central coverage gate was **permanently off** on live paths
    ("exists, self-tests green, never runs"). `check_snapshots` made the same
    mistake. A constant that "declares a default that has no effect" is worse
    than no default: it makes people **believe** the configuration is in place.

    Judgment (AST): a module-level `DEFAULT_X = …` with **no Load reference**
    anywhere in that file ⇒ report. Only `check_*.py` + platform modules (i.e.
    `zreflect/*.py`) are scanned.
    """
    import ast  # noqa: PLC0415
    d = py_dir if py_dir is not None else gate.zdir()
    out = []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for n in names:
        if not n.endswith(".py"):
            continue
        try:
            tree = ast.parse(open(os.path.join(d, n), encoding="utf-8").read())
        except (OSError, SyntaxError):
            continue
        defined = {t.id for node in tree.body if isinstance(node, ast.Assign)
                   for t in node.targets
                   if isinstance(t, ast.Name) and t.id.startswith("DEFAULT_")}
        loaded = {node.id for node in ast.walk(tree)
                  if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
        for dead in sorted(defined - loaded):
            out.append(M("knobs.dead_default", file=n, name=dead))
    return out


def _dead_default_ok():
    """A `DEFAULT_X` defined but never Loaded ⇒ must report; used ⇒ must not."""
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    d = tempfile.mkdtemp()
    try:
        dead = ("DEFAULT_X = 'v'\n"
                "def run():\n"
                "    return os.environ.get('K') or 'hardcoded'\n")
        live = ("DEFAULT_X = 'v'\n"
                "def run():\n"
                "    return os.environ.get('K') or DEFAULT_X\n")
        # First with only the "dead" one
        with open(os.path.join(d, "check_dead.py"), "w", encoding="utf-8") as fh:
            fh.write(dead)
        got_dead = [p.code for p in dead_default_problems(py_dir=d)]
        # Switch to the "live" one ⇒ should not report
        with open(os.path.join(d, "check_dead.py"), "w", encoding="utf-8") as fh:
            fh.write(live)
        got_live = dead_default_problems(py_dir=d)
        return got_dead == ["knobs.dead_default"] and got_live == []
    finally:
        shutil.rmtree(d, True)


def a_pack_lang():
    """Pick an **installed** language pack name (for self-evidence judgments of the
    "read a real pack" kind); none installed ⇒ None.

    Those judgments verify "rendering fidelity" (are the placeholders in message
    templates right, are the sentences still there) — **which language it is
    doesn't matter**, so it must not be hard-coded to `zh`. A downstream repo
    installing exactly one pack is the product's main scenario ("pick one from a
    pile of packs"); hard-coding zh would false-rot the
    `REFLECT_I18N=<en-only>` self-test.
    """
    langs = installed_langs()
    return langs[0] if langs else None


_CODE_RE = re.compile(r'M\("([a-z][a-z0-9_.]+)"')
# `_Semantic(...)` also produces user-visible messages (lazily rendered); counted too.
_SEM_RE = re.compile(r'_Semantic\("([a-z][a-z0-9_.]+)"')

# Self-evidence / documentation-only codes: they are **never** rendered to users
# (they only appear in `--selftest` assertions, or as docstring examples).
# Declared via an **explicit prefix** instead of a hand-written roster — adding
# such a code only requires using this prefix (discovered, doesn't drift).
_SELFTEST_CODE_PREFIXES = ("probe.", "gate.off.body")


def used_codes(py_dir=None):
    """Message codes the core source would **actually send to users**
    (`M("…")` / `_Semantic("…")`).

    **Discovered**: scan the source, keep no written roster. This is the
    reference surface for the "pack completeness" judgment — without it, "both
    packs missing the same entry" would go all green (a zh↔en set-difference
    comparison cannot see a shared omission).

    **Strip docstrings**: examples in docs (`M(…)` shapes) are not output;
    without stripping, doc examples get taken for real messages (observed false
    positive).
    Prefixes in `_SELFTEST_CODE_PREFIXES` are self-evidence-only codes (also
    never sent to users).
    """
    import ast  # noqa: PLC0415
    d = py_dir if py_dir is not None else gate.zdir()
    out = set()
    for _n, src in _py_sources(d):
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        # docstring constants (exempt: examples are not output)
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    docs.add(doc)
        text_wanted = argparse_strip(src, docs)
        out |= set(_CODE_RE.findall(text_wanted))
        out |= set(_SEM_RE.findall(text_wanted))
    return {c for c in out
            if not any(c.startswith(p) for p in _SELFTEST_CODE_PREFIXES)}


def argparse_strip(src, docs):
    """Erase docstring bodies from the source (coarse replacement only; sufficient
    for scanning)."""
    for doc in docs:
        if doc:
            src = src.replace(doc, "")
    return src


def _unreadable_dir_is_loud():
    """Pack directory unreadable ⇒ must report `pack_unreadable`; must not pass as
    "zero packs" (a legal state)."""
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    if os.name == "nt":
        # ⚠️ **On Windows `chmod 0` does not prevent reading**: `os.chmod` there
        # only toggles the read-only bit, and `listdir` still gets in. So the
        # fixture "make an unreadable directory" cannot even be built on
        # Windows — this test can't test anything (stated as not applicable,
        # not a silent pass).
        # Observed: on the CI Windows leg, `knobs` self-test ran 28 PASS / 1
        # FAIL, and the red one was exactly this.
        return True
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return True        # root ignores permission bits; untestable (stated as not applicable)
    d = tempfile.mkdtemp()
    try:
        os.chmod(d, 0)
        prev = os.environ.get("REFLECT_I18N")
        os.environ["REFLECT_I18N"] = d
        try:
            try:
                installed_langs()
            except PacksUnreadable:
                return True
            return False
        finally:
            if prev is None:
                os.environ.pop("REFLECT_I18N", None)
            else:
                os.environ["REFLECT_I18N"] = prev
    finally:
        os.chmod(d, 0o755)
        shutil.rmtree(d, True)


def pack_coverage_problems(codes=None, loader=None, discovery=None):
    """C4 reconciliation (4): **every code used by the source must exist in every
    installed pack**.

    The zh↔en set-difference comparison (`pack_sync_problems`) cannot see "both
    sides missing the same thing" — observed: delete `locks.ok` from both zh and
    en and `pack_sync_problems()` returns `[]`, while a `REFLECT_LANG=zh` user
    sees `locks.ok(count=3)` (a bare code) on screen with a normal exit code.
    That is the **silent degradation this repo exists to fight**, the classic C4
    failure mode ("two copies that must agree" only guarantees agreement, not
    completeness).

    The reference surface is the **source** (`used_codes()`), not another pack —
    so two packs drifting together are still caught. Zero packs is a legal state
    ⇒ nothing to check; return empty.

    `langs=None` ⇒ discover via `discovery()` (default `installed_langs()`).
    ⚠️ This parameter used to be **accepted but never called** (in the
    signature, absent from the implementation) — passing a fake discovery in
    changed nothing (observed). That is the shape this repo detests most: an
    interface claiming injectability that is not. Now it goes through the same
    channel as `pack_sync_problems`.
    """
    load = loader if loader is not None else load_pack
    codes = used_codes() if codes is None else set(codes)
    try:
        langs = list((discovery or installed_langs)())
    except PacksUnreadable as e:
        return [M("knobs.pack_unreadable", lang="*", error=e)]
    if not codes or not langs:
        return []                       # zero packs / zero codes: no comparable sides
    out = []
    for lang in sorted(langs):
        try:
            table = load(lang)
        except Exception as e:                           # noqa: BLE001
            return [M("knobs.pack_unreadable", lang=lang, error=e)]
        missing = sorted(codes - set(table))
        if missing:
            out.append(M("knobs.pack_missing_code",
                         lang=lang, count=len(missing),
                         codes=", ".join(missing[:8])))
    return out


def pack_sync_problems(loader=None, discovery=None):
    """C4 reconciliation (3): every language pack's **key set** and **placeholder
    names** must agree.

    Nothing enforced this before — hand-add a code to zh and forget en, and a
    `REFLECT_LANG=en` user silently sees a bare code (the silent degradation
    this repo exists to eliminate). At the time of writing the two packs were
    equal, but "equal" was luck, not a judgment.

    `discovery` decides "which languages count" (default `installed_langs()`).
    ⚠️ There used to be a `langs=` parameter that could **directly inject a set
    of language names** — it let six self-tests bypass the discovery channel:
    swap `installed_langs()` back to a hand-written list and 5/6 cases stayed
    green (observed BLIND). Two parameters for the same thing, and the weaker
    one becomes a back door. Removed: to pin languages, inject `discovery`,
    going through the same seam as production.
    `loader` is injectable (fake packs for self-evidence); the default is
    `i18n.load_pack` (the **merged view** — same table as the real loader;
    reading single shards would fork from the loader).
    """
    load = loader if loader is not None else load_pack
    try:
        langs = list((discovery or installed_langs)())
    except PacksUnreadable as e:
        return [M("knobs.pack_unreadable", lang="*", error=e)]
    tables, err = _load_tables(langs, load)
    if err:
        return err
    early = _empty_pack_verdict(tables)
    if early is not None:
        return early
    ref_lang = sorted(tables)[0]
    ref = tables[ref_lang]
    out = []
    for lang in sorted(tables):
        if lang == ref_lang:
            continue
        out += _key_set_problems(lang, ref_lang, ref, tables[lang])
        out += _placeholder_problems(lang, ref_lang, ref, tables[lang])
    return out


def _empty_pack_verdict(tables):
    """The two verdicts for "zero packs / broken packs". Returns `None` = keep
    comparing.

    **Zero packs is a legal state** (the user wants "the core works without any
    language expression"): no pack installed ⇒ there is no "mutual agreement" to
    speak of, but the configuration is not broken — return empty (no report).
    "A pack was requested but can't be read" is handled by `pack_unreadable` /
    the activation path's `i18n.pack_absent`; that's a different matter: **not
    requested** vs **requested but absent**.

    Installed but all tables empty ⇒ that is a **broken pack** (a directory is
    claimed but has no content); report.
    """
    if not tables:
        return []
    if not any(tables.values()):
        return [M("knobs.pack_sync_empty", pack_dir=pack_dir())]
    return None


def _load_tables(langs, load):
    """Load all installed packs. Returns `(tables, error list or None)`.

    ⚠️ **Must catch `load_pack` exceptions**: it raises `MissingPack` for broken
    shards, and `pack_sync_problems` can be called **outside**
    `activate_or_fatal()` (the `registry --gates` roster reconciliation is one
    such call), so the exception would bubble to the top as a bare traceback
    rc=1 — escaping this repo's rc contract (broken config = FATAL rc 2).
    Observed: `REFLECT_LANG` unset + a broken shard ⇒ rc=1 traceback; the same
    input with `REFLECT_LANG=zh` gives rc=2.
    """
    tables = {}
    for lang in langs:
        try:
            tables[lang] = load(lang)
        except Exception as e:                           # noqa: BLE001
            return {}, [M("knobs.pack_unreadable", lang=lang, error=e)]
    return tables, None


def _key_set_problems(lang, ref_lang, ref, other):
    """Key-set difference: keys only the reference has / only this pack has."""
    out = []
    only_ref = sorted(set(ref) - set(other))
    only_other = sorted(set(other) - set(ref))
    if only_ref:
        out.append(M("knobs.pack_missing_keys", lang=lang, reference=ref_lang,
                     keys=", ".join(only_ref[:8])))
    if only_other:
        out.append(M("knobs.pack_extra_keys", lang=lang, reference=ref_lang,
                     keys=", ".join(only_other[:8])))
    return out


def _placeholder_problems(lang, ref_lang, ref, other):
    """Placeholder-name agreement: one difference ⇒ KeyError at render time (or
    worse, a silently dropped segment)."""
    out = []
    for code in sorted(set(ref) & set(other)):
        a = sorted(_PLACEHOLDER_RE.findall(ref[code]))
        b = sorted(_PLACEHOLDER_RE.findall(other[code]))
        if a == b:
            continue
        # The param must not be named `code`: `M(code, **params)`'s first
        # parameter is already named code, and a same-named kwarg raises
        # `TypeError: M() got multiple values` (observed hit).
        out.append(M("knobs.pack_placeholder_mismatch",
                     lang=lang, key=code, reference_lang=ref_lang,
                     expected_params=", ".join(a) or "-",
                     actual_params=", ".join(b) or "-"))
    return out


def null_pack():
    """A context manager over an **explicit null pack** (self-evidence only).

    Shape judgments in self-evidence ("with no pack installed it should be a
    code") must carry their own null scope: the entry `activate()` sets
    `REFLECT_LANG` to zh/en, and without its own scope an assertion becomes
    "whatever environment it runs in is what gets tested" — observed: under
    `REFLECT_LANG=zh gates-selftest.sh` such cases all went red.
    """
    return bind(NULL)


def _semantics_can_red():
    """Does `_semantics_are_codes_under()` have teeth? Given a table that **won't
    render as codes** ⇒ must be False."""
    sem = [(k, w) for k, _d, w in REGISTRY.values() if isinstance(w, _Semantic)]
    if not sem:
        return False
    # Use a fake pack where "every code is translated into a sentence":
    # str(w) != w.code ⇒ should return False
    fake = {w.code: "SENTENCE %s" % w.code for _k, w in sem}
    return _semantics_are_codes_under(
        bind(Catalog.load("xx", {"xx": fake}))) is False


def _planted_red_when_blind():
    """Turn the discovery channel off (back to a hand-written list); the planted
    check must go red."""
    prev = installed_langs
    globals()["installed_langs"] = lambda: ["zh", "en"]     # pretend discovery is broken
    try:
        return _discovery_sees_planted_lang() is False
    finally:
        globals()["installed_langs"] = prev


def _semantics_are_codes_under(cm):
    """Under the `cm` language-pack scope, every knob semantic renders as a code
    (and is non-empty)."""
    sem = [(k, w) for k, _d, w in REGISTRY.values()
           if isinstance(w, _Semantic)]
    if not sem:
        return False                        # zero-value guard: semantics gone ⇒ roster broken
    cm.__enter__()
    try:
        return all(str(w) == w.code for _k, w in sem)
    finally:
        cm.__exit__(None, None, None)


def _cases_fixture(d):
    """Build the fixture (fake source directory + phantom token). `d` comes from `_cases()`."""
    open(os.path.join(d, "good.py"), "w", encoding="utf-8").write(
        'X = os.environ.get("REFLECT_FACTS")\n')
    # The phantom token is built by concatenation: this file is inside the scan
    # surface (zreflect/*.py), so writing the literal out would get it collected
    # by this very file's scan_surface_problems() (an old pit of this repo).
    # Fixture bodies (fake sources / fake READMEs) are in **English** — they are
    # scanned inputs, not core output (same convention as facts.py: Chinese
    # fixtures would be treated as messages by the zero-language gates).
    phantom = "REFLECT_" + "GHOSTX"
    open(os.path.join(d, "phantom.py"), "w", encoding="utf-8").write(
        '# a comment mentions the nonexistent knob ' + phantom + '\n')
    return {"d": d, "phantom": phantom}


def _cases_scan(fx):
    """See `_cases()`: 6 cases in this group."""
    d, phantom = fx["d"], fx["phantom"]
    return [
    # (a) normally no report
    ("knobs.registry_entry_shape",
     lambda: all(k in KINDS and isinstance(dflt, str) and w.strip()
                 for k, dflt, w in REGISTRY.values()) and len(REGISTRY) >= 20),
    ("knobs.scan_clean",
     lambda: scan_surface_problems() == []),
    ("knobs.real_tree_scan_clean", lambda: scan_surface_problems() == []),
    # (b) what must report, must report
    ("★ knobs.phantom_token",
     lambda: any(p.code == "knobs.phantom_token"
                 and p.params.get("token") == phantom
                 for p in scan_surface_problems(py_dir=d))),
    ("★ knobs.registry_empty", lambda: bool(REGISTRY)),
    ("knobs.phases_registered", lambda: "REFLECT_PHASES" in REGISTRY),
    ]


_README_TRIO = {"README.md": "x", "README.zh.md": "x", "README.de.md": "x"}


def _cases_readme_nominations():
    """An unregistered knob name appearing in a README (phantom defense) — must
    report + normally silent."""
    return [
        ("knobs.readme_nominations_registered",
         lambda: readme_problems(files={
             "README.md": "uses REFLECT_FACTS and REFLECT_DOC.",
             "README.zh.md": "x", "README.de.md": "x"}) == []),
        ("knobs.real_readmes_clean", lambda: readme_problems() == []),
        ("\u2605 knobs.readme_phantom",
         lambda: any(x.code == "knobs.readme_phantom"
                     for x in readme_problems(files=dict(
                         _README_TRIO,
                         **{"README.md": "see " + "REFLECT_" + "GHOSTY" + "."})))),
    ]


def _cases_readme_declared_read():
    """The declared↔read reconciliation — never once proven red since landing
    (AGENTS rule 4).

    ⚠️ The assertion must **not** be extracted into a helper: `never_falsifiable`
    only scans the lambda's AST, and delegating to a function blinds it — that
    was done before, and after the helper became `return True` it was 26 PASS /
    0 FAIL all green (observed). Rather write a long line than switch the
    detector off.
    """
    return [
        ("\u2605 knobs.declared_not_read",
         # A knob is declared but never appears in the source ⇒ must report, and
         # must **name that knob**
         lambda: [p.code for p in declared_vs_read_problems(
             [{"file": "check_x.py", "knobs": ("REFLECT_FACTS",)}],
             sources={"check_x.py": "X = 1\n"})
         ] == ["knobs.declared_not_read"]
         and [p.params for p in declared_vs_read_problems(
             [{"file": "check_x.py", "knobs": ("REFLECT_FACTS",)}],
             sources={"check_x.py": "X = 1\n"})
         ] == [{"file": "check_x.py", "knobs": "REFLECT_FACTS"}]),
        # Declared and actually read ⇒ must not report (positive control; otherwise
        # "always report" would also fool the self-test)
        ("knobs.declared_and_read_is_clean",
         lambda: declared_vs_read_problems(
             [{"file": "check_x.py", "knobs": ("REFLECT_FACTS",)}],
             sources={"check_x.py":
                      'X = os.environ.get("REFLECT_FACTS")\n'}) == []),
    ]


def _cases_readme_rows():
    """Missing rows in the README config table — the direction opposite of the
    phantom check."""
    return [
        ("\u2605 knobs.readme_missing_rows",
         # ⚠️ The assertion **pins the code**, not just `!= []`: before, any wrong
         # code could satisfy this case (observed: substituting a fake
         # `readme_phantom` still passed).
         lambda: [p.code for p in registry_vs_readme_problems(
             tables=dict.fromkeys(_README_TRIO, "| `REFLECT_FACTS` | x |\n"),
             # The list is **pinned**: a judgment must not read `REFLECT_READMES`
             # to decide how many rounds it runs.
             names=tuple(_README_TRIO))
         ] == ["knobs.readme_missing_rows"] * 3),
    ]


def _cases_readme_empty():
    """(c) Empty-input tier (the third class of AGENTS rule 4).

    Both reconcilers previously had only "no report" and "must report" tiers;
    empty input returned `[]` — indistinguishable from "clean". Here empty input
    is **explicitly stated as not applicable** (not faked as a pass): returning
    empty when there are no comparable sides is correct, but a case must pin it,
    otherwise a broken implementation would also return empty.
    """
    return [
        ("knobs.declared_vs_read_empty_in_scope",
         lambda: declared_vs_read_problems([{"file": "x.py", "knobs": ()}],
                                           sources={}) == []),
        ("knobs.registry_vs_readme_empty_tables",
         lambda: registry_vs_readme_problems(tables={}) == []),
    ]


def _cases_readme(fx):
    """See `_cases()`: 8 cases in this group.

    Four groups (phantom / declared↔read / missing rows / empty input): the four
    reconcilers each check a different direction, and when mixed into one list,
    "which direction this case tests" can only be told from comments.
    """
    return (_cases_readme_nominations() + _cases_readme_declared_read()
            + _cases_readme_rows() + _cases_readme_empty())


def _cases_semantics(fx):
    """See `_cases()`: 3 cases in this group."""
    return [
("knobs.semantic_renders_as_code_by_default",
 # Carries its own **null scope**: this tests "with no pack installed it is a
 # code", independent of which pack the entry point activated. It used to read
 # `str(w)` directly, and under `REFLECT_LANG=zh` it rendered sentences and all
 # went red (observed) — an assertion without a declared scope = whatever
 # environment it runs in is what gets tested.
 # Delegated to a helper (a null scope requires paired enter/exit; inlining
 # would become one unreadable line).
 # The always-true detector cannot see the delegate body ⇒ gate marks it
 # "unaudited"; a same-source counter-proof below shows the helper really has
 # teeth.
 lambda: _semantics_are_codes_under(null_pack())),
("★ knobs.semantics_are_codes_can_red", lambda: _semantics_can_red()),
# The **positive evidence** for lazily rendered semantics: in the real zh pack
# every semantic has an entry, and under the zh pack it renders as that
# sentence (not a code). Reading the real pack from disk = proof the migration
# lost no semantics (injecting a fake table only proves "my template renders my
# words" — circular reasoning).
# Repro: REFLECT_LANG=zh python3 zreflect/knobs.py --selftest
("knobs.semantics_present_in_real_packs",
 # Conditional judgment: **if packs are installed they must be complete**.
 # Zero packs (legal state) ⇒ nothing to verify, condition holds vacuously;
 # a broken pack installed ⇒ this still goes red (verified with a planted pack).
 lambda: not installed_langs() or _semantic_packs_intact()),
    ]


def _cases_sync_rules():
    """Set difference / placeholders / extra keys / empty pack — these test the
    **rules themselves**.

    Injecting `discovery` in these four cases is **intentional**: they must not
    depend on the discovery channel (that is tested separately by
    `pack_sync_sees_every_installed_lang`). Passing `discovery=` explicitly
    states "I am testing the rules" — previously `langs=` passed the same thing,
    looking like a discovery test while actually bypassing it.
    """
    return [
        ("\u2605 knobs.pack_missing_keys",
         lambda: [p.code for p in pack_sync_problems(
             discovery=lambda: ("zh", "en"), loader=lambda l: {
                 "zh": {"a": "x"}, "en": {"a": "x", "b": "y"}}[l])
         ] == ["knobs.pack_missing_keys"]),
        ("\u2605 knobs.pack_placeholder_mismatch",
         lambda: [p.code for p in pack_sync_problems(
             discovery=lambda: ("zh", "en"), loader=lambda l: {
                 "zh": {"a": "x %(k)s"}, "en": {"a": "x %(j)s"}}[l])
         ] == ["knobs.pack_placeholder_mismatch"]),
        # The extra-keys direction must also be reportable (only missing keys were
        # tested before — "one extra key" equally makes the other side's user see
        # a bare code; the other face of the same hole).
        # The reference side is `sorted(...)[0]` (here = "en"), so "zh has an
        # extra key" goes through extra_keys; reversed, it would be reported as
        # en missing keys (same hole, two wordings).
        ("\u2605 knobs.pack_extra_keys",
         lambda: [p.code for p in pack_sync_problems(
             discovery=lambda: ("zh", "en"), loader=lambda l: {
                 "zh": {"a": "x", "b": "y"}, "en": {"a": "x"}}[l])
         ] == ["knobs.pack_extra_keys"]),
        # (c) empty input must report
        ("\u2605 knobs.pack_sync_empty",
         lambda: [p.code for p in pack_sync_problems(
             discovery=lambda: ("zh", "en"), loader=lambda l: {})]
         == ["knobs.pack_sync_empty"]),
    ]


def _cases_sync_coverage():
    """Discovery + pack completeness: these two must **not** hand the answer to the
    code under test."""
    return [
        # Discovery (no written roster): a half-broken pack added on disk must be
        # seen by the reconciler too.
        # ⚠️ Goes through **default discovery** (no `discovery=` passed) — passing
        # it amounts to handing the answer to the code under test (observed:
        # that way, even after swapping `installed_langs` back to a hand-written
        # list, this case still PASSED).
        ("\u2605 knobs.pack_sync_sees_every_installed_lang",
         lambda: _discovery_sees_planted_lang()),
        # (d) **Pack completeness** (C4 reconciliation 4): every code the source
        # uses must be in every installed pack.
        # This catches "both sides missing the same thing" — with set-difference
        # comparison alone, a shared omission goes all green and the user sees a
        # bare code (observed: delete `locks.ok` from both packs ⇒ all green).
        ("knobs.coverage_real_repo_clean",
         lambda: pack_coverage_problems() == []),
        # **`discovery=` must actually be called** (previously accepted in the
        # signature, never called in the implementation: passing a fake discovery
        # changed nothing). This pins the "injectable" promise.
        ("\u2605 knobs.coverage_honours_discovery",
         lambda: (lambda seen: ([p.code for p in pack_coverage_problems(
             codes={"a.b"}, discovery=lambda: seen.append(1) or ["zz"],
             loader=lambda l: {})] == ["knobs.pack_missing_code"] and
             len(seen) == 1))([])),
        ("\u2605 knobs.pack_missing_code",
         lambda: [p.code for p in pack_coverage_problems(
             codes={"a.b", "c.d"}, discovery=lambda: ("zh", "en"),
             loader=lambda l: ({"a.b": "x", "c.d": "y"} if l == "en"
                               else {"a.b": "x"}))
         ] == ["knobs.pack_missing_code"]),
        # **Unreadable directory ≠ no packs installed** (AGENTS discipline 7: if it
        # can't be read, say so; never fabricate a 0).
        # `installed_langs()` used to `return []` on OSError, collapsing broken
        # permissions and "zero packs" into the same false value ⇒ reconciliation
        # all green (observed chmod 000 ⇒ []).
        ("\u2605 knobs.pack_unreadable_on_oserror",
         lambda: _unreadable_dir_is_loud()),
    ]


def _cases_sync(fx):
    """See `_cases()`: 9 cases in this group.

    Two groups (rules / discovery and coverage): the former injects discovery to
    test the rules themselves; the latter passes **no** discovery and tests
    "that it really gets called" — mixed together, a reader cannot tell which
    class an assertion belongs to.
    """
    return _cases_sync_rules() + _cases_sync_coverage()


def _cases_pack(fx):
    """The 12 language-pack judgments: 3 semantics + 9 sync/coverage."""
    return (
        _cases_semantics(fx)
        + _cases_sync(fx)
    )


def _cases_registry(fx):
    """See `_cases()`: 5 cases in this group."""
    return [
    # zh / en key sets and placeholder names agree (C4 reconciliation 3). Real
    # packs green = the migration dropped nothing on either side; the reverse
    # assertion is in tier (b) (fake packs must report).
    ("knobs.real_packs_in_sync",
     # Same as above: zero packs is legal ⇒ there is no "mutual" to reconcile;
     # with packs installed, they must agree.
     lambda: not installed_langs() or pack_sync_problems() == []),
    # ⚠️ The case above is a **delegation** (it builds a temporary fixture and
    # cannot be inlined) ⇒ the always-true detector cannot see inside it. Under
    # gate's new judgment it would be marked "unaudited"; so here is a
    # **same-source counter-proof**: turn the discovery channel off and the
    # planted check must go red. Only both together count as proof.
    ("★ knobs.discovery_planted_can_red", lambda: _planted_red_when_blind()),
    # **Dead defaults**: a `DEFAULT_*` defined but never used — "declared but
    # without effect"
    ("★ knobs.dead_default", lambda: _dead_default_ok()),
    # **The list knob's default has exactly one producer**: `docs_names()` must
    # agree with `REGISTRY`.
    # ⚠️ `check_stale` and `check_retractions` previously each hand-copied a
    # five-doc default while the registry had six — `PRINCIPLES.md` was never in
    # their scan surface (observed).
    ("★ knobs.docs_names_follow_registry", lambda: _docs_names_follows()),
    # **The flag vocabulary**: three states + case folding. Two vocabularies used
    # to coexist (`== "off"` and `in ("1","true","yes")`); the latter was
    # case-sensitive — `TRUE` silently did nothing.
    ("★ knobs.flag_three_states", lambda: _flag_case()),
    ]


def _flag_case():
    """`flag()`'s three states: true / false / unset, at least one spelling each
    (including case folding).

    ⚠️ `TRUE` (uppercase) must count as true — that is exactly the hole in the
    doc-side vocabulary. Empty string and unset must both be `None` (= unset;
    the caller applies its own default), not False.
    """
    import os  # noqa: PLC0415
    name = "REFLECT_" + "FLAG_PROBE"
    prev = os.environ.get(name)
    try:
        seen = {}
        for v in ("1", "TRUE", "Yes", "ON"):
            os.environ[name] = v
            seen[v] = flag(name)
        for v in ("0", "FALSE", "No", "OFF"):
            os.environ[name] = v
            seen[v] = flag(name)
        os.environ[name] = ""
        empty = flag(name)
        os.environ.pop(name)
        unset = flag(name)
        return (all(seen[v] is True for v in ("1", "TRUE", "Yes", "ON"))
                and all(seen[v] is False for v in ("0", "FALSE", "No", "OFF"))
                and empty is None and unset is None)
    finally:
        if prev is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = prev


def _docs_names_follows():
    """**The two scanning gates' default surface must equal the registry** — not
    "the function returns the registry".

    ⚠️ The first version wrote `docs_names() == REGISTRY["REFLECT_DOCS"]`, which
    is **circular reasoning** (the function itself reads REGISTRY; both sides
    change together, so a broken change stays vacuously true — observed: putting
    the old five-doc default back into REGISTRY kept this green). A vacuous
    judgment is worse than none.

    The real judgment is at the **consumer end**: which files `check_stale` /
    `check_retractions` actually scan when the knob is **unset**. They each used
    to hand-copy a five-doc literal while the registry had six — only reading
    from the consumer end reveals that difference.
    """
    import os  # noqa: PLC0415
    registered = [s.strip() for s in REGISTRY["REFLECT_DOCS"][1].split(",")
                  if s.strip()]
    prev = os.environ.get("REFLECT_DOCS")
    try:
        os.environ.pop("REFLECT_DOCS", None)
        scanned = _docs_scanned_by_gates()
        if scanned != registered:
            return False
        # With the knob set it must **not** fall back to the registry (otherwise
        # the user cannot change it; the knob would be dead)
        os.environ["REFLECT_DOCS"] = "only.md"
        return _docs_scanned_by_gates() == ["only.md"]
    finally:
        if prev is None:
            os.environ.pop("REFLECT_DOCS", None)
        else:
            os.environ["REFLECT_DOCS"] = prev


def _docs_scanned_by_gates():
    """The list of documents the two gates will scan under the **current
    environment** (consumer end, the single truth).

    It calls the **gates' own entries**, not a re-read of the registry — only
    that reveals the difference of "a gate hand-copied a different literal".
    """
    import check_retractions  # noqa: PLC0415
    import check_stale  # noqa: PLC0415
    # `check_stale.scanned_docs()` returns the documents it **actually read**
    # (a name->text dict; unreadable ones are skipped), so take the keys;
    # `check_retractions`'s version returns the name list.
    stale = list(check_stale.scanned_docs())
    retr = list(check_retractions.scanned_docs())
    return stale if stale == retr else []          # sides disagree ⇒ empty (guaranteed red)


def _cases():
    """Assemble the four fixture groups. **Assembly only** — the judgments live in
    the group functions."""
    import atexit  # noqa: PLC0415
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    d = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, d, True)
    fx = _cases_fixture(d)
    return (
        _cases_scan(fx)
        + _cases_readme(fx)
        + _cases_pack(fx)
        + _cases_registry(fx)
    )


MODULE = module_meta("Knob registry", "the single roster of REFLECT_* + roster self-consistency judgments", selftest=True)


if __name__ == "__main__":
    sys.path.insert(0, __file__.rsplit("/", 1)[0])
    from gate import main_selftest_or  # noqa: PLC0415

    def _run(argv):
        # `--list`: the **official exit** for users to look up knob semantics
        # (AGENTS.md routes here). It did not exist before — the docs pointed at
        # a command with rc=2 (caught in review).
        if "--list" in argv:
            print(knobs_table())
            return 0
        if argv and argv[0] in ("--help", "-h"):
            print(M("knobs.usage"), file=sys.stderr)
            return 0
        print(M("knobs.module_only"), file=sys.stderr)
        print(M("knobs.usage"), file=sys.stderr)
        return 2
    # Self-test titles are a **developer interface** (check_i18n's exempt surface
    # (b)); by design they stay in one language.
    sys.exit(main_selftest_or(sys.argv[1:],
                              M("gate.title.knobs"),
                              _cases, _run))

