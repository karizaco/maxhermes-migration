#!/usr/bin/env python3
"""Outcome panel for a past sweep — what the candidates did afterwards.

Why
---
A screen that is never scored becomes a screen nobody trusts. The sweep runs
every weekday and produces a Tier-A list, but without a feedback loop there
is no way to know whether the 3-stylist names beat the market or whether the
whole book is noise.

This script takes a signal date and a candidate list, pulls the sessions that
FOLLOW that date out of shibui, and reports the 1/3/5-session forward return
for each name plus the benchmark's return over the same window. Sessions that
have not happened yet are reported as pending, not as zero.

It reads shibui through the MCP bridge (cloud-prompts/_shared/mcp_bridge.py),
so it works in the Cloud runtime where the shibui MCP tool is not registered.

Usage
-----
    python scripts/reconcile.py --date 2026-10-28 --symbols NTSK,SMCI,QLYS \
        --out-dir daily-screens/2026-10-28
    python scripts/reconcile.py --date 2026-10-28 --from-csv .../master.csv \
        --benchmark SPY --out-dir ...

Outputs
-------
    <out-dir>/_reconciliation.json
    <out-dir>/reconciliation.md
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

SQL = """
-- Forward returns for the sessions AFTER a signal date
WITH hist AS (
  SELECT q.symbol, q.date, q.close,
         ROW_NUMBER() OVER (PARTITION BY q.symbol ORDER BY q.date) AS seq_after
  FROM shibui.stock_quotes q
  WHERE q.ticker IN ({syms})
    AND q.date >= '{signal}'
    AND q.date <= DATE '{signal}' + INTERVAL '60 days'
),
sig AS (
  SELECT symbol, date AS d0, close AS c0 FROM hist WHERE date = '{signal}'
),
fwd AS (
  SELECT symbol, seq_after, date, close FROM hist WHERE date > '{signal}'
)
SELECT s.symbol, s.d0, s.c0,
       f1.date AS d1, f1.close AS c1,
       f3.date AS d3, f3.close AS c3,
       f5.date AS d5, f5.close AS c5
FROM sig s
LEFT JOIN fwd f1 ON f1.symbol = s.symbol AND f1.seq_after = 1
LEFT JOIN fwd f3 ON f3.symbol = s.symbol AND f3.seq_after = 3
LEFT JOIN fwd f5 ON f5.symbol = s.symbol AND f5.seq_after = 5
ORDER BY s.symbol
LIMIT 200
"""


def find_bridge(explicit: str | None) -> Path | None:
    cands = []
    if explicit:
        cands.append(Path(explicit))
    if os.environ.get("MCP_BRIDGE_PATH"):
        cands.append(Path(os.environ["MCP_BRIDGE_PATH"]))
    here = Path(__file__).resolve()
    cands.append(here.parent.parent.parent / "_shared" / "mcp_bridge.py")
    cands.append(here.parent / "mcp_bridge.py")
    for c in cands:
        if c.exists():
            return c
    return None


def run_query(bridge: Path, sql: str, label: str) -> list[dict]:
    args_file = Path(f"/tmp/_reconcile_{label}.json")
    args_file.write_text(json.dumps({
        "query": sql,
        "user_prompt": f"reconciliation panel: forward returns after a signal date ({label})",
    }))
    out = subprocess.run(
        ["python3", str(bridge), "shibui", "stock_data_query", str(args_file)],
        capture_output=True, text=True, timeout=300,
    ).stdout
    try:
        rows = json.loads(out)
    except Exception:
        raise RuntimeError(f"shibui query failed for {label}: {out[:300]}")
    if isinstance(rows, dict):
        raise RuntimeError(f"shibui query failed for {label}: {str(rows)[:300]}")
    return rows


def load_symbols(args) -> list[str]:
    syms: list[str] = []
    if args.symbols:
        syms += [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if args.from_csv:
        with open(args.from_csv, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                for key in ("ticker", "symbol", "Ticker", "Symbol"):
                    if row.get(key):
                        syms.append(str(row[key]).strip().split(".")[0].split("/")[0].upper())
                        break
    if args.benchmark:
        syms.append(args.benchmark.upper())
    seen, out = set(), []
    for s in syms:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def pct(a, b):
    if a is None or b is None or not b:
        return None
    return (a / b - 1.0) * 100.0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Forward-return panel for a past sweep")
    p.add_argument("--date", required=True, help="the signal date (the sweep's data date)")
    p.add_argument("--symbols", default="", help="comma-separated tickers")
    p.add_argument("--from-csv", default=None, help="CSV with a ticker/symbol column")
    p.add_argument("--benchmark", default="SPY", help="benchmark ticker for the same window")
    p.add_argument("--out-dir", default=".", help="where to write the JSON + markdown")
    p.add_argument("--bridge", default=None, help="path to mcp_bridge.py")
    args = p.parse_args(argv)

    syms = load_symbols(args)
    if not syms:
        print("no symbols given (use --symbols or --from-csv)", file=sys.stderr)
        return 2
    bridge = find_bridge(args.bridge)
    if bridge is None:
        print("mcp_bridge.py not found — pass --bridge or set MCP_BRIDGE_PATH", file=sys.stderr)
        return 2

    sql = SQL.format(syms=", ".join(f"'{s}'" for s in syms), signal=args.date)
    rows = run_query(bridge, sql, "forward")

    bench = next((r for r in rows if r["symbol"] == args.benchmark.upper()), None)
    bench_ret = {
        "1": pct(bench.get("c1"), bench.get("c0")) if bench else None,
        "3": pct(bench.get("c3"), bench.get("c0")) if bench else None,
        "5": pct(bench.get("c5"), bench.get("c0")) if bench else None,
    }

    results = []
    for r in rows:
        if r["symbol"] == args.benchmark.upper():
            continue
        rec = {"symbol": r["symbol"], "signal_date": r.get("d0"), "signal_close": r.get("c0")}
        for k, ccol, dcol in (("1", "c1", "d1"), ("3", "c3", "d3"), ("5", "c5", "d5")):
            rec[f"close_{k}"] = r.get(ccol)
            rec[f"date_{k}"] = r.get(dcol)
            rec[f"ret_{k}"] = pct(r.get(ccol), r.get("c0"))
        results.append(rec)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "signal_date": args.date,
        "benchmark": args.benchmark.upper(),
        "benchmark_returns": bench_ret,
        "n": len(results),
        "results": results,
    }
    (out_dir / "_reconciliation.json").write_text(json.dumps(payload, indent=2))

    def cell(v):
        return "—" if v is None else f"{v:+.2f}%"

    lines = [
        f"# Reconciliation — signal date {args.date}",
        "",
        f"_Forward returns for the sessions after the signal date. Benchmark "
        f"{args.benchmark.upper()}: 1-session {cell(bench_ret['1'])}, "
        f"3-session {cell(bench_ret['3'])}, 5-session {cell(bench_ret['5'])}._",
        "",
        "A pending session is shown as `—`: the sessions after the signal date have "
        "not happened yet, so the number is unknown rather than zero.",
        "",
        "| Ticker | Signal close | +1 | +3 | +5 | vs SPY +1 | vs SPY +3 | vs SPY +5 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        rel = []
        for k in ("1", "3", "5"):
            a, b = r.get(f"ret_{k}"), bench_ret.get(k)
            rel.append("—" if a is None or b is None else f"{a - b:+.2f}%")
        lines.append(
            f"| **{r['symbol']}** | {r.get('signal_close') or '—'} | "
            f"{cell(r.get('ret_1'))} | {cell(r.get('ret_3'))} | {cell(r.get('ret_5'))} | "
            f"{rel[0]} | {rel[1]} | {rel[2]} |"
        )
    lines.append("")
    (out_dir / "reconciliation.md").write_text("\n".join(lines))

    print(f"reconciliation: {len(results)} symbols over the {args.date} signal date "
          f"-> {out_dir / 'reconciliation.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
