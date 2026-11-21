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

    # ---------- ISOLATED SCANNER `close` DEFECT ----------
    # Measured 2026-11-18: the scanner served a PRE-MARKET print in the `close` column for ONE
    # name (AUGO, 66.26) against the morning brief's corrected prior close (66.98), and the old
    # logic read that single row as "the session is live" and returned OPEN for a pull that
    # landed 5m20s BEFORE the 09:30 ET open. A live session moves the `close` column off the
    # prior close for essentially EVERY name; a field defect moves it for a handful. The
    # mismatch RATE is the discriminator, and the defects must be NAMED.
    truth = [row("AAA", 100.0, 1.0, 105.0), row("BBB", 50.0, -2.0, 47.0),
             row("CCC", 20.0, 0.5, 21.0), row("DDD", 10.0, -1.0, 9.5),
             row("EEE", 30.0, 2.0, 31.0), row("FFF", 5.0, -1.0, 4.8)]
    defect = [dict(r) for r in truth]
    defect[0]["close"] = 99.28                       # the scanner served a pre-market print
    defect[0]["change"] = -1.07
    defect[0]["change_abs"] = 99.28 - 99.28 / (1 - 0.0107)
    m4 = os.path.join(tmp, "defect_merged.json")
    mc4 = os.path.join(tmp, "defect_morning.csv")
    write_merged(m4, defect)
    write_morning_csv(mc4, truth)                   # the morning baseline holds the TRUE closes
    rc, out, err = run(["--merged", m4, "--morning-csv", mc4, "--json-only"])
    v = json.loads(out)
    check(rc == 0 and v["session_state"] == "PRE-OPEN",
          "ISOLATED-DEFECT verdict", "rc=%d state=%s" % (rc, v["session_state"]))
    check(v["close_field_defects"] == ["AAA"],
          "ISOLATED-DEFECT named", str(v["close_field_defects"]))
    check(v["front_matter"]["market_open_at_pull"] is False,
          "ISOLATED-DEFECT front matter", str(v["front_matter"]))
    check("ISOLATED scanner `close` defects" in v["verdict_reason"],
          "ISOLATED-DEFECT reason", v["verdict_reason"][:160])
    check(v["tests"]["prior_close_matches_morning"]["mismatch_rate"] < 0.25,
          "ISOLATED-DEFECT rate", str(v["tests"]["prior_close_matches_morning"]))

    # ---------- ISOLATED DEFECT ON A SMALL COMMON SET ----------
    # A four-name common set with one defective row is a 25% mismatch rate — the threshold a
    # live session produces. The COUNT floor is what stops it tipping the verdict.
    small_truth = [row("AAA", 100.0, 1.0, 105.0), row("BBB", 50.0, -2.0, 47.0),
                   row("CCC", 20.0, 0.5, 21.0), row("DDD", 10.0, -1.0, 9.5)]
    small = [dict(r) for r in small_truth]
    small[0]["close"] = 99.28
    small[0]["change"] = -1.07
    small[0]["change_abs"] = 99.28 - 99.28 / (1 - 0.0107)
    m5 = os.path.join(tmp, "small_merged.json")
    mc5 = os.path.join(tmp, "small_morning.csv")
    write_merged(m5, small)
    write_morning_csv(mc5, small_truth)
    rc, out, err = run(["--merged", m5, "--morning-csv", mc5, "--json-only"])
    v = json.loads(out)
    check(rc == 0 and v["session_state"] == "PRE-OPEN",
          "SMALL-SET-DEFECT verdict", "rc=%d state=%s" % (rc, v["session_state"]))

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

    # ---------- the ET offset is DERIVED (DST), not hardcoded ----------
    # The sandbox's America/New_York observes DST: a fixed -5 is an hour EARLY for
    # every date from mid-March to early November, a fixed -4 an hour LATE for the
    # rest of the year. The tool must resolve the offset through the IANA zone for
    # the instant it is asked about.
    import importlib.util
    spec = importlib.util.spec_from_file_location("session_state_mod", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import datetime as _dt

    def _offset_at(instant):
        return int(round((instant.astimezone(mod.ET).utcoffset()
                          or _dt.timedelta(hours=-5)).total_seconds() / 3600.0))

    summer = _dt.datetime(2026, 7, 15, 12, 0, tzinfo=_dt.timezone.utc)
    winter = _dt.datetime(2026, 1, 15, 12, 0, tzinfo=_dt.timezone.utc)
    check(_offset_at(summer) == -4,
          "EDT offset is derived",
          "2026-07-15 12:00 UTC -> %+d (want -4)" % _offset_at(summer))
    check(_offset_at(winter) == -5,
          "EST offset is derived",
          "2026-01-15 12:00 UTC -> %+d (want -5)" % _offset_at(winter))
    check(mod.et_offset_hours() in (-5, -4),
          "the reported offset is one of the two",
          "reported %+d" % mod.et_offset_hours())
    check(not hasattr(mod, "ET_OFFSET_HOURS"),
          "the hardcoded offset constant is gone",
          "a fixed offset is an hour wrong for half the year")
    check(mod.now_et().tzinfo is not None
          and mod.now_et().utcoffset() in (_dt.timedelta(hours=-5), _dt.timedelta(hours=-4)),
          "now_et is DST-aware",
          str(mod.now_et()))

    failed = [n for ok, n, _ in RESULTS if not ok]
    print("\n%d tests, %d passed, %d failed" % (len(RESULTS), len(RESULTS) - len(failed), len(failed)))
    for n in failed:
        print("  FAILED: %s" % n)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
