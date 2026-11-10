#!/usr/bin/env python3
"""
test_reaction_contract.py — regression test for cron #15's pipeline + artifact.

Three parts:

  A. PIPELINE BEHAVIOUR (the fixes)
     A1 the pre-market window is 04:00-09:30 ET on a WINTER date (EST)
     A2 the pre-market window is 04:00-09:30 ET on a SUMMER date (EDT)
     A3 the base close is the IMMEDIATELY prior session's close, not the
        prior-prior one - with the exact bar fixtures that broke the
        2026-11-03 US rows and the 2026-11-04 ASX rows
     A4 a 09:00-09:29 ET print is INSIDE the window (the old hour-based filter
        dropped the last 30 minutes of the pre-market)

  B. THE CHECKER ACCEPTS A CONFORMING ARTIFACT
     A synthetic artifact that follows the contract must pass.

  C. FAULT INJECTION — THE CHECKER MUST BITE
     Each mutation must make the checker FAIL. A mutation that does not change
     the text is itself a failure (a no-op mutation silently "passes" and
     reports a false NOT CAUGHT).

The pipeline code under test is loaded from the SHIPPED scanner file by
executing the side-effect-free region between its PURE-HELPERS markers, so
this test can never trigger the scanner's self-heal (which would overwrite the
file under test) and never tests a copy of the code.

Offline and dependency-free: the Cloud sandbox has no PyPI access.

Usage:  python3 tools/test_reaction_contract.py
Exit:   0 = all checks passed, 1 = a check failed.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CHECKER = os.path.join(HERE, "check_reaction_artifact.py")

FAILURES = []
PASSED = []


def ok(name):
    PASSED.append(name)
    print(f"  PASS  {name}")


def bad(name, detail):
    FAILURES.append(f"{name}: {detail}")
    print(f"  FAIL  {name}: {detail}")


# ---------------------------------------------------------------- locate code
def find_scanner():
    """The shipped scanner file. Never silently skip: if it cannot be found
    the test FAILS, because a test that inspects nothing proves nothing."""
    cands = []
    env = os.environ.get("REACTION_SCANNER")
    if env:
        cands.append(env)
    cands += [
        os.path.join(REPO, "..", "minimax-cloud-outputs", "scripts",
                     "earnings_reaction_scanner.py"),
        "/workspace/scripts/earnings_reaction_scanner.py",
        os.path.join(REPO, "..", "..", "minimax-cloud-outputs", "scripts",
                     "earnings_reaction_scanner.py"),
        os.path.join("/workspace", "repo-outputs", "scripts",
                     "earnings_reaction_scanner.py"),
    ]
    for c in cands:
        if c and os.path.exists(c):
            return os.path.abspath(c)
    return None


def exec_pure(path):
    """Exec the scanner's pure region with TRIPWIRES on every side effect.

    Returns (namespace, calls). `calls` lists the side effects that happened.

    Why the tripwires are not optional: the self-heal's FUNCTION DEFINITIONS sit
    inside the region (only its CALL is outside it). If that call ever moved
    inside, a plain exec would run the real self-heal - which fetches the
    remote script and RE-EXECS, replacing the file under test and re-running
    this test forever. With the tripwires the region cannot reach the network,
    the filesystem or the process table at all, and the attempt is RECORDED so
    the test can fail with a message instead of hanging.
    """
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    if "# ==== PURE-HELPERS-BEGIN" not in src or "# ==== PURE-HELPERS-END" not in src:
        raise RuntimeError("the scanner has no PURE-HELPERS markers - the test cannot "
                           "load it without triggering the self-heal")
    body = src.split("# ==== PURE-HELPERS-BEGIN")[1]
    body = body.split("# ==== PURE-HELPERS-END")[0]
    body = "\n".join(body.split("\n")[1:])
    calls = []

    def trip(name):
        def _boom(*a, **k):
            calls.append(name)
            raise AssertionError(f"the pure region called {name}")
        return _boom

    class TripSubprocess:
        run = staticmethod(trip("subprocess.run"))
        PIPE = subprocess.PIPE

    class TripOS:
        execv = staticmethod(trip("os.execv"))
        remove = staticmethod(trip("os.remove"))
        makedirs = staticmethod(trip("os.makedirs"))
        path = os.path
        environ = os.environ      # the REAL environ: the fetch reads GITHUB_TOKEN
                                   # from it, and a missing attribute would abort
                                   # the flow BEFORE the tripwire is reached

    ns = {"json": json, "subprocess": TripSubprocess, "time": __import__("time"),
          "datetime": datetime, "os": TripOS, "sys": sys, "re": re, "__file__": path}
    exec(compile(body, path, "exec"), ns)
    return ns, calls


def load_pure(path):
    """The scanner's side-effect-free namespace. Fails loudly if the region
    performed a side effect - it must never run the self-heal."""
    ns, calls = exec_pure(path)
    if calls:
        raise RuntimeError(
            f"the pure-helpers region performed a side effect ({sorted(set(calls))}) - "
            f"the self-heal CALL must stay BELOW the PURE-HELPERS-END marker, or this "
            f"test would re-exec and replace the file under test")
    return ns


def test_pure_region_has_no_side_effects(path):
    """A0 — exec'ing the pure region must not touch the network, the
    filesystem or the process table."""
    try:
        _, calls = exec_pure(path)
    except AssertionError as exc:
        bad("A0-pure-region", str(exc))
        return
    if calls:
        bad("A0-pure-region", f"executing the pure region called {sorted(set(calls))} — "
                             f"the region must not touch the network, the filesystem or "
                             f"the process table")
        return
    ok("A0 the pure-helpers region executes with no network, no file write and "
       "no re-exec")


# ------------------------------------------------------------------ part A
def test_pipeline(ns):
    ET = ns["ET"]

    def ts(s):
        return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=ET).timestamp()

    # A1 / A2 — the window in ET, winter and summer.
    for day, label, off, u0, u1 in (
            (datetime.date(2026, 1, 15), "winter (EST, UTC-5)", 5, 9, 14),
            (datetime.date(2026, 7, 15), "summer (EDT, UTC-4)", 4, 8, 13)):
        start, end = ns["premarket_window_utc"](day)
        s_et = start.astimezone(ET)
        e_et = end.astimezone(ET)
        if (s_et.hour, s_et.minute) != (4, 0):
            bad(f"A-window-{label}", f"the window opens at {s_et:%H:%M} ET, expected 04:00")
            continue
        if (e_et.hour, e_et.minute) != (9, 30):
            bad(f"A-window-{label}", f"the window closes at {e_et:%H:%M} ET, expected 09:30")
            continue
        # the UTC bounds must reflect the venue's offset on THAT date
        if (start.hour, start.minute) != (u0, 0) or (end.hour, end.minute) != (u1, 30):
            bad(f"A-window-{label}",
                f"the UTC bounds are {start:%H:%M}-{end:%H:%M}, expected "
                f"{u0:02d}:00-{u1:02d}:30 for UTC-{off}")
            continue
        ok(f"A1/A2 pre-market window is 04:00-09:30 ET on a {label} date")

    # A3 — the base close is the IMMEDIATELY prior session.
    # US: Yahoo's AAPL feed as it stood at 08:02 ET on 2026-11-03. The Nov 2
    # bar carries a different ET stamp than the earlier bars because the DST
    # change moved the market open by an hour — a modal time-of-day filter
    # kept the OLDER bars and rolled the base back to the prior-prior session.
    us_bars = [(ts("2026-10-22 09:30"), 348.22), (ts("2026-10-23 09:30"), 347.73),
               (ts("2026-10-26 09:30"), 343.91), (ts("2026-10-27 09:30"), 347.10),
               (ts("2026-10-28 09:30"), 343.83), (ts("2026-10-29 09:30"), 348.91),
               (ts("2026-10-30 09:30"), 344.63), (ts("2026-11-02 09:30"), 338.32)]
    now = datetime.datetime(2026, 11, 3, 8, 2, tzinfo=ET)
    s = ns["resolve_session_bars"](us_bars, False, now)
    if s["last_date"] != "2026-11-02" or s["last"] != 338.32:
        bad("A3-us-base", f"the base is {s['last_date']} / {s['last']} — expected the "
                          f"immediately prior session 2026-11-02 / 338.32")
    elif s["ref_date"] != "2026-10-30" or s["ref"] != 344.63:
        bad("A3-us-base", f"the reference close is {s['ref_date']} / {s['ref']} — "
                          f"expected 2026-10-30 / 344.63")
    elif s["prior_close"] != 338.32:
        bad("A3-us-base", f"the pre-market base is {s['prior_close']}, expected 338.32")
    else:
        ok("A3 US base close is the immediately prior session (Nov 2), not the "
           "prior-prior (Oct 30)")

    # AU: QAN.AX as it stood at 08:05 ET on 2026-11-04. The ASX stamps shift at
    # the DST boundary too (19:00 -> 18:00 ET), which is what cost the
    # 2026-11-04 run 24 of its 25 ASX rows.
    au_bars = [(ts("2026-10-22 19:00"), 8.42), (ts("2026-10-25 19:00"), 8.40),
               (ts("2026-10-26 19:00"), 8.65), (ts("2026-10-27 19:00"), 8.70),
               (ts("2026-10-28 19:00"), 8.68), (ts("2026-10-29 19:00"), 8.79),
               (ts("2026-11-01 18:00"), 8.80), (ts("2026-11-02 18:00"), 9.36),
               (ts("2026-11-03 18:00"), 8.90)]
    now2 = datetime.datetime(2026, 11, 4, 8, 5, tzinfo=ET)
    s2 = ns["resolve_session_bars"](au_bars, False, now2)
    if s2["last_date"] != "2026-11-03" or s2["last"] != 8.90:
        bad("A3-au-base", f"the base is {s2['last_date']} / {s2['last']} — expected the "
                          f"immediately prior session 2026-11-03 / 8.90")
    elif s2["ref_date"] != "2026-11-02" or s2["ref"] != 9.36:
        bad("A3-au-base", f"the reference close is {s2['ref_date']} / {s2['ref']} — "
                          f"expected 2026-11-02 / 9.36")
    else:
        ok("A3 ASX base close is the immediately prior session, not the pre-DST one")

    # A4 — a print at 09:15 ET is INSIDE the window.
    pm = [(ts("2026-11-03 03:50"), 1.0), (ts("2026-11-03 04:00"), 2.0),
          (ts("2026-11-03 09:15"), 3.0), (ts("2026-11-03 09:29"), 4.0),
          (ts("2026-11-03 09:30"), 5.0), (ts("2026-11-03 09:35"), 6.0)]
    got = [d.strftime("%H:%M") for d, _ in ns["select_premarket_bars"](pm, now)]
    if got != ["04:00", "09:15", "09:29"]:
        bad("A4-premarket-window", f"the window selected {got} — expected "
                                   f"['04:00', '09:15', '09:29']")
    else:
        ok("A4 the window keeps the 09:00-09:29 ET prints and drops 03:50 / 09:30")


# ------------------------------------------------------- synthetic artifact
CONFORMING_ARTIFACT = """# Earnings reaction scanner — 2026-11-05

- Cron: `0 8 * * 1-5` America/New_York (weekdays, 08:00 ET)
- Fire time (ET): 2026-11-05 08:03:11 Wed
- Run type: `scheduled_scan`
- artifact_contract: REACTION_ARTIFACT_V2
- ref_close_source: yahoo_chart_daily (Yahoo Finance daily chart bars)

## TL;DR

- 1 AMC reactions, 1 pre-market gaps, 0 without extended-hours data; 1 EU/UK and 1 ASX movers.

## Actionable read

- **Move vs this name's own history.** The `Move vs avg daily` column divides the
  reaction by the name's own mean absolute daily move.
- **US-listed and tradeable vs foreign-only.** 1 published reactions are on a
  US venue; 1 more foreign reactions have a US ADR line; 0 are foreign-only.
- **Not yet fully priced — US (hypothesis, not a recommendation).**
  HLMN — -4.65%, 1.55x that average. Hypothesis only.

## US — Headline table

| Ticker | Venue | Close | Chg % | Pre-mkt % | Post-mkt % | Move vs avg daily | Ref close | Ref source | Ref asof | US tradeable | Last earnings | Tag | Earn | Catalyst |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| HLMN | NASDAQ | 8.39 | 7.56 | -4.65 | — | 1.6x | 8.39 | yahoo_chart_daily | 2026-11-04 | US-listed | 2026-11-04 (1d ago) | PRE_GAP | N | Hillman Q3 adj EPS $0.22 vs $0.21 |

## US — QUIET one-liners

| Ticker | Venue | Chg % | Pre-mkt % | Post-mkt % | Move vs avg daily | Ref close | Ref source | Ref asof | US tradeable | Earn | Catalyst |
|---|---|---|---|---|---|---|---|---|---|---|---|
| MPC | NYSE | -3.22 | 2.00 | — | 0.9x | 178.00 | yahoo_chart_daily | 2026-11-04 | US-listed | — | no catalyst lookup (outside the per-run budget) |

## EU/UK — Headline table

| Ticker | Market | Venue | Close | Chg % | Currency | Move vs avg daily | Ref close | Ref source | Ref asof | US tradeable | Last earnings | Earn | Catalyst |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TMV | germany | XETR | 12.40 | -27.18 | EUR | 6.2x | 42.90 | yahoo_chart_daily | 2026-11-04 | ADR (OTC:TMVWY) | 2026-11-03 (2d ago) | Y | TeamViewer Q3 published; FY26 revenue guide cut to -1%/-2% cc |

## AU (ASX) — Headline table

| Ticker | Venue | Close | Chg % | Currency | Move vs avg daily | Ref close | Ref source | Ref asof | US tradeable | Last earnings | Earn | Catalyst |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| QAN | ASX | 9.36 | 6.36 | AUD | 2.1x | 8.80 | yahoo_chart_daily | 2026-11-04 | ADR (OTC:QABSY) | 2026-10-29 (7d ago) | N | Not earnings. Brent -7.63% on US-Iran peace progress |

## Source health

- scanner_calls: 39 | scanner_errors: 0
- pipeline_version: 2026-11-05.1
- yahoo_calls: 12 | yahoo_429: 0 | yahoo_errors: 0
- reference_close (screener vs Yahoo, resolved BEFORE the tables were built): agree=4 mismatch=0 unverified=0 stale_reference=0
- rows_dropped_stale_ref: 0 (rows whose screener-implied reference close disagreed with Yahoo's by more than 0.5%; they are dropped, not published)
- us_premarket_check: checked=1 within_1pp=1 within_3pp=1 unavailable=0
- degraded_sources: 2
  (the chat reply's `errors:` MUST equal this number - one entry per degraded
  source, not one per run)
  1. yahoo_chart_api.rate_limited — 3 fetches returned HTTP 429
  2. yahoo_chart_api.reference_close_unresolved — TMV: the reference close could not be resolved

## Audit line

`earnings-reaction target=earnings-reactions:2026-11-05 candidates=12 amc_reactions=1 pre_gaps=1 eu_reactions=1 asx_reactions=1 catalyst_lookups=4 bod=0 rows_dropped_stale_ref=0 degraded_sources=2`
"""

CONFORMING_REPLY = """### Signal

- HLMN -4.65% pre-market, 1.6x its own average daily move.

### Method & caveats

- The reference close comes from Yahoo's daily chart bars.

### Files

- earnings/2026-11-05-reactions.md

### Push / errors

- push: ok
- errors: 2
"""


# ------------------------------------------- B2. the MONDAY AU reference close
# THE 2026-11-09 REGRESSION. On a Monday scan the checker's AU floor was one
# day NEWER than the label the pipeline can emit, so a perfectly correct
# artifact was rejected: 25 of 25 ASX rows failed. An ASX daily bar is
# stamped at the session OPEN - 18:00 ET the previous day after the ASX DST
# change - so the Friday Nov 6 ASX close of 5.73 carries the label
# 2026-11-05. The floor walked the SESSION calendar but forgot the one-day
# stamp shift; on Tue-Fri scans the two cancelled out, which is why the bug
# stayed hidden through 2026-11-04..11-06.
#
# This fixture is a MONDAY (2026-11-09) scan: the US base is Thursday Nov 5,
# the EU base is Friday Nov 6, and the AU base is the Friday Nov 6 session
# LABELLED 2026-11-05 by its ET stamp.
def _monday_artifact():
    t = CONFORMING_ARTIFACT
    t = t.replace("# Earnings reaction scanner — 2026-11-05",
                  "# Earnings reaction scanner — 2026-11-09")
    t = t.replace("- Fire time (ET): 2026-11-05 08:03:11 Wed",
                  "- Fire time (ET): 2026-11-09 08:03:11 Mon")
    # US rows: the reported session is Friday Nov 6, so the base is Thu Nov 5.
    t = t.replace("| yahoo_chart_daily | 2026-11-04 | US-listed |",
                  "| yahoo_chart_daily | 2026-11-05 | US-listed |")
    # EU row: the EU session is LIVE on the scan date, so its base is Fri Nov 6.
    t = t.replace("| yahoo_chart_daily | 2026-11-04 | ADR (OTC:TMVWY) |",
                  "| yahoo_chart_daily | 2026-11-06 | ADR (OTC:TMVWY) |")
    # AU row: the Friday Nov 6 session, labelled 2026-11-05 by its ET stamp.
    t = t.replace("| yahoo_chart_daily | 2026-11-04 | ADR (OTC:QABSY) |",
                  "| yahoo_chart_daily | 2026-11-05 | ADR (OTC:QABSY) |")
    t = t.replace("earnings-reactions:2026-11-05", "earnings-reactions:2026-11-09")
    return t


MONDAY_ARTIFACT = _monday_artifact()
MONDAY_REPLY = CONFORMING_REPLY.replace("earnings/2026-11-05-reactions.md",
                                         "earnings/2026-11-09-reactions.md")


def test_monday_au_floor():
    """The AU floor must be the label the pipeline can actually emit."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("reaction_checker", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # (scan day, expected AU floor) — the floor is the base session minus the
    # one-day ET stamp shift.
    for scan_d, want in (("2026-11-09", "2026-11-05"),   # Monday
                          ("2026-11-10", "2026-11-08"),   # Tuesday
                          ("2026-11-06", "2026-11-04"),   # Friday
                          ("2026-11-05", "2026-11-03")):  # Thursday
        got = mod.min_ref_date(scan_d, "AU")
        if got != want:
            bad("B2-au-floor",
                f"min_ref_date({scan_d}, 'AU') is {got} — expected {want} (the AU "
                f"floor must be the base session minus the one-day ET stamp shift)")
            return
    ok("B2 the AU reference-close floor matches the label the pipeline emits "
       "(Monday included)")

    # And the Monday artifact must be ACCEPTED with that floor.
    rc, out = run_checker(MONDAY_ARTIFACT, MONDAY_REPLY)
    if rc != 0:
        bad("B2-monday-artifact",
            f"the checker rejected a correct MONDAY artifact (exit {rc}):\n{out}")
    else:
        ok("B2 the checker accepts a Monday-scan artifact with the ET-stamped "
           "AU base")

    # And the gate must still BITE: rolling the AU base back one session
    # (the 2026-11-04 stale-reference class) must be rejected.
    stale = MONDAY_ARTIFACT.replace(
        "| yahoo_chart_daily | 2026-11-05 | ADR (OTC:QABSY) |",
        "| yahoo_chart_daily | 2026-11-04 | ADR (OTC:QABSY) |")
    if stale == MONDAY_ARTIFACT:
        bad("B2-au-fault", "the AU fault mutation is a NO-OP — it would report a "
                           "false 'NOT CAUGHT'")
        return
    rc, out = run_checker(stale, MONDAY_REPLY)
    if rc == 0:
        bad("B2-au-fault", "the checker ACCEPTED a Monday artifact whose AU base "
                           "was rolled back one session")
    else:
        ok("B2 the checker rejects a Monday artifact whose AU base was rolled "
           "back one session")


def run_checker(artifact_text, reply_text=None, tmpdir=None):
    """Run the checker on a synthetic artifact. Returns (exit_code, stdout)."""
    tmpdir = tmpdir or tempfile.mkdtemp()
    a = os.path.join(tmpdir, "artifact.md")
    with open(a, "w", encoding="utf-8") as fh:
        fh.write(artifact_text)
    cmd = [sys.executable, CHECKER, a]
    if reply_text is not None:
        r = os.path.join(tmpdir, "reply.md")
        with open(r, "w", encoding="utf-8") as fh:
            fh.write(reply_text)
        cmd += ["--reply", r]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr)


def test_checker_accepts_conforming():
    rc, out = run_checker(CONFORMING_ARTIFACT, CONFORMING_REPLY)
    if rc != 0:
        bad("B-conforming", f"the checker rejected a conforming artifact (exit {rc}):\n{out}")
    else:
        ok("B the checker accepts a conforming artifact")


def test_checker_bites():
    """Every mutation must make the checker FAIL — and must actually change the text."""
    muts = [
        ("C-no-marker",
         lambda t: t.replace("- artifact_contract: REACTION_ARTIFACT_V2",
                             "- artifact_contract: REACTION_ARTIFACT_V1"),
         None, "the capability marker was removed"),
        ("C-catalysts-section",
         lambda t: t.replace("## Source health",
                             "## Catalysts\n\n| Ticker | Region | Catalyst | Earnings-driven |\n"
                             "|---|---|---|---|\n| HLMN | US | dup | N |\n\n## Source health"),
         None, "a separate `## Catalysts` section was added"),
        ("C-duplicate-name",
         lambda t: t.replace("| MPC | NYSE | -3.22 |",
                             "| HLMN | NYSE | -3.22 |"),
         None, "a name appears twice"),
        ("C-missing-ref-source",
         lambda t: t.replace("| yahoo_chart_daily | 2026-11-04 | US-listed |",
                             "|  | 2026-11-04 | US-listed |"),
         None, "ref_close_source was blanked"),
        ("C-missing-ref-asof",
         lambda t: t.replace("| yahoo_chart_daily | 2026-11-04 | US-listed |",
                             "| yahoo_chart_daily |  | US-listed |"),
         None, "ref_close_asof was blanked"),
        ("C-missing-us-tradeable",
         lambda t: t.replace("| yahoo_chart_daily | 2026-11-04 | US-listed |",
                             "| yahoo_chart_daily | 2026-11-04 |  |"),
         None, "us_tradeable was blanked"),
        ("C-stale-ref-asof",
         lambda t: t.replace("| yahoo_chart_daily | 2026-11-04 | US-listed |",
                             "| yahoo_chart_daily | 2026-10-28 | US-listed |"),
         None, "a reference close older than the previous session was published"),
        ("C-errors-mismatch",
         None,
         lambda r: r.replace("- errors: 2", "- errors: 1"),
         "the reply's errors count did not match degraded_sources"),
        ("C-degraded-count-mismatch",
         lambda t: t.replace("- degraded_sources: 2", "- degraded_sources: 5"),
         None, "degraded_sources did not match the listed sources"),
        ("C-missing-rows-dropped",
         lambda t: t.replace("rows_dropped_stale_ref: 0 (rows whose",
                             "rows_dropped_stale_ref: (rows whose"),
         None, "rows_dropped_stale_ref was not published"),
        ("C-missing-section",
         lambda t: t.replace("## Actionable read\n", "## Notes\n"),
         None, "the Actionable read section was removed"),
        ("C-section-order",
         lambda t: t.replace("## Source health\n", "## Source health moved\n\n"
                             "## Actionable read moved\n"),
         None, "the sections were reordered"),
    ]
    tmpdir = tempfile.mkdtemp()
    try:
        for name, mutate, reply_mutate, desc in muts:
            artifact = CONFORMING_ARTIFACT
            reply = CONFORMING_REPLY
            if mutate is not None:
                artifact = mutate(CONFORMING_ARTIFACT)
            if reply_mutate is not None:
                reply = reply_mutate(CONFORMING_REPLY)
            if artifact == CONFORMING_ARTIFACT and reply == CONFORMING_REPLY:
                bad(name, f"the mutation is a NO-OP ({desc}) - it would report a false "
                          f"'NOT CAUGHT'")
                continue
            rc, out = run_checker(artifact, reply, tmpdir=tmpdir)
            if rc == 0:
                bad(name, f"the checker ACCEPTED a broken artifact ({desc})")
            else:
                ok(f"{name} the checker rejects: {desc}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    print("A. pipeline behaviour")
    scanner = find_scanner()
    if not scanner:
        print("  FAIL  the scanner file could not be found — set REACTION_SCANNER or "
              "clone karizaco/minimax-cloud-outputs next to this repo")
        FAILURES.append("the scanner file could not be found")
    else:
        print(f"  (scanner: {scanner})")
        try:
            ns = load_pure(scanner)
        except Exception as exc:
            print(f"  FAIL  the scanner's pure region could not be loaded: {exc}")
            FAILURES.append(f"the scanner's pure region could not be loaded: {exc}")
        else:
            test_pure_region_has_no_side_effects(scanner)
            test_pipeline(ns)

    print("B. the checker accepts a conforming artifact")
    test_checker_accepts_conforming()

    print("B2. the AU reference-close floor (the 2026-11-09 Monday regression)")
    test_monday_au_floor()

    print("C. fault injection — the checker must bite")
    test_checker_bites()

    print()
    print(f"{len(PASSED)} passed, {len(FAILURES)} failed")
    if FAILURES:
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
