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
        w.writerow(["ticker", "name", "prior_close", "gap_pct", "prior_session_change_pct",
                    "has_news", "market_cap",
                    "setup_theme", "setup_published"])
        for r in rows:
            if r["ticker"] == "NOPM":
                continue
            w.writerow([r["ticker"], r["name"], "%.4f" % r["close"], "%.2f" % r["premarket_change"],
                        "-1.23",
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


def run_builder(merged, mmd, mcsv, slots, out, state="PRE-OPEN", stall=None, snapshot="09:24:15",
                state_file=None, state_note=None):
    cmd = [sys.executable, BUILD, "--merged", merged, "--morning-md", mmd,
           "--morning-csv", mcsv, "--slots", slots, "--date", "2026-11-12",
           "--fire-time-et", "2026-11-12 09:20", "--snapshot-et", snapshot,
           "--session-state", state, "--out-dir", out]
    if stall is not None:
        cmd += ["--stall-min", str(stall)]
    if state_file is not None:
        cmd += ["--state", state_file]
    if state_note is not None:
        cmd += ["--state-note", state_note]
    return subprocess.run(cmd, capture_output=True, text=True)


def main():
    tmp = tempfile.mkdtemp(prefix="refresh_build_test_")
    out = os.path.join(tmp, "out")

    # ---------- 0. the GATE's verdict rides into the artifact ----------
    # Measured 2026-11-18: the gate returned OPEN on ONE isolated scanner `close` defect for a
    # pull that landed before the open, and the run published PRE-OPEN — in prose, by hand. The
    # builder now reads the gate's verdict file: it NAMES the defects, and it publishes BOTH
    # verdicts when the branch it was told to publish is not the gate's.
    merged0, mmd0, mcsv0, slots0 = build_fixture(tmp)
    gatef = os.path.join(tmp, "state.json")
    json.dump({"marker": "session-state-v3", "session_state": "PRE-OPEN",
               "close_field_defects": ["AUGO"],
               "verdict_reason": "the scanner's close disagreed on one name of 703 common names"},
              open(gatef, "w"))
    out0 = os.path.join(tmp, "out_gate")
    p0 = run_builder(merged0, mmd0, mcsv0, slots0, out0, state_file=gatef)
    md0 = os.path.join(out0, "2026-11-12-pre-market-refresh.md")
    if os.path.exists(md0):
        t0 = open(md0, encoding="utf-8").read()
        check("AUGO" in t0, "the isolated close-field defect is NAMED in Source health")
        check("ISOLATED field defects" in t0,
              "the defect line says what it is", "the defect line is missing")
    else:
        check(False, "the gate-verdict build wrote a file")

    gatef2 = os.path.join(tmp, "state_open.json")
    json.dump({"marker": "session-state-v3", "session_state": "OPEN",
               "close_field_defects": [],
               "verdict_reason": "the gate says the session is live"},
              open(gatef2, "w"))
    out1 = os.path.join(tmp, "out_gate_open")
    p1 = run_builder(merged0, mmd0, mcsv0, slots0, out1, state="PRE-OPEN", state_file=gatef2,
                     state_note="the pull landed before the 09:30 ET open")
    md1 = os.path.join(out1, "2026-11-12-pre-market-refresh.md")
    if os.path.exists(md1):
        t1 = open(md1, encoding="utf-8").read()
        check("session-state gate returned `OPEN`" in t1,
              "a verdict disagreement publishes BOTH verdicts")
        check("the pull landed before the 09:30 ET open" in t1,
              "the run's reason is published")
    else:
        check(False, "the disagreement build wrote a file")
    check("the session-state gate returned OPEN" in (p1.stderr or ""),
          "the disagreement is printed on stderr", (p1.stderr or "").strip()[-120:])

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

    # The cash case must ALSO satisfy the REAL contract gate.  It did not: line 1 carried
    # no digit and no invalidation level, and the watch table carried two rows instead of
    # three - the gate had never been run on this branch, and the 2026-11-17 fire found it.
    md2_path = os.path.join(out2, "2026-11-12-pre-market-refresh.md")
    csv2_path = os.path.join(out2, "2026-11-12-pre-market-refresh.csv")
    if os.path.exists(md2_path) and os.path.exists(csv2_path):
        c2 = subprocess.run([sys.executable, CHECKER, "--md", md2_path, "--csv", csv2_path,
                             "--morning-csv", mcsv2], capture_output=True, text=True)
        fails2 = [l for l in (c2.stdout + c2.stderr).split("\n") if l.startswith("FAIL")]
        check(c2.returncode == 0 and not fails2,
              "the REAL contract checker passes on the CASH CASE too",
              (c2.stdout.strip().split("\n")[-1] if c2.stdout else ""))

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

    # ---------- 7. the risk and watch lines follow the gap's DIRECTION ----------
    # The default fixture puts a gap-DOWN in the risk slot and a gap-UP in the watch slot,
    # which is the only combination the old direction-blind templates happened to fit.
    # Swap them: a gap-UP risk and a gap-DOWN watch must publish the OTHER level, or the
    # prose contradicts the watch table two sections below it.
    tmp5 = tempfile.mkdtemp(prefix="refresh_build_test_dir_")
    merged5, mmd5, mcsv5, slots5 = build_fixture(tmp5)
    s5 = json.load(open(slots5))
    s5["risk"] = {"ticker": "G01", "clause": "the policy relief is fading"}
    s5["watch"] = {"ticker": "D00", "clause": "the seller is still there"}
    json.dump(s5, open(slots5, "w"))
    out5 = os.path.join(tmp5, "out")
    p5 = run_builder(merged5, mmd5, mcsv5, slots5, out5)
    md5 = open(os.path.join(out5, "2026-11-12-pre-market-refresh.md")).read() \
        if os.path.exists(os.path.join(out5, "2026-11-12-pre-market-refresh.md")) else ""
    risk_line = ""
    watch_line = ""
    for l in md5.split("\n"):
        if l.strip().startswith("2. **The one risk**"):
            risk_line = l
        if l.strip().startswith("3. **The one thing to watch"):
            watch_line = l
    check("a trade back to/below the prior close" in risk_line,
          "a gap-UP risk publishes the gap-fill level", risk_line[-120:])
    check("a break of the pre-market low" not in risk_line,
          "a gap-UP risk does NOT publish the PM-low level", risk_line[-120:])
    check("an open below" in watch_line and "a reclaim of" in watch_line,
          "a gap-DOWN watch publishes the seller/reclaim wording", watch_line[-120:])
    check("keeps it bid" not in watch_line,
          "a gap-DOWN watch does NOT publish the bid wording", watch_line[-120:])

    # ---------- 8. the LATE-PULL branch must be publishable ----------
    # It advertised `pull_late: true` / `market_open_at_pull: true` but the CSV writer always
    # wrote the three live columns empty, so its own internal gate refused to write the file:
    # "market_open_at_pull is true but live_* are blank".  The branch was unreachable.
    tmp6 = tempfile.mkdtemp(prefix="refresh_build_test_late_")
    merged6, mmd6, mcsv6, slots6 = build_fixture(tmp6)
    m6 = json.load(open(merged6))
    m6["pulled_at_et"] = "2026-11-12 21:24:08"      # after the 16:00 close
    json.dump(m6, open(merged6, "w"))
    out6 = os.path.join(tmp6, "out")
    p6 = run_builder(merged6, mmd6, mcsv6, slots6, out6, state="OPEN", stall=722,
                     snapshot="21:24")
    md6_path = os.path.join(out6, "2026-11-12-pre-market-refresh.md")
    csv6_path = os.path.join(out6, "2026-11-12-pre-market-refresh.csv")
    check(p6.returncode == 0 and os.path.exists(md6_path) and os.path.exists(csv6_path),
          "the LATE-PULL branch publishes a file", (p6.stderr or "").strip().split("\n")[-1])
    if os.path.exists(md6_path) and os.path.exists(csv6_path):
        md6 = open(md6_path).read()
        rows6 = list(csv.DictReader(open(csv6_path)))
        check("market_open_at_pull: true" in md6 and "pull_late: true" in md6,
              "the late pull carries pull_late and market_open_at_pull")
        check("settled" in md6, "the intro says the live columns are the SETTLED close")
        check("722 minute" in md6, "the intro states the stall")
        check(all(r["live_close"].strip() for r in rows6),
              "the live columns carry the regular session")
        check(all(r["prior_session_change_pct"].strip() for r in rows6),
              "prior_session_change_pct comes from the morning CSV in a late pull")
        c6 = subprocess.run([sys.executable, CHECKER, "--md", md6_path, "--csv", csv6_path,
                             "--morning-csv", mcsv6], capture_output=True, text=True)
        fails6 = [l for l in (c6.stdout + c6.stderr).split("\n") if l.startswith("FAIL")]
        check(c6.returncode == 0 and not fails6,
              "the REAL contract checker passes on the LATE-PULL branch",
              (c6.stdout.strip().split("\n")[-1] if c6.stdout else ""))

    # The LIVE late pull (the session is open but the close has not happened) is a DIFFERENT
    # branch from the CLOSED one above, and it had NO test: it computed the stall sentence and
    # then DROPPED it, so a replayed file never said WHY it was late. Measured 2026-11-19: the
    # 09:20 ET fire was held 44 minutes and the published artifact's intro named no stall at all.
    tmp7 = tempfile.mkdtemp(prefix="refresh_build_test_late_live_")
    merged7, mmd7, mcsv7, slots7 = build_fixture(tmp7)
    m7 = json.load(open(merged7))
    m7["pulled_at_et"] = "2026-11-12 10:06:17"      # inside the session
    json.dump(m7, open(merged7, "w"))
    out7 = os.path.join(tmp7, "out")
    p7 = run_builder(merged7, mmd7, mcsv7, slots7, out7, state="OPEN", stall=44,
                     snapshot="10:06")
    md7_path = os.path.join(out7, "2026-11-12-pre-market-refresh.md")
    csv7_path = os.path.join(out7, "2026-11-12-pre-market-refresh.csv")
    check(p7.returncode == 0 and os.path.exists(md7_path),
          "the LIVE late-pull branch publishes a file", (p7.stderr or "").strip().split("\n")[-1])
    if os.path.exists(md7_path):
        md7 = open(md7_path).read()
        check("held this fire for 44 minutes" in md7,
              "the LIVE late pull STATES THE STALL", "the stall is missing from the intro")
        check("after the 09:30 ET open" in md7,
              "the LIVE late pull states the open time", "the open time is missing")
        check("10:06" in md7, "the LIVE late pull states the pull time")
        c7 = subprocess.run([sys.executable, CHECKER, "--md", md7_path, "--csv", csv7_path,
                             "--morning-csv", mcsv7], capture_output=True, text=True)
        fails7 = [l for l in (c7.stdout + c7.stderr).split("\n") if l.startswith("FAIL")]
        check(c7.returncode == 0 and not fails7,
              "the contract checker passes on the LIVE late-pull branch",
              "; ".join(fails7)[:200])

    # ---------- 2. the 2026-11-19 fixes: the three defects that fire measured ----------
    # (a) The morning brief's own v2 contract puts its TITLE and intro paragraph BEFORE the
    #     `---` block. The builder's front-matter parser used to demand that the file START
    #     with `---`, so it read nothing and the artifact published a literal "?" where the
    #     baseline's band counts belong - and the checker's placeholder list held only "???",
    #     so the gate passed it.
    merged2, mmd2, mcsv2, slots2 = build_fixture(tmp)
    mrows2 = json.load(open(merged2))["rows"]
    ug = sum(1 for r in mrows2 if num(r["premarket_change"] or 0) > 0)
    ud = sum(1 for r in mrows2 if num(r["premarket_change"] or 0) < 0)
    with open(mmd2, "w") as fh:
        fh.write("# Agentic pre-market brief - 2026-11-12\n\nOne pull of the tape at 08:34 ET.\n\n"
                 "---\ndate: 2026-11-12\ncron: 26-agentic-pre-market-brief\n"
                 "up_3pct: %d\ndown_3pct: %d\nscreen_complete: true\n---\n\n# morning\n" % (ug, ud))
    out2 = os.path.join(tmp, "out_titled_baseline")
    p2 = run_builder(merged2, mmd2, mcsv2, slots2, out2)
    md2 = os.path.join(out2, "2026-11-12-pre-market-refresh.md")
    csv2 = os.path.join(out2, "2026-11-12-pre-market-refresh.csv")
    if os.path.exists(md2):
        t2 = open(md2, encoding="utf-8").read()
        nonheading2 = "\n".join(ln for ln in t2.split("\n") if "can this gap hold" not in ln)
        check("?" not in nonheading2,
              "a TITLED baseline publishes no bare '?'")
        check(("%d gainers / %d decliners" % (ug, ud)) in t2,
              "the baseline's band counts are read from a TITLED file",
              "the band-membership sentence lost the counts")
        c2 = subprocess.run([sys.executable, CHECKER, "--md", md2, "--csv", csv2,
                             "--morning-csv", mcsv2], capture_output=True, text=True)
        fails2 = [l for l in (c2.stdout + c2.stderr).split("\n") if l.startswith("FAIL")]
        check(c2.returncode == 0 and not fails2,
              "the contract checker passes on a TITLED baseline",
              "; ".join(fails2)[:200])
    else:
        check(False, "the titled-baseline build wrote a file")

    # (b) The GATE WINS. Measured 2026-11-19: the gate returned OPEN (581 of 747 common
    #     names off their prior close) and the artifact published "These are ISOLATED field
    #     defects, not a live session" directly beside `market_open_at_pull: true`.
    gatef3 = os.path.join(tmp, "state_live.json")
    json.dump({"marker": "session-state-v3", "session_state": "OPEN",
               "close_field_defects": ["AUGO", "NVDA", "SLS"],
               "tests": {"prior_close_matches_morning": {"checked": 747, "failed": 581}},
               "verdict_reason": "the scanner's close moved off the prior close on 581 of 747 names"},
              open(gatef3, "w"))
    out3 = os.path.join(tmp, "out_live_gate")
    p3 = run_builder(merged2, mmd2, mcsv2, slots2, out3, state="OPEN", state_file=gatef3,
                     snapshot="10:06:17")
    md3 = os.path.join(out3, "2026-11-12-pre-market-refresh.md")
    csv3 = os.path.join(out3, "2026-11-12-pre-market-refresh.csv")
    if os.path.exists(md3):
        t3 = open(md3, encoding="utf-8").read()
        check("not a live session" not in t3,
              "a LIVE pull never claims the session is not live")
        check("LIVE regular-session price" in t3 and "market_open_at_pull: true" in t3,
              "a LIVE pull says the close column IS the live price")
        check("581" in t3, "a LIVE pull publishes the gate's OWN count")
        c3 = subprocess.run([sys.executable, CHECKER, "--md", md3, "--csv", csv3,
                             "--morning-csv", mcsv2], capture_output=True, text=True)
        fails3 = [l for l in (c3.stdout + c3.stderr).split("\n") if l.startswith("FAIL")]
        check(c3.returncode == 0 and not fails3,
              "the contract checker passes on the LIVE branch",
              "; ".join(fails3)[:200])
    else:
        check(False, "the live-gate build wrote a file")

    # (c) The verb follows the gap's DIRECTION. Measured 2026-11-19: SLS moved from -20.61%
    #     to -14.15% and the artifact published "extended its gap 6.46pp" - on a gap-DOWN name
    #     a POSITIVE change is the decline NARROWING.
    merged4, mmd4, mcsv4, slots4 = build_fixture(tmp)
    rows4 = list(csv.DictReader(open(mcsv4)))
    with open(mcsv4, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows4[0].keys()))
        w.writeheader()
        for r in rows4:
            if r["ticker"] == "D00":
                r["gap_pct"] = "-12.00"          # the pull says -8.00: the decline NARROWED
                r["setup_theme"] = "C1 - a theme"
            w.writerow(r)
    out4 = os.path.join(tmp, "out_gap_direction")
    p4 = run_builder(merged4, mmd4, mcsv4, slots4, out4)
    md4 = os.path.join(out4, "2026-11-12-pre-market-refresh.md")
    if os.path.exists(md4):
        t4 = open(md4, encoding="utf-8").read()
        check("narrowed its decline **4.00pp**" in t4,
              "a gap-DOWN name that moved toward zero NARROWED its decline")
        check("extended its gap **4.00pp**" not in t4,
              "a gap-DOWN name is never published as extending its gap")
    else:
        check(False, "the gap-direction build wrote a file")

    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmp2, ignore_errors=True)
    shutil.rmtree(tmp3, ignore_errors=True)
    shutil.rmtree(tmp4, ignore_errors=True)
    shutil.rmtree(tmp5, ignore_errors=True)
    shutil.rmtree(tmp6, ignore_errors=True)
    shutil.rmtree(tmp7, ignore_errors=True)

    failed = [n for ok, n, _ in RESULTS if not ok]
    print("\n%d tests, %d passed, %d failed" % (len(RESULTS), len(RESULTS) - len(failed), len(failed)))
    for n in failed:
        print("  FAILED: %s" % n)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
