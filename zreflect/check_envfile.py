#!/usr/bin/env python3
"""env file gate (**pluggable module**, issue #8): guards the hooks' REFLECT_* carrier.

Hooks load Einfacht.env through the pluggable einfacht-env.sh
(default name; REFLECT_ENV_FILE can swap it) — that is the
persistent carrier of issue #8: inside hook context, "whoever
remembers to export" does not count.
This gate guards the carrier's **silent rot**, all members of the
"deployed ≠ running" family:

  · a knob name mistyped by one character ⇒ silently ignored by
    every program, the value never reaches the hooks — the most
    dangerous kind: everything keeps running as usual;
  · a file knob pointing at a missing file ⇒ the hook's [ -f ]
    guard silently skips, and the machine block quietly goes
    stale from that moment on;
  · an empty value / a file with nothing but comments left ⇒
    looks configured while nothing was ever loaded;
  · broken sh syntax ⇒ the hook dies loudly only at commit
    time (set -e), with an error pointing nowhere clear.

**The roster is registration-based** (since 2026-10-07, Phase 2): the
criteria data = the REGISTRY in `zreflect/knobs.py` (name → kind /
default / semantics); this file's handwritten FILE_KNOBS list is
retired. The audit is bidirectional:

  · an exported name not in the registry ⇒ typo / phantom
    (configured yet silently inert);
  · a REFLECT_* token appearing in the zreflect/*.py scan surface
    that is **not** in the registry ⇒ phantom knob / typo
    (docstring nominations don't count, registration does — the
    structural fix for the REFLECT_AB/REFLECT_PINS phantom incident);
  · REFLECT_* names appearing in the trilingual READMEs (the
    REFLECT_READMES list) ⊆ registry (doc-side phantom defense,
    runs in selftest).

Pluggable: Einfacht.env absent (neither the hooks directory nor the
repo root has it) ⇒ state plainly that it is off, return 0 (hooks
fall back to plain environment variables + the default name).

Honest boundary: existence is only checked for paths **relative to
the repo root**; in repos whose core.hooksPath relocates the layout,
the hooks directory is found via reflect-hooks/ (the text-form
ceiling of declarative checks, same boundary as issue #7).

Usage (run directly, cwd=repo root):
    python3 zreflect/check_envfile.py [--selftest]
Exit codes: 0=green / 1=problems found / 2=configuration or environment broken.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import knobs  # noqa: E402
from gate import fatal, finish, main_selftest_or, meta, off, repo  # noqa: E402
from i18n import M  # noqa: E402
from knobs import REGISTRY  # noqa: E402

ENV_FILE = (os.environ.get("REFLECT_ENV_FILE", "Einfacht.env")
            .strip() or "Einfacht.env")

_EXPORT_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
# The explicit parentheses only spell out the precedence (`^a|b$` alternation
# binds loosest anyway); behavior is character-for-character identical to
# `^["\']|["\']$` — strips only a leading/trailing quote, keeps inner quotes.
_QUOTES_RE = re.compile(r'^(?:["\'])|(?:["\'])$')
# Knob token: REFLECT_ + uppercase. **The left boundary is required** — without
# it, the retraction example text (a `ZCODE_` prefix + one token) gets sliced
# mid-word into a fake token, and each trilingual README audit reports one
# false positive apiece (hit in practice). ⚠️ Neither this comment nor the
# selftest ever spells out that fake token.

# The single source of truth for the token regex is knobs._TOKEN_RE
# (two identical copies existed before; they would drift).
from knobs import _TOKEN_RE  # noqa: E402  (single source; this file used to keep its own copy)


def known_knobs(py_dir=None):
    """Discovery scan: the full set of REFLECT_* tokens appearing in zreflect/*.py.

    Used for auditing (not the roster itself — the roster is knobs.REGISTRY):
    a token that appears in the scan surface but is missing from the registry
    = phantom / typo, reported by this gate. `py_dir` is injectable
    (selftest uses a fake source tree — if real files entered the selftest,
    the selftest would depend on the machine).

    ⚠️ **The default directory is the checked repo's zreflect** (`repo("zreflect")`),
    not the tool's own — this gate guards **the checked repo's** carrier, not
    the tool itself. `knobs._py_sources()` is the shared read loop, but the
    base is passed explicitly here: the two default directories coincide in
    production but differ under fixtures (that difference must be kept, not
    left to coincidence).
    """
    d = py_dir if py_dir is not None else repo("zreflect")
    found = set()
    for _name, text in knobs._py_sources(d):
        found.update(_TOKEN_RE.findall(text))
    return found


def _known_knobs_scans_repo():
    """`known_knobs()`'s default scan surface must be the **checked repo's** zreflect, not the tool's.

    The criterion tests **behavior**: place a phantom knob in a fixture repo,
    and `known_knobs()` must see it. The tool's own zreflect lacks that token
    ⇒ if the default directory drifts to the tool side, this goes red.
    """
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    d = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(d, "zreflect"))
        marker = "REFLECT_" + "PROBEONLY"        # built by concatenation: keeps the scan surface clean
        with open(os.path.join(d, "zreflect", "probe.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("X = os.environ.get('%s')\n" % marker)
        # ⚠️ `gate.repo()` reads the **module-level `GATE_REPO`** (snapshotted at
        # import time); mutating `os.environ` has no effect on it (observed:
        # after changing the env var, known_knobs still scanned the real repo).
        # The module attribute must be patched directly.
        import gate  # noqa: PLC0415
        prev = gate.GATE_REPO
        gate.GATE_REPO = d
        try:
            return marker in known_knobs()
        finally:
            gate.GATE_REPO = prev
    finally:
        shutil.rmtree(d, True)


def parse_exports(text):
    """Parse the effective exports of an env file (pure function: the selftest needs it).

    Returns {name: value}. Comment lines / blank lines are skipped — a
    file with only comments left ⇒ empty dict (the "looks configured"
    silent rot is reported by the caller). Values get quote stripping
    only, no variable expansion (the existence criteria don't need the
    expanded values).
    """
    out = {}
    for line in text.splitlines():
        m = _EXPORT_RE.match(line)
        if not m:
            continue
        out[m.group(1)] = _QUOTES_RE.sub("", m.group(2).strip())
    return out


def _phantom_token_problems(scanned, registry):
    """REFLECT_* tokens that appear in the scan surface but not in the registry (phantom / typo).

    The typo sample must be constructed by the caller via concatenation —
    this file is itself inside the scan surface, so a hardcoded literal
    would sweep the typo into the scan surface and the guard would be dead.
    """
    out = []
    for tok in sorted(scanned):
        if tok not in registry:
            out.append(M("envfile.unknown_knob", knob=tok))
    return out


def _existence_targets(kind, value):
    """Knob value → (list of paths to existence-check, is-dir flag); None = this kind isn't checked."""
    if kind == "file":
        return [value], False
    if kind == "list":
        return [t.strip() for t in value.split(",") if t.strip()], False
    if kind == "dir":
        return [value], True
    return None                         # number / flag / value get no existence check


def _export_problems(name, value, registry, file_exists, dir_exists):
    """Criteria for a single export: empty value / unregistered / missing target (order = report order)."""
    if not value:
        return [M("envfile.empty_value", key=name)]
    kind = registry.get(name, (None,))[0]
    if kind is None:
        return [M("envfile.unregistered_knob", key=name)]
    targets = _existence_targets(kind, value)
    if targets is None:
        return []
    paths, is_dir = targets
    # "file / dir" is a grammar noun, not a knob value: split into two codes so
    # no Chinese constant appears in a template (zero-language core); the knob
    # name and the path still travel as parameters.
    #
    # ⚠️ **Each of the two codes gets its own `M(...)` call**: written as
    # `M("a" if is_dir else "b")`, the `knobs.used_codes()` regex only catches
    # the first ⇒ the other doesn't exist in front of `pack_coverage`. The
    # language pack lacks it, the user sees a bare code, and the audit stays
    # green anyway (observed: this very case is what the newly added
    # `i18n_cover.code_not_literal` caught).
    out = []
    for t in paths:
        hit = dir_exists(t) if is_dir else file_exists(t)
        if not hit:
            entry = registry.get(name, ("", "", "?"))[2]
            out.append(M("envfile.dir_missing", key=name, entry=entry, target=t)
                       if is_dir else
                       M("envfile.file_missing", key=name, entry=entry, target=t))
    return out


def _syntax_problems(syntax_ok):
    """sh -n verdict → problems: False = file syntax broken; None = the instrument itself broke."""
    if syntax_ok is False:
        return [M("envfile.syntax_broken", name=ENV_FILE)]
    if syntax_ok is None:
        return [M("envfile.syntax_tool_broken")]
    return []


def problems(exports, registry, file_exists, dir_exists, syntax_ok=None,
             scanned=()):
    """Pure function: returns the problem list (empty = green). No printing allowed during selftest.

    `registry` = knobs.REGISTRY (name → (kind, default, semantics));
    `scanned` = the scan surface of known_knobs() (audits phantom / typo);
    `file_exists` / `dir_exists` = existence probes (selftest injects a fake
    filesystem);
    `syntax_ok` = the sh -n verdict (True / False; None = the instrument itself can't run).
    """
    if not exports:
        return [M("envfile.no_effective_export", name=ENV_FILE)]
    # Phantom / typo audit (scan surface) + per-export carrier criteria + sh syntax.
    out = _phantom_token_problems(scanned, registry)
    for name in sorted(exports):
        if not name.startswith("REFLECT_"):
            continue                    # non-knob exports are not this gate's business
        out += _export_problems(name, exports[name], registry,
                                file_exists, dir_exists)
    return out + _syntax_problems(syntax_ok)


def _find_env_file():
    """Same resolution order as the plugin: hooks directory first, repo root second."""
    for d in (repo("reflect-hooks"), repo()):
        p = os.path.join(d, ENV_FILE)
        if os.path.exists(p):
            return p
    return None


def run(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    p = _find_env_file()
    if p is None:
        # ⚠️ C3: the off early-return **only skips the carrier checks** — roster
        # self-consistency (phantom knobs / README phantoms) has nothing to do
        # with whether the carrier exists; it moved to knobs.py and is funneled
        # through registry.problems() (while it was welded here, this repo had
        # no Einfacht.env ⇒ it never executed; hit in practice).
        return off(M("envfile.off", name=ENV_FILE))
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as e:
        return fatal(M("envfile.unreadable", path=p, error=e))
    scanned = known_knobs()
    if not scanned:
        return fatal(M("envfile.scan_empty", path=repo("zreflect")))
    # Syntax check (instrument): sh -n parses only, never executes. A syntax
    # error ⇒ a problem to report; can't run at all ⇒ the instrument broke
    # (syntax_ok=None, reported as such).
    syntax = None
    try:
        r = subprocess.run(["sh", "-n", p], capture_output=True)
        syntax = r.returncode == 0
    except OSError:
        syntax = None
    exports = parse_exports(text)
    # Criteria inside the carrier: export-name typo / file knob pointing at a
    # missing target / empty value / sh syntax.
    # (README phantoms and the "tool-repo scan surface" phantoms belong to
    # knobs.py; this gate's scan covers the **checked repo's** zreflect/ —
    # only it can see typos in the downstream repo's own code, a scan surface
    # distinct from knobs'; both copies stay.)
    probs = problems(exports, REGISTRY,
                     lambda t: os.path.exists(repo(t)),
                     lambda t: os.path.isdir(repo(t)),
                     syntax_ok=syntax, scanned=scanned)
    return finish(M("envfile.title"), probs,
                  M("envfile.ok", path=os.path.relpath(p, repo()),
                    count=len(exports)))


def _cases_fixture():
    """Fixture (the setup section of the original `_cases`, moved over verbatim)."""
    good_files = ("STATE.md", "README.md", "README.zh.md",
                  "README.de.md", "FACTS.json", "AGENTS.md",
                  "RETRACT.json", "invariants.json")
    fe = lambda t: t in good_files                     # noqa: E731
    de = lambda t: t in ("questions", "cases")         # noqa: E731
    registry = {k: REGISTRY[k] for k in
                ("REFLECT_DOC", "REFLECT_READMES", "REFLECT_QUESTIONS",
                 "REFLECT_FACTS", "REFLECT_NAKED_MIN", "REFLECT_ENV_FILE")}
    good_env = {"REFLECT_DOC": "STATE.md",
                "REFLECT_READMES": "README.md,README.zh.md,README.de.md",
                "REFLECT_QUESTIONS": "questions",
                "REFLECT_NAKED_MIN": "100"}
    # The typo sample is built by concatenation: this file is inside the scan
    # surface and gets scanned by known_knobs() — a hardcoded literal would
    # sweep the typo into the scan surface and the guard would be dead.
    typo = "REFLECT_" + "DOCSS"
    return {'good_files': good_files, 'fe': fe, 'de': de, 'registry': registry, 'good_env': good_env, 'typo': typo}


def _cases_knobs(fx):
    """See `_cases()`: this group has 7 cases."""
    fe, de, registry, good_env, typo = fx["fe"], fx["de"], fx["registry"], fx["good_env"], fx["typo"]
    return [
    # (1) healthy input reports nothing
    ("envfile.ok",
     lambda: problems(good_env, registry, fe, de, syntax_ok=True,
                      scanned=registry.keys()) == []),
    ("envfile.scan_clean",
     lambda: problems(good_env, registry, fe, de, syntax_ok=True,
                      scanned=set(registry) | {"REFLECT_FACTS"}) == []),
    ("envfile.readme_nominations_registered",
     lambda: knobs.readme_problems(files={
         "README.md": "REFLECT_DOC REFLECT_READMES",
         "README.zh.md": "x", "README.de.md": "x"}) == []),
    # (2) what should be reported must be reported
    ("★ envfile.unknown_knob",
     lambda: any(getattr(p,"code","") == "envfile.unknown_knob" for p in problems(
         good_env, registry, fe, de, syntax_ok=True,
         scanned=set(registry) | {typo}))),
    ("★ envfile.unregistered_knob",
     lambda: any(getattr(p,"code","") == "envfile.unregistered_knob" for p in problems(
         {typo: "STATE.md"}, registry, fe, de, syntax_ok=True,
         scanned=registry.keys()))),
    ("★ envfile.file_missing.list_target",
     lambda: any(getattr(p,"code","") == "envfile.file_missing" and p.params.get("target") == "README.missing.md" for p in problems(
         {"REFLECT_READMES": "README.md,README.missing.md"},
         registry, fe, de, syntax_ok=True, scanned=registry.keys()))),
    # ⚠️ There used to be an "audit" case asserting `repo("zreflect") == knobs._zdir()` —
    # **that was wrong**: it only asserted a configuration fact (GATE_REPO wasn't
    # overridden) and had **nothing to do** with where `known_knobs` actually scans.
    # Observed: after changing known_knobs' default directory to `knobs._zdir()`
    # (a real drift), that assertion stayed green. A criterion must test the
    # **code path**, not a coincidence.
    # Replaced by the case below: the default directory must point at the
    # checked repo (under the fixture it really goes red).
    ("★ envfile.known_knobs_scans_checked_repo",
     lambda: _known_knobs_scans_repo()),
    ]


def _cases_carrier(fx):
    """See `_cases()`: this group has 8 cases."""
    fe, de, registry, typo = fx["fe"], fx["de"], fx["registry"], fx["typo"]
    return [
    ("envfile.non_reflect_export",
     lambda: problems({"PATH": "/usr/bin"}, registry, fe, de,
                      syntax_ok=True, scanned=registry.keys()) == []),
    ("★ envfile.file_missing",
     lambda: any(getattr(p,"code","") == "envfile.file_missing" for p in problems(
         {"REFLECT_DOC": "MYSTATE.md"}, registry, fe, de,
         syntax_ok=True, scanned=registry.keys()))),
    ("★ envfile.dir_missing",
     lambda: any(getattr(p,"code","") == "envfile.dir_missing" for p in problems(
         {"REFLECT_QUESTIONS": "STATE.md"}, registry, fe, de,
         syntax_ok=True, scanned=registry.keys()))),
    ("★ envfile.empty_value",
     lambda: any(getattr(p,"code","") == "envfile.empty_value" for p in problems(
         {"REFLECT_DOC": ""}, registry, fe, de, syntax_ok=True,
         scanned=registry.keys()))),
    # (3) empty input must be reported
    ("★ envfile.no_effective_export",
     lambda: problems({}, registry, fe, de, syntax_ok=True,
                      scanned=registry.keys()) != []),
    # Edge case (the criterion itself lives in knobs.py; one case is kept here as
    # a chained proof that the move lost no semantics):
    # a fake token must not be sliced out of a foreign prefix (the retraction
    # example text once got sliced into a fake knob name).
    # ⚠️ The sample is built by concatenation: this file is inside the scan
    # surface; a literal written out would get absorbed by the audit.
    ("★ envfile.prefix_word_not_sliced",
     lambda: knobs.readme_problems(files={
         "README.md": "> ZCODE_" + typo,
         "README.zh.md": "x", "README.de.md": "x"}) == []),
    # Quote stripping (the explicit precedence of _QUOTES_RE only spells things
    # out; behavior is character-for-character unchanged):
    # replay: python3 zreflect/check_envfile.py --selftest
    ("envfile.strip_quotes",
     lambda: parse_exports("D=\"hello\"")["D"] == "hello"
     and parse_exports("D='hello'")["D"] == "hello"),
    ("★ envfile.inner_quotes_kept",
     lambda: parse_exports("D=a\"b")["D"] == "a\"b"
     and parse_exports("D='a\"b'")["D"] == "a\"b"),
    ]


def _cases_syntax(fx):
    """See `_cases()`: this group has 2 cases."""
    fe, de, registry, good_env = fx["fe"], fx["de"], fx["registry"], fx["good_env"]
    return [
    ("★ envfile.syntax_broken",
     lambda: any(getattr(p,"code","") == "envfile.syntax_broken" for p in problems(
         good_env, registry, fe, de, syntax_ok=False,
         scanned=registry.keys()))),
    ("★ envfile.syntax_tool_broken",
     lambda: any(getattr(p,"code","") == "envfile.syntax_tool_broken" for p in problems(
         good_env, registry, fe, de, syntax_ok=None,
         scanned=registry.keys()))),
    ]


def _cases():
    """Assemble the 3 groups of fixture assertions. **Assemble only** — the criteria live in the group functions."""
    fx = _cases_fixture()
    return (
    _cases_knobs(fx)
    + _cases_carrier(fx)
    + _cases_syntax(fx)
    )


GATE = meta("env-file gate",
            "guards the hooks' REFLECT_* carrier (knob typos / dangling "
            "targets / empty values)",
            knobs=("REFLECT_ENV_FILE",),
            off_reason="a repo without an env carrier (all knobs at their "
                       "defaults) does not need it: spec not configured "
                       "⇒ state it is off")

if __name__ == "__main__":
    sys.exit(main_selftest_or(sys.argv[1:],
                              M("gate.title.envfile"),
                              _cases(), run))
