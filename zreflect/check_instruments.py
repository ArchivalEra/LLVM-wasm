#!/usr/bin/env python3
"""Instrument lifecycle gate (**pluggable module**, issue #6 item 1).

The facts system guards values, assertions, and sources, but never guarded
**whether the command/instrument doing the measuring itself rots**. The `cmd`
replay contract (issue #2, item 1) catches "the command died" (rc != 0) but
cannot catch **silent instrument distortion**: the command succeeds, the value
is stable, the replay "passes" forever -- yet it is not measuring what it was
meant to measure. `grep -c X` **exits successfully returning 0** when the
instrument does not recognize X -- the stealthiest kind.

This gate is **pluggable**: with both knobs unset => explicitly not enabled,
exit 0 (repos that do not configure it are entirely unaffected; the
discovery-based roster still enrolls it, and the selftest still proves it can
go red). Enabling (each part independent):

  - `REFLECT_INSTRUMENT_DAYS=<days>` -- **constancy detection**: when a ledger
    entry's `first_seen` (maintained automatically by `measure()`: value
    unchanged keeps the old date, a changed value stamps today,
    `ledger.fact()` does the stamping) is older than the threshold => report
    "human confirmation needed: is this cmd measuring, or does it always
    return the same number?". Unset = that rule explicitly not enabled
    (unreadable / unparseable first_seen is also reported -- if it cannot be
    read, say so; guessing is not allowed).

  - `REFLECT_INSTRUMENTS=instruments.json` -- **the method registry**
    (schema: `{"methods": [{text, why, fixed_in}]}`): falsified **measuring
    methods** get a registration slot, the way `retractions.json` handles
    "retracted assertions"; any ledger `cmd` containing a falsified snippet =>
    report (a broken measuring method must not stay in the ledger). Knob set
    but the registry file missing => report (configured but never registered =
    a broken promise).

Zero-value guard: an empty ledger => report (empty is not a pass).

Usage (run directly, cwd = repo root):
    python3 zreflect/check_instruments.py [--selftest]
Exit codes: 0 = green / 1 = problems found / 2 = config or environment broken
(a config failure is not a check failure).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gate import (  # noqa: E402
    fatal,
    finish,
    load_spec,
    main_selftest_or,
    meta,
    off,
    repo,  # noqa: E402
)
from i18n import M  # noqa: E402
from ledger import facts_of, load_or_fatal  # noqa: E402

INSTRUMENTS_RAW = os.environ.get("REFLECT_INSTRUMENTS", "").strip()
DAYS_RAW = os.environ.get("REFLECT_INSTRUMENT_DAYS", "").strip()


def _days():
    if not DAYS_RAW:
        return None
    try:
        return float(DAYS_RAW)
    except ValueError:
        return None


def _age_days(first_seen):
    """Age in days of first_seen (%Y-%m-%d); unparseable => None (if it cannot
    be read, say so)."""
    try:
        d = datetime.strptime(str(first_seen), "%Y-%m-%d").replace(
            tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - d).total_seconds() / 86400.0


def _constant_return_problems(f, days):
    """Constancy detection: a `first_seen` older than the threshold => "is this
    cmd measuring, or does it always return the same number?\""""
    out = []
    for k in sorted(f):
        entry = f[k] if isinstance(f[k], dict) else {"value": f[k]}
        fs = entry.get("first_seen")
        if not fs:
            continue                  # old ledger entries have no first_seen: do not guess, do not report
        age = _age_days(fs)
        if age is None:
            out.append(M("instruments.first_seen_unparseable",
                         key=k, first_seen=fs))
        elif age > days:
            out.append(M("instruments.constant_return", key=k,
                         first_seen=fs, days=age, threshold=days))
    return out


def _falsified_hits(text, why, fixed, f):
    """The ledger keys hit by one falsified snippet (a hit = that fact still
    uses the broken measuring method)."""
    hits = []
    for k in sorted(f):
        entry = f[k] if isinstance(f[k], dict) else {"value": f[k]}
        if text in str(entry.get("cmd") or ""):
            hits.append(M("instruments.falsified_method", key=k, text=text,
                          why=why, fixed_in=fixed))
    return hits


def _falsified_method_problems(f, methods):
    """Method registry: any ledger `cmd` containing a falsified snippet =>
    report (a broken measuring method must not stay in the ledger)."""
    out = []
    for m in (methods or []):
        text = str(m.get("text") or "").strip()
        why = str(m.get("why") or "").strip()
        if not text or not why:
            out.append(M("instruments.entry_malformed", entry=m))
            continue
        fixed = m.get("fixed_in") or M("instruments.fixed_in_unregistered")
        out += _falsified_hits(text, why, fixed, f)
    return out


def problems(ledger, methods=None, days=None):
    """Pure function: return the problem list (empty = green). No printing
    during the selftest.

    `methods` = the method registry (list of falsified measuring methods);
    `days` = the constancy-detection threshold (None = that rule not enabled).
    **The two are independent**: constancy detection handles "the value has
    never changed", the registry handles "the measuring method itself was
    falsified" -- each is its own named helper, each understandable alone.
    """
    f = facts_of(ledger)
    if not f:
        return [M("instruments.ledger_empty")]
    out = []
    if days is not None:
        out += _constant_return_problems(f, days)
    out += _falsified_method_problems(f, methods)
    return out


def _load_methods(name):
    """Read the method registry (the JSON `REFLECT_INSTRUMENTS` points at).
    Returns `(methods, rc)`."""
    if not name:
        return [], 0
    reg_path = repo(name)
    if not os.path.exists(reg_path):
        return [], fatal(M("instruments.registry_missing", name=name))
    reg, err = load_spec(reg_path)
    if err:
        return [], fatal(M("instruments.spec_broken", name=name, error=err))
    return reg.get("methods") or [], 0


def run(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    name = INSTRUMENTS_RAW
    days = _days()
    if DAYS_RAW and days is None:
        return fatal(M("instruments.days_unparseable",
                       days_knob="REFLECT_INSTRUMENT_DAYS", value=DAYS_RAW))
    if not name and days is None:
        return off(M("instruments.off",
                     days_knob="REFLECT_INSTRUMENT_DAYS",
                     instruments_knob="REFLECT_INSTRUMENTS"))
    led_path = repo(os.environ.get("REFLECT_FACTS", "FACTS.json"))
    if not os.path.exists(led_path):
        return fatal(M("instruments.ledger_missing", path=led_path))
    methods, rc = _load_methods(name)
    if rc:
        return rc
    probs = problems(load_or_fatal(led_path), methods=methods, days=days)
    return finish(M("instruments.title"), probs, _ok_line(name, methods, days))


def _ok_line(name, methods, days):
    """The pass line must state **which modes are on** (otherwise "green" cannot
    distinguish "everything on" from "nothing on")."""
    parts = []
    if days is not None:
        parts.append(M("instruments.part_days", threshold=days))
    if name:
        parts.append(M("instruments.part_methods", name=name,
                       count=len(methods)))
    return M("instruments.ok",
             modes=" + ".join(parts) or M("instruments.part_none"))


def _cases():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    old = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%d")
    led = {"facts": {"n": {"value": 7, "cmd": "echo 7", "source": "s",
                              "first_seen": today}}}
    led_old = {"facts": {"n": {"value": 7, "cmd": "echo 7", "source": "s",
                                  "first_seen": old}}}
    led_bad = {"facts": {"n": {"value": 7, "cmd": "echo 7", "source": "s",
                                  "first_seen": "bad-date"}}}
    led_method = {"facts": {"n": {"value": 7,
                                     "cmd": "llvm-objdump -d x.o | grep -c relaxed_madd",
                                     "source": "s", "first_seen": today}}}
    methods = [{"text": "grep -c relaxed_madd",
                "why": "llvm-objdump only prints <unknown> for relaxed-simd, "
                       "grep is always 0 (command succeeds, value stable, replay "
                       "passes forever)",
                "fixed_in": "calibrate= a calibration sample known to contain relaxed_madd"}]
    return [
        # (1) compliant input: nothing reported
        ("instruments.fresh",
         lambda: problems(led, days=30) == []),
        ("instruments.registered_method_absent",
         lambda: problems(led, methods=methods, days=30) == []),
        ("instruments.first_seen_absent",
         lambda: problems({"facts": {"n": {"value": 1, "cmd": "c"}}},
                          days=30) == []),
        # (2) what must be reported is reported
        ("★ instruments.constant_return",
         lambda: [p.code for p in problems(led_old, days=30)]
         == ["instruments.constant_return"]),
        ("★ instruments.first_seen_unparseable",
         lambda: [p.code for p in problems(led_bad, days=30)]
         == ["instruments.first_seen_unparseable"]),
        ("★ instruments.falsified_method",
         lambda: [p.code for p in problems(led_method, methods=methods)]
         == ["instruments.falsified_method"]),
        ("★ instruments.entry_malformed",
         lambda: [p.code for p in problems(led, methods=[{"text": "x"}])]
         == ["instruments.entry_malformed"]),
        # (3) empty input must be reported
        ("★ instruments.ledger_empty",
         lambda: [p.code for p in problems({"facts": {}}, days=30)]
         == ["instruments.ledger_empty"]),
    ]


GATE = meta("Instrument lifecycle gate", "constancy detection (first_seen) + falsified-method registry",
            knobs=("REFLECT_INSTRUMENTS", "REFLECT_INSTRUMENT_DAYS", "REFLECT_FACTS"),
            off_reason="both knobs unset => the specialized mechanism is not enabled"
                       " (pluggable; this repo turns it on when needed)")

if __name__ == "__main__":
    sys.exit(main_selftest_or(sys.argv[1:], "check_instruments", _cases, run))
