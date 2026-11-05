#!/usr/bin/env python3
"""
test_premarket_contract.py — prove the cron #08 artifact contract is satisfiable AND
that the checker actually catches a breach.

Why
---
A checker that only ever fails is a checker nobody trusts, and a contract nobody can
satisfy is a contract that gets skipped. This test does both:

  1. builds a synthetic pre-market session (the shape of 2026-11-03: PURR straddling
     the bar, a clean flag, a 10-share phantom, a high-quality setup that went nowhere,
     a name with no print at all),
  2. runs `premarket_pull.py` over it with the network layer stubbed,
  3. renders a contract-shaped artifact from the CSV it produced,
  4. runs `check_premarket_artifact.py` and requires exit 0,
  5. then MUTATES that artifact five different ways and requires the checker to fail
     each time.

USAGE
    python3 tools/test_premarket_contract.py
Exit codes: 0 = all good; 1 = a breach was not caught (or a contract cannot be met).
"""

import csv
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PP_PATH = ROOT / "cloud-prompts" / "skills" / "stock-screener-suite" / "scripts" / "premarket_pull.py"
CK_PATH = ROOT / "tools" / "check_premarket_artifact.py"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pp = _load(PP_PATH, "pp")
ck = _load(CK_PATH, "ck")

# ----------------------------------------------------------------------------------
# the synthetic session
# ----------------------------------------------------------------------------------
# ticker -> (ref_close, tape_last, exec_shares, pm_volume, quote, bid, ask,
#            pm_high, pm_low, stylists, origins)
SESSION = {
    "PURR": (9.71, 10.0083, 5000, 595761, 10.14, 10.04, 10.14, 10.28, 9.58, 3,
             "B_stockbee_ep9m;E_qullamaggie_5d_gainers;G_peoplewish"),
    "ZLTO": (40.0, 42.08, 4000, 300000, 42.08, 42.05, 42.10, 42.30, 39.80, 2,
             "A_stockbee_4pct;G_peoplewish"),
    "CAI": (32.10, 33.8747, 10, 20267, 33.8747, 31.70, 33.90, 32.65, 31.90, 3,
            "C_qullamaggie_rs;G_peoplewish;H_hernandez_sector_leader"),
    "CDNA": (85.88, 86.65, 300, 3350, 86.12, 86.10, 87.60, 86.41, 85.75, 3,
             "A_stockbee_4pct;C_qullamaggie_rs;D_qullamaggie_ep;E_qullamaggie_5d_gainers;"
             "G_peoplewish"),
    "KOD": (97.625, 98.5764, 200, 6739, 98.19, 97.64, 98.74, 98.35, 97.54, 3,
            "C_qullamaggie_rs;G_peoplewish;H_hernandez_sector_leader"),
    "HTFL": (54.49, 54.15, 150, 3526, 54.46, 54.45, 55.49, 55.05, 53.60, 3,
             "C_qullamaggie_rs;G_peoplewish;H_hernandez_sector_leader"),
    "NOPR": (25.0, None, 0, 0, 26.5, 25.1, 26.6, None, None, 1, "G_peoplewish"),
}


def _stub_network():
    def fake_best_tape(sym, pulls):
        ref, last, exec_shares, vol, quote, bid, ask, hi, lo, _st, _or = SESSION[sym]
        if last is None:
            return {"prints": [], "newest": None, "consol_raw": None, "consol_price": None,
                    "consol_pct": None, "counter_vol": None, "pm_high": None, "pm_low": None,
                    "tape_rows": 0, "cache_hit": None, "updated": None}, []
        prints = [{"time": "08:45:00", "minutes": 525, "price": last, "vol": vol - exec_shares},
                  {"time": "09:12:00", "minutes": 552, "price": last, "vol": exec_shares}]
        return {"prints": prints, "newest": prints[-1],
                "consol_raw": "$%s 0.0000 (0.00%%)" % last, "consol_price": last,
                "consol_pct": 0.0, "counter_vol": vol,
                "pm_high": "$%s (09:02:00 AM)" % hi if hi else None,
                "pm_low": "$%s (08:31:00 AM)" % lo if lo else None,
                "tape_rows": len(prints), "cache_hit": "MISS", "updated": None}, [prints[-1]]

    def fake_info(sym):
        ref, last, exec_shares, vol, quote, bid, ask, hi, lo, _st, _or = SESSION[sym]
        return {"price": quote, "pct": round((quote / ref - 1) * 100, 2), "ts": "Nov 05, 2026 9:12 AM ET",
                "ts_minutes": 552, "bid": bid, "ask": ask, "secondary_close": ref,
                "market_status": "Pre-Market", "asset_class": "stocks"}

    def fake_cboe(sym):
        ref = SESSION[sym][0]
        return {"price": SESSION[sym][4], "close": ref, "prev_day_close": ref, "volume": 1,
                "last_trade_time": "09:12:00", "timestamp": "2026-11-05T14:12:22Z"}

    def fake_tv(symbols):
        out = {}
        for s in symbols:
            ref = SESSION[s][0]
            out[s] = {"close": ref, "premarket_change": round((SESSION[s][4] / ref - 1) * 100, 2),
                      "premarket_high": SESSION[s][7], "premarket_low": SESSION[s][8],
                      "premarket_volume": int((SESSION[s][3] or 0) * 0.5), "description": s}
        return out

    pp._best_tape = fake_best_tape
    pp._fetch_info = fake_info
    pp._fetch_cboe = fake_cboe
    pp._fetch_tv = fake_tv


def _write_focus_csv(path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ticker", "stylists", "origins", "close_2026-11-04", "chg_pct_2026-11-04",
                    "close_2026-11-05", "chg_pct_2026-11-05", "rvol_2026-11-05", "flags"])
        for sym, row in SESSION.items():
            w.writerow([sym, row[9], row[10], 1.0, 1.0, row[0], 1.0, 1.0, ""])


def _render_artifact(csv_path, md_path, reply_path):
    """Render a minimal artifact that satisfies the contract, from the CSV."""
    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    flagged = [r for r in rows if r["verdict"] == "FLAGGED"]
    nonflag = [r for r in rows if r["verdict"] != "FLAGGED"]

    def rank(r):
        st = float(r["stylists"] or 0)
        og = len([o for o in (r["origins"] or "").split(";") if o])
        g = abs(float(r["pm_gap_pct"] or 0))
        return (-st, -og, -g, r["ticker"])

    nonflag.sort(key=rank)

    md = []
    md.append("# Pre-Market Gapper — Thursday, 05 November 2026")
    md.append("")
    md.append("**Session:** Thursday 2026-11-05 pre-market. **Cron:** #08 "
              "`stock-screener-pre-market-gapper` (08:30 ET; one snapshot at 09:12 ET).")
    md.append("**Source of record:** Nasdaq public quote API; cross-checked against TradingView "
              "and Cboe.")
    md.append("")
    md.append("_contract: %s · flagged: %d · scanned: %d · gate: |gap|>=4.0%% and "
              "pm_volume>=50,000 and exec_shares>=25 · reference close: prior sweep focus.csv_"
              % (ck.CONTRACT_VERSION, len(flagged), len(rows)))
    md.append("")
    md.append("## TL;DR")
    md.append("")
    md.append("- %d of %d Focus names cleared the gate (|gap|>=4%%, pre-market volume>=50,000 "
              "shares, executed print>=25 shares)." % (len(flagged), len(rows)))
    md.append("- The most consequential name is the only FLAGGED one; the rest of the list did "
              "not move.")
    md.append("- The quote is not always a market: one name cleared the bar on a live quote and "
              "not on the executed tape.")
    md.append("")
    md.append("## Focus scan — all names")
    md.append("")
    md.append("| Ticker | Ref close | PM price (last executed print) | Gap % | PM volume | "
              "Exec shares | Exec notional | PM high | PM low | Quote % | Verdict |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        md.append("| %s | %s | %s | %s%% | %s | %s | %s | %s | %s | %s%% | %s |" % (
            r["ticker"], r["ref_close"], r["pm_price"], r["pm_gap_pct"], r["pm_volume"],
            r["exec_shares"], r["exec_notional"], r["pm_high"], r["pm_low"],
            r["quote_gap_pct"], r["verdict"]))
    md.append("")
    md.append("## Focus names that did not qualify")
    md.append("")
    for r in nonflag:
        md.append("- **%s** — %s%% · %s shares · %s–%s · %s stylists, %s origins (%s) · "
                  "setup: good setup that went nowhere — it never moved." % (
                      r["ticker"], r["pm_gap_pct"], r["pm_volume"], r["pm_low"], r["pm_high"],
                      r["stylists"], len([o for o in (r["origins"] or "").split(";") if o]),
                      ", ".join(o for o in (r["origins"] or "").split(";") if o)))
    md.append("")
    md.append("## Flags")
    md.append("")
    for r in rows:
        es = float(r["exec_shares"] or 0)
        g = abs(float(r["pm_gap_pct"] or 0))
        if es < ck.MIN_EXECUTED_SHARES and g >= ck.GAP_TRIGGER_PCT:
            md.append("- **%s** %s%% on %s executed shares = a quote, not a market." % (
                r["ticker"], r["pm_gap_pct"], r["exec_shares"]))
    md.append("")
    md.append("## Method, source health & caveats")
    md.append("")
    md.append("- Reference close: the prior sweep's own `focus.csv` (latest dated `close_<date>` "
              "column), cross-checked against TradingView and Cboe; all three agreed.")
    md.append("- The published gap is the consolidated tape's last executed print; the live "
              "quote is published separately as `quote_gap_pct`.")
    md.append("- Nasdaq `/info` `secondaryData` was not used as the denominator — it drifts "
              "and flips intraday.")
    md.append("")
    Path(md_path).write_text("\n".join(md), encoding="utf-8")

    reply = []
    reply.append("Pre-market gapper: %d of %d Focus names cleared the gate." % (len(flagged),
                                                                               len(rows)))
    reply.append("")
    reply.append("### Signal")
    for r in flagged:
        reply.append("- %s %s%% — cleared the gate on %s executed shares." % (
            r["ticker"], r["pm_gap_pct"], r["exec_shares"]))
    for r in nonflag[:2]:
        reply.append("- %s %s%% — good setup (%s origins) that went nowhere." % (
            r["ticker"], r["pm_gap_pct"],
            len([o for o in (r["origins"] or "").split(";") if o])))
    reply.append("")
    reply.append("### Method & caveats")
    reply.append("- Nasdaq public quote API, cross-checked against TradingView and Cboe.")
    reply.append("")
    reply.append("### Files")
    reply.append("- %s" % md_path)
    reply.append("")
    reply.append("### Push / errors")
    reply.append("push: ok (verified)")
    reply.append("errors: 0")
    Path(reply_path).write_text("\n".join(reply), encoding="utf-8")


def _run_checker(md, csv_path, reply):
    proc = subprocess.run([sys.executable, str(CK_PATH), "--md", str(md), "--csv", str(csv_path),
                           "--reply", str(reply)], capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def main():
    failures = []

    def expect(name, cond, detail=""):
        if cond:
            print("  ok   %s" % name)
        else:
            print("  FAIL %s %s" % (name, detail))
            failures.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="premarket-contract-"))
    focus = tmp / "focus.csv"
    _write_focus_csv(focus)

    print("[setup] synthetic session")
    _stub_network()
    rc = pp.main(["--from-csv", str(focus), "--out-dir", str(tmp), "--pulls", "4",
                  "--quiet"])
    expect("the helper ran", rc == 0, "rc=%s" % rc)
    csv_path = tmp / "pre-market-gapper.csv"
    expect("the helper wrote the contract CSV", csv_path.exists())
    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    expect("one row per Focus name", len(rows) == len(SESSION),
           "%d != %d" % (len(rows), len(SESSION)))
    verdicts = {r["ticker"]: r["verdict"] for r in rows}
    expect("PURR is BORDERLINE_TAPE_ONLY", verdicts.get("PURR") == "BORDERLINE_TAPE_ONLY",
           str(verdicts.get("PURR")))
    expect("ZLTO is FLAGGED", verdicts.get("ZLTO") == "FLAGGED", str(verdicts.get("ZLTO")))
    expect("CAI is BORDERLINE_THIN", verdicts.get("CAI") == "BORDERLINE_THIN",
           str(verdicts.get("CAI")))
    expect("NOPR is NO_PRINT", verdicts.get("NOPR") == "NO_PRINT", str(verdicts.get("NOPR")))
    expect("CDNA is BELOW", verdicts.get("CDNA") == "BELOW", str(verdicts.get("CDNA")))
    for r in rows:
        for col in ("verdict", "exec_shares", "ref_close_source"):
            if not str(r.get(col, "")).strip():
                failures.append("column %s empty on %s" % (col, r["ticker"]))
    expect("every row carries verdict / exec_shares / ref_close_source",
           not [f for f in failures if "column" in f])

    md = tmp / "pre-market-gapper.md"
    reply = tmp / "reply.txt"
    _render_artifact(csv_path, md, reply)

    print("[check] a contract-shaped artifact must PASS")
    rc, out = _run_checker(md, csv_path, reply)
    expect("the checker passes a conforming artifact", rc == 0, out[-2000:])
    if rc != 0:
        print(out)

    print("[check] each breach must FAIL")
    # (a) a name below the size floor counted as a flag
    rows_b = [dict(r) for r in rows]
    for r in rows_b:
        if r["ticker"] == "CAI":
            r["verdict"] = "FLAGGED"
    bad_csv = tmp / "bad_flag.csv"
    with open(bad_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows_b)
    rc, out = _run_checker(md, bad_csv, reply)
    expect("a thin print counted as FLAGGED is caught", rc == 1, out[-400:])

    # (b) a non-qualifying name dropped from the section
    md_b = tmp / "bad_section.md"
    text = "\n".join(ln for ln in md.read_text(encoding="utf-8").split("\n")
                     if not ln.startswith("- **CDNA**"))
    md_b.write_text(text, encoding="utf-8")
    rc, out = _run_checker(md_b, csv_path, reply)
    expect("a non-qualifying name missing from the section is caught", rc == 1, out[-400:])

    # (c) a thin print missing from Flags
    md_c = tmp / "bad_flags.md"
    text = md.read_text(encoding="utf-8")
    text = "\n".join(ln for ln in text.split("\n")
                     if not (ln.startswith("- **CAI**") and "quote, not a market" in ln))
    md_c.write_text(text, encoding="utf-8")
    rc, out = _run_checker(md_c, csv_path, reply)
    expect("a thin print missing from Flags is caught", rc == 1, out[-400:])

    # (d) the reply missing the top 2 non-qualifying names
    reply_d = tmp / "bad_reply.txt"
    text = reply.read_text(encoding="utf-8")
    text = "\n".join(ln for ln in text.split("\n")
                     if not (ln.startswith("- CDNA") or ln.startswith("- KOD")))
    reply_d.write_text(text, encoding="utf-8")
    rc, out = _run_checker(md, csv_path, reply_d)
    expect("a reply that omits the top 2 non-qualifying names is caught", rc == 1, out[-400:])

    # (e) a required CSV column dropped
    bad_e = tmp / "bad_cols.csv"
    cols = [c for c in rows[0].keys() if c != "exec_shares"]
    with open(bad_e, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    rc, out = _run_checker(md, bad_e, reply)
    expect("a missing exec_shares column is caught", rc == 1, out[-400:])

    # (f) the contract marker removed
    md_f = tmp / "bad_marker.md"
    text = md.read_text(encoding="utf-8")
    text = "\n".join(ln for ln in text.split("\n") if "_contract:" not in ln)
    md_f.write_text(text, encoding="utf-8")
    rc, out = _run_checker(md_f, csv_path, reply)
    expect("a missing contract marker is caught", rc == 1, out[-400:])

    print()
    if failures:
        print("TEST FAILED — %d problem(s):" % len(failures))
        for f in failures:
            print("  - %s" % f)
        return 1
    print("TEST OK — the contract is satisfiable and every breach above was caught.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
