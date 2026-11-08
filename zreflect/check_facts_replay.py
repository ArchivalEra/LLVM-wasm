#!/usr/bin/env python3
"""Replay gate: every ledger fact's `cmd` is **actually run once**, and stdout must equal the ledger value.

What it blocks is the mechanism's own biggest empty promise (issue #2 (1)):
the README opens with "this should be a re-runnable assertion", but the
mechanism as shipped had **nowhere that executes the `cmd`** — when a cmd
rots (path moved, tool renamed, command starts erroring), it goes, bad name
and all, straight into the living state document via `--render-doc`, and
every gate stays green as if nothing happened. "Re-runnable" stops being a
slogan and becomes an assertion re-proven at every pre-commit / pre-push.

Criteria (`cmd` runs verbatim, cwd = repo root):

  · **Bare-value contract**: stdout stripped of leading/trailing whitespace
    must **equal** the value (`str(value)`). Printing only "the whole line
    containing the value" ⇒ readable by humans, not judgeable by machines
    ⇒ judged a mismatch.
  · **rc ≠ 0 ⇒ report**: a bad command is not "the value changed", it is
    "the re-run mechanism itself died".
  · **Timeout ⇒ report** (default 10s, overridable via
    `REFLECT_REPLAY_TIMEOUT`): a command wired into pre-commit must not wait
    forever for a result.
  · **No `cmd` ⇒ report**: a fact without a re-run command is prose.
  · Pipes **no longer swallow errors**: with bash use `bash -o pipefail -c`
    (the "fails but green" shape where `cat is gone | wc -l` prints 0 with
    rc=0 is exactly what this gate must redden). Without bash it falls back
    to /bin/sh and says so in the output — criteria strength varying with the
    environment must never happen silently.

Three zero-value guards: empty ledger ⇒ report; not a single cmd ran
successfully (all rc≠0/timeout) ⇒ report; every fact declares
`replay: false` **and has no witness, no calibration** ⇒ report (full
exemption is not a "pass", it is "this gate checked nothing"; expensive
facts carrying witness / calibrate are still checked — issue #5/#6).

Third tier: **witness** (issue #5) — an expensive fact with `replay=False`
can carry a cheap witness (`witness` + `witness_expect`, both required
together; incomplete shapes are rejected on the spot by `ledger.fact()`).
Witness is **orthogonal** to `replay`: the value itself is not re-run
verbatim, but its **provenance/context** ("the tool/input that produced it
is the one I think it is") is **really run at every commit**, under the same
bare-value contract (`stdout.strip() == witness_expect`). "Expensive" is
precisely where a cheap re-check matters most: the artifact did not change,
but the tool producing it did — that can slip all the way to the most
expensive end-to-end regression before exploding. The witness catches it at
commit time.

Fourth tier: **instrument calibration** (issue #6 (1)) — the replay contract
catches "the command died" (rc≠0), but not **silent instrument drift**: the
command succeeds, the value is stable, the re-run "passes" forever, yet what
it measures is not the thing at all (`grep -c X` exits successfully with 0
when the instrument does not recognize X). A `cmd` that claims "whether the
artifact contains X" gets a **known-positive sample**: `calibrate` (a cheap
command run against the sample) + `calibrate_expect` (the sample's known
output), orthogonal to `replay` / `witness`, **really run at every commit**,
under the same bare-value contract.

Boundary (stated explicitly in issue #2 (1), don't overdo it): replay should
cover only facts that **need no build artifacts**. The ones that start
services or compile binaries opt out explicitly with
`fact(value, cmd, source, replay=False)` — that is an exemption with a
roster and a stated reason, not silence; the whole gate also keeps a
repo-wide exit via `REFLECT_REPLAY=off` (same precedent as `REFLECT_RETIRED`:
**state that it is not enabled, don't pretend it was checked**).
Another class needs no build artifacts but is **different on every run**
(random padding lengths, GREASE payloads, timestamps — issue #4 (5)): store
**one measured sample** + a pair of `*_stable` stability marker keys
(consumers split into two tiers: stable judged verbatim, unstable judged
structurally), or set `replay=False` explicitly — **bare storage is
forbidden**: bare storage = this fact is red forever = noise = eventually
the whole gate gets switched off. A value that changes ≠ it cannot enter the
ledger; you must first declare how it changes.

⚠️ This gate executes **commands from this repo's own ledger** — the trust
boundary is the same as the pre-commit scripts themselves. The ledger is a
file the repo produces and reviews itself; editing the ledger = an
edit-build-script-level commitment, not a runtime input.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gate import fatal, finish, main_selftest_or, meta, off, repo  # noqa: E402
from i18n import Catalog, M, bind, load_pack
from knobs import a_pack_lang  # noqa: E402
from ledger import facts_of, load_or_fatal, value_of  # noqa: E402
from runner import (  # noqa: E402
    default_timeout,
    quote,
    run_cmd,
    timeout_with_status,
)


def _replay_one(k, raw_entry, run, seconds, out, stats):
    """Replay **one** fact, writing results into out / stats (issue #22 complexity split).

    Each branch does exactly one thing: skip (replay=False) / missing cmd /
    timeout / bad rc / value mismatch.
    """
    entry = raw_entry if isinstance(raw_entry, dict) else {"value": raw_entry}
    cmd = str(entry.get("cmd") or "").strip()
    if entry.get("replay") is False:
        stats["skipped"] += 1
        return
    if not cmd:
        out.append(M("replay.no_cmd", key=k))
        return
    stats["attempts"] += 1
    rc, stdout = run(cmd)
    if rc is None:
        out.append(M("replay.timeout", key=k, seconds=seconds, command=cmd))
        return
    if rc != 0:
        # `stdout` has by now had stderr appended by `run_cmd` (see its
        # comment) — put it into the message, otherwise "the command crashed"
        # leaves you guessing.
        out.append(M("replay.command_failed", key=k, return_code=rc,
                     command=cmd, detail=quote(stdout.strip()[:200])))
        return
    stats["ran"] += 1
    _judge_ok(k, entry, cmd, stdout, out, stats)


def _judge_ok(k, entry, cmd, stdout, out, stats):
    """The judgment after rc==0: principle entries check for a "stance", numeric entries check bare-value equality.

    ⚠️ The principle-entry contract is **both conditions together** (a
    directional mistake was made here once — exactly the thing this repo was
    founded to kill: recreating fake green inside a mechanism built to kill
    fake green):

      · stdout **non-empty** — a gate that really ran takes a stance
        (`ok(…)` or `OFF: …`); a command that says nothing cannot be
        distinguished between "ran and passed" and "never ran at all".
      · stdout **contains no `OFF:` line** — that is "not enabled", not
        "passed".

    rc-only judging launders off into green (this repo's history: "8 of 13
    gates off, all green, invisible"); stdout-only judging misreads a
    "silent pass". Both conditions are required.
    """
    if entry.get("kind") == "principle":
        got = stdout.strip()
        if not got:
            out.append(M("replay.principle_said_nothing", key=k, command=cmd))
            return
        import machine  # noqa: PLC0415
        if any(kind == "off" for _i, kind, _ln in machine.scan(got)):
            out.append(M("replay.principle_is_off", key=k,
                         command=cmd, detail=quote(got[:120])))
            return
        stats["ok"] += 1
        return
    got = stdout.strip()
    want = str(value_of(entry))
    if got != want:
        out.append(M("replay.mismatch", key=k,
                     actual=quote(got), expected=quote(want)))
        return
    stats["ok"] += 1




# ⚠️ **Cycle guard** (observed blowing memory: OOM).
#
# A principle's cmd may be **another gate** (that is reuse). But if that gate
# itself can trigger a replay (`registry --run commit` reaches this gate;
# so does `gates-selftest.sh`), you get an `A → B → A` cycle. Without a
# guard it spawns child processes without end until OOM
# (observed: `principle.only_measured`'s cmd was this very file — re-running
# itself).
#
# Two guards, both required:
#   · **In-process**: while this module is already replaying, a nested call
#     to `replay_all` returns an empty result immediately and records a
#     `replay.nested` (returning silently would amount to "the nested layer
#     says everything is fine");
#   · **Cross-process**: the child inherits the `EINFACHT_REPLAY_DEPTH`
#     environment variable; above the cap ⇒ the whole gate reports
#     `replay.too_deep` (not a silent skip — a cycle is a configuration
#     error that needs a human to fix the ledger, not runtime noise).
_DEPTH_ENV = "EINFACHT_REPLAY_DEPTH"
_MAX_DEPTH = 2          # top level (1) → sub-gate (2) at most; deeper is a cycle


def _depth():
    try:
        return int(os.environ.get(_DEPTH_ENV, "0") or 0)
    except ValueError:
        return 0


def _probe_failure(kind, key, rc, seconds, command, got, want):
    """A probe's failure message. Each tier has its **own literal code**.

    ⚠️ The `i18n` contract requires codes to be literals (composed codes make
    the language-pack directory impossible to prove complete), and in the
    language packs "witness" and "calibrate" are two different sentences —
    stuffing the noun into a parameter would break template word order in
    non-Chinese languages. So this is an `if/else`, not
    `"replay.%s_…" % kind`.
    """
    if rc is None:
        return (M("replay.witness_timeout", key=key, seconds=seconds,
                  command=command) if kind == "witness"
                else M("replay.calibrate_timeout", key=key,
                       seconds=seconds, command=command))
    if rc != 0:
        return (M("replay.witness_command_failed", key=key,
                  return_code=rc, command=command) if kind == "witness"
                else M("replay.calibrate_command_failed", key=key,
                       return_code=rc, command=command))
    return (M("replay.witness_mismatch", key=key,
              actual=quote(got), expected=quote(want)) if kind == "witness"
            else M("replay.calibrate_mismatch", key=key,
                   actual=quote(got), expected=quote(want)))


def _run_probe(kind, key, entry, run, seconds):
    """Run one probe (witness / calibrate). Returns `(problem or None, passed)`."""
    probe = str(entry.get(kind) or "").strip()
    if not probe:
        return None, False
    expect = entry.get(kind + "_expect")
    rc, stdout = run(probe)
    if rc is None or rc != 0:
        return _probe_failure(kind, key, rc, seconds, probe, "", ""), False
    got = stdout.strip()
    want = str(expect) if expect is not None else ""
    if got != want:
        return _probe_failure(kind, key, rc, seconds, probe, got, want), False
    return None, True


def _one_probe(kind, ok_key, key, entry, run, seconds, out, stats):
    """A single probe: no such kind ⇒ skip; present ⇒ count one attempt, run it, keep the books."""
    if not str(entry.get(kind) or "").strip():
        return
    stats[kind + "_attempts"] += 1
    problem, passed = _run_probe(kind, key, entry, run, seconds)
    if problem is not None:
        out.append(problem)
    if passed:
        stats[ok_key] += 1


def _run_probes(f, run, seconds, out, stats):
    """Probe tier (#5 witness / #6 (1) instrument calibration): orthogonal to
    replay — an expensive fact's provenance / instrument really runs each
    commit, under the same bare-value contract."""
    for kind, ok_key in (("witness", "witnessed"), ("calibrate", "calibrated")):
        for key in sorted(f):
            entry = f[key] if isinstance(f[key], dict) else {"value": f[key]}
            _one_probe(kind, ok_key, key, entry, run, seconds, out, stats)


def replay_all(ledger, runner=None):
    """Replay entry by entry, returning {problems, ok, attempts, skipped}. **Side effects flow only through runner**.

    `runner(cmd) -> (rc, stdout)` is injectable (the selftest uses a fake
    runner — once the real shell enters the selftest, the selftest depends on
    the machine). The pure function stays quiet: not one print here.
    """
    if _depth() >= _MAX_DEPTH:
        return {"problems": [M("replay.too_deep", depth=_depth(),
                               limit=_MAX_DEPTH)],
                "ok": 0, "attempts": 0, "ran": 0, "skipped": 0,
                "witness_attempts": 0, "witnessed": 0,
                "calibrate_attempts": 0, "calibrated": 0}
    run = runner or run_cmd
    out = []
    f = facts_of(ledger)
    stats = {"ok": 0, "attempts": 0, "ran": 0, "skipped": 0,
             "witness_attempts": 0, "witnessed": 0,
             "calibrate_attempts": 0, "calibrated": 0}
    if not f:
        # Zero-value guard: an empty ledger is not "no violations", it is
        # "nothing was measured".
        stats["problems"] = [M("replay.empty_ledger")]
        return stats
    seconds = default_timeout()
    for k in sorted(f):
        _replay_one(k, f[k], run, seconds, out, stats)
    if stats["attempts"] and stats["ran"] == 0:
        out.append(M("replay.none_ran", attempts=stats["attempts"]))
    _run_probes(f, run, seconds, out, stats)
    if not stats["attempts"] and stats["skipped"] and not stats["witness_attempts"] \
            and not stats["calibrate_attempts"]:
        out.append(M("replay.all_skipped", count=stats["skipped"]))
    stats["problems"] = out
    return stats


def run(argv):
    import knobs  # noqa: PLC0415
    # Go through `knobs.flag` (the single place of origin) — the previous
    # `.lower() == "off"` was a second vocabulary.
    if knobs.flag("REFLECT_REPLAY") is False:
        return off(M("replay.off"))
    # Parsing lives in exactly one place (runner.timeout_with_status) — this
    # used to probe again with its own float(), so the same bad value was
    # silent in the runner and warned here (observed: an empty string got two
    # different treatments).
    seconds, bad_timeout = timeout_with_status()
    if bad_timeout is not None:
        print("⚠ %s" % M("replay.bad_timeout", value=bad_timeout,
                         default=seconds), file=sys.stderr)
    name = os.environ.get("REFLECT_FACTS", "FACTS.json")
    p = repo(name)
    if not os.path.exists(p):
        return fatal(M("replay.ledger_missing", name=name))
    r = replay_all(load_or_fatal(p))
    tail = str(M("replay.ok_skipped", count=r["skipped"])) if r["skipped"] else ""
    wtail = str(M("replay.ok_witnessed", count=r["witnessed"])) if r["witnessed"] else ""
    ctail = str(M("replay.ok_calibrated", count=r["calibrated"]) if r["calibrated"] else "")
    return finish(M("replay.title"), r["problems"],
                  M("replay.ok", count=r["ok"], skipped=tail,
                    witnessed=wtail, calibrated=ctail))


LED = {"facts": {"n": {"value": 12, "cmd": "c"}}}




def _cases_fixture():
    """Build the fixture ledgers + rendering closures. Returns a dict, fed to the three group functions."""
    multi = {"facts": {"a": {"value": 1, "cmd": "ca"},
                       "b": {"value": 2, "cmd": "cb", "replay": False}}}
    wit = {"facts": {"expensive": {"value": "bench-42", "cmd": "run-bench",
                                    "replay": False,
                                    "witness": "echo tool-ok",
                                    "witness_expect": "tool-ok"}}}
    cal = {"facts": {"objcheck": {"value": "fma-present", "cmd": "scan-artifact",
                                   "replay": False,
                                   "calibrate": "echo known-positive",
                                   "calibrate_expect": "known-positive"}}}
    # Criteria of the kind "the message must point at the repair" (re-test
    # guidance / cold-start hint) cannot be verified against the null pack —
    # the null pack only has code + params, no sentences. So read a **real
    # shipped zh pack from disk** (`zreflect/lang/zh/facts_replay.json`) and
    # treat the rendered result as the assertion surface.
    #
    # Why read the real pack instead of injecting a fake table: injecting a
    # fake table only proves "the template I wrote renders the words I
    # wrote" — circular reasoning. Reading the real pack turns "the migration
    # lost no semantics" into a falsifiable claim: if the cold-start hint
    # fell out of the zh pack, this selftest goes red on the spot. (The zh
    # pack stores, by contract, the **verbatim removed text**, so it doubles
    # as evidence of migration fidelity.)
    # ⚠️ Likewise must not hard-code `zh` (see the same note in check_facts):
    # installing exactly one pack is the product's main scenario. Use the
    # **first installed pack**; none at all ⇒ the case cannot exist, stated
    # openly.
    pack_lang = a_pack_lang()
    real_pack = load_pack(pack_lang) if pack_lang else {}

    def codes(ledger, runner):
        return [p.code for p in replay_all(ledger, runner=runner)["problems"]]

    def said(ledger, runner):
        """The text rendered under that language pack (zero packs ⇒ empty list; criterion see pack_entry_wired)."""
        if not pack_lang:
            return []
        with bind(Catalog.load(pack_lang, {pack_lang: real_pack})):
            return [str(p) for p in replay_all(ledger, runner=runner)["problems"]]

    def _hint_has(ledger, runner, *anchors):
        """Do the rendered sentences all contain these **ASCII anchors** (the caller handles the zero-pack conditional short circuit)?"""
        return any(all(a in text for a in anchors)
                   for text in said(ledger, runner))

    def params(ledger, runner, code):
        return [p.params for p in replay_all(ledger, runner=runner)["problems"]
                if p.code == code]

    return {"multi": multi, "wit": wit, "cal": cal, "said": said,
            "hint_has": _hint_has, "params": params, "codes": codes,
            "pack_lang": pack_lang}


def _cases_replay_ok(fx):
    """(1) normal: no report — trailing newline / surrounding whitespace stripped / explicit skip."""
    multi = fx["multi"]
    return [
        ("replay.ok_trailing_newline",
         lambda: replay_all(LED, runner=lambda c: (0, "12\n"))["problems"] == []),
        ("replay.ok_string_value",
         lambda: replay_all({"facts": {"s": {"value": "v1", "cmd": "c"}}},
                            runner=lambda c: (0, " v1\n"))["problems"] == []),
        ("replay.ok_skip_declared",
         lambda: replay_all(multi, runner=lambda c: (0, "1"))["problems"] == []),
    ]


def _cases_replay_failures(fx):
    """(2) what must be reported gets reported: mismatch / dead command / timeout / missing cmd.

    The two "repair anchor" cases (`replay.mismatch_repair_hint` /
    `timeout_cold_start_hint`) are **conditional criteria**: a language pack
    installed means the message must carry the ASCII anchors
    (`--accept-changes` / `REFLECT_REPLAY_TIMEOUT`); zero packs is a legal
    state with no sentences to verify — stated openly, not faked as a pass.
    """
    _hint_has, params = fx["hint_has"], fx["params"]
    codes, pack_lang = fx["codes"], fx["pack_lang"]
    return [
        ("\u2605 replay.mismatch_repair_hint",
         # The real pack's "mismatch" message must still carry the repair
         # anchors: `--accept-changes` (ASCII — the decidable part of the
         # repair) + `facts.py` (the re-test command). Pure Chinese semantic
         # anchors would turn themselves into "natural language inside the
         # core" — exactly the shape the zero-language gate exists to
         # eliminate.
         lambda: codes(LED, lambda c: (0, "13")) == ["replay.mismatch"]
         and params(LED, lambda c: (0, "13"), "replay.mismatch")[0]["key"] == "n"
         and (not pack_lang or _hint_has(LED, lambda c: (0, "13"),
                                         "accept-changes", "facts.py"))),
        ("\u2605 replay.mismatch_full_line",
         lambda: codes(LED, lambda c: (0, "count=12 total"))
         == ["replay.mismatch"]),
        ("\u2605 replay.command_failed",
         lambda: codes(LED, lambda c: (1, ""))
         == ["replay.command_failed", "replay.none_ran"]
         and params(LED, lambda c: (1, ""),
                    "replay.command_failed")[0]["return_code"] == 1),
        ("\u2605 replay.timeout_cold_start_hint",
         # The cold-start hint's semantic anchor: the `REFLECT_REPLAY_TIMEOUT`
         # knob name (ASCII) must still be in the template — delete the
         # cold-start sentence (which originally carried the knob name) ⇒
         # this case goes red.
         lambda: codes(LED, lambda c: (None, ""))
         == ["replay.timeout", "replay.none_ran"]
         and (not pack_lang or _hint_has(LED, lambda c: (None, ""),
                                         "REFLECT_REPLAY_TIMEOUT"))),
        ("\u2605 replay.no_cmd",
         lambda: codes({"facts": {"n": {"value": 1, "source": "s"}}},
                       lambda c: (0, "1")) == ["replay.no_cmd"]),
    ]


def _cases_replay_empty(fx):
    """(3) empty input must be reported: empty ledger / not one cmd ran / all skipped."""
    codes, params = fx["codes"], fx["params"]
    two = {"facts": {"a": {"value": 1, "cmd": "x"},
                     "b": {"value": 2, "cmd": "y"}}}
    return [
        ("\u2605 replay.empty_ledger",
         lambda: codes({"facts": {}}, lambda c: (0, "")) == ["replay.empty_ledger"]),
        ("\u2605 replay.none_ran",
         lambda: codes(two, lambda c: (1, ""))
         == ["replay.command_failed", "replay.command_failed",
             "replay.none_ran"]
         and params(two, lambda c: (1, ""),
                    "replay.none_ran")[0]["attempts"] == 2),
        ("\u2605 replay.all_skipped",
         lambda: codes({"facts": {"a": {"value": 1, "cmd": "x",
                                        "replay": False}}},
                       lambda c: (0, "1")) == ["replay.all_skipped"]),
    ]


def _cases_replay(fx):
    """See `_cases()`: this group has 11 entries.

    Three sub-groups (normal / must-report / empty input): in the flat list
    of 11, the two **conditional criteria** (anchors verified only when a
    pack is installed) are mixed in, and a reader cannot easily see why they
    carry `not pack_lang`.
    """
    return (_cases_replay_ok(fx) + _cases_replay_failures(fx)
            + _cases_replay_empty(fx))


def _cases_witness(fx):
    """See `_cases()`: this group has 6 entries."""
    codes = fx["codes"]
    wit = fx["wit"]
    return [
    # (3) witness tier (issue #5)
    ("replay.witness_ok",
     lambda: replay_all(wit, runner=lambda c: (0, "tool-ok"))["problems"] == []),
    ("replay.witness_counted",
     lambda: replay_all(wit, runner=lambda c: (0, "tool-ok"))["witnessed"] == 1),
    ("★ replay.witness_mismatch",
     lambda: codes(wit, lambda c: (0, "tool-CHANGED"))
     == ["replay.witness_mismatch"]),
    ("★ replay.witness_command_failed",
     lambda: codes(wit, lambda c: (1, "")) == ["replay.witness_command_failed"]),
    ("★ replay.witness_timeout",
     lambda: codes(wit, lambda c: (None, "")) == ["replay.witness_timeout"]),
    ("replay.witness_satisfies_guard",
     lambda: "replay.all_skipped" not in
     codes(wit, lambda c: (0, "tool-ok"))),
    ]


def _cases_calibrate(fx):
    """See `_cases()`: this group has 6 entries."""
    codes = fx["codes"]
    cal = fx["cal"]
    return [
    # (4) instrument calibration tier (issue #6 (1))
    ("replay.calibrate_ok",
     lambda: replay_all(cal, runner=lambda c: (0, "known-positive"))["problems"] == []),
    ("replay.calibrate_counted",
     lambda: replay_all(cal, runner=lambda c: (0, "known-positive"))["calibrated"] == 1),
    ("★ replay.calibrate_mismatch",
     lambda: codes(cal, lambda c: (0, "wrong")) == ["replay.calibrate_mismatch"]),
    ("★ replay.calibrate_command_failed",
     lambda: codes(cal, lambda c: (1, "")) == ["replay.calibrate_command_failed"]),
    ("★ replay.calibrate_timeout",
     lambda: codes(cal, lambda c: (None, "")) == ["replay.calibrate_timeout"]),
    ("replay.calibrate_satisfies_guard",
     lambda: "replay.all_skipped" not in
     codes(cal, lambda c: (0, "known-positive"))),
    ]


def _cases():
    """Assemble the three fixture groups. **Assembly only** — the criteria live in the group functions."""
    fx = _cases_fixture()
    return (
        _cases_replay(fx)
        + _cases_witness(fx)
        + _cases_calibrate(fx)
    )



GATE = meta("Replay gate", "ledger cmds re-run verbatim (bare-value contract: stdout must equal the value)",
            knobs=("REFLECT_FACTS", "REFLECT_REPLAY", "REFLECT_REPLAY_TIMEOUT"),
            name_dependent=True,
            # ⚠️ This used to say "stated as not enabled when unset" — **a
            # lie**: it runs when unset, and only an explicit
            # `REFLECT_REPLAY=off` turns it off (all three states observed).
            # Replay now carries the "principles force-run at every commit"
            # requirement and must not default to off.
            off_reason="the whole gate closes only when REFLECT_REPLAY=off is set explicitly (this is the repo-wide exit; unset it still runs)")

if __name__ == "__main__":
    sys.exit(main_selftest_or(sys.argv[1:],
                              M("gate.title.facts_replay"),
                              _cases, run))
