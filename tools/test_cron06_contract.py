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

MASTER_CSV = "symbol,stylists,data_date\nAAAA,jeff_sun,2026-11-06\nCCCC,stockbee,2026-11-06\n"

# an INDEPENDENT short-interest source (shares), for the cross-check
SI_XCHECK = [
    {"ticker": "AAAA", "interest_shares": 100_000_000, "short_pct_float": 30.0,
     "settlement_date": "2026-10-30", "days_to_cover": 3, "source": "independent"},
    {"ticker": "CCCC", "interest_shares": 12_000_000, "short_pct_float": 60.0,
     "settlement_date": "2026-10-30", "days_to_cover": 4, "source": "independent"},
    {"ticker": "DDDD", "interest_shares": 1_000_000, "short_pct_float": 20.0,
     "settlement_date": "2026-10-30", "days_to_cover": 2, "source": "independent"},
    {"ticker": "EEEE", "interest_shares": 300_000, "short_pct_float": 30.0,
     "settlement_date": "2026-10-30", "days_to_cover": 6, "source": "independent"},
]


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
    (d / "si_xcheck.json").write_text(json.dumps(SI_XCHECK, indent=1))


def run_engine(d: Path, count_override: dict | None = None):
    """count_override lets a fault-injection case pass a WRONG count and require the
    engine to REFUSE to publish (the truncation guard is a real gate, not a claim)."""
    counts = {"ipo": 3, "sf": 4, "scan": 3}
    counts.update(count_override or {})
    md = d / "daily-screens" / FIRE
    cmd = [sys.executable, str(ENGINE),
           "--fire-date", FIRE, "--data-date", DATA,
           "--ipo-json", str(d / "ipo.json"), "--sf-json", str(d / "sf.json"),
           "--ipo-enrich-json", str(d / "ipo_enrich.json"),
           "--sf-enrich-json", str(d / "sf_enrich.json"),
           "--scan-json", str(d / "scan.json"), "--shape-json", str(d / "shape.json"),
           "--si-crosscheck-json", str(d / "si_xcheck.json"),
           "--backlog-md", str(d / "prior_backlog.md"),
           "--prior-state", str(d / "prior_state.json"),
           "--master-csv", str(d / "master.csv"),
           "--ipo-rows-passing", str(counts["ipo"]),
           "--sf-rows-passing", str(counts["sf"]),
           "--scan-rows-passing", str(counts["scan"]),
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
           "--prior-backlog", str(d / "prior_backlog.md"),
           "--prior-state", str(d / "prior_state.json")]
    if reply:
        cmd += ["--reply", str(reply)]
    return subprocess.run(cmd, capture_output=True, text=True)


def set_cell_by_name(txt: str, row_prefix: str, column: str, value: str) -> str:
    """Replace the cell of the FIRST table row starting with row_prefix, in the
    column NAMED `column`.

    Two traps this helper exists to kill (both hit on 2026-11-19):

    * a mutator that targets a FIXED INDEX silently mutates a different field the
      moment a column is added (the cross-check's "Src %Float" shifted the short-float
      table and the C11 mutation was writing a placeholder into the market cap instead
      of the squeeze flag) — and the mutation then "passes" because the checker never
      saw the field it was supposed to break;
    * the header and the data row must be split THE SAME WAY. A leading "|" makes
      `line.split("|")` produce one more cell than `line.strip().strip("|").split("|")`,
      so a column index taken from one and applied to the other lands one cell off.
    """
    lines = txt.splitlines()
    cols = {}
    for line in lines:
        if line.startswith("|"):
            cells = [c.strip() for c in line.split("|")]
            names = [c for c in cells]
            if "#" in names and "Ticker" in names:
                cols = {name: i for i, name in enumerate(names)}
                break
    if column not in cols:
        raise AssertionError(f"the mutator cannot find the column {column!r} — "
                             "a mutation that cannot be applied must FAIL the test")
    idx = cols[column]
    out = []
    hit = False
    for line in lines:
        if (not hit) and line.startswith(row_prefix):
            cells = line.split("|")
            cells[idx] = f" {value} "
            line = "|".join(cells)
            hit = True
        out.append(line)
    if not hit:
        raise AssertionError(f"the mutator cannot find the row {row_prefix!r} — "
                             "a mutation that cannot be applied must FAIL the test")
    return "\n".join(out) + "\n"


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

        # The reply is part of the artifact set: without restoring it, the C14
        # mutation leaves a broken reply behind and EVERY LATER mutation is
        # "caught" by C14 instead of its own clause — a green run that proves
        # nothing.  Restored and unrestored with the files (2026-11-14).
        def restore():
            for f in names:
                shutil.copy(md / f, (md / f).with_suffix(".bak"))
            shutil.copy(state_file, state_file.with_suffix(".bak"))
            shutil.copy(reply, reply.with_suffix(".bak"))

        def unrestore():
            for f in names:
                shutil.move(str((md / f).with_suffix(".bak")), str(md / f))
            shutil.move(str(state_file.with_suffix(".bak")), str(state_file))
            shutil.move(str(reply.with_suffix(".bak")), str(reply))

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
            lambda: edit_md("weekly-ipo.md",
                            lambda t: set_cell_by_name(t, "| 1 | AAAA |", "Days Since IPO", "—")))

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
                            lambda t: set_cell_by_name(t, "| 1 | AAAA |", "Squeeze", "—")))

        mut("C12 the data date is not published", "C12",
            lambda: edit_md("peoplewish-backlog.md", lambda t: t.replace("data_date: 2026-11-06", "data_date: 2026-11-05")))

        mut("C13 the source-health section is missing", "C13",
            lambda: edit_md("weekly-ipo.md", lambda t: t.split("## Source health")[0]))

        mut("C14 the reply omits a newly tagged ticker", "C14",
            lambda: reply.write_text("### Signal\n\n- nothing here\n"))

        # rename the heading, not the file tail: truncating at the section would ALSO
        # remove the source-health section, and the mutation would then be "caught" by
        # C13 instead of its own clause.
        mut("C16 the short-interest cross-check section is missing", "C16",
            lambda: edit_md("weekly-high-short-float.md",
                            lambda t: t.replace("## Short-interest cross-check",
                                                "## Cross-check removed", 1)))

        def bad_gap(j):
            for r in j["short_interest_crosscheck"]["rows"]:
                if r["ticker"] == "CCCC":
                    r["pct_gap_pp"] = 99.9
        mut("C16 a cross-check percentage gap is not the recomputed one", "C16",
            lambda: edit_json(bad_gap))

        def bad_verdict(j):
            for r in j["short_interest_crosscheck"]["rows"]:
                if r["ticker"] == "CCCC":
                    r["verdict"] = "FINE"
        mut("C16 a cross-check verdict is outside the closed set", "C16",
            lambda: edit_json(bad_verdict))

        def blank_delta(j):
            for r in j["short_float_rows"]:
                r["short_float_delta_pp"] = "NO_PRIOR_SNAPSHOT"
        mut("C15 the week-over-week short-float delta is silently empty", "C15",
            lambda: edit_json(blank_delta))

        # ---- 3. the ENGINE refuses a truncated branch ----------------------------
        # The truncation guard is only a gate if it can fail: the count comes from a
        # SEPARATE COUNT(*) query, so passing a wrong count must stop the engine.
        bad_dir = tmp / "bad"
        bad_dir.mkdir(exist_ok=True)
        cmd = [sys.executable, str(ENGINE),
               "--fire-date", FIRE, "--data-date", DATA,
               "--ipo-json", str(tmp / "ipo.json"), "--sf-json", str(tmp / "sf.json"),
               "--ipo-enrich-json", str(tmp / "ipo_enrich.json"),
               "--sf-enrich-json", str(tmp / "sf_enrich.json"),
               "--scan-json", str(tmp / "scan.json"), "--shape-json", str(tmp / "shape.json"),
               "--si-crosscheck-json", str(tmp / "si_xcheck.json"),
               "--backlog-md", str(tmp / "prior_backlog.md"),
               "--prior-state", str(tmp / "prior_state.json"),
               "--master-csv", str(tmp / "master.csv"),
               "--ipo-rows-passing", "99", "--sf-rows-passing", "4", "--scan-rows-passing", "3",
               "--out-md-dir", str(bad_dir),
               "--out-json", str(bad_dir / "cron06-refresh.json"),
               "--out-state", str(bad_dir / "state.json")]
        rr = subprocess.run(cmd, capture_output=True, text=True)
        if rr.returncode == 0:
            print("FAIL: the engine PUBLISHED an artifact whose screen count did not match "
                  "the collected rows — the truncation guard is vacuous")
            sys.exit(1)
        print("ok  the engine refuses to publish a truncated branch")

        # ---- 3b. the TRUNCATION case: the rows say there are more than arrived -----
        trunc_dir = tmp / "trunc"
        trunc_dir.mkdir(exist_ok=True)
        bad_rows = json.loads((tmp / "ipo.json").read_text())
        for r in bad_rows:
            r["rows_passing"] = 99
        (tmp / "ipo_trunc.json").write_text(json.dumps(bad_rows, indent=1))
        cmd2 = list(cmd)
        cmd2[cmd2.index("--ipo-json") + 1] = str(tmp / "ipo_trunc.json")
        cmd2[cmd2.index("--ipo-rows-passing") + 1] = "99"
        cmd2[cmd2.index("--out-md-dir") + 1] = str(trunc_dir)
        cmd2[cmd2.index("--out-json") + 1] = str(trunc_dir / "cron06-refresh.json")
        cmd2[cmd2.index("--out-state") + 1] = str(trunc_dir / "state.json")
        rr2 = subprocess.run(cmd2, capture_output=True, text=True)
        if rr2.returncode == 0:
            print("FAIL: the engine PUBLISHED a branch whose own count says more rows "
                  "arrived than were collected — the truncation guard is vacuous")
            sys.exit(1)
        print("ok  the engine refuses to publish a TRUNCATED branch (rows_passing > collected)")

        def cut_coverage(j):
            xc = j["short_interest_crosscheck"]
            keep = xc["rows"][:1]
            xc["rows"] = keep
            xc["crosschecked_names"] = 1
            xc["coverage_pct"] = 25.0
            xc["not_cross_checked"] = ["CCCC", "DDDD", "EEEE"]
            return keep

        def cut_md(txt):
            # scope the cut to the CROSS-CHECK table only — a blunt row-drop across the
            # whole document also empties the intersection table, and then C6 catches
            # the mutation instead of C19.
            head, sep, rest = txt.partition("## Short-interest cross-check")
            section, sep2, tail = rest.partition("\n## ")
            lines = section.splitlines()
            hdr = next((l for l in lines if l.startswith("|") and "Shibui %Float" in l), None)
            if hdr is None:
                raise AssertionError("the mutator cannot find the cross-check table")
            ti = [c.strip() for c in hdr.split("|")].index("Ticker")
            kept = []
            for line in lines:
                if line.startswith("|") and line != hdr and "---" not in line:
                    cells = [c.strip() for c in line.split("|")]
                    if len(cells) > ti and cells[ti] not in ("Ticker", "AAAA"):
                        continue
                kept.append(line)
            return head + sep + "\n".join(kept) + sep2 + tail

        mut("C19 the cross-check covers a handful of names", "C19",
            lambda: (edit_json(cut_coverage),
                      edit_md("weekly-high-short-float.md", cut_md)))

        def bad_qualifier(j):
            for r in j["backlog_live_rescore"]:
                r["ten_year_qualifier"] = "MAYBE"
                break
        mut("C17 a 10-year qualifier is outside the closed set", "C17",
            lambda: edit_json(bad_qualifier))

        mut("C18 the sweep basis date is missing", "C18",
            lambda: edit_json(lambda j: j.__setitem__("sweep_basis_data_date", "")))

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
