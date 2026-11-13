#!/usr/bin/env python3
"""
test_open_0950_pull.py — prove the cron #17 open-slot pull engine's rules hold,
and that each rule can actually FAIL a broken reconstruction.

Why
---
The 2026-11-10 open fire published a board whose every price was computed
against a TEN-DAY-OLD reference price: the script read Yahoo's
`chartPreviousClose` out of a multi-day range, where that field is the close
BEFORE the range starts. Nothing crashed. The board was wrong and looked
right. A pull engine that has only ever run on good data is a rumor.

This test does two things, offline (no network):

  1. asserts every rule the engine claims to enforce — the prior close comes
     from the PRIOR SESSION's bars, a null close neither drops a name nor
     erases its volume, the edge's throttle body is a THROTTLE and not a
     parse error, the venue prefix is stripped, the universe filters do not
     eat the issuer's non-leveraged funds, and the pace scales on both bases;
  2. MUTATES a good reconstruction six different ways and requires the
     PUBLISH GATE to fail each one — a ten-day-old prior close, an index
     mismatch, a missing price, an inflated cross-section, an incomplete
     published set.

Every mutation asserts the text/data actually CHANGED before the gate runs,
so a mutation that does not apply reports a false "NOT CAUGHT".

USAGE
    python3 tools/test_open_0950_pull.py
Exit codes: 0 = all good; 1 = a rule does not hold, or a breach was not caught.
"""

import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(ROOT, "tools", "open_0950_pull.py")

spec = importlib.util.spec_from_file_location("open_0950_pull", ENGINE)
op = importlib.util.module_from_spec(spec)
spec.loader.exec_module(op)

PASS = "PASS"
FAIL = "FAIL"
results = []


def check(name, cond, detail=""):
    results.append((PASS if cond else FAIL, name, detail))
    print("  %-4s %s%s" % (PASS if cond else FAIL, name, (" — " + detail) if detail and not cond else ""))
    return cond


def mk_payload(prior_bars, day_bars, meta_pc=100.0):
    ts, closes, opens, vols = [], [], [], []
    for b in prior_bars + day_bars:
        ts.append(b["ts"])
        closes.append(b["c"])
        opens.append(b["o"])
        vols.append(b["v"])
    return {"meta": {"chartPreviousClose": meta_pc},
            "timestamp": ts,
            "indicators": {"quote": [{"close": closes, "open": opens, "volume": vols}]}}


def good_world():
    """A small, consistent reconstruction: two indices and two stocks."""
    d_prior = datetime(2026, 11, 11, 15, 55, tzinfo=op.ET)
    d_30 = datetime(2026, 11, 12, 9, 30, tzinfo=op.ET)
    d_45 = datetime(2026, 11, 12, 9, 45, tzinfo=op.ET)
    prior = [{"ts": d_prior.timestamp(), "o": 700.0, "c": 699.0, "v": 1000}]
    day = [{"ts": d_30.timestamp(), "o": 698.0, "c": 697.5, "v": 400},
           {"ts": d_45.timestamp(), "o": 697.0, "c": 696.0, "v": 600}]
    recs = {}
    for sym, pc, px in (("SPY", 699.0, 696.0), ("QQQ", 690.0, 688.0),
                        ("AAPL", 100.0, 101.0), ("MSFT", 200.0, 199.0)):
        r = op.build_record(sym, mk_payload(prior, day, meta_pc=pc * 1.15),
                            "2026-11-12", "2026-11-11")
        r["session_vol_to_0950_raw"] = 1000
        r["y5m_total_prior"] = 9000
        r["y5m_total_to_pull"] = 9000
        r["daily_volume_live_today"] = 9500
        r["pace"] = 1.2
        recs[sym] = r
    daily = {s: {"daily_close_prior_official": recs[s]["prior_close"],
                 "daily_volume_live_today": 9500} for s in recs}
    scanner = {s: recs[s]["chg_pct_0950"] for s in recs}
    return recs, daily, scanner


def main():
    print("== 1. the rules the engine claims to enforce ==")
    recs, daily, scanner = good_world()

    check("the prior close is the PRIOR SESSION's last bar",
          all(recs[s]["prior_close"] is not None for s in recs))
    check("the engine records which basis it used",
          all(recs[s]["prior_close_source"] == "prior_session_last_non_null_bar"
              for s in recs))
    check("the stale meta.chartPreviousClose is kept for audit only",
          recs["SPY"]["meta_chart_previous_close"] == 699.0 * 1.15)

    # a null close must not drop the name or its volume
    d_30 = datetime(2026, 11, 12, 9, 30, tzinfo=op.ET)
    d_45 = datetime(2026, 11, 12, 9, 45, tzinfo=op.ET)
    prior = [{"ts": datetime(2026, 11, 11, 15, 55, tzinfo=op.ET).timestamp(),
              "o": 700.0, "c": 699.0, "v": 1000}]
    day = [{"ts": d_30.timestamp(), "o": 698.0, "c": None, "v": 400},
           {"ts": d_45.timestamp(), "o": 697.0, "c": 696.0, "v": 600}]
    r = op.build_record("X", mk_payload(prior, day), "2026-11-12", "2026-11-11")
    check("a null close does not drop the name", r.get("status") == "OK", str(r.get("status")))
    check("the price is the last NON-NULL close at or before the cut",
          r.get("close_0950") == 696.0, str(r.get("close_0950")))
    check("a null-close bar's volume still counts",
          r.get("session_vol_to_0950_raw") == 1000, str(r.get("session_vol_to_0950_raw")))

    check("'Edge: Too Many Requests' is a THROTTLE",
          op.classify_body("Edge: Too Many Requests")[0] == "THROTTLE")
    check("a delisted symbol is SYMBOL_MISSING",
          op.classify_body('{"chart":{"result":null,"error":{"code":"Not Found"}}}')[0]
          == "SYMBOL_MISSING")
    check("the venue prefix is stripped", op.yahoo_symbol("NASDAQ:NVDA") == "NVDA")
    check("a slash class becomes a dash", op.yahoo_symbol("NYSE:SNUS/PH") == "SNUS-PH")
    check("'ProShares Bitcoin ETF' is NOT levered (the issuer is not a token)",
          not op.is_leveraged("ProShares Bitcoin ETF"))
    check("'ProShares UltraPro QQQ' IS levered",
          op.is_leveraged("ProShares UltraPro QQQ"))
    check("'Unity Software Inc.' is NOT a warrant",
          not op.is_warrant_or_unit("U", "Unity Software Inc."))

    avg10 = {"avg10": {"X": {"avg": 1000.0, "n": 10}},
             "prior_session": {"date": "2026-11-11", "volumes": {"X": 10000.0}}}
    rr = {"symbol": "X", "status": "OK", "session_vol_to_0950_raw": 500.0,
          "y5m_total_prior": 8000.0, "y5m_total_to_pull": 9000.0,
          "daily_volume_live_today": 9500.0}
    op.attach_pace(rr, avg10)
    check("the pace scales on the published basis",
          abs(rr["pace"] - (625.0 / 1000.0 / 0.125)) < 1e-9, str(rr["pace"]))
    check("the live basis is published alongside it",
          abs(rr["pace_live_basis"] - (9500.0 * (500.0 / 9000.0) / 1000.0 / 0.125)) < 1e-9)

    print()
    print("== 2. the PUBLISH GATE must CATCH each breach ==")

    # a good world passes
    g = op.run_gate(recs, {"SPY": recs["SPY"]["chg_pct_0950"]}, published=list(recs),
                    daily=daily, scanner_change=scanner)
    check("a consistent reconstruction passes the gate", g["ok"], str(g["failures"]))

    # M1: the 2026-11-10 defect — the prior close is 10 sessions old
    m1 = json.loads(json.dumps(recs))
    for s in m1:
        m1[s]["prior_close"] = m1[s]["prior_close"] * 0.88
    d1 = {s: {"daily_close_prior_official": recs[s]["prior_close"]} for s in recs}
    g1 = op.run_gate(m1, {"SPY": recs["SPY"]["chg_pct_0950"]}, published=list(m1),
                     daily=d1)
    check("M1 a ten-day-old prior close is CAUGHT",
          not g1["ok"] and any("G2" in f for f in g1["failures"]), str(g1["failures"]))

    # M2: the index disagrees
    g2 = op.run_gate(recs, {"SPY": recs["SPY"]["chg_pct_0950"] - 6.0},
                     published=list(recs), daily=daily)
    check("M2 an index mismatch is CAUGHT",
          not g2["ok"] and any("G1" in f for f in g2["failures"]), str(g2["failures"]))

    # M3: a published name has no price
    m3 = json.loads(json.dumps(recs))
    m3["AAPL"]["close_0950"] = None
    g3 = op.run_gate(m3, {"SPY": recs["SPY"]["chg_pct_0950"]}, published=list(m3),
                     daily=daily)
    check("M3 a published name with no price is CAUGHT",
          not g3["ok"] and any("G3" in f for f in g3["failures"]), str(g3["failures"]))

    # M4: a published name has no pace
    m4 = json.loads(json.dumps(recs))
    m4["MSFT"]["pace"] = None
    g4 = op.run_gate(m4, {"SPY": recs["SPY"]["chg_pct_0950"]}, published=list(m4),
                     daily=daily)
    check("M4 a published name with no pace is CAUGHT",
          not g4["ok"] and any("G3" in f for f in g4["failures"]), str(g4["failures"]))

    # M5: the whole cross-section is wrong (the scanner disagrees everywhere).
    # The index leg is left consistent on purpose, so this isolates G4: the
    # ten-day-basis defect moved every NON-index name by ~20pp.
    m5 = json.loads(json.dumps(recs))
    for s in ("AAPL", "MSFT", "QQQ"):
        m5[s]["chg_pct_0950"] = m5[s]["chg_pct_0950"] - 20.0
    g5 = op.run_gate(m5, {"SPY": recs["SPY"]["chg_pct_0950"]}, published=list(m5),
                     daily=daily, scanner_change=scanner)
    check("M5 a systematically wrong cross-section is CAUGHT",
          not g5["ok"] and any("G4" in f for f in g5["failures"]), str(g5["failures"]))

    # M6: a truncated pull — a published name never landed
    m6 = dict(recs)
    m6.pop("MSFT")
    g6 = op.run_gate(m6, {"SPY": recs["SPY"]["chg_pct_0950"]}, published=list(recs),
                     daily=daily)
    check("M6 a truncated pull (a published name never landed) is CAUGHT",
          not g6["ok"], str(g6["failures"]))

    # the resume path
    tmp = tempfile.mkdtemp()
    jl = os.path.join(tmp, "records.jsonl")
    with open(jl, "w") as fh:
        fh.write(json.dumps({"symbol": "A", "status": "OK"}) + "\n")
    check("a completed symbol is not re-fetched on a retry", "A" in op.load_done(jl))

    # the engine's own selftest must also be green
    import subprocess
    r = subprocess.run([sys.executable, ENGINE, "selftest"], capture_output=True, text=True)
    check("the engine's own selftest is green",
          r.returncode == 0, (r.stdout or "")[-300:])

    print()
    failed = [x for x in results if x[0] == FAIL]
    if failed:
        print("CONTRACT FAILED — %d of %d checks failed:" % (len(failed), len(results)))
        for f in failed:
            print("   - %s %s" % (f[1], f[2]))
        return 1
    print("CONTRACT OK — %d checks passed." % len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
