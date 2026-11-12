#!/usr/bin/env python3
"""Fault-injection test for the cron #20 settle contract (EOD_SETTLE_V1).

A checker that has never been observed FAILING is a claim, not a check. This test builds a
minimal valid artifact, proves the checker passes it, then injects each settle defect in
turn and proves the checker rejects it with the right message.

  python3 tools/test_eod_settle_contract.py

Exit code 0 = every case behaved as expected.
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CHECKER = os.path.join(REPO, "tools", "check_eod_artifact.py")

COLUMNS = [
    "date", "ticker", "name", "open", "high", "low", "close", "volume", "change_pct",
    "market_cap", "pe_ratio", "sector", "currency", "exchange",
    "rel_volume", "pct_from_52w_high", "pct_from_52w_low", "sma_20", "sma_50", "sma_200",
    "pct_vs_sma_50", "pct_vs_sma_200", "atr_14", "atr_pct", "gap_pct",
    "avg_daily_dollar_volume", "float_shares", "market_cap_usd", "cap_source_symbol",
    "data_quality", "settle_status", "settle_round",
]

SAMPLE = [
    {"date": "2026-11-11", "ticker": "AAPL", "name": "Apple Inc", "open": "350",
     "high": "356", "low": "349", "close": "355.6", "volume": "28000802",
     "change_pct": "1.259", "market_cap": "5064611069952", "pe_ratio": "38.81",
     "sector": "Information Technology", "currency": "USD", "exchange": "NASDAQ",
     "rel_volume": "0.6209", "pct_from_52w_high": "-1.541", "pct_from_52w_low": "66.29",
     "sma_20": "340.2", "sma_50": "330.4", "sma_200": "290.1", "pct_vs_sma_50": "7.63",
     "pct_vs_sma_200": "22.58", "atr_14": "5.76", "atr_pct": "1.62", "gap_pct": "1.71",
     "avg_daily_dollar_volume": "369805691", "float_shares": "14569078010",
     "market_cap_usd": "5064611069952", "cap_source_symbol": "AAPL", "data_quality": "OK",
     "settle_status": "CONFIRMED", "settle_round": "0"},
    {"date": "2026-11-11", "ticker": "ZZZZ", "name": "Zzzz Corp", "open": "", "high": "",
     "low": "", "close": "", "volume": "", "change_pct": "", "market_cap": "",
     "pe_ratio": "", "sector": "Materials", "currency": "USD", "exchange": "NASDAQ",
     "rel_volume": "", "pct_from_52w_high": "", "pct_from_52w_low": "", "sma_20": "",
     "sma_50": "", "sma_200": "", "pct_vs_sma_50": "", "pct_vs_sma_200": "", "atr_14": "",
     "atr_pct": "", "gap_pct": "", "avg_daily_dollar_volume": "", "float_shares": "",
     "market_cap_usd": "", "cap_source_symbol": "", "data_quality": "NO_HISTORY|NO_CAP",
     "settle_status": "NO_BAR", "settle_round": "4"},
]


def build_md(rows) -> str:
    counts = {"CONFIRMED": 0, "UNCONFIRMED": 0, "NO_BAR": 0}
    for r in rows:
        counts[r["settle_status"]] = counts.get(r["settle_status"], 0) + 1
    return "\n".join([
        "# EOD US market snapshot — 2026-11-11",
        "",
        "## TL;DR",
        "",
        "- one",
        "- two",
        "- three",
        "",
        "## Coverage",
        "",
        "| Column | Rows populated | Basis |",
        "|---|---|---|",
        "| `close` | 1 | settled |",
        "",
        "Rows: **2**. Settled closes: **1**.",
        "",
        f"**Settle evidence:** {counts['CONFIRMED']} of {len(rows)} rows are `CONFIRMED` - "
        f"their close was matched against an INDEPENDENT reading; {counts['UNCONFIRMED']} are "
        f"`UNCONFIRMED` and {counts['NO_BAR']} carry no session bar at all. The deepest probe "
        f"round was 4.",
        "",
        "### Data-quality flags (per row, `data_quality`)",
        "",
        "| Flag | Rows | Meaning |",
        "|---|---|---|",
        "| `OK` | 1 | none |",
        "",
        "## Market read",
        "",
        "| Index | Proxy | Close | Change |",
        "|---|---|---|---|",
        "| S&P 500 | SPY | 759.84 | -0.37% |",
        "| Nasdaq 100 | QQQ | 690.38 | -0.68% |",
        "| Russell 2000 | IWM | 283.05 | -0.68% |",
        "| Dow 30 | DIA | 524.42 | -0.31% |",
        "| Equal 500 | RSP | 222.67 | -0.03% |",
        "| Mid 400 | IWM | 283.05 | -0.68% |",
        "",
        "## Source health",
        "",
        "| Source | Use | Status |",
        "|---|---|---|",
        "| shibui | universe | ok |",
        "",
        "## Method & caveats",
        "",
        "- **Market-cap currency**: `market_cap` is **USD**.",
        "- **Conversion direction**: none — no FX conversion is applied to this file.",
        "",
    ])


def write_artifact(tmp, rows, md=None):
    csv_path = os.path.join(tmp, "a.csv")
    md_path = os.path.join(tmp, "a.md")
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})
    with open(md_path, "w") as fh:
        fh.write(md if md is not None else build_md(rows))
    return csv_path, md_path


def run_checker(csv_path, md_path):
    p = subprocess.run([sys.executable, CHECKER, "--csv", csv_path, "--md", md_path],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def main() -> int:
    failures = []
    passed = 0

    def expect(name, cond, detail=""):
        nonlocal passed
        if cond:
            passed += 1
            print(f"ok   {name}")
        else:
            failures.append(f"{name}: {detail}")
            print(f"FAIL {name}: {detail}")

    # ---- 1. the valid artifact passes
    with tempfile.TemporaryDirectory() as tmp:
        csv_path, md_path = write_artifact(tmp, [dict(r) for r in SAMPLE])
        rc, out = run_checker(csv_path, md_path)
        expect("the valid artifact passes the checker", rc == 0, out.strip()[-400:])

    # ---- 2. an empty settle_status is rejected
    with tempfile.TemporaryDirectory() as tmp:
        rows = [dict(r) for r in SAMPLE]
        rows[0]["settle_status"] = ""
        csv_path, md_path = write_artifact(tmp, rows)
        rc, out = run_checker(csv_path, md_path)
        expect("an empty settle_status is rejected", rc == 1 and "settle_status" in out,
               out.strip()[-400:])

    # ---- 3. an off-vocabulary settle_status is rejected
    with tempfile.TemporaryDirectory() as tmp:
        rows = [dict(r) for r in SAMPLE]
        rows[0]["settle_status"] = "PROBABLY_FINE"
        csv_path, md_path = write_artifact(tmp, rows)
        rc, out = run_checker(csv_path, md_path)
        expect("an off-vocabulary settle_status is rejected",
               rc == 1 and "closed vocabulary" in out, out.strip()[-400:])

    # ---- 4. a NO_BAR row that carries a close is rejected
    with tempfile.TemporaryDirectory() as tmp:
        rows = [dict(r) for r in SAMPLE]
        rows[1]["settle_status"] = "NO_BAR"
        rows[1]["close"] = "12.34"
        rows[1]["high"] = "13"
        rows[1]["low"] = "12"
        csv_path, md_path = write_artifact(tmp, rows)
        rc, out = run_checker(csv_path, md_path)
        expect("a NO_BAR row carrying a close is rejected",
               rc == 1 and "NO_BAR" in out, out.strip()[-400:])

    # ---- 5. a non-integer settle_round is rejected
    with tempfile.TemporaryDirectory() as tmp:
        rows = [dict(r) for r in SAMPLE]
        rows[0]["settle_round"] = "round-3"
        csv_path, md_path = write_artifact(tmp, rows)
        rc, out = run_checker(csv_path, md_path)
        expect("a non-integer settle_round is rejected",
               rc == 1 and "settle_round" in out, out.strip()[-400:])

    # ---- 6. a report whose settle counts disagree with the CSV is rejected
    with tempfile.TemporaryDirectory() as tmp:
        rows = [dict(r) for r in SAMPLE]
        md = build_md(rows).replace("1 of 2 rows are `CONFIRMED`", "2 of 2 rows are `CONFIRMED`")
        csv_path, md_path = write_artifact(tmp, rows, md=md)
        rc, out = run_checker(csv_path, md_path)
        expect("a report whose settle counts disagree with the CSV is rejected",
               rc == 1 and "settle evidence" in out, out.strip()[-400:])

    # ---- 7. a report with no settle evidence at all is rejected
    with tempfile.TemporaryDirectory() as tmp:
        rows = [dict(r) for r in SAMPLE]
        md = "\n".join(ln for ln in build_md(rows).splitlines()
                       if "Settle evidence" not in ln)
        csv_path, md_path = write_artifact(tmp, rows, md=md)
        rc, out = run_checker(csv_path, md_path)
        expect("a report with no settle evidence is rejected",
               rc == 1 and "settle evidence" in out, out.strip()[-400:])

    # ---- 8. the checker itself must be present and runnable
    expect("the checker is present", os.path.exists(CHECKER), CHECKER)

    print(f"\n{passed} cases passed, {len(failures)} failed")
    for f in failures:
        print("  " + f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
