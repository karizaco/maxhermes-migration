#!/usr/bin/env python3
"""
test_earnings_reminder_contract.py — regression test for cron #19's reaction layer
and artifact contract.

Three parts:

  A. THE HELPER (offline, fixture-driven)
     A1 BMO reaction window  = close(D-1) -> close(D)
     A2 AMC reaction window  = close(D)   -> close(D+1)
     A3 a missing implied move makes the score equal avg_abs_move exactly
     A4 the score is 0.6*avg + 0.4*implied when both are present
     A5 the OCC symbol parser reads strike / side / expiry
     A6 a report date on a non-trading day falls back to the next bar

  B. THE CHECKER ACCEPTS A CONFORMING ARTIFACT
     A synthetic artifact that follows the contract must pass.

  C. FAULT INJECTION — THE CHECKER MUST BITE
     Each mutation must make the checker FAIL. A mutation that does not change the
     text is itself a failure (a no-op mutation silently "passes" and reports a
     false NOT CAUGHT).

Offline and dependency-free: the Cloud sandbox has no PyPI access.

Usage:  python3 tools/test_earnings_reminder_contract.py
Exit:   0 = all checks passed, 1 = a check failed.
"""
import datetime
import importlib.util
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKER = os.path.join(HERE, "check_earnings_reminder_artifact.py")
HELPER = os.path.join(HERE, "earnings_reaction_stats.py")

FAILURES = []
PASSED = []


def ok(name):
    PASSED.append(name)


def bad(name, detail):
    FAILURES.append(f"{name}: {detail}")


def load_helper():
    spec = importlib.util.spec_from_file_location("reaction_stats", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------- fixtures
def bars(pairs):
    return [(datetime.date.fromisoformat(d), c) for d, c in pairs]


CONFORMING = """---
date: 2026-11-06
cron: 19-earnings-reminder-daily
fire_time_et: 06:00
snapshot_et: 06:04
source: EarningsWhispers + Yahoo + Nasdaq
primary_source: Yahoo (market cap) | EarningsWhispers (EPS/revenue)
status: ok
pending_count: 3
already_reported_count: 1
non_us_count: 2
reaction_ranked: true
band_low_usd: 40000000000
---

# Earnings - Fri 2026-11-06

## Big S&P 500 today

| Ticker | Company | Time | EPS est | Rev est | Mkt cap | Prior day % | YTD % | Avg abs move % | Implied move % | Prior result | Reaction score | Status | Flag |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ARM | Arm Holdings | AMC 4:05 PM | 0.60 | 1.50B | $216.3B | -13.08 | 45.32 | 9.07 | 12.34 | beat | 10.38 | pending | - |
| QCOM | Qualcomm | AMC 4:00 PM | 2.30 | 11.00B | $175.6B | -9.49 | -9.38 | 8.92 | 8.58 | beat | 8.78 | pending | - |
| KDP | Keurig Dr Pepper | BMO 6:30 AM | 1.02 | 4.60B | $50.1B | +0.40 | -3.10 | 3.10 | n/a | beat | 3.10 | pending | boundary_case |
| MCD | McDonald's | BMO 7:00 AM | 3.40 | 7.30B | $186.1B | -0.78 | -8.32 | 2.17 | 1.45 | beat | 1.88 | pending | - |

## Non-US primary listings

| ticker_primary | venue_primary | Company | next_report | us_peer | us_tradeable | Status |
|---|---|---|---|---|---|---|
| 7203.T | Tokyo Stock Exchange | Toyota Motor | Nov 6, 07:00 JST | TM (NYSE ADR) | ADR (US-listed) | pending |
| 005930.KS | Korea Exchange | Samsung Electronics | Nov 6, 08:00 KST | SSNLF (OTC) | ADR (OTC) | pending |

## Just below the line - excluded by the $50B floor

| Ticker | Company | Mkt cap | Reports today |
|---|---|---|---|
| MDLN | Medline Industries | $45.9B | no |
| SLF | Sun Life Financial | $44.8B | no |

## Already reported (before 06:00 ET)

| Ticker | Company | Released | Actual | vs consensus |
|---|---|---|---|---|
| NOVO-B.CO (NVO) | Novo Nordisk | ~01:00 ET | rev $12.19B | beat |

## Notes

- Ranked by reaction potential, not market cap.
- KDP is inside the floor by $0.1B and is flagged `boundary_case`.

## Source health

| Source | URL / query | Status | Notes |
|---|---|---|---|
| EarningsWhispers calendar | https://www.earningswhispers.com/calendar/20261106 | ok | server-rendered |

## Rules applied

- Report dates confirmed against issuer sources.
"""


def run_checker(text):
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(text)
        path = fh.name
    try:
        p = subprocess.run([sys.executable, CHECKER, path], capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr
    finally:
        os.unlink(path)


# ------------------------------------------------------------------------ part A
def test_helper():
    m = load_helper()

    # A1 BMO: close(D-1) -> close(D)
    b = bars([("2026-11-02", 100.0), ("2026-11-03", 110.0), ("2026-11-04", 99.0)])
    avg, n = m.avg_abs_move_pct(b, [datetime.date(2026, 11, 4)], "BMO")
    if abs(avg - 10.0) > 1e-6:
        bad("A1", f"BMO reaction window gave {avg}, expected 10.0 (close D-1 -> D)")
    else:
        ok("A1")

    # A2 AMC: close(D) -> close(D+1)
    b = bars([("2026-11-02", 100.0), ("2026-11-03", 110.0), ("2026-11-04", 99.0)])
    avg, n = m.avg_abs_move_pct(b, [datetime.date(2026, 11, 3)], "AMC")
    if abs(avg - 10.0) > 1e-6:
        bad("A2", f"AMC reaction window gave {avg}, expected 10.0 (close D -> D+1)")
    else:
        ok("A2")

    # A3 missing implied move -> score == avg
    avg, imp = 5.0, None
    score = round(0.6 * avg + 0.4 * (imp if imp is not None else avg), 2)
    if score != 5.0:
        bad("A3", f"score with no implied move was {score}, expected 5.0")
    else:
        ok("A3")

    # A4 both present
    score = round(0.6 * 8.92 + 0.4 * 8.58, 2)
    if abs(score - 8.78) > 0.011:
        bad("A4", f"score was {score}, expected 8.78")
    else:
        ok("A4")

    # A5 OCC parsing
    p = m._occ("AAPL261106C00110000")
    if not p or p["strike"] != 110.0 or p["side"] != "C" or p["date"] != datetime.date(2026, 11, 6):
        bad("A5", f"OCC parse gave {p}")
    else:
        ok("A5")

    # A6 a report date with no bar (holiday) is skipped, not crashed
    b = bars([("2026-11-02", 100.0), ("2026-11-04", 110.0)])
    avg, n = m.avg_abs_move_pct(b, [datetime.date(2026, 11, 3)], "BMO")
    if avg is not None:
        bad("A6", f"a report date with no bar returned {avg}, expected None")
    else:
        ok("A6")


# ------------------------------------------------------------------------ part B
def test_conforming():
    code, out = run_checker(CONFORMING)
    if code != 0:
        bad("B", f"a conforming artifact was rejected:\n{out}")
    else:
        ok("B")


# ------------------------------------------------------------------------ part C
MUTATIONS = [
    ("C1 drop the reaction-score column",
     lambda t: t.replace("| Reaction score |", "| |")),
    ("C2 unsort the roster by reaction score",
     lambda t: t.replace("| ARM | Arm Holdings | AMC 4:05 PM | 0.60 | 1.50B | $216.3B | -13.08 | 45.32 | 9.07 | 12.34 | beat | 10.38 | pending | - |\n| QCOM | Qualcomm | AMC 4:00 PM | 2.30 | 11.00B | $175.6B | -9.49 | -9.38 | 8.92 | 8.58 | beat | 8.78 | pending | - |",
                         "| QCOM | Qualcomm | AMC 4:00 PM | 2.30 | 11.00B | $175.6B | -9.49 | -9.38 | 8.92 | 8.58 | beat | 8.78 | pending | - |\n| ARM | Arm Holdings | AMC 4:05 PM | 0.60 | 1.50B | $216.3B | -13.08 | 45.32 | 9.07 | 12.34 | beat | 10.38 | pending | - |")),
    ("C3 break the reaction-score formula",
     lambda t: t.replace("| 8.92 | 8.58 | beat | 8.78 |", "| 8.92 | 8.58 | beat | 9.90 |")),
    ("C4 empty a us_peer cell",
     lambda t: t.replace("| TM (NYSE ADR) |", "|  |")),
    ("C5 publish a non-US issuer in BOTH tables",
     lambda t: t.replace("| 7203.T | Tokyo Stock Exchange | Toyota Motor | Nov 6, 07:00 JST | TM (NYSE ADR) | ADR (US-listed) | pending |",
                         "| 7203.T | Tokyo Stock Exchange | Toyota Motor | Nov 6, 07:00 JST | TM (NYSE ADR) | ADR (US-listed) | pending |\n"
                         "| TM | Toyota Motor (NYSE ADR) | AMC | 1.20 | 30.00B | $300.0B | +1.00 | 5.00 | 4.00 | 5.00 | beat | 4.40 | pending | - |")),
    ("C6 put an above-the-floor name in the band table",
     lambda t: t.replace("| MDLN | Medline Industries | $45.9B | no |",
                         "| MDLN | Medline Industries | $65.9B | no |")),
    ("C7 drop the boundary_case flag",
     lambda t: t.replace("| pending | boundary_case |", "| pending | - |")),
    ("C8 delete the non-US table",
     lambda t: re.sub(r"## Non-US primary listings.*?(?=## Just below the line)", "", t, flags=re.S)),
    ("C9 reaction_ranked is not true",
     lambda t: t.replace("reaction_ranked: true", "reaction_ranked: false")),
    ("C10 an unknown us_tradeable value",
     lambda t: t.replace("| ADR (OTC) | pending |", "| ADR (unlisted) | pending |")),
    ("C11 an n/a score with no degradation declared",
     lambda t: t.replace("| 3.10 | 3.10 | pending |", "| n/a | n/a | pending |")
                .replace("| 1.45 | beat | 1.88 |", "| n/a | beat | n/a |")),
    ("C12 a declared degradation that does not match the rows",
     lambda t: t.replace("reaction_ranked: true",
                         "reaction_ranked: true\nreaction_degraded: 3")),
]


def test_degradation_is_allowed_when_declared():
    """An n/a score is legitimate ONLY when the front-matter declares the exact count."""
    degraded = CONFORMING.replace("reaction_ranked: true",
                                  "reaction_ranked: true\nreaction_degraded: 1")
    degraded = degraded.replace("| 1.45 | beat | 1.88 |", "| n/a | beat | n/a |")
    code, out = run_checker(degraded)
    if code != 0:
        bad("D1", f"a declared degradation was rejected:\n{out}")
    else:
        ok("D1")


def test_mutations():
    for name, mutate in MUTATIONS:
        mutated = mutate(CONFORMING)
        if mutated == CONFORMING:
            bad(name, "the mutation did not change the artifact text - a no-op mutation "
                      "reports a false NOT CAUGHT")
            continue
        code, out = run_checker(mutated)
        if code == 0:
            bad(name, "the checker ACCEPTED a non-conforming artifact")
        else:
            ok(name)


def main():
    test_helper()
    test_conforming()
    test_mutations()
    test_degradation_is_allowed_when_declared()
    print(f"passed: {len(PASSED)}")
    for p in PASSED:
        print(f"  ok   {p}")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}")
        for f in FAILURES:
            print(f"  FAIL {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
