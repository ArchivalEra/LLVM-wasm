#!/usr/bin/env python3
"""Data layer of the facts ledger: read/write + two guards. **Pure functions, and therefore self-provable.**

Re-measurement has two silent rot modes, each paired with one guard:

  · **dropped entry** — the input is gone ⇒ the fact silently **disappears**.
    Guard: `dropped_keys()`.
  · **changed value** — the input changed, or was measured wrong ⇒ the fact
    silently **becomes a different number**. Guard: `changed_keys()`.

The changed-value mode is nastier: if a gate only spot-checks a few shas,
then once the old values of the other entries get overwritten there is
**no way left to find out they ever changed**. So the guard's scope must be
narrow and precise.
"""
import json
import time
from datetime import datetime, timedelta, timezone

from gate import (
    fatal_exit,  # noqa: E402
    machine,
    module_meta,
)
from i18n import M


class Unreadable(RuntimeError):
    """The ledger file exists but can't be read (bad JSON / permissions / encoding).

    **This is a different thing from "no ledger"**: the latter is the normal
    shape of a fresh repo (an empty table is returned when `missing_ok=True`),
    the former is a configuration accident — it must reach FATAL rc=2 and
    must never surface as a bare traceback (that would escape this repo's rc
    contract, and a traceback with rc=0 is even worse: the caller believes
    it succeeded).
    """


def load(path, missing_ok=False):
    """Read JSON. With `missing_ok=True` a **missing file returns an empty
    table** — for "a new repo's first run": the ledger doesn't exist yet, and
    `facts.py`'s two guards (dropped / changed) must be able to handle "there
    is no previous version". **The default remains a hard error**: the caller
    must explicitly say it accepts a missing ledger, so a mistyped path isn't
    silently taken for "no ledger yet".

    ⚠️ Bad JSON / permissions / encoding always raise `Unreadable` (not a bare
    `JSONDecodeError`): the caller converts that into FATAL rc=2. Previously
    everything bubbled to the top — observed: `facts.py --check` printed a
    traceback for a broken ledger with **rc=0**, and the caller believed it
    had been audited.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        if missing_ok:
            return {}
        raise
    except (OSError, UnicodeError, ValueError) as e:
        raise Unreadable(path, e) from e


def load_or_fatal(path, name=None):
    """Read the ledger; **broken file → FATAL rc=2** (`SystemExit(2)`).

    Gates use this instead of a bare `load()`: a broken ledger is a
    **configuration accident** and must take the FATAL tier, not surface as a
    traceback (Python would exit 1, and rc=1 in `registry --run` means
    "criterion red" — a completely different fix: fix the configuration vs
    fix the problem).

    Observed: a `{ broken` FACTS.json made `check_facts.py` print a traceback
    and exit 1, and the user would go fix the gate.
    """
    import sys  # noqa: PLC0415

    from i18n import M  # noqa: PLC0415
    try:
        return load(path)
    except Unreadable as e:
        cause = e.args[1] if len(e.args) > 1 else e
        print(machine().emit("fatal", M("ledger.unreadable_gate",
                                        name=name or path, error=cause)),
              file=sys.stderr)
        raise SystemExit(2) from e


def facts_of(ledger):
    """The facts table inside a ledger (tolerates two shapes: wrapped doc / the table itself)."""
    led = ledger or {}
    return led.get("facts") if isinstance(led, dict) and "facts" in led else (led or {})


def dropped_keys(old_facts, new_facts):
    """Which **keys** this re-measurement would drop (pure function: the selftest needs it)."""
    return sorted(set(old_facts or {}) - set(new_facts or {}))


def value_of(entry):
    """A fact's **value**. Tolerates both the dict shape and the bare-value shape.

    (Originally `_value`: consumed as an interface by check_facts /
    check_facts_replay / check_stale — the underscore-private name was private
    in name only, promoted on 2026-10-07.)
    """
    return entry.get("value") if isinstance(entry, dict) else entry


def short_value(v, n=24):
    """Shrink a value to one line (a 64-char sha keeps only its first 16), for the "changed value" hint."""
    s = v if isinstance(v, str) else str(v)
    if len(s) == 64:
        return s[:16] + "…"
    return s if len(s) <= n else s[:n] + "…"


def changed_keys(old_facts, new_facts):
    """Which keys' **values** this re-measurement would change. Returns `[(key, old value, new value)]`.

    ⚠️ **Compares `value` only**, not `cmd`/`source`/`note` — those describe
    "how to replay", and editing them is normal doc maintenance. If those also
    had to be explicitly accepted, the guard would turn into noise and end up
    being waved through wholesale by `--accept-changes`, dead as a guard.
    This also means: **a newly added key is not a changed value** (that's an
    addition, which this guard must not block).
    """
    olds = old_facts or {}
    out = []
    for k, nv in sorted((new_facts or {}).items()):
        if k not in olds:
            continue
        ov = value_of(olds[k])
        if ov != value_of(nv):
            out.append((k, ov, value_of(nv)))
    return out


def fact(value, cmd, source, note="", replay=True,
         witness=None, witness_expect=None,
         calibrate=None, calibrate_expect=None, kind="value"):
    """Make one fact: value + re-run command + source (+ optional note).

    ⚠️ **The bare-value contract of `cmd` (issue #2 (1))**: `check_facts_replay.py`
    **runs it verbatim** (cwd = repo root, bash + `pipefail`) and compares **stdout
    stripped of leading/trailing whitespace** against `value`. So `cmd` must
    **print only the value itself** — printing "the whole line containing the
    value" is readable by humans but not judgeable by machines, and the replay
    gate will read it as a mismatch. This contract is the premise for "re-runnable"
    being judgeable at all.

    Entries that start services / need build artifacts and cannot run in this
    environment at all: write `replay=False` explicitly (the replay gate skips
    them, and alarms when **every entry is exempted** — exemption has a roster,
    it is not silent).

    **Third tier: witness (issue #5)** — an expensive fact with `replay=False`
    can carry a **cheap witness**: `witness` (a cheap, harmless, read-only
    command) + `witness_expect` (the expected stdout). Witness is **orthogonal**
    to `replay`: the expensive fact's value is not re-run verbatim, but its
    **provenance/context** ("the tool/input that produced it is the one I think
    it is") is **really run at every commit**, under the same bare-value
    contract (`stdout.strip() == witness_expect`).

    **Fourth tier: instrument calibration (issue #6 (1))** — the replay contract
    catches "the command died" (rc≠0), but not **silent instrument drift**: the
    command succeeds, the value is stable, the re-run "passes" forever, yet what
    it measures is not the thing at all (`grep -c X` exits successfully with 0
    when the instrument does not recognize X). A `cmd` that claims "whether the
    artifact contains X" gets a **known-positive sample**: `calibrate` (a cheap
    command run against the sample) + `calibrate_expect` (the sample's known
    output). Orthogonal to `replay` / `witness`, **really run at every commit**,
    under the same bare-value contract. The `witness` / `calibrate` pairs must
    **each be given together** — giving only one is an incomplete shape, and
    the collector rejects it on the spot (a half assertion is easier to catch
    than a silent absence).

    `measured_at` is stamped automatically at **collection time** (issue #3 (2)):
    it is the record of "when it was measured", used for rendering the
    "measured at" column and for fact age, and **must never be treated as a
    measurement input** (collect.py principle 2: otherwise `--check` never
    converges — it is an output, not an input).
    `first_seen` (issue #6 (1)) is likewise stamped at collection time:
    `measure()` keeps the old date while the value is unchanged and takes today
    when the value changes — the always-the-same detection ("is this cmd
    measuring, or always returning the same number?") depends on it.
    """
    _require_pairs((witness, witness_expect, "witness"),
                   (calibrate, calibrate_expect, "calibrate"))
    d = {"value": value, "cmd": cmd, "source": source,
         "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
         "first_seen": time.strftime("%Y-%m-%d")}
    _fill_optional(d, note, replay, witness, witness_expect,
                   calibrate, calibrate_expect, kind)
    return d


def _require_pairs(*pairs):
    """Paired parameters must be given **together** — one alone is an incomplete
    shape, rejected on the spot.

    A half assertion is easier to catch than a silent absence: an entry with
    `witness` but no `witness_expect` would make the replay gate compare against
    `None`, reporting "value mismatch" instead of "shape incomplete".
    """
    for a, b, name in pairs:
        if (a is None) != (b is None):
            fatal_exit(M("ledger.shape_incomplete", name=name))


def _fill_optional(d, note, replay, witness, witness_expect,
                   calibrate, calibrate_expect, kind):
    """Fill the optional fields into the entry, only when given.

    ⚠️ **Fields not given are not written as empty values**: `"replay": True`
    and "no replay key" are the same thing downstream, but writing it in would
    litter the ledger with noise fields (and `changed_keys` would misjudge if
    it ever compared keys beyond `value`).
    """
    if note:
        d["note"] = note
    if not replay:
        d["replay"] = False
    if witness is not None:
        d["witness"] = witness
        d["witness_expect"] = witness_expect
    if calibrate is not None:
        d["calibrate"] = calibrate
        d["calibrate_expect"] = calibrate_expect
    # `kind` picks the **replay contract**:
    #   "value"     stdout must equal value (a numeric fact)
    #   "principle" rc==0 suffices, and stdout **must be empty** (a verdict,
    #               not a value)
    # Both contracts live in the same executor (`check_facts_replay`); no new
    # replay path is added.
    if kind != "value":
        d["kind"] = kind


def age_days(entry):
    """Days since this fact's collection time (non-negative float, issue #3 (2)).

    `measured_at` missing / unparseable ⇒ None — if it can't be read, say so;
    guessing 0 is not allowed (0 would be read as "just measured", a false
    assertion).
    """
    ts = entry.get("measured_at") if isinstance(entry, dict) else None
    if not ts:
        return None
    try:
        when = datetime.strptime(str(ts), "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - when).total_seconds() / 86400.0


# ── Self-verification (three tiers: clean reports nothing / what must report
#    reports / empty input reports) ─────────────────────────────────────────────
def _cases_guards():
    """(1) Dropped-entry / changed-value guards: clean reports nothing + what
    must report reports + a fresh start is legal."""
    from gate import raises  # noqa: PLC0415
    return [
        ("ledger.dropped_clean",
         lambda: dropped_keys({"a": 1}, {"a": 1, "c": 3}) == []),
        ("ledger.changed_clean",
         lambda: changed_keys({"a": {"value": 1}}, {"a": {"value": 1}}) == []),
        ("ledger.changed_cmd_only",
         lambda: changed_keys({"a": {"value": 1, "cmd": "old"}},
                              {"a": {"value": 1, "cmd": "new"}}) == []),
        ("\u2605 ledger.dropped_keys",
         lambda: dropped_keys({"a": 1, "b": 2}, {"a": 1}) == ["b"]),
        ("\u2605 ledger.changed_keys",
         lambda: changed_keys({"a": {"value": 1}}, {"a": {"value": 2}})
         == [("a", 1, 2)]),
        # (3) Empty input must report (here the opposite of "must not report":
        #     a fresh start is a legal first generation)
        ("ledger.first_run_dropped_silent",
         lambda: dropped_keys({}, {"a": 1}) == []),
        ("ledger.first_run_changed_silent",
         lambda: changed_keys({}, {"a": {"value": 1}}) == []),
        ("ledger.raises_detects",
         lambda: raises(lambda: (_ for _ in ()).throw(SystemExit(2)))),
    ]


def _cases_shapes():
    """Appendix: ledger shapes — the three interfaces `facts_of` / `short_value`
    / `value_of`."""
    return [
        ("ledger.facts_of_both_shapes",
         lambda: facts_of({"facts": {"a": 1}}) == {"a": 1}
         and facts_of({"a": 1}) == {"a": 1}),
        ("ledger.short_value_sha",
         lambda: short_value("a" * 64) == "a" * 16 + "\u2026"),
        # Steady state: `value_of` tolerates both the dict shape and the bare value
        ("ledger.value_of_both_shapes",
         lambda: value_of({"value": 3}) == 3 and value_of(7) == 7),
    ]


def _cases_measurement():
    """(2) Fact age + `first_seen` (issue #3 (2) / #6 (1))."""
    return [
        ("ledger.fact_stamps_measured_at",
         lambda: isinstance(fact(1, "c", "s").get("measured_at"), str)),
        ("ledger.age_days_missing_none", lambda: age_days({"value": 1}) is None),
        ("ledger.age_days_bad_stamp_none",
         lambda: age_days({"measured_at": "not-a-time"}) is None),
        ("ledger.age_days_fresh",
         lambda: 0 <= age_days({"measured_at": time.strftime(
             "%Y-%m-%dT%H:%M:%S%z")}) < 1),
        ("ledger.age_days_about_40",
         lambda: 39 < age_days({"measured_at": (
             datetime.now(timezone.utc) - timedelta(days=40)
         ).strftime("%Y-%m-%dT%H:%M:%S%z")}) < 41),
        ("ledger.fact_stamps_first_seen",
         lambda: fact(1, "c", "s").get("first_seen")
         == time.strftime("%Y-%m-%d")),
    ]


def _cases_probes():
    """(3) Witness / (4) instrument calibration (issue #5 / #6 (1)): paired
    fields — one alone must raise."""
    from gate import raises  # noqa: PLC0415
    return [
        ("ledger.witness_fields",
         lambda: fact(1, "c", "s", witness="w", witness_expect="e")
         .get("witness") == "w"
         and fact(1, "c", "s", witness="w", witness_expect="e")
         .get("witness_expect") == "e"),
        ("ledger.no_witness_no_field",
         lambda: "witness" not in fact(1, "c", "s")),
        ("\u2605 ledger.witness_only",
         lambda: raises(lambda: fact(1, "c", "s", witness="w"))),
        ("\u2605 ledger.witness_expect_only",
         lambda: raises(lambda: fact(1, "c", "s", witness_expect="e"))),
        ("ledger.calibrate_fields",
         lambda: fact(1, "c", "s", calibrate="cal", calibrate_expect="e")
         .get("calibrate") == "cal"),
        ("\u2605 ledger.calibrate_only",
         lambda: raises(lambda: fact(1, "c", "s", calibrate="cal"))),
        ("\u2605 ledger.calibrate_expect_only",
         lambda: raises(lambda: fact(1, "c", "s", calibrate_expect="e"))),
    ]


def _cases():
    """Four groups: guards / shapes / fact age / probes. They test four
    different facets of the ledger."""
    return (_cases_guards() + _cases_shapes()
            + _cases_measurement() + _cases_probes())


def _selftest():
    from gate import activate_or_fatal, selftest  # noqa: PLC0415
    # Activation **precedes** self-verification: a pack set but absent ⇒
    # FATAL rc 2 (this entry previously never activated, so with
    # REFLECT_LANG=de a nonexistent pack was silently accepted).
    rc = activate_or_fatal()
    if rc:
        return rc
    return selftest(M("gate.title.ledger"), _cases())


MODULE = module_meta("facts ledger data layer",
                     "pure functions: read/write + two guards", selftest=True)


if __name__ == "__main__":
    import sys  # noqa: PLC0415
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
    sys.exit(_selftest())
