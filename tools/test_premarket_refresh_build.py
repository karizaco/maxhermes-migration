#!/usr/bin/env python3
"""
test_premarket_refresh_build.py — prove premarket_refresh_build.py builds a contract-passing
artifact, and that the defects it was written to prevent cannot come back.

The builder exists because the 2026-11-12 run wrote its artifact by hand and the hand-writing
produced three template bugs and two NULL-as-zero defects. A generator that has only ever been
run once is a rumor, so these tests:

  1. build a SYNTHETIC pull with enough names for the real contract checker to run on it;
  2. run the builder and then run tools/check_premarket_refresh.py on its output — the builder's
     output must satisfy the SAME contract the hand-written artifact had to satisfy;
  3. mutate the fixture so that each defect the builder was written to prevent reappears, and
     assert the builder REFUSES to write, or publishes the honest value.

USAGE
    python3 test_premarket_refresh_build.py
"""

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "premarket_refresh_build.py")
CHECKER = os.path.join(HERE, "check_premarket_refresh.py")
RESULTS = []


def check(ok, name, detail=""):
    RESULTS.append((bool(ok), name, detail))
    print("%s %-34s %s" % ("PASS" if ok else "FAIL", name, detail))
    return bool(ok)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def make_row(ticker, close, chg, pm, pv=500000, adv=2000000, cap=5_000_000_000):
    return {"ticker": ticker, "name": ticker, "description": ticker + " Inc.",
            "close": close, "change": chg, "change_abs": close - close / (1 + chg / 100.0),
            "average_volume_30d_calc": adv, "premarket_close": pm,
            "premarket_change": (pm - close) / close * 100.0,
            "premarket_high": max(pm, close) * 1.01, "premarket_low": min(pm, close) * 0.99,
            "premarket_volume": pv, "market_cap_basic": cap,
            "market_cap_published": cap, "cap_source": "the scanner's market_cap_basic",
            "sector": "Electronic Technology", "exchange": "NASDAQ"}


def build_fixture(tmp, mutate=None):
    """30 gate-passing gainers + decliners, plus the shapes that broke the hand-written run."""
    rows = []
    for i in range(20):
        rows.append(make_row("G%02d" % i, 100.0 + i, 1.0, 100.0 + i + 8.0))
    for i in range(12):
        rows.append(make_row("D%02d" % i, 100.0 + i, -1.0, 100.0 + i - 8.0))
    # a thin-tape name: passes Gate A, fails the $100m quality floor
    rows.append(make_row("THIN", 5.0, 0.0, 5.5, pv=400000, adv=1000000, cap=40_000_000))
    # a name that fails Gate A on liquidity: 1,000 pre-market shares
    rows.append(make_row("ILLIQ", 12.0, 0.0, 13.0, pv=1000, adv=1000000, cap=500_000_000))
    # the two NULL rows that reached the 2026-11-12 CSV as zeros
    null_adv = make_row("NULADV", 7.0, 0.0, 7.6, pv=200000, adv=None, cap=300_000_000)
    null_cap = make_row("NULCAP", 9.0, 0.0, 9.6, pv=200000, adv=1000000, cap=None)
    null_adv["average_volume_30d_calc"] = None
    null_cap["market_cap_basic"] = None
    null_cap["market_cap_published"] = None
    rows += [null_adv, null_cap]
    # a name with no pre-market print at all — excluded, never published as 0.0000
    nopm = make_row("NOPM", 4.0, 0.0, 4.4)
    nopm["premarket_close"] = None
    nopm["premarket_change"] = None
    rows.append(nopm)

    if mutate:
        mutate(rows)

    merged = os.path.join(tmp, "merged.json")
    json.dump({"date": "2026-11-12", "pulled_at_et": "2026-11-12 09:24:15",
               "marker": "brief26-pull-v1",
               "band": {"gainers": sum(1 for r in rows
                                       if num(r["premarket_change"] or 0) > 0),
                        "decliners": sum(1 for r in rows
                                         if num(r["premarket_change"] or 0) < 0),
                        "complete": True},
               "rows": rows}, open(merged, "w"))

    # a morning baseline: the same names, most of them flat, so nothing has "changed"
    mcsv = os.path.join(tmp, "morning.csv")
    with open(mcsv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ticker", "name", "prior_close", "gap_pct", "has_news", "market_cap",
                    "setup_theme", "setup_published"])
        for r in rows:
            if r["ticker"] == "NOPM":
                continue
            w.writerow([r["ticker"], r["name"], "%.4f" % r["close"], "%.2f" % r["premarket_change"],
                        "yes" if r["ticker"].startswith("G") else "no",
                        ("%d" % r["market_cap_basic"]) if r["market_cap_basic"] else "",
                        "C1 - a theme" if r["ticker"] == "G00" else "", "yes" if r["ticker"] == "G00" else "no"])
    mmd = os.path.join(tmp, "morning.md")
    with open(mmd, "w") as fh:
        fh.write("---\ndate: 2026-11-12\ncron: 26-agentic-pre-market-brief\n"
                 "up_3pct: %d\ndown_3pct: %d\nscreen_complete: true\n---\n\n# morning\n"
                 % (sum(1 for r in rows if num(r["premarket_change"] or 0) > 0),
                    sum(1 for r in rows if num(r["premarket_change"] or 0) < 0)))

    slots = os.path.join(tmp, "slots.json")
    json.dump({"drivers": {"G00": {"class": "EARNINGS-RECONFIRM", "anchored": True,
                                   "note": "adjusted EPS $0.49 against $0.47 expected"},
                           "D00": {"class": "EARNINGS-CUT", "anchored": True,
                                   "note": "guidance withdrawn"}},
               "setup": {"ticker": "G00"},
               "risk": {"ticker": "D00", "clause": "the tape is de-rating"},
               "watch": {"ticker": "G01", "clause": "the biggest mover"}}, open(slots, "w"))
    return merged, mmd, mcsv, slots


def run_builder(merged, mmd, mcsv, slots, out):
    return subprocess.run([sys.executable, BUILD, "--merged", merged, "--morning-md", mmd,
                           "--morning-csv", mcsv, "--slots", slots, "--date", "2026-11-12",
                           "--fire-time-et", "2026-11-12 09:20", "--snapshot-et", "09:24:15",
                           "--session-state", "PRE-OPEN", "--out-dir", out],
                          capture_output=True, text=True)


def main():
    tmp = tempfile.mkdtemp(prefix="refresh_build_test_")
    out = os.path.join(tmp, "out")

    # ---------- 1. the happy path ----------
    merged, mmd, mcsv, slots = build_fixture(tmp)
    p = run_builder(merged, mmd, mcsv, slots, out)
    check(p.returncode == 0, "builder exits 0", (p.stderr or "").strip().split("\n")[-1])
    md_path = os.path.join(out, "2026-11-12-pre-market-refresh.md")
    csv_path = os.path.join(out, "2026-11-12-pre-market-refresh.csv")
    check(os.path.exists(md_path) and os.path.exists(csv_path), "both files written")

    if os.path.exists(md_path) and os.path.exists(csv_path):
        # ---------- 2. the REAL contract checker on the builder's output ----------
        c = subprocess.run([sys.executable, CHECKER, "--md", md_path, "--csv", csv_path,
                            "--morning-csv", mcsv], capture_output=True, text=True)
        fails = [l for l in (c.stdout + c.stderr).split("\n") if l.startswith("FAIL")]
        check(c.returncode == 0 and not fails,
              "the REAL contract checker passes", (c.stdout.strip().split("\n")[-1] if c.stdout else ""))

        # ---------- 3. the defects the builder exists to prevent ----------
        rows = list(csv.DictReader(open(csv_path)))
        by = {r["ticker"]: r for r in rows}
        check(by["NULADV"]["avg_volume_30d"].strip() == "",
              "a NULL average volume is EMPTY", repr(by["NULADV"]["avg_volume_30d"]))
        check(by["NULADV"]["pct_of_adv"].strip() == "",
              "its %ADV is EMPTY too", repr(by["NULADV"]["pct_of_adv"]))
        check(by["NULCAP"]["market_cap"].strip() == "",
              "a NULL market cap is EMPTY", repr(by["NULCAP"]["market_cap"]))
        check("NOPM" not in by, "a row with no pre-market print is excluded")
        check(all(r["live_close"].strip() == "" and r["live_volume"].strip() == ""
                  for r in rows), "live_* are blank on every row (pre-open)")
        bad = []
        for r in rows:
            try:
                d = float(r["premarket_close"]) / (1 + float(r["premarket_change_pct"]) / 100.0)
                if abs(d - float(r["prior_close"])) > 0.0005 + abs(float(r["prior_close"])) * 1e-6:
                    bad.append(r["ticker"])
            except ValueError:
                bad.append(r["ticker"])
        check(not bad, "every row reproduces its own prior close", str(bad[:5]))
        md = open(md_path).read()
        check("+ANCHORED" in md, "the anchored driver is published")
        check("no name carries an anchored catalyst" not in md,
              "the cash case is NOT published when a setup exists")
        check(md.count("EARNINGS-RECONFIRM+ANCHORED") >= 1, "the driver carries the +ANCHORED suffix")

    # ---------- 4. the cash case ----------
    tmp2 = tempfile.mkdtemp(prefix="refresh_build_test_cash_")
    merged2, mmd2, mcsv2, slots2 = build_fixture(tmp2)

    def strip_drivers(rows):
        pass
    s2 = json.load(open(slots2))
    s2["drivers"] = {}
    s2.pop("setup")
    json.dump(s2, open(slots2, "w"))
    out2 = os.path.join(tmp2, "out")
    p2 = run_builder(merged2, mmd2, mcsv2, slots2, out2)
    md2 = open(os.path.join(out2, "2026-11-12-pre-market-refresh.md")).read() \
        if os.path.exists(os.path.join(out2, "2026-11-12-pre-market-refresh.md")) else ""
    check("no name carries an anchored catalyst" in md2,
          "the cash case is published honestly", p2.stderr.strip().split("\n")[-1])

    # ---------- 5. an unknown driver class is refused, not published ----------
    tmp3 = tempfile.mkdtemp(prefix="refresh_build_test_drv_")
    merged3, mmd3, mcsv3, slots3 = build_fixture(tmp3)
    s3 = json.load(open(slots3))
    s3["drivers"]["G00"]["class"] = "MADE-UP-CLASS"
    json.dump(s3, open(slots3, "w"))
    out3 = os.path.join(tmp3, "out")
    p3 = run_builder(merged3, mmd3, mcsv3, slots3, out3)
    md3 = open(os.path.join(out3, "2026-11-12-pre-market-refresh.md")).read() \
        if os.path.exists(os.path.join(out3, "2026-11-12-pre-market-refresh.md")) else ""
    check("MADE-UP-CLASS" not in md3, "an invented driver class is not published")
    check("unknown driver class" in (p3.stderr or "").lower(),
          "the invented class is reported", p3.stderr.strip().split("\n")[-1])

    # ---------- 6. a truncated band publishes screen_complete: false ----------
    tmp4 = tempfile.mkdtemp(prefix="refresh_build_test_trunc_")
    merged4, mmd4, mcsv4, slots4 = build_fixture(tmp4)
    m4 = json.load(open(merged4))
    m4["band"]["complete"] = False
    json.dump(m4, open(merged4, "w"))
    out4 = os.path.join(tmp4, "out")
    p4 = run_builder(merged4, mmd4, mcsv4, slots4, out4)
    md4 = open(os.path.join(out4, "2026-11-12-pre-market-refresh.md")).read() \
        if os.path.exists(os.path.join(out4, "2026-11-12-pre-market-refresh.md")) else ""
    check("screen_complete: false" in md4, "a truncated band publishes screen_complete: false")
    check("FLOOR" in md4.upper() or "floor" in md4, "a truncated band says its counts are floors")

    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmp2, ignore_errors=True)
    shutil.rmtree(tmp3, ignore_errors=True)
    shutil.rmtree(tmp4, ignore_errors=True)

    failed = [n for ok, n, _ in RESULTS if not ok]
    print("\n%d tests, %d passed, %d failed" % (len(RESULTS), len(RESULTS) - len(failed), len(failed)))
    for n in failed:
        print("  FAILED: %s" % n)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
