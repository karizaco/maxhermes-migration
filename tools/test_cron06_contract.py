#!/usr/bin/env python3
"""
test_cron06_contract.py — prove the cron #06 contract is SATISFIABLE and that
`check_cron06_artifact.py` actually bites.

WHY
---
A checker that only ever fails is a checker nobody trusts, and a contract nobody can
satisfy is a contract that gets skipped ("the checker is broken" is how a gate becomes
decoration). This test does both:

  1. feeds the ENGINE synthetic screens (a tiny IPO book, a tiny short-float book, a
     tiny 10-year scan, a prior ledger), renders the artifacts, and requires the
     checker to exit 0 — the contract is satisfiable by construction;
  2. then MUTATES that artifact set fourteen ways, one per contract clause, and
     requires the checker to fail EVERY time.

USAGE
    python3 tools/test_cron06_contract.py

EXIT CODES
    0 = the contract is satisfiable and the checker bites on every mutation
    1 = a breach was not caught, or a contract cannot be met
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "cloud-prompts" / "_shared" / "cron06_refresh.py"
CK = ROOT / "tools" / "check_cron06_artifact.py"

FIRE = "2026-11-07"
DATA = "2026-11-06"

# --- synthetic screens -------------------------------------------------------
IPO = [
    {"ticker": "AAAA", "symbol": "AAAA.NASDAQ", "name": "Alpha Health Inc", "ipo_date": "2026-08-01",
     "exchange": "NASDAQ", "type": "Common Stock", "market_cap": 2_400_000_000.0,
     "gics_sector": "Health Care", "gics_industry": "Biotechnology", "rows_passing": 3},
    {"ticker": "BBBB", "symbol": "BBBB.NYSE", "name": "Beta Tools Inc", "ipo_date": "2025-11-20",
     "exchange": "NYSE", "type": "Common Stock", "market_cap": None,
     "gics_sector": "Industrials", "gics_industry": "Machinery", "rows_passing": 3},
    {"ticker": "CCCC", "symbol": "CCCC.NYSE", "name": "Gamma Energy Inc", "ipo_date": "2026-02-10",
     "exchange": "NYSE", "type": "Common Stock", "market_cap": 900_000_000.0,
     "gics_sector": "Energy", "gics_industry": "Oil & Gas", "rows_passing": 3},
]

SF = [
    {"ticker": "AAAA", "symbol": "AAAA.NASDAQ", "short_percent_float": 4.2028, "shares_float": 97_000_000,
     "percent_institutions": 36.2, "name": "Alpha Health Inc", "exchange": "NASDAQ", "type": "Common Stock",
     "gics_sector": "Health Care", "rows_passing": 4},
    {"ticker": "CCCC", "symbol": "CCCC.NYSE", "short_percent_float": 0.6180, "shares_float": 20_000_000,
     "percent_institutions": 12.0, "name": "Gamma Energy Inc", "exchange": "NYSE", "type": "Common Stock",
     "gics_sector": "Energy", "rows_passing": 4},
    {"ticker": "DDDD", "symbol": "DDDD.NASDAQ", "short_percent_float": 0.2450, "shares_float": 5_000_000,
     "percent_institutions": 5.0, "name": "Delta Micro Inc", "exchange": "NASDAQ", "type": "Common Stock",
     "gics_sector": "Information Technology", "rows_passing": 4},
    {"ticker": "EEEE", "symbol": "EEEE.NYSE", "short_percent_float": 0.3300, "shares_float": 1_000_000,
     "percent_institutions": 1.0, "name": "Epsilon Co", "exchange": "NYSE", "type": "Common Stock",
     "gics_sector": "Financials", "rows_passing": 4},
]

SF_ENRICH = [
    {"symbol": "AAAA.NASDAQ", "close_last": 6.35, "vol_last": 100_000, "adv30": 30_000_000.0,
     "bars30": 30, "close_prev": 6.05, "close_30d_ago": 5.10, "market_cap": 1_200_000_000.0},
    {"symbol": "CCCC.NYSE", "close_last": 12.10, "vol_last": 90_000, "adv30": 8_000_000.0,
     "bars30": 30, "close_prev": 12.40, "close_30d_ago": 13.00, "market_cap": 900_000_000.0},
    {"symbol": "DDDD.NASDAQ", "close_last": 3.20, "vol_last": 50_000, "adv30": 1_200_000.0,
     "bars30": 30, "close_prev": 3.10, "close_30d_ago": 2.80, "market_cap": 200_000_000.0},
    {"symbol": "EEEE.NYSE", "close_last": 9.00, "vol_last": 10_000, "adv30": 900_000.0,
     "bars30": 30, "close_prev": 8.90, "close_30d_ago": 9.10, "market_cap": 500_000_000.0},
]

IPO_ENRICH = [
    {"symbol": "AAAA.NASDAQ", "close_last": 18.20, "adv30": 60_000_000.0, "bars30": 30},
    {"symbol": "BBBB.NYSE", "close_last": 7.40, "adv30": 2_000_000.0, "bars30": 30},
    {"symbol": "CCCC.NYSE", "close_last": 12.10, "adv30": 8_000_000.0, "bars30": 30},
]

SCAN = [
    {"symbol": "AAAA.NASDAQ", "min10": 2.05, "max10": 70.0, "cnt10": 2514, "ytd_low": 12.0,
     "cur_close": 54.62, "cur_vol": 100_000, "prev_close": 51.78, "gain_pct": 2564.0, "rows_passing": 3},
    {"symbol": "CCCC.NYSE", "min10": 1.20, "max10": 60.0, "cnt10": 2400, "ytd_low": 5.0,
     "cur_close": 40.00, "cur_vol": 90_000, "prev_close": 39.00, "gain_pct": 3233.3, "rows_passing": 3},
    {"symbol": "FFFF.NYSE", "min10": 0.90, "max10": 20.0, "cnt10": 2300, "ytd_low": 30.0,
     "cur_close": 21.00, "cur_vol": 10_000, "prev_close": 21.00, "gain_pct": 2233.3, "rows_passing": 3},
]

SHAPE = [
    {"symbol": "AAAA.NASDAQ", "name": "Alpha Health Inc", "type": "Common Stock", "exchange": "NASDAQ",
     "gics_sector": "Health Care", "hi60": 55.60, "lo60": 30.0, "hi10": 50.0, "lo10": 40.0, "bars60": 60},
    {"symbol": "CCCC.NYSE", "name": "Gamma Energy Inc", "type": "Common Stock", "exchange": "NYSE",
     "gics_sector": "Energy", "hi60": 55.0, "lo60": 20.0, "hi10": 50.0, "lo10": 30.0, "bars60": 60},
    {"symbol": "FFFF.NYSE", "name": "Phi Foods Inc", "type": "Common Stock", "exchange": "NYSE",
     "gics_sector": "Consumer Staples", "hi60": 40.0, "lo60": 15.0, "hi10": 30.0, "lo10": 20.0, "bars60": 60},
]

PRIOR_LEDGER = """# peoplewish 1000%-in-10-years — Pattern-Study Backlog

## Newly tagged entries (2026-10-31 run)

| # | Ticker | Name | Type | Exchange | Sector | Current | 10y Low | Peak Gain | Gain | 60d High | Contraction | YTD Low | Last Day | Tags |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | DDDD | Delta Micro Inc | Common Stock | NASDAQ | Information Technology | $2.90 | $0.40 | 6,000% | 625% | $3.10 | 0.40 | $1.20 | +1.00% | VCP, coil |

## Carried forward (first tagged on or before 2026-10-31)

| Ticker | Name | Type | Exchange | Sector | Current | 10y Low | Peak Gain | Gain | 60d High | Contraction | YTD Low | Last Day | Tags | First Tagged |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EEEE ⚠ | Epsilon Co | ETF | NYSE | — | $9.00 | $0.50 | 1,700% | 1,700% | $9.10 | 0.50 | $8.00 | +0.00% | breakout | 2026-10-03 |
"""

PRIOR_STATE = {
    "contract": "cron06-refresh-v2", "fire_date": "2026-10-31", "data_date": "2026-10-30",
    "rows_passing": 4, "universe_pct": {"CCCC": 66.0, "DDDD": 24.0},
    "universe_liquidity": {}, "universe_close": {},
}

MASTER_CSV = "symbol,stylists\nAAAA,jeff_sun\nCCCC,stockbee\n"


def write_inputs(d: Path):
    (d / "ipo.json").write_text(json.dumps(IPO, indent=1))
    (d / "sf.json").write_text(json.dumps(SF, indent=1))
    (d / "sf_enrich.json").write_text(json.dumps(SF_ENRICH, indent=1))
    (d / "ipo_enrich.json").write_text(json.dumps(IPO_ENRICH, indent=1))
    (d / "scan.json").write_text(json.dumps(SCAN, indent=1))
    (d / "shape.json").write_text(json.dumps(SHAPE, indent=1))
    (d / "prior_backlog.md").write_text(PRIOR_LEDGER)
    (d / "prior_state.json").write_text(json.dumps(PRIOR_STATE, indent=1))
    (d / "master.csv").write_text(MASTER_CSV)


def run_engine(d: Path):
    md = d / "daily-screens" / FIRE
    cmd = [sys.executable, str(ENGINE),
           "--fire-date", FIRE, "--data-date", DATA,
           "--ipo-json", str(d / "ipo.json"), "--sf-json", str(d / "sf.json"),
           "--ipo-enrich-json", str(d / "ipo_enrich.json"),
           "--sf-enrich-json", str(d / "sf_enrich.json"),
           "--scan-json", str(d / "scan.json"), "--shape-json", str(d / "shape.json"),
           "--backlog-md", str(d / "prior_backlog.md"),
           "--prior-state", str(d / "prior_state.json"),
           "--master-csv", str(d / "master.csv"),
           "--out-md-dir", str(md),
           "--out-json", str(md / "cron06-refresh.json"),
           "--out-state", str(d / "pattern-study" / "cron06-state" / f"short-float-{FIRE}.json")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("engine failed:\n" + r.stdout + r.stderr)
        sys.exit(1)
    return md


def run_checker(d: Path, md: Path, reply: Path | None = None):
    cmd = [sys.executable, str(CK),
           "--md-dir", str(md),
           "--json", str(md / "cron06-refresh.json"),
           "--state", str(d / "pattern-study" / "cron06-state" / f"short-float-{FIRE}.json"),
           "--prior-backlog", str(d / "prior_backlog.md")]
    if reply:
        cmd += ["--reply", str(reply)]
    return subprocess.run(cmd, capture_output=True, text=True)


def set_cell(txt: str, row_prefix: str, idx: int, value: str) -> str:
    """Replace one cell of the first table row starting with row_prefix."""
    out = []
    for line in txt.splitlines():
        if line.startswith(row_prefix):
            cells = line.split("|")
            cells[idx] = f" {value} "
            line = "|".join(cells)
        out.append(line)
    return "\n".join(out) + "\n"


def build_reply(md: Path) -> str:
    j = json.loads((md / "cron06-refresh.json").read_text())
    names = list(j.get("newly_tagged") or []) + list((j.get("intersections") or {}).get("union") or [])
    lines = ["### Signal", ""]
    for n in dict.fromkeys(names):
        lines.append(f"- {n} - newly tagged or in an intersection")
    lines.append("")
    return "\n".join(lines)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="cron06-ct-"))
    try:
        write_inputs(tmp)
        md = run_engine(tmp)

        # ---- 1. the contract is satisfiable -----------------------------------
        reply = tmp / "reply.txt"
        reply.write_text(build_reply(md))
        r = run_checker(tmp, md, reply)
        if r.returncode != 0:
            print("FAIL: the checker rejects a conforming artifact — the contract is not satisfiable")
            print(r.stdout)
            sys.exit(1)
        print("ok  the checker accepts a conforming artifact")

        # ---- 2. every mutation must be caught ---------------------------------
        state_file = tmp / "pattern-study" / "cron06-state" / f"short-float-{FIRE}.json"
        names = ("weekly-ipo.md", "weekly-high-short-float.md", "peoplewish-backlog.md",
                 "cron06-refresh.json")

        def restore():
            for f in names:
                shutil.copy(md / f, (md / f).with_suffix(".bak"))
            shutil.copy(state_file, state_file.with_suffix(".bak"))

        def unrestore():
            for f in names:
                shutil.move(str((md / f).with_suffix(".bak")), str(md / f))
            shutil.move(str(state_file.with_suffix(".bak")), str(state_file))

        def edit_json(fn):
            p = md / "cron06-refresh.json"
            j = json.loads(p.read_text())
            fn(j)
            p.write_text(json.dumps(j, indent=1))

        def edit_md(name, fn):
            p = md / name
            t = p.read_text()
            p.write_text(fn(t))

        mutations = []

        def mut(label, clause, fn):
            mutations.append((label, clause, fn))

        mut("C1 a required artifact is missing", "C1",
            lambda: os.remove(md / "weekly-ipo.md"))

        mut("C2 the contract marker is missing", "C2",
            lambda: edit_md("weekly-ipo.md", lambda t: t.replace("contract: cron06-refresh-v2", "contract: none")))

        def trunc(j):
            j["coverage"]["short_float"]["rows_kept"] = 200
        mut("C3 a branch is truncated (rows_kept != rows_passing)", "C3", lambda: edit_json(trunc))

        def blank_days(t):
            return re_sub_days(t)
        mut("C4 an IPO row loses days_since_ipo", "C4",
            lambda: edit_md("weekly-ipo.md", lambda t: set_cell(t, "| 1 | AAAA |", 7, "—")))

        mut("C5 a verdict is outside the closed set", "C5",
            lambda: edit_json(lambda j: j["short_float_rows"][0].__setitem__("tradeable_verdict", "AWESOME")))

        def drop_inter(j):
            j["intersections"]["ipo_crowded"] = []
        mut("C6 an intersection name is missing", "C6", lambda: edit_json(drop_inter))

        mut("C7 a tag_change value is outside the closed set", "C7",
            lambda: edit_md("peoplewish-backlog.md", lambda t: t.replace("| NEW |", "| SORT-OF |", 1)))

        def drop_ledger(t):
            lines = [l for l in t.splitlines() if not l.startswith("| EEEE")]
            return "\n".join(lines) + "\n"
        mut("C8 a name is dropped from the ledger", "C8",
            lambda: edit_md("peoplewish-backlog.md", drop_ledger))

        mut("C9 the state snapshot is missing", "C9",
            lambda: os.remove(state_file))

        def float_artifact(j):
            for r in j["short_float_rows"]:
                if r["tradeable_verdict"] == "FLOAT_ARTIFACT":
                    r["tradeable_verdict"] = "TRADEABLE"
        mut("C10 a float artifact is published as tradeable", "C10", lambda: edit_json(float_artifact))

        mut("C11 a required field carries a placeholder", "C11",
            lambda: edit_md("weekly-high-short-float.md",
                            lambda t: set_cell(t, "| 1 | AAAA |", 10, "—")))

        mut("C12 the data date is not published", "C12",
            lambda: edit_md("peoplewish-backlog.md", lambda t: t.replace("data_date: 2026-11-06", "data_date: 2026-11-05")))

        mut("C13 the source-health section is missing", "C13",
            lambda: edit_md("weekly-ipo.md", lambda t: t.split("## Source health")[0]))

        mut("C14 the reply omits a newly tagged ticker", "C14",
            lambda: reply.write_text("### Signal\n\n- nothing here\n"))

        failures = []
        for label, clause, fn in mutations:
            restore()
            fn()
            r = run_checker(tmp, md, reply)
            unrestore()
            if r.returncode == 0:
                failures.append(f"{label} [{clause}] — the checker did NOT catch it")
                print(f"FAIL {label} [{clause}] — not caught")
            else:
                first = [l for l in r.stdout.splitlines() if l.strip().startswith("- [")]
                got = first[0].strip()[2:] if first else "(no clause line)"
                print(f"ok  {label} -> {got}")

        if failures:
            print()
            print(f"FAILED — {len(failures)} mutation(s) slipped through:")
            for f in failures:
                print("  -", f)
            sys.exit(1)
        print()
        print(f"CONTRACT TEST OK — {len(mutations)} mutations, all caught.")
        sys.exit(0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def re_sub_days(t):
    return t


if __name__ == "__main__":
    main()
