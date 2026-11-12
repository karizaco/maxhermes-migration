#!/usr/bin/env python3
"""
test_bonde_stop_rule.py — hermetic tests for cron #04's stop rule (contract v4).

WHY THIS FILE EXISTS
--------------------
Before 2026-11-12 the screen used a HOUSE stop rule ("body low, except on a near-doji body
under 15% of the range, where the signal bar's LOW is used", then tightened to the 2.5% cap).
Bonde's actual rule is:

  * the stop goes in the NEXT MORNING, at the low of the signal candle's BODY (his default);
  * the shadow (bar) low is his explicitly sanctioned ALTERNATIVE, legal only when it is
    within 2.5% of the purchase price.

The house rule published stops Bonde would never take (a shadow stop further than 2.5% from
the entry, tightened back to the cap) and it published 0.00% risk lines - a stop AT the entry -
on names whose body low sat on the entry (ADBE and TRI on 2026-11-10).

These tests pin the new rule to the four real bars from 2026-11-10, and they FAULT-INJECT the
three ways the artifact can lie about the stop, so the checker is observed failing rather than
merely claimed to work.

USAGE
    python3 tools/test_bonde_stop_rule.py

Exit 0 = all tests pass; 1 = at least one failure (each is printed).
"""

import csv
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import reversal_bullish as rb          # noqa: E402

CHECKER = os.path.join(HERE, "check_bonde_artifact.py")

FAILS = []
CHECKS = [0]


def ok(msg):
    CHECKS[0] += 1
    print(f"  ok   {msg}")


def bad(msg):
    CHECKS[0] += 1
    FAILS.append(msg)
    print(f"  FAIL {msg}")


def bar(open_, high, low, close):
    return {"open": open_, "high": high, "low": low, "close": close, "volume": 1_000_000}


# ---------------------------------------------------------------- the real bars
# 2026-11-10, the settled 16:00 close.
CASES = [
    # ticker, O, H, L, C, entry, expected stop, expected class, expected basis token,
    # expected body_stop_pct, expected shadow_stop_pct, expected degenerate
    ("DOCU", 77.50, 77.80, 75.56, 77.66, 77.66, 77.50, "BODY_LOW", "body low",
     0.206, 2.704, False),
    ("SYK", 324.07, 324.76, 317.87, 324.29, 324.29, 317.87, "STRUCTURAL", "shadow low",
     0.068, 1.979, True),
    ("ADBE", 237.82, 237.82, 231.82, 236.70, 236.70, 231.82, "STRUCTURAL", "shadow low",
     0.000, 2.062, True),
    ("TRI", 108.98, 109.47, 106.47, 108.41, 108.41, 106.47, "STRUCTURAL", "shadow low",
     0.000, 1.793, True),
]


def test_real_bars():
    print("[stop_profile] the four real 2026-11-10 bars")
    for (t, o, h, l, c, entry, exp_stop, exp_class, exp_basis,
         exp_body_pct, exp_shadow_pct, exp_degen) in CASES:
        p = rb.stop_profile(rb.candle_metrics(bar(o, h, l, c)), entry)
        if abs(p["stop"] - exp_stop) > 0.011:
            bad(f"{t}: stop {p['stop']} != expected {exp_stop} "
                f"(basis: {p['stop_basis']})")
        else:
            ok(f"{t}: stop {p['stop']:.2f} ({p['stop_basis']})")
        if p["stop_class"] != exp_class:
            bad(f"{t}: stop_class {p['stop_class']} != expected {exp_class}")
        else:
            ok(f"{t}: stop_class {exp_class}")
        if exp_basis not in p["stop_basis"].lower():
            bad(f"{t}: basis {p['stop_basis']!r} does not name {exp_basis!r}")
        else:
            ok(f"{t}: basis names {exp_basis!r}")
        if abs(p["body_stop_pct"] - exp_body_pct) > 0.01:
            bad(f"{t}: body_stop_pct {p['body_stop_pct']} != expected {exp_body_pct}")
        else:
            ok(f"{t}: body_stop_pct {p['body_stop_pct']}")
        if abs(p["shadow_stop_pct"] - exp_shadow_pct) > 0.01:
            bad(f"{t}: shadow_stop_pct {p['shadow_stop_pct']} != expected {exp_shadow_pct}")
        else:
            ok(f"{t}: shadow_stop_pct {p['shadow_stop_pct']}")
        if (p["body_stop_degenerate"] == "yes") != exp_degen:
            bad(f"{t}: body_stop_degenerate {p['body_stop_degenerate']} != expected {exp_degen}")
        else:
            ok(f"{t}: body_stop_degenerate={p['body_stop_degenerate']}")
        if p["stop"] >= entry - 0.011 and p["stop_class"] != "NO_LEGAL_STOP":
            bad(f"{t}: the published stop is at the entry ({p['stop']}) with class "
                f"{p['stop_class']} — a 0.00% risk line must never be published as a stop")
        else:
            ok(f"{t}: no 0.00% risk line published")


def test_no_legal_stop():
    print("[stop_profile] the case where NO stop is legal")
    # body low sits on the entry, shadow low 3.0% away -> over Bonde's 2.5% cap
    p = rb.stop_profile(rb.candle_metrics(bar(100.0, 100.0, 97.0, 100.0)), 100.0)
    if p["stop_class"] != "NO_LEGAL_STOP":
        bad(f"expected NO_LEGAL_STOP, got {p['stop_class']}")
    else:
        ok("a degenerate body low with an illegal shadow stop is NO_LEGAL_STOP")
    if "no legal stop" not in p["stop_basis"].lower():
        bad(f"NO_LEGAL_STOP must say so in its basis, got {p['stop_basis']!r}")
    else:
        ok("NO_LEGAL_STOP names the missing legal stop in its basis")
    if p["stop_class"] != "NO_LEGAL_STOP":
        bad("the class must stay NO_LEGAL_STOP so no reader treats the row as a trade")
    else:
        ok("the row stays NO_LEGAL_STOP (the published level is the body low, for reference)")


def test_capped():
    print("[stop_profile] the 2.5% cap on a non-degenerate body low")
    p = rb.stop_profile(rb.candle_metrics(bar(90.0, 96.0, 89.0, 95.0)), 95.0)
    if p["stop_class"] != "CAPPED":
        bad(f"expected CAPPED, got {p['stop_class']}")
    else:
        ok("a body low beyond the cap is CAPPED")
    if abs(p["stop"] - 92.63) > 0.011:
        bad(f"capped stop {p['stop']} != 92.63")
    else:
        ok(f"the cap binds the stop at {p['stop']}")


# ---------------------------------------------------------------- the checker
MD_HEAD = """# Bonde Reversal Bullish — Tuesday, 10 November 2026

## TL;DR

- **Mechanical passers: 1** of 951 names scanned · mode **LIVE** · signal session **2026-11-10** · entry = the settled 16:00 ET close.
- **Ideas promoted: 1** — **AAA** is the only idea promoted.
- **Body-low stop:** the published stop sits inside the signal bar's own range for AAA — it is tighter than the structural level.

## Candidates

| Ticker | Company | Entry | Stop | Stop % | Stop class | Stop basis | Body low | Bar low | Bar high | Stop vs bar low | DCR | Body | Lower shdw | Tail | ADR | Drop days | 1-day chg | Vol vs 30d avg | Capitulation | Mkt cap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **AAA** | Alpha Corp. | **100.00** | {stop} | {stop_pct}% | `{stop_class}` | {basis} | {body_low} | {bar_low} | {bar_high} | {svbl} | 0.800 | 0.200 | 4.00 | 4.00x | 3.50% | 3 | -1.00% | 70% | LOW_VOLUME | $50.00B |

## Promoted ideas

### ✅ IDEA 1 — AAA (Alpha Corp.) · entry 100.00 · stop {stop} (-1.00%) · stop_class {stop_class} · vol 70% of 30d avg (LOW_VOLUME) · Day 1
**Catalyst:** a named, dated catalyst.
**Invalidated if** AAA closes below {bar_low} / the catalyst does not happen by the date.

## Not promoted

- **BBB** (Beta Corp.) — passed all gates but not promoted. **Invalidated if** BBB closes below 10.00.

## Bonde gate matrix

| Ticker | 1. 5-day low | 2. DCR ≥ .60 | 3. shadow > body | 3b. hammer | 3c. body ≤ .30 | 5. decline + washout | 6. ADR ≥ 3% | 7. price ≥ $5 | 8. trend | vol | minv3 | avolv30 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AAA | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

## Filter funnel

| Step | Filter | Left |
|---|---|---|
| 1 | universe | 951 |
| 2 | DCR | 133 |
| 3 | + shape | 133 |
| 4 | + history | 4 |

## Method, source health & caveats

- **Session alignment — proof this scan is for today:** 12/12 agree (100.0%) → mode **LIVE**.
- **The stop rule is Bonde's, not the house's.**

| Source | Used for | Status |
|---|---|---|
| TradingView public scanner | live session OHLC | ok |

_Generated by cron #4 `reversal-bullish-3:55` · contract `bonde-artifact-v4`_
"""

CSV_COLS = ["ticker", "company", "exchange", "sector", "signal_session", "entry_price",
            "stop", "stop_basis", "stop_pct", "stop_class", "stop_capped", "stop_placement",
            "body_low", "body_stop_pct", "shadow_stop_pct", "body_stop_degenerate",
            "bar_low", "bar_high", "stop_vs_bar_low_pct", "bar_low_vs_entry_pct",
            "invalidation_level", "capitulation", "vol_vs_30d_avg_pct"]


def write_artifact(tmp, stop, stop_pct, stop_class, basis, body_low, bar_low, bar_high,
                   svbl, body_stop_pct, shadow_stop_pct, degenerate):
    md = os.path.join(tmp, "reversal-bullish-3_55.md")
    csv_path = os.path.join(tmp, "reversal-bullish-3_55.csv")
    with open(md, "w") as fh:
        fh.write(MD_HEAD.format(stop=stop, stop_pct=stop_pct, stop_class=stop_class,
                                basis=basis, body_low=body_low, bar_low=bar_low,
                                bar_high=bar_high, svbl=svbl))
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_COLS)
        w.writerow(["AAA", "Alpha Corp.", "NYSE", "Tech", "2026-11-10", 100.00, stop, basis,
                    stop_pct, stop_class, "no", "next morning, after the open", body_low,
                    body_stop_pct, shadow_stop_pct, degenerate, bar_low, bar_high, svbl,
                    -1.0, bar_low, "LOW_VOLUME", 70])
    return md, csv_path


def run_checker(md, csv_path):
    p = subprocess.run([sys.executable, CHECKER, "--md", md, "--csv", csv_path],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def test_checker_fault_injection():
    print("[checker] fault injection — the checker must FAIL a lying artifact")
    with tempfile.TemporaryDirectory() as tmp:
        # 1. a stop published AT the entry (the 0.00% risk line the old rule produced)
        md, csv_path = write_artifact(tmp, 100.00, 0.00, "BODY_LOW", "body low",
                                      100.00, 96.00, 101.00, "+4.17%", 0.00, 4.00, "yes")
        rc, out = run_checker(md, csv_path)
        if rc == 0:
            bad("the checker ACCEPTED an artifact whose stop equals the entry (0.00% risk)")
        else:
            ok("the checker rejects a 0.00% risk line")
            if "not below the entry" not in out:
                bad("the rejection did not name the 0.00% risk line")
            else:
                ok("the rejection names the 0.00% risk line")

    with tempfile.TemporaryDirectory() as tmp:
        # 2. the shadow low substituted for a USABLE body low (Bonde's default stands)
        md, csv_path = write_artifact(tmp, 96.00, 4.00, "BODY_LOW", "shadow low",
                                      99.00, 96.00, 101.00, "+0.00%", 1.00, 4.00, "no")
        rc, out = run_checker(md, csv_path)
        if rc == 0:
            bad("the checker ACCEPTED an artifact that substituted the shadow low for a usable "
                "body low")
        else:
            ok("the checker rejects a shadow stop substituted for a usable body low")
            if "Bonde's default is the body low" not in out:
                bad("the rejection did not name the body-low default")
            else:
                ok("the rejection names the body-low default")

    with tempfile.TemporaryDirectory() as tmp:
        # 3. a shadow stop beyond the 2.5% cap (Bonde forbids it)
        md, csv_path = write_artifact(tmp, 96.00, 4.00, "STRUCTURAL", "shadow low",
                                      96.00, 96.00, 101.00, "+0.00%", 4.00, 4.00, "yes")
        rc, out = run_checker(md, csv_path)
        if rc == 0:
            bad("the checker ACCEPTED a shadow stop more than 2.5% from the entry")
        else:
            ok("the checker rejects an illegal (over-cap) shadow stop")

    with tempfile.TemporaryDirectory() as tmp:
        # 4. a COMPLIANT artifact must pass
        md, csv_path = write_artifact(tmp, 99.00, 1.00, "BODY_LOW", "body low",
                                      99.00, 96.00, 101.00, "+3.13%", 1.00, 4.00, "no")
        rc, out = run_checker(md, csv_path)
        if rc != 0:
            bad("the checker REJECTED a compliant artifact:\n" + out[-1500:])
        else:
            ok("the checker accepts a compliant v4 artifact")


def main():
    print(f"test_bonde_stop_rule.py — contract {rb.CONTRACT_VERSION}\n")
    test_real_bars()
    print()
    test_no_legal_stop()
    print()
    test_capped()
    print()
    test_checker_fault_injection()
    print()
    if FAILS:
        print(f"FAILED — {len(FAILS)} of {CHECKS[0]} checks failed:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print(f"OK — {CHECKS[0]} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
