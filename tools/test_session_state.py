#!/usr/bin/env python3
"""
test_session_state.py — prove session_state.py can tell PRE-OPEN from OPEN.

A checker that has only ever seen a synthetic artifact has observed nothing; a checker that has
only ever agreed with the writer has observed nothing either. These tests build the three
states by hand and assert the verdict AND the exit code for each, so a regression in the
decision logic cannot pass silently.

The three states are built to differ in the way the real data differs:

  PRE-OPEN   the scanner's `close` is the last completed session's close, so it MATCHES the
             morning brief's published prior_close, and the settled-session identity holds.
  OPEN       the scanner's `close` has become the LIVE price, so it no longer matches the
             morning brief's prior_close, and the rows sit within 1% of the pre-market print.
  BROKEN     the settled-session identity fails — the pull is internally inconsistent and NO
             verdict is safe.

USAGE
    python3 test_session_state.py
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "session_state.py")
RESULTS = []


def check(ok, name, detail=""):
    RESULTS.append((bool(ok), name, detail))
    print("%s %-26s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


def row(ticker, close, chg, pm, pv=500000, adv=2000000, cap=5_000_000_000):
    """One scanner row. `chg` is the regular session's own % move."""
    change_abs = close - close / (1 + chg / 100.0)
    return {"ticker": ticker, "name": ticker, "description": ticker + " Inc.",
            "close": close, "change": chg, "change_abs": change_abs,
            "average_volume_30d_calc": adv, "premarket_close": pm,
            "premarket_change": (pm - close) / close * 100.0,
            "premarket_high": max(pm, close) * 1.01, "premarket_low": min(pm, close) * 0.99,
            "premarket_volume": pv, "market_cap_basic": cap,
            "market_cap_published": cap, "cap_source": "the scanner's market_cap_basic",
            "sector": "Electronic Technology", "exchange": "NASDAQ"}


def write_merged(path, rows, band_complete=True):
    json.dump({"date": "2026-11-12", "pulled_at_et": "2026-11-12 09:24:15",
               "marker": "brief26-pull-v1",
               "band": {"gainers": sum(1 for r in rows if r["premarket_change"] > 0),
                        "decliners": sum(1 for r in rows if r["premarket_change"] < 0),
                        "complete": band_complete},
               "rows": rows}, open(path, "w"))


def write_morning_csv(path, rows):
    import csv as _csv
    with open(path, "w", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(["ticker", "name", "prior_close", "gap_pct", "has_news", "market_cap"])
        for r in rows:
            w.writerow([r["ticker"], r["name"], "%.4f" % r["close"],
                        "%.2f" % r["premarket_change"], "no", "%d" % r["market_cap_basic"]])


def run(tool_args):
    p = subprocess.run([sys.executable, TOOL] + tool_args, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def main():
    tmp = tempfile.mkdtemp(prefix="session_state_test_")

    # ---------- PRE-OPEN ----------
    pre = [row("AAA", 100.0, 1.0, 105.0), row("BBB", 50.0, -2.0, 47.0),
           row("CCC", 20.0, 0.5, 21.0), row("DDD", 10.0, -1.0, 9.5)]
    m = os.path.join(tmp, "pre_merged.json")
    mc = os.path.join(tmp, "pre_morning.csv")
    write_merged(m, pre)
    write_morning_csv(mc, pre)
    rc, out, err = run(["--merged", m, "--morning-csv", mc, "--json-only"])
    v = json.loads(out)
    check(rc == 0 and v["session_state"] == "PRE-OPEN",
          "PRE-OPEN verdict", "rc=%d state=%s" % (rc, v["session_state"]))
    check(v["tests"]["settled_session_identity"]["ok"] is True,
          "PRE-OPEN identity", str(v["tests"]["settled_session_identity"]))
    check(v["tests"]["prior_close_matches_morning"]["failed"] == 0,
          "PRE-OPEN prior close", str(v["tests"]["prior_close_matches_morning"]))
    check(v["front_matter"]["market_open_at_pull"] is False,
          "PRE-OPEN front matter", str(v["front_matter"]))

    # ---------- OPEN: the close column has become the LIVE price ----------
    opened = [row("AAA", 104.2, 1.0, 105.0), row("BBB", 47.1, -2.0, 47.0),
              row("CCC", 20.9, 0.5, 21.0), row("DDD", 9.6, -1.0, 9.5)]
    m2 = os.path.join(tmp, "open_merged.json")
    write_merged(m2, opened)
    write_morning_csv(mc, pre)          # the morning baseline still holds the PRIOR closes
    rc, out, err = run(["--merged", m2, "--morning-csv", mc, "--json-only"])
    v = json.loads(out)
    check(rc == 3 and v["session_state"] == "OPEN",
          "OPEN verdict", "rc=%d state=%s" % (rc, v["session_state"]))
    check(v["front_matter"]["market_open_at_pull"] is True,
          "OPEN front matter", str(v["front_matter"]))

    # ---------- BROKEN: the settled-session identity fails ----------
    broken = [row("AAA", 100.0, 1.0, 105.0), row("BBB", 50.0, -2.0, 47.0)]
    broken[1]["change_abs"] = 999.0
    m3 = os.path.join(tmp, "broken_merged.json")
    write_merged(m3, broken)
    rc, out, err = run(["--merged", m3, "--morning-csv", mc, "--json-only"])
    v = json.loads(out)
    check(rc == 4 and v["session_state"] == "INDETERMINATE",
          "BROKEN verdict", "rc=%d state=%s" % (rc, v["session_state"]))
    check(v["tests"]["settled_session_identity"]["failed"] == 1,
          "BROKEN identity counted", str(v["tests"]["settled_session_identity"]))

    # ---------- no morning baseline: the primary discriminator is unavailable ----------
    rc, out, err = run(["--merged", m, "--json-only"])
    v = json.loads(out)
    check(v["tests"]["prior_close_matches_morning"]["ok"] is None,
          "missing baseline is reported", str(v["tests"]["prior_close_matches_morning"]))

    failed = [n for ok, n, _ in RESULTS if not ok]
    print("\n%d tests, %d passed, %d failed" % (len(RESULTS), len(RESULTS) - len(failed), len(failed)))
    for n in failed:
        print("  FAILED: %s" % n)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
