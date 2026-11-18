#!/usr/bin/env python3
"""test_premarket_intraday_extreme.py — the intraday-extreme line must BITE.

MARKER: premarket-intraday-extreme-v1

The 2026-11-18 fire published a `BORDERLINE_INTRADAY` flag line that read
"crossed the bar intraday and gave it back (pre-market high +0.26% / low
+0.26% -> +0.52% at the snapshot)" for a name whose verdict was that it
CROSSED the bar. `pm_high_gap_pct` / `pm_low_gap_pct` are the CURRENT
pre-market range, not the extreme that crossed the bar, so the line
contradicted the verdict it was flagging and the extreme itself was published
nowhere in the markdown (MOH's overnight extreme was -6.98%, a DOWNWARD
cross, and the reader could not tell).

The renderer now publishes the SIGNED extreme. This test renders FIXTURES and
asserts:

  T1  the Flags line carries the SIGNED extreme (a downward cross reads with
      its minus sign, not as an absolute value)
  T2  the Flags line no longer quotes the current pre-market range as the
      crossing fact
  T3  the CSV `flag_reason` carries the same signed extreme
  T4  a pull JSON that PREDATES `max_tape_gap_signed_pct` still renders the
      signed extreme, from the tape's own print list (the fallback path)
  T5  a record with NEITHER falls back to the old wording instead of crashing

A test that cannot fail is a claim. Run it:

    python3 tools/test_premarket_intraday_extreme.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RENDERER_CANDIDATES = (
    os.path.join(HERE, "render_premarket_artifact.py"),
    os.path.join(HERE, os.pardir, "cloud-prompts", "skills", "stock-screener-suite",
                 "scripts", "render_premarket_artifact.py"),
)
RENDERER = next((c for c in RENDERER_CANDIDATES if os.path.exists(c)), RENDERER_CANDIDATES[0])

FAILS = []


def bad(msg):
    FAILS.append(msg)
    print("  FAIL  %s" % msg)


def ok(msg):
    print("  ok    %s" % msg)


def record(ticker, gap, high_gap, low_gap, extra=None):
    rec = {
        "ticker": ticker,
        "base_close": 100.0,
        "base_close_source": "focus.csv+tradingview+cboe",
        "base_close_conflict": "",
        "pm_price": 100.0 * (1 + gap / 100.0),
        "pm_gap_pct": gap,
        "quote_price": 100.0 * (1 + gap / 100.0),
        "quote_gap_pct": gap,
        "exec_shares": 500,
        "exec_notional": 50000.0,
        "pm_volume": 120000,
        "pm_volume_source": "Nasdaq extended-trading cumulative counter",
        "pm_high": "$100.50",
        "pm_low": "$99.50",
        "pm_high_px": 100.5,
        "pm_low_px": 99.5,
        "pm_high_gap_pct": high_gap,
        "pm_low_gap_pct": low_gap,
        "tape_lag_min": 5.0,
        "tape_newest_print": "08:20:33",
        "tape_pulls": 2,
        "tape_vintage_count": 1,
        "stylists": "jeff_sun|stockbee",
        "origins": "A_stockbee_4pct|G_peoplewish",
        "prior_session_change": 3.2,
        "verdict": "BORDERLINE_INTRADAY",
        "flag_reason": ("crossed the bar intraday (pre-market high/low reached %.2f%%) but is "
                        "not there at the snapshot (%.2f%%)" % (abs(gap), gap)),
        "driver_class": "IDIOSYNCRATIC",
        "driver_basis": "no proxy within 1.5pp",
        "universe_date": "2026-11-17",
        "ref_close_date": "2026-11-17",
    }
    if extra:
        rec.update(extra)
    return rec


def render(records, tmp):
    out = os.path.join(tmp, "out")
    os.makedirs(out, exist_ok=True)
    pull = {
        "contract": "premarket-artifact-v6",
        "pull_marker": "premarket-pull-v2",
        "render_marker": "premarket-render-v1",
        "gap_trigger": 4.0,
        "volume_floor": 50000,
        "min_executed_shares": 25,
        "pulls_per_symbol": 2,
        "flagged": [],
        "tape_waves": [{"wave": 1, "at_et": "08:36:21 ET", "symbols": len(records)}],
        "proxies": {"SPY": {"premarket_change": 0.1, "close": 700.0}},
        "crypto_proxy": None,
        "market_ladder": [],
        "catalysts": {},
        "records": {r["ticker"]: r for r in records},
        "driver_classes": {},
        "marker_line": ("_contract: premarket-artifact-v6 · flagged: 0 · scanned: "
                        + str(len(records))
                        + " · gate: |gap|>=4.0% and pm_volume>=50,000 and exec_shares>=25 · "
                        "reference close: focus.csv · pull: premarket-pull-v2 · "
                        "renderer: premarket-render-v1_"),
    }
    manifest = {
        "universe_date": "2026-11-17",
        "expected_prior_session": "2026-11-17",
        "ref_close_column": "today_close",
        "universe_source": "focus.csv",
        "flags": [],
    }
    context = {"catalysts": {"FAKE": {"confirmed": True, "source": "test", "note": "test"}},
               "notes": [], "source_health": []}
    pp = os.path.join(tmp, "_premarket-pull.json")
    mp = os.path.join(tmp, "_universe.json")
    cp = os.path.join(tmp, "premarket-context.json")
    for path, obj in ((pp, pull), (mp, manifest), (cp, context)):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)
    proc = subprocess.run(
        [sys.executable, RENDERER, "--pull-json", pp, "--universe-manifest", mp,
         "--context", cp, "--out-dir", out, "--date", "2026-11-18"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        bad("the renderer exited %d: %s" % (proc.returncode, proc.stderr.strip()[:400]))
        return None, None
    md = open(os.path.join(out, "pre-market-gapper.md"), encoding="utf-8").read()
    csv_text = open(os.path.join(out, "pre-market-gapper.csv"), encoding="utf-8").read()
    return md, csv_text


def flags_line(md, ticker):
    for ln in md.splitlines():
        if ln.startswith("- **%s**" % ticker) and "crossed the bar intraday" in ln:
            return ln
    return None


def main():
    if not os.path.exists(RENDERER):
        print("renderer not found at %s" % RENDERER)
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        # T1 + T2 + T3: a DOWNWARD cross, with the signed field present.
        md, csv_text = render(
            [record("DOWN", -0.10, 0.52, 0.52, {"max_tape_gap_signed_pct": -6.98,
                                               "max_tape_gap_pct": 6.98})], tmp)
        if md is None:
            return 1
        ln = flags_line(md, "DOWN")
        if not ln:
            bad("no intraday flag line for DOWN")
        else:
            if "-6.98%" in ln:
                ok("T1 the Flags line carries the SIGNED extreme (-6.98%)")
            else:
                bad("T1 the Flags line does not carry the signed extreme: %s" % ln)
            if "pre-market high" in ln or "pre-market low" in ln:
                bad("T2 the Flags line still quotes the current range as the crossing fact: %s" % ln)
            else:
                ok("T2 the Flags line no longer quotes the current range as the crossing fact")
        if "reached -6.98%" in csv_text:
            ok("T3 the CSV flag_reason carries the signed extreme")
        else:
            bad("T3 the CSV flag_reason does not carry the signed extreme")

    with tempfile.TemporaryDirectory() as tmp:
        # T4: a pull JSON that predates `max_tape_gap_signed_pct`.
        md, csv_text = render(
            [record("OLD", -0.40, 0.17, 0.17, {"tape_print_gaps": [-6.26, -1.0, 0.4]})], tmp)
        if md is None:
            return 1
        ln = flags_line(md, "OLD")
        if ln and "-6.26%" in ln:
            ok("T4 a pull JSON without the signed field still renders the signed extreme")
        else:
            bad("T4 the fallback path did not render the signed extreme: %s" % ln)

    with tempfile.TemporaryDirectory() as tmp:
        # T5: neither source -> the old wording, and no crash.
        md, csv_text = render([record("BARE", 0.5, 0.5, 0.5)], tmp)
        if md is None:
            return 1
        ln = flags_line(md, "BARE")
        if ln and "pre-market high" in ln:
            ok("T5 a record with no extreme falls back to the old wording instead of crashing")
        else:
            bad("T5 the fallback wording is missing: %s" % ln)

    if FAILS:
        print("\n%d check(s) FAILED" % len(FAILS))
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
