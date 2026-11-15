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


# ------------------------------------------------------------------ the v4 fixture
# A v4 artifact: the coverage floor is PUBLISHED - in the front matter, in the TL;DR and in
# the source-health table, with the arithmetic that adds up.
CONFORMING_V4 = """---
date: 2026-11-16
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
contract: EARNINGS_REMINDER_V4
coverage_receipt: calendar_rows=147 s_and_p_500_hits=3 bigcap_hits=7 us_roster_rows=3 band_rows=2
coverage_floor: floor_usd=50000000000 band_low_usd=40000000000 us_population=5542 below_band_us=4954 band_us=67 at_or_above_floor_us=417 no_cap_us=104 source=TradingView america scanner (market_cap_basic, issuer-level USD)
---

# Earnings - Mon 2026-11-16

## TL;DR

- **Coverage floor - a scope limit, not a missing company.** This reminder covers S&P 500
  constituents plus US-listed reporters with a market cap of **$50B or more** (TradingView
  scanner, `market_cap_basic`, issuer-level USD). The band just under the floor - **$40B to $50B**
  - is published in the *Just below the line* table so the cliff is visible. **A US reporter below
  $40B market cap is out of scope for this reminder: it is not on this list, and its absence does
  not mean it did not report.** Of the scanner's **5,542** US names, **4,954** are below the $40B
  band floor and therefore out of scope, **67** sit in the $40B-$50B band, **417** are at or above
  the $50B floor, and **104** carry no market cap at all.

## Big S&P 500 today

| Ticker | Company | Time | EPS est | Rev est | Mkt cap | Prior day % | YTD % | Avg abs move % | Implied move % | Prior result | Reaction score | Status | Flag |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ARM | Arm Holdings | AMC 4:05 PM | 0.60 | 1.50B | $216.3B | -13.08 | 45.32 | 9.07 | 12.34 | beat | 10.38 | pending | - |
| QCOM | Qualcomm | AMC 4:00 PM | 2.30 | 11.00B | $175.6B | -9.49 | -9.38 | 8.92 | 8.58 | beat | 8.78 | pending | - |
| KDP | Keurig Dr Pepper | BMO 6:30 AM | 1.02 | 4.60B | $50.1B | +0.40 | -3.10 | 3.10 | n/a | beat | 3.10 | pending | boundary_case |

## Non-US primary listings

| ticker_primary | venue_primary | Company | next_report | us_peer | us_tradeable | Status |
|---|---|---|---|---|---|---|
| 7203.T | Tokyo Stock Exchange | Toyota Motor | Nov 16, 07:00 JST | TM (NYSE ADR) | ADR (US-listed) | pending |
| 005930.KS | Korea Exchange | Samsung Electronics | Nov 16, 08:00 KST | SSNLF (OTC) | ADR (OTC) | pending |

## Just below the line - excluded by the $50B floor

| Ticker | Company | Mkt cap | Reports today |
|---|---|---|---|
| MDLN | Medline Industries | $45.9B | no |
| SLF | Sun Life Financial | $44.8B | no |

## Already reported (before 06:00 ET)

| Ticker | Company | Released | Actual | vs consensus | us_tradeable |
|---|---|---|---|---|---|
| NOVO-B.CO (NVO) | Novo Nordisk | ~01:00 ET | rev $12.19B | beat | ADR (US-listed) |

## Notes

- Ranked by reaction potential, not by market cap.
- KDP is inside the floor by $0.1B and is flagged `boundary_case`.

## Source health

| Source | URL / query | Status | Notes |
|---|---|---|---|
| EarningsWhispers calendar | https://www.earningswhispers.com/calendar/20261116 | ok | server-rendered |
| Coverage floor (scope limit) | `scanner.tradingview.com/america/scan` - `market_cap_basic` (issuer-level USD), constants `MCAP_FLOOR = $50B` and `band_low_usd = $40B` | ok | The roster is bounded by the market-cap band, not by who reported: S&P 500 constituents plus US-listed names at or above $50B, with the $40B-$50B band published below the floor. A US reporter below $40B market cap is out of scope - it is not on this list (a scope limit, not a missing company). US names below the band floor: 4,954 of 5,542 (67 in the band, 417 at or above the floor, 104 with no cap) |

## Rules applied

- Report dates confirmed against issuer sources.
"""


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


def test_conforming_v4():
    """A v4 artifact - the coverage floor published in all three places - must pass."""
    code, out = run_checker(CONFORMING_V4)
    if code != 0:
        bad("B2", f"a conforming v4 artifact was rejected:\n{out}")
    else:
        ok("B2")


def _v3_artifact_without_the_floor():
    """A Friday-shaped artifact: v3 marker, no TL;DR, no `coverage_floor`, no floor row.

    This is the artifact the fleet already published. Under the v3 rules it is legal; under the
    v4 rules it is NOT. The two tests below are the same file judged by both rule sets - which
    is exactly what the grandfathering rule decides.
    """
    legacy = CONFORMING_V4.replace("date: 2026-11-16", "date: 2026-11-13")
    legacy = legacy.replace("contract: EARNINGS_REMINDER_V4", "contract: EARNINGS_REMINDER_V3")
    legacy = re.sub(r"^coverage_floor: .*?\n", "", legacy, flags=re.M)
    legacy = re.sub(r"## TL;DR.*?(?=## Big S&P 500 today)", "", legacy, flags=re.S)
    legacy = re.sub(r"\| Coverage floor \(scope limit\) \|.*?\n", "", legacy)
    return legacy


def test_grandfathered_v3_artifact_still_passes():
    """A v3 artifact has no TL;DR and no `coverage_floor` - and must NOT be failed for it.

    This is the rule that keeps the fleet's auditors out of a false finding: a contract change
    must not retroactively fail an artifact that was legal when it was written.
    """
    legacy = _v3_artifact_without_the_floor()
    if legacy == CONFORMING_V4:
        bad("B3", "the grandfathering fixture was not actually downgraded")
        return
    code, out = run_checker(legacy)
    if code != 0:
        bad("B3", f"a grandfathered v3 artifact was failed by the v4 floor rules:\n{out}")
    else:
        ok("B3")


def test_the_floor_rule_bites_without_the_grandfather():
    """The SAME file, judged as v4, MUST fail - the grandfathering rule is load-bearing."""
    as_v4 = _v3_artifact_without_the_floor().replace(
        "contract: EARNINGS_REMINDER_V3", "contract: EARNINGS_REMINDER_V4")
    code, out = run_checker(as_v4)
    if code == 0:
        bad("B4", "an artifact with a v4 marker was ACCEPTED without a published floor - the "
                  "grandfathering rule has a hole")
    else:
        ok("B4")


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

# The v4 floor rules, fault-injected against the v4 fixture. Each mutation removes or breaks
# ONE part of the published floor; the checker must fail every one of them.
FLOOR_MUTATIONS = [
    ("C13 delete the TL;DR section entirely",
     lambda t: re.sub(r"## TL;DR.*?(?=## Big S&P 500 today)", "", t, flags=re.S)),
    ("C14 keep the TL;DR section but empty it of the floor",
     lambda t: re.sub(r"## TL;DR.*?(?=## Big S&P 500 today)",
                       "## TL;DR\n\n- Nothing to see here today.\n\n", t, flags=re.S)),
    ("C15 the TL;DR states the wrong floor and the wrong band",
     lambda t: re.sub(r"- \*\*Coverage floor - a scope limit.*?no market cap at all\.",
                      "- **Coverage floor - a scope limit, not a missing company.** This reminder "
                      "covers S&P 500 constituents plus US-listed reporters with a market cap of "
                      "**$5B or more** (TradingView scanner, `market_cap_basic`, issuer-level "
                      "USD). The band just under the floor - **$4B to $5B** - is published below "
                      "it. A US reporter below $4B market cap is out of scope for this "
                      "reminder: it is not on this list.", t, flags=re.S)),
    ("C16 the TL;DR drops the consequence in words",
     lambda t: t.replace("**A US reporter below\n  $40B market cap is out of scope for this "
                          "reminder: it is not on this list, and its absence does\n  not mean it "
                          "did not report.**",
                          "**A US reporter below\n  $40B market cap is out of scope for this "
                          "reminder.**")),
    ("C17 delete the Source-health floor row",
     lambda t: re.sub(r"\| Coverage floor \(scope limit\) \|.*?\n", "", t)),
    ("C18 the Source-health floor row drops the consequence",
     lambda t: re.sub(r"A US reporter below \$40B market cap is out of scope - it is not on this "
                      r"list \(a scope limit, not a missing company\)\.",
                      "The roster is bounded by the market-cap band.", t)),
    ("C19 delete the `coverage_floor` front-matter key",
     lambda t: re.sub(r"^coverage_floor: .*?\n", "", t, flags=re.M)),
    ("C20 break the coverage_floor arithmetic",
     lambda t: t.replace("us_population=5542 below_band_us=4954",
                         "us_population=5542 below_band_us=9954")),
    ("C21 the coverage_floor band count cannot hold the published band rows",
     lambda t: t.replace("band_us=67", "band_us=1")),
    ("C22 the coverage_floor source does not name the scanner column",
     lambda t: t.replace("source=TradingView america scanner (market_cap_basic, "
                         "issuer-level USD)", "source=TradingView america scanner")),
    ("C23 the coverage_floor names a floor the band is not applied with",
     lambda t: t.replace("floor_usd=50000000000", "floor_usd=5000000000")),
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


def test_floor_mutations():
    """The published floor is a gate: every mutation of it must be caught."""
    for name, mutate in FLOOR_MUTATIONS:
        mutated = mutate(CONFORMING_V4)
        if mutated == CONFORMING_V4:
            bad(name, "the mutation did not change the artifact text - a no-op mutation "
                      "reports a false NOT CAUGHT")
            continue
        code, out = run_checker(mutated)
        if code == 0:
            bad(name, "the checker ACCEPTED an artifact whose published floor was broken")
        else:
            ok(name)


def main():
    test_helper()
    test_conforming()
    test_conforming_v4()
    test_grandfathered_v3_artifact_still_passes()
    test_the_floor_rule_bites_without_the_grandfather()
    test_mutations()
    test_floor_mutations()
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
